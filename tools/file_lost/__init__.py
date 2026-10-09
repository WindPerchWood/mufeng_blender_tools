import bpy

from . import operators
from . import ui


def register():
    operators.register()
    ui.register()
    bpy.types.Scene.mf_filelost_settings = bpy.props.PointerProperty(
        type=operators.MF_PG_FileLostSettings)
    bpy.types.WindowManager.mf_filelost_view = bpy.props.PointerProperty(
        type=ui.MF_PG_FileLostView)


def unregister():
    del bpy.types.WindowManager.mf_filelost_view
    del bpy.types.Scene.mf_filelost_settings
    ui.unregister()
    operators.unregister()
