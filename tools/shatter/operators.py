import random
import time

import bmesh
import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree


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

TOOL_ID = "Shatter"
GRID_OP_ID = "mf.shatter_grid"
RANDOM_OP_ID = "mf.shatter_random"
WM_ATTR = "mf_shatter"

PREVIEW_NAME = "MF_切割预览"
PREVIEW_FLAG = "mf_shatter_preview"


GRID_SLOW_CELLS = 500
SHATTER_WARN_PARTS = 150
SHATTER_MAX_PARTS = 500

SKIN_MM = 1.0
SKIN_OPEN_RATIO = 0.01
WELD_DIST = 1e-6
SKIN_MAX_GROW = 10.0
SKIN_DESC = ("切开前先给模型加一层 1 毫米厚的皮，碎块才会是封闭实体（切口有面）。"
             "\n只要模型存在开放边（占比超过 1%）就会加厚；"
             "完全闭合的实体模型不会被改动。"
             "\n代价：碎块面数约翻倍，切割会慢一些、文件也会变大。")


def target_object(context):
    try:
        selected = [o for o in context.selected_objects if o.type == 'MESH']
    except Exception:
        return None
    if not selected:
        return None
    active = getattr(context, "active_object", None)
    if active is not None and active.type == 'MESH' and active in selected:
        return active
    return selected[0]


def source_is_flat(me):
    if me is None:
        return False
    faces = list(me.polygons)
    if not faces:
        return False
    if not me.has_custom_normals:
        return not any(p.use_smooth for p in faces)
    step = max(1, len(faces) // 200)
    for p in faces[::step]:
        normal = p.normal
        for li in p.loop_indices:
            if normal.dot(me.corner_normals[li].vector) < 0.998:
                return False
    return True


def source_bmesh(context, obj, skin=False):
    me = None
    try:
        dg = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(
            eval_obj, preserve_all_data_layers=True, depsgraph=dg)
    except Exception as exc:
        utils.report("WARNING", f"取生效网格失败，改用原始网格: {exc}")
        me = None

    bm = bmesh.new()
    if me is not None:
        flat = source_is_flat(me)
        bm.from_mesh(me)
        mats = list(me.materials)
        bpy.data.meshes.remove(me)
    else:
        flat = source_is_flat(obj.data)
        bm.from_mesh(obj.data)
        mats = list(obj.data.materials)

    bm, welded = weld_source(bm)
    if welded:
        utils.report("INFO", f"{obj.name} 顶点未焊接，已自动焊接成闭合实体")

    if skin:
        if not needs_skin(bm):
            utils.report("INFO", f"{obj.name} 已是闭合实体，未加厚")
        else:
            thickness = skin_thickness(context)
            if add_skin(bm, thickness, context):
                utils.report("INFO",
                             f"{obj.name} 零厚度面片，已加厚 {SKIN_MM:g} 毫米"
                             f"（{thickness:.6g} 个单位）")
            else:
                utils.report("WARNING", f"{obj.name} 加厚未生效，按原网格切割")
    return bm, mats, flat


def bounds_of(bm):
    if not bm.verts:
        return None
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    return (Vector((min(xs), min(ys), min(zs))),
            Vector((max(xs), max(ys), max(zs))))


def skin_thickness(context):
    try:
        scale = context.scene.unit_settings.scale_length
    except Exception:
        scale = 1.0
    if not scale or scale <= 0.0:
        scale = 1.0
    return (SKIN_MM * 0.001) / scale


def open_edges(bm):
    return sum(1 for e in bm.edges if len(e.link_faces) < 2)


def weld_source(bm):
    if not bm.faces or open_edges(bm) == 0:
        return bm, False
    probe = bm.copy()
    try:
        bmesh.ops.remove_doubles(probe, verts=list(probe.verts), dist=WELD_DIST)
    except Exception as exc:
        utils.report("WARNING", f"焊接探测失败，按原网格切割: {exc}")
        probe.free()
        return bm, False
    if open_edges(probe) == 0:
        bm.free()
        return probe, True
    probe.free()
    return bm, False


def needs_skin(bm):
    edges = len(bm.edges)
    if not bm.faces or edges == 0:
        return False
    return open_edges(bm) > edges * SKIN_OPEN_RATIO


def add_skin(bm, thickness, context):
    if not bm.faces or thickness <= 0.0:
        return False
    lo_hi = bounds_of(bm)
    if lo_hi is None:
        return False
    lo0, hi0 = lo_hi

    backup = bpy.data.meshes.new("mf_skin_backup")
    bm.to_mesh(backup)
    src = bpy.data.meshes.new("mf_skin_src")
    bm.to_mesh(src)
    tmp = bpy.data.objects.new("mf_skin_src", src)
    context.scene.collection.objects.link(tmp)

    out = None
    err = None
    try:
        mod = tmp.modifiers.new("MF_Skin", 'SOLIDIFY')
        mod.thickness = thickness
        mod.solidify_mode = 'EXTRUDE'
        dg = context.evaluated_depsgraph_get()
        out = bpy.data.meshes.new_from_object(
            tmp.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    except Exception as exc:
        err = exc
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.meshes.remove(src)

    if err is not None or out is None:
        utils.report("WARNING", f"加厚失败，按原网格切割: {err}")
        bpy.data.meshes.remove(backup)
        return False

    bm.clear()
    bm.from_mesh(out)
    bpy.data.meshes.remove(out)

    lo_hi = bounds_of(bm)
    if lo_hi is None:
        bm.clear()
        bm.from_mesh(backup)
        bpy.data.meshes.remove(backup)
        return False
    lo1, hi1 = lo_hi
    grow = max((Vector(lo0) - Vector(lo1)).length,
               (Vector(hi1) - Vector(hi0)).length)
    limit = thickness * SKIN_MAX_GROW
    if grow > limit:
        bm.clear()
        bm.from_mesh(backup)
        bpy.data.meshes.remove(backup)
        utils.report("WARNING",
                     f"{SKIN_MM:g} 毫米加厚会让包围盒外扩 {grow:.4g} 个单位"
                     f"（上限 {limit:.4g}），该模型无法安全加厚，已按原网格切割")
        return False
    bpy.data.meshes.remove(backup)
    return True


def piece_collection(obj, context):
    if obj.users_collection:
        return obj.users_collection[0]
    return context.scene.collection


def hide_object(obj):
    try:
        obj.hide_set(True)
        return
    except Exception:
        pass
    try:
        obj.hide_viewport = True
    except Exception:
        pass


def new_piece(name, bm, src, mats, coll, flat=False):
    if flat:
        for f in bm.faces:
            f.smooth = False
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    me.update()
    if flat:
        attr = me.attributes.get("custom_normal")
        if attr is not None:
            try:
                me.attributes.remove(attr)
            except Exception:
                pass
    for mat in mats:
        try:
            me.materials.append(mat)
        except Exception:
            pass
    obj = bpy.data.objects.new(name, me)
    obj.matrix_world = src.matrix_world.copy()
    try:
        obj.color = src.color
    except Exception:
        pass
    coll.objects.link(obj)
    return obj


def _walk_edge_loops(open_edges):
    adj = {}
    for e in open_edges:
        adj.setdefault(e.verts[0], []).append(e)
        adj.setdefault(e.verts[1], []).append(e)
    seen = set()
    loops = []
    for e0 in open_edges:
        if e0 in seen:
            continue
        seen.add(e0)
        loop = [e0]
        start = e0.verts[0]
        cur = e0.verts[1]
        while cur != start:
            nxt = None
            for e in adj.get(cur, []):
                if e not in seen:
                    nxt = e
                    break
            if nxt is None:
                break
            seen.add(nxt)
            loop.append(nxt)
            a, b = nxt.verts
            cur = b if a == cur else a
        loops.append(loop)
    return loops


def _fill_loops(bm, open_edges):
    """按环序补面, 自相交环退化为扇形三角化; 返回新建面数"""
    made = 0
    for loop in _walk_edge_loops(open_edges):
        order = [loop[0].verts[0]]
        cur = loop[0].verts[1]
        used = {loop[0]}
        while True:
            nxt = None
            for e in loop:
                if e in used:
                    continue
                if e.verts[0] == cur or e.verts[1] == cur:
                    nxt = e
                    break
            if nxt is None:
                break
            used.add(nxt)
            order.append(cur)
            a, b = nxt.verts
            cur = b if a == cur else a
        closed = (cur == order[0])
        if not closed:
            order.append(cur)
        try:
            bm.faces.new(tuple(order))
            made += 1
            continue
        except Exception:
            pass
        for k in range(1, len(order) - 1):
            try:
                bm.faces.new((order[0], order[k], order[k + 1]))
                made += 1
            except Exception:
                pass
    return made


def _needle_faces(bm, min_apex_edge):
    """找针状面: 长宽比极端 + 面积占比极小 + 针尖只连长边 + 针尖周围全是细长面"""
    sliver = set()
    for f in bm.faces:
        els = [e.calc_length() for e in f.edges]
        mx, mn = max(els), min(els)
        if mx <= 0 or mn <= 0 or mx / mn <= 50:
            continue
        if f.calc_area() / (mx * mx) < 2e-3:
            sliver.add(f)
    found = []
    for f in sliver:
        els = [(e.calc_length(), e) for e in f.edges]
        mx = max(l for l, _ in els)
        mn = min(l for l, _ in els)
        if mx <= 0 or mn <= 0 or mx / mn <= 50:
            continue
        short_edge = min(els, key=lambda t: t[0])[1]
        a, b = short_edge.verts
        for apex in f.verts:
            if apex is a or apex is b:
                continue
            ls = [e.calc_length() for e in apex.link_edges]
            if ls and min(ls) > min_apex_edge:
                if all(g in sliver for g in apex.link_faces):
                    found.append((f, apex))
                    break
    return found


def cleanup_piece(bm, lo, hi, do_sliver=False):
    """删除针状退化面及其残留点线; 迭代执行直到无离群, 返回删除的面数"""
    if not bm.faces:
        return 0
    diag = max((Vector(hi) - Vector(lo)).length, 1e-9)
    tol = max(diag * 1e-4, 1e-9)
    removed = 0
    for _ in range(4):
        doomed = set()
        base = set()

        def mark(faces):
            for f in faces:
                doomed.add(f)
                for e in f.edges:
                    base.add(e.verts[0])
                    base.add(e.verts[1])

        bad = []
        for v in bm.verts:
            c = v.co
            if (c.x < lo[0] - tol or c.x > hi[0] + tol or
                    c.y < lo[1] - tol or c.y > hi[1] + tol or
                    c.z < lo[2] - tol or c.z > hi[2] + tol):
                bad.append(v)
        for v in bad:
            mark(v.link_faces)
        if do_sliver:
            min_apex = max(diag * 1e-4, 1e-9)
            mark(f for f, _apex in _needle_faces(bm, min_apex))
        if not doomed:
            break
        bmesh.ops.delete(bm, geom=list(doomed), context='FACES')
        wire_e = [e for e in bm.edges if not e.link_faces]
        if wire_e:
            bmesh.ops.delete(bm, geom=wire_e, context='EDGES')
        loose_v = [v for v in bm.verts if not v.link_edges]
        if loose_v:
            bmesh.ops.delete(bm, geom=loose_v, context='VERTS')
        hole_e = [e for e in bm.edges
                  if len(e.link_faces) < 2
                  and e.verts[0] in base and e.verts[1] in base]
        if hole_e:
            _fill_loops(bm, hole_e)
        removed += len(doomed)
    for w in (diag * 1e-4, diag * 1e-3, diag * 2e-3, diag * 4e-3):
        open_e = [e for e in bm.edges if len(e.link_faces) < 2]
        if not open_e:
            break
        vs = set()
        for e in open_e:
            vs.add(e.verts[0])
            vs.add(e.verts[1])
        try:
            bmesh.ops.remove_doubles(bm, verts=list(vs), dist=w)
        except Exception:
            pass
        open_e = [e for e in bm.edges if len(e.link_faces) < 2]
        if open_e:
            _fill_loops(bm, open_e)
    try:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=WELD_DIST)
    except Exception:
        pass
    return removed


def _cap(bm, cut_edges):
    if not cut_edges:
        return
    deg = {}
    for e in cut_edges:
        for v in e.verts:
            deg[v] = deg.get(v, 0) + 1
    if any(d < 2 for d in deg.values()):
        return
    try:
        bmesh.ops.holes_fill(bm, edges=cut_edges, sides=0)
        return
    except Exception:
        pass
    try:
        bmesh.ops.edgenet_fill(bm, edges=cut_edges)
    except Exception:
        pass


def slice_mesh(bm, plane_co, plane_no, keep_positive, dist=1e-6):
    geom = [*bm.verts, *bm.edges, *bm.faces]
    if not geom:
        return 0
    res = bmesh.ops.bisect_plane(
        bm, geom=geom, dist=dist,
        plane_co=plane_co, plane_no=plane_no,
        clear_outer=not keep_positive,
        clear_inner=keep_positive,
    )
    _cap(bm, [g for g in res.get("geom_cut", ()) if isinstance(g, bmesh.types.BMEdge)])
    return len(bm.faces)


def _progress_begin(context, total):
    try:
        context.window_manager.progress_begin(0, max(int(total), 1))
    except Exception:
        pass


def _progress_update(context, value):
    try:
        context.window_manager.progress_update(int(value))
    except Exception:
        pass


def _progress_end(context):
    try:
        context.window_manager.progress_end()
    except Exception:
        pass


def _select_only(context, pieces):
    if not pieces:
        return
    try:
        for o in context.selected_objects:
            o.select_set(False)
    except Exception:
        pass
    for p in pieces:
        try:
            p.select_set(True)
        except Exception:
            pass
    try:
        context.view_layer.objects.active = pieces[0]
    except Exception:
        pass


def run_grid_cut(context, obj, sx, sy, sz, hide_original=True, skin=False):
    src_bm, mats, flat = source_bmesh(context, obj, skin)
    lo_hi = bounds_of(src_bm)
    if lo_hi is None:
        src_bm.free()
        return []
    lo, hi = lo_hi
    eps = max((hi - lo).length * 1e-6, 1e-9)
    coll = piece_collection(obj, context)

    xs = [lo.x + (hi.x - lo.x) * i / sx for i in range(sx + 1)]
    ys = [lo.y + (hi.y - lo.y) * j / sy for j in range(sy + 1)]
    zs = [lo.z + (hi.z - lo.z) * k / sz for k in range(sz + 1)]

    axis_hits = [ax for ax, n in (("x", sx), ("y", sy), ("z", sz)) if n > 1]
    base = obj.name
    pieces = []
    total = sx * sy * sz
    done = 0
    _progress_begin(context, total)

    def finish_leaf(bm, i, j, k):
        nonlocal done
        done += 1
        _progress_update(context, done)
        if not bm.faces:
            bm.free()
            return
        cleanup_piece(bm, lo, hi, skin)
        if not bm.faces:
            bm.free()
            return
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        if len(axis_hits) == 1:
            idx = {"x": i, "y": j, "z": k}[axis_hits[0]]
            name = f"{base}_{axis_hits[0]}{idx + 1}"
        else:
            name = f"{base}_{i + 1}_{j + 1}_{k + 1}"
        pieces.append(new_piece(name, bm, obj, mats, coll, flat))
        bm.free()

    def recurse(bm, i0, i1, j0, j1, k0, k1):
        span, axis = max((i1 - i0, 0), (j1 - j0, 1), (k1 - k0, 2))
        if span == 0:
            finish_leaf(bm, i0, j0, k0)
            return
        if axis == 0:
            s = (i0 + i1) // 2
            bm_r = bm.copy()
            slice_mesh(bm, Vector((xs[s + 1], 0, 0)), Vector((1, 0, 0)), True, eps)
            slice_mesh(bm_r, Vector((xs[s + 1], 0, 0)), Vector((1, 0, 0)), False, eps)
            recurse(bm, s + 1, i1, j0, j1, k0, k1)
            recurse(bm_r, i0, s, j0, j1, k0, k1)
        elif axis == 1:
            s = (j0 + j1) // 2
            bm_r = bm.copy()
            slice_mesh(bm, Vector((0, ys[s + 1], 0)), Vector((0, 1, 0)), True, eps)
            slice_mesh(bm_r, Vector((0, ys[s + 1], 0)), Vector((0, 1, 0)), False, eps)
            recurse(bm, i0, i1, s + 1, j1, k0, k1)
            recurse(bm_r, i0, i1, j0, s, k0, k1)
        else:
            s = (k0 + k1) // 2
            bm_r = bm.copy()
            slice_mesh(bm, Vector((0, 0, zs[s + 1])), Vector((0, 0, 1)), True, eps)
            slice_mesh(bm_r, Vector((0, 0, zs[s + 1])), Vector((0, 0, 1)), False, eps)
            recurse(bm, i0, i1, j0, j1, s + 1, k1)
            recurse(bm_r, i0, i1, j0, j1, k0, s)

    try:
        recurse(src_bm, 0, sx - 1, 0, sy - 1, 0, sz - 1)
    finally:
        _progress_end(context)

    if hide_original and pieces:
        hide_object(obj)
    return pieces


def gen_seeds(bm, count, rng, min_sep):
    seeds = []
    bvh = BVHTree.FromBMesh(bm)
    lo, hi = bounds_of(bm)
    tries = 0
    limit = count * 200 + 500
    while len(seeds) < count and tries < limit:
        tries += 1
        p = Vector((rng.uniform(lo.x, hi.x),
                    rng.uniform(lo.y, hi.y),
                    rng.uniform(lo.z, hi.z)))
        loc, nor, _idx, _dist = bvh.find_nearest(p)
        if loc is None:
            continue

        if (p - loc).dot(nor) >= 0.0:
            continue
        if min_sep > 0.0 and any((p - q).length < min_sep for q in seeds):
            continue
        seeds.append(p)

    if len(seeds) < count:
        faces = list(bm.faces)
        if faces:
            inset = max((hi - lo).length * 0.01, 1e-6)
            guard = 0
            while len(seeds) < count and guard < count * 50:
                guard += 1
                face = faces[rng.randrange(len(faces))]
                p = face.calc_center_median() - face.normal * inset
                if min_sep > 0.0 and any((p - q).length < min_sep for q in seeds):
                    continue
                seeds.append(p)
    return seeds


def run_random_fracture(context, obj, count, seed=0, hide_original=True):
    src_bm, mats, flat = source_bmesh(context, obj)
    lo_hi = bounds_of(src_bm)
    if lo_hi is None:
        src_bm.free()
        return []
    lo, hi = lo_hi
    eps = max((hi - lo).length * 1e-6, 1e-9)
    coll = piece_collection(obj, context)

    rng = random.Random(seed) if seed else random.Random()
    seeds = gen_seeds(src_bm, count, rng, (hi - lo).length * 0.002)
    if len(seeds) < 2:
        src_bm.free()
        return []

    base = obj.name
    pieces = []
    total = len(seeds)
    _progress_begin(context, total)

    for i, pi in enumerate(seeds):
        _progress_update(context, i + 1)
        bm = src_bm.copy()

        order = sorted((j for j in range(len(seeds)) if j != i),
                       key=lambda j: (seeds[j] - pi).length)
        dead = False
        for j in order:
            d = seeds[j] - pi
            if d.length <= eps:
                continue
            mid = (pi + seeds[j]) * 0.5

            if not slice_mesh(bm, mid, d.normalized(), False, eps):
                dead = True
                break
        if dead or not bm.faces:
            bm.free()
            continue
        cleanup_piece(bm, lo, hi, False)
        if not bm.faces:
            bm.free()
            continue
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        pieces.append(new_piece(f"{base}_{i + 1:03d}", bm, obj, mats, coll, flat))
        bm.free()

    _progress_end(context)
    src_bm.free()

    if hide_original and pieces:
        hide_object(obj)
    return pieces


def remove_preview():
    obj = bpy.data.objects.get(PREVIEW_NAME)
    if obj is None or not obj.get(PREVIEW_FLAG):
        return
    me = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        return
    if me is not None and getattr(me, "users", 0) == 0:
        try:
            bpy.data.meshes.remove(me)
        except Exception:
            pass


def grid_line_coords(lo, hi, sx, sy, sz):
    xs = [lo.x + (hi.x - lo.x) * i / sx for i in range(sx + 1)]
    ys = [lo.y + (hi.y - lo.y) * j / sy for j in range(sy + 1)]
    zs = [lo.z + (hi.z - lo.z) * k / sz for k in range(sz + 1)]
    coords = []
    for j in range(sy + 1):
        for k in range(sz + 1):
            if j in (0, sy) or k in (0, sz):
                coords.append((xs[0], ys[j], zs[k]))
                coords.append((xs[-1], ys[j], zs[k]))
    for i in range(sx + 1):
        for k in range(sz + 1):
            if i in (0, sx) or k in (0, sz):
                coords.append((xs[i], ys[0], zs[k]))
                coords.append((xs[i], ys[-1], zs[k]))
    for i in range(sx + 1):
        for j in range(sy + 1):
            if i in (0, sx) or j in (0, sy):
                coords.append((xs[i], ys[j], zs[0]))
                coords.append((xs[i], ys[j], zs[-1]))
    return coords


def update_preview(context=None):
    try:
        ctx = context or bpy.context
        props = getattr(ctx.window_manager, WM_ATTR, None)
    except Exception:
        return
    if props is None or not props.show_preview:
        remove_preview()
        return
    try:
        target = target_object(ctx)
    except Exception:
        target = None
    if target is None:
        remove_preview()
        return
    try:
        if target.hide_get():
            remove_preview()
            return
    except Exception:
        pass

    if props.segx <= 1 and props.segy <= 1 and props.segz <= 1:
        remove_preview()
        return

    try:
        corners = [Vector(c) for c in target.bound_box]
        lo = Vector((min(c.x for c in corners),
                     min(c.y for c in corners),
                     min(c.z for c in corners)))
        hi = Vector((max(c.x for c in corners),
                     max(c.y for c in corners),
                     max(c.z for c in corners)))
        coords = grid_line_coords(lo, hi, props.segx, props.segy, props.segz)
        edges = [(i, i + 1) for i in range(0, len(coords), 2)]

        obj = bpy.data.objects.get(PREVIEW_NAME)
        if obj is None:
            me = bpy.data.meshes.new(PREVIEW_NAME)
            obj = bpy.data.objects.new(PREVIEW_NAME, me)
            obj[PREVIEW_FLAG] = True
            obj.hide_select = True
            obj.show_in_front = True
            obj.color = (1.0, 0.45, 0.1, 1.0)
            parent_coll = target.users_collection[0] if target.users_collection \
                else ctx.scene.collection
            parent_coll.objects.link(obj)
        else:
            me = obj.data
            me.clear_geometry()
        me.from_pydata(coords, edges, [])
        me.update()
        obj.matrix_world = target.matrix_world.copy()
    except Exception as exc:
        utils.report("WARNING", f"分割线预览刷新失败: {exc}")


def _on_setting_changed(self, context):
    update_preview(context)


class MF_PG_ShatterSettings(bpy.types.PropertyGroup):
    segx: IntProperty(name="X 分段", description="X 方向切成几段",
                      default=1, min=1, max=100,
                      update=_on_setting_changed)
    segy: IntProperty(name="Y 分段", description="Y 方向切成几段",
                      default=1, min=1, max=100,
                      update=_on_setting_changed)
    segz: IntProperty(name="Z 分段", description="Z 方向切成几段",
                      default=1, min=1, max=100,
                      update=_on_setting_changed)

    count: IntProperty(name="破碎数量", description="随机碎成几块",
                       default=10, min=2, max=1000)

    seed: IntProperty(name="随机种子", description="0 = 每次都不一样；填固定值可复现同一套碎块",
                      default=0, min=0, max=999999)

    hide_original: BoolProperty(name="隐藏原物体", default=True,
                                description="切完后把源物体藏起来")

    skin: BoolProperty(name="先加厚成实体", default=False, description=SKIN_DESC)

    show_preview: BoolProperty(name="预览分割线", default=False,
                               description="在物体包围盒上画出切割线",
                               update=_on_setting_changed)


class MF_OT_Shatter_Grid(bpy.types.Operator):
    bl_idname = GRID_OP_ID
    bl_label = "整齐切割"
    bl_description = "按包围盒把物体规则切成 X*Y*Z 块"
    bl_options = {'REGISTER', 'UNDO'}

    segx: IntProperty(name="X 分段", default=1, min=1, max=100)
    segy: IntProperty(name="Y 分段", default=1, min=1, max=100)
    segz: IntProperty(name="Z 分段", default=1, min=1, max=100)
    hide_original: BoolProperty(name="隐藏原物体", default=True)
    skin: BoolProperty(name="先加厚成实体", default=False, description=SKIN_DESC)

    def execute(self, context):
        obj = target_object(context)
        if obj is None:
            self.report({'WARNING'}, "请先选中一个网格物体")
            return {'CANCELLED'}
        if self.segx <= 1 and self.segy <= 1 and self.segz <= 1:
            self.report({'WARNING'}, "三个方向的分段都是 1，没有可切的内容")
            return {'CANCELLED'}

        remove_preview()
        start = time.perf_counter()

        props = getattr(context.window_manager, WM_ATTR, None)
        if props is not None:
            props.show_preview = False

        pieces = run_grid_cut(context, obj, self.segx, self.segy, self.segz,
                              self.hide_original, self.skin)
        if not pieces:
            self.report({'WARNING'}, "没有切出任何碎块（物体包围盒为空？）")
            return {'CANCELLED'}

        _select_only(context, pieces)
        cost = time.perf_counter() - start
        utils.report("INFO", f"整齐切割 {obj.name}：{self.segx}x{self.segy}x{self.segz} "
                             f"-> {len(pieces)} 块，耗时 {cost:.1f} 秒")
        self.report({'INFO'}, f"已切成 {len(pieces)} 块（{cost:.1f} 秒）")
        return {'FINISHED'}


class MF_OT_Shatter_Random(bpy.types.Operator):
    bl_idname = RANDOM_OP_ID
    bl_label = "随机破碎"
    bl_description = "在物体内部随机撒点，用中垂面切出 Voronoi 碎块"
    bl_options = {'REGISTER', 'UNDO'}

    count: IntProperty(name="破碎数量", default=10, min=2, max=1000)
    seed: IntProperty(name="随机种子", default=0, min=0, max=999999)
    hide_original: BoolProperty(name="隐藏原物体", default=True)

    def execute(self, context):
        obj = target_object(context)
        if obj is None:
            self.report({'WARNING'}, "请先选中一个网格物体")
            return {'CANCELLED'}
        if self.count > SHATTER_MAX_PARTS:
            self.report({'ERROR'},
                        f"破碎数量超过上限 {SHATTER_MAX_PARTS}（切面数是数量的平方，"
                        f"再大 Blender 会卡死）")
            return {'CANCELLED'}

        remove_preview()
        start = time.perf_counter()
        props = getattr(context.window_manager, WM_ATTR, None)
        if props is not None:
            props.show_preview = False

        pieces = run_random_fracture(context, obj, self.count, self.seed,
                                     self.hide_original)
        if not pieces:
            self.report({'WARNING'}, "没能生成碎块（物体太小或网格为空）")
            return {'CANCELLED'}

        _select_only(context, pieces)
        cost = time.perf_counter() - start
        utils.report("INFO", f"随机破碎 {obj.name}：目标 {self.count} 块 "
                             f"-> 实得 {len(pieces)} 块，耗时 {cost:.1f} 秒")
        self.report({'INFO'}, f"已碎成 {len(pieces)} 块（{cost:.1f} 秒）")
        return {'FINISHED'}


classes = (MF_PG_ShatterSettings, MF_OT_Shatter_Grid, MF_OT_Shatter_Random)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR, PointerProperty(type=MF_PG_ShatterSettings))


def unregister():
    remove_preview()
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
