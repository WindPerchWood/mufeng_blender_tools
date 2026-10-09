import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import KEY_OP_ID, OP_ID, WM_ATTR

TOOL_ID = "Visibility"

PANEL_KEYWORDS = (
    "ggkjx", "kjx", "keshixing", "yincang", "xianshi", "xianying", "bantouming",
    "touming", "dante", "dantechu", "baoliu", "tietu", "alpha", "opacity", "fade",
    "fadeout", "keyframe", "key",
    "visibility", "vis", "hide", "unhide",
    "show", "toggle", "changjing",
    "可见性", "更改可见性", "可见", "隐藏", "显示", "显隐", "隐藏物体", "显示物体",
    "半透明", "透明", "淡出", "淡入", "渐隐", "渐现", "整体透明", "保留贴图", "关键帧", "K帧", "场",
)


class MF_PT_Visibility(utils.MF_ToolPanel):
    bl_label = "更改可见性"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 11
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='HIDE_OFF')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        selected = list(context.selected_objects)
        if selected:
            layout.label(text=f"已选 {len(selected)} 个物体", icon='OBJECT_DATA')
        else:
            layout.label(text="未选中物体", icon='ERROR')

        col = layout.column(align=True)
        col.prop(props, "value", slider=True)

        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator(OP_ID, text="更改可见性", icon='HIDE_OFF').value = props.value
        row.operator(KEY_OP_ID, text="", icon='KEYFRAME').value = props.value


classes = (MF_PT_Visibility,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
