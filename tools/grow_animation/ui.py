import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (OP_AXIS_SHIFT, OP_DRAW_PATH, OP_PATH_SHIFT,
                        OP_UNVIS_KEY, OP_VIS_KEY, TOOL_ID, WM_ATTR)

KEYWORDS = (
    "szdh", "shengzhang", "shengzhangdonghua", "shengzhangguanjianzhen",
    "growth", "growanim", "grow", "animation", "anim",
    "viskey", "visibilitykey", "movekeys", "path", "retime",
    "生长", "生长动画", "生长关键帧", "长出来", "依次出现",
    "可见性", "可见性关键帧", "显隐关键帧",
    "按顺序移动帧", "按轴向", "轴向排序", "排序错帧",
    "绘制直线", "绘制路径", "画线", "路径错帧", "样条错帧", "曲线错帧",
    "移动关键帧", "错帧", "错开", "关键帧偏移",
)
PANEL_KEYWORDS = ("shengzhangdonghua", "growanimation") + KEYWORDS


def _props(context):
    return getattr(context.window_manager, WM_ATTR, None)


class MF_PT_GrowAnimation(utils.MF_ToolPanel):
    bl_label = "生长动画"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 14
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='TIME')

    def draw(self, context):
        layout = self.layout
        props = _props(context)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        selected = context.selected_objects
        layout.label(text=f"已选 {len(selected)} 个物体" if selected else "未选中物体",
                     icon='OBJECT_DATA' if selected else 'ERROR')

        box = layout.box()
        box.label(text="可见性关键帧")
        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator(OP_VIS_KEY, text="不可见-可见")
        row.operator(OP_UNVIS_KEY, text="可见-不可见")

        box = layout.box()
        box.label(text="按轴向排序移动帧")
        box.row(align=True).prop(props, "axis", expand=True)
        row = box.row(align=True)
        row.prop(props, "step")
        row.prop(props, "descending", text="降序", toggle=True)
        box.prop(props, "selected_only", text="仅移动选中帧")
        row = box.row()
        row.scale_y = 1.3
        row.operator(OP_AXIS_SHIFT, text="执行", icon='PLAY')

        box = layout.box()
        box.label(text="按绘制路径移动关键帧")
        row = box.row()
        row.scale_y = 1.3
        row.operator(OP_DRAW_PATH, text="绘制直线", icon='CURVE_DATA')
        box.prop(props, "path_object", text="路径")
        row = box.row(align=True)
        row.prop(props, "path_frames")
        box.prop(props, "path_selected_only", text="仅移动选中帧")
        row = box.row()
        row.scale_y = 1.3
        row.operator(OP_PATH_SHIFT, text="执行", icon='PLAY')


classes = (MF_PT_GrowAnimation,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
