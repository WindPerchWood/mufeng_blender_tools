import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import OP_ID
from . import cube_overlay


class MF_PT_ViewCube(utils.MF_ToolPanel):
    bl_label = "视图魔方"
    bl_idname = "MF_PT_ViewCube"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "stmf", "shitu", "viewcube", "cube", "view", "nav", "navigation",
        "视角", "方向", "正交", "透视", "顶视图",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='CUBE')

    AUX_BUTTONS = (
        ("TOGGLE_ORTHO", "正交/透视"),
    )

    def draw(self, context):
        layout = self.layout

        text = "关闭悬浮魔方" if cube_overlay.is_enabled() else "开启悬浮魔方"
        layout.operator(OP_ID, text=text,
                        icon='HIDE_OFF' if cube_overlay.is_enabled() else 'HIDE_ON'
                        ).view_key = 'OVERLAY_TOGGLE'

        for key, label in self.AUX_BUTTONS:
            layout.operator(OP_ID, text=label).view_key = key


classes = (MF_PT_ViewCube,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
