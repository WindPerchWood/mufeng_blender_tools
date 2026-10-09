
import json
import os
import shutil
import subprocess
import tempfile

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

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
        PANEL_CATEGORY="MF Tools",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[MF Tools] {level}: {msg}"),
    )

TOOL_ID = "Archive"

OP_ALERT = "mf.archive_alert"
OP_OPEN_DIR = "mf.archive_open_dir"
OP_COLLECT = "mf.archive_collect"

CREATE_NO_WINDOW = 0x08000000

ARCHIVE_OPTIONS = {
    "only_used": True,
    "dedupe": True,
    "preview": True,
}

UNSAVED_STEM = "未命名工程"

SNAPSHOT_PREFIX = "barc_snapshot_"

STATE = {
    "last_status": "",
    "last_detail": "",
    "last_output": "",
    "last_report": "",
    "last_files": 0,
    "last_dirs": 0,
}

FINISHED = "FINISHED"
CANCELLED = "CANCELLED"


def source_blend():
    return bpy.data.filepath or ""


def source_stem():
    path = source_blend()
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return UNSAVED_STEM


def default_save_path():
    path = source_blend()
    if path:
        base = os.path.dirname(path)
    else:
        base = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
    return os.path.join(base, "%s_归档.zip" % source_stem())


def split_save_path(filepath):
    path = (filepath or "").strip().strip('"')
    if not path:
        return "", ""
    if not path.lower().endswith(".zip"):
        path += ".zip"
    folder = os.path.dirname(os.path.abspath(path))
    name = os.path.splitext(os.path.basename(path))[0].strip()
    return folder, (name or "归档")


def build_job(filepath="", preview_src="", src_blend="", snapshot=""):
    folder, name = split_save_path(filepath or default_save_path())
    return {
        "src_blend": src_blend or source_blend(),
        "snapshot": snapshot or "",
        "archive_root": os.path.abspath(os.path.join(folder, name)) if folder else "",
        "archive_name": name,
        "options": dict(ARCHIVE_OPTIONS),
        "preview_src": preview_src or "",
    }


def snapshot_target():
    folder = tempfile.mkdtemp(prefix=SNAPSHOT_PREFIX)
    return folder, os.path.join(folder, "snapshot.blend")


def write_snapshot():
    folder, path = snapshot_target()
    try:
        bpy.ops.wm.save_as_mainfile(
            filepath=path,
            check_existing=False,
            compress=False,
            copy=True,
        )
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        return "", "没能把当前工程写成临时快照：%r" % exc
    if not os.path.isfile(path):
        shutil.rmtree(folder, ignore_errors=True)
        return "", "没能把当前工程写成临时快照：文件没生成（磁盘满了？）"
    return path, ""


def cleanup_snapshot(path):
    if not path:
        return
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.basename(folder).startswith(SNAPSHOT_PREFIX) and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass


def worker_script():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")


def spawn_worker(job):
    tmpdir = tempfile.mkdtemp(prefix="barc_")
    job_path = os.path.join(tmpdir, "job.json")
    report_path = os.path.join(tmpdir, "report.json")
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)

    exe = bpy.app.binary_path
    args = [exe, "--background", "--factory-startup"]
    src = job.get("src_blend") or ""
    if src and os.path.isfile(src):
        args.append(src)
    args += ["--python", worker_script(), "--", job_path, report_path]

    env = dict(os.environ)
    env["BARC_AUTORUN"] = "1"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=tempfile.gettempdir(),
        **kwargs
    )
    return proc, job_path, report_path


def _cleanup_job_dir(report_path):
    job_dir = os.path.dirname(os.path.abspath(report_path))
    if os.path.basename(job_dir).startswith("barc_") and os.path.isdir(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)


def read_report(proc, report_path):
    tail = ""
    try:
        if proc.stdout is not None:
            tail = proc.stdout.read().decode("utf-8", "replace")
    except Exception:
        tail = ""
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            report["_stdout_tail"] = tail[-2000:]
            _cleanup_job_dir(report_path)
            return report
        except Exception as exc:
            _cleanup_job_dir(report_path)
            return {"ok": False, "error": "报告文件读不出来：%r" % exc, "_stdout_tail": tail[-2000:]}
    _cleanup_job_dir(report_path)
    return {
        "ok": False,
        "error": "子进程没有产出报告（退出码 %s）" % getattr(proc, "returncode", "?"),
        "_stdout_tail": tail[-2000:],
    }


def run_worker_sync(job):
    proc, _job_path, report_path = spawn_worker(job)
    proc.wait()
    return read_report(proc, report_path)


def human_size(num):
    step = 1024.0
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return "%.1f %s" % (value, unit) if unit != "B" else "%d B" % int(value)
        value /= step
    return "%.1f TB" % value


def summarize_report(report):
    if not report:
        return "尚未归档过", ""
    if not report.get("ok"):
        return "归档失败", (report.get("error") or "未知错误")
    summary = report.get("summary", {})
    verify = report.get("verify", {})
    line1 = "已归档：%d 个文件 / %d 个缓存目录 / %s" % (
        summary.get("files", 0),
        summary.get("dirs", 0),
        human_size(summary.get("bytes", 0)),
    )
    line2 = "自检：断链 %d / 绝对路径残留 %d / 图片读不出 %d" % (
        len(verify.get("broken_paths", [])),
        len(verify.get("absolute_paths", [])),
        len(verify.get("images_unreadable", [])),
    )
    pre = verify.get("pre_existing_missing") or []
    if pre:
        line2 += " ｜ 归档前就已缺失 %d" % len(pre)
    return line1, line2



def op_capture_preview(context, target_path):
    if bpy.app.background:
        return ""
    try:
        from . import worker as _worker

        ok, _msg = _worker.take_preview(target_path)
        return target_path if ok else ""
    except Exception:
        return ""


def op_build(context, filepath):
    folder, _name = split_save_path(filepath or default_save_path())
    if not folder:
        return CANCELLED, "没有指定保存位置", None

    snapshot, why = write_snapshot()
    if not snapshot:
        return CANCELLED, why, None

    preview_src = ""
    if ARCHIVE_OPTIONS["preview"]:
        preview_dir = tempfile.mkdtemp(prefix="barc_preview_")
        preview_src = op_capture_preview(context, os.path.join(preview_dir, "preview.png"))
        if not preview_src:
            shutil.rmtree(preview_dir, ignore_errors=True)

    job = build_job(filepath, preview_src=preview_src,
                    src_blend=snapshot, snapshot=snapshot)
    try:
        proc, job_path, report_path = spawn_worker(job)
    except Exception as exc:
        op_discard({"job": job, "snapshot": snapshot})
        return CANCELLED, "拉不起归档进程：%r" % exc, None

    return FINISHED, "归档已开始…", {
        "proc": proc,
        "job_path": job_path,
        "report_path": report_path,
        "job": job,
        "snapshot": snapshot,
    }


def op_discard(session):
    if not session:
        return
    cleanup_snapshot(session.get("snapshot"))
    try:
        from . import worker as _worker

        _worker._cleanup_preview((session.get("job") or {}).get("preview_src"))
    except Exception:
        pass


def op_finish(report):
    line1, line2 = summarize_report(report)
    STATE["last_status"] = line1
    STATE["last_detail"] = line2
    STATE["last_report"] = report.get("report_file", "") or ""
    summary = report.get("summary", {})
    STATE["last_output"] = report.get("archive_file") or report.get("archive_root") or ""
    STATE["last_files"] = summary.get("files", 0)
    STATE["last_dirs"] = summary.get("dirs", 0)

    if report.get("ok"):
        warns = report.get("warnings", [])
        msg = line1
        if warns:
            msg += "（%d 条提示）" % len(warns)
        return FINISHED, msg
    return CANCELLED, "归档失败：%s" % (report.get("error") or "未知错误")


def op_open_folder(path):
    target = path
    if target and os.path.isfile(target):
        target = os.path.dirname(target)
    if not target or not os.path.isdir(target):
        return CANCELLED, "还没有归档过，或者归档文件已被移走。"
    try:
        bpy.ops.wm.path_open(filepath=target)
    except Exception as exc:
        return CANCELLED, "打开目录失败：%r" % exc
    return FINISHED, "已在文件管理器中打开：%s" % target



class MF_OT_Archive_Alert(Operator):
    bl_idname = OP_ALERT
    bl_label = "归档提示"
    bl_options = {"REGISTER"}

    message: StringProperty(default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        for line in (self.message or "").splitlines() or [""]:
            self.layout.label(text=line[:120])

    def execute(self, context):
        return {"FINISHED"}


class MF_OT_Archive_OpenDir(Operator):
    bl_idname = OP_OPEN_DIR
    bl_label = "打开所在文件夹"
    bl_description = "在文件管理器里打开压缩包所在的位置"
    bl_options = {"REGISTER"}

    def execute(self, context):
        status, msg = op_open_folder(STATE["last_output"])
        self.report({"ERROR"} if status == CANCELLED else {"INFO"}, msg)
        return {status}


class MF_OT_Archive_Collect(ExportHelper, Operator):
    bl_idname = OP_COLLECT
    bl_label = "归档到 ZIP…"
    bl_description = "选择保存位置和文件名，把散落各处的贴图/缓存/链接库收拢成一个 ZIP"
    bl_options = {"REGISTER"}

    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})
    filepath: StringProperty(subtype="FILE_PATH")

    _session = None
    _timer = None

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = STATE["last_output"] or default_save_path()
        return super().invoke(context, event)

    def execute(self, context):
        if bpy.app.background:
            path = self.filepath or default_save_path()
            status, msg, session = op_build(context, path)
            if status == CANCELLED:
                self.report({"ERROR"}, msg)
                return {CANCELLED}
            session["proc"].wait()
            report = read_report(session["proc"], session["report_path"])
            op_discard(session)
            status, msg = op_finish(report)
            self.report({"INFO"} if status == FINISHED else {"ERROR"}, msg)
            return {status}
        return self._begin(context)

    def _begin(self, context):
        status, msg, session = op_build(context, self.filepath)
        if status == CANCELLED:
            self.report({"ERROR"}, msg)
            return {CANCELLED}
        self._session = session
        self._timer = None

        window_manager = context.window_manager
        try:
            window_manager.progress_begin(0, 100)
            self._timer = window_manager.event_timer_add(0.3, window=context.window)
            window_manager.modal_handler_add(self)
        except Exception as exc:
            return self._finish_sync(context, session, exc)

        self.report({"INFO"}, msg)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        session = self._session
        self._session = None
        window_manager = context.window_manager
        try:
            window_manager.progress_end()
        except Exception:
            pass
        if self._timer is not None:
            try:
                window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

        report = read_report(session["proc"], session["report_path"])
        op_discard(session)
        status, msg = op_finish(report)
        if status == FINISHED:
            self.report({"INFO"}, msg)
            for line in report.get("warnings", [])[:6]:
                self.report({"WARNING"}, line)
        else:
            self.report({"ERROR"}, msg)
            detail = "\n".join(
                [msg]
                + report.get("errors", [])[:4]
                + ["", "排查用的详细清单留在保留的工作文件夹里：归档报告.json。"]
            )
            try:
                bpy.ops.mf.archive_alert("INVOKE_DEFAULT", message=detail)
            except Exception:
                pass
        return {"FINISHED"}

    def _finish_sync(self, context, session, exc):
        self.report({"WARNING"}, "拿不到窗口，改为同步执行（%r）" % exc)
        session["proc"].wait()
        return self._finish(context)

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        session = self._session
        if session is None:
            return {"FINISHED"}
        if session["proc"].poll() is None:
            try:
                context.window_manager.progress_update(30)
            except Exception:
                pass
            return {"RUNNING_MODAL"}
        try:
            context.window_manager.progress_update(100)
        except Exception:
            pass
        return self._finish(context)

    def cancel(self, context):
        try:
            context.window_manager.progress_end()
        except Exception:
            pass
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        session = self._session
        self._session = None
        if session is not None:
            try:
                session["proc"].terminate()
            except Exception:
                pass
            op_discard(session)


classes = (MF_OT_Archive_Alert, MF_OT_Archive_OpenDir, MF_OT_Archive_Collect)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
