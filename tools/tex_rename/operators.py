import bpy
from bpy.props import StringProperty

try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    def _fallback_register(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _fallback_unregister(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(
        PANEL_CATEGORY="木风工具箱",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

from . import planner

TOOL_ID = "TexRename"
OP_ID_RUN = f"mf.{TOOL_ID.lower()}_run"
OP_ID_TOGGLE = f"mf.{TOOL_ID.lower()}_toggle"
OP_ID_ALERT = f"mf.{TOOL_ID.lower()}_alert"

GROUP_STATE = {tag: True for tag, _label, _pfx in planner.GROUPS}

SUMMARY = {}


def _settings_from_op(op):
    settings = planner.Settings()
    settings.blend_stem = planner.blend_stem()
    for tag, _label, default_pfx in planner.GROUPS:
        settings.groups[tag] = bool(GROUP_STATE.get(tag, True))
        settings.prefixes[tag] = (getattr(op, "pfx_" + tag, "") or default_pfx)
    return settings


class MF_OT_texrename_run(bpy.types.Operator):
    bl_idname = OP_ID_RUN
    bl_label = "执行改名"
    bl_description = ("按面板勾选的类型批量把中文名改成英文名；贴图/缓存文件另存英文名副本，"
                      "原文件保留\n"
                      "命名规则：mat_0001、map_0001、hdri_0001、cache_0001、lib_0001、"
                      "ies_0001、pts_0001、obj_0001")
    bl_options = {'REGISTER'}

    pfx_material: StringProperty(name="材质名前缀", default="mat_")
    pfx_image: StringProperty(name="贴图前缀", default="map_")
    pfx_hdri: StringProperty(name="HDRI 前缀", default="hdri_")
    pfx_cache: StringProperty(name="外部缓存前缀", default="cache_")
    pfx_library: StringProperty(name="链接库前缀", default="lib_")
    pfx_ies: StringProperty(name="IES 前缀", default="ies_")
    pfx_pointcache: StringProperty(name="点缓存前缀", default="pts_")
    pfx_object: StringProperty(name="物体名前缀", default="obj_")

    def execute(self, context):
        settings = _settings_from_op(self)
        if planner.count_groups(settings) == 0:
            self.report({'WARNING'}, "所有分组都关着，没有可执行的动作")
            return {'CANCELLED'}
        plan = planner.build_plan(settings)
        if not plan.records:
            self.report({'INFO'}, "没有发现需要改名的中文名，什么都不会改")
            return {'CANCELLED'}
        stats, elapsed = planner.run_plan(plan.records)
        text = planner.format_stats(stats, elapsed)
        if plan.truncated:
            text += "（清单已达上限 %d 条）" % planner.MAX_RECORDS
        SUMMARY.clear()
        if stats.get(planner.ST_FAIL):
            SUMMARY["text"] = text
            self.report({'WARNING'}, text)
            bpy.ops.mf.texrename_alert(
                'INVOKE_DEFAULT',
                message="有 %d 项处理失败。失败原因可在 Blender 的系统控制台里查"
                        "（Windows：Window → Toggle System Console）。\n\n%s"
                        % (stats[planner.ST_FAIL], text))
        else:
            kinds = {}
            for record in plan.records:
                if record.status == planner.ST_OK:
                    kinds[record.kind] = kinds.get(record.kind, 0) + 1
            SUMMARY["kinds"] = kinds
            self.report({'INFO'}, text)
        return {'FINISHED'}


class MF_OT_texrename_toggle(bpy.types.Operator):
    bl_idname = OP_ID_TOGGLE
    bl_label = "切换处理类型"
    bl_description = "开：处理该类型；关：跳过"
    bl_options = {'REGISTER'}

    tag: StringProperty(default="")

    def execute(self, context):
        if self.tag in GROUP_STATE:
            GROUP_STATE[self.tag] = not GROUP_STATE[self.tag]
        return {'FINISHED'}


class MF_OT_texrename_alert(bpy.types.Operator):
    bl_idname = OP_ID_ALERT
    bl_label = "名称转英文"
    bl_description = "显示改名结果提示"
    bl_options = {'REGISTER'}

    message: StringProperty(default="")

    def invoke(self, context, event):
        if bpy.app.background:
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        for line in (self.message or "").splitlines():
            self.layout.label(text=line)

    def execute(self, context):
        return {'FINISHED'}


classes = (MF_OT_texrename_run, MF_OT_texrename_toggle, MF_OT_texrename_alert)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
