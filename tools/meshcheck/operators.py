import math

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from mathutils import Vector

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types

    def _fallback_register(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _fallback_unregister(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

from . import algorithms as core
from . import markers

TOOL_ID = "MeshCheck"
OP_ID_RUN = "mf.meshcheck_run"
OP_ID_CLEAR = "mf.meshcheck_clear"
OP_ID_TOGGLE = "mf.meshcheck_toggle"

OK = "FINISHED"
NO = "CANCELLED"

_KIND_TITLE = {
    core.FLIP: "反转法线",
    core.NONMANIFOLD: "非流形边",
    core.OVERLAP: "重叠面",
}

def collect_targets(context):
    targets = []
    try:
        selected = list(getattr(context, "selected_objects", None) or [])
    except Exception:
        selected = []
    for obj in selected:
        if obj is not None and getattr(obj, "type", None) == "MESH":
            targets.append(obj)
    if not targets:
        active = getattr(context, "active_object", None)
        if active is not None and getattr(active, "type", None) == "MESH":
            targets.append(active)
    return targets

def combined_diagonal(objects):
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in objects:
        box = getattr(obj, "bound_box", None)
        if not box:
            continue
        matrix = obj.matrix_world
        for corner in box:
            point = matrix @ Vector(corner)
            for i in range(3):
                if point[i] < lo[i]:
                    lo[i] = point[i]
                if point[i] > hi[i]:
                    hi[i] = point[i]
    if lo[0] == float("inf"):
        return 0.0
    return math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))

def object_diagonal(obj):
    box = getattr(obj, "bound_box", None)
    if not box:
        return 0.0
    matrix = obj.matrix_world
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for corner in box:
        point = matrix @ Vector(corner)
        for i in range(3):
            if point[i] < lo[i]:
                lo[i] = point[i]
            if point[i] > hi[i]:
                hi[i] = point[i]
    if lo[0] == float("inf"):
        return 0.0
    return math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))

def analyze_object(context, obj, opts):
    matrix = obj.matrix_world
    use_evaluated = bool(opts.get("use_evaluated"))
    if use_evaluated and len(obj.modifiers):
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            return core.analyze_mesh(mesh, matrix, opts)
        finally:
            evaluated.to_mesh_clear()
    return core.analyze_mesh(obj.data, matrix, opts)

def _marker_half_size(obj, st):
    percent = 8.0 if st is None else float(st.marker_percent)
    diagonal = object_diagonal(obj)
    if diagonal <= 0.0:
        diagonal = combined_diagonal([obj]) or 1.0
    return max(diagonal * percent / 100.0 * 0.5, 1.0e-6)

def _marker_bundles(targets, reports, st):
    cap = int(st.max_markers) if st is not None else 500
    bundles = {kind: [] for kind in core.KINDS}
    for obj, report in zip(targets, reports):
        half = _marker_half_size(obj, st)
        for kind in core.KINDS:
            for point in report[kind]["positions"]:
                bundles[kind].append((point, half))
    if cap:
        for kind in core.KINDS:
            if len(bundles[kind]) > cap:
                bundles[kind] = bundles[kind][:cap]
    return bundles

def _summary_text(merged, created):
    return "体检完成：%d 个物体｜反转法线 %d、非流形边 %d、重叠面 %d｜标记物体 %d 个" % (
        merged["objects"],
        merged[core.FLIP]["count"],
        merged[core.NONMANIFOLD]["count"],
        merged[core.OVERLAP]["count"],
        created,
    )

def _nonmanifold_detail(data):
    if not data.get("count"):
        return ""
    parts = []
    if data.get("wire"):
        parts.append("悬空线 %d" % data["wire"])
    if data.get("boundary"):
        parts.append("边界/破洞 %d" % data["boundary"])
    if data.get("multi"):
        parts.append("多面共边 %d" % data["multi"])
    if data.get("bad_verts"):
        parts.append("非流形点 %d" % data["bad_verts"])
    if data.get("loose_verts"):
        parts.append("孤立点 %d" % data["loose_verts"])
    return "、".join(parts)

def op_run_check(context):
    st = markers.settings(context)
    targets = collect_targets(context)
    if not targets:
        return NO, "请先在 3D 视图里选中一个网格物体，再点【模型体检】"

    opts = markers.options_from_settings(st)
    opts["use_evaluated"] = bool(st.use_evaluated) if st is not None else False

    reports = []
    for obj in targets:
        try:
            reports.append(analyze_object(context, obj, opts))
        except Exception as error:
            return NO, "检测「%s」时出错：%s" % (obj.name, error)

    merged = core.merge_reports(reports)

    colors = markers.colors_from_settings(st)
    bundles = _marker_bundles(targets, reports, st)
    created = markers.build_markers(
        bundles,
        colors,
        show_in_front=bool(st.markers_show_in_front) if st is not None else True,
        hide_render=bool(st.markers_hide_render) if st is not None else True,
    )

    summary = _summary_text(merged, created)

    if st is not None:
        st.has_result = True
        st.result_objects = merged["objects"]
        st.result_flip = merged[core.FLIP]["count"]
        st.result_nonmanifold = merged[core.NONMANIFOLD]["count"]
        st.result_overlap = merged[core.OVERLAP]["count"]
        st.note_flip = merged[core.FLIP]["note"]
        st.note_nonmanifold = _nonmanifold_detail(merged[core.NONMANIFOLD])
        st.note_overlap = merged[core.OVERLAP]["note"]
        st.marker_objects = created
        st.result_text = summary

    if merged[core.FLIP]["status"] == core.ST_SKIPPED_OPEN:
        summary += "（有开放网格，已跳过反转法线检测）"

    return OK, summary

def op_clear_markers(context):
    removed = markers.clear_markers()
    st = markers.settings(context)
    if st is not None:
        st.marker_objects = 0
    if not removed:
        return OK, "当前没有模型体检标记"
    return OK, "已清除 %d 个标记物体" % removed

def op_reset_result(context):
    removed = markers.clear_markers()
    st = markers.settings(context)
    if st is not None:
        st.has_result = False
        st.result_objects = 0
        st.result_flip = 0
        st.result_nonmanifold = 0
        st.result_overlap = 0
        st.note_flip = ""
        st.note_nonmanifold = ""
        st.note_overlap = ""
        st.result_text = ""
        st.marker_objects = 0
    return OK, "已重置体检结果（清除 %d 个标记物体）" % removed

def op_set_section(context, section):
    st = markers.settings(context)
    if st is None:
        return NO, "当前上下文取不到设置"
    prop = markers.SECTION_PROPS.get(section)
    if prop is None:
        return NO, "未知的段落：%s" % section
    setattr(st, prop, not bool(getattr(st, prop)))
    return OK, ""

class MF_OT_MeshCheck_Run(bpy.types.Operator):
    bl_idname = OP_ID_RUN
    bl_label = "模型体检"
    bl_description = "检测反转法线 / 非流形边 / 重叠面，并用红黄蓝方块标出位置。只检测，不改模型"
    bl_options = {'REGISTER', 'UNDO'}

    show_popup: BoolProperty(
        name="完成后弹窗",
        description="体检结束后弹出结果窗口",
        default=True,
        options={'SKIP_SAVE'},
    )
    message: StringProperty(default="", options={'SKIP_SAVE'})

    _ran = False
    _status = OK

    def _perform(self, context):
        if self._ran:
            return
        status, message = op_run_check(context)
        self._ran = True
        self._status = status
        self.message = message

    def invoke(self, context, event):
        self._perform(context)
        if self._status != OK:
            self.report({'ERROR'}, self.message)
            return {NO}
        if bpy.app.background or not self.show_popup:
            self.report({'INFO'}, self.message)
            return {OK}
        try:
            return context.window_manager.invoke_props_dialog(self, width=380)
        except Exception:
            self.report({'INFO'}, self.message)
            return {OK}

    def draw(self, context):
        st = markers.settings(context)
        layout = self.layout

        if st is None:
            layout.label(text="取不到设置", icon='ERROR')
            return

        layout.label(text="模型体检结果", icon='CHECKMARK')
        layout.label(text="已检测 %d 个物体" % st.result_objects)
        layout.separator()

        rows = (
            ("color_flip", "反转法线", st.result_flip),
            ("color_nonmanifold", "非流形边", st.result_nonmanifold),
            ("color_overlap", "重叠面", st.result_overlap),
        )
        for prop, title, count in rows:
            row = layout.row(align=True)
            row.prop(st, prop, text="")
            row.label(text=title)
            row.label(text=str(count))

        for note in (st.note_flip, st.note_nonmanifold, st.note_overlap):
            if note:
                layout.separator()
                layout.label(text=note, icon='INFO')

        layout.separator()
        layout.label(text="视口已用 %d 个方块标出错误位置" % st.marker_objects, icon='VIEWZOOM')

    def execute(self, context):
        self._perform(context)
        if self._status != OK:
            self.report({'ERROR'}, self.message)
            return {NO}
        self.report({'INFO'}, self.message)
        return {OK}

class MF_OT_MeshCheck_Clear(bpy.types.Operator):
    bl_idname = OP_ID_CLEAR
    bl_label = "清除标记"
    bl_description = "删除视口里的全部模型体检标记方块，并重置结果"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        status, message = op_reset_result(context)
        self.report({'INFO'} if status == OK else {'ERROR'}, message)
        return {status}

class MF_OT_MeshCheck_Toggle(bpy.types.Operator):
    bl_idname = OP_ID_TOGGLE
    bl_label = "展开 / 收起"
    bl_description = "切换模型体检面板中某一段的展开状态"
    bl_options = {'INTERNAL'}

    section: EnumProperty(
        name="段落",
        items=(
            ("check", "检测项目", "选择要检测的错误类型"),
            ("param", "参数与标记", "容差、标记数量与颜色"),
            ("help", "说明", "使用说明"),
        ),
        default="check",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        status, message = op_set_section(context, self.section)
        if status != OK and message:
            self.report({'WARNING'}, message)
        return {status}

classes = (
    MF_OT_MeshCheck_Run,
    MF_OT_MeshCheck_Clear,
    MF_OT_MeshCheck_Toggle,
)

def register():
    utils.register_classes(classes)

def unregister():
    utils.unregister_classes(classes)
