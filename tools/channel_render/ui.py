import os

import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from . import operators
from .operators import iter_target_objects, collect_materials


class MF_PT_channel(utils.MF_ToolPanel):
    bl_label = "一键通道渲染"
    bl_idname = "MF_PT_channel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("tdxr", "channelrender", "channel", "通道", "通道渲染")

    def draw_header(self, context):
        self.layout.label(text="", icon='RENDER_STILL')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.mf_channel

        try:
            objects = iter_target_objects(context, settings.only_selected)
            if settings.mode == "OBJECT":
                summary = "{} 个物体".format(len(objects))
            else:
                summary = "{} 个物体 · {} 个材质".format(
                    len(objects), len(collect_materials(objects))
                )
        except Exception:
            summary = "—"
        row = layout.row()
        row.label(text=summary, icon='INFO')

        column = layout.column(align=True)
        column.label(text="通道类型")
        column.row().prop(settings, "mode", expand=True)

        column = layout.column(align=True)
        column.prop(settings, "seed")

        row = column.row(align=True)
        row.prop(settings, "transparent", toggle=True)
        row.prop(settings, "only_selected", toggle=True)

        column.prop(settings, "show_result")
        column.prop(settings, "output_dir")

        if not bpy.data.filepath and (settings.output_dir or "").strip().startswith("//"):
            row = layout.row()
            row.alert = True
            row.label(text=".blend 未存盘，将输出到临时目录", icon='ERROR')

        if settings.last_output:
            box = layout.box()
            box.label(text="最近输出")
            column = box.column(align=True)
            column.label(text=os.path.basename(settings.last_output))
            folder = os.path.dirname(settings.last_output)
            column.label(text=folder)
            box.operator("mf.channel_open_folder", icon='FILEBROWSER')

        if operators._SAVED["active"]:
            column = layout.column(align=True)
            column.alert = True
            column.operator("mf.channel_restore", icon='LOOP_BACK')

        column = layout.column()
        column.operator("mf.channel_render")


classes = (MF_PT_channel,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
