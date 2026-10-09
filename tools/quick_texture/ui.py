import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="Toolbox",
                                  MF_ToolPanel=bpy.types.Panel)

from .operators import QUICKTEXTURE_OT_apply, OP_ID


class QUICKTEXTURE_PT_main(utils.MF_ToolPanel):
    bl_label = "一键贴图"
    bl_idname = "QUICKTEXTURE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = (
        "yjt", "yijiantietu", "tietu", "texture", "tex", "uv", "map", "material",
        "贴图", "纹理", "材质", "图片",
    )

    def draw_header(self, context):
        self.layout.label(text="", icon='TEXTURE')

    def draw(self, context):
        layout = self.layout
        sel = [o for o in context.selected_objects if getattr(o, "data", None)]
        layout.label(text=f"已选 {len(sel)} 个对象" if sel else "未选中对象",
                     icon='INFO' if sel else 'ERROR')

        row = layout.row()
        row.scale_y = 1.4
        row.operator(OP_ID, text="选择贴图并应用", icon='FILE_IMAGE')

        layout.label(text="弹窗里可设 UV / 材质方式", icon='BLANK1')


classes = (QUICKTEXTURE_PT_main,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
