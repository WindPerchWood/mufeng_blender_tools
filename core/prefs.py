import bpy

from . import utils

ADDON_ID = __name__.split(".")[0]


class MF_ToolToggle(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="启用",
        description="勾选后该工具面板显示在 N 面板中",
        default=True,
    )


class MF_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    export_dir: bpy.props.StringProperty(
        name="默认导出目录",
        subtype='DIR_PATH',
        default="//export",
    )
    show_debug: bpy.props.BoolProperty(
        name="显示调试信息",
        default=False,
    )
    tools: bpy.props.CollectionProperty(type=MF_ToolToggle)


classes = (MF_ToolToggle, MF_AddonPreferences)


def _find_item(prefs, tool_id):
    for item in prefs.tools:
        if item.name == tool_id:
            return item
    return None


def sync_tool_entries(tool_ids):
    p = utils.get_prefs()
    old = {item.name: item.enabled for item in p.tools}
    p.tools.clear()
    for tid in tool_ids:
        item = p.tools.add()
        item.name = tid
        item.enabled = old.get(tid, True)


def get_item(tool_id):
    try:
        return _find_item(utils.get_prefs(), tool_id)
    except Exception:
        return None


def is_tool_enabled(tool_id):
    if not tool_id:
        return True
    item = get_item(tool_id)
    return True if item is None else item.enabled


def set_tool_enabled(tool_id, enabled):
    item = get_item(tool_id)
    if item is not None:
        item.enabled = enabled


def set_all(enabled):
    p = utils.get_prefs()
    for item in p.tools:
        item.enabled = enabled


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
