import os

import bpy

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
        PANEL_CATEGORY="MF Tools",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

from . import disk, naming, scan

TOOL_ID = "BatchRename"
OP_APPLY_ID = "mf.batch_rename_apply"
OP_CLEAR_ID = "mf.batch_rename_clear_keyword"

SCENE_ATTR = "mf_batchrename_settings"

REPORT_LIMIT = 4000

ACTION_ITEMS = (
    (naming.A_PREFIX, "加前缀", "在原名前面加上关键字"),
    (naming.A_SUFFIX, "加后缀", "在原名后面加上关键字"),
    (naming.A_STRIP_PREFIX, "清除前缀", "去掉与关键字匹配的开头；匹配不上时切掉第一个分隔符之前的部分"),
    (naming.A_STRIP_SUFFIX, "清除后缀", "去掉与关键字匹配的结尾；匹配不上时切掉最后一个分隔符之后的部分"),
    (naming.A_RENAME, "重命名", "整段覆盖成「关键字 + 4 位序号」"),
)
ACTION_KEYS = naming.ACTION_KEYS
ACTION_LABELS = {k: l for k, l, _d in ACTION_ITEMS}

SCOPE_ITEMS = (
    (scan.SCOPE_SELECTED, "仅选中", "只处理选中的物体；材质/贴图取选中物体引用到的"),
    (scan.SCOPE_ALL, "全场景", "处理场景里全部物体、材质、贴图"),
)


def _tag_redraw(self, context):
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


class MF_PG_BatchRenameSettings(bpy.types.PropertyGroup):
    keyword: bpy.props.StringProperty(
        name="名称",
        description="加/清 前缀后缀、重命名共用的关键字。"
                    "填 MF_ 之类的短词就行，不用带分隔符",
        default="", update=_tag_redraw)
    scope: bpy.props.EnumProperty(
        name="范围", items=SCOPE_ITEMS, default=scan.SCOPE_SELECTED,
        update=_tag_redraw)
    do_object: bpy.props.BoolProperty(
        name="物体名", description="处理物体（含空物体）的名称", default=True)
    do_material: bpy.props.BoolProperty(
        name="材质名", description="处理材质的名称", default=True)
    do_image: bpy.props.BoolProperty(
        name="贴图名",
        description="处理贴图数据块的名称。"
                    "勾了下方的「同时重命名磁盘贴图文件」才会动硬盘上的文件",
        default=True)
    skip_cameras: bpy.props.BoolProperty(
        name="不处理相机名称",
        description="勾上后「物体名」这一类会跳过所有相机 —— "
                    "镜头通常按用途手工命名，被前缀一扫就废了",
        default=False)
    skip_lights: bpy.props.BoolProperty(
        name="不处理灯光名称",
        description="勾上后「物体名」这一类会跳过所有灯光，理由同上",
        default=False)
    rename_disk: bpy.props.BoolProperty(
        name="同时重命名磁盘贴图文件", default=True,
        description="连同硬盘上的图片文件一起改名，并同步工程里的路径。\n"
                    "关掉就只改 Blender 里的数据块名，完全不碰磁盘。\n"
                    "⚠ 磁盘改名不能用 Ctrl+Z 撤销，动之前先看清报告区的清单")
    last_report: bpy.props.StringProperty(default="")


def snapshot(settings):
    return {
        "keyword": settings.keyword,
        "scope": settings.scope,
        "do_object": settings.do_object,
        "do_material": settings.do_material,
        "do_image": settings.do_image,
        "skip_cameras": settings.skip_cameras,
        "skip_lights": settings.skip_lights,
        "rename_disk": settings.rename_disk,
    }


class Plan(object):
    def __init__(self, action, kw):
        self.action = action
        self.kw = kw
        self.renames = []
        self.units = []
        self.skips = []
        self.disk_skips = []
        self.notes = []
        self.nochange = 0
        self.dupe_files = 0
        self.error = ""

    @property
    def has_work(self):
        return bool(self.renames)

    def empty_message(self):
        if self.error:
            return self.error
        return "没有需要改名的对象（勾选的类别里一条都没命中）"

    def counts(self):
        out = {}
        for entry, _new in self.renames:
            out[entry.kind] = out.get(entry.kind, 0) + 1
        return out


def build_plan(context, action, snap):
    if action not in ACTION_KEYS:
        raise ValueError("unknown action: %r" % (action,))

    use_snap = dict(snap)
    kw_raw = (use_snap.get("keyword") or "").strip()

    plan = Plan(action, kw_raw)
    if not kw_raw:
        plan.error = "「%s」需要先填关键字" % ACTION_LABELS.get(action, action)
        return plan

    if not (use_snap.get("do_object") or use_snap.get("do_material") or use_snap.get("do_image")):
        plan.error = "一个类别都没勾选（物体名 / 材质名 / 贴图名）"
        return plan

    entries, notes = scan.collect(context, use_snap)
    plan.notes.extend(notes)
    if not entries:
        plan.error = ("范围=仅选中，但场景里没有任何选中物体" if use_snap["scope"] == scan.SCOPE_SELECTED
                      else "场景里没有可处理的条目")
        return plan

    kw_file, kw_changed = naming.sanitize_keyword(kw_raw)
    if kw_changed:
        plan.notes.append("关键字里的非法文件名字符已替换为 _（只影响贴图/文件名）")
    if not kw_file:
        kw_file = None

    entries.sort(key=lambda e: (naming.KINDS.index(e.kind), e.label.lower()))

    counters = {}
    seen_files = {}

    for entry in entries:
        if not entry.writable:
            plan.skips.append((entry.skip or "不可改名", entry.label))
            continue

        with_ext = entry.kind == naming.KIND_IMAGE
        kw = kw_file if (with_ext and kw_file is not None) else kw_raw
        if kw is None:
            plan.skips.append(("关键字净化后为空，无法作为文件名", entry.label))
            continue

        serial = None
        if action == "RENAME":
            counters[entry.kind] = counters.get(entry.kind, 0) + 1
            serial = counters[entry.kind]

        new_label = naming.transform(entry.label, action, kw, with_ext, serial)
        if new_label is None:
            plan.nochange += 1
            continue

        plan.renames.append((entry, new_label))

        if entry.kind == naming.KIND_IMAGE and use_snap.get("rename_disk") and entry.skip_disk:
            plan.disk_skips.append((entry.skip_disk, entry.label))

        if not use_snap.get("rename_disk") or not entry.has_disk:
            continue

        safe = naming.sanitize_filename(new_label)
        if not safe:
            plan.skips.append(("净化后文件名为空，磁盘不动", entry.label))
            continue

        if entry.file_abs:
            key = disk._norm(entry.file_abs)
            unit = seen_files.get(key)
            if unit is not None:
                unit["followers"].append(entry)
                plan.dupe_files += 1
                continue
            wanted = os.path.join(os.path.dirname(entry.file_abs), safe)
            if disk._norm(wanted) == key:
                continue
            unit = disk.make_file_unit(entry, entry.file_abs, wanted)
            seen_files[key] = unit
            plan.units.append(unit)
        elif entry.seq_frames:
            key = disk._norm(entry.seq_frames[0][1])
            unit = seen_files.get(key)
            if unit is not None:
                unit["followers"].append(entry)
                plan.dupe_files += 1
                continue
            pattern_abs = bpy.path.abspath(entry.id.filepath)
            wanted = os.path.join(os.path.dirname(pattern_abs), safe)
            unit = disk.make_seq_unit(entry, list(entry.seq_frames), wanted)
            seen_files[key] = unit
            plan.units.append(unit)

    return plan


def _to_blender_path(abs_path, was_relative):
    if was_relative:
        try:
            return bpy.path.relpath(abs_path)
        except Exception:
            pass
    return abs_path


def apply_plan(context, plan, snap):
    rep = {"action": plan.action, "kw": plan.kw, "counts": {}, "db_ok": 0,
           "db_fail": [], "disk_ok": 0, "disk_fail": [], "path_ok": 0,
           "skips": list(plan.skips), "disk_skips": list(plan.disk_skips),
           "nochange": plan.nochange, "notes": list(plan.notes)}

    for entry, new_label in plan.renames:
        try:
            entry.id.name = new_label
            rep["db_ok"] += 1
            rep["counts"][entry.kind] = rep["counts"].get(entry.kind, 0) + 1
        except Exception as exc:
            rep["db_fail"].append("%s %s：%s" % (entry.kind_label, entry.label, exc))

    if plan.units and snap.get("rename_disk"):
        moves, plan_errs = disk.plan(plan.units)
        for unit, why in plan_errs:
            rep["disk_fail"].append("%s：%s" % (unit["entry"].label, why))
        rolled_back = False
        if moves:
            n, errs = disk.run_moves(moves)
            rep["disk_ok"] += n
            rep["disk_fail"].extend(errs)
            if errs:
                rolled_back = True
                rep["notes"].append("磁盘改名失败并已整体回滚，贴图路径保持原样")

        if not rolled_back:
            for unit in plan.units:
                if unit["final"] is None:
                    continue
                for entry in [unit["entry"]] + list(unit["followers"]):
                    img = entry.id
                    try:
                        old_raw = img.filepath or ""
                        img.filepath = _to_blender_path(unit["final"], old_raw.startswith("//"))
                        try:
                            img.reload()
                        except Exception:
                            pass
                        rep["path_ok"] += 1
                    except Exception as exc:
                        rep["disk_fail"].append("%s 路径回写失败：%s" % (entry.label, exc))

    return rep


def format_report(rep):
    lines = []
    title = ACTION_LABELS.get(rep["action"], rep["action"])
    for kind in naming.KINDS:
        n = rep["counts"].get(kind, 0)
        if n:
            lines.append("完成%s命名 %d 个" % (naming.KIND_LABELS[kind], n))
    if not lines:
        lines.append("%s：没有改动任何名称" % title)
    if rep["disk_ok"]:
        lines.append("磁盘文件改名 %d 个" % rep["disk_ok"])

    if rep["skips"]:
        buckets = {}
        for reason, _name in rep["skips"]:
            buckets[reason] = buckets.get(reason, 0) + 1
        parts = ["%s %d" % (r, n) for r, n in sorted(buckets.items(), key=lambda kv: -kv[1])]
        lines.append("跳过 %d 项（%s）" % (len(rep["skips"]), "；".join(parts[:3])))
    if rep["nochange"]:
        lines.append("无需改动 %d 个" % rep["nochange"])

    if rep.get("disk_skips"):
        buckets = {}
        for reason, _name in rep["disk_skips"]:
            buckets[reason] = buckets.get(reason, 0) + 1
        parts = ["%s %d" % (r, n) for r, n in sorted(buckets.items(), key=lambda kv: -kv[1])]
        lines.append("只改名字、磁盘未动 %d 张（%s）"
                     % (len(rep["disk_skips"]), "；".join(parts[:3])))

    for msg in rep["db_fail"][:3]:
        lines.append("失败：" + msg)
    for msg in rep["disk_fail"][:3]:
        lines.append("磁盘：" + msg)
    if len(rep["db_fail"]) + len(rep["disk_fail"]) > 6:
        lines.append("……还有 %d 条，点「查看完整报告」"
                     % (len(rep["db_fail"]) + len(rep["disk_fail"]) - 6))
    for note in rep["notes"][:3]:
        lines.append(note)
    return "\n".join(lines)


def full_report(rep):
    out = [format_report(rep), ""]
    if rep["db_fail"]:
        out.append("【数据块改名失败】")
        out.extend("  " + m for m in rep["db_fail"])
    if rep["disk_fail"]:
        out.append("【磁盘改名失败】")
        out.extend("  " + m for m in rep["disk_fail"])
    if rep["skips"]:
        out.append("【跳过明细】")
        out.extend("  %s —— %s" % (n, r) for r, n in rep["skips"][:40])
    if rep.get("disk_skips"):
        out.append("【只改名字、磁盘未动】")
        out.extend("  %s —— %s" % (n, r) for r, n in rep["disk_skips"][:40])
    if rep["notes"]:
        out.append("【提示】")
        out.extend("  " + m for m in rep["notes"])
    return "\n".join(out)


def remember(settings, text):
    settings.last_report = (text or "")[:REPORT_LIMIT]


class MF_OT_BatchRename_Apply(bpy.types.Operator):
    bl_idname = OP_APPLY_ID
    bl_label = "执行命名操作"
    bl_description = (
        "按当前「名称关键字」和「范围」执行这个动作。\n"
        "改动清单见面板底部报告区（悬停本按钮前先看那里）"
    )
    bl_options = {"REGISTER", "UNDO"}

    action: bpy.props.EnumProperty(
        name="动作", items=ACTION_ITEMS, default="PREFIX",
        options={"HIDDEN"})

    def execute(self, context):
        st = getattr(context.scene, SCENE_ATTR)
        snap = snapshot(st)
        plan = build_plan(context, self.action, snap)

        if not plan.has_work:
            msg = plan.empty_message()
            remember(st, msg)
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        rep = apply_plan(context, plan, snap)
        remember(st, full_report(rep))

        summary = format_report(rep).splitlines()
        headline = summary[0] if summary else "完成"
        if rep["db_fail"] or rep["disk_fail"]:
            self.report({"ERROR"}, headline + "（有失败项，见报告）")
        else:
            self.report({"INFO"}, headline)
        return {"FINISHED"}


class MF_OT_BatchRename_ClearKeyword(bpy.types.Operator):
    bl_idname = OP_CLEAR_ID
    bl_label = "清空名称"
    bl_description = "清空「名称关键字」输入框"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def execute(self, context):
        getattr(context.scene, SCENE_ATTR).keyword = ""
        return {"FINISHED"}


classes = (MF_PG_BatchRenameSettings,
           MF_OT_BatchRename_Apply,
           MF_OT_BatchRename_ClearKeyword)


def register():
    utils.register_classes(classes)
    setattr(bpy.types.Scene, SCENE_ATTR,
            bpy.props.PointerProperty(type=MF_PG_BatchRenameSettings))


def unregister():
    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    utils.unregister_classes(classes)
