import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import OP_ID, WM_ATTR

TOOL_ID = "BookStack"

PANEL_KEYWORDS = ("shubenduidie", "sbdj", "bookstack", "book",
                  "书", "书本", "堆叠", "书本堆叠")


def _props(context):
    return getattr(context.window_manager, WM_ATTR, None)


class MF_PT_BookStack(utils.MF_ToolPanel):
    bl_label = "书本堆叠"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15                        # 2~14 已被现有工具占用
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='MESH_CUBE')

    def draw(self, context):
        layout = self.layout
        props = _props(context)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        sel = context.selected_objects
        layout.label(text=f"已选 {len(sel)} 个源物体" if sel else "未选中源物体",
                     icon='OBJECT_DATA' if sel else 'ERROR')

        col = layout.column(align=True)
        col.prop(props, "count")
        col.prop(props, "rot_x_prob")
        col.prop(props, "rot_y_prob")
        col.prop(props, "rot_xy_deg")
        col.prop(props, "offset")
        col.prop(props, "no_repeat")

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator(OP_ID, text="开始堆叠", icon='PLAY')


classes = (MF_PT_BookStack,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
