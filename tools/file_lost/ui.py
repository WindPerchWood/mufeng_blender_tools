import bpy

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (OP_SCAN, OP_RECONNECT, OP_ROOT_ADD, OP_ROOT_REMOVE,
                        OP_ITEM_ACTIVATE, KIND_ICONS)

VIEW_ROWS = 10


class MF_PG_FileLostView(bpy.types.PropertyGroup):
    scroll: bpy.props.FloatProperty(
        name="列表滚动", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="资源列表的滚动位置")


class MF_PT_FileLost(utils.MF_ToolPanel):
    bl_label = "检查丢失贴图"
    bl_idname = "MF_PT_FileLost"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("jcdstt", "filelost", "losttexture", "丢失", "贴图")

    def draw_header(self, context):
        self.layout.label(text="", icon='ORPHAN_DATA')

    def draw(self, context):
        st = context.scene.mf_filelost_settings
        view = context.window_manager.mf_filelost_view
        layout = self.layout

        layout.operator(OP_SCAN, icon='FILE_REFRESH')

        box = layout.box()
        box.label(text="状态：%s" % st.last_message)

        self._draw_items(layout, st, view)

        layout.operator(OP_RECONNECT, icon='FILE_TICK')

        self._draw_roots(layout, st)

    @staticmethod
    def _draw_items(layout, st, view):
        n = len(st.items)
        max_start = max(0, n - VIEW_ROWS)
        start = min(int(round(view.scroll * max_start)), max_start)
        end = min(start + VIEW_ROWS, n)

        box = layout.box()
        for i in range(start, end):
            it = st.items[i]
            row = box.row(align=True)
            op = row.operator(OP_ITEM_ACTIVATE, text=it.label,
                              icon=KIND_ICONS.get(it.kind, 'QUESTION'),
                              emboss=False, depress=(i == st.active_index))
            op.index = i
            if it.status == 'FOUND':
                row.label(text="", icon='CHECKMARK')

        if n > VIEW_ROWS:
            row = box.row()
            row.prop(view, "scroll", text="", slider=True)

    @staticmethod
    def _draw_roots(layout, st):
        layout.operator(OP_ROOT_ADD, icon='ADD')

        box = layout.box()
        for i, root in enumerate(st.search_roots):
            r = box.row(align=True)
            r.prop(root, "path", text="")
            op = r.operator(OP_ROOT_REMOVE, text="", icon='X')
            op.index = i


classes = (MF_PG_FileLostView, MF_PT_FileLost)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
