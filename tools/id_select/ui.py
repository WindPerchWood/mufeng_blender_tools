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

    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel,
                                  register_classes=_fallback_register,
                                  unregister_classes=_fallback_unregister)

from .operators import OP_SELECT, STATE_ATTR, TOOL_ID, id_of

PANEL_KEYWORDS = (
    "axz", "axzcx", "id", "idcx", "idchaxun", "anid", "anzhaoid", "quxuan",
    "select", "selectbyid", "elementid", "objectid", "find", "locate", "query",
    "pick", "lookup", "goto",
    "按ID选择", "按ID选择查询", "选择项的ID", "选择项ID", "ID查询", "元素ID", "物体ID",
    "编号", "反查", "查找", "定位", "选择", "查询", "跨集合",
)


class MF_PT_IdSelect(utils.MF_ToolPanel):
    bl_label = "ID 选择查询"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='RESTRICT_SELECT_OFF')

    def draw(self, context):
        layout = self.layout
        state = getattr(context.window_manager, STATE_ATTR, None)
        if state is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        selected = list(context.selected_objects)
        if selected:
            ids = [str(id_of(obj)) for obj in selected]
            layout.label(text="已选 %d 个物体  ID: %s" % (len(selected), ", ".join(ids)),
                         icon='OBJECT_DATA')
        else:
            layout.label(text="未选中物体", icon='ERROR')

        col = layout.column(align=True)
        col.prop(state, "ids_input", text="", icon='VIEWZOOM')

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator(OP_SELECT, text="按 ID 选择查询", icon='RESTRICT_SELECT_OFF')


classes = (MF_PT_IdSelect,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
