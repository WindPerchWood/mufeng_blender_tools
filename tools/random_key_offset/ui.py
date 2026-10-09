import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import DO_OP_ID, TOOL_ID, WM_ATTR

KEYWORDS = (
    "sjydgjz", "sjgjz", "suiji", "guanjianzhen", "gjz",
    "randomkey", "keyoffset", "keyframe", "movekeys", "retime", "offset",
    "time", "shift",
    "随机", "随机移动关键帧", "随机关键帧", "随机帧", "关键帧", "关键帧偏移",
    "偏移关键帧", "移动关键帧", "错帧", "错开", "打乱", "时间偏移",
)
PANEL_KEYWORDS = ("suijiyidongguanjianzhen", "randomkeyoffset") + KEYWORDS


def _props(context):
    return getattr(context.window_manager, WM_ATTR, None)


class MF_PT_RandomKeyOffset(utils.MF_ToolPanel):
    bl_label = "随机移动关键帧"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 13
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = PANEL_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='TIME')

    def draw(self, context):
        layout = self.layout
        props = _props(context)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        selected = list(context.selected_objects)
        if selected:
            layout.label(text=f"已选 {len(selected)} 个物体", icon='OBJECT_DATA')
        else:
            layout.label(text="未选中物体", icon='ERROR')

        row = layout.row(align=True)
        row.prop(props, "offset_min")
        row.prop(props, "offset_max")

        layout.prop(props, "selected_only", text="仅移动选中帧")

        row = layout.row()
        row.scale_y = 1.5
        row.operator(DO_OP_ID, text="移动", icon='PLAY')


classes = (MF_PT_RandomKeyOffset,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
