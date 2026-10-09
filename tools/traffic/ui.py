
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
        PANEL_CATEGORY="木风工具箱",
        MF_ToolPanel=bpy.types.Panel,
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

from . import props

from .operators import (
    OP_ACTIVATE_CAR,
    OP_ACTIVATE_ROAD,
    OP_APPLY_DURATION,
    OP_CLEAR_ALL,
    OP_COMPUTE,
    OP_OFFSET_ALL,
    OP_PICK_CARS,
    OP_PICK_ROADS,
    OP_REMOVE_CAR,
    OP_REMOVE_ROAD,
    current_road,
)


class MF_PT_Traffic(utils.MF_ToolPanel):
    bl_idname = "MF_PT_Traffic"
    bl_label = "车辆道路生成系统"
    bl_description = "沿道路曲线批量铺排车流：路径约束 + 随机前后偏移 + 帧数可控的循环动画"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 16
    bl_options = {"DEFAULT_CLOSED"}

    MF_SEARCH_KEYWORDS = ("clsc", "traffic", "cheliu", "车流", "车流生成",
                          "车辆道路生成系统", "道路", "路径动画")

    def draw_header(self, context):
        self.layout.label(text="", icon='AUTO')

    def draw(self, context):
        layout = self.layout
        st = getattr(context.scene, props.SCENE_ATTR, None)
        if st is None:
            layout.label(text="参数未就绪，请重新启用插件", icon="ERROR")
            return

        _draw_pick(layout, st)
        layout.separator()
        _draw_scope(layout, st)
        layout.separator()
        _draw_generate(layout, st)
        layout.separator()
        _draw_duration(layout, st)
        layout.separator()
        _draw_global(layout, st)
        layout.separator()
        _draw_cleanup(layout)

        if st.last_report and st.show_report:
            box = layout.box()
            box.label(text=st.last_report, icon="INFO")


def _draw_pick(layout, st):
    col = layout.column(align=True)
    col.label(text="拾取", icon="EYEDROPPER")

    row = col.row(align=True)
    row.operator(OP_PICK_ROADS, icon="CURVE_DATA")
    row.operator(OP_PICK_CARS, icon="MESH_DATA")

    col.separator(factor=0.5)
    col.label(text="道路 (%d)" % len(st.roads))
    _draw_name_list(col, st, st.roads, "road_index", OP_ACTIVATE_ROAD)
    row = col.row(align=True)
    op = row.operator(OP_REMOVE_ROAD, text="移除选中道路", icon="REMOVE")
    op.index = st.road_index
    row.enabled = bool(st.roads)

    col.separator(factor=0.5)
    col.label(text="车辆 (%d)" % len(st.cars))
    _draw_name_list(col, st, st.cars, "car_index", OP_ACTIVATE_CAR)
    row = col.row(align=True)
    op = row.operator(OP_REMOVE_CAR, text="移除选中车辆", icon="REMOVE")
    op.index = st.car_index
    row.enabled = bool(st.cars)


def _draw_scope(layout, st):
    road = current_road(st)
    box = layout.box()
    if road is None:
        box.alert = True
        box.label(text="还没选道路：请在「道路」列表里点一条", icon="ERROR")
    else:
        box.label(text="作用范围：%s" % road.name, icon="CURVE_DATA")
        box.label(text="下面按钮只动这条路上的车")


def _draw_generate(layout, st):
    col = layout.column(align=True)
    col.label(text="生成", icon="DUPLICATE")

    col.prop(st, "car_count")

    col.operator(OP_COMPUTE, icon="PLAY")


def _draw_duration(layout, st):
    col = layout.column(align=True)
    col.label(text="循环速度", icon="TIME")

    col.prop(st, "anim_start_frame")
    col.prop(st, "loop_frames")

    col.label(text="帧数越小走得越快（速度 = 曲线长度 ÷ 帧数）", icon="INFO")
    col.label(text="闭合曲线绕一圈、开放曲线走完整条，走完立刻重来")
    col.operator(OP_APPLY_DURATION, icon="PLAY")


def _draw_global(layout, st):
    col = layout.column(align=True)
    col.label(text="整体调节", icon="WORLD")

    col.prop(st, "global_offset")
    col.operator(OP_OFFSET_ALL, icon="SORT_DESC")


def _draw_cleanup(layout):
    col = layout.column(align=True)
    col.row(align=True).operator(OP_CLEAR_ALL, icon="TRASH")


def _draw_name_list(layout, st, items, index_attr, activate_idname):
    box = layout.box()
    if not len(items):
        box.label(text="（空）", icon="INFO")
        return
    active = getattr(st, index_attr)
    for i, it in enumerate(items):
        row = box.row(align=True)
        op = row.operator(
            activate_idname, text=it.name, emboss=False,
            icon=it.icon or "OBJECT_DATA",
            depress=(i == active),
        )
        op.index = i


classes = (
    MF_PT_Traffic,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
