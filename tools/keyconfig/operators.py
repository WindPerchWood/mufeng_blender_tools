import math
import os
import shutil

import bpy


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

TOOL_ID = "Keyconfig"


KEYCONFIG_NAME = "custom_keymap"

DEFAULT_KEYCONFIG = "Blender"

_SRC_KEYMAP = os.path.join(os.path.dirname(__file__), "presets", f"{KEYCONFIG_NAME}.py")


def preset_dir():
    return bpy.utils.user_resource(
        'SCRIPTS', path=os.path.join("presets", "keyconfig"), create=True,
    )


def deployed_path():
    return os.path.join(preset_dir(), f"{KEYCONFIG_NAME}.py")

def active_name(context=None):
    try:
        wm = (context or bpy.context).window_manager
        kc = wm.keyconfigs.active
        return kc.name if kc else ""
    except Exception:
        return ""


def is_enabled(context=None):
    return active_name(context) == KEYCONFIG_NAME

def _same_file(path_a, path_b):
    try:
        if not os.path.exists(path_b):
            return False
        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _deploy():
    if not os.path.exists(_SRC_KEYMAP):
        return None

    dst = deployed_path()
    if _same_file(_SRC_KEYMAP, dst):
        return dst

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(_SRC_KEYMAP, dst)
    except OSError as exc:
        utils.report("ERROR", f"写入键位文件失败: {exc}")
        return None
    return dst


def enable_keyconfig(context):
    wm = context.window_manager
    dst = _deploy()
    if dst is None:
        return False, f"找不到插件自带的键位文件 presets/{KEYCONFIG_NAME}.py"

    kc = wm.keyconfigs.get(KEYCONFIG_NAME)
    if kc is not None:
        if getattr(kc, "is_user_defined", False):
            try:
                wm.keyconfigs.remove(kc)
            except Exception as exc:
                utils.report("WARNING", f"移除旧键位方案失败，改为直接激活: {exc}")
                wm.keyconfigs.active = kc
                return True, f"已启用键位方案：{KEYCONFIG_NAME}（沿用旧内容）"
        else:
            utils.report("WARNING", f"{KEYCONFIG_NAME} 不是用户方案，无法重建")
            wm.keyconfigs.active = kc
            return True, f"已启用键位方案：{KEYCONFIG_NAME}（沿用原方案）"

    if not bpy.utils.keyconfig_set(dst, report=lambda lv, msg: utils.report(lv, msg)):
        return False, "键位方案载入失败，详情见控制台"

    return True, f"已启用键位方案：{KEYCONFIG_NAME}"


def disable_keyconfig(context):
    path = bpy.utils.preset_find(DEFAULT_KEYCONFIG, "keyconfig")
    if not path:
        return False, f"找不到 Blender 默认键位预设 {DEFAULT_KEYCONFIG}.py"
    if not bpy.utils.keyconfig_set(path, report=lambda lv, msg: utils.report(lv, msg)):
        return False, "恢复默认键位失败，详情见控制台"
    return True, f"已恢复默认键位：{DEFAULT_KEYCONFIG}"


class MF_OT_Keyconfig_Toggle(bpy.types.Operator):
    bl_idname = f"mf.{TOOL_ID.lower()}_toggle"
    bl_label = "切换键位方案"
    bl_description = "勾选使用自带键位方案，取消勾选回到 Blender 默认键位"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if is_enabled(context):
            ok, msg = disable_keyconfig(context)
        else:
            ok, msg = enable_keyconfig(context)
        level = 'INFO' if ok else 'ERROR'
        self.report({level}, msg)
        utils.report(level, msg)
        return {'FINISHED'} if ok else {'CANCELLED'}


class MF_OT_MaxZoomExtents(bpy.types.Operator):
    bl_idname = "mf.max_zoom_extents"
    bl_label = "最大化显示 (Max 风格)"
    bl_description = "有选中项时最大化显示选中项，没有选中项时最大化显示全部"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    @staticmethod
    def has_selection(context):
        obs = [o for o in context.view_layer.objects if o.select_get() and o.visible_get()]
        if not obs:
            return False
        if context.mode == 'OBJECT':
            return True
        for o in obs:
            if o.type == 'MESH' and o.data is not None:
                me = o.data
                if any(v.select for v in me.vertices):
                    return True
                if any(e.select for e in me.edges):
                    return True
                if any(f.select for f in me.polygons):
                    return True
            else:

                return True
        return False

    def execute(self, context):
        if self.has_selection(context):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        else:
            bpy.ops.view3d.view_all(use_all_regions=False)
        return {'FINISHED'}


def _selection_signature(context):
    ob = context.active_object
    if ob is not None and ob.mode == 'EDIT':
        me = ob.data
        if hasattr(me, "vertices"):
            import bmesh

            try:
                bm = bmesh.from_edit_mesh(me)
                return (
                    sum(1 for v in bm.verts if v.select),
                    sum(1 for e in bm.edges if e.select),
                    sum(1 for f in bm.faces if f.select),
                )
            except Exception:
                pass
    return (len(context.selected_objects),)


class MF_OT_MaxSelectToggle(bpy.types.Operator):
    bl_idname = "mf.select_toggle"
    bl_label = "加选 / 取消（Max 风格，一次生效）"
    bl_description = (
        "点未选中的物体：加选；点已选中的物体：立即取消（不受"
        "'需先变成活动物体'的限制，一次生效）；点空白处：取消全部选择"
    )

    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        loc = (event.mouse_region_x, event.mouse_region_y)
        try:
            sel_before = _selection_signature(context)
            act_before = context.active_object.name if context.active_object else ""

            bpy.ops.view3d.select(toggle=True, location=loc)

            sel_after = _selection_signature(context)
            act_after = context.active_object.name if context.active_object else ""

            if sel_before == sel_after:
                if act_before != act_after:

                    bpy.ops.view3d.select(deselect=True, location=loc)
                else:

                    bpy.ops.view3d.select(deselect_all=True, location=loc)
        except Exception:

            return {'PASS_THROUGH'}
        return {'FINISHED'}


class MF_OT_CreateCameraFromView(bpy.types.Operator):
    bl_idname = "mf.create_camera_from_view"
    bl_label = "从当前视图创建摄像机 (Max 风格)"
    bl_description = ("按当前 3D 视图新建一台摄像机（机位与视野都与视口一致），"
                      "设为场景的活动摄像机并切到它的视图")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.area is not None
                and context.area.type == 'VIEW_3D'
                and context.region_data is not None)

    @staticmethod
    def view_half_fov_h(region, rv3d):
        from mathutils import Vector
        from bpy_extras.view3d_utils import region_2d_to_vector_3d

        try:
            cx, cy = region.width * 0.5, region.height * 0.5
            d_c = region_2d_to_vector_3d(region, rv3d, Vector((cx, cy))).normalized()
            d_r = region_2d_to_vector_3d(
                region, rv3d, Vector((region.width - 1.0, cy))).normalized()
            half = float(d_c.angle(d_r))
            return half if half > 1e-4 else None
        except Exception:
            return None

    def execute(self, context):
        rv3d = context.region_data
        scene = context.scene
        prev_camera = scene.camera
        prev_persp = rv3d.view_perspective

        space = None
        ob = None
        try:
            space = context.space_data
            cam_data = bpy.data.cameras.new("Camera_MF")

            half = self.view_half_fov_h(context.region, rv3d) if context.region else None
            if half is not None:
                cam_data.sensor_fit = 'HORIZONTAL'
                cam_data.sensor_width = 36.0
                cam_data.lens = 18.0 / math.tan(half)
            else:
                cam_data.lens = float(getattr(space, "lens", 50.0))

            ob = bpy.data.objects.new("Camera_MF", cam_data)
            (context.collection or scene.collection).objects.link(ob)

            scene.camera = ob
            try:
                space.camera = ob
            except Exception:
                pass

            if prev_persp == 'CAMERA' and prev_camera is not None:

                ob.matrix_world = prev_camera.matrix_world.copy()
                if prev_camera.data is not None:
                    cam_data.lens = prev_camera.data.lens
                    cam_data.sensor_width = prev_camera.data.sensor_width
                    cam_data.sensor_fit = prev_camera.data.sensor_fit
            else:
                result = bpy.ops.view3d.camera_to_view()
                if 'FINISHED' not in result:
                    raise RuntimeError("对齐视图失败（视图可能被锁定或没有可用区域）")

            if rv3d.view_perspective != 'CAMERA':
                rv3d.view_perspective = 'CAMERA'
        except Exception as exc:

            try:
                scene.camera = prev_camera
                if ob is not None:
                    data = ob.data
                    bpy.data.objects.remove(ob, do_unlink=True)
                    if data is not None and data.users == 0:
                        bpy.data.cameras.remove(data)
                rv3d.view_perspective = prev_persp
            except Exception:
                pass
            self.report({'ERROR'}, f"从视图创建摄像机失败: {exc}")
            return {'CANCELLED'}

        try:
            for other in context.selected_objects:
                other.select_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
        except Exception:
            pass

        self.report({'INFO'}, "已按当前视图创建摄像机并设为活动摄像机")
        return {'FINISHED'}


class MF_OT_ViewCameraSelected(bpy.types.Operator):
    bl_idname = "mf.view_camera_selected"
    bl_label = "摄像机视图（选中优先）"
    bl_description = "选中了摄像机就切到它的视图；再按一次退回用户视图；没选中则用活动摄像机"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.area is not None
                and context.area.type == 'VIEW_3D'
                and context.region_data is not None)

    @staticmethod
    def picked_camera(context):
        act = context.active_object
        if act is not None and act.type == 'CAMERA':
            return act
        for ob in context.selected_objects:
            if ob.type == 'CAMERA':
                return ob
        return None

    def execute(self, context):
        rv3d = context.region_data
        scene = context.scene
        picked = self.picked_camera(context)
        try:
            if picked is None:

                bpy.ops.view3d.view_camera()
                return {'FINISHED'}

            if rv3d.view_perspective == 'CAMERA' and scene.camera is picked:
                bpy.ops.view3d.view_camera()
                return {'FINISHED'}

            if rv3d.view_perspective == 'CAMERA':
                bpy.ops.view3d.view_camera()
            scene.camera = picked
            try:
                context.space_data.camera = picked
            except Exception:
                pass
            if rv3d.view_perspective != 'CAMERA':
                bpy.ops.view3d.view_camera()
        except Exception as exc:
            self.report({'ERROR'}, f"切换摄像机视图失败: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MF_OT_Keyconfig_Toggle,
    MF_OT_MaxZoomExtents,
    MF_OT_MaxSelectToggle,
    MF_OT_CreateCameraFromView,
    MF_OT_ViewCameraSelected,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
