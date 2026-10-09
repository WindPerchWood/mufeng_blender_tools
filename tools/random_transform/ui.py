import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (AXES, DO_OP_ID, RESET_OP_ID, WM_ATTR)

TOOL_ID = "RandomTransform"

OBJ_KEYWORDS = (
    "sjbh", "sjyd", "suiji", "random", "randomize", "rand", "transform",
    "scatter", "sui-ji", "随机", "随机变换", "随机移动", "随机旋转", "随机缩放",
    "散布", "打散", "乱序", "扰动",
)
PANEL_KEYWORDS = ("suijibianhuan", "randomtransform") + OBJ_KEYWORDS


def _props(context):
    return getattr(context.window_manager, WM_ATTR, None)


def _draw_axes(layout, props):
    col = layout.column(align=True)
    header = col.split(factor=0.2, align=True)
    header.label(text="")
    row = header.row(align=True)
    row.label(text="最小")
    row.label(text="最大")
    for axis in AXES:
        split = col.split(factor=0.2, align=True)
        split.prop(props, f"axis_{axis}", text=axis.upper())
        row = split.row(align=True)
        row.prop(props, f"min_{axis}", text="")
        row.prop(props, f"max_{axis}", text="")


class MF_PT_RandomTransform(utils.MF_ToolPanel):
    bl_label = "随机变换"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 10
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='DRIVER')

    def draw(self, context):
        layout = self.layout
        props = _props(context)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        selected = list(context.selected_objects)
        if context.mode == 'EDIT_MESH' and context.active_object is not None:
            layout.label(text=f"编辑模式：{context.active_object.name}（先在物体模式用）",
                         icon='EDITMODE_HLT')
            return
        if selected:
            layout.label(text=f"已选 {len(selected)} 个物体", icon='OBJECT_DATA')
        else:
            layout.label(text="未选中物体", icon='ERROR')

        row = layout.row(align=True)
        row.prop(props, "mode", expand=True)
        row = layout.row(align=True)
        row.prop(props, "coord", expand=True)

        _draw_axes(layout, props)

        row = layout.row(align=True)
        row.prop(props, "link_xy", toggle=True, text="X=Y")
        row.prop(props, "link_yz", toggle=True, text="Y=Z")
        row.prop(props, "link_all", toggle=True, text="全同")

        if props.mode == 'SCALE':
            layout.prop(props, "reset_scale")

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator(DO_OP_ID, text="解算", icon='PLAY')
        row.operator(RESET_OP_ID, text="", icon='LOOP_BACK')


classes = (MF_PT_RandomTransform,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
