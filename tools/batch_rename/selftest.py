import os
import re
import struct
import sys
import tempfile
import shutil
import traceback
import zlib

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.basename(_HERE)
_PLUGROOT = os.path.dirname(_HERE)
if _PLUGROOT not in sys.path:
    sys.path.insert(0, _PLUGROOT)

import importlib
rename = importlib.import_module(_PKG)
naming = importlib.import_module(_PKG + ".naming")
scan = importlib.import_module(_PKG + ".scan")
disk = importlib.import_module(_PKG + ".disk")
operators = importlib.import_module(_PKG + ".operators")
ui = importlib.import_module(_PKG + ".ui")

PKG = "mf"          # 算子命名空间
SCENE_ATTR = "mf_batchrename_settings"
_TMP_DIRS = []
_IMAGES = []

class Checker(object):
    def __init__(self):
        self.total = 0
        self.failed = []

    def check(self, label, cond):
        self.total += 1
        if cond:
            print("[ok] %s" % label)
        else:
            self.failed.append(label)
            print("[FAIL] %s" % label)
        return bool(cond)

    def eq(self, label, got, want):
        return self.check("%s → 得到 %r，期望 %r" % (label, got, want), got == want)

    def report(self):
        print("")
        print("=" * 60)
        print("自检结果：%d 项，失败 %d 项" % (self.total, len(self.failed)))
        for f in self.failed:
            print("  [FAIL] %s" % f)
        print("=" * 60)
        return not self.failed

def _write_png(path, w=4, h=4, rgb=(200, 30, 30)):
    raw = b""
    for _y in range(h):
        raw += b"\x00" + bytes(rgb) * w

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = b"\x89PNG\r\n\x1a\n"
    blob += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    blob += chunk(b"IDAT", zlib.compress(raw))
    blob += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(blob)

def _drop_images():
    for img in _IMAGES:
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass
    del _IMAGES[:]

def _clear_scene():
    _drop_images()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for ma in list(bpy.data.materials):
        bpy.data.materials.remove(ma)

def _new_mesh_object(name, mat=None):
    me = bpy.data.meshes.new(name + "_mesh")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        me.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    return ob

def _node_material(name, images):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    for i, img in enumerate(images):
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.location = (i * 300, 0)
    return mat

def build_scene():
    _clear_scene()
    root = tempfile.mkdtemp(prefix="brn_selftest_")
    _TMP_DIRS.append(root)

    p_a = os.path.join(root, "tex_a.png")
    p_b = os.path.join(root, "tex_b.png")
    p_cn = os.path.join(root, "贴图_甲.png")
    _write_png(p_a, rgb=(200, 30, 30))
    _write_png(p_b, rgb=(30, 200, 30))
    _write_png(p_cn, rgb=(30, 30, 200))

    seq_dir = os.path.join(root, "seq")
    os.makedirs(seq_dir, exist_ok=True)
    for i in (1, 2, 3):
        _write_png(os.path.join(seq_dir, "wood_%04d.png" % i))

    img_a = bpy.data.images.load(p_a)
    _IMAGES.append(img_a)
    img_b = bpy.data.images.load(p_b)
    _IMAGES.append(img_b)
    img_cn = bpy.data.images.load(p_cn)
    _IMAGES.append(img_cn)

    img_dup = bpy.data.images.load(p_a)
    _IMAGES.append(img_dup)

    img_gen = bpy.data.images.new("GenTex", 4, 4)
    _IMAGES.append(img_gen)

    img_rel = bpy.data.images.new("RelTex", 4, 4)
    img_rel.source = "FILE"
    img_rel.filepath = "//sub/tex_rel.png"
    _IMAGES.append(img_rel)

    img_seq = bpy.data.images.load(os.path.join(seq_dir, "wood_0001.png"))
    _IMAGES.append(img_seq)
    img_seq.source = "SEQUENCE"
    img_seq.filepath = os.path.join(seq_dir, "wood_####.png")

    mat_a = _node_material("木头_A", [img_a, img_dup])
    mat_b = _node_material("Metal_B", [img_b, img_seq, img_cn])
    ob_a = _new_mesh_object("Beta_Box", mat_a)
    ob_b = _new_mesh_object("Alpha_Box", mat_b)

    cam = bpy.data.objects.new("MyCamera", bpy.data.cameras.new("MyCamera"))
    bpy.context.scene.collection.objects.link(cam)
    light = bpy.data.objects.new("MyLight", bpy.data.lights.new("MyLight", "POINT"))
    bpy.context.scene.collection.objects.link(light)

    for ob in list(bpy.data.objects):
        try:
            ob.select_set(False)
        except Exception:
            pass
    bpy.context.view_layer.objects.active = None

    return {"dir": root, "img_a": img_a, "img_b": img_b, "img_cn": img_cn,
            "img_dup": img_dup, "img_gen": img_gen, "img_rel": img_rel,
            "img_seq": img_seq, "mat_a": mat_a, "mat_b": mat_b,
            "ob_a": ob_a, "ob_b": ob_b, "cam": cam, "light": light,
            "seq_dir": seq_dir, "p_a": p_a}

def _run(action, **over):
    st = getattr(bpy.context.scene, SCENE_ATTR)
    snap = operators.snapshot(st)
    snap.update(over)
    plan = operators.build_plan(bpy.context, action, snap)
    rep = None
    if plan.has_work:
        rep = operators.apply_plan(bpy.context, plan, snap)
    return plan, rep

def t_naming(C):
    print("\n---- 1. 纯逻辑 naming ----")
    C.eq("split_ext('tex.png')", naming.split_ext("tex.png"), ("tex", ".png"))
    C.eq("split_ext('.png')", naming.split_ext(".png"), ("", ".png"))
    C.eq("split_ext('noext')", naming.split_ext("noext"), ("noext", ""))
    C.eq("split_ext('tex.####.png')", naming.split_ext("tex.####.png"), ("tex.####", ".png"))

    sh = naming.parse("seq_####.png", True)
    C.eq("parse 序列 head", sh.head, "seq_")
    C.eq("parse 序列 hashes", sh.hashes, "####")
    C.eq("parse 序列 ext", sh.ext, ".png")
    C.check("parse 序列判定 is_sequence", sh.is_sequence)

    C.eq("parse('Box.001', with_ext=False) ext", naming.parse("Box.001", False).ext, "")
    C.eq("parse('Box.001', with_ext=True) ext", naming.parse("Box.001", True).ext, ".001")

    C.eq("加前缀(物体)", naming.transform("Box_01", "PREFIX", "MF_", False), "MF_Box_01")
    C.eq("加后缀(物体)", naming.transform("Box_01", "SUFFIX", "_v2", False), "Box_01_v2")
    C.eq("加前缀(贴图保留扩展名)",
         naming.transform("tex_a.png", "PREFIX", "MF_", True), "MF_tex_a.png")
    C.eq("加后缀(贴图)",
         naming.transform("tex_a.png", "SUFFIX", "_v2", True), "tex_a_v2.png")

    C.eq("清除前缀·字段匹配", naming.transform("MF_tex", "STRIP_PREFIX", "MF_", False), "tex")
    C.eq("清除前缀·分隔符兜底",
         naming.transform("tex_a", "STRIP_PREFIX", "MF_", False), "a")
    C.eq("清除后缀·字段匹配", naming.transform("texMF_", "STRIP_SUFFIX", "MF_", False), "tex")
    C.eq("清除后缀·分隔符兜底", naming.transform("tex_a", "STRIP_SUFFIX", "MF_", False), "tex")
    C.eq("清除前缀·没有分隔符时不动",
         naming.transform("noext", "STRIP_PREFIX", "MF_", False), None)
    C.eq("清除前缀·字段为空也能兜底",
         naming.transform("tex_a", "STRIP_PREFIX", "", False), "a")
    C.eq("清除前缀·分隔符在开头", naming.transform("_lead", "STRIP_PREFIX", "", False), "lead")
    C.eq("清除后为空则不动", naming.transform("_", "STRIP_PREFIX", "", False), None)

    C.eq("强制重命名(物体)", naming.transform("Box_01", "RENAME", "kw", False, 7), "kw0007")
    C.eq("强制重命名(贴图)", naming.transform("tex_a.png", "RENAME", "kw", True, 2), "kw0002.png")
    C.eq("强制重命名(序列)",
         naming.transform("wood_####.png", "RENAME", "kw", True, 5), "kw0005_####.png")

    C.eq("关键字为空则不动", naming.transform("Box", "PREFIX", "", False), None)
    C.eq("pad(1)", naming.pad(1), "0001")
    C.eq("pad(12345)", naming.pad(12345), "12345")

    safe, changed = naming.sanitize_keyword('v1:*.')
    C.eq("关键字净化", safe, "v1__")
    C.check("关键字净化标记 changed", changed)
    C.eq("净化未变时 changed=False", naming.sanitize_keyword("MF_")[1], False)
    C.eq("净化保留名 CON", naming.sanitize_filename("CON.txt"), "_CON.txt")
    C.eq("净化非法字符", naming.sanitize_filename("a:b?c.png"), "a_b_c.png")
    C.eq("净化结尾点空格", naming.sanitize_filename("tex. "), "tex")
    C.eq("净化空白", naming.sanitize_filename("   "), "")
    C.eq("净化序列名不动井号", naming.sanitize_filename("MF_seq_####.png"), "MF_seq_####.png")

    C.eq("帧名替换保留 4 位宽",
         naming.sequence_frame_name("kw0001_####.png", "0001"), "kw0001_0001.png")
    C.eq("帧名替换不重算宽度",
         naming.sequence_frame_name("kw0001_####.png", "1"), "kw0001_1.png")

def t_disk(C):
    print("\n---- 2. 磁盘引擎 disk ----")
    root = tempfile.mkdtemp(prefix="brn_disk_")
    _TMP_DIRS.append(root)

    def w(name, text):
        p = os.path.join(root, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    a, b = w("a.txt", "AAA"), w("b.txt", "BBB")
    units = [disk.make_file_unit(None, a, b), disk.make_file_unit(None, b, os.path.join(root, "c.txt"))]
    moves, errs = disk.plan(units)
    C.eq("链式改名允许通过（protected 生效）", len(moves), 2)
    C.eq("链式改名无错误", errs, [])
    n, e2 = disk.run_moves(moves)
    C.eq("链式改名移动数", n, 2)
    C.eq("链式改名无错误2", e2, [])
    with open(b, encoding="utf-8") as fh:
        C.eq("b.txt 内容 = 原 a", fh.read(), "AAA")
    with open(os.path.join(root, "c.txt"), encoding="utf-8") as fh:
        C.eq("c.txt 内容 = 原 b", fh.read(), "BBB")

    x = w("x.txt", "X")
    w("MF_x.txt", "OLD")
    units = [disk.make_file_unit(None, x, os.path.join(root, "MF_x.txt"))]
    moves, errs = disk.plan(units)
    C.eq("撞名时产生避让", len(moves), 1)
    C.eq("避让后的目标名", os.path.basename(moves[0][1]), "MF_x_1.txt")
    C.eq("避让仍在同一目录", os.path.dirname(moves[0][1]), root)

    ghost = os.path.join(root, "ghost.txt")
    units = [disk.make_file_unit(None, ghost, os.path.join(root, "zz.txt"))]
    moves, _e = disk.plan(units)
    n, errs = disk.run_moves(moves)
    C.eq("源不存在时移动数 0", n, 0)
    C.check("源不存在时给出错误", bool(errs))
    C.eq("失败后无临时残片", [f for f in os.listdir(root) if disk.TMP_TAG in f], [])

    C.eq("序列名避让保留井号",
         os.path.basename(disk._insert_suffix(os.path.join(root, "s_####.png"), "_1")),
         "s_####_1.png")

def t_scan(C, sc):
    print("\n---- 3. 采集 scan ----")
    C.eq("相机类型", sc["cam"].type, "CAMERA")
    C.eq("灯光类型", sc["light"].type, "LIGHT")
    C.check("重复引用的图指向同一文件",
            disk._norm(sc["img_a"].filepath) == disk._norm(sc["img_dup"].filepath))

    entries, notes = scan.collect(bpy.context, {
        "scope": scan.SCOPE_ALL, "do_object": True, "do_material": True,
        "do_image": True, "skip_cameras": False, "skip_lights": False})
    kinds = {}
    for e in entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    C.eq("全场景物体数", kinds.get("object"), 4)
    C.eq("全场景材质数", kinds.get("material"), 2)
    C.eq("全场景贴图数（已剔除 2 张内置预览图）", kinds.get("image"), 7)
    C.eq("bpy.data.images 总数（守卫：素材确实造了 9 张）", len(bpy.data.images), 9)

    reasons = {}
    for e in entries:
        if e.skip:
            reasons.setdefault(e.skip, []).append(e.label)
        elif e.skip_disk:
            reasons.setdefault(e.skip_disk, []).append(e.label)
    C.check("内置预览图不产生任何 Entry",
            all(e.id.name not in ("Render Result", "Viewer Node") for e in entries))
    C.check("内置预览图不占 notes",
            not any("内置预览图" in n for n in notes))
    C.check("程序生成图磁盘被跳过", scan.R_GENERATED in reasons)
    C.check("未存盘的 // 路径被挡住", scan.R_UNSAVED in reasons)

    seq_entries = [e for e in entries if e.seq_frames]
    C.eq("识别出 1 个序列图", len(seq_entries), 1)
    C.eq("序列帧数", len(seq_entries[0].seq_frames), 3)
    C.eq("序列帧号原始串保留",
         sorted(d for _n, _p, d in seq_entries[0].seq_frames), ["0001", "0002", "0003"])

    sc["ob_a"].select_set(True)
    bpy.context.view_layer.objects.active = sc["ob_a"]
    sel_entries, _n = scan.collect(bpy.context, {
        "scope": scan.SCOPE_SELECTED, "do_object": True, "do_material": True,
        "do_image": True, "skip_cameras": False, "skip_lights": False})
    sel_kinds = {}
    for e in sel_entries:
        sel_kinds[e.kind] = sel_kinds.get(e.kind, 0) + 1
    C.eq("仅选中：物体数", sel_kinds.get("object"), 1)
    C.eq("仅选中：材质数", sel_kinds.get("material"), 1)
    C.check("仅选中：贴图 >= 2", sel_kinds.get("image", 0) >= 2)
    C.check("仅选中不含未选中的物体",
            all(e.id is not sc["ob_b"] for e in sel_entries))

    ex_entries, ex_notes = scan.collect(bpy.context, {
        "scope": scan.SCOPE_ALL, "do_object": True, "do_material": False,
        "do_image": False, "skip_cameras": True, "skip_lights": True})
    names = [e.id.name for e in ex_entries]
    C.check("排除开关生效：相机不在列表", "MyCamera" not in names)
    C.check("排除开关生效：灯光不在列表", "MyLight" not in names)
    C.eq("排除后只剩 2 个网格物体", len(ex_entries), 2)

    C.check("排除项触发时 notes 有提示", any("跳过" in n for n in ex_notes))
    C.check("notes 里不含范围过程统计",
            not any("范围=" in n for n in ex_notes))

    orig = scan._lib_ok
    try:
        scan._lib_ok = lambda _idb: False
        ro_entries, _n = scan.collect(bpy.context, {
            "scope": scan.SCOPE_ALL, "do_object": True, "do_material": True,
            "do_image": True, "skip_cameras": False, "skip_lights": False})
    finally:
        scan._lib_ok = orig
    C.check("只读分支：全部不可写",
            bool(ro_entries) and all(not e.writable for e in ro_entries))
    C.check("只读分支：原因一律是链接库",
            bool(ro_entries) and all(e.skip == scan.R_LINKED for e in ro_entries))
    C.check("只读分支：至少有一条走的是链接库原因",
            any(e.skip == scan.R_LINKED for e in ro_entries))

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None

def t_engine(C, sc):
    print("\n---- 4. 引擎 operators ----")

    st = getattr(bpy.context.scene, SCENE_ATTR)
    st.keyword = "MF_"

    plan, rep = _run("PREFIX", scope=scan.SCOPE_ALL,
                     do_object=True, do_material=True, do_image=True,
                     rename_disk=True)
    C.check("加前缀：有计划", plan.has_work)
    C.eq("加前缀：物体 Beta", sc["ob_a"].name, "MF_Beta_Box")
    C.eq("加前缀：物体 Alpha", sc["ob_b"].name, "MF_Alpha_Box")
    C.eq("加前缀：相机", sc["cam"].name, "MF_MyCamera")
    C.eq("加前缀：灯光", sc["light"].name, "MF_MyLight")
    C.eq("加前缀：材质", sc["mat_a"].name, "MF_木头_A")
    C.eq("加前缀：贴图数据块名", sc["img_a"].name, "MF_tex_a.png")
    C.eq("加前缀：重复引用的贴图也改名", sc["img_dup"].name, "MF_tex_a.png.001")
    C.check("加前缀：磁盘文件真的没了旧名", not os.path.exists(sc["p_a"]))
    C.check("加前缀：磁盘出现新名",
            os.path.exists(os.path.join(sc["dir"], "MF_tex_a.png")))
    C.check("加前缀：filepath 已回写且指得到文件",
            os.path.exists(bpy.path.abspath(sc["img_a"].filepath)))
    C.eq("加前缀：filepath 指向新名",
            os.path.basename(bpy.path.abspath(sc["img_a"].filepath)), "MF_tex_a.png")
    C.check("加前缀：重复引用的兄弟也回写成功",
            os.path.exists(bpy.path.abspath(sc["img_dup"].filepath)))
    C.eq("加前缀：同文件只挪一次", plan.dupe_files, 1)
    C.eq("加前缀：贴图计数", rep["counts"].get("image"), 7)
    C.check("加前缀：生成图磁盘被跳过并报出原因",
            any(r == scan.R_GENERATED for r, _ in plan.disk_skips))
    C.check("加前缀：撞名报告里也有磁盘跳过项",
            any(r == scan.R_UNSAVED for r, _ in plan.disk_skips))
    C.check("加前缀：序列图数据块改名",
            sc["img_seq"].name.startswith("MF_wood_"))
    C.check("加前缀：序列帧文件改名",
            os.path.exists(os.path.join(sc["seq_dir"], "MF_wood_0001.png")))
    C.check("加前缀：序列井号形态保留", "#" in sc["img_seq"].filepath)
    C.check("加前缀：序列 filepath 仍解析得到",
            os.path.exists(bpy.path.abspath(sc["img_seq"].filepath).replace("####", "0002")))

    plan, rep = _run("STRIP_PREFIX", scope=scan.SCOPE_ALL,
                     do_object=True, do_material=True, do_image=True,
                     rename_disk=True)
    C.check("清除前缀：有计划", plan.has_work)
    C.eq("清除前缀：物体回到原名", sc["ob_a"].name, "Beta_Box")
    C.eq("清除前缀：材质回到原名", sc["mat_a"].name, "木头_A")
    C.eq("清除前缀：贴图回到原名", sc["img_a"].name, "tex_a.png")
    C.check("清除前缀：磁盘也回滚", os.path.exists(sc["p_a"]))
    C.check("清除前缀：序列帧回滚",
            os.path.exists(os.path.join(sc["seq_dir"], "wood_0001.png")))

    st.keyword = "_v2"
    plan, _rep = _run("SUFFIX", scope=scan.SCOPE_ALL,
                      do_object=True, do_material=False, do_image=False,
                      rename_disk=False)
    C.eq("加后缀：物体", sc["ob_a"].name, "Beta_Box_v2")
    plan, _rep = _run("STRIP_SUFFIX", scope=scan.SCOPE_ALL,
                      do_object=True, do_material=False, do_image=False,
                      rename_disk=False)
    C.eq("清除后缀：物体回原名", sc["ob_a"].name, "Beta_Box")

    st.keyword = "SKIP_"
    plan, _rep = _run("PREFIX", scope=scan.SCOPE_ALL, do_object=True,
                      do_material=False, do_image=False, rename_disk=False,
                      skip_cameras=True, skip_lights=True)
    C.eq("排除相机后名字未变", sc["cam"].name, "MyCamera")
    C.eq("排除灯光后名字未变", sc["light"].name, "MyLight")
    C.eq("排除后物体照常改名", sc["ob_a"].name, "SKIP_Beta_Box")
    _run("STRIP_PREFIX", scope=scan.SCOPE_ALL, do_object=True,
         do_material=False, do_image=False, rename_disk=False)
    C.eq("回滚回 Beta_Box", sc["ob_a"].name, "Beta_Box")

    st.keyword = "MF"
    plan, rep = _run("RENAME", scope=scan.SCOPE_ALL, do_object=True,
                     do_material=True, do_image=True, rename_disk=True)
    C.check("强制重命名：有计划", plan.has_work)
    C.eq("强制重命名：物体 0001", sc["ob_b"].name, "MF0001")
    C.eq("强制重命名：物体 0002", sc["ob_a"].name, "MF0002")
    C.eq("强制重命名：相机 0003", sc["cam"].name, "MF0003")
    C.eq("强制重命名：灯光 0004", sc["light"].name, "MF0004")
    C.check("强制重命名：材质带序号", re.match(r"^MF\d{4}$", sc["mat_b"].name) is not None)
    C.check("强制重命名：贴图保留扩展名",
            re.match(r"^MF\d{4}\.png$", sc["img_a"].name) is not None)
    C.check("强制重命名：磁盘文件名同步",
            os.path.exists(os.path.join(sc["dir"], sc["img_a"].name)))
    C.check("强制重命名：序列名是 关键字+序号_",
            re.match(r"^MF\d{4}_####\.png$", sc["img_seq"].name) is not None)
    frames = sorted(f for f in os.listdir(sc["seq_dir"]) if f.endswith(".png"))
    C.eq("强制重命名：序列 3 帧都在", len(frames), 3)
    C.check("强制重命名：序列帧名带 4 位帧号",
            re.match(r"^MF\d{4}_0001\.png$", frames[0]) is not None)

def t_engine_edges(C):
    print("\n---- 4b. 边界与范围 ----")

    sc = build_scene()
    st = getattr(bpy.context.scene, SCENE_ATTR)
    st.keyword = ""

    plan, _rep = _run("PREFIX", scope=scan.SCOPE_ALL)
    C.check("空关键字 → 不执行且给原因", (not plan.has_work) and bool(plan.error))

    st.keyword = "X_"
    plan, _rep = _run("PREFIX", scope=scan.SCOPE_ALL, do_object=False,
                      do_material=False, do_image=False)
    C.check("一个类别都没勾 → 不执行且给原因", (not plan.has_work) and bool(plan.error))

    plan, _rep = _run("PREFIX", scope=scan.SCOPE_SELECTED, do_object=True,
                      do_material=True, do_image=True, rename_disk=True)
    C.check("范围=仅选中但没选中 → 不执行且给原因",
            (not plan.has_work) and ("没有" in plan.error))

    st.keyword = "SEL_"
    sc["ob_a"].select_set(True)
    bpy.context.view_layer.objects.active = sc["ob_a"]
    plan, rep = _run("PREFIX", scope=scan.SCOPE_SELECTED, do_object=True,
                     do_material=False, do_image=False, rename_disk=False)
    C.eq("仅选中：选中的改了", sc["ob_a"].name, "SEL_Beta_Box")
    C.eq("仅选中：没选的没动", sc["ob_b"].name, "Alpha_Box")
    C.eq("仅选中：计数为 1", rep["counts"].get("object"), 1)

    _clear_scene()
    _new_mesh_object("PlainName")
    plan, _rep = _run("STRIP_PREFIX", scope=scan.SCOPE_ALL, do_object=True,
                      do_material=False, do_image=False, rename_disk=False)
    C.eq("无分隔符的名字 → 无需改动计数", plan.nochange, 1)
    C.check("无需改动时不算有计划", not plan.has_work)

    sc = build_scene()
    st.keyword = "MF_"
    occupy = os.path.join(sc["dir"], "MF_tex_a.png")
    with open(occupy, "wb") as fh:
        fh.write(b"occupied")
    plan, rep = _run("PREFIX", scope=scan.SCOPE_ALL, do_object=False,
                     do_material=False, do_image=True, rename_disk=True)
    C.check("撞名：仍产生磁盘动作", bool(plan.units))
    C.check("撞名：旧文件已让位", not os.path.exists(sc["p_a"]))
    C.check("撞名：避让名存在",
            os.path.exists(os.path.join(sc["dir"], "MF_tex_a_1.png")))
    C.check("撞名：filepath 指到避让名",
            os.path.basename(bpy.path.abspath(sc["img_a"].filepath)) == "MF_tex_a_1.png")
    with open(occupy, "rb") as fh:
        C.eq("撞名：已存在的同名文件没被覆盖", fh.read(), b"occupied")

    sc = build_scene()
    before = sorted(os.listdir(sc["dir"]))
    plan, rep = _run("PREFIX", scope=scan.SCOPE_ALL, do_object=True,
                     do_material=False, do_image=True, rename_disk=False)
    C.eq("关掉磁盘改名：无磁盘单元", len(plan.units), 0)
    C.eq("关掉磁盘改名：磁盘文件数不变", sorted(os.listdir(sc["dir"])), before)
    C.eq("关掉磁盘改名：数据块名照样改", sc["img_a"].name, "MF_tex_a.png")

def t_operator(C):
    print("\n---- 5. 算子入口 ----")
    sc = build_scene()
    st = getattr(bpy.context.scene, SCENE_ATTR)

    st.scope = scan.SCOPE_ALL
    st.do_object = True
    st.do_material = False
    st.do_image = False
    st.rename_disk = False
    st.keyword = "OP_"

    res = bpy.ops.mf.batch_rename_apply(action="RENAME")
    C.check("batch_rename_apply 返回 FINISHED", "FINISHED" in res)
    C.check("算子确实改了名", sc["ob_b"].name.startswith("OP_"))
    C.check("算子写了面板报告字段", bool(st.last_report))
    C.check("报告里有人话计数", "完成" in st.last_report)

    st.keyword = ""
    try:
        res = bpy.ops.mf.batch_rename_apply(action="PREFIX")
        cancelled = "CANCELLED" in res
    except RuntimeError:
        cancelled = True
    C.check("空关键字时算子取消而不是闷头执行", cancelled)
    C.check("空关键字时面板给出原因", bool(st.last_report))
    C.check("取消时报告区写的是原因，不是旧报告",
            "完成" not in st.last_report)

    registered = _registered_ops()
    for name in ("batch_rename_apply", "batch_rename_clear_keyword"):
        C.check("算子已注册：%s" % name, name in registered)
    for gone in ("rn_toggle_options", "rn_show_report"):
        C.check("旧弹窗算子已移除：%s" % gone, gone not in registered)

def _registered_ops():
    out = set()
    mod = getattr(bpy.ops, PKG, None)
    if mod is None:
        return out
    for name in dir(mod):
        if name.startswith("_"):
            continue
        try:
            getattr(mod, name).get_rna_type()
            out.add(name)
        except Exception:
            pass
    return out

class FakeLog(object):
    def __init__(self):
        self.props = []
        self.ops = []
        self.icons = []
        self.prop_kwargs = set()
        self.op_kwargs = set()
        self.labels = []

class FakeOpProps(object):
    def __init__(self):
        self.action = None

class FakeLayout(object):

    def __init__(self, log=None):
        self.log = log if log is not None else FakeLog()
        self.alignment = "EXPAND"

    def _child(self):
        return FakeLayout(self.log)

    def row(self, align=False):
        return self._child()

    def column(self, align=False):
        return self._child()

    def box(self):
        return self._child()

    def split(self, **kw):
        return self._child()

    def separator(self, **kw):
        pass

    def label(self, text="", **kw):
        self.log.labels.append(text)
        if kw.get("icon"):
            self.log.icons.append(kw["icon"])

    def prop(self, data, name=None, **kw):
        self.log.props.append((data, name))
        self.log.prop_kwargs.update(kw.keys())
        if kw.get("icon"):
            self.log.icons.append(kw["icon"])

    def operator(self, idname, **kw):
        self.log.ops.append(idname)
        self.log.op_kwargs.update(kw.keys())
        if kw.get("icon"):
            self.log.icons.append(kw["icon"])
        return FakeOpProps()

class FakePanel(object):
    def __init__(self, layout, owner):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        raw = self._owner.__dict__.get(name, None)
        if isinstance(raw, staticmethod):
            return raw.__func__
        return getattr(self._owner, name).__get__(self, type(self))

def _layout_params(fn_name):
    fn = bpy.types.UILayout.bl_rna.functions.get(fn_name)
    if fn is None:
        return set()
    return set(fn.parameters.keys())

def _icon_set():
    return {i.identifier for i in
            bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}

def t_ui(C):
    print("\n---- 6. UI 静态体检 ----")
    C.check("面板按 bl_idname 注册", hasattr(bpy.types, ui.PANEL_ID))
    C.eq("面板分类", ui.MF_PT_BatchRename.bl_category, operators.utils.PANEL_CATEGORY)
    C.eq("面板空间", ui.MF_PT_BatchRename.bl_space_type, "VIEW_3D")
    C.eq("面板区域", ui.MF_PT_BatchRename.bl_region_type, "UI")
    C.check("面板继承 MF_ToolPanel",
            issubclass(ui.MF_PT_BatchRename, operators.utils.MF_ToolPanel))
    C.check("面板默认折叠 DEFAULT_CLOSED",
            "DEFAULT_CLOSED" in ui.MF_PT_BatchRename.bl_options)
    C.check("面板有搜索别名 MF_SEARCH_KEYWORDS",
            bool(getattr(ui.MF_PT_BatchRename, "MF_SEARCH_KEYWORDS", ())))
    C.check("面板标题有图标 draw_header",
            "draw_header" in ui.MF_PT_BatchRename.__dict__)
    C.check("面板排序 bl_order 已设置",
            getattr(ui.MF_PT_BatchRename, "bl_order", None) is not None)

    log = FakeLog()
    ui.MF_PT_BatchRename.draw(FakePanel(FakeLayout(log), ui.MF_PT_BatchRename), bpy.context)
    C.check("draw() 跑通且画出了控件", bool(log.props) and bool(log.ops))

    rna = set(operators.MF_PG_BatchRenameSettings.bl_rna.properties.keys())
    missing = sorted({n for _d, n in log.props if n and n not in rna})
    C.eq("面板引用的属性名全部存在", missing, [])

    registered = _registered_ops()
    bad_ops = sorted({o for o in log.ops
                      if o.startswith(PKG + ".") and o.split(".", 1)[1] not in registered})
    C.eq("面板引用的算子全部已注册", bad_ops, [])

    icons = _icon_set()
    C.eq("面板用到的图标全部存在", sorted({i for i in log.icons if i not in icons}), [])
    C.check("确实用到了图标（守卫本身不是空跑）", bool(log.icons))

    C.eq("prop() 只用了合法参数",
         sorted(k for k in log.prop_kwargs if k not in _layout_params("prop")), [])
    C.eq("operator() 只用了合法参数",
         sorted(k for k in log.op_kwargs if k not in _layout_params("operator")), [])
    C.check("prop 确实带过关键字参数（守卫非空跑）", bool(log.prop_kwargs))

    names = {n for _d, n in log.props}
    for want in ("do_object", "do_material", "do_image",
                 "skip_cameras", "skip_lights", "rename_disk",
                 "keyword", "scope"):
        C.check("常驻画出 %s" % want, want in names)

    C.eq("面板按钮数量", len(log.ops), 6)

    C.check("参数组里没有 options_open",
            "options_open" not in operators.MF_PG_BatchRenameSettings.bl_rna.properties)
    C.check("面板不再画「折叠选项」标题", "折叠选项" not in log.labels)

    C.check("参数组里没有 unify_keyword",
            "unify_keyword" not in operators.MF_PG_BatchRenameSettings.bl_rna.properties)
    C.check("动作表里没有 UNIFY", "UNIFY" not in operators.ACTION_KEYS)
    C.check("面板不再画「统一命名」按钮",
            not any("统一命名" in l for l in log.labels))

    C.check("operators 里没有 preview_hint",
            not hasattr(operators, "preview_hint"))
    C.check("面板不再画「预估」", not any("预估" in l for l in log.labels))

def t_no_dialog(C):
    print("\n---- 6b. 无弹窗守卫 ----")

    for cls in operators.classes:
        if not getattr(cls, "bl_idname", ""):
            continue
        C.check("%s 没有定义 invoke()" % cls.bl_idname.split(".")[-1],
                "invoke" not in cls.__dict__)
        C.check("%s 有 bl_description（悬停说明）" % cls.bl_idname.split(".")[-1],
                bool(getattr(cls, "bl_description", "")))

    for fn_name in ("naming.py", "scan.py", "disk.py", "operators.py", "ui.py"):
        with open(os.path.join(_HERE, fn_name), encoding="utf-8") as fh:
            code = _strip_comments(fh.read())
        C.check("%s 里没有 invoke_props_dialog" % fn_name,
                "invoke_props_dialog" not in code)
        C.check("%s 里没有 invoke_popup" % fn_name,
                "invoke_popup" not in code)

def _strip_comments(src):
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    return "\n".join(ln.split("#")[0] for ln in src.splitlines())

def t_static(C):
    print("\n---- 7. 源码静态体检 ----")
    src = {}
    for fn_name in ("naming.py", "scan.py", "disk.py", "operators.py", "ui.py"):
        with open(os.path.join(_HERE, fn_name), encoding="utf-8") as fh:
            src[fn_name] = fh.read()
    code = {k: _strip_comments(v) for k, v in src.items()}
    all_src = "\n".join(src.values())

    probe = 'x = 1  # import bpy\n"""说明：本模块不 import bpy"""\n'
    C.check("守卫自证：注释与文档串里的 import bpy 不算数",
            "import bpy" not in _strip_comments(probe))

    C.check("源码里没有 template_list", "template_list" not in all_src)
    C.check("假布局刻意不提供 template_list",
            "template_list" not in FakeLayout.__dict__)

    C.check("没有 modal_timer_register 这个假 API",
            "modal_timer_register" not in all_src)
    wm_funcs = set(bpy.types.WindowManager.bl_rna.functions.keys())
    called = set(re.findall(r"(?<!ops\.)\b(?:window_manager|wm)\.([A-Za-z_]\w*)\s*\(", all_src))
    C.eq("window_manager 上的方法名全部真实存在",
         sorted(n for n in called if n not in wm_funcs), [])
    C.eq("整个包不再调用任何 window_manager 方法", sorted(called), [])

    C.check("naming.py 不 import bpy", "import bpy" not in code["naming.py"])
    C.check("disk.py 不 import bpy", "import bpy" not in code["disk.py"])
    C.check("逻辑与算子分离：引擎函数是模块级的",
            "def apply_plan(" in src["operators.py"] and "def build_plan(" in src["operators.py"])
    C.check("算子 idname 前缀统一 mf.",
            operators.OP_APPLY_ID.startswith("mf.") and operators.OP_CLEAR_ID.startswith("mf."))

    align_enum = {i.identifier for i in
                  bpy.types.UILayout.bl_rna.properties["alignment"].enum_items}
    used_align = set(re.findall(r'\.alignment\s*=\s*"([A-Z_]+)"', all_src))
    C.eq("ui 里用到的 alignment 值全部合法", sorted(used_align - align_enum), [])

    opt_enum = {i.identifier for i in
                bpy.types.Operator.bl_rna.properties["bl_options"].enum_items}
    used_opts = set()
    for cls in operators.classes:
        used_opts |= set(getattr(cls, "bl_options", ()))
    C.eq("算子 bl_options 全部合法", sorted(used_opts - opt_enum), [])
    C.check("确实设置了 bl_options（守卫非空跑）", bool(used_opts))

    C.eq("动作枚举项与 ACTION_KEYS 一致",
         {k for k, _l, _d in operators.ACTION_ITEMS}, set(operators.ACTION_KEYS))
    C.eq("operators.ACTION_KEYS 就是 naming.ACTION_KEYS",
         operators.ACTION_KEYS, naming.ACTION_KEYS)
    C.eq("动作枚举项的键就是 naming 的常量",
         {k for k, _l, _d in operators.ACTION_ITEMS},
         {naming.A_PREFIX, naming.A_SUFFIX, naming.A_STRIP_PREFIX,
          naming.A_STRIP_SUFFIX, naming.A_RENAME})
    for act in naming.ACTION_KEYS:
        got = naming.transform("Box_01", act, "X_", False, 1)
        C.check("transform() 认得动作 %s" % act, got is not None)
    try:
        naming.transform("Box", "NO_SUCH_ACTION", "X_", False, 1)
        unknown_raised = False
    except ValueError:
        unknown_raised = True
    C.check("transform() 遇到未知动作抛 ValueError（守卫非空跑）", unknown_raised)

def run():
    C = Checker()
    print("Blender %s / 包 %s" % (bpy.app.version_string, _PKG))
    rename.register()

    sc = build_scene()
    t_naming(C)
    t_disk(C)
    t_scan(C, sc)
    t_engine(C, sc)
    t_engine_edges(C)
    t_operator(C)
    t_ui(C)
    t_no_dialog(C)
    t_static(C)

    print("\n---- 8. 注销 ----")
    rename.unregister()
    C.check("注销后 scene 上没有 %s" % SCENE_ATTR,
            not hasattr(bpy.context.scene, SCENE_ATTR))
    C.check("注销后面板类已移除", not hasattr(bpy.types, ui.PANEL_ID))
    C.check("注销后算子已移除", "batch_rename_apply" not in _registered_ops())
    rename.register()
    C.check("可以重新注册回来", hasattr(bpy.context.scene, SCENE_ATTR))

    return C.report()

def _cleanup():
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    del _TMP_DIRS[:]

def main():
    try:
        ok = run()
    except Exception:
        traceback.print_exc()
        ok = False
    finally:
        _cleanup()
    return ok

if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
