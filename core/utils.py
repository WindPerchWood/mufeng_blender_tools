import bpy

PANEL_CATEGORY = "MF Tools"


class MF_ToolPanel(bpy.types.Panel):
    MF_SEARCH_KEYWORDS = ()

    @classmethod
    def poll(cls, context):

        from . import search
        return search.panel_visible(cls, context)


def register_classes(classes):
    for c in classes:
        try:
            bpy.utils.register_class(c)
        except Exception as exc:
            print(f"[MF Tools] 注册失败 {c.__name__}: {exc}")


def unregister_classes(classes):
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception as exc:
            print(f"[MF Tools] 注销失败 {c.__name__}: {exc}")


def get_prefs():
    return bpy.context.preferences.addons[__package__.split(".")[0]].preferences


def report(level, message):
    print(f"[MF Tools] {level}: {message}")
