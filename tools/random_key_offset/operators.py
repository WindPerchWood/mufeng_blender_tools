import random

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty

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
        PANEL_CATEGORY="MF Tools",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[MF Tools] {level}: {msg}"),
    )

TOOL_ID = "RandomKeyOffset"
DO_OP_ID = "mf.randkeyoffset_do"
WM_ATTR = "mf_randkeyoffset"

_FAR = 100000
_REDRAW_AREAS = {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'TIMELINE'}

_WARN_NO_SELECTED_KEY = ("没有选中的关键帧可移动（先在摄影表/曲线编辑器里选键，"
                         "或关掉「仅移动选中帧」）")


class MF_PG_RandomKeyOffsetSettings(bpy.types.PropertyGroup):
    offset_min: IntProperty(
        name="Min",
        description="随机偏移下限（帧，含本值）",
        default=-5, min=-_FAR, max=_FAR,
        soft_min=-1000, soft_max=1000,
    )
    offset_max: IntProperty(
        name="Max",
        description="随机偏移上限（帧，含本值）",
        default=5, min=-_FAR, max=_FAR,
        soft_min=-1000, soft_max=1000,
    )
    selected_only: BoolProperty(
        name="仅移动选中帧",
        description="只平移摄影表/曲线编辑器里被选中的关键帧；"
                    "勾选时若没有任何键被选中则不做任何操作",
        default=False,
    )


def _get_props(context):
    return getattr(context.window_manager, WM_ATTR, None)


def _slot_pointer(anim_data):
    slot = getattr(anim_data, "action_slot", None)
    return slot.as_pointer() if slot is not None else 0


def _tag_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for win in wm.windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type in _REDRAW_AREAS:
                area.tag_redraw()


def _action_fcurves(anim):
    action = anim.action if anim is not None else None
    if action is None:
        return ()

    layers = getattr(action, "layers", None)
    if layers is None:
        return tuple(getattr(action, "fcurves", ()))

    slot = getattr(anim, "action_slot", None)
    slot_ptr = slot.as_pointer() if slot is not None else 0

    found = []
    for layer in layers:
        for strip in layer.strips:
            if getattr(strip, "type", "") != 'KEYFRAME':
                continue
            for bag in getattr(strip, "channelbags", ()):
                bag_slot = getattr(bag, "slot", None)
                if slot_ptr and bag_slot is not None \
                        and bag_slot.as_pointer() != slot_ptr:
                    continue
                found.extend(bag.fcurves)
    return tuple(found)


def _anim_sources(obj):
    raw = [obj.animation_data]

    data = getattr(obj, "data", None)
    if data is not None:
        raw.append(getattr(data, "animation_data", None))
        shape_keys = getattr(data, "shape_keys", None)
        if shape_keys is not None:
            raw.append(getattr(shape_keys, "animation_data", None))

    for slot in getattr(obj, "material_slots", ()):
        mat = slot.material
        if mat is None:
            continue
        raw.append(getattr(mat, "animation_data", None))
        node_tree = getattr(mat, "node_tree", None)
        if node_tree is not None:
            raw.append(getattr(node_tree, "animation_data", None))

    out = []
    seen = set()
    for anim in raw:
        if anim is None:
            continue
        ptr = anim.as_pointer()
        if ptr in seen:
            continue
        seen.add(ptr)
        out.append(anim)
    return out


def _shift_fcurve(fcurve, delta, selected_only):
    moved = 0
    negative = 0
    for kp in fcurve.keyframe_points:
        if selected_only and not kp.select_control_point:
            continue
        x, y = kp.co_ui
        x += delta
        kp.co_ui = (x, y)
        moved += 1
        if x < 0.0:
            negative += 1
    if moved:
        fcurve.update()
    return moved, negative


class MF_OT_RandomKeyOffset_Do(bpy.types.Operator):
    bl_idname = DO_OP_ID
    bl_label = "随机移动关键帧"
    bl_description = ("每个选中物体各抽一个随机帧偏移（含两端），把该物体名下的关键帧整体平移："
                      "包括物体自身的位移/旋转/缩放、物体数据、形态键，以及「更改可见性」"
                      "打在材质上的透明淡出键；勾选「仅移动选中帧」只平移被选中的键")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}

        low = min(props.offset_min, props.offset_max)
        high = max(props.offset_min, props.offset_max)
        selected_only = props.selected_only

        done = set()
        moved_objects = 0
        moved_keys = 0
        moved_material_keys = 0
        negative = 0

        for obj in context.selected_objects:
            targets = []
            for anim in _anim_sources(obj):
                if anim.action is None:
                    continue
                combo = (anim.action.as_pointer(), _slot_pointer(anim))
                if combo in done:
                    continue
                fcurves = _action_fcurves(anim)
                if not fcurves:
                    continue
                done.add(combo)
                targets.append((anim, fcurves))

            if not targets:
                continue

            delta = random.randint(low, high)

            obj_keys = 0
            for anim, fcurves in targets:
                owner = getattr(anim, "id_data", None)
                is_material = owner is not None and getattr(owner, "bl_rna", None) \
                    is not None and owner.bl_rna.identifier in ('Material', 'ShaderNodeTree')

                for fcurve in fcurves:
                    keys, neg = _shift_fcurve(fcurve, delta, selected_only)
                    obj_keys += keys
                    negative += neg
                    if keys and is_material:
                        moved_material_keys += keys

                if owner is not None:
                    try:
                        owner.update_tag()
                    except Exception:
                        pass

            if obj_keys:
                moved_objects += 1
                moved_keys += obj_keys
                obj.update_tag(refresh={'OBJECT', 'TIME'})

        if not moved_keys:
            if selected_only:
                self.report({'WARNING'}, _WARN_NO_SELECTED_KEY)
            else:
                self.report({'WARNING'}, "选中物体没有可移动的关键帧")
            return {'CANCELLED'}

        try:
            context.scene.frame_set(context.scene.frame_current)
        except Exception:
            context.view_layer.update()
        _tag_redraw()

        message = f"{moved_objects} 个物体 / {moved_keys} 个关键帧已随机平移"
        if moved_material_keys:
            message += f"（含 {moved_material_keys} 个材质可见性键）"
        if negative:
            message += f"（{negative} 个键落到 0 帧以前）"
        self.report({'INFO'}, message)
        return {'FINISHED'}


classes = (MF_PG_RandomKeyOffsetSettings, MF_OT_RandomKeyOffset_Do)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_RandomKeyOffsetSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
