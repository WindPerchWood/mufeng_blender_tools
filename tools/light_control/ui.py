import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import HIDE_ID, OFF_ID, ON_ID, UNHIDE_ID

TOOL_ID = "LightControl"

PANEL_KEYWORDS = (
    "dggj", "dg", "deng", "dengguang", "kaiguan", "guandeng", "kaideng",
    "gbdeng", "kddeng", "yincangdeng", "xianshideng", "tubiao", "tubiaoq",
    "light", "lights", "lighttools", "lighting", "lamp", "toggle", "onoff",
    "hide", "unhide", "show", "off", "on", "icon", "icons", "overlay", "extras",
    "灯光", "灯光工具", "灯", "关灯", "开灯", "关闭灯光", "打开灯光",
    "关闭所有灯光", "打开所有灯光", "隐藏灯光", "显示灯光", "显示", "隐藏",
    "开关", "关掉灯光", "图标", "灯图标", "叠加层", "附加项", "场",
)


class MF_PT_LightControl(utils.MF_ToolPanel):
    bl_label = "灯光工具"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 12
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='LIGHT')

    def draw(self, context):
        layout = self.layout

        selected = list(context.selected_objects)
        lights = [o for o in selected if o.type == 'LIGHT']
        if lights:
            layout.label(text=f"已选 {len(lights)} 盏灯光", icon='LIGHT')
        elif selected:
            layout.label(text=f"已选 {len(selected)} 个对象（无灯光）", icon='OBJECT_DATA')
        else:
            layout.label(text="未选中 → 关闭/打开全部灯光", icon='LIGHT')

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator(OFF_ID, text="关闭所有/选中灯光", icon='LIGHT')
        col.operator(ON_ID, text="打开所有/选中灯光", icon='LIGHT')

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator(HIDE_ID, text="隐藏灯光", icon='HIDE_ON')
        row.operator(UNHIDE_ID, text="显示灯光", icon='HIDE_OFF')


classes = (MF_PT_LightControl,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
