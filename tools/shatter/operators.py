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


def _open_edges(bm):
    return [e for e in bm.edges if e.is_valid and len(e.link_faces) == 1]


def _open_at(v):
    return [e for e in v.link_edges if e.is_valid and len(e.link_faces) == 1]


def _walk_loop(start, used, allow=None):
    v0 = start.verts[0]
    verts = [v0]
    edges = [start]
    used.add(start)
    cur = start.verts[1]
    prev = start.verts[1].co - start.verts[0].co
    while cur is not v0:
        cands = [e for e in _open_at(cur)
                 if e not in used and (allow is None or allow(e))]
        if not cands:
            return None
        if len(cands) > 1:
            def straight(e):
                a, b = e.verts
                vec = (b.co - a.co) if a is cur else (a.co - b.co)
                return vec.normalized().dot(prev.normalized())
            nxt = max(cands, key=straight)
        else:
            nxt = cands[0]
        used.add(nxt)
        edges.append(nxt)
        verts.append(cur)
        a, b = nxt.verts
        other = b if a is cur else a
        prev = other.co - cur.co
        cur = other
    if len(verts) < 3:
        return None
    return verts, edges


def _loops_from(starts, allow=None):
    used = set()
    loops = []
    budget = 64 * len(starts) + 4096
    spent = 0
    for e0 in starts:
        if e0 in used:
            continue
        if spent > budget:
            break
        r = _walk_loop(e0, set(), allow)
        spent += len(r[1]) if r else 8
        if r is None:
            used.add(e0)
            continue
        used.update(r[1])
        loops.append(r)
    return loops


def _loop_normal(verts):
    n = Vector((0.0, 0.0, 0.0))
    for i in range(len(verts)):
        a = verts[i - 1].co
        b = verts[i].co
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    if n.length < 1e-12:
        return None
    n.normalize()
    return n


def _clip_ear(bm, verts, pts, idx):
    m = len(idx)
    best_k = -1
    best_hits = -1
    for k in range(m):
        i0 = idx[k - 1]
        i1 = idx[k]
        i2 = idx[(k + 1) % m]
        ax, ay = pts[i0]
        bx, by = pts[i1]
        cx, cy = pts[i2]
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 1e-12:
            continue
        chord = None
        for e in verts[i0].link_edges:
            if e.other_vert(verts[i0]) is verts[i2]:
                chord = e
                break
        if chord is not None and len(chord.link_faces) >= 2:
            continue
        lo_x = ax if ax < bx else bx
        if cx < lo_x:
            lo_x = cx
        hi_x = ax if ax > bx else bx
        if cx > hi_x:
            hi_x = cx
        lo_y = ay if ay < by else by
        if cy < lo_y:
            lo_y = cy
        hi_y = ay if ay > by else by
        if cy > hi_y:
            hi_y = cy
        hits = 0
        for j in idx:
            if j == i0 or j == i1 or j == i2:
                continue
            px, py = pts[j]
            if px < lo_x or px > hi_x or py < lo_y or py > hi_y:
                continue
            d1 = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
            d2 = (px - bx) * (cy - by) - (py - by) * (cx - bx)
            d3 = (px - cx) * (ay - cy) - (py - cy) * (ax - cx)
            if ((d1 >= 0 and d2 >= 0 and d3 >= 0)
                    or (d1 <= 0 and d2 <= 0 and d3 <= 0)):
                hits += 1
                if best_hits == 0:
                    break
        if best_hits < 0 or hits < best_hits:
            best_hits = hits
            best_k = k
            if hits == 0:
                break
    if best_k < 0:
        return None
    k = best_k
    try:
        bm.faces.new((verts[idx[k - 1]], verts[idx[k]], verts[idx[(k + 1) % m]]))
    except Exception:
        return None
    idx.pop(k)
    return 1


def _ear_fill(bm, verts):
    n = _loop_normal(verts)
    if n is None:
        return 0
    if abs(n.x) < 0.9:
        ux, uy, uz = 1.0, 0.0, 0.0
    else:
        ux, uy, uz = 0.0, 1.0, 0.0
    d = ux * n.x + uy * n.y + uz * n.z
    ux -= n.x * d
    uy -= n.y * d
    uz -= n.z * d
    ul = (ux * ux + uy * uy + uz * uz) ** 0.5
    if ul < 1e-9:
        return 0
    ux /= ul
    uy /= ul
    uz /= ul
    vx = n.y * uz - n.z * uy
    vy = n.z * ux - n.x * uz
    vz = n.x * uy - n.y * ux
    pts = []
    for x in verts:
        c = x.co
        pts.append((c.x * ux + c.y * uy + c.z * uz,
                    c.x * vx + c.y * vy + c.z * vz))
    idx = [i for i in range(len(pts))
           if i == 0 or pts[i] != pts[i - 1]]
    if len(idx) < 3:
        return 0
    area = 0.0
    m = len(idx)
    for k in range(m):
        x0, y0 = pts[idx[k - 1]]
        x1, y1 = pts[idx[k]]
        area += x0 * y1 - x1 * y0
    if area < 0:
        idx.reverse()
    made = 0
    guard = 0
    while len(idx) > 3 and guard < 4 * m + 32:
        guard += 1
        if _clip_ear(bm, verts, pts, idx) is None:
            break
        made += 1
    if len(idx) == 3:
        try:
            bm.faces.new((verts[idx[0]], verts[idx[1]], verts[idx[2]]))
            made += 1
        except Exception:
            pass
    return made


def _sweep_debris(bm):
    wire_e = [e for e in bm.edges if not e.link_faces]
    if wire_e:
        bmesh.ops.delete(bm, geom=wire_e, context='EDGES')
    loose_v = [v for v in bm.verts if not v.link_edges]
    if loose_v:
        bmesh.ops.delete(bm, geom=loose_v, context='VERTS')


def _remove_flaps(bm):
    removed = 0
    for _ in range(4):
        doomed = set()
        for f in bm.faces:
            opens = [e for e in f.edges if len(e.link_faces) == 1]
            if len(opens) < 2:
                continue
            rest = [e for e in f.edges if len(e.link_faces) != 1]
            if not rest:
                continue
            if not all(len(e.link_faces) >= 2 for e in rest):
                continue
            doomed.add(f)
        if not doomed:
            break
        bmesh.ops.delete(bm, geom=list(doomed), context='FACES_ONLY')
        removed += len(doomed)
        _sweep_debris(bm)
    return removed


def _fill_loop(bm, verts, edges):
    if len(verts) < 3 or len(edges) < 3:
        return 0
    for e in edges:
        if len(e.link_faces) >= 2:
            return 0
    faces = set()
    for e in edges:
        faces.update(e.link_faces)
    if len(faces) == 1 and len(faces.pop().verts) == len(verts):
        return 0
    try:
        res = bmesh.ops.holes_fill(bm, edges=list(edges), sides=0)
        made = len(res.get("faces", []))
        if made:
            return made
    except Exception:
        pass
    n = _loop_normal(verts)
    if n is None:
        return 0
    dmax = max(abs((x.co - verts[0].co).dot(n)) for x in verts)
    if dmax > 1e-6:
        return _ear_fill(bm, verts)
    try:
        bm.faces.new(tuple(verts))
        return 1
    except Exception:
        return _ear_fill(bm, verts)


def _cap(bm, edges=None):
    made = 0
    for _ in range(8):
        if edges:
            starts = [e for e in edges if e.is_valid and len(e.link_faces) == 1]
        else:
            starts = _open_edges(bm)
        if not starts:
            break
        n = 0
        for verts, ledges in _loops_from(starts):
            n += _fill_loop(bm, verts, ledges)
        if n == 0:
            break
        made += n
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


def cleanup_piece(bm, lo, hi, do_sliver=False, open_shell=False):
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
        hole_e = [e for e in bm.edges
                  if len(e.link_faces) < 2
                  and e.verts[0] in base and e.verts[1] in base]
        if hole_e:
            _cap(bm, hole_e)
        removed += len(doomed)
    _sweep_debris(bm)
    if not open_shell:
        # 开放壳（Revit 组合体、玻璃等）的面本来就带多条开放边，
        # 翘片清理会把整个边带吃掉，全面补盖会把玻璃/开口封上垃圾面
        _remove_flaps(bm)
        if _open_edges(bm):
            _cap(bm)
        for w in (diag * 1e-4, diag * 1e-3, diag * 2e-3, diag * 4e-3):
            open_e = _open_edges(bm)
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
            if _open_edges(bm):
                _cap(bm)
    try:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=WELD_DIST)
    except Exception:
        pass
    _sweep_debris(bm)
    book_e = [e for e in bm.edges if len(e.link_faces) > 2]
    if book_e:
        try:
            bmesh.ops.split_edges(bm, edges=book_e)
        except Exception:
            pass
    return removed


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


_AXIS_NORMALS = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))

_LAYER_KINDS = ("float", "int", "bool", "string", "float_vector", "float_color", "color")


def _cap_planar(bm, edges, axis=None, c=None, eps=0.0):
    """平面环专用补盖。faces.new 是 O(1)，holes_fill 是 O(总面数)，
    大网格上逐环补盖必须走 faces.new，否则补面开销随整网规模爆炸。
    allow 把游走限制在同一切割平面内：开放壳（玻璃/边带）的开放边
    不在同一平面上，游走不会跳上去拉出跨平面垃圾盖。"""
    made = 0
    starts = [e for e in edges if e.is_valid and len(e.link_faces) == 1]
    allow = None
    if axis is not None:
        def allow(e):
            a, b = e.verts
            return abs(a.co[axis] - c) <= eps and abs(b.co[axis] - c) <= eps
    for verts, ledges in _loops_from(starts, allow):
        if len(verts) < 3 or len(ledges) < 3:
            continue
        ok = True
        faces = set()
        for e in ledges:
            if len(e.link_faces) != 1:
                ok = False
                break
            faces.update(e.link_faces)
        if ok and len(faces) == 1 and len(faces.pop().verts) == len(verts):
            continue  # 单面环（如平片），补了会糊重面
        try:
            bm.faces.new(tuple(verts))
            made += 1
        except Exception:
            try:
                res = bmesh.ops.holes_fill(bm, edges=list(ledges), sides=0)
                made += len(res.get("faces", []))
            except Exception:
                pass
    return made


def _split_components(bm):
    """按边连通性把面分成互不相连的组（split_edges 之后每组就是一块碎块）"""
    seen = set()
    groups = []
    for f in bm.faces:
        if f in seen:
            continue
        stack = [f]
        seen.add(f)
        group = []
        while stack:
            cur = stack.pop()
            group.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf not in seen:
                        seen.add(nf)
                        stack.append(nf)
        groups.append(group)
    return groups


def _mirror_layers(src_bm, dst_bm, vmap, emap, fmap, loop_pairs, has_vg=False):
    """把源网格的自定义数据层（UV / 顶点色 / 权重等）镜像到碎块上"""
    for sdom, ddom, mapping in (
            (src_bm.verts, dst_bm.verts, vmap),
            (src_bm.edges, dst_bm.edges, emap),
            (src_bm.faces, dst_bm.faces, fmap),
    ):
        for kind in _LAYER_KINDS:
            try:
                slayers = getattr(sdom.layers, kind)
                dlayers = getattr(ddom.layers, kind)
                for name in slayers.keys():
                    sk = slayers[name]
                    dk = dlayers[name] if name in dlayers.keys() else dlayers.new(name)
                    for se, de in mapping.items():
                        de[dk] = se[sk]
            except Exception:
                continue
    if has_vg:
        try:
            sk = src_bm.verts.layers.deform.verify()
            dk = dst_bm.verts.layers.deform.verify()
            for sv, dv in vmap.items():
                d = dv[dk]
                d.clear()
                for g, w in dict(sv[sk]).items():
                    d[g] = w
        except Exception:
            pass
    for kind in ("uv",) + _LAYER_KINDS:
        try:
            slayers = getattr(src_bm.loops.layers, kind)
            dlayers = getattr(dst_bm.loops.layers, kind)
            for name in slayers.keys():
                sk = slayers[name]
                dk = dlayers[name] if name in dlayers.keys() else dlayers.new(name)
                for sl, nl in loop_pairs:
                    nl[dk] = sl[sk]
        except Exception:
            continue


def _piece_bmesh(group, src_bm, has_vg=False):
    """把一个连通体复制成独立 bmesh（保留平滑标记、材质槽与自定义数据层）"""
    out = bmesh.new()
    if has_vg:
        # deform 层必须在建顶点前 verify，否则顶点包装对象会失效
        out.verts.layers.deform.verify()
    vmap = {}
    emap = {}
    fmap = []
    loop_pairs = []
    for f in group:
        vs = []
        for v in f.verts:
            nv = vmap.get(v)
            if nv is None:
                nv = out.verts.new(v.co)
                vmap[v] = nv
            vs.append(nv)
        try:
            nf = out.faces.new(vs)
        except ValueError:
            continue
        nf.smooth = f.smooth
        nf.material_index = f.material_index
        fmap.append((f, nf))
        for se, de in zip(f.edges, nf.edges):
            emap[se] = de
    for sf, nf in fmap:
        lut = {nl.vert: nl for nl in nf.loops}
        for sl in sf.loops:
            nl = lut.get(vmap[sl.vert])
            if nl is not None:
                loop_pairs.append((sl, nl))
    _mirror_layers(src_bm, out, vmap, emap, dict(fmap), loop_pairs, has_vg)
    out.normal_update()
    return out


def _restore_vg_names(src_obj, piece):
    """bmesh 的 deform 层不带组名映射，按源物体顺序补建同名顶点组"""
    for g in src_obj.vertex_groups:
        piece.vertex_groups.new(name=g.name)


def _cell_of(group, lo, hi, sx, sy, sz):
    """按碎块顶点均值判断它属于哪个格子（碎块不会跨格）"""
    acc = Vector((0.0, 0.0, 0.0))
    n = 0
    for f in group:
        for v in f.verts:
            acc += v.co
            n += 1
    idx = []
    for axis, m in ((0, sx), (1, sy), (2, sz)):
        span = hi[axis] - lo[axis]
        if span <= 0.0 or m <= 1 or n == 0:
            idx.append(0)
        else:
            k = int((acc[axis] / n - lo[axis]) / span * m)
            idx.append(min(m - 1, max(0, k)))
    return tuple(idx)


def run_grid_cut(context, obj, sx, sy, sz, hide_original=True, skin=False):
    """整齐切割：逐平面切-断-补 -> 连通体分块，替代旧的二分递归整网复制"""
    src_bm, mats, flat = source_bmesh(context, obj, skin)
    lo_hi = bounds_of(src_bm)
    if lo_hi is None:
        src_bm.free()
        return [], {"closed": 0, "open": 0}
    lo, hi = lo_hi
    eps = max((hi - lo).length * 1e-6, 1e-9)
    coll = piece_collection(obj, context)

    axis_hits = [ax for ax, n in (("x", sx), ("y", sy), ("z", sz)) if n > 1]
    base = obj.name
    stats = {"closed": 0, "open": 0}
    has_vg = bool(obj.vertex_groups)
    # 源网格带开放边（组合体/玻璃/片状物）时，碎块保留源有破洞，
    # 只保证切割处补盖，不做翘片清理和全面封盖
    src_open = open_edges(src_bm) > 0

    total = 0
    for n, axis in ((sx, 0), (sy, 1), (sz, 2)):
        if n > 1 and hi[axis] > lo[axis]:
            total += n - 1

    # 逐平面：切一刀 -> 断开切割边 -> 立刻补这一刀的平面盖。
    # 后续平面的切割会自然把之前的盖切成每格一块的平面碎片，
    # 所以每个格子的盖都是平面盖，体积与旧版一致。
    # 每轴开切前只扫一遍既有边分桶（O(E)/轴）；每刀的新切割边直接用
    # bisect 返回的 geom_cut、开放边直接用 split_edges 的返回值，
    # 全程不做 O(E)*平面数 的重复扫描。
    _progress_begin(context, max(total, 1))
    done = 0
    try:
        for axis, n in ((0, sx), (1, sy), (2, sz)):
            if n <= 1 or hi[axis] <= lo[axis]:
                continue
            a0 = lo[axis]
            step = (hi[axis] - lo[axis]) / n
            bucket = {}
            for e in src_bm.edges:
                fa = (e.verts[0].co[axis] - a0) / step
                ia = int(fa + 0.5)
                if ia < 1 or ia >= n or abs(fa - ia) * step > eps:
                    continue
                fb = (e.verts[1].co[axis] - a0) / step
                if int(fb + 0.5) != ia or abs(fb - ia) * step > eps:
                    continue
                bucket.setdefault(ia, []).append(e)
            for k in range(1, n):
                done += 1
                _progress_update(context, done)
                c = a0 + k * step
                co = Vector((0.0, 0.0, 0.0))
                co[axis] = c
                geom = [*src_bm.verts, *src_bm.edges, *src_bm.faces]
                res = bmesh.ops.bisect_plane(
                    src_bm, geom=geom, dist=eps, plane_co=co,
                    plane_no=_AXIS_NORMALS[axis],
                    clear_inner=False, clear_outer=False)
                cut = [g for g in res.get("geom_cut", ())
                       if isinstance(g, bmesh.types.BMEdge)
                       and abs(g.verts[0].co[axis] - c) <= eps
                       and abs(g.verts[1].co[axis] - c) <= eps]
                pre = [e for e in bucket.get(k, ()) if e.is_valid]
                if pre:
                    cut = list(dict.fromkeys(cut + pre))
                if not cut:
                    continue
                ret = bmesh.ops.split_edges(src_bm, edges=cut)
                open_e = [e for e in ret.get("edges", ())
                          if e.is_valid and len(e.link_faces) == 1]
                if open_e:
                    _cap_planar(src_bm, open_e, axis, c, eps)
    finally:
        _progress_end(context)

    cells = {}
    for g in _split_components(src_bm):
        # 多壳组合体（Revit 导入件等）一个格子里有大量互不相连的壳片，
        # 按旧版语义它们同属一个格子 = 一块碎块，不能拆成独立物体
        cells.setdefault(_cell_of(g, lo, hi, sx, sy, sz), []).extend(g)

    pieces = []
    total = len(cells)
    _progress_begin(context, max(total, 1))
    try:
        for done, cell in enumerate(sorted(cells)):
            _progress_update(context, done + 1)
            bm = _piece_bmesh(cells[cell], src_bm, has_vg)
            if not bm.faces:
                bm.free()
                continue
            cleanup_piece(bm, lo, hi, skin, src_open)
            if not bm.faces:
                bm.free()
                continue
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            if _open_edges(bm):
                stats["open"] += 1
            else:
                stats["closed"] += 1
            i, j, k = cell
            if len(axis_hits) == 1:
                idx = {"x": i, "y": j, "z": k}[axis_hits[0]]
                name = f"{base}_{axis_hits[0]}{idx + 1}"
            else:
                name = f"{base}_{i + 1}_{j + 1}_{k + 1}"
            piece = new_piece(name, bm, obj, mats, coll, flat)
            if has_vg:
                _restore_vg_names(obj, piece)
            pieces.append(piece)
            bm.free()
    finally:
        _progress_end(context)
        src_bm.free()

    if hide_original and pieces:
        hide_object(obj)
    return pieces, stats


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
        return [], {"closed": 0, "open": 0}
    lo, hi = lo_hi
    eps = max((hi - lo).length * 1e-6, 1e-9)
    coll = piece_collection(obj, context)

    rng = random.Random(seed) if seed else random.Random()
    seeds = gen_seeds(src_bm, count, rng, (hi - lo).length * 0.002)
    if len(seeds) < 2:
        src_bm.free()
        return [], {"closed": 0, "open": 0}

    base = obj.name
    pieces = []
    stats = {"closed": 0, "open": 0}
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
        if _open_edges(bm):
            stats["open"] += 1
        else:
            stats["closed"] += 1
        pieces.append(new_piece(f"{base}_{i + 1:03d}", bm, obj, mats, coll, flat))
        bm.free()

    _progress_end(context)
    src_bm.free()

    if hide_original and pieces:
        hide_object(obj)
    return pieces, stats


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

        pieces, stats = run_grid_cut(context, obj, self.segx, self.segy, self.segz,
                                     self.hide_original, self.skin)
        if not pieces:
            self.report({'WARNING'}, "没有切出任何碎块（物体包围盒为空？）")
            return {'CANCELLED'}

        _select_only(context, pieces)
        cost = time.perf_counter() - start
        utils.report("INFO", f"整齐切割 {obj.name}：{self.segx}x{self.segy}x{self.segz} "
                             f"-> {len(pieces)} 块，耗时 {cost:.1f} 秒")
        msg = f"已切成 {len(pieces)} 块（{cost:.1f} 秒）"
        if stats["open"]:
            msg += f"，{stats['open']} 块仍有开放边（可开启『先加厚成实体』）"
        self.report({'INFO'}, msg)
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

        pieces, stats = run_random_fracture(context, obj, self.count, self.seed,
                                            self.hide_original)
        if not pieces:
            self.report({'WARNING'}, "没能生成碎块（物体太小或网格为空）")
            return {'CANCELLED'}

        _select_only(context, pieces)
        cost = time.perf_counter() - start
        utils.report("INFO", f"随机破碎 {obj.name}：目标 {self.count} 块 "
                             f"-> 实得 {len(pieces)} 块，耗时 {cost:.1f} 秒")
        msg = f"已碎成 {len(pieces)} 块（{cost:.1f} 秒）"
        if stats["open"]:
            msg += f"，{stats['open']} 块仍有开放边（可开启『先加厚成实体』）"
        self.report({'INFO'}, msg)
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
