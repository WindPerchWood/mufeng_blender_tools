"""样条线子工具 · N 面板：只负责画界面，业务全调 operators 里的操作符。"""

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

from .operators import MF_OT_Spline_Line, OP_ID_DRAW, STATE


class MF_PT_Spline(utils.MF_ToolPanel):
    bl_label = "样条线"
    bl_idname = "MF_PT_Spline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("ytx", "spline", "zhixian", "样条线", "直线")

    def draw_header(self, context):
        self.layout.label(text="", icon='CURVE_BEZCURVE')

    def draw(self, context):
        layout = self.layout

        layout.operator(OP_ID_DRAW, text="直线", icon='CURVE_BEZCURVE')
        if STATE["active_tool"]:
            layout.label(text="绘制中：%s" % STATE["active_tool"], icon='INFO')


classes = (MF_PT_Spline,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
