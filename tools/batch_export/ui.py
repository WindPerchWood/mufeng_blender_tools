import bpy

from ...core import utils
from .operators import MF_OT_BatchExport_Run, available_exporters

TOOL_ID = "BatchExport"


class MF_PT_BatchExport(utils.MF_ToolPanel):
    bl_label = "批量导出"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "pldc", "daochu", "export", "batch", "save",
        "fbx", "obj", "gltf", "glb", "stl", "ply", "usd", "usdc",
        "alembic", "abc", "bvh", "grease", "svg", "pdf", "格式",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='EXPORT')

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.scale_y = 1.4
        row.operator(MF_OT_BatchExport_Run.bl_idname, icon='FILE_3D')
        box = layout.box()
        box.label(text=f"已选对象: {len(context.selected_objects)}")
        try:
            count = len(available_exporters())
        except Exception:
            count = 0
        box.label(text=f"可用导出格式: {count} 种（文件 > 导出）")


classes = (MF_PT_BatchExport,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
