"""【打包归档】N 面板：只负责画界面，业务全调 operators 里的操作符。"""

import os

import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from . import operators
from .operators import OP_COLLECT, OP_OPEN_DIR


class MF_PT_Archive(utils.MF_ToolPanel):
    bl_label = "打包归档"
    bl_idname = "MF_PT_Archive"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("dgbg", "archive", "打包", "归档", "zip", "收集")

    def draw_header(self, context):
        self.layout.label(text="", icon='PACKAGE')

    def draw(self, context):
        layout = self.layout
        state = operators.STATE

        box = layout.box()
        box.label(text="归档", icon='DISCLOSURE_TRI_DOWN')
        box.label(text="保存位置和文件名在点归档时选。")
        box.operator(OP_COLLECT, icon='PACKAGE')
        if not operators.source_blend():
            box.label(text="工程还没存过盘，也能直接归档。")

        if state["last_status"]:
            box.label(text=state["last_status"][:64])
            if state["last_detail"]:
                box.label(text=state["last_detail"][:64])
            if state["last_output"]:
                box.label(text="产物：%s" % os.path.basename(state["last_output"])[:44])
            grid = box.grid_flow(columns=2, even_columns=True, align=True)
            grid.label(text="文件 %d" % state["last_files"])
            grid.label(text="缓存目录 %d" % state["last_dirs"])
        row = box.row(align=True)
        row.operator(OP_OPEN_DIR, icon='FILE_FOLDER')


classes = (MF_PT_Archive,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
