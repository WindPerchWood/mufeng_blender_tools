import bpy

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import OP_APPLY_ID, OP_CLEAR_ID, SCENE_ATTR

PANEL_ID = "MF_PT_BatchRename"
REPORT_PREVIEW_LINES = 7

from .operators import MF_OT_BatchRename_Apply, MF_OT_BatchRename_ClearKeyword


class MF_PT_BatchRename(utils.MF_ToolPanel):
    bl_label = "批量重命名"
    bl_idname = PANEL_ID
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 19
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("plmm", "batchrename", "重命名", "批量改名", "改名")

    def draw_header(self, context):
        self.layout.label(text="", icon='FONT_DATA')

    def draw(self, context):
        st = getattr(context.scene, SCENE_ATTR, None)
        if st is None:
            self.layout.label(text="参数组未注册")
            return
        lay = self.layout

        self._draw_keyword(lay, st)
        self._draw_scope(lay, st)
        self._draw_targets(lay, st)
        self._draw_actions(lay, st)
        self._draw_report(lay, st)

    def _draw_keyword(self, lay, st):
        row = lay.row(align=True)
        row.label(text="名称")
        row.prop(st, "keyword", text="")
        row.operator(OP_CLEAR_ID, text="", icon="X")

    def _draw_scope(self, lay, st):
        lay.prop(st, "scope", expand=True)

    def _draw_targets(self, lay, st):
        row = lay.row(align=True)
        row.prop(st, "do_object")
        row.prop(st, "do_material")
        row.prop(st, "do_image")

        row = lay.row(align=True)
        row.prop(st, "skip_cameras")
        row.prop(st, "skip_lights")

        lay.prop(st, "rename_disk")

    def _draw_actions(self, lay, st):
        row = lay.row(align=True)
        self._action_button(row, "PREFIX", "加前缀")
        self._action_button(row, "SUFFIX", "加后缀")

        row = lay.row(align=True)
        self._action_button(row, "STRIP_PREFIX", "清除前缀")
        self._action_button(row, "STRIP_SUFFIX", "清除后缀")

        self._action_button(lay, "RENAME", "重命名")

    def _draw_report(self, lay, st):
        lay.separator()
        box = lay.box()
        if not st.last_report:
            box.label(text="还没有执行过", icon="INFO")
            return
        for line in st.last_report.splitlines()[:REPORT_PREVIEW_LINES]:
            box.label(text=line)

    @staticmethod
    def _action_button(lay, action, text):
        props = lay.operator(OP_APPLY_ID, text=text)
        props.action = action
        return props


classes = (MF_PT_BatchRename,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
