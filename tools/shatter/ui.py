import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (
    GRID_MAX_CELLS,
    GRID_OP_ID,
    RANDOM_OP_ID,
    SHATTER_WARN_PARTS,
    WM_ATTR,
    target_object,
)

TOOL_ID = "Shatter"


GRID_KEYWORDS = (
    "zq", "zqsg", "zhengqi", "grid", "gridcut", "cut", "slice", "split",
    "整齐", "整齐切割", "格子切", "切块", "切割", "切开", "切分",
)
RANDOM_KEYWORDS = (
    "sjps", "suiji", "random", "fracture", "voronoi", "debris", "cellfracture",
    "随机", "随机破碎", "破碎", "碎块", "爆破", "炸开",
)
PANEL_KEYWORDS = ("wtps", "posui", "shatter", "break") + GRID_KEYWORDS + RANDOM_KEYWORDS


class MF_PT_Shatter(utils.MF_ToolPanel):
    bl_label = "物体破碎"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 8
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_EXPLODE')

    def draw(self, context):
        layout = self.layout
        target = target_object(context)
        if target is None:
            layout.label(text="请先选中一个网格物体", icon='ERROR')
        else:
            layout.label(text=f"目标：{target.name}", icon='OBJECT_DATA')


class MF_PT_Shatter_Cut(utils.MF_ToolPanel):
    bl_label = "整齐切割"

    bl_idname = f"MF_PT_{TOOL_ID}_Cut"
    bl_parent_id = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = GRID_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='MESH_GRID')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return
        target = target_object(context)

        row = layout.row(align=True)
        row.prop(props, "segx", text="X")
        row.prop(props, "segy", text="Y")
        row.prop(props, "segz", text="Z")

        cells = props.segx * props.segy * props.segz
        if cells > 1:
            over = cells > GRID_MAX_CELLS
            layout.label(text=f"共 {cells} 块" + ("（超过上限，请调小）" if over else ""),
                         icon='ERROR' if over else 'INFO')
        else:
            layout.label(text="把某一轴调到 2 以上才会切", icon='INFO')

        layout.prop(props, "skin")

        row = layout.row()
        row.scale_y = 1.5
        op = row.operator(GRID_OP_ID, text="切割物体", icon='MOD_BOOLEAN')
        op.segx = props.segx
        op.segy = props.segy
        op.segz = props.segz
        op.hide_original = props.hide_original
        op.skin = props.skin
        row.enabled = target is not None and 1 < cells <= GRID_MAX_CELLS

        layout.prop(props, "hide_original")
        layout.prop(props, "show_preview")


class MF_PT_Shatter_Break(utils.MF_ToolPanel):
    bl_label = "随机破碎"
    bl_idname = f"MF_PT_{TOOL_ID}_Break"
    bl_parent_id = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = RANDOM_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_EXPLODE')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return
        target = target_object(context)

        layout.prop(props, "count")
        layout.prop(props, "seed")

        if props.count > SHATTER_WARN_PARTS:
            layout.label(text=f"数量偏大（切面数 ≈ {props.count}²），会算一会儿",
                         icon='ERROR')

        row = layout.row()
        row.scale_y = 1.5
        op = row.operator(RANDOM_OP_ID, text="随机破碎", icon='MOD_EXPLODE')
        op.count = props.count
        op.seed = props.seed
        op.hide_original = props.hide_original
        row.enabled = target is not None


classes = (MF_PT_Shatter, MF_PT_Shatter_Cut, MF_PT_Shatter_Break)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
