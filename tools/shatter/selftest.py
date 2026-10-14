import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from . import operators as ops
    from . import ui
else:
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from mufeng_blender_tools.tools.shatter import operators as ops
    from mufeng_blender_tools.tools.shatter import ui


class Harness:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.lines = []

    def title(self, text):
        self.lines.append("")
        self.lines.append("── %s " % text + "─" * max(0, 46 - len(text)))

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            self.lines.append("  PASS  %s" % name)
        else:
            self.failed += 1
            suffix = "   <- %s" % detail if detail else ""
            self.lines.append("  FAIL  %s%s" % (name, suffix))

    def eq(self, name, got, want):
        self.check(name, got == want, "得到 %r，期望 %r" % (got, want))

    def near(self, name, got, want, tol):
        self.check(name, abs(got - want) <= tol,
                   "得到 %.5f，期望 %.5f±%.5f" % (got, want, tol))


def _wipe_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.collections):
        for item in list(block):
            if item.users == 0:
                try:
                    block.remove(item)
                except Exception:
                    pass


def _deselect_all():
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        for obj in bpy.context.view_layer.objects:
            if obj is not None:
                obj.select_set(False)
    bpy.context.view_layer.objects.active = None


def _activate(obj):
    _deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _add_cube(size=2.0):
    bpy.ops.mesh.primitive_cube_add(size=size)
    return bpy.context.active_object


def _add_uv_sphere(radius=1.5):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius)
    return bpy.context.active_object


def _add_torus():
    bpy.ops.mesh.primitive_torus_add(major_radius=1.2, minor_radius=0.4)
    return bpy.context.active_object


def _add_cylinder(vertices=16, radius=1.0, depth=2.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth)
    return bpy.context.active_object


def _add_plane(size=4.0):
    bpy.ops.mesh.primitive_plane_add(size=size)
    return bpy.context.active_object


def _drop_faces(obj, predicate):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    doomed = [f for f in bm.faces if predicate(f)]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES_ONLY")
    bm.to_mesh(obj.data)
    bm.free()
    return len(doomed)


def _subdivide(obj, predicate, cuts=1):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if predicate(e)],
                              cuts=cuts, use_grid_fill=True)
    bm.to_mesh(obj.data)
    bm.free()


def _add_octahedron():
    me = bpy.data.meshes.new("Oct")
    me.from_pydata(
        [(1.4, 0, 0), (0, 1.4, 0), (-1.4, 0, 0), (0, -1.4, 0), (0, 0, 1.4), (0, 0, -1.4)],
        [],
        [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
         (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)])
    obj = bpy.data.objects.new("Oct", me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _add_frame():
    outer = [(-2, -2, -1.5), (2, -2, -1.5), (2, 2, -1.5), (-2, 2, -1.5),
             (-2, -2, 1.5), (2, -2, 1.5), (2, 2, 1.5), (-2, 2, 1.5)]
    inner = [(-0.6, -0.6, -1.5), (0.6, -0.6, -1.5), (0.6, 0.6, -1.5), (-0.6, 0.6, -1.5),
             (-0.6, -0.6, 1.5), (0.6, -0.6, 1.5), (0.6, 0.6, 1.5), (-0.6, 0.6, 1.5)]
    faces = [(0, 1, 9, 8), (1, 2, 10, 9), (2, 3, 11, 10), (3, 0, 8, 11),
             (4, 5, 13, 12), (5, 6, 14, 13), (6, 7, 15, 14), (7, 4, 12, 15),
             (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
             (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15)]
    me = bpy.data.meshes.new("Frame")
    me.from_pydata(outer + inner, [], faces)
    obj = bpy.data.objects.new("Frame", me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _add_open_tube(vertices=16):
    obj = _add_cylinder(vertices=vertices)
    _drop_faces(obj, lambda f: abs(f.normal.z) > 0.9)
    return obj


def _add_holed_sphere():
    obj = _add_uv_sphere()
    _drop_faces(obj, lambda f: f.calc_center_median().z > 1.4)
    return obj


def _add_belt_cylinder():
    obj = _add_cylinder(vertices=12)
    _subdivide(obj, lambda e: abs(e.verts[0].co.z) < 1e-6 and abs(e.verts[1].co.z) < 1e-6)
    return obj


def _bm(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    return bm


def _stats(bm):
    open_e = ops._open_edges(bm)
    nonman = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    zero = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    loose = sum(1 for v in bm.verts if not v.link_edges)
    vol = 0.0
    for f in bm.faces:
        vs = [v.co for v in f.verts]
        for i in range(2, len(vs)):
            vol += vs[0].dot(vs[i - 1].cross(vs[i])) / 6.0
    return len(open_e), nonman, zero, loose, abs(vol), len(bm.faces)


def _cut(bm, co, no, keep_positive):
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    lo, hi = ops.bounds_of(bm)
    eps = max((hi - lo).length * 1e-6, 1e-9)
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=eps, plane_co=Vector(co),
                                 plane_no=Vector(no),
                                 clear_outer=not keep_positive,
                                 clear_inner=keep_positive)
    cut_edges = [g for g in res.get("geom_cut", ()) if isinstance(g, bmesh.types.BMEdge)]
    ops._cap(bm, cut_edges)
    return cut_edges


def _piece_report(h, name, obj):
    bm = _bm(obj)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.check("%s 封闭" % name, open_e == 0, "开放边 %d" % open_e)
    h.check("%s 流形" % name, nonman == 0, "非流形边 %d" % nonman)
    h.check("%s 无零面积面" % name, zero == 0, "零面积面 %d" % zero)
    h.check("%s 无散点" % name, loose == 0, "散点 %d" % loose)
    return vol, faces


def _test_planar_cap(h):
    h.title("① 平面切环（干净切割）")
    obj = _add_cube()
    _activate(obj)
    bm = _bm(obj)
    _cut(bm, (0, 0, 0), (0, 0, 1), True)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("切后半封闭", open_e, 0)
    h.eq("切后半无流形问题", nonman, 0)
    h.eq("补 1 个盖面", faces, 6)
    h.near("体积为原立方体一半", vol, 4.0, 1e-6)


def _test_ring_cap(h):
    h.title("② 切面正好穿过顶点环（旧代码静默失败）")
    obj = _add_uv_sphere()
    _activate(obj)
    bm = _bm(obj)
    ce = _cut(bm, (0, 0, 0), (0, 0, 1), True)
    h.check("赤道环几何被返回", len(ce) > 0, "geom_cut %d 条" % len(ce))
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("UV 球赤道切割后封闭", open_e, 0)
    h.check("半球体积正确", 6.5 < vol < 7.1, "vol=%.4f" % vol)

    obj = _add_octahedron()
    _activate(obj)
    bm = _bm(obj)
    _cut(bm, (0, 0, 0), (0, 0, 1), True)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("八面体赤道切割后封闭", open_e, 0)
    h.eq("上半是 4 三角 + 1 盖", faces, 5)

    obj = _add_belt_cylinder()
    _activate(obj)
    bm = _bm(obj)
    _cut(bm, (0, 0, 0), (0, 0, 1), True)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("腰带环切割后封闭", open_e, 0)
    h.near("下半圆柱体积", vol, 3.0, 0.01)


def _test_multi_loop_cap(h):
    h.title("③ 一刀切出多个环（圆环）")
    obj = _add_torus()
    _activate(obj)
    bm = _bm(obj)
    total_faces = len(bm.faces)
    _cut(bm, (0, 0, 0), (0, 0, 1), True)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("圆环切割后封闭", open_e, 0)
    h.eq("两个环各补一个盖", faces, total_faces // 2 + 2)
    h.check("半圆环体积正确", 1.7 < vol < 1.95, "vol=%.4f" % vol)


def _test_nonplanar_cap(h):
    h.title("④ 非平面闭环（开放网格斜切，耳切三角化）")
    obj = _add_open_tube()
    _activate(obj)
    bm = _bm(obj)
    _cut(bm, (0.3, 0.2, 0.4), (0.4, 0.3, 0.9), True)
    open_e, nonman, zero, loose, vol, faces = _stats(bm)
    bm.free()
    h.eq("斜切开放管后封闭", open_e, 0)
    h.eq("无流形问题", nonman, 0)
    h.eq("无零面积面", zero, 0)
    h.check("补出了实体体积", vol > 0.05, "vol=%.4f" % vol)


def _test_wire_and_snarl(h):
    h.title("⑤ 悬空线与顶点乱麻（带孔球）")
    obj = _add_holed_sphere()
    _activate(obj)
    bm = _bm(obj)
    wires = sum(1 for e in bm.edges if not e.link_faces)
    bm.free()
    h.check("源网格确实带悬空线", wires > 0, "wire=%d" % wires)
    pieces, stats = ops.run_grid_cut(bpy.context, obj, 2, 2, 2, True, False)
    h.eq("切出 8 块", len(pieces), 8)
    bad = 0
    open_pieces = 0
    for p in pieces:
        bm = _bm(p)
        open_e, nonman, zero, loose, vol, faces = _stats(bm)
        bm.free()
        if nonman or zero or loose:
            bad += 1
        if open_e:
            open_pieces += 1
    h.eq("8 块全部干净（开放源允许保留源破洞）", bad, 0)
    h.check("开放源的破洞被如实保留", open_pieces > 0)
    h.eq("统计与实况一致", stats["open"], open_pieces)


def _test_sheet(h):
    h.title("⑥ 平片不补出重面")
    obj = _add_plane()
    _activate(obj)
    pieces, stats = ops.run_grid_cut(bpy.context, obj, 2, 2, 1, True, False)
    h.eq("平片切出 4 块", len(pieces), 4)
    ok = True
    for p in pieces:
        bm = _bm(p)
        faces = len(bm.faces)
        bm.free()
        if faces != 1:
            ok = False
    h.check("单面平片保持单面（不糊重面）", ok)
    h.eq("统计如实报告开放", stats["open"], 4)


def _test_flap_book(h):
    h.title("⑦ 擦顶点残留：翘片与 4 面边（随机破碎回归）")
    obj = _add_open_tube()
    _activate(obj)
    pieces, stats = ops.run_random_fracture(bpy.context, obj, 12, 9, True)
    h.eq("碎成 12 块", len(pieces), 12)
    bad = 0
    for p in pieces:
        bm = _bm(p)
        open_e, nonman, zero, loose, vol, faces = _stats(bm)
        bm.free()
        if open_e or nonman or zero or loose:
            bad += 1
    h.eq("12 块全部封闭且流形", bad, 0)
    h.eq("统计与实况一致", stats, {"closed": 12, "open": 0})


def _test_grid_e2e(h):
    h.title("⑧ 算子端到端：整齐切割")
    obj = _add_uv_sphere()
    _activate(obj)
    before = len(bpy.data.objects)
    try:
        result = bpy.ops.mf.shatter_grid(segx=2, segy=2, segz=2, hide_original=True, skin=False)
        h.check("算子返回 FINISHED", "FINISHED" in result, str(result))
    except Exception as exc:
        h.check("算子返回 FINISHED", False, repr(exc))
        return
    h.eq("新增 8 个碎块", len(bpy.data.objects) - before, 8)
    pieces = [o for o in bpy.data.objects if o.name.startswith("Sphere_")]
    h.eq("按名字数出 8 块", len(pieces), 8)
    bad = 0
    for p in pieces:
        bm = _bm(p)
        open_e = len(ops._open_edges(bm))
        bm.free()
        if open_e:
            bad += 1
    h.eq("8 块全封闭", bad, 0)
    h.check("原物体已隐藏", obj.hide_viewport or obj.hide_get())


def _test_random_e2e(h):
    h.title("⑨ 算子端到端：随机破碎")
    obj = _add_uv_sphere()
    _activate(obj)
    try:
        result = bpy.ops.mf.shatter_random(count=8, seed=3, hide_original=True)
        h.check("算子返回 FINISHED", "FINISHED" in result, str(result))
    except Exception as exc:
        h.check("算子返回 FINISHED", False, repr(exc))
        return
    pieces = [o for o in bpy.data.objects if o.name.startswith("Sphere_")]
    h.eq("碎出 8 块", len(pieces), 8)
    bad = 0
    for p in pieces:
        bm = _bm(p)
        open_e = len(ops._open_edges(bm))
        bm.free()
        if open_e:
            bad += 1
    h.eq("8 块全封闭", bad, 0)


def _test_skin_e2e(h):
    h.title("⑩ 加厚模式")
    obj = _add_open_tube()
    _activate(obj)
    pieces, stats = ops.run_grid_cut(bpy.context, obj, 1, 1, 2, True, True)
    h.eq("切出 2 块", len(pieces), 2)
    bad = 0
    for p in pieces:
        bm = _bm(p)
        open_e, nonman, zero, loose, vol, faces = _stats(bm)
        bm.free()
        if open_e or nonman or loose:
            bad += 1
    h.eq("2 块全封闭", bad, 0)


def _operator_registered(short_name):
    try:
        getattr(bpy.ops.mf, short_name).get_rna_type()
        return True
    except Exception:
        return False


_TOOL_PKG = "mufeng_blender_tools.tools.shatter"


def _tool_package():
    return sys.modules.get(__package__ or _TOOL_PKG)


def _test_registration(h):
    h.title("⑪ 注册 / 注销")
    pkg = _tool_package()
    h.check("工具包可访问", pkg is not None)
    if pkg is None:
        return
    h.check("算子 shatter_grid 已注册", _operator_registered("shatter_grid"))
    h.check("算子 shatter_random 已注册", _operator_registered("shatter_random"))
    h.check("主面板已注册", hasattr(bpy.types, ui.MF_PT_Shatter.bl_idname))
    h.check("切割子面板已注册", hasattr(bpy.types, ui.MF_PT_Shatter_Cut.bl_idname))
    h.check("WindowManager 属性已挂载",
            ops.WM_ATTR in bpy.types.WindowManager.bl_rna.properties)

    pkg.unregister()
    h.check("注销后算子消失", not _operator_registered("shatter_grid"))
    h.check("注销后主面板消失", not hasattr(bpy.types, ui.MF_PT_Shatter.bl_idname))
    h.check("注销后子面板消失", not hasattr(bpy.types, ui.MF_PT_Shatter_Cut.bl_idname))
    h.check("注销后属性移除",
            ops.WM_ATTR not in bpy.types.WindowManager.bl_rna.properties)

    pkg.register()
    h.check("重新注册后算子回来", _operator_registered("shatter_grid"))
    h.check("重新注册后主面板回来", hasattr(bpy.types, ui.MF_PT_Shatter.bl_idname))
    h.check("重新注册后属性恢复",
            ops.WM_ATTR in bpy.types.WindowManager.bl_rna.properties)


def _test_static(h):
    h.title("⑫ 静态卫生")
    path = os.path.abspath(ops.__file__)
    src = open(path, encoding="utf-8").read()
    code = "\n".join(line.split("#")[0] for line in src.splitlines())
    h.check("旧扇形补面函数已移除", "_fill_loops" not in code)
    h.check("旧双向游走函数已移除", "_walk_edge_loops" not in code)
    h.check("不再依赖 edgenet_fill", "edgenet_fill" not in code)
    for fn in ("_cap", "_ear_fill", "_remove_flaps", "_sweep_debris", "_loops_from"):
        h.check("引擎函数 %s 存在" % fn, hasattr(ops, fn))


class FakeLayout:
    def __init__(self, log=None):
        self.log = log if log is not None else []

    def _rec(self, kind, target):
        self.log.append((kind, target))

    def row(self, *a, **k):
        return FakeLayout(self.log)

    def column(self, *a, **k):
        return FakeLayout(self.log)

    def box(self, *a, **k):
        return FakeLayout(self.log)

    def split(self, *a, **k):
        return FakeLayout(self.log)

    def label(self, *a, **k):
        self._rec("label", a[0] if a else k.get("text", ""))
        return None

    def prop(self, data, prop, **k):
        self._rec("prop", prop)
        return None

    def operator(self, op_id, **k):
        self._rec("operator", op_id)
        return _FakeOp(op_id)

    def separator(self, *a, **k):
        return None


class _FakeOp:
    def __init__(self, op_id):
        self.op_id = op_id


class _FakePanel:
    def __init__(self, layout):
        self.layout = layout

    def __getattr__(self, name):
        return getattr(type(self), name).__get__(self, type(self))


def _test_panel_draw(h):
    h.title("⑬ 面板绘制")
    props = getattr(bpy.context.window_manager, ops.WM_ATTR, None)
    h.check("参数组可访问", props is not None)
    if props is None:
        return
    for cls in (ui.MF_PT_Shatter, ui.MF_PT_Shatter_Cut, ui.MF_PT_Shatter_Break):
        log = []
        try:
            cls.draw(_FakePanel(FakeLayout(log)), bpy.context)
            h.check("%s draw 无异常" % cls.bl_idname, True)
        except Exception as exc:
            h.check("%s draw 无异常" % cls.bl_idname, False, repr(exc))
            continue
        ops_drawn = [t for kind, t in log if kind == "operator"]
        if cls is ui.MF_PT_Shatter:
            h.check("%s 只画目标标签" % cls.bl_idname, not ops_drawn)
        else:
            h.check("%s 画出了操作按钮" % cls.bl_idname, len(ops_drawn) > 0)
            h.check("%s 按钮 id 正确" % cls.bl_idname,
                    all(t in (ops.GRID_OP_ID, ops.RANDOM_OP_ID) for t in ops_drawn),
                    str(ops_drawn))


def _ensure_registered():
    if hasattr(bpy.types, "MF_OT_Shatter_Grid"):
        return
    root = __package__.split(".")[0] if __package__ else "mufeng_blender_tools"
    package = sys.modules.get(root)
    if package is not None and hasattr(package, "register"):
        package.register()
        return
    ops.register()
    ui.register()


def run():
    h = Harness()
    h.lines.append("=" * 58)
    h.lines.append("物体破碎（补洞引擎） 无头自检")
    h.lines.append("Blender %s   后台模式：%s" % (bpy.app.version_string, bpy.app.background))
    h.lines.append("=" * 58)

    _ensure_registered()
    _wipe_scene()

    groups = (
        _test_planar_cap,
        _test_ring_cap,
        _test_multi_loop_cap,
        _test_nonplanar_cap,
        _test_wire_and_snarl,
        _test_sheet,
        _test_flap_book,
        _test_grid_e2e,
        _test_random_e2e,
        _test_skin_e2e,
        _test_registration,
        _test_static,
        _test_panel_draw,
    )
    for group in groups:
        try:
            group(h)
        except Exception as error:
            h.failed += 1
            h.lines.append("  FAIL  %s 抛出异常：%s" % (group.__name__, error))
            h.lines.append(traceback.format_exc())
        finally:
            _wipe_scene()

    h.lines.append("")
    h.lines.append("=" * 58)
    h.lines.append("结果：通过 %d 项，失败 %d 项 %s"
                   % (h.passed, h.failed, "—— 全部通过" if not h.failed else "—— 有失败"))
    h.lines.append("=" * 58)
    return h.passed, h.failed, h.lines


def main():
    passed, failed, lines = run()
    for line in lines:
        print(line)
    return failed


if __name__ == "__main__":
    try:
        raise SystemExit(1 if main() else 0)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("\n[自检中断] 未捕获异常，见上方 Traceback")
        raise SystemExit(1)
