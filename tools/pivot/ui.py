import bpy

from ...core import utils
from .operators import MF_OT_Pivot_Set

TOOL_ID = "Pivot"


class MF_PT_Pivot(utils.MF_ToolPanel):
    bl_label = "变换轴心"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "bhzx", "zhouxin", "pivot", "pivotpoint", "axis", "center",
        "轴点", "中心点", "坐标原点", "原点",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='PIVOT_BOUNDBOX')

    BUTTONS = (
        ("X_MAX", "X_max"), ("X_MIN", "X_min"),
        ("Y_MAX", "Y_max"), ("Y_MIN", "Y_min"),
        ("Z_MAX", "Z_max"), ("Z_MIN", "Z_min"),
        ("CENTER", "中心"), ("RANDOM", "随机"),
    )

    def draw(self, context):
        layout = self.layout
        sel = context.selected_objects
        layout.label(text=f"已选 {len(sel)} 个对象" if sel else "未选中对象",
                     icon='INFO' if sel else 'ERROR')

        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True)
        for key, label in self.BUTTONS:
            grid.operator(MF_OT_Pivot_Set.bl_idname, text=label).pos_type = key


classes = (MF_PT_Pivot,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
