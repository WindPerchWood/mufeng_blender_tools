import bpy


try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import PARENT_OP_ID, UNPARENT_OP_ID

TOOL_ID = "MaxParent"

PANEL_KEYWORDS = (
    "maxparent", "parent", "link", "unlink", "fuzi", "mushi", "jiechu",
    "父子", "父级", "绑定", "解绑", "解除", "链接", "父子绑定",
)


class MF_PT_MaxParent(utils.MF_ToolPanel):
    bl_label = "父子绑定"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='LINKED')

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator(PARENT_OP_ID, text="绑定到活动物体", icon='LINKED')
        col.operator(UNPARENT_OP_ID, text="解除父级", icon='UNLINKED')


classes = (MF_PT_MaxParent,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
