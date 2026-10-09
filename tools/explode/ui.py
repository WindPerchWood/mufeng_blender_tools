import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import MF_OT_Explode_Do, OP_ID, WM_ATTR

TOOL_ID = "Explode"


class MF_PT_Explode(utils.MF_ToolPanel):
    bl_label = "原地炸开"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 7
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "ydzk", "zhakai", "explode", "scatter", "spread", "sep",
        "炸开", "爆炸", "散开", "分离", "扩散",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_EXPLODE')

    AXIS_BUTTONS = (
        ('X', "X", "只沿世界 X 轴推开"),
        ('Y', "Y", "只沿世界 Y 轴推开"),
        ('Z', "Z", "只沿世界 Z 轴推开"),
    )

    def draw(self, context):
        layout = self.layout
        sel = context.selected_objects
        layout.label(text=f"已选 {len(sel)} 个对象" if sel else "请先选择物体",
                     icon='INFO' if sel else 'ERROR')

        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        layout.prop(props, "distance")

        row = layout.row(align=True)
        row.scale_y = 1.4
        for key, text, tip in self.AXIS_BUTTONS:
            op = row.operator(OP_ID, text=text)
            op.axis = key
            op.distance = props.distance
        row.enabled = bool(sel)

        row = layout.row()
        row.scale_y = 1.4
        op = row.operator(OP_ID, text="XYZ 三轴炸开", icon='MOD_EXPLODE')
        op.axis = 'XYZ'
        op.distance = props.distance
        row.enabled = bool(sel)


classes = (MF_PT_Explode,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
