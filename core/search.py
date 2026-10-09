import bpy
from bpy.props import PointerProperty, StringProperty

from . import prefs, utils

WM_ATTR = "mf_search"
PANEL_ID = "MF_PT_SearchBar"
SEARCH_ORDER = -100


def _tag_redraw(context=None):
    try:
        wm = (context or bpy.context).window_manager
    except Exception:
        return
    for win in wm.windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _on_query_changed(self, context):
    _tag_redraw(context)


class MF_PG_SearchState(bpy.types.PropertyGroup):
    query: StringProperty(
        name="搜索工具",
        description="按工具名或关键词过滤下方面板；空格分隔多个关键词（需全部命中）",
        default="",

        options={'TEXTEDIT_UPDATE'},
        update=_on_query_changed,
    )


def state(context):
    return getattr(context.window_manager, WM_ATTR, None)

def query_of(context):
    try:
        st = state(context)
        return st.query if st else ""
    except Exception:
        return ""


def normalize(text):
    return " ".join(str(text or "").split()).lower()

def match_tool(label, keywords, query):
    tokens = normalize(query).split()
    if not tokens:
        return True
    haystack = " ".join([label or ""] + list(keywords or ())).lower().replace(" ", "")
    return all(tok in haystack for tok in tokens)


def panel_visible(cls, context):
    try:
        tool_id = getattr(cls, "MF_TOOL_ID", "")
        if tool_id and not prefs.is_tool_enabled(tool_id):
            return False
        query = query_of(context)
        if not query:
            return True
        return match_tool(
            getattr(cls, "bl_label", ""),
            getattr(cls, "MF_SEARCH_KEYWORDS", ()),
            query,
        )
    except Exception:
        return True


class MF_PT_SearchBar(bpy.types.Panel):
    bl_label = "搜索工具"
    bl_idname = PANEL_ID
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = SEARCH_ORDER
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        st = state(context)
        if st is None:
            layout.label(text="搜索未就绪，请重载插件", icon='ERROR')
            return

        row = layout.row(align=True)
        row.prop(st, "query", text="", icon='VIEWZOOM')
        row.operator("mf.settings_toggle", text="", icon='PREFERENCES')


classes = (MF_PG_SearchState, MF_PT_SearchBar)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR, PointerProperty(type=MF_PG_SearchState))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
