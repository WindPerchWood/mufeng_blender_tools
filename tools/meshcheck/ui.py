import bpy

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from . import markers
from . import operators as ops
from .operators import OP_ID_RUN, OP_ID_CLEAR, OP_ID_TOGGLE

ICON_OPEN = 'TRIA_DOWN'
ICON_CLOSED = 'TRIA_RIGHT'

RESULT_ROWS = (
    ("color_flip", "反转法线", "result_flip"),
    ("color_nonmanifold", "非流形边", "result_nonmanifold"),
    ("color_overlap", "重叠面", "result_overlap"),
)

HELP_LINES = (
    "只检测，不改模型：全程只读网格，原始数据一个字都不动。",
    "红=反转法线，黄=非流形边，蓝=重叠面，颜色可在上面改。",
    "网格不封闭时会自动跳过反转法线检测，避免误报；",
    "需要强行检查时，打开「开放网格也查法线」。",
    "再点一次【模型体检】会重建标记；点【清除标记】全部撤掉。",
)

def _section_header(layout, section, title, is_open):
    row = layout.row(align=True)
    row.alignment = 'LEFT'
    op = row.operator(
        OP_ID_TOGGLE,
        text=title,
        icon=ICON_OPEN if is_open else ICON_CLOSED,
        emboss=False,
    )
    op.section = section

class MF_PT_MeshCheck(utils.MF_ToolPanel):
    bl_label = "模型体检"
    bl_idname = "MF_PT_MeshCheck"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("mxhj", "meshcheck", "模型体检", "体检", "mesh check")

    def draw_header(self, context):
        self.layout.label(text="", icon='ZOOM_SELECTED')

    def draw(self, context):
        st = markers.settings(context)
        layout = self.layout

        if st is None:
            layout.label(text="模型体检未就绪", icon='ERROR')
            return

        self._draw_button(layout, st)
        self._draw_result(layout, st)
        self._draw_check(layout, st)
        self._draw_param(layout, st)
        self._draw_help(layout, st)

    def _draw_button(self, layout, st):
        col = layout.column()
        col.scale_y = 1.6
        op = col.operator(OP_ID_RUN, text="模型体检", icon='ZOOM_SELECTED')
        op.show_popup = st.show_popup

    def _draw_result(self, layout, st):
        if not st.has_result:
            col = layout.column()
            col.label(text="选中网格物体后点上方按钮", icon='INFO')
            col.label(text="  红=反转法线 · 黄=非流形边 · 蓝=重叠面")
            return

        box = layout.box()
        box.label(text="检测结果（%d 个物体）" % st.result_objects, icon='CHECKMARK')
        for color_prop, title, count_prop in RESULT_ROWS:
            row = box.row(align=True)
            row.prop(st, color_prop, text="")
            row.label(text=title)
            sub = row.row()
            sub.alignment = 'RIGHT'
            sub.label(text=str(getattr(st, count_prop)))

        for note in (st.note_flip, st.note_nonmanifold, st.note_overlap):
            if note:
                box.label(text=note, icon='INFO')

        row = box.row(align=True)
        row.label(text="标记方块：%d 个物体" % st.marker_objects, icon='VIEWZOOM')

    def _draw_check(self, layout, st):
        _section_header(layout, "check", "① 检测项目", st.sec_check)
        if not st.sec_check:
            return
        col = layout.column()
        col.prop(st, "check_flip")
        col.prop(st, "check_nonmanifold")
        col.prop(st, "check_overlap")
        col.separator()
        col.prop(st, "flip_on_open")

    def _draw_param(self, layout, st):
        _section_header(layout, "param", "② 参数与标记", st.sec_param)
        if not st.sec_param:
            return
        col = layout.column()
        col.prop(st, "overlap_tolerance")
        col.prop(st, "max_markers")
        col.prop(st, "marker_percent")
        col.separator()
        col.prop(st, "markers_show_in_front")
        col.prop(st, "markers_hide_render")
        col.prop(st, "use_evaluated")
        col.prop(st, "show_popup")
        col.separator()
        col.label(text="方块颜色")
        row = col.row(align=True)
        for color_prop, _title, _count in RESULT_ROWS:
            row.prop(st, color_prop, text="")
        col.separator()
        col.operator(OP_ID_CLEAR, text="清除标记", icon='TRASH')

    def _draw_help(self, layout, st):
        _section_header(layout, "help", "③ 说明", st.sec_help)
        if not st.sec_help:
            return
        col = layout.column()
        for line in HELP_LINES:
            col.label(text=line)

classes = (
    MF_PT_MeshCheck,
)

def register():
    utils.register_classes(classes)

def unregister():
    utils.unregister_classes(classes)
