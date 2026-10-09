import bpy

from ...core import utils
from .operators import MF_OT_Keyconfig_Toggle, active_name, is_enabled

TOOL_ID = "Keyconfig"


class MF_PT_Keyconfig(utils.MF_ToolPanel):
    bl_label = "键位方案"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "jwfa", "jianwei", "keyconfig", "keymap", "key", "hotkey", "max",
        "键位", "快捷键", "按键", "3dsmax",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='TOOL_SETTINGS')

    def draw(self, context):
        layout = self.layout
        on = is_enabled(context)
        current = active_name(context) or "未知"

        layout.label(text=f"当前方案：{current}", icon='INFO' if on else 'BLANK1')

        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator(
            MF_OT_Keyconfig_Toggle.bl_idname,
            text="使用我的键位方案" if on else "使用 Blender 默认键位",
            icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT',
            depress=on,
        )


classes = (MF_PT_Keyconfig,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
