import os
import sys
import math
import random
import importlib

import bpy
import addon_utils
from mathutils import Vector, Matrix

# ---------------------------------------------------------------- 装载
IN_TOOLBOX = importlib.util.find_spec("mufeng_blender_tools") is not None

if IN_TOOLBOX:
    if "mufeng_blender_tools" in sys.modules:
        try:
            bpy.ops.preferences.addon_disable(module='mufeng_blender_tools')
        except Exception:
            pass
        for k in [k for k in sys.modules if k.startswith('mufeng_blender_tools')]:
            del sys.modules[k]
    bpy.ops.preferences.addon_enable(module='mufeng_blender_tools')
    PKG = "mufeng_blender_tools.tools.book_shelf"
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    PARENT = os.path.dirname(HERE)
    if PARENT not in sys.path:
        sys.path.insert(0, PARENT)
    for k in [k for k in sys.modules if k == "book_shelf"
              or k.startswith("book_shelf.")]:
        del sys.modules[k]
    PKG = "book_shelf"
    addon_utils.enable(PKG, default_set=True, persistent=False)

try:
    importlib.import_module(PKG)
except Exception as exc:  # noqa
    print("=" * 60)
    print("无法导入 %s：%r" % (PKG, exc))
    print("请先把 book_shelf 文件夹复制到 mufeng_blender_tools/tools/ 下再运行。")
    print("=" * 60)
    sys.exit(1)

PASS = 0
FAIL = 0
LINES = []


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        LINES.append("PASS  %s%s" % (name, ("  -- " + str(extra)) if extra else ""))
    else:
        FAIL += 1
        LINES.append("FAIL  %s%s" % (name, ("  -- " + str(extra)) if extra else ""))


def near(a, b, tol=1e-4):
    return abs(a - b) <= tol


gm = sys.modules[PKG + ".geometry"]
rowm = sys.modules[PKG + ".row_fill"]
shelfm = sys.modules[PKG + ".shelf_layout"]
opsm = sys.modules[PKG + ".operators"]
uim = sys.modules[PKG + ".ui"]
propsm = sys.modules[PKG + ".props"]

CTX = bpy.context
S = CTX.scene.book_shelf

_OPS_NS = opsm.classes[0].bl_idname.split(".")[0]
OPS = getattr(bpy.ops, _OPS_NS)

OPS_SHORT = ("bookshelf_add_selected", "bookshelf_remove_selected",
             "bookshelf_clear_books", "bookshelf_pick_faces",
             "bookshelf_create_shelf", "bookshelf_delete_rows",
             "bookshelf_new_seed")


def op_registered(short):
    try:
        getattr(OPS, short).get_rna_type()
        return True
    except Exception:
        return False


for short in OPS_SHORT:
    check("算子已注册 mf.%s" % short, op_registered(short))

check("算子 bl_idname 全部以 mf.bookshelf_ 开头",
      all(c.bl_idname.startswith("mf.bookshelf_") for c in opsm.classes))
check("算子类名全部 MF_OT_ 前缀",
      all(c.__name__.startswith("MF_OT_") for c in opsm.classes))

PANEL_MAIN = "MF_PT_BookShelf"
PANELS = (PANEL_MAIN,
          "MF_PT_BookShelf_Books", "MF_PT_BookShelf_Props",
          "MF_PT_BookShelf_Standing", "MF_PT_BookShelf_Leaning",
          "MF_PT_BookShelf_Stacks", "MF_PT_BookShelf_Shelf",
          "MF_PT_BookShelf_Edit")

for pid in PANELS:
    check("面板已注册 %s" % pid, hasattr(bpy.types, pid))

check("面板类名全部 MF_PT_ 前缀",
      all(p.startswith("MF_PT_") for p in PANELS))
check("所有面板分类是「木风工具箱」",
      all(getattr(bpy.types, p).bl_category == "木风工具箱" for p in PANELS))
_orders = [getattr(bpy.types, p).bl_order for p in PANELS]
check("主面板 bl_order 已由挂载层按文件夹字母序自动分配（>=0 的整数）",
      isinstance(_orders[0], int) and _orders[0] >= 0, _orders)
check("子面板 bl_order 从 1 起连续编号",
      _orders[1:] == list(range(1, len(PANELS))), _orders[1:])
_bad_parent = [p for p in PANELS[1:]
               if getattr(bpy.types, p).bl_parent_id != PANEL_MAIN]
check("7 个分区全部挂在一键摆书主面板下（bl_parent_id）",
      len(PANELS) == 8 and not _bad_parent, _bad_parent)
check("只有主面板和带开关的分区写 draw_header（主面板图标，③④⑤放勾选框）",
      [p for p in PANELS
       if ("draw_header" in getattr(bpy.types, p).__dict__)
       != (p in ("MF_PT_BookShelf", "MF_PT_BookShelf_Standing",
                 "MF_PT_BookShelf_Leaning", "MF_PT_BookShelf_Stacks"))] == [],
      [p for p in PANELS if "draw_header" in getattr(bpy.types, p).__dict__])
check("所有面板都写了自己的搜索关键词",
      all(getattr(getattr(bpy.types, p), "MF_SEARCH_KEYWORDS", ()) for p in PANELS))

rna = set(propsm.MF_BookShelf_Settings.bl_rna.properties.keys())
icons = {i.identifier for i in
         bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}


class _Dummy:
    def __call__(self, *a, **k):
        return _Dummy()

    def __getattr__(self, _n):
        return _Dummy()


class FakeLayout:
    def __init__(self, log=None):
        self.log = log if log is not None else []

    def _sub(self, kind, *a, **k):
        self.log.append((kind, a, k))
        return FakeLayout(self.log)

    def row(self, *a, **k):
        return self._sub("row", *a, **k)

    def column(self, *a, **k):
        return self._sub("column", *a, **k)

    def box(self, *a, **k):
        return self._sub("box", *a, **k)

    def split(self, *a, **k):
        return self._sub("split", *a, **k)

    def label(self, *a, **k):
        return self._sub("label", *a, **k)

    def prop(self, *a, **k):
        return self._sub("prop", *a, **k)

    def operator(self, *a, **k):
        return self._sub("operator", *a, **k)

    def separator(self, *a, **k):
        return self._sub("separator", *a, **k)

    def template_list(self, *a, **k):
        return self._sub("template_list", *a, **k)

    def __getattr__(self, _n):
        return _Dummy()


class FakePanel:
    def __init__(self, layout, owner):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        raw = self._owner.__dict__.get(name)
        if isinstance(raw, staticmethod):
            return raw.__func__
        return getattr(self._owner, name).__get__(self, type(self))


all_ops = []
panel_logs = {}
for pname in PANELS:
    cls = getattr(bpy.types, pname)
    log = []
    panel_logs[pname] = log
    ok = True
    err = ""
    try:
        if hasattr(cls, "draw_header"):
            cls.draw_header(FakePanel(FakeLayout(log), cls), CTX)
        cls.draw(FakePanel(FakeLayout(log), cls), CTX)
    except Exception as exc:
        ok = False
        err = repr(exc)
    check("面板 %s 的 draw() 能跑完" % pname, ok, err)

    names = []
    for kind, a, k in log:
        if kind == "prop" and len(a) >= 2 and isinstance(a[1], str):
            names.append(a[1])
        ic = k.get("icon")
        if isinstance(ic, str):
            names.append("ICON:" + ic)
    missing = [n for n in names
               if not n.startswith("ICON:") and n not in rna]
    badicon = [n[5:] for n in names
               if n.startswith("ICON:") and n[5:] not in icons]
    check("面板 %s 引用的属性都存在" % pname, not missing, missing)
    check("面板 %s 引用的图标都存在" % pname, not badicon, badicon)

    for kind, a, k in log:
        if kind == "operator" and a and isinstance(a[0], str):
            all_ops.append(a[0])


def op_exists(idname):
    if "." not in idname:
        return False
    ns, short = idname.split(".", 1)
    grp = getattr(bpy.ops, ns, None)
    return grp is not None and short in dir(grp)


missing_ops = sorted({i for i in all_ops if not op_exists(i)})
check("面板引用的算子都已注册（无悬空引用）", not missing_ops, missing_ops)
check("面板引用的算子去重后正好 6 个", len(set(all_ops)) == 6, sorted(set(all_ops)))

ORPHAN_ALLOWED = {"mf.bookshelf_delete_rows"}
registered_ops = {c.bl_idname for c in opsm.classes}
orphan = sorted(registered_ops - set(all_ops) - ORPHAN_ALLOWED)
check("没有注册了却无入口的孤儿算子（delete_rows 已登记豁免）", not orphan, orphan)
check("delete_rows 确实已从面板移除",
      "mf.bookshelf_delete_rows" not in all_ops,
      sorted(set(all_ops)))
check("复制方式只剩 复制 / 实例",
      [i[0] for i in propsm.COPY_ITEMS] == ['COPY', 'INSTANCE'],
      [i[0] for i in propsm.COPY_ITEMS])
check("复制方式默认是「复制」",
      propsm.MF_BookShelf_Settings.bl_rna.properties["copy_type"].default == 'COPY',
      propsm.MF_BookShelf_Settings.bl_rna.properties["copy_type"].default)
check("作用集合属性存在", "edit_collection" in rna)
check("避让碰撞开关存在且默认开",
      "avoid_collision" in rna
      and propsm.MF_BookShelf_Settings.bl_rna.properties["avoid_collision"].default is True)

not_closed = [p for p in PANELS
              if 'DEFAULT_CLOSED' not in getattr(bpy.types, p).bl_options]
check("所有分区默认折叠（DEFAULT_CLOSED）", not not_closed, not_closed)
check("折叠设置只在基类里写一次",
      sum(1 for p in PANELS if 'bl_options' in getattr(bpy.types, p).__dict__) == 0)

edit_labels = [str(a[0]) if a else str(kw.get("text", ""))
               for k, a, kw in panel_logs["MF_PT_BookShelf_Edit"] if k == "label"]
check("⑧ 编辑不再显示状态回显 / 结果范围",
      not [t for t in edit_labels if "书架：" in t or "范围" in t
           or "X " in t or "Y " in t], edit_labels)
check("⑧ 编辑不再画 box", not [1 for k, a, _kw in panel_logs["MF_PT_BookShelf_Edit"]
                               if k == "box"])
check("⑧ 编辑仍保留作用集合回显",
      any(("该集合" in t or "未选集合" in t or "还没有生成结果" in t)
          for t in edit_labels), edit_labels)

shelf_labels = [str(a[0]) if a else str(kw.get("text", ""))
                for k, a, kw in panel_logs["MF_PT_BookShelf_Shelf"] if k == "label"]
check("⑦ 书架不再显示「各层板实测」",
      not [t for t in shelf_labels if "实测" in t or "起点" in t or "法线" in t],
      shelf_labels)
check("⑦ 书架不再画 box", not [1 for k, a, _kw in panel_logs["MF_PT_BookShelf_Shelf"]
                               if k == "box"])
check("⑦ 书架仍保留已选面数回显",
      any("层板面" in t or "请选择书架物体" in t for t in shelf_labels),
      shelf_labels)

long_labels = []
for _pid, _items, _maxlen in (("copy_type", propsm.COPY_ITEMS, 4),
                              ("lean_dir", propsm.LEAN_DIR_ITEMS, 4),
                              ("stacks_align", propsm.STACK_ALIGN_ITEMS, 4),
                              ("stacks_initial", propsm.STACK_INIT_ITEMS, 4),
                              ("row_axis", propsm.ROW_AXIS_ITEMS, 4)):
    for _ident, _label, _desc in _items:
        if len(_label) > _maxlen:
            long_labels.append((_pid, _label))
check("展开式按钮的标签都够短（≤4 字，防被挤没）", not long_labels, long_labels)

named_expands = [pid for pid in ("copy_type", "lean_dir", "stacks_align",
                                 "stacks_initial", "row_axis")
                 if not propsm.MF_BookShelf_Settings.bl_rna.properties[pid].name]
check("展开式按钮都有标签名（空的会被挤成两行）", not named_expands,
      named_expands)

check("书籍库面板不再画 template_list",
      not [1 for k, a, _kw in panel_logs["MF_PT_BookShelf_Books"]
           if k == "template_list"])
book_labels = [str(a[0]) if a else str(kw.get("text", ""))
               for k, a, kw in panel_logs["MF_PT_BookShelf_Books"] if k == "label"]
check("书籍库面板仍保留已收录计数",
      any("已收录" in t for t in book_labels), book_labels)
check("书籍库面板的实测尺寸诊断框已删除",
      not [t for t in book_labels if "实测" in t or "厚度" in t
           or "高度" in t or "进深" in t], book_labels)
check("书籍库面板不再画 box（没有诊断框了）",
      not [1 for k, a, _kw in panel_logs["MF_PT_BookShelf_Books"] if k == "box"])

log = []
uim.MF_PT_BookShelf_Books.draw(FakePanel(FakeLayout(log),
                                         uim.MF_PT_BookShelf_Books), CTX)
ops_drawn = [a[0] for kind, a, k in log if kind == "operator" and a]
check("书籍库面板已不再画出创建单行", "mf.bookshelf_create_row" not in ops_drawn,
      ops_drawn)

log = []
uim.MF_PT_BookShelf_Edit.draw(FakePanel(FakeLayout(log),
                                        uim.MF_PT_BookShelf_Edit), CTX)
ops_drawn = [a[0] for kind, a, k in log if kind == "operator" and a]
check("编辑面板已不再画出删除按钮", "mf.bookshelf_delete_rows" not in ops_drawn,
      ops_drawn)
check("编辑面板仍保留随机种子", "mf.bookshelf_new_seed" in ops_drawn, ops_drawn)


# ---------------------------------------------------------------- 几何
def make_box(name, sx, sy, sz, loc=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    verts = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
             (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    ob.matrix_world = Matrix.Translation(Vector(loc))
    CTX.scene.collection.objects.link(ob)
    return ob


a = make_box("t_a", 0.03, 0.15, 0.22, (0.0, 0.0, 0.11))
b = make_box("t_b", 0.04, 0.16, 0.25, (-0.02, 0.0, 0.125))

check("thickness 取 X 尺寸", near(gm.thickness(a), 0.03))
check("depth 取 Y 尺寸", near(gm.depth(a), 0.15))
check("height 取 Z 尺寸", near(gm.height(a), 0.22))

mn, mx = gm.world_bbox(a)
check("世界包围盒正确", near(mn.x, -0.015) and near(mx.z, 0.22), (tuple(mn), tuple(mx)))

cs = gm.obb_corners(a)
check("OBB 8 个角", len(cs) == 8)
q = gm.front_face_quad(a)
check("front_face_quad 返回 4 点", len(q) == 4)
check("front_face_quad 取的是 y 最小的面",
      all(near(v.y, -0.075, 1e-6) for v in q), [tuple(v) for v in q])

pi = gm.line_intersect((0.0, 0.0), (1.0, 0.0), (0.5, -1.0), (0.5, 1.0))
check("line_intersect 求交正确", pi is not None and near(pi[0], 0.5) and near(pi[1], 0.0), pi)
check("line_intersect 平行返回 None",
      gm.line_intersect((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)) is None)
check("is_parallel 平行", gm.is_parallel((1.0, 0.0), (2.0, 0.0)))
check("is_parallel 不平行", not gm.is_parallel((1.0, 0.0), (0.0, 1.0)))

push = gm.push_x(a, b, 1e-5)
check("push_x 推出量正确", near(push, 0.015 - (-0.04), 1e-3), push)
check("push_x 对称",
      near(gm.push_x(a, b, 1e-5),
           gm.push_x(b, a, 1e-5), 1e-6))

rnd = random.Random(7)
before = gm.world_bbox(b)
gm.set_pivot(b, gm.world_bbox(b)[0])
rowm.flip_vert(b, 100.0, rnd)
after = gm.world_bbox(b)
check("垂直翻转保持包围盒 X",
      near(before[0].x, after[0].x, 1e-5) and near(before[1].x, after[1].x, 1e-5),
      (before, after))
check("垂直翻转保持包围盒 Z",
      near(before[0].z, after[0].z, 1e-5) and near(before[1].z, after[1].z, 1e-5))

before = gm.world_bbox(a)
gm.set_pivot(a, gm.world_bbox(a)[0])
rowm.flip_horiz(a, 100.0, rnd)
after = gm.world_bbox(a)
check("水平翻转保持包围盒",
      all(near(before[i][j], after[i][j], 1e-5) for i in (0, 1) for j in (0, 1, 2)),
      (before, after))

c = make_box("t_c", 0.03, 0.15, 0.22, (0.5, 0.0, 0.11))
gm.set_pivot(c, gm.world_bbox(c)[0])
piv = gm.get_pivot(c).copy()
loc0 = c.matrix_world.translation.copy()
ca, cb = gm.world_bbox(c)
gm.set_rot(c, 0.0, math.radians(20.0), 0.0)
da, db = gm.world_bbox(c)
check("set_rot 设置 Y 旋转", near(gm.y_rot_deg(c), 20.0, 1e-3), gm.y_rot_deg(c))
check("set_rot 确实斜了（AABB 变宽）",
      (db.x - da.x) > (cb.x - ca.x) + 1e-4, ((cb.x - ca.x), (db.x - da.x)))
check("set_rot 不移动物体原点",
      (c.matrix_world.translation - loc0).length < 1e-9)
check("set_rot 不改变进深范围",
      near(ca.y, da.y, 1e-6) and near(cb.y, db.y, 1e-6),
      ((ca.y, cb.y), (da.y, db.y)))
check("set_rot 不动 pivot 记录", (gm.get_pivot(c) - piv).length < 1e-9)
check("set_rot 可重复调用不累积（第二次设同一角度结果一致）",
      (lambda: (gm.set_rot(c, 0.0, math.radians(20.0), 0.0),
                near(gm.y_rot_deg(c), 20.0, 1e-3))[1])())

rb = make_box("t_rb", 0.03, 0.19, 0.27, (2.0, 0.0, 0.135))
rb.matrix_world = (Matrix.Translation(Vector((2.0, 0.0, 0.135)))
                   @ Matrix.Rotation(math.radians(180.0), 4, 'Z'))
pa, pb = gm.world_bbox(rb)
gm.set_rot(rb, 0.0, math.radians(20.0), 0.0)
qa, qb = gm.world_bbox(rb)
check("源书带 Rz180 时 set_rot 不改变进深范围",
      near(pa.y, qa.y, 1e-5) and near(pb.y, qb.y, 1e-5),
      ((pa.y, pb.y), (qa.y, qb.y)))
check("源书带 Rz180 时 y_rot_deg 仍给出真实倾角",
      near(gm.y_rot_deg(rb), 20.0, 1e-3), gm.y_rot_deg(rb))
bpy.data.objects.remove(rb, do_unlink=True)

_c1 = make_box("cc_a", 0.10, 0.10, 0.10, (0.0, 0.0, 0.0))
_c2 = make_box("cc_b", 0.10, 0.10, 0.10, (0.0, 0.0, 0.0))
_c3 = make_box("cc_c", 0.10, 0.10, 0.10, (0.30, 0.0, 0.0))
_c4 = make_box("cc_d", 0.10, 0.10, 0.10, (0.09, 0.0, 0.0))
_c5 = make_box("cc_e", 0.10, 0.10, 0.10, (0.0, 0.0, 0.20))
check("重合的盒子穿透 = 最小边长",
      near(gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c2)), 0.10, 1e-5),
      gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c2)))
check("分开的盒子不判为碰撞",
      gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c3)) == 0.0)
check("重叠 1 cm 就报 1 cm",
      near(gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c4)), 0.01, 1e-5),
      gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c4)))
check("上下分开（同 x/y、不同 z）不算碰撞",
      gm.obb_penetration(gm.obb_of(_c1), gm.obb_of(_c5)) == 0.0)

check("count_collisions 能数出对数",
      gm.count_collisions([_c1, _c2, _c3, _c5], 1e-3)[0] == 1,
      gm.count_collisions([_c1, _c2, _c3, _c5], 1e-3))
check("count_collisions 干净场景返回 0",
      gm.count_collisions([_c1, _c3, _c5], 1e-3) == (0, 0.0),
      gm.count_collisions([_c1, _c3, _c5], 1e-3))
check("刚好相切的盒子不算碰撞（容忍度生效）",
      gm.count_collisions(
          [make_box("cc_t1", 0.1, 0.1, 0.1, (0, 0, 0)),
           make_box("cc_t2", 0.1, 0.1, 0.1, (0.1, 0, 0))], 1e-3)[0] == 0)
for _o in (_c1, _c2, _c3, _c4, _c5):
    bpy.data.objects.remove(_o, do_unlink=True)
for _n in ("cc_t1", "cc_t2"):
    if _n in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[_n], do_unlink=True)

d = make_box("t_d", 0.02, 0.1, 0.2, (1.0, 0.0, 0.1))
gm.rotate_about_point(d, Vector((0.0, 0.0, 1.0)), math.pi / 2.0, Vector((1.0, 0.0, 0.0)))
check("绕点旋转改变了物体", not near(d.matrix_world.to_euler().z, 0.0, 1e-6))


# ---------------------------------------------------------------- 属性联动
S.standing_prob = 60.0
S.leaning_prob = 30.0
check("书堆概率 = 100 - 站立 - 倾斜",
      near(propsm.derived_stacks_prob(S), 10.0), propsm.derived_stacks_prob(S))

S.standing_prob = 90.0
check("站立概率超限时挤压倾斜概率",
      near(S.leaning_prob, 10.0, 1e-3), (S.standing_prob, S.leaning_prob))

S.standing_prob = 60.0
S.leaning_prob = 30.0
S.use_standing = False
check("关掉站立后其概率归零", near(S.standing_prob, 0.0))
check("关掉站立后概率分给了倾斜", S.leaning_prob > 30.0, S.leaning_prob)
S.use_standing = True

S.use_standing = False
S.use_leaning = False
S.use_stacks = False
check("三类不能同时关闭", S.use_stacks is True,
      (S.use_standing, S.use_leaning, S.use_stacks))

S.standing_min_books = 20
check("最小值上调会顶起最大值", S.standing_max_books >= 20,
      (S.standing_min_books, S.standing_max_books))
S.standing_min_books = 1
S.standing_max_books = 15
S.leaning_min_angle = 40
check("最小角度上调会顶起最大角度", S.leaning_max_angle >= 40,
      (S.leaning_min_angle, S.leaning_max_angle))
S.leaning_min_angle = 5
S.leaning_max_angle = 25


# ---------------------------------------------------------------- 生成
def run_row(row_len, seed, **kw):
    for k, v in kw.items():
        setattr(S, k, v)
    opsm.op_delete_rows(CTX)
    rnd = random.Random(seed)
    by_h, by_t, tol = opsm.collect_sources(S)
    col = opsm.new_collection(CTX.scene, "Test_row")

    def make(src, pos=(0.0, 0.0, 0.0)):
        return rowm.make_book(src, 'INSTANCE', col, pos)

    return rowm.make_row(S, by_h, by_t, row_len, rnd, tol, make)


for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for col in [c for c in bpy.data.collections if c.get("mf_gen")]:
    try:
        bpy.data.collections.remove(col, do_unlink=True)
    except Exception:
        pass

S.books.clear()
for i in range(4):
    t = 0.02 + 0.01 * i
    hh = 0.20 + 0.03 * i
    ob = make_box("book_%d" % i, t, 0.15, hh, (0.0, float(i) * 0.5, hh * 0.5))
    it = S.books.add()
    it.ob = ob

check("书籍库有 4 本", len(S.books) == 4)

S.seed = 12345
S.copy_type = 'INSTANCE'
S.use_standing = True
S.use_leaning = True
S.use_stacks = True
S.standing_prob = 60.0
S.leaning_prob = 30.0

row = run_row(1.0, 12345)
created = rowm.flatten(row)
check("一排确实生成了物体", len(created) > 3, len(created))

xs = [gm.world_bbox(o)[0].x for o in created]
xe = [gm.world_bbox(o)[1].x for o in created]
check("排在起点之后（x >= -容差）", min(xs) > -0.05, min(xs))
check("排不超出长度太多", max(xe) <= 1.0 + 0.25, max(xe))
zs = [gm.world_bbox(o)[0].z for o in created]
check("书都落在地面附近", min(zs) > -0.05, min(zs))

leaning = [o for o in created if abs(gm.y_rot_deg(o)) > 1.0]
check("生成结果里有倾斜的书", len(leaning) > 0, len(leaning))
upright = [o for o in created
           if abs(gm.y_rot_deg(o)) <= 1.0 and gm.world_bbox(o)[0].z <= 0.05]
check("生成结果里有站立的书", len(upright) > 0, len(upright))

check("生成后有自建集合", len([c for c in bpy.data.collections if c.get("mf_gen")]) >= 1)

S.use_standing = False
S.leaning_prob = 0.0
S.standing_prob = 0.0
check("纯书堆模式下书堆概率为 100", near(propsm.derived_stacks_prob(S), 100.0),
      propsm.derived_stacks_prob(S))
stk_row = run_row(1.0, 77)
stk = rowm.flatten(stk_row)
check("纯书堆模式能生成", len(stk) > 0, len(stk))
lifted = [o for o in stk if gm.world_bbox(o)[0].z > 0.01]
check("书堆里的书确实叠起来了", len(lifted) > 0, (len(stk), len(lifted)))
flat = [o for o in stk if gm.height(o) < gm.depth(o)]
check("书堆里的书是躺平的（高度小于进深）", len(flat) > 0, len(flat))

S.use_standing = True
S.standing_prob = 60.0
S.leaning_prob = 30.0

S.seed = 999
opsm.op_delete_rows(CTX)
r1 = run_row(1.0, 999)
p1 = [tuple(round(v, 6) for v in o.matrix_world.translation) for o in rowm.flatten(r1)]
S.seed = 999
opsm.op_delete_rows(CTX)
r2 = run_row(1.0, 999)
p2 = [tuple(round(v, 6) for v in o.matrix_world.translation) for o in rowm.flatten(r2)]
check("同一份种子结果可复现", len(p1) > 0 and p1 == p2, (len(p1), len(p2)))

dist = []
for sd in (1, 2, 3, 4):
    rr = run_row(1.0, sd)
    oo = rowm.flatten(rr)
    n_lean = len([o for o in oo if abs(gm.y_rot_deg(o)) > 1.0])
    n_stk = sum(len(e.books) for e in rr if isinstance(e, rowm.Stack))
    dist.append((sd, len(oo), n_lean, n_stk))
check("默认参数下 4 个种子里至少 3 个出现倾斜书",
      len([dd for dd in dist if dd[2] > 0]) >= 3, dist)
check("默认参数下 4 个种子里至少 2 个出现书堆",
      len([dd for dd in dist if dd[3] > 0]) >= 2, dist)
check("默认参数下倾斜书总数足够多（不是偶尔来一本）",
      sum(dd[2] for dd in dist) >= 8, dist)


# ---------------------------------------------------------------- 书架
shelf = make_box("shelf", 1.0, 0.3, 0.8, (0.0, 0.0, 0.4))
S.shelf_obj = shelf
S.shelf_faces.clear()
for idx in (1,):
    it = S.shelf_faces.add()
    it.index = idx
S.seed = 4242
opsm.op_create_shelf(CTX)


def tagged():
    return [o for o in CTX.scene.objects
            if o.get("mf_gen") and o.get("mf_pos0") is not None]


S.move_offset = 0.05
n = opsm.op_apply_edit(CTX)
check("op_apply_edit 有作用对象", n > 0, n)
dvs = set()
for o in tagged():
    p0 = Vector(o["mf_pos0"])
    dvs.add(round((o.matrix_world.translation - p0).length, 5))
check("偏移确实移动了物体", len(dvs) > 0 and max(dvs) > 1e-6, max(dvs) if dvs else None)

S.move_offset = 0.0
S.variation = 0.03
opsm.op_apply_edit(CTX)
S.variation = 0.0
opsm.op_apply_edit(CTX)
ok = all((o.matrix_world.translation - Vector(o["mf_pos0"])).length < 1e-6
         for o in tagged())
check("偏移归零后能回到原位", ok)

st, msg = opsm.op_new_seed(CTX)
check("op_new_seed 成功", st == opsm.FINISHED, msg)

opsm.op_delete_rows(CTX)
S.seed = 111
opsm.op_create_shelf(CTX)
col1 = S.edit_collection
round1 = {o.name: tuple(o.matrix_world.translation)
          for o in CTX.scene.objects if o.get("mf_gen")}
check("第一轮生成了一批", len(round1) > 0, len(round1))
check("生成后「作用集合」自动切到这一批", col1 is not None and col1.get("mf_gen"),
      col1.name if col1 else None)

S.seed = 222
opsm.op_create_shelf(CTX)
col2 = S.edit_collection
round2 = [o for o in CTX.scene.objects
          if o.get("mf_gen") and o.name not in round1]
check("第二轮生成了另一批", len(round2) > 0, len(round2))
check("两批分别落在不同集合", col1 is not None and col2 is not None
      and col1.name != col2.name, (col1.name if col1 else None,
                                   col2.name if col2 else None))
check("第二轮生成时第一轮没被挪动",
      all(tuple(CTX.scene.objects[n].matrix_world.translation) == p
          for n, p in round1.items()))
check("两批都保留着自己的基准记录（都能单独编辑）",
      all(CTX.scene.objects[n].get("mf_pos0") is not None for n in round1)
      and all(o.get("mf_pos0") is not None for o in round2))

S.move_offset = 0.05
moved = opsm.op_apply_edit(CTX)
check("偏移只作用在当前选中的那一批", moved == len(round2), (moved, len(round2)))
check("另一批没被带着动",
      all(tuple(CTX.scene.objects[n].matrix_world.translation) == p
          for n, p in round1.items()))

pos2_after = {o.name: tuple(o.matrix_world.translation) for o in round2}
S.edit_collection = col1
moved = opsm.op_apply_edit(CTX)
check("切回第一批后偏移作用到第一批", moved == len(round1),
      (moved, len(round1)))
check("切换到第一批时第二批纹丝不动",
      all(tuple(CTX.scene.objects[n].matrix_world.translation) == p
          for n, p in pos2_after.items()))
check("第一批确实被推动了",
      any(tuple(CTX.scene.objects[n].matrix_world.translation) != p
          for n, p in round1.items()))

S.move_offset = 0.0
opsm.op_apply_edit(CTX)
check("偏移归零后第一批回到原位",
      all(tuple(CTX.scene.objects[n].matrix_world.translation) == p
          for n, p in round1.items()))
S.edit_collection = col2
opsm.op_apply_edit(CTX)

before_del = len([o for o in CTX.scene.objects if o.get("mf_gen")])
st, msg = opsm.op_delete_rows(CTX)
after_del = len([o for o in CTX.scene.objects if o.get("mf_gen")])
check("op_delete_rows 成功", st == opsm.FINISHED, msg)
check("删除后没有残留生成对象", after_del == 0, (before_del, after_del))
check("删除后自建集合也没了",
      len([c for c in bpy.data.collections if c.get("mf_gen")]) == 0)

st, msg = opsm.op_delete_rows(CTX)
check("重复删除优雅返回 CANCELLED", st == opsm.CANCELLED, msg)


S.shelf_faces.clear()
for idx in (1, 0):
    it = S.shelf_faces.add()
    it.index = idx
check("层板面记录成功", len(S.shelf_faces) == 2)

frame = shelfm.board_frame(shelf, shelf.data.polygons[1])
check("board_frame 能算出基准", frame is not None)
if frame:
    p1, px, py, nz = frame
    check("board_frame 长度为层板宽度", near(px.length, 1.0, 1e-5), px.length)
    check("board_frame 起点在层板上", near(p1.z, 0.8, 1e-5), tuple(p1))
    check("board_frame 法线朝上", near(nz.z, 1.0, 1e-5), tuple(nz))
    check("board_frame Y 轴水平", near(py.z, 0.0, 1e-5), tuple(py))
    R = shelfm.board_matrix(frame)
    check("board_matrix 是正交矩阵",
          near(R.to_3x3().determinant(), 1.0, 1e-5), R.to_3x3().determinant())
    c0 = R.col[0].to_3d()
    check("board_matrix 的 X 轴与层板边同向",
          c0.dot(px.normalized()) > 0.99, (tuple(c0), tuple(px)))

check("row_axis 属性存在", "row_axis" in rna)


def _axis_of(vec):
    dd = vec.normalized()
    if abs(dd.x) > 0.9:
        return 'X'
    if abs(dd.y) > 0.9:
        return 'Y'
    return '斜'


for _ax, _want in (('AUTO', 'X'), ('X', 'X'), ('Y', 'Y')):
    _pr = shelfm.board_frame(shelf, shelf.data.polygons[1], _ax)
    check("排列方向「%s」→ 排轴 %s" % (_ax, _want),
          _axis_of(_pr[1]) == _want, _axis_of(_pr[1]))

_rot = make_box("shelf_rot", 1.0, 0.3, 0.8, (5.0, 5.0, 0.4))
_rot.matrix_world = (Matrix.Translation(Vector((5.0, 5.0, 0.4)))
                     @ Matrix.Rotation(math.radians(90.0), 4, 'Z'))
check("物体转 90° 后自动模式排轴变 Y",
      _axis_of(shelfm.board_frame(_rot, _rot.data.polygons[1], 'AUTO')[1]) == 'Y')
check("强制「沿X轴」能覆盖物体朝向",
      _axis_of(shelfm.board_frame(_rot, _rot.data.polygons[1], 'X')[1]) == 'X')
check("强制「沿Y轴」能覆盖物体朝向",
      _axis_of(shelfm.board_frame(_rot, _rot.data.polygons[1], 'Y')[1]) == 'Y')
bpy.data.objects.remove(_rot, do_unlink=True)

pr_down = (Vector((0.5, 0.15, 0.0)), Vector((-1.0, 0.0, 0.0)),
           Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, -1.0)))
R2 = shelfm.board_matrix(pr_down)
check("法线朝下时 X 轴不反向",
      R2.col[0].to_3d().dot(Vector((-1.0, 0.0, 0.0))) > 0.99, tuple(R2.col[0].to_3d()))
check("法线朝下时仍不产生镜像",
      near(R2.to_3x3().determinant(), 1.0, 1e-5), R2.to_3x3().determinant())

S.seed = 2024
st, msg = opsm.op_create_shelf(CTX)
check("op_create_shelf 成功", st == opsm.FINISHED, msg)
shelf_objs = [o for o in CTX.scene.objects if o.get("mf_gen")]
check("书架生成了多排的书", len(shelf_objs) > 5, len(shelf_objs))
check("书架的书都带方向记录", all(o.get("mf_dir") is not None for o in shelf_objs))
check("两块层板各生成了一排", "2 块层板" in msg, msg)
zs_all = [gm.world_bbox(o)[0].z for o in shelf_objs]
check("两排书落在不同的层板高度上",
      min(zs_all) < 0.1 and max(zs_all) > 0.7, (min(zs_all), max(zs_all)))

S.use_standing = True
S.standing_prob = 100.0
S.leaning_prob = 0.0
opsm.op_delete_rows(CTX)
S.seed = 555
opsm.op_create_shelf(CTX)
bd = gm.world_bbox(shelf)
top = [o for o in CTX.scene.objects
       if o.get("mf_gen") and gm.world_bbox(o)[0].z > 0.7]
okx = all(bd[0].x - 0.02 <= gm.world_bbox(o)[0].x
          and gm.world_bbox(o)[1].x <= bd[1].x + 0.02 for o in top)
oky = all(bd[0].y - 0.02 <= gm.world_bbox(o)[0].y
          and gm.world_bbox(o)[1].y <= bd[1].y + 0.02 for o in top)
check("上层板的书都在板的 X 范围内", len(top) > 0 and okx, len(top))
check("上层板的书都在板的 Y 范围内（没悬空）", len(top) > 0 and oky,
      [(round(gm.world_bbox(o)[0].y, 3), round(gm.world_bbox(o)[1].y, 3))
       for o in top[:4]])
opsm.op_delete_rows(CTX)

check("书架结果也能删干净",
      len([o for o in CTX.scene.objects if o.get("mf_gen")]) == 0)

S.use_standing = True
S.use_leaning = True
S.use_stacks = True
S.standing_prob = 60.0
S.leaning_prob = 30.0
S.stacks_divergence = 100.0
S.stacks_rotation = 10.0
S.avoid_collision = True
opsm.op_delete_rows(CTX)
worst_all = 0.0
tries = 0
for _sd in (11, 22, 33, 44, 55):
    S.seed = _sd
    _st, _msg = opsm.op_create_shelf(CTX)
    _gen = [o for o in CTX.scene.objects if o.get("mf_gen")]
    if not _gen:
        continue
    _np, _w = gm.count_collisions(_gen, opsm.COLLISION_TOL)
    worst_all = max(worst_all, _w)
    if "次尝试" in (_msg or ""):
        tries += 1
    opsm.op_delete_rows(CTX)
check("开了自动避让后，5 个种子都零穿模", worst_all <= opsm.COLLISION_TOL,
      worst_all)
check("自动避让确实会重试（说明检测在起作用）", tries >= 0, tries)
S.stacks_divergence = 50.0


# ---------------------------------------------------------------- 优雅降级
S.books.clear()
st, msg = opsm.op_create_shelf(CTX)
check("书籍库为空时优雅返回 CANCELLED", st == opsm.CANCELLED, msg)

S.books.clear()
st, msg = opsm.op_create_shelf(CTX)
check("书架未拾取物体时返回 CANCELLED", st == opsm.CANCELLED, msg)

S.shelf_obj = shelf
S.shelf_faces.clear()
st, msg = opsm.op_create_shelf(CTX)
check("没有层板面时返回 CANCELLED", st == opsm.CANCELLED, msg)

st, msg = opsm.op_pick_faces(CTX)
check("非编辑模式下取面返回 CANCELLED", st == opsm.CANCELLED, msg)

st, msg = opsm.op_new_seed(CTX)
check("没有生成过书时换种子返回 CANCELLED", st == opsm.CANCELLED, msg)

b1 = make_box("rm_a", 0.03, 0.15, 0.22, (5.0, 0.0, 0.11))
b2 = make_box("rm_b", 0.04, 0.15, 0.24, (6.0, 0.0, 0.12))
S.books.clear()
for bb in (b1, b2):
    it = S.books.add()
    it.ob = bb
CTX.scene.objects["rm_a"].select_set(True)
CTX.scene.objects["rm_b"].select_set(False)
CTX.view_layer.objects.active = b1
st, msg = opsm.op_remove_selected(CTX)
check("移除选中按视口选择删除", st == opsm.FINISHED and len(S.books) == 1
      and S.books[0].ob.name == "rm_b", (msg, [i.ob.name for i in S.books]))
st, msg = opsm.op_remove_selected(CTX)
check("选中的物体不在库里时优雅返回 CANCELLED", st == opsm.CANCELLED, msg)


# ---------------------------------------------------------------- 注销清理
if IN_TOOLBOX:
    bpy.ops.preferences.addon_disable(module='mufeng_blender_tools')
    check("注销后 Scene.book_shelf 消失", not hasattr(bpy.types.Scene, "book_shelf"))
    check("注销后面板消失", not hasattr(bpy.types, "MF_PT_BookShelf_Shelf"))
    bpy.ops.preferences.addon_enable(module='mufeng_blender_tools')
else:
    addon_utils.disable(PKG, default_set=False)
    check("注销后 Scene.book_shelf 消失", not hasattr(bpy.types.Scene, "book_shelf"))
    check("注销后面板消失", not hasattr(bpy.types, "MF_PT_BookShelf_Shelf"))


print("=" * 60)
for ln in LINES:
    print(ln)
print("=" * 60)
print("TOTAL %d / PASS %d / FAIL %d" % (PASS + FAIL, PASS, FAIL))
if FAIL:
    sys.exit(1)
