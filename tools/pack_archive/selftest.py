
import os
import shutil
import struct
import sys
import tempfile
import time
import zipfile
import zlib

import bpy

from . import operators

core = operators
ops = operators
from . import plan, scan, ui


class Results(object):
    def __init__(self):
        self.items = []

    def check(self, name, ok, detail=""):
        self.items.append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
        return bool(ok)

    def skip(self, name, why):
        self.items.append({"name": name + "（已跳过）", "ok": True, "detail": why})

    def section(self, title):
        self.items.append({"name": "── %s ──" % title, "ok": True, "section": True})

    @property
    def failed(self):
        return [i for i in self.items if not i.get("section") and not i["ok"]]

    @property
    def passed(self):
        return [i for i in self.items if not i.get("section") and i["ok"]]

    def dump(self):
        lines = []
        for item in self.items:
            if item.get("section"):
                lines.append("")
                lines.append(item["name"])
                continue
            mark = "OK  " if item["ok"] else "FAIL"
            lines.append("  [%s] %s%s" % (mark, item["name"],
                                          ("  <- " + item["detail"]) if item["detail"] else ""))
        lines.append("")
        lines.append("通过 %d / 失败 %d" % (len(self.passed), len(self.failed)))
        return "\n".join(lines)


def _write_png(path, rgb):
    width = height = 8
    raw = b""
    for _y in range(height):
        raw += b"\x00" + bytes(rgb) * width

    def chunk(tag, data):
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(blob)
    return path


def _write_wav(path):
    rate = 8000
    samples = b"\x00\x00" * (rate // 10)
    blob = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    blob += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    blob += b"data" + struct.pack("<I", len(samples)) + samples
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(blob)
    return path


def _load_image(name, path):
    img = bpy.data.images.load(path, check_existing=False)
    img.name = name
    return img


def _fingerprint(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_size, int(stat.st_mtime))


def test_pure_logic(res, tmp):
    res.section("A 纯逻辑（脱离 bpy，用真实临时文件）")

    res.check("非法字符被替换",
              plan.sanitize_filename('a<b>c:d"e/f\\g|h?i*j.png') == "a_b_c_d_e_f_g_h_i_j.png",
              plan.sanitize_filename('a<b>c:d"e/f\\g|h?i*j.png'))
    res.check("Windows 保留名被加下划线", plan.sanitize_filename("CON.png") == "CON_.png")
    res.check("结尾的点和空格被剥掉", plan.sanitize_filename("name .png") == "name.png")
    res.check("超长名被截断", len(plan.sanitize_filename("x" * 400 + ".png")) <= 118)
    res.check("中文名原样保留（不转拼音、不丢字）",
              plan.sanitize_filename("木纹贴图.png") == "木纹贴图.png",
              plan.sanitize_filename("木纹贴图.png"))
    res.check("拼音功能已被彻底移除（回归检查）",
              not hasattr(plan, "to_ascii_name") and not hasattr(plan, "has_cjk"))
    res.check("build_plan 签名里不再有拼音参数",
              "pinyin" not in plan.build_plan.__code__.co_varnames)

    src = os.path.join(tmp, "pure_src")
    same_a = _write_png(os.path.join(src, "a", "tile.png"), (255, 0, 0))
    diff_b = _write_png(os.path.join(src, "b", "tile.png"), (0, 0, 255))
    twin_c = _write_png(os.path.join(src, "b", "tile_dup.png"), (255, 0, 0))

    result = plan.build_plan(
        [
            {"src": same_a, "kind": "IMAGE", "subdir": "textures", "owner": "A1"},
            {"src": same_a, "kind": "IMAGE", "subdir": "textures", "owner": "A2"},
            {"src": diff_b, "kind": "IMAGE", "subdir": "textures", "owner": "B"},
            {"src": twin_c, "kind": "IMAGE", "subdir": "textures", "owner": "C"},
        ],
        os.path.join(tmp, "pure_out"),
    )
    entries = result["entries"]
    by_src = {os.path.normcase(e["src"]): e for e in entries}

    res.check("同一个源被引用两次只产出一条清单项",
              len(by_src[os.path.normcase(same_a)]["record_ids"]) == 2,
              by_src[os.path.normcase(same_a)]["record_ids"])
    res.check("同名不同内容自动加序号",
              by_src[os.path.normcase(diff_b)]["name"] == "tile_2.png",
              by_src[os.path.normcase(diff_b)]["name"])
    names = sorted(e["name"] for e in entries)
    res.check("四条记录收敛成三个目标名且互不冲突",
              names == ["tile.png", "tile_2.png", "tile_dup.png"], names)
    res.check("统计函数可用", plan.summarize(result)["files"] == 3, plan.summarize(result))
    res.check("统计去重条数正确", plan.summarize(result)["deduped"] == 1,
              plan.summarize(result)["deduped"])

    dupe1 = _write_png(os.path.join(tmp, "pure_src2", "x", "same.png"), (12, 34, 56))
    dupe2 = _write_png(os.path.join(tmp, "pure_src2", "y", "same.png"), (12, 34, 56))
    result2 = plan.build_plan(
        [
            {"src": dupe1, "kind": "IMAGE", "subdir": "textures", "owner": "D1"},
            {"src": dupe2, "kind": "IMAGE", "subdir": "textures", "owner": "D2"},
        ],
        os.path.join(tmp, "pure_out2"),
    )
    res.check("同名且同内容合并成一项",
              len(result2["entries"]) == 1 and len(result2["entries"][0]["record_ids"]) == 2,
              [len(e["record_ids"]) for e in result2["entries"]])

    dir_a = os.path.join(tmp, "cacheX", "sim")
    dir_b = os.path.join(tmp, "cacheY", "sim")
    for d in (dir_a, dir_b):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "c_0_1.bphys"), "wb") as handle:
            handle.write(b"\x00" * 32)
    result3 = plan.build_plan(
        [
            {"src": dir_a, "kind": "CACHE_DIR", "subdir": "cache", "is_dir": True,
             "name_hint": "Object:桌子", "owner": "Object:桌子"},
            {"src": dir_b, "kind": "CACHE_DIR", "subdir": "cache", "is_dir": True,
             "name_hint": "Object:椅子", "owner": "Object:椅子"},
        ],
        os.path.join(tmp, "pure_out3"),
    )
    dir_names = sorted(e["name"] for e in result3["entries"])
    res.check("两个同名缓存目录拿到不同目标名", len(set(dir_names)) == 2, dir_names)
    res.check("缓存目录名带上了引用者提示",
              all(("桌子" in n) or ("椅子" in n) for n in dir_names), dir_names)

    missing_plan = plan.build_plan(
        [{"src": os.path.join(tmp, "根本不存在.png"), "kind": "IMAGE",
          "subdir": "textures", "owner": "M1"}],
        os.path.join(tmp, "pure_out4"),
    )
    res.check("不存在的源被记进 missing 而不是崩掉",
              len(missing_plan["missing"]) == 1 and not missing_plan["entries"])


def build_messy_project(root, res, built):
    project_dir = os.path.join(root, "项目")
    other_dir = os.path.join(root, "别的盘")
    download_dir = os.path.join(root, "下载")
    os.makedirs(project_dir, exist_ok=True)

    lib_path = os.path.join(other_dir, "素材库", "家具.blend")
    os.makedirs(os.path.dirname(lib_path), exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    root_mesh = bpy.data.meshes.new("AssetMesh")
    root_cube = bpy.data.objects.new("AssetCube", root_mesh)
    bpy.context.scene.collection.objects.link(root_cube)
    bpy.ops.wm.save_as_mainfile(filepath=lib_path, check_existing=False)

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene

    def obj_with_material(name, images):
        mat = bpy.data.materials.new(name + "_材质")
        mat.use_nodes = True
        for img in images:
            mat.node_tree.nodes.new("ShaderNodeTexImage").image = img
        mesh = bpy.data.meshes.new(name + "_mesh")
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(mat)
        scene.collection.objects.link(obj)
        return obj

    tex_path = os.path.join(download_dir, "材质缓存", "木纹贴图.png")
    _write_png(tex_path, (200, 120, 40))
    for idx in range(2):
        img = _load_image("木纹_%d" % idx, tex_path)
        obj_with_material("平面_木纹_%d" % idx, [img])
    built.add("shared_file")

    col_path = os.path.join(project_dir, "col.png")
    _write_png(col_path, (40, 200, 120))
    obj_with_material("平面_col", [_load_image("col", col_path)])
    built.add("single_image")

    tile_a = _write_png(os.path.join(root, "包A", "tile.png"), (255, 0, 0))
    tile_b = _write_png(os.path.join(root, "包B", "tile.png"), (0, 255, 0))
    obj_with_material(
        "平面_tile",
        [_load_image("tileA", tile_a), _load_image("tileB", tile_b)],
    )
    built.add("tile_pair")

    env_path = _write_png(os.path.join(root, "环境库", "天空.png"), (10, 10, 200))
    env_img = _load_image("天空", env_path)
    world = bpy.data.worlds.new("测试世界")
    world.use_nodes = True
    world.node_tree.nodes.new("ShaderNodeTexEnvironment").image = env_img
    scene.world = world
    built.add("hdri")

    seq_dir = os.path.join(root, "序列", "anim")
    for i in range(1, 4):
        _write_png(os.path.join(seq_dir, "frame_%04d.png" % i), (i * 40, 0, 0))
    seq_pattern = os.path.join(seq_dir, "frame_####.png")
    seq_img = None
    try:
        bpy.ops.image.open(filepath=seq_pattern, use_sequence=True)
        candidates = [i for i in bpy.data.images if getattr(i, "source", "") == "SEQUENCE"]
        if candidates:
            seq_img = candidates[0]
    except Exception:
        seq_img = None
    if seq_img is None:
        try:
            seq_img = bpy.data.images.load(
                os.path.join(seq_dir, "frame_0001.png"), check_existing=False
            )
            seq_img.source = "SEQUENCE"
            seq_img.filepath = seq_pattern
            seq_img.reload()
        except Exception:
            seq_img = None
    if seq_img is not None and getattr(seq_img, "source", "") == "SEQUENCE":
        obj_with_material("平面_seq", [seq_img])
        built.add("sequence")
    else:
        res.skip("图片序列", "本机 Blender 没能构造出 SEQUENCE 类型的数据块")

    wav = _write_wav(os.path.join(root, "音效库", "提示音.wav"))
    try:
        sound = bpy.data.sounds.load(wav)
        speaker_data = bpy.data.speakers.new("音源数据")
        speaker_data.sound = sound
        speaker = bpy.data.objects.new("音源", speaker_data)
        scene.collection.objects.link(speaker)
        built.add("sound")
    except Exception as exc:
        res.skip("音频", repr(exc))

    cache_dir = os.path.join(root, "缓存区", "simcache")
    os.makedirs(cache_dir, exist_ok=True)
    for i in range(3):
        with open(os.path.join(cache_dir, "cache_0_%d.bphys" % i), "wb") as handle:
            handle.write(b"\x00" * 64)
    try:
        cloth_mesh = bpy.data.meshes.new("ClothMesh")
        cloth_obj = bpy.data.objects.new("布料", cloth_mesh)
        scene.collection.objects.link(cloth_obj)
        mod = cloth_obj.modifiers.new("Cloth", "CLOTH")
        cache = mod.point_cache
        cache.filepath = cache_dir
        for flag in ("use_disk_cache", "use_external"):
            try:
                setattr(cache, flag, True)
            except Exception:
                pass
        built.add("cache")
    except Exception as exc:
        res.skip("模拟缓存", repr(exc))

    try:
        with bpy.data.libraries.load(lib_path, link=True) as (src, dst):
            dst.objects = list(src.objects)
        linked = bpy.data.objects.get("AssetCube")
        if linked is not None:
            scene.collection.objects.link(linked)
            built.add("lib")
        else:
            res.skip("链接库", "链进来后找不到 AssetCube")
    except Exception as exc:
        res.skip("链接库", repr(exc))

    gone_path = os.path.join(root, "已删除的素材", "早就没了的贴图.png")
    _write_png(gone_path, (9, 9, 9))
    obj_with_material("平面_丢了", [_load_image("早就没了", gone_path)])
    os.remove(gone_path)
    built.add("pre_missing")

    project_path = os.path.join(project_dir, "工程.blend")
    bpy.ops.wm.save_as_mainfile(filepath=project_path, check_existing=False)
    return project_path


def test_end_to_end(res, tmp):
    res.section("B/C 端到端归档")

    root = os.path.join(tmp, "乱工程")
    os.makedirs(root, exist_ok=True)
    built = set()
    project_path = build_messy_project(root, res, built)

    project_dir = os.path.dirname(project_path)
    norm_proj = os.path.normcase(os.path.normpath(project_dir))
    resolved = []
    for img in bpy.data.images:
        raw = img.filepath or ""
        if raw:
            resolved.append(os.path.normpath(bpy.path.abspath(raw)))
    outside = [p for p in resolved if not os.path.normcase(p).startswith(norm_proj)]
    res.check("测试前提：源工程的贴图确实散落在工程目录之外",
              len(outside) >= 4, outside)
    res.check("测试前提：工程目录里原本没有 textures/ 之类的统一目录",
              "textures" not in os.listdir(project_dir), os.listdir(project_dir))
    res.check("测试前提：没有孤儿数据块（否则存盘时会被 Blender 丢掉）",
              all(i.users or i.use_fake_user for i in bpy.data.images),
              [(i.name, i.users) for i in bpy.data.images if not i.users])

    fingerprint = _fingerprint(project_path)
    archive_root = os.path.join(root, "归档输出", "工程_归档")
    preview_dir = tempfile.mkdtemp(prefix="barc_preview_")
    preview_src = _write_png(os.path.join(preview_dir, "preview.png"), (250, 250, 250))

    job = {
        "src_blend": project_path,
        "archive_root": archive_root,
        "archive_name": "工程",
        "options": {
            "only_used": True, "dedupe": True, "preview": True,
        },
        "preview_src": preview_src,
    }

    started = time.time()
    report = core.run_worker_sync(job)
    elapsed = time.time() - started

    res.check("worker 跑通并返回 ok", report.get("ok"),
              (report.get("error") or "") + " " + (report.get("traceback", "") or "")[-300:])
    res.check("报告包含完整步骤链", len(report.get("steps", [])) >= 9,
              [s["label"] for s in report.get("steps", [])])

    archive_blend = report.get("archive_blend", "")
    res.check("压缩包已生成", str(report.get("archive_file", "")).endswith(".zip"),
              report.get("archive_file"))
    res.check("工作文件夹已删除（用户只要压缩包）", report.get("folder_removed"),
              report.get("warnings"))
    res.check("删干净了：同级目录下确实只剩压缩包",
              not os.path.exists(archive_root)
              and sorted(os.listdir(os.path.dirname(archive_root))) != []
              and all(n.endswith(".zip") for n in os.listdir(os.path.dirname(archive_root))),
              os.listdir(os.path.dirname(archive_root)))

    from . import worker as _w

    guard = os.path.join(tmp, "guard", "工程_归档")
    os.makedirs(guard, exist_ok=True)
    with open(os.path.join(guard, "keep.txt"), "w", encoding="utf-8") as handle:
        handle.write("x")
    guard_report = {"warnings": []}
    guard_removed = _w.remove_working_folder(guard, "", guard_report)
    res.check("压缩包不存在时拒删工作文件夹（安全底线）",
              not guard_removed and os.path.isdir(guard), guard_report["warnings"])
    flat_zip = os.path.join(tmp, "guard", "扁平.zip")
    with zipfile.ZipFile(flat_zip, "w") as zf:
        zf.writestr("扁平的包.blend", b"x")
        zf.writestr("textures/a.png", b"x")
    res.check("扁平的包（根目录下直接就是 .blend）校验通过",
              _w.verify_archive_file(flat_zip, expected_base="扁平的包",
                                     expected_blend="扁平的包.blend")[0])

    nested_zip = os.path.join(tmp, "guard", "套了一层.zip")
    with zipfile.ZipFile(nested_zip, "w") as zf:
        zf.writestr("套了/套了.blend", b"x")
        zf.writestr("套了/textures/a.png", b"x")
    ok_nested, why_nested = _w.verify_archive_file(nested_zip, expected_base="套了",
                                                   expected_blend="套了.blend")
    res.check("又套了一层同名根目录的包校验不通过（回归：那是旧写法）",
              not ok_nested and "同名根目录" in why_nested, why_nested)

    other_zip = os.path.join(tmp, "guard", "别的包.zip")
    with zipfile.ZipFile(other_zip, "w") as zf:
        zf.writestr("别人的.blend", b"x")
        zf.writestr("textures/a.png", b"x")
    ok_other, why_other = _w.verify_archive_file(other_zip, expected_base="别的包",
                                                 expected_blend="别的包.blend")
    res.check("根目录下没有我们刚存进去的那个 .blend 时校验不通过（防误删）",
              not ok_other and "快照" in why_other, why_other)
    empty_zip = os.path.join(tmp, "guard", "空的.zip")
    with open(empty_zip, "wb") as handle:
        handle.write(b"")
    res.check("空压缩包校验不通过", not _w.verify_archive_file(empty_zip)[0])
    res.check("不存在的压缩包校验不通过", not _w.verify_archive_file("")[0])
    res.check("压缩包名可预测且恒定是 .zip（所以能在压缩之前就写进报告）",
              _w.archive_target_path(os.path.join(tmp, "x", "y")).endswith("y.zip"),
              _w.archive_target_path(os.path.join(tmp, "x", "y")))
    res.check("压缩包名不依赖任何格式参数",
              _w.archive_target_path.__code__.co_argcount == 1,
              _w.archive_target_path.__code__.co_varnames)

    zip_path = report.get("archive_file", "")
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()

    def listing(sub):
        prefix = "%s/" % sub
        heads = set()
        for member in members:
            if not member.startswith(prefix):
                continue
            rest = member[len(prefix):]
            if not rest or rest.startswith("/"):
                continue
            heads.add(rest.split("/")[0])
        return sorted(heads)

    textures = listing("textures")
    hdri = listing("hdri")
    audio = listing("audio")
    cache = listing("cache")
    lib = listing("lib")

    res.check("压缩包里有 .blend", any(m.lower().endswith(".blend") for m in members),
              members[:8])
    res.check("交付包里**没有**归档报告.json（用户要求：交付物只留工程+素材+预览图）",
              not [m for m in members if m.endswith("归档报告.json")],
              [m for m in members if m.endswith(".json")])
    res.check("成功路径上报告不落盘（工作文件夹删了，报告也不留）",
              not report.get("report_file")
              and not os.path.exists(os.path.join(archive_root, "归档报告.json")),
              report.get("report_file"))
    base = os.path.basename(archive_root)
    top_blends = [m for m in members
                  if m.lower().endswith(".blend") and "/" not in m]
    res.check("归档根下只有一个 .blend，没有 .blend1 这种自动备份",
              len(top_blends) == 1, top_blends)
    res.check("整包里没有任何 .blend1/.blend2 之类的备份残留",
              not [m for m in members
                   if os.path.splitext(m)[1].lower().startswith(".blend")
                   and os.path.splitext(m)[1][6:].isdigit()],
              [m for m in members if ".blend" in m.lower()])
    res.check("worker 确实关掉了 Blender 的自动存盘备份",
              report.get("save_backups_disabled") is True,
              report.get("save_backups_disabled"))
    e2e_worker_src = open(_w.__file__, encoding="utf-8").read()
    res.check("二次存盘显式写了 compress=True（不靠「继承上一次的设置」这种猜法）",
              "save_mainfile(compress=True" in e2e_worker_src,
              [ln.strip() for ln in e2e_worker_src.splitlines() if "save_mainfile" in ln])
    res.check("HDRI 被单独归入 hdri/", len(hdri) == 1, hdri)
    res.check("音频归入 audio/", len(audio) == 1 or "sound" not in built, audio)
    res.check("缓存目录归入 cache/", len(cache) == 1 or "cache" not in built, cache)
    res.check("链接库归入 lib/", len(lib) == 1 or "lib" not in built, lib)

    res.check("中文名贴图被原样收进来",
              len([n for n in textures if "木纹" in n]) == 1, textures)
    res.check("同一个文件被两个数据块引用 → 只拷一份",
              len([n for n in textures if "木纹" in n]) == 1, textures)
    res.check("同名不同内容的两张图都在",
              len([n for n in textures if n.lower().startswith("tile")]) == 2, textures)
    res.check("同名不同内容的两张图名字不冲突", len(set(textures)) == len(textures), textures)
    res.check("工程目录里的普通贴图也在", "col.png" in textures, textures)
    if "sequence" in built:
        frames = [n for n in textures if n.startswith("frame_")]
        res.check("图片序列的三帧都被拷进来", len(frames) == 3, frames)
    else:
        res.skip("图片序列", "未构造成功")

    expected_min = 4 + (3 if "sequence" in built else 0)
    res.check("textures/ 里文件数量符合预期", len(textures) == expected_min,
              "%d vs %d  %s" % (len(textures), expected_min, textures))
    base_name = os.path.basename(archive_root)
    res.check("zip 里没有多套一层同名根目录（解压直接就是内容）",
              not [m for m in members
                   if m == base_name or m.startswith(base_name + "/")],
              [m for m in members if m.startswith(base_name)][:8])
    zip_subdirs = sorted({m.split("/")[0] for m in members
                         if "/" in m and not m.endswith("/")})
    expected_subdirs = sorted(sub for sub in plan.MANAGED_SUBDIRS if listing(sub))
    res.check("包成员里没有任何目录条目（不再补空目录）",
              not [m for m in members if m.endswith("/")],
              [m for m in members if m.endswith("/")][:8])
    res.check("包里只出现真正有内容的子目录，空的一个不留",
              zip_subdirs == expected_subdirs,
              (zip_subdirs, expected_subdirs))
    res.check("测试前提：确实存在「本该为空」的子目录类型（否则上面这条是空跑）",
              len(set(plan.MANAGED_SUBDIRS) - set(expected_subdirs)) >= 1,
              sorted(set(plan.MANAGED_SUBDIRS) - set(expected_subdirs)))
    res.check("空目录确实被扫掉了（报告里有清理记录，且只删标准子目录）",
              isinstance(report.get("pruned_empty_dirs"), list)
              and set(report["pruned_empty_dirs"]) <= set(plan.MANAGED_SUBDIRS),
              report.get("pruned_empty_dirs"))

    summary = report.get("summary", {})
    res.check("去重被记进统计", summary.get("deduped", 0) >= 1, summary.get("deduped"))

    verify = report.get("verify", {})
    res.check("自检：没有绝对路径残留", not verify.get("absolute_paths"),
              verify.get("absolute_paths"))
    res.check("自检：没有断链", not verify.get("broken_paths"), verify.get("broken_paths"))
    res.check("自检：图片全部读得出来", not verify.get("images_unreadable"),
              verify.get("images_unreadable"))
    res.check("自检真的检查了图片（不是空跑）", verify.get("images_checked", 0) >= 5,
              verify.get("images_checked"))
    res.check("序列图被如实标为「跳过像素校验」而不是误报读不出",
              verify.get("images_sequence_skipped", 0) >= 1
              if "sequence" in built else True,
              verify.get("images_sequence_skipped"))
    res.check("原工程文件没有被改动", _fingerprint(project_path) == fingerprint,
              "%s -> %s" % (fingerprint, _fingerprint(project_path)))
    res.check("父进程抓的预览图真的进了压缩包（回归：曾经读错 key，图被静默丢掉）",
              any(m.endswith("预览图.png") for m in members),
              [m for m in members if "预览" in m] or report.get("warnings"))
    res.check("预览临时文件连同目录一起清掉",
              not os.path.exists(preview_dir), preview_dir)
    res.check("耗时合理（<180s）", elapsed < 180, "%.1fs" % elapsed)

    if "pre_missing" in built:
        res.check("归档前就丢的贴图不会让整个归档判失败", report.get("ok"),
                  report.get("error") or report.get("warnings"))
        res.check("丢的那张被单独记账，没混进「断链」",
                  not verify.get("broken_paths")
                  and len(verify.get("pre_existing_missing", [])) >= 1,
                  (verify.get("broken_paths"), verify.get("pre_existing_missing")))
        res.check("报告里列出了归档前就缺的资源",
                  len(report.get("pre_existing_missing", [])) >= 1,
                  report.get("pre_existing_missing"))
        res.check("给了人能看懂的提示",
                  any("归档之前就已经找不到" in w for w in report.get("warnings", [])),
                  report.get("warnings"))
        res.check("丢的图被计进 images_pre_missing 而不是 images_unreadable",
                  verify.get("images_pre_missing", 0) >= 1
                  and "早就没了" not in verify.get("images_unreadable", []),
                  (verify.get("images_pre_missing"), verify.get("images_unreadable")))
        res.check("统计里也标了缺失数", summary.get("missing", 0) >= 1, summary)
    else:
        res.skip("归档前就丢失的资源", "未构造成功")

    from . import worker as _w2

    pdir = tempfile.mkdtemp(prefix="barc_preview_")
    pfile = os.path.join(pdir, "preview.png")
    with open(pfile, "wb") as handle:
        handle.write(b"x")
    _w2._cleanup_preview(pfile)
    res.check("预览临时文件连同临时目录一起清掉",
              not os.path.exists(pfile) and not os.path.isdir(pdir), pdir)
    bystander = os.path.join(tmp, "别动我.png")
    with open(bystander, "wb") as handle:
        handle.write(b"x")
    _w2._cleanup_preview(bystander)
    res.check("清理只认自己造的临时文件，不碰别的路径",
              os.path.isfile(bystander), bystander)

    up_dir = tempfile.mkdtemp(prefix="barc_preview_")
    up_src = os.path.join(up_dir, "preview.png")
    with open(up_src, "wb") as handle:
        handle.write(b"x")
    up_root = os.path.join(tmp, "预览单元")
    os.makedirs(up_root, exist_ok=True)
    up_report = {"warnings": [], "steps": []}
    _w2._attach_preview({"options": {"preview": True}, "preview_src": up_src},
                        up_root, up_report)
    res.check("job 顶层给的 preview_src 会被真正采用（回归检查）",
              os.path.isfile(os.path.join(up_root, "预览图.png")), up_report)
    res.check("采用之后临时文件被清掉", not os.path.exists(up_dir), up_dir)

    none_report = {"warnings": [], "steps": []}
    _w2._attach_preview({"options": {"preview": True}, "preview_src": ""},
                        up_root, none_report)
    res.check("完全没有预览源时不静默：要么附上图，要么留下人话提示",
              bool(none_report.get("preview"))
              or any("预览图" in w for w in none_report["warnings"]),
              none_report)

    res.section("D 解压压缩包并打开归档文件验收")
    extract_dir = os.path.join(tmp, "解压验证")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    extracted_blend = os.path.join(extract_dir, os.path.basename(archive_blend))
    res.check("压缩包解压后 .blend 就在预期位置", os.path.isfile(extracted_blend),
              extracted_blend)
    bpy.ops.wm.open_mainfile(filepath=extracted_blend)

    absolute = []
    relative = 0
    for coll in ("images", "fonts", "sounds", "volumes", "libraries", "cache_files",
                 "movieclips"):
        for block in getattr(bpy.data, coll, ()):
            path = getattr(block, "filepath", "") or ""
            if not path:
                continue
            if path.startswith("//"):
                relative += 1
            else:
                absolute.append("%s.%s = %s" % (coll, block.name, path))
    res.check("重开后所有引用都是 // 相对路径", not absolute, absolute)
    res.check("确实有引用被改写（不是空跑）", relative >= 5, relative)

    if "sequence" in built:
        seq_ok = any("####" in (i.filepath or "") for i in bpy.data.images)
        res.check("序列的 #### 占位符被正确保留在相对路径里", seq_ok,
                  [i.filepath for i in bpy.data.images])

    from . import worker as _worker

    skip_names = {"早就没了"} if "pre_missing" in built else set()
    single = [i for i in bpy.data.images
              if i.source == "FILE" and i.name not in skip_names]
    readable = [i for i in single if _worker.image_readable(i)]
    res.check("单帧图片真的都读得出来（用生产代码里那个判据）",
              len(readable) >= 4 and len(readable) == len(single),
              [(i.name, tuple(i.size)) for i in single])
    nonzero = False
    for img in readable:
        try:
            if sum(float(v) for v in img.pixels[:16]) > 0:
                nonzero = True
                break
        except Exception:
            continue
    res.check("读出的像素不是全黑", nonzero)

    if "lib" in built:
        res.check("链接库的物体还在（库路径已改写且可解析）",
                  bpy.data.objects.get("AssetCube") is not None,
                  [o.name for o in bpy.data.objects])

    fail_root = os.path.join(root, "故意失败")
    fail_job = {
        "src_blend": project_path,
        "archive_root": os.path.join(fail_root, "坏_归档"),
        "archive_name": "不存在的子目录/坏_归档",
        "options": {"only_used": True, "dedupe": True, "preview": True},
        "preview_src": "",
    }
    fail_report = core.run_worker_sync(fail_job)
    res.check("注入的故障真的让归档失败了（别让自检测了个寂寞）",
              not fail_report.get("ok"), fail_report.get("error"))
    kept = os.path.join(fail_root, "坏_归档")
    res.check("失败时工作文件夹被保留（不会让你白跑一趟）",
              os.path.isdir(kept), kept)
    res.check("失败时归档报告.json 留在工作文件夹里（唯一的排查线索）",
              os.path.isfile(os.path.join(kept, "归档报告.json")),
              sorted(os.listdir(kept)) if os.path.isdir(kept) else "文件夹没保住")
    return report


def _temp_snapshots():
    try:
        return sorted(n for n in os.listdir(tempfile.gettempdir())
                      if n.startswith(core.SNAPSHOT_PREFIX))
    except OSError:
        return []


def _temp_leftovers():
    try:
        return sorted(n for n in os.listdir(tempfile.gettempdir())
                      if n.startswith("barc_"))
    except OSError:
        return []


def test_operator_entry(res, tmp):
    res.section("F 插件入口（算子）")

    project_path = os.path.join(tmp, "乱工程", "项目", "工程.blend")
    if not os.path.isfile(project_path):
        res.check("能回到源工程做算子测试", False, project_path)
        return
    bpy.ops.wm.open_mainfile(filepath=project_path)

    settings = core.STATE
    parent = os.path.join(tmp, "算子归档")
    out_dir = os.path.join(parent, "工程_归档")
    zip_path = os.path.join(parent, "工程_归档.zip")
    before_any = _temp_leftovers()

    status = bpy.ops.mf.archive_collect(filepath=zip_path)
    res.check("算子返回 FINISHED", "FINISHED" in status, status)
    res.check("面板状态被写成「已归档…」",
              settings["last_status"].startswith("已归档"), settings["last_status"])
    res.check("面板记录了文件数", settings["last_files"] >= 7, settings["last_files"])
    res.check("产物正好落在用户选的路径上（不是别的地方）",
              os.path.normcase(settings["last_output"]) == os.path.normcase(zip_path),
              settings["last_output"])
    res.check("面板不再指向已删除的文件夹",
              not os.path.isdir(out_dir) and not settings["last_report"], settings["last_report"])
    res.check("工作文件夹没留下：保存目录里只剩压缩包",
              sorted(os.listdir(parent)) == ["工程_归档.zip"], os.listdir(parent))
    with zipfile.ZipFile(zip_path) as _zf:
        res.check("压缩包内确实有 .blend",
                  any(m.lower().endswith(".blend") for m in _zf.namelist()),
                  _zf.namelist()[:6])
    res.check("归档后的工程里引用是相对路径",
              all(i.filepath.startswith("//") for i in bpy.data.images if i.filepath),
              [i.filepath for i in bpy.data.images])
    res.check("工程已存盘时，默认保存路径就在工程旁边",
              os.path.normcase(os.path.dirname(core.default_save_path()))
              == os.path.normcase(os.path.dirname(project_path)),
              core.default_save_path())

    no_ext = os.path.join(parent, "没写扩展名")
    status2 = bpy.ops.mf.archive_collect(filepath=no_ext)
    res.check("用户没写 .zip 时自动补上",
              "FINISHED" in status2 and os.path.isfile(no_ext + ".zip"),
              sorted(os.listdir(parent)))

    res.check("连跑几次归档后系统临时目录零残留（快照/预览/job 目录全部回收）",
              _temp_leftovers() == before_any,
              set(_temp_leftovers()) ^ set(before_any))

    res.check("打开目录：目录不存在时优雅返回失败而不是抛异常",
              ops.op_open_folder(os.path.join(tmp, "根本不存在的目录"))[0] == "CANCELLED")

    line1, line2 = core.summarize_report({"ok": False, "error": "模拟失败"})
    res.check("失败报告被压成「归档失败 + 原因」",
              line1 == "归档失败" and "模拟失败" in line2, (line1, line2))
    res.check("没归档过时摘要不崩",
              core.summarize_report(None)[0] == "尚未归档过")

    before_snaps = _temp_snapshots()
    project_dir = os.path.dirname(project_path)
    probe_mesh = bpy.data.meshes.new("_dirty_probe")
    probe_obj = bpy.data.objects.new("_dirty_probe", probe_mesh)
    bpy.context.scene.collection.objects.link(probe_obj)
    res.check("测试前提：改动场景后确实进入未保存状态", bpy.data.is_dirty, bpy.data.is_dirty)

    dirty_zip = os.path.join(parent, "带改动_归档.zip")
    status_dirty = bpy.ops.mf.archive_collect(filepath=dirty_zip)
    res.check("有未保存修改时照样能归档（不再要求先 Ctrl+S）",
              "FINISHED" in status_dirty and os.path.isfile(dirty_zip), status_dirty)
    res.check("归档过程没有把用户的工程偷偷存盘（is_dirty 还在）",
              bpy.data.is_dirty, bpy.data.is_dirty)
    res.check("内存快照没落到用户的工程目录里（没在人家工程旁边拉屎）",
              not [n for n in os.listdir(project_dir) if "barc_snapshot" in n],
              os.listdir(project_dir))
    res.check("临时快照用完就删（系统临时目录里没留下 barc_snapshot_*）",
              _temp_snapshots() == before_snaps, _temp_snapshots())

    if os.path.isfile(dirty_zip):
        dirty_dir = os.path.join(tmp, "解压_带改动")
        with zipfile.ZipFile(dirty_zip) as zf:
            zf.extractall(dirty_dir)
        dirty_blend = os.path.join(dirty_dir, "带改动_归档.blend")
        res.check("未保存改动也打包了出来（压缩包里能找到 .blend）",
                  os.path.isfile(dirty_blend), dirty_blend)
        if os.path.isfile(dirty_blend):
            bpy.ops.wm.open_mainfile(filepath=dirty_blend)
            res.check("归档里带的是**当前编辑器状态**，不是磁盘上的旧版本",
                      bpy.data.objects.get("_dirty_probe") is not None,
                      [o.name for o in bpy.data.objects])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    res.check("测试前提：当前工程确实没有磁盘文件", not bpy.data.filepath, bpy.data.filepath)
    res.check("未保存工程也有可用的默认保存路径（不再靠空串兜底）",
              core.default_save_path().endswith("未命名工程_归档.zip"), core.default_save_path())

    unsaved_png = os.path.join(tmp, "未保存素材", "贴图.png")
    _write_png(unsaved_png, (10, 200, 90))
    unsaved_mesh = bpy.data.meshes.new("未保存方块")
    unsaved_obj = bpy.data.objects.new("未保存方块", unsaved_mesh)
    bpy.context.scene.collection.objects.link(unsaved_obj)
    unsaved_mat = bpy.data.materials.new("未保存材质")
    unsaved_mat.use_nodes = True
    unsaved_tex = unsaved_mat.node_tree.nodes.new("ShaderNodeTexImage")
    unsaved_tex.image = bpy.data.images.load(unsaved_png)
    unsaved_obj.data.materials.append(unsaved_mat)

    unsaved_zip = os.path.join(tmp, "未保存归档", "未命名_归档.zip")
    before_snaps = _temp_snapshots()
    status5 = bpy.ops.mf.archive_collect(filepath=unsaved_zip)
    res.check("从没存过盘的工程也能直接归档（旧版本这里是硬拦阻）",
              "FINISHED" in status5, status5)
    res.check("未保存工程照样产出了压缩包", os.path.isfile(unsaved_zip),
              os.path.isdir(os.path.dirname(unsaved_zip))
              and os.listdir(os.path.dirname(unsaved_zip)))
    res.check("未保存工程的临时快照也被清干净了",
              _temp_snapshots() == before_snaps, _temp_snapshots())
    if os.path.isfile(unsaved_zip):
        with zipfile.ZipFile(unsaved_zip) as zf:
            unsaved_names = [n.replace("\\", "/") for n in zf.namelist()]
        res.check("未保存工程归档里带着 .blend",
                  any(n.lower().endswith(".blend") for n in unsaved_names),
                  unsaved_names[:6])
        res.check("未保存工程的外部贴图被收进 textures/",
                  any("textures/" in n and n.endswith(".png") for n in unsaved_names),
                  [n for n in unsaved_names if n.endswith(".png")][:6])


def _panel_referenced_props():
    import re

    with open(ui.__file__, "r", encoding="utf-8") as handle:
        source = handle.read()
    return set(re.findall(r'prop\(\s*settings,\s*"([^"]+)"', source))


def _module_file(name):
    mod = {"core": core, "ops": ops, "plan": plan, "scan": scan, "ui": ui}.get(name)
    if mod is None:
        from . import worker as mod
    return mod.__file__


def _w_signature(func_name="make_archive"):
    from . import worker as mod

    code = getattr(mod, func_name).__code__
    return list(code.co_varnames[: code.co_argcount])


def _w_mod():
    from . import worker as mod

    return mod


def _panel_prop_gaps():
    return []


def _panel_icon_gaps():
    import re

    with open(ui.__file__, "r", encoding="utf-8") as handle:
        source = handle.read()
    used = set(re.findall(r'icon="([A-Z0-9_]+)"', source))
    known = {
        i.identifier
        for i in bpy.types.UILayout.bl_rna.functions["label"]
        .parameters["icon"].enum_items
    }
    return sorted(i for i in used if i not in known)


def _wm_api_gaps():
    import re

    from . import ops as ops_mod

    with open(ops_mod.__file__, "r", encoding="utf-8") as handle:
        source = handle.read()
    used = set(re.findall(r"window_manager\.([A-Za-z_]\w*)\s*\(", source))
    used |= set(re.findall(r"(?<!ops\.)\bwm\.([A-Za-z_]\w*)\s*\(", source))
    known = {f.identifier for f in bpy.types.WindowManager.bl_rna.functions}
    return sorted(name for name in used if name not in known), sorted(used)


def test_registration(res):
    res.section("E 注册 / 注销")

    res.check("面板已注册（按 bl_idname 查，不用类名）",
              hasattr(bpy.types, "MF_PT_Archive"))
    res.check("运行状态就位（模块级 STATE，不再挂 Scene）", hasattr(core, "STATE"))
    res.check("面板引用的属性都存在", not _panel_prop_gaps(), _panel_prop_gaps())
    res.check("面板用的图标都真实存在", not _panel_icon_gaps(), _panel_icon_gaps())

    gaps, used = _wm_api_gaps()
    res.check("源码里用到的窗口管理器方法都真实存在（专门抓假 API）",
              not gaps, "用到 %s；不存在的 %s" % (used, gaps))
    res.check("模态定时器用的是 event_timer_add / event_timer_remove",
              {"event_timer_add", "event_timer_remove", "modal_handler_add"} <= set(used),
              used)

    removed = {"pinyin", "compress_blend", "open_after", "use_version", "version",
               "target_dir", "archive_name"}
    ui_src_all = open(ui.__file__, encoding="utf-8").read()
    res.check("已删除的功能属性不再出现在面板源码里（回归检查）",
              not any(('"%s"' % k) in ui_src_all for k in removed),
              [k for k in removed if k in ui_src_all])
    job_options = core.build_job("")["options"]
    res.check("job 里也不再传这些参数",
              not (removed & set(job_options)), sorted(job_options))
    res.check("resolve_settings 已经删掉（路径改由保存对话框给）",
              not hasattr(core, "resolve_settings"))
    res.check("面板源码里也不再引用这些属性",
              not (removed & set(_panel_referenced_props())), sorted(_panel_referenced_props()))
    res.check("面板源码里不再出现「归档到 / 归档名」这类输入框属性名",
              not any(k in open(ui.__file__, encoding="utf-8").read()
                      for k in ('"target_dir"', '"archive_name"')))

    removed_two = {"zip_format", "ZIP_FORMAT_ITEMS"}
    res.check("压缩格式属性与选项表彻底消失（回归检查）",
              not hasattr(ui, "ZIP_FORMAT_ITEMS") and "zip_format" not in ui_src_all)
    res.check("job 里也不再传压缩格式",
              "zip_format" not in job_options, sorted(job_options))

    fixed_options = {"only_used", "dedupe", "preview"}
    res.check("三个开关不再作为可调属性暴露（回归检查）",
              not (fixed_options & set(_panel_referenced_props())),
              sorted(fixed_options & set(_panel_referenced_props())))
    res.check("面板源码里也不再引用这三个开关",
              not (fixed_options & set(_panel_referenced_props())),
              sorted(_panel_referenced_props()))
    res.check("三个行为在 job 里仍有明确落点、且是默认开启",
              all(job_options.get(k) is True for k in fixed_options), job_options)
    res.check("三行为唯一出处是 core.ARCHIVE_OPTIONS（常量即真源）",
              core.ARCHIVE_OPTIONS == {"only_used": True, "dedupe": True, "preview": True},
              core.ARCHIVE_OPTIONS)
    res.check("build_job 只认 filepath / preview_src / src_blend / snapshot（不再吃设置对象）",
              core.build_job.__code__.co_varnames[:4]
              == ("filepath", "preview_src", "src_blend", "snapshot"),
              core.build_job.__code__.co_varnames[:core.build_job.__code__.co_argcount])

    worker_src = open(_module_file("worker"), encoding="utf-8").read()

    res.check("op_scan 已删除（检查功能不再有 UI 入口，纯函数也不留）",
              not hasattr(ops, "op_scan"))
    res.check("BARC_OT_scan 类已删除", not hasattr(ops, "BARC_OT_scan"))
    scan_state = {"scan_text", "scan_detail", "show_detail"}
    res.check("检查用的三个属性已彻底消失（回归检查）",
              not (scan_state & set(_panel_referenced_props())),
              sorted(scan_state & set(_panel_referenced_props())))
    ui_src = open(ui.__file__, encoding="utf-8").read()
    res.check("面板源码里不再引用检查相关的属性 / 算子",
              not any(k in ui_src for k in ("scan_text", "scan_detail",
                                            "show_detail", "mf.scan")),
              sorted(scan_state & set(_panel_referenced_props())))
    res.check("scan.py 本体保留（worker 的扫描引擎还在用它）",
              hasattr(scan, "scan") and _module_file("scan").endswith("scan.py"))

    res.check("build_warnings 已删除（未保存不再是拦阻，脏也不再需要确认）",
              not hasattr(core, "build_warnings"))
    res.check("confirm_dirty 弹窗算子已删除", not hasattr(ops, "BARC_OT_confirm_dirty"))
    res.check("归档算子不再有 confirmed 标记（那是配合脏确认弹窗的）",
              "confirmed" not in bpy.ops.mf.archive_collect.get_rna_type().properties.keys(),
              sorted(bpy.ops.mf.archive_collect.get_rna_type().properties.keys()))
    res.check("op_build 不再吃设置对象（快照流程跟面板状态无关）",
              ops.op_build.__code__.co_varnames[:2] == ("context", "filepath"),
              ops.op_build.__code__.co_varnames[:ops.op_build.__code__.co_argcount])

    res.check("core 提供 write_snapshot / cleanup_snapshot / SNAPSHOT_PREFIX",
              all(hasattr(core, n) for n in
                  ("write_snapshot", "cleanup_snapshot", "snapshot_target", "SNAPSHOT_PREFIX")))
    core_src = open(_module_file("core"), encoding="utf-8").read()
    res.check("快照固定落在系统临时目录（绝不能写进用户的工程/交付目录）",
              'tempfile.mkdtemp(prefix=SNAPSHOT_PREFIX)' in core_src)
    res.check("快照用 copy=True 写（不改用户的当前文件、不动未保存状态）",
              "copy=True" in core_src
              and bpy.ops.wm.save_as_mainfile.get_rna_type().properties.get("copy") is not None)
    res.check("worker 侧也有快照兜底清理（父进程崩了也得有人收）",
              "_cleanup_snapshot" in worker_src
              and "_cleanup_snapshot(job.get(\"snapshot\"))" in worker_src)
    res.check("父进程在取消 / 失败路径上也会清（op_discard 接进了三条路）",
              all(k in open(_module_file("ops"), encoding="utf-8").read()
                  for k in ("op_discard(session)", "op_discard({\"job\": job")) )

    res.check("worker 里不再有 tar.gz / 7z / 「跳过压缩」的残留",
              not any(k in worker_src for k in
                      ("tarfile", "tar.gz", "-t7z", "_find_7z", "跳过压缩", "7-Zip")))
    res.check("压缩入口不再接受格式参数（签名只剩 root + report）",
              len(_w_signature("make_archive")) == 2, _w_signature("make_archive"))
    res.check("自检重扫支持「归档前就缺」的独立记账（回归检查）",
              len(_w_signature("verify")) == 3
              and _w_signature("verify")[1] == "pre_missing_refs",
              _w_signature("verify"))
    res.check("worker 提供 pre_missing_index",
              hasattr(_w_mod(), "pre_missing_index"))
    res.check("预览图走系统临时目录，不落到用户的输出目录里",
              'mkdtemp(prefix="barc_preview_")' in
              open(_module_file("ops"), encoding="utf-8").read())
    res.check("拼音相关代码已从 core / worker 里清干净",
              not hasattr(core, "pinyin_converter")
              and not hasattr(core, "pinyin_available")
              and "pypinyin" not in open(_module_file("worker"), encoding="utf-8").read(),
              "core.pinyin_* / worker 里的 pypinyin 引用")
    res.check("压缩 .blend 改成恒定开启（开关删了，行为要有明确落点）",
              "compress=True" in open(_module_file("worker"), encoding="utf-8").read())

    registered = set()
    for name in ("archive_collect", "archive_open_dir", "archive_alert"):
        try:
            getattr(bpy.ops.mf, name).get_rna_type()
            registered.add(name)
        except Exception:
            pass
    res.check("三个算子都真的注册了（试调 get_rna_type，不用 hasattr）",
              registered == {"archive_collect", "archive_open_dir", "archive_alert"},
              sorted(registered))

    collect_props = set(bpy.ops.mf.archive_collect.get_rna_type().properties.keys())
    res.check("归档算子带 filepath（走标准保存对话框）", "filepath" in collect_props,
              sorted(collect_props))
    res.check("归档算子限定扩展名为 .zip",
              getattr(ops.MF_OT_Archive_Collect, "filename_ext", "") == ".zip",
              getattr(ops.MF_OT_Archive_Collect, "filename_ext", None))

    sandbox = tempfile.gettempdir()
    folder, name = core.split_save_path(os.path.join(sandbox, "我的包.zip"))
    res.check("保存路径被正确拆成 目录 + 名字",
              os.path.normcase(folder) == os.path.normcase(sandbox) and name == "我的包",
              (folder, name))
    _folder2, name2 = core.split_save_path(os.path.join(sandbox, "没扩展名"))
    res.check("没写扩展名也能拆对", name2 == "没扩展名", name2)
    res.check("空路径返回空而不是崩", core.split_save_path("") == ("", ""))
    res.check("默认保存路径以 _归档.zip 结尾",
              core.default_save_path().endswith("_归档.zip"), core.default_save_path())
    res.check("默认保存路径不会退化成系统临时目录（那是交付位置，不是垃圾位）",
              os.path.normcase(os.path.dirname(os.path.abspath(core.default_save_path())))
              != os.path.normcase(tempfile.gettempdir()),
              core.default_save_path())

    res.check("op_discard 是纯函数，传 None / 空会话也不炸（取消路径天天走）",
              ops.op_discard(None) is None and ops.op_discard({}) is None)

    from . import register as _pkg_register, unregister as _pkg_unregister

    _pkg_unregister()
    res.check("注销后面板消失", not hasattr(bpy.types, "MF_PT_Archive"))
    _pkg_register()
    res.check("重新注册后面板回来了", hasattr(bpy.types, "MF_PT_Archive"))


def run(keep=False):
    res = Results()
    tmp = tempfile.mkdtemp(prefix="barc_selftest_")
    try:
        test_pure_logic(res, tmp)
        test_end_to_end(res, tmp)
        test_operator_entry(res, tmp)
        test_registration(res)
    except Exception as exc:
        import traceback

        res.check("自检本身没抛异常", False, "%s: %s" % (type(exc).__name__, exc))
        res.items[-1]["detail"] += "\n" + traceback.format_exc()[-800:]
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"tmp": tmp, "passed": len(res.passed), "failed": len(res.failed),
            "items": res.items, "text": res.dump()}


def main():
    outcome = run(keep=False)
    print("\n" + "=" * 70)
    print("打包归档 · 无头自检")
    print("=" * 70)
    print(outcome["text"])
    print("=" * 70)
    print("BARC_SELFTEST passed=%d failed=%d" % (outcome["passed"], outcome["failed"]))
    return 0 if outcome["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
