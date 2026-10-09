
import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from . import planner
from .operators import OP_ID_RUN, OP_ID_TOGGLE, GROUP_STATE, SUMMARY

WRAP_WIDTH = 34

def wrap_text(text, width=WRAP_WIDTH):
    if not text:
        return []
    lines = []
    current = ""
    current_width = 0
    for char in text:
        char_width = 2 if ord(char) > 127 else 1
        if current_width + char_width > width and current:
            lines.append(current)
            current = ""
            current_width = 0
        current += char
        current_width += char_width
    if current:
        lines.append(current)
    return lines

class MF_PT_texrename(utils.MF_ToolPanel):
    bl_label = "名称转英文"
    bl_idname = "MF_PT_texrename"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("mczy", "texrename", "名称", "转英文", "改名", "英文")

    def draw_header(self, context):
        self.layout.label(text="", icon='FILE_IMAGE')

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.scale_y = 1.4
        chunks = (planner.GROUPS[:4], planner.GROUPS[4:])
        for chunk in chunks:
            row = col.row(align=True)
            for tag, label, _pfx in chunk:
                row.operator(OP_ID_TOGGLE, text=label,
                             depress=GROUP_STATE.get(tag, True)).tag = tag

        layout.separator()
        layout.operator(OP_ID_RUN, text="执行改名", icon='PLAY')
        layout.label(text="中文名改英文，文件另存副本", icon='INFO')

        if SUMMARY:
            box = layout.box()
            if "kinds" in SUMMARY:
                kinds = SUMMARY["kinds"]
                for name in sorted(kinds, key=lambda k: (-kinds[k], k)):
                    row = box.row()
                    row.label(text=name)
                    row.label(text=str(kinds[name]))
            else:
                for line in wrap_text(SUMMARY.get("text", "")):
                    box.label(text=line)

classes = (MF_PT_texrename,)

def register():
    utils.register_classes(classes)

def unregister():
    utils.unregister_classes(classes)
