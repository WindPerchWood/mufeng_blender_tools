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

from . import plan as P
from . import props

from .operators import OP_CLEAR, OP_ESTIMATE, OP_GROW, OP_SELECT


class MF_PT_FloorGrowth(utils.MF_ToolPanel):
    bl_idname = "MF_PT_FloorGrowth"
    bl_label = "地板生长"
    bl_description = "地砖/墙砖逐个翻滚生长的动画生成器（关键帧 / 几何节点烘焙 双模式）"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 17
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "dbsz", "dibanshengzhang", "floorgrowth", "floor", "floor_growth",
        "tile", "tiles", "tilegrowth",
        "地砖", "地砖生长", "地板", "地板生长", "瓷砖", "铺砖", "砖块",
        "砖块生长", "翻滚", "翻滚生长", "逐个生长", "地砖动画",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='MESH_GRID')

    def draw(self, context):
        layout = self.layout
        st = getattr(context.scene, props.SCENE_ATTR, None)
        if st is None:
            layout.label(text="参数未就绪，请重新启用插件", icon='ERROR')
            return

        box = layout.box()
        box.label(text="① 目标", icon='OBJECT_DATA')
        box.prop(st, "target_mode", text="")
        if st.target_mode == 'COLLECTION':
            box.prop(st, "target_collection", text="")
        elif st.target_mode == 'PREFIX':
            box.prop(st, "target_prefix", text="")
        row = box.row(align=True)
        row.operator(OP_SELECT, icon='RESTRICT_SELECT_OFF')
        row.operator(OP_ESTIMATE, icon='TIME')

        box = layout.box()
        box.label(text="② 起点与传播", icon='CURVE_PATH')
        box.prop(st, "origin_mode")
        if st.origin_mode == 'OBJECT':
            box.prop(st, "origin_object", text="")
        box.prop(st, "origin_offset")
        box.prop(st, "spread_mode")
        if st.spread_mode == P.SPREAD_VECTOR:
            box.prop(st, "direction")
        if st.spread_mode == P.SPREAD_WAVE:
            box.prop(st, "wave_axis")
            box.prop(st, "wave_period")
        if st.spread_mode == P.SPREAD_RANDOM:
            box.prop(st, "random_seed")
        box.prop(st, "ease_mode")
        box.prop(st, "jitter", slider=True)

        box = layout.box()
        box.label(text="③ 整体时序", icon='TIME')
        col = box.column(align=True)
        col.prop(st, "start_frame")
        col.prop(st, "spread_frames")
        col.prop(st, "per_tile_frames")

        box = layout.box()
        box.label(text="④ 出现阶段", icon='FULLSCREEN_ENTER')
        box.prop(st, "appear_mode")
        if st.appear_mode != P.APPEAR_NONE:
            box.prop(st, "appear_frames")
            box.prop(st, "gap_after_appear")

        box = layout.box()
        box.label(text="⑤ 单块动作", icon='MOD_SIMPLEDEFORM')
        box.prop(st, "flip_angle")
        box.prop(st, "flip_axis")
        if st.flip_axis == P.AXIS_CUSTOM:
            box.prop(st, "custom_axis")
        box.prop(st, "lift_height")
        if st.lift_height > 0.0:
            box.prop(st, "lift_mode")
        box.prop(st, "use_bounce")
        if st.use_bounce:
            box.prop(st, "bounce_amount", slider=True)

        box = layout.box()
        box.label(text="⑥ 输出", icon='EXPORT')
        box.prop(st, "interpolate")
        box.prop(st, "auto_clear_before")

        box = layout.box()
        box.label(text="⑦ 大规模（>1000 块）", icon='MOD_BUILD')
        col = box.column(align=True)
        col.prop(st, "use_baking")
        col.prop(st, "baking_threshold")
        if st.use_baking:
            col.prop(st, "baking_realize")
            col.prop(st, "baking_keep_source")
            col.prop(st, "baking_auto_hint")
            box.label(text="原砖会被隐藏，改由几何节点实例化", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.6
        if st.use_baking:
            col.operator(OP_GROW, icon='MOD_BUILD', text="烘焙生成（几何节点）")
        else:
            col.operator(OP_GROW, icon='PLAY')
        row = layout.row(align=True)
        row.operator(OP_CLEAR, icon='TRASH')


classes = (MF_PT_FloorGrowth,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
