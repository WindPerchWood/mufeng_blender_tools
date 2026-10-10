import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    def _fb_reg(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _fb_unreg(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel,
                                  register_classes=_fb_reg,
                                  unregister_classes=_fb_unreg)

from .operators import (MF_OT_RotMode_Set, MF_OT_RotMode_Unparent,
                        MF_OT_RotMode_SingleUser, MF_OT_RotMode_ApplyTransform,
                        OP_ID, UNPARENT_OP_ID, SINGLE_USER_OP_ID,
                        APPLY_TRS_OP_ID, CLEAR_EMPTIES_OP_ID, WM_ATTR)


class MF_PT_RotMode(utils.MF_ToolPanel):
    bl_label = "物体变换"
    bl_idname = "MF_PT_RotMode"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("wuti", "bianhuan", "transform", "物体变换", "变换",
                          "旋转", "xzms", "rotmode", "rotationmode", "四元数",
                          "欧拉", "euler", "quaternion", "父级", "单体",
                          "unparent", "apply", "singleuser",
                          "空物体", "kongwuti", "empty", "empties", "清除", "qingchu", "clear")

    def draw_header(self, context):
        self.layout.label(text="", icon='LOOP_FORWARDS')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            return
        row = layout.row(align=True)
        row.prop(props, "mode", text="")
        row.operator(MF_OT_RotMode_Set.bl_idname, text="应用全部").mode = props.mode

        col = layout.column(align=True)
        col.operator(UNPARENT_OP_ID, text="解除全部父级")
        col.operator(SINGLE_USER_OP_ID, text="全部变单体")
        col.operator(APPLY_TRS_OP_ID, text="应用全部变换")
        col.operator(CLEAR_EMPTIES_OP_ID, text="清除空物体")


classes = (MF_PT_RotMode,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
