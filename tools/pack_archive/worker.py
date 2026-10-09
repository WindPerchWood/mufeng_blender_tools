
import json
import os
import shutil
import sys
import time
import traceback
import zipfile

try:
    from . import plan, scan
except (ImportError, ValueError):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import plan
    import scan

import bpy

VERSION = "1.0.0"
ZIP_SUFFIX = ".zip"


def _posix_rel(path, start):
    return os.path.relpath(path, start).replace("\\", "/")


def _step(report, label, detail=""):
    report["steps"].append({"label": label, "detail": detail, "t": round(time.time(), 3)})


def _copy_entry(entry, warnings, errors):
    src = entry["src"]
    dst = entry["dst_abs"]
    try:
        if entry["is_dir"]:
            os.makedirs(dst, exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                warnings.append("缓存目录还不存在，只建了空目录：%s" % src)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        for extra in entry.get("extra_files") or ():
            try:
                shutil.copy2(extra, os.path.join(os.path.dirname(dst), os.path.basename(extra)))
            except Exception as exc:
                errors.append("序列帧 %s 拷贝失败：%r" % (extra, exc))
    except Exception as exc:
        errors.append("%s → %s 拷贝失败：%r" % (src, dst, exc))
        return False
    return True


def rel_for(entry, rec):
    pattern = (rec or {}).get("seq_pattern") or ""
    if pattern:
        return "//%s/%s" % (entry["subdir"], pattern)
    return "//" + entry["dst_rel"]


def apply_remap(plan_result, records, report):
    ok_count = 0
    failed = []
    for entry in plan_result["entries"]:
        for rec_id in entry["record_ids"]:
            rec = records[rec_id] if 0 <= rec_id < len(records) else {}
            new_value = rel_for(entry, rec)
            if scan.apply_ref(rec.get("ref"), new_value, as_dir=bool(entry["is_dir"])):
                ok_count += 1
                rec["raw"] = new_value
            else:
                failed.append("%s（%s）" % (new_value, rec.get("owner", "未知")))
    return ok_count, failed


def take_preview(path):
    if bpy.app.background:
        return False, "后台模式不截图"
    best = None
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                if best is None or area.width * area.height > best[0].width * best[0].height:
                    best = (area, window)
    except Exception:
        best = None
    if best is not None:
        try:
            with bpy.context.temp_override(window=best[1], area=best[0],
                                           screen=best[1].screen):
                bpy.ops.screen.screenshot_area(filepath=path)
            return True, "已抓取 3D 视图"
        except Exception:
            pass
    try:
        bpy.ops.screen.screenshot(filepath=path)
        return True, "已抓取整窗"
    except Exception as exc:
        return False, "截图失败：%r" % exc


SNAPSHOT_PREFIX = "barc_snapshot_"


def _disable_save_backups():
    try:
        bpy.context.preferences.filepaths.save_version = 0
        return True
    except Exception:
        return False


def _sweep_blend_backups(archive_blend):
    removed = []
    stem = os.path.splitext(os.path.basename(archive_blend))[0]
    folder = os.path.dirname(os.path.abspath(archive_blend))
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
        head, ext = os.path.splitext(name)
        if head == stem and ext.startswith(".blend") and ext[6:].isdigit():
            try:
                os.remove(os.path.join(folder, name))
                removed.append(name)
            except OSError:
                pass
    return removed


def _cleanup_snapshot(path):
    if not path:
        return
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.basename(folder).startswith(SNAPSHOT_PREFIX) and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass


def _cleanup_preview(path):
    if not path:
        return
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.basename(folder).startswith("barc_preview_") and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        elif os.path.isfile(path) and os.path.basename(path).startswith("barc_preview"):
            os.remove(path)
    except Exception:
        pass


def _attach_preview(job, archive_root, report):
    opts = job.get("options", {})
    src = job.get("preview_src") or opts.get("preview_src") or ""
    if not opts.get("preview", True):
        _cleanup_preview(src)
        return
    dst = os.path.join(archive_root, "预览图.png")
    if src and os.path.isfile(src):
        try:
            shutil.copy2(src, dst)
            report["preview"] = dst
            _step(report, "附预览图", os.path.basename(src))
        except Exception as exc:
            report["warnings"].append("预览图拷贝失败：%r" % exc)
        finally:
            _cleanup_preview(src)
        return
    ok, msg = take_preview(dst)
    if ok:
        report["preview"] = dst
    _step(report, "附预览图", msg)
    if not ok:
        report["warnings"].append("预览图未生成（%s）" % msg)


def count_orphans():
    total = 0
    for coll_name in ("images", "sounds", "volumes", "fonts", "movieclips"):
        for block in getattr(bpy.data, coll_name, ()):
            if getattr(block, "users", 0) or getattr(block, "use_fake_user", False):
                continue
            if not (getattr(block, "filepath", "") or ""):
                continue
            if getattr(block, "packed_file", None) is not None:
                continue
            total += 1
    return total


def image_readable(img):
    try:
        if img.size[0] > 0 and img.size[1] > 0:
            return True
        img.reload()
        if img.size[0] > 0 and img.size[1] > 0:
            return True
        return bool(img.pixels[0] >= 0.0)
    except Exception:
        return False


def _ref_key(ref):
    if not ref:
        return None
    return (ref.get("how", ""), ref.get("coll", ""), ref.get("name", ""),
            ref.get("obj", ""), ref.get("mod", ""), ref.get("ps", ""))


def pre_missing_index(records):
    refs = set()
    images = set()
    raws = []
    for rec in records:
        if not rec.get("missing"):
            continue
        refs.add(_ref_key(rec.get("ref")))
        if (rec.get("ref") or {}).get("coll") == "images":
            images.add(rec["ref"]["name"])
        raws.append(rec.get("raw") or rec.get("src") or "")
    return refs, images, raws


def verify(archive_root, pre_missing_refs=None, pre_missing_images=None):
    pre_missing_refs = pre_missing_refs or set()
    pre_missing_images = pre_missing_images or set()
    records, _warnings = scan.scan(only_used=True)
    results = {
        "records": len(records),
        "absolute_paths": [],
        "broken_paths": [],
        "cache_soft_missing": 0,
        "orphan_skipped": count_orphans(),
        "images_checked": 0,
        "images_unreadable": [],
        "images_sequence_skipped": 0,
        "pre_existing_missing": [],
        "images_pre_missing": 0,
    }
    for rec in records:
        raw = rec.get("raw") or ""
        if _ref_key(rec.get("ref")) in pre_missing_refs:
            results["pre_existing_missing"].append("%s（%s）" % (raw, rec.get("owner", "")))
            continue
        if not raw.startswith("//"):
            results["absolute_paths"].append(raw)
            continue
        resolved = bpy.path.abspath(raw)
        if "#" in raw:
            if not scan.expand_sequence(resolved):
                results["broken_paths"].append(
                    "%s（%s，序列一帧都没找到）" % (raw, rec.get("owner", ""))
                )
            continue
        if rec.get("soft") and not os.path.exists(resolved):
            results["cache_soft_missing"] += 1
        elif not os.path.exists(resolved):
            results["broken_paths"].append("%s（%s）" % (raw, rec.get("owner", "")))

    for img in bpy.data.images:
        source = getattr(img, "source", "")
        if source not in {"FILE", "SEQUENCE", "MOVIE"}:
            continue
        if not getattr(img, "users", 0) or getattr(img, "packed_file", None) is not None:
            continue
        if img.name in pre_missing_images:
            results["images_pre_missing"] += 1
            continue
        if source != "FILE":
            results["images_sequence_skipped"] += 1
            continue
        results["images_checked"] += 1
        if not image_readable(img):
            results["images_unreadable"].append(img.name)
    return results, records


def archive_target_path(archive_root):
    return os.path.join(
        os.path.dirname(archive_root), os.path.basename(archive_root) + ZIP_SUFFIX
    )


def make_archive(archive_root, report):
    target = archive_target_path(archive_root)
    if os.path.exists(target):
        try:
            os.remove(target)
        except OSError as exc:
            report["warnings"].append("旧压缩包删不掉：%r" % exc)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _dirs, files in os.walk(archive_root):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, _posix_rel(full, archive_root))
    _step(report, "压缩", os.path.basename(target))
    return target


def prune_empty_dirs(root):
    removed = []
    base = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if os.path.abspath(dirpath) == base:
            continue
        if dirnames or filenames:
            continue
        try:
            os.rmdir(dirpath)
            removed.append(_posix_rel(dirpath, base))
        except OSError:
            pass
    return removed


def verify_archive_file(path, expected_base="", expected_blend=""):
    if not path or not os.path.isfile(path):
        return False, "压缩包不存在"
    if os.path.getsize(path) <= 0:
        return False, "压缩包是空的"
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()

        if not any(n.lower().endswith(".blend") for n in names):
            return False, "包里没有 .blend"
        if expected_base:
            nested = [n for n in names if n == expected_base or
                      n.startswith(expected_base + "/")]
            if nested:
                return False, "包里又套了一层同名根目录 %s/（%d 个条目），不该出现" % (
                    expected_base, len(nested))
        if expected_blend and expected_blend not in names:
            return False, "包根目录下没有 %s，不是这个归档根的快照" % expected_blend
            source_dir = os.path.join(os.path.dirname(path), expected_base)
            if os.path.isdir(source_dir):
                on_disk = 0
                for _r, _d, files in os.walk(source_dir):
                    on_disk += len(files)
                in_zip = len([n for n in names if not n.endswith("/")])
                if in_zip != on_disk:
                    return False, "包里只有 %d 个文件，磁盘上有 %d 个，压包不完整" % (
                        in_zip, on_disk)
    except Exception as exc:
        return False, "压缩包读不开：%r" % exc
    return True, "%d 字节" % os.path.getsize(path)


def remove_working_folder(archive_root, archive_file, report):
    if not archive_file or not os.path.isfile(archive_file):
        report["warnings"].append("没有可用的压缩包，工作文件夹保留在：%s" % archive_root)
        return False
    if not os.path.isdir(archive_root):
        return False
    if os.path.dirname(os.path.normpath(archive_root)) != os.path.dirname(
        os.path.normpath(archive_file)
    ):
        report["warnings"].append("归档目录不在压缩包同级，为安全起见没有删除")
        return False
    try:
        shutil.rmtree(archive_root)
    except Exception as exc:
        report["warnings"].append("工作文件夹删除失败（压缩包已生成，可手动删）：%r" % exc)
        return False
    report["folder_removed"] = True
    return True


def write_report_copy(report):
    root = report.get("archive_root") or ""
    if not root or not os.path.isdir(root):
        return ""
    path = os.path.join(root, "归档报告.json")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            payload = {k: v for k, v in report.items() if not k.startswith("_")}
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path
    except Exception as exc:
        report["warnings"].append("归档报告写盘失败：%r" % exc)
        return ""


def run_job(job):
    started = time.time()
    report = {
        "ok": False,
        "error": "",
        "version": VERSION,
        "blender": bpy.app.version_string,
        "archive_root": "",
        "archive_blend": "",
        "archive_file": "",
        "report_file": "",
        "folder_removed": False,
        "preview": "",
        "steps": [],
        "warnings": [],
        "errors": [],
        "missing": [],
        "skipped": [],
        "summary": {},
        "verify": {},
        "pre_existing_missing": [],
        "remap": {"ok": 0, "failed": []},
        "blend_backups": [],
        "pruned_empty_dirs": [],
        "save_backups_disabled": False,
        "seconds": 0.0,
    }

    archive_root = os.path.abspath(job.get("archive_root") or "")
    archive_name = job.get("archive_name") or "archive"
    options = job.get("options", {})
    backups_off = _disable_save_backups()
    report["save_backups_disabled"] = bool(backups_off)
    if not backups_off:
        report["warnings"].append(
            "没能关掉 Blender 的自动存盘备份，归档里可能会多出一个 .blend1"
        )

    try:
        if not archive_root:
            raise ValueError("没有指定归档目录")
        report["archive_root"] = archive_root

        if os.path.isdir(archive_root) and os.listdir(archive_root):
            report["warnings"].append("归档目录已存在且非空，同名文件会被覆盖：%s" % archive_root)
        os.makedirs(archive_root, exist_ok=True)
        _step(report, "建立归档目录", archive_root)

        records, scan_warnings = scan.scan(only_used=bool(options.get("only_used", True)))
        report["warnings"].extend(scan_warnings)
        _step(report, "扫描外部资源", "%d 条引用" % len(records))

        pre_refs, pre_images, pre_raws = pre_missing_index(records)
        report["pre_existing_missing"] = pre_raws
        if pre_raws:
            report["warnings"].append(
                "有 %d 个资源在归档之前就已经找不到了（不是归档弄丢的，路径原样保留）：%s"
                % (len(pre_raws), "、".join(os.path.basename(p) for p in pre_raws[:5]))
            )

        plan_result = plan.build_plan(
            records,
            archive_root,
            dedupe=bool(options.get("dedupe", True)),
        )
        report["summary"] = plan.summarize(plan_result)
        report["missing"] = [
            {"src": m["src"], "owner": m.get("owner", "")} for m in plan_result["missing"]
        ]
        report["skipped"] = plan_result["skipped"]
        _step(
            report,
            "编译拷贝清单",
            "%d 项（含 %d 项目录），去重省下 %d 条引用"
            % (len(plan_result["entries"]), report["summary"]["dirs"],
               report["summary"]["deduped"]),
        )

        copied = 0
        for entry in plan_result["entries"]:
            if _copy_entry(entry, report["warnings"], report["errors"]):
                copied += 1
        _step(report, "拷贝资源", "%d/%d 项成功" % (copied, len(plan_result["entries"])))

        archive_blend = os.path.join(archive_root, "%s.blend" % archive_name)
        bpy.ops.wm.save_as_mainfile(
            filepath=archive_blend,
            check_existing=False,
            compress=True,
            relative_remap=False,
        )
        report["archive_blend"] = archive_blend
        _step(report, "保存归档内 .blend", os.path.basename(archive_blend))

        ok_count, failed = apply_remap(plan_result, records, report)
        report["remap"] = {"ok": ok_count, "failed": failed}
        _step(report, "改写为相对路径", "%d 条成功，%d 条失败" % (ok_count, len(failed)))
        if failed:
            report["warnings"].append("有 %d 条引用没能改写，请检查报告" % len(failed))

        try:
            bpy.ops.wm.save_mainfile(compress=True, relative_remap=False)
        except Exception:
            bpy.ops.wm.save_as_mainfile(filepath=archive_blend, check_existing=False,
                                        compress=True, relative_remap=False)
        report["blend_backups"] = _sweep_blend_backups(archive_blend)
        _step(report, "二次存盘", "相对路径已写回 .blend")

        _attach_preview(job, archive_root, report)

        results, _recs = verify(archive_root, pre_refs, pre_images)
        report["verify"] = results
        _step(
            report,
            "自检重扫",
            "引用 %d 条 / 绝对路径残留 %d / 断链 %d / 归档前就缺 %d"
            % (results["records"], len(results["absolute_paths"]),
               len(results["broken_paths"]), len(results["pre_existing_missing"])),
        )

        report["archive_file"] = archive_target_path(archive_root)
        report["pruned_empty_dirs"] = prune_empty_dirs(archive_root)
        if report["pruned_empty_dirs"]:
            _step(report, "清掉空目录", "、".join(report["pruned_empty_dirs"]))
        archive_file = make_archive(archive_root, report)
        report["archive_file"] = archive_file
        packed_ok, detail = verify_archive_file(
            archive_file,
            expected_base=os.path.basename(archive_root),
            expected_blend=os.path.basename(archive_blend),
        )
        _step(
            report,
            "校验压缩包",
            "%s / %s" % (os.path.basename(archive_file) if archive_file else "（没生成）", detail),
        )

        refs_ok = not results["broken_paths"] and not results["absolute_paths"]
        report["ok"] = bool(archive_file) and packed_ok and not report["errors"] and refs_ok
        if report["ok"]:
            if remove_working_folder(archive_root, archive_file, report):
                _step(report, "清理工作文件夹", "只留压缩包")
                report["report_file"] = ""
        elif not archive_file:
            report["error"] = "没能生成压缩包，工作文件夹保留在：%s" % archive_root
            report["warnings"].append("压缩包未生成，已保留工作文件夹，不会让你白跑一趟")
        elif not refs_ok:
            report["error"] = "归档完成但自检未通过：存在断链或绝对路径残留，详见工作文件夹里的报告"
        elif not packed_ok:
            report["error"] = "压缩包校验未通过（%s），工作文件夹已保留" % detail
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()

    report["seconds"] = round(time.time() - started, 2)
    _cleanup_preview(job.get("preview_src"))
    _cleanup_snapshot(job.get("snapshot"))
    if not report.get("report_file"):
        if os.path.isdir(report.get("archive_root") or ""):
            report["report_file"] = write_report_copy(report)
    return report


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if not args:
        print("BARC: 缺少 job.json 参数")
        return 2
    job_path = args[0]
    report_path = args[1] if len(args) > 1 else job_path + ".report.json"
    try:
        with open(job_path, "r", encoding="utf-8") as handle:
            job = json.load(handle)
    except Exception as exc:
        print("BARC: 读取 job 失败 %r" % exc)
        return 2

    try:
        report = run_job(job)
    except Exception as exc:
        report = {
            "ok": False,
            "error": "worker 自己崩了：%s: %s" % (type(exc).__name__, exc),
            "traceback": traceback.format_exc()[-2000:],
            "warnings": [],
            "errors": [],
            "steps": [],
            "summary": {},
            "verify": {},
        }
        print(report["traceback"])
    try:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        print("BARC: 写 report 失败 %r" % exc)
        return 2
    print("BARC_DONE ok=%s %s" % (report.get("ok"), report_path))
    return 0 if report.get("ok") else 1


if __name__ == "__main__" or os.environ.get("BARC_AUTORUN") == "1":
    sys.exit(main())
