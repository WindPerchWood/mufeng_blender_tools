import bpy

from . import prefs, utils

POPUP_WIDTH = 340
POPUP_COLUMNS = 2

TOOL_LIST = []


def set_tool_list(infos):
    TOOL_LIST.clear()
    TOOL_LIST.extend(infos)
    try:
        prefs.sync_tool_entries([tid for tid, _ in infos])
    except Exception as exc:
        utils.report("ERROR", f"同步工具显示开关失败: {exc}")


class MF_OT_SettingsToggle(bpy.types.Operator):
    bl_idname = "mf.settings_toggle"
    bl_label = "工具显示设置"
    bl_description = "打开/关闭工具显示设置（勾选决定哪些工具面板显示）"
    bl_options = {'REGISTER'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        if not TOOL_LIST:
            self.report({'WARNING'}, "暂无工具可设置")
            return {'CANCELLED'}
        wm = context.window_manager
        win = context.window

        # 弹窗默认出现在鼠标处，这里临时把光标挪到窗口中心让弹窗居中，
        # 弹出后立刻把光标移回原位，鼠标不动
        rows = (len(TOOL_LIST) + POPUP_COLUMNS - 1) // POPUP_COLUMNS
        popup_h = 40 + rows * 22 + 46
        orig = (event.mouse_x, event.mouse_y)
        x = (win.width - POPUP_WIDTH) // 2
        y = (win.height + popup_h) // 2
        y = max(popup_h + 8, min(y, win.height - 8))
        try:
            win.cursor_warp(int(x), int(y))
        except Exception:
            pass

        result = wm.invoke_popup(self, width=POPUP_WIDTH)

        try:
            win.cursor_warp(int(orig[0]), int(orig[1]))
        except Exception:
            pass
        return result

    def draw(self, context):
        layout = self.layout
        flow = layout.grid_flow(
            row_major=True, columns=POPUP_COLUMNS,
            even_columns=True, even_rows=True, align=True,
        )
        for tool_id, label in TOOL_LIST:
            item = prefs.get_item(tool_id)
            if item is None:
                continue
            flow.prop(item, "enabled", text=label)

        row = layout.row(align=True)
        row.operator(MF_OT_ToolsShowAll.bl_idname, text="全部显示")
        row.operator(MF_OT_ToolsHideAll.bl_idname, text="全部隐藏")


class MF_OT_ToolsShowAll(bpy.types.Operator):
    bl_idname = "mf.tools_show_all"
    bl_label = "全部显示"
    bl_description = "显示全部工具面板"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        prefs.set_all(True)
        return {'FINISHED'}


class MF_OT_ToolsHideAll(bpy.types.Operator):
    bl_idname = "mf.tools_hide_all"
    bl_label = "全部隐藏"
    bl_description = "隐藏全部工具面板（搜索栏和设置面板不受影响）"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        prefs.set_all(False)
        return {'FINISHED'}


classes = (MF_OT_SettingsToggle, MF_OT_ToolsShowAll, MF_OT_ToolsHideAll)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
