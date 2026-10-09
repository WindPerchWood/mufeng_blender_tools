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
        MF_ToolPanel=bpy.types.Panel,
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

from .operators import MODE_ITEMS, WM_ATTR


class MF_PT_Guide(utils.MF_ToolPanel):
    bl_label = "构图辅助线"
    bl_idname = "MF_PT_Guide"
    bl_description = "在相机视图里叠加构图参考线：三分法、黄金分割、开方、中分、对角线、三角"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 18
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "gtfzx", "goutufuzhuxian", "guide", "guides", "composition", "thirds",
        "golden", "grid", "overlay",
        "构图", "辅助线", "参考线", "构图辅助线", "三分法", "黄金分割",
        "井字", "中分", "对角线", "三角构图", "开方构图",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='GRID')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        layout.prop(props, "enabled", text="启用构图线", toggle=True)

        layout.separator(factor=0.4)
        col = layout.column(align=True)
        col.label(text="构图法")
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for identifier, label, _desc in MODE_ITEMS:
            grid.prop_enum(props, "mode", identifier, text=label)

        layout.separator(factor=0.4)
        box = layout.box()
        box.label(text="外观", icon='COLOR')
        box.prop(props, "color", text="")
        box.prop(props, "line_width")


classes = (MF_PT_Guide,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
