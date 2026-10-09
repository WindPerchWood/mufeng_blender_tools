bl_info = {
    "name": "MF Tools (MF Blender Tools)",
    "author": "MF",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D视图 > 右侧栏 > MF Tools",
    "description": "Blender 工具集合：单入口插件包 + 按功能分包的自动挂载架构",
    "category": "Interface",
}


import importlib
import pkgutil

import bpy

from .core import prefs
from .core import search
from .core import settings
from .core import utils

_SUBPACKAGES = []


def _discover_tools():
    from . import tools
    importlib.reload(tools)

    found = []
    for info in pkgutil.iter_modules(tools.__path__):
        try:
            mod = importlib.import_module(f".tools.{info.name}", __package__)
            importlib.reload(mod)
        except Exception as exc:
            utils.report("ERROR", f"子包 {info.name} 载入失败: {exc}")
            continue
        if hasattr(mod, "register"):
            found.append(mod)
        else:
            utils.report("WARNING", f"子包 {info.name} 没有 register()，已跳过")
    # N 面板顺序 = 子包文件夹名字母序，新工具加入后自动插位，无需手改 bl_order
    found.sort(key=lambda m: m.__name__.rsplit(".", 1)[-1])
    return found


def _assign_panel_order(mods):
    """按文件夹字母序给各工具主面板改写 bl_order（在 register_class 之前生效）。

    只改"继承 MF_ToolPanel、带 bl_order、无 bl_parent_id"的主面板；
    子面板（book_shelf 分区、shatter 子卷展栏等）挂父面板下，内部排序不受影响。
    """
    for index, mod in enumerate(mods):
        ui_mod = getattr(mod, "ui", mod)
        for name in dir(ui_mod):
            cls = getattr(ui_mod, name)
            if (isinstance(cls, type)
                    and issubclass(cls, utils.MF_ToolPanel)
                    and cls is not utils.MF_ToolPanel
                    and getattr(cls, "bl_order", None) is not None
                    and not getattr(cls, "bl_parent_id", "")):
                cls.bl_order = index
                break


def _collect_tool_meta(mods):
    infos = []
    for mod in mods:
        tool_id = mod.__name__.rsplit(".", 1)[-1]
        ui_mod = getattr(mod, "ui", mod)
        label = tool_id
        for name in dir(ui_mod):
            cls = getattr(ui_mod, name)
            if (isinstance(cls, type)
                    and issubclass(cls, utils.MF_ToolPanel)
                    and cls is not utils.MF_ToolPanel):
                try:
                    cls.MF_TOOL_ID = tool_id
                except Exception:
                    pass
                if not getattr(cls, "bl_parent_id", "") and getattr(cls, "bl_label", ""):
                    label = cls.bl_label
        infos.append((tool_id, label))
    return infos


def register():
    _SUBPACKAGES.clear()
    prefs.register()
    search.register()
    settings.register()
    _SUBPACKAGES.extend(_discover_tools())
    _assign_panel_order(_SUBPACKAGES)
    settings.set_tool_list(_collect_tool_meta(_SUBPACKAGES))
    for mod in _SUBPACKAGES:
        try:
            mod.register()
        except Exception as exc:
            utils.report("ERROR", f"{mod.__name__} 注册失败: {exc}")
    utils.report("INFO", f"MF Tools已加载，挂载 {len(_SUBPACKAGES)} 个工具")


def unregister():
    for mod in reversed(_SUBPACKAGES):
        try:
            mod.unregister()
        except Exception as exc:
            utils.report("ERROR", f"{mod.__name__} 注销失败: {exc}")
    _SUBPACKAGES.clear()
    settings.unregister()
    search.unregister()
    prefs.unregister()


if __name__ == "__main__":
    register()
