"""相机工具：N 面板，只负责画界面，业务全调 operators 里的操作符。"""

import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (MF_OT_Add, MF_OT_TargetAdd, MF_OT_TargetDrop, MF_OT_Lock,
                        pick_camera, find_track, dot_distance, SCENE_PROP)


class MF_PT_Camera(utils.MF_ToolPanel):
    bl_label = "相机"
    bl_idname = "MF_PT_Camera"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("xiangji", "camera", "相机", "目标相机", "自由相机", "锁定变换")

    def draw_header(self, context):
        self.layout.label(text="", icon='CAMERA_DATA')

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        cam = pick_camera(context)
        track = find_track(cam)
        settings = getattr(scene, SCENE_PROP, None)

        box = layout.box()
        box.label(text="创建相机", icon='OUTLINER_OB_CAMERA')
        row = box.row(align=True)
        row.operator(MF_OT_Add.bl_idname, text="自由相机").mode = 'FREE'
        row.operator(MF_OT_Add.bl_idname, text="目标相机").mode = 'TARGET'

        box = layout.box()
        box.label(text="目标点 Target", icon='TRACKER')

        if cam is None:
            box.label(text="场景里还没有相机", icon='INFO')
            return

        box.label(text="当前相机：%s" % cam.name)
        if track is not None:
            dist = dot_distance(cam)
            box.label(text="目标距离 %.3f" % (dist if dist is not None else 0.0),
                      icon='FIXED_SIZE')
        else:
            box.label(text="状态：自由相机")

        split = box.split(factor=0.5, align=True)
        left = split.row(align=True)
        left.enabled = track is None
        left.operator(MF_OT_TargetAdd.bl_idname, text="创建目标")
        right = split.row(align=True)
        right.enabled = track is not None
        right.operator(MF_OT_TargetDrop.bl_idname, text="清除目标")

        if settings is not None:
            col = box.column(align=True)
            col.label(text="拾取物体作为目标", icon='EYEDROPPER')
            col.prop(settings, "target_pick", text="")

        box = layout.box()
        box.label(text="相机视图", icon='VIEW_CAMERA')
        row = box.row(align=True)
        row.operator(MF_OT_Lock.bl_idname, text="锁定变换",
                     depress=cam.lock_location[0])


def _extend_camera_menu(self, _ctx):
    layout = self.layout
    layout.separator()
    layout.operator(MF_OT_TargetAdd.bl_idname, icon='TRACKER')
    layout.operator(MF_OT_TargetDrop.bl_idname, icon='TRACKER')


classes = (MF_PT_Camera,)


def register():
    utils.register_classes(classes)
    bpy.types.VIEW3D_MT_view_cameras.append(_extend_camera_menu)


def unregister():
    bpy.types.VIEW3D_MT_view_cameras.remove(_extend_camera_menu)
    utils.unregister_classes(classes)
