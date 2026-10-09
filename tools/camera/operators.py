
import bpy

from math import pi
from mathutils import Vector
from bpy.props import EnumProperty, PointerProperty
from bpy.types import Operator, PropertyGroup

try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    def _fallback_register(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _fallback_unregister(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(
        PANEL_CATEGORY="木风工具箱",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

SCENE_PROP = "mf_cam"
MARK_AUTO_TARGET = "mf_auto_target"

FINISHED, CANCELLED = 'FINISHED', 'CANCELLED'


def active_collection(ctx):
    layer = getattr(ctx.view_layer, "active_layer_collection", None)
    return layer.collection if layer is not None else ctx.scene.collection


def pick_camera(ctx):
    obj = getattr(ctx, "active_object", None)
    if obj is not None and obj.type == 'CAMERA':
        return obj
    return ctx.scene.camera


def find_track(cam):
    if cam is None or cam.type not in {'CAMERA', 'LIGHT'}:
        return None
    for c in cam.constraints:
        if c.type == 'TRACK_TO' and c.enabled and c.influence > 0:
            return c
    return None


def focus(ctx, obj):
    for o in ctx.selected_objects:
        o.select_set(False)
    if obj is not None:
        obj.select_set(True)
    ctx.view_layer.objects.active = obj


def place(obj, world_pos):
    if obj.parent:
        obj.location = obj.parent.matrix_world.inverted() @ world_pos
    else:
        obj.location = world_pos


def ahead_of(cam, distance):
    return cam.matrix_world @ Vector((0.0, 0.0, -distance))


def is_owned_dot(obj):
    return obj is not None and obj.type == 'EMPTY' and bool(obj.get(MARK_AUTO_TARGET))


def is_claimed(obj):
    if obj is None:
        return False
    if obj.children:
        return True
    for other in bpy.data.objects:
        for c in other.constraints:
            if c.target is obj:
                return True
    for cam_data in bpy.data.cameras:
        if cam_data.dof.focus_object is obj:
            return True
    return False


def sweep_dots():
    doomed = [o for o in bpy.data.objects if is_owned_dot(o) and not is_claimed(o)]
    for o in doomed:
        bpy.data.objects.remove(o, do_unlink=True)
    return len(doomed)


def aim_at(cam, target):
    c = cam.constraints.new('TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    return c


def dot_distance(cam):
    c = find_track(cam)
    if c is None or c.target is None:
        return None
    return (c.target.matrix_world.to_translation() - cam.matrix_world.to_translation()).length


def attach_dot(ctx, cam):
    ctx.view_layer.update()
    size = cam.data.display_size
    dot = bpy.data.objects.new(cam.name + "_target", None)
    dot.empty_display_type = 'SPHERE'
    dot.show_axis = True
    dot.empty_display_size = size / 10.0
    dot[MARK_AUTO_TARGET] = 1
    home = cam.users_collection[0] if cam.users_collection else active_collection(ctx)
    home.objects.link(dot)
    place(dot, ahead_of(cam, size * 3.0))
    aim_at(cam, dot)
    ctx.view_layer.update()
    return dot


def core_add(ctx, want_target):
    data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", data)
    cam.rotation_mode = 'XYZ'
    cam.rotation_euler = (pi / 2.0, 0.0, 0.0)
    cam.location = ctx.scene.cursor.location.copy()
    active_collection(ctx).objects.link(cam)

    if want_target:
        attach_dot(ctx, cam)

    if ctx.scene.camera is None:
        ctx.scene.camera = cam

    focus(ctx, cam)
    kind = "目标相机" if want_target else "自由相机"
    return FINISHED, "已创建%s %s" % (kind, cam.name)


def core_target(ctx):
    cam = pick_camera(ctx)
    if cam is None or cam.type != 'CAMERA':
        return CANCELLED, "请先选中一个相机"
    if find_track(cam) is not None:
        return CANCELLED, "这台相机已经有目标点了"

    dot = attach_dot(ctx, cam)
    focus(ctx, cam)
    return FINISHED, "已创建目标点 %s" % dot.name


def core_untarget(ctx):
    cam = pick_camera(ctx)
    if cam is None or find_track(cam) is None:
        return CANCELLED, "当前相机不是目标相机"

    ctx.view_layer.update()
    frozen = cam.matrix_world.copy()

    released = []
    for c in [c for c in cam.constraints if c.type == 'TRACK_TO']:
        if c.target is not None:
            released.append(c.target)
        cam.constraints.remove(c)

    cam.matrix_world = frozen
    ctx.view_layer.update()

    freed = 0
    for dot in released:
        if is_owned_dot(dot) and not is_claimed(dot):
            bpy.data.objects.remove(dot, do_unlink=True)
            freed += 1
    freed += sweep_dots()

    focus(ctx, cam)
    return FINISHED, "已转为自由相机（回收 %d 个目标空物体）" % freed


def core_retarget(ctx, picked):
    cam = pick_camera(ctx)
    if cam is None or cam.type != 'CAMERA':
        return CANCELLED, "请先选中一个相机"
    if picked is None:
        return CANCELLED, "请先拾取一个目标物体"
    if picked is cam:
        return CANCELLED, "目标物体不能是相机自己"

    c = find_track(cam)
    if c is None:
        aim_at(cam, picked)
    else:
        c.target = picked
        c.enabled = True

    ctx.view_layer.update()

    msg = "目标点已设为 %s" % picked.name
    freed = sweep_dots()
    if freed:
        msg += "（回收 %d 个旧目标空物体）" % freed
    return FINISHED, msg


def core_lock(ctx):
    cam = ctx.scene.camera
    if cam is None:
        return CANCELLED, "场景里没有活动相机"

    locked = not cam.lock_location[0]
    cam.lock_location = [locked, locked, locked]
    cam.lock_rotation = [locked, locked, locked]
    cam.lock_scale = [locked, locked, locked]
    return FINISHED, "锁定相机变换：%s" % ("开" if locked else "关")


def on_pick_prop(settings, ctx):
    picked = settings.target_pick
    if picked is None:
        return

    settings.target_pick = None

    if ctx is None:
        return

    cam = pick_camera(ctx)
    if cam is None or cam.type != 'CAMERA' or picked is cam:
        return

    core_retarget(ctx, picked)


class MF_PG_Settings(PropertyGroup):
    target_pick: PointerProperty(
        name="目标物体",
        description="拾取场景里任意物体，立即设为本相机的目标点",
        type=bpy.types.Object,
        update=on_pick_prop,
    )


class MF_OT_Base(Operator):
    bl_options = {'REGISTER', 'UNDO'}

    def _wrap(self, outcome):
        state, msg = outcome
        if msg:
            self.report({'INFO'} if state == FINISHED else {'ERROR'}, msg)
        return {state}


class MF_OT_Add(MF_OT_Base):
    bl_idname = "mf.cam_add"
    bl_label = "创建相机"
    bl_description = "创建相机（默认平视朝前，放在 3D 光标处）"

    mode: EnumProperty(
        name="类型",
        items=[
            ('FREE', "自由相机", "只创建一个相机对象"),
            ('TARGET', "目标相机", "同时创建目标点并建立 LookAt"),
        ],
        default='FREE',
    )

    @classmethod
    def poll(cls, ctx):
        return ctx.area is not None and ctx.area.type == 'VIEW_3D'

    def execute(self, ctx):
        return self._wrap(core_add(ctx, self.mode == 'TARGET'))


class MF_OT_TargetAdd(MF_OT_Base):
    bl_idname = "mf.cam_create_target"
    bl_label = "创建目标点"
    bl_description = "给相机加一个 LookAt 目标点（变成目标相机）"

    @classmethod
    def poll(cls, ctx):
        cam = pick_camera(ctx)
        return cam is not None and cam.type == 'CAMERA' and find_track(cam) is None

    def execute(self, ctx):
        return self._wrap(core_target(ctx))


class MF_OT_TargetDrop(MF_OT_Base):
    bl_idname = "mf.cam_clear_target"
    bl_label = "清除目标点"
    bl_description = "移除 LookAt 目标，变回自由相机并保持当前朝向"

    @classmethod
    def poll(cls, ctx):
        return find_track(pick_camera(ctx)) is not None

    def execute(self, ctx):
        return self._wrap(core_untarget(ctx))


class MF_OT_Lock(MF_OT_Base):
    bl_idname = "mf.cam_lock_transform"
    bl_label = "锁定相机变换"
    bl_description = "锁住活动相机的位置/旋转/缩放，防止误拖动"

    @classmethod
    def poll(cls, ctx):
        return ctx.scene.camera is not None

    def execute(self, ctx):
        return self._wrap(core_lock(ctx))


classes = (
    MF_PG_Settings,
    MF_OT_Add,
    MF_OT_TargetAdd,
    MF_OT_TargetDrop,
    MF_OT_Lock,
)


def register():
    utils.register_classes(classes)
    setattr(bpy.types.Scene, SCENE_PROP, PointerProperty(type=MF_PG_Settings))


def unregister():
    delattr(bpy.types.Scene, SCENE_PROP)
    utils.unregister_classes(classes)
