import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="MF Tools",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import (
    OP_ID,
    WM_ATTR,
    selected_mesh_objects,
)

TOOL_ID = "Separate"

MF_SEARCH_KEYWORDS = (
    "flwt", "fenli", "wtfl",
    "aysfl", "anysfl", "aidfl", "aydfl",
    "separate", "split", "detach", "loose", "looseparts", "element", "byid",
    "分离", "物体分离", "拆分", "拆开", "打散", "按元素", "按元素分离",
    "按ID", "按ID分离", "按材质", "材质ID", "元素",
)


class MF_PT_Separate(utils.MF_ToolPanel):
    bl_label = "物体分离"
    bl_idname = f"MF_PT_{TOOL_ID}"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 9
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = MF_SEARCH_KEYWORDS

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_BOOLEAN')

    def draw(self, context):
        layout = self.layout
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is None:
            layout.label(text="参数未就绪，请重载插件", icon='ERROR')
            return

        meshes = selected_mesh_objects(context)
        if not meshes:
            layout.label(text="请先选中网格物体", icon='ERROR')
        elif len(meshes) == 1:
            layout.label(text=f"目标：{meshes[0].name}", icon='OBJECT_DATA')
        else:
            layout.label(text=f"目标：{len(meshes)} 个网格物体", icon='OBJECT_DATA')

        layout.prop(props, "mode", expand=True)

        row = layout.row()
        row.scale_y = 1.5
        op = row.operator(OP_ID, text="分离", icon='MOD_BOOLEAN')
        op.mode = props.mode
        row.enabled = bool(meshes)


classes = (MF_PT_Separate,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
