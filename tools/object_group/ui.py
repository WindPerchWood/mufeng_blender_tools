import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Toolbox",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (
    MF_OT_ObjectGroup_Join,
    MF_OT_ObjectGroup_Make,
    MF_OT_ObjectGroup_Dissolve,
)


class MF_PT_ObjectGroup(utils.MF_ToolPanel):
    bl_label = "对象归组"
    bl_idname = "MF_PT_ObjectGroup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "dxgz", "guizu", "group", "collection", "join", "merge",
        "合并", "打组", "成组", "集合", "解散",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_COLLECTION')

    def draw(self, context):
        layout = self.layout
        sel = context.selected_objects
        layout.label(text=f"已选 {len(sel)} 个对象" if sel else "未选中对象",
                     icon='INFO' if sel else 'ERROR')

        col = layout.column(align=True)
        col.operator(MF_OT_ObjectGroup_Join.bl_idname,
                     text="合并成一个对象", icon='AUTOMERGE_ON')
        col.operator(MF_OT_ObjectGroup_Make.bl_idname,
                     text="选中对象成集合", icon='OUTLINER_COLLECTION')
        col.operator(MF_OT_ObjectGroup_Dissolve.bl_idname,
                     text="解散集合（含嵌套）" if sel else "解散所有集合（含嵌套）",
                     icon='CANCEL')


classes = (MF_PT_ObjectGroup,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
