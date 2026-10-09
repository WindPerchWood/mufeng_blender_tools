import math

import bmesh
from mathutils import Vector

CLASS_PREFIX = "MC_"
ID_PREFIX = "mf."
PANEL_CATEGORY = "模型体检"
SCENE_PROP = "meshcheck"

FLIP = "flip"
NONMANIFOLD = "nonmanifold"
OVERLAP = "overlap"

KINDS = (FLIP, NONMANIFOLD, OVERLAP)

ST_EMPTY = "EMPTY"
ST_OK = "OK"
ST_WHOLE_INWARD = "WHOLE_INWARD"
ST_SKIPPED_OPEN = "SKIPPED_OPEN"
ST_PARTIAL_OPEN = "PARTIAL_OPEN"

DEFAULT_OPTS = {
    "check_flip": True,
    "check_nonmanifold": True,
    "check_overlap": True,
    "flip_on_open": False,
    "overlap_tolerance": 1e-4,
    "max_markers": 500,
}

_TOL_FLOOR = 1e-9

def normalize_opts(opts):
    out = dict(DEFAULT_OPTS)
    if opts:
        for key in DEFAULT_OPTS:
            value = opts.get(key, None)
            if value is not None:
                out[key] = value

    try:
        tol = float(out["overlap_tolerance"])
    except (TypeError, ValueError):
        tol = DEFAULT_OPTS["overlap_tolerance"]
    out["overlap_tolerance"] = max(_TOL_FLOOR, tol)

    try:
        cap = int(out["max_markers"])
    except (TypeError, ValueError):
        cap = DEFAULT_OPTS["max_markers"]
    out["max_markers"] = max(0, cap)

    for key in ("check_flip", "check_nonmanifold", "check_overlap", "flip_on_open"):
        out[key] = bool(out[key])

    return out

def _limit(points, cap):
    total = len(points)
    if cap and total > cap:
        return points[:cap], total
    return list(points), total

def signed_volume(bm):


    total = 0.0
    for face in bm.faces:
        verts = face.verts
        count = len(verts)
        if count < 3:
            continue
        origin = verts[0].co
        for i in range(1, count - 1):
            try:
                total += origin.dot(verts[i].co.cross(verts[i + 1].co))
            except (AttributeError, ValueError):
                continue
    return total / 6.0

def count_edges_by_faces(bm):
    wire, boundary, multi = [], [], []
    for edge in bm.edges:
        n = len(edge.link_faces)
        if n == 0:
            wire.append(edge)
        elif n == 1:
            boundary.append(edge)
        elif n > 2:
            multi.append(edge)
    return wire, boundary, multi

def is_closed(bm):
    if len(bm.edges) == 0 or len(bm.faces) == 0:
        return False
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            return False
    return True

def surface_diagonal(bm):
    if len(bm.verts) == 0:
        return 0.0
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for vert in bm.verts:
        co = vert.co
        for i in range(3):
            if co[i] < lo[i]:
                lo[i] = co[i]
            if co[i] > hi[i]:
                hi[i] = co[i]
    if lo[0] == float("inf"):
        return 0.0
    return math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))

def _faces_on_inconsistent_edges(bm):


    suspects = set()
    for edge in bm.edges:
        if len(edge.link_faces) == 2 and not edge.is_contiguous:
            suspects.update(edge.link_faces)
    return suspects

def find_flipped(bm, closed, flip_on_open=False, max_markers=500):


    faces = list(bm.faces)
    if not faces:
        return ST_EMPTY, []

    if not closed:
        if not flip_on_open:
            return ST_SKIPPED_OPEN, []

        suspects = _faces_on_inconsistent_edges(bm)
        return ST_PARTIAL_OPEN, sorted(suspects, key=lambda f: f.index)

    volume = signed_volume(bm)
    inward = volume < 0.0

    reference = bm.copy()
    try:
        bmesh.ops.recalc_face_normals(reference, faces=list(reference.faces))
        reference.faces.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        if len(reference.faces) != len(faces):

            suspects = _faces_on_inconsistent_edges(bm)
            return (ST_WHOLE_INWARD if inward else ST_OK), sorted(suspects, key=lambda f: f.index)

        flipped = []
        for face, ref in zip(faces, reference.faces):
            try:
                if face.normal.dot(ref.normal) < 0.0:
                    flipped.append(face)
            except (AttributeError, ValueError):
                continue
    finally:
        reference.free()

    return (ST_WHOLE_INWARD if inward else ST_OK), flipped

def find_nonmanifold(bm, max_markers=500):
    wire, boundary, multi = count_edges_by_faces(bm)

    bad_verts = []
    loose_verts = []
    for vert in bm.verts:
        if len(vert.link_edges) == 0:
            loose_verts.append(vert)
        elif len(vert.link_faces) > 0 and not vert.is_manifold:


            bad_verts.append(vert)

    positions = []
    for edge in wire:
        positions.append((edge.verts[0].co + edge.verts[1].co) / 2.0)
    for edge in boundary:
        positions.append((edge.verts[0].co + edge.verts[1].co) / 2.0)
    for edge in multi:
        positions.append((edge.verts[0].co + edge.verts[1].co) / 2.0)
    for vert in bad_verts:
        positions.append(Vector(vert.co))
    for vert in loose_verts:
        positions.append(Vector(vert.co))

    edge_total = len(wire) + len(boundary) + len(multi)
    return {
        "count": edge_total,
        "wire": len(wire),
        "boundary": len(boundary),
        "multi": len(multi),
        "bad_verts": len(bad_verts),
        "loose_verts": len(loose_verts),
        "positions": positions,
    }

def face_signature(coords, tolerance):


    if len(coords) < 3:
        return None
    inverse = 1.0 / tolerance
    quantized = []
    for co in coords:
        try:
            quantized.append((
                int(round(co[0] * inverse)),
                int(round(co[1] * inverse)),
                int(round(co[2] * inverse)),
            ))
        except (TypeError, ValueError, IndexError):
            return None
    quantized.sort()
    return tuple(quantized)

def find_overlap(bm, tolerance, max_markers=500):


    buckets = {}
    for face in bm.faces:
        coords = [tuple(v.co) for v in face.verts]
        key = face_signature(coords, tolerance)
        if key is None:
            continue
        buckets.setdefault(key, []).append(face)

    groups = []
    involved = 0
    for faces in buckets.values():
        if len(faces) < 2:
            continue
        involved += len(faces)
        center = Vector((0.0, 0.0, 0.0))
        for face in faces:
            center += face.calc_center_median()
        center /= float(len(faces))
        groups.append((center, len(faces)))

    groups.sort(key=lambda item: (-item[1], item[0].x, item[0].y, item[0].z))
    return {"groups": len(groups), "count": involved, "positions": [g[0] for g in groups]}

def _blank(kind):
    return {
        "count": 0,
        "status": ST_EMPTY if kind == FLIP else "",
        "note": "",
        "positions": [],
        "markers": 0,
        "markers_total": 0,
    }

def analyze_bmesh(bm, matrix=None, opts=None, max_markers=None):


    cfg = normalize_opts(opts)
    if max_markers is not None:
        cfg["max_markers"] = max(0, int(max_markers))

    bm.normal_update()
    wire, boundary, multi = count_edges_by_faces(bm)
    closed = is_closed(bm)

    report = {
        "verts": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "closed": closed,
        "diagonal": surface_diagonal(bm),
        "warnings": [],
        FLIP: _blank(FLIP),
        NONMANIFOLD: _blank(NONMANIFOLD),
        OVERLAP: _blank(OVERLAP),
    }


    if cfg["check_flip"]:
        status, faces = find_flipped(bm, closed, cfg["flip_on_open"], cfg["max_markers"])
        note = ""
        if status == ST_SKIPPED_OPEN:
            note = "开放网格，已跳过反转法线检测"
        elif status == ST_WHOLE_INWARD:
            note = "整体法线朝内，全部面的朝向都反了"
        elif status == ST_PARTIAL_OPEN:
            note = "开放网格，仅报出法向互相矛盾的面"
        points = [face.calc_center_median() for face in faces]
        limited, total = _limit(points, cfg["max_markers"])
        report[FLIP] = {
            "count": len(faces),
            "status": status,
            "note": note,
            "positions": limited,
            "markers": len(limited),
            "markers_total": total,
        }


    if cfg["check_nonmanifold"]:
        data = find_nonmanifold(bm, cfg["max_markers"])
        limited, total = _limit(data["positions"], cfg["max_markers"])
        note = ""
        if data["count"]:
            parts = []
            if data["wire"]:
                parts.append("悬空线 %d" % data["wire"])
            if data["boundary"]:
                parts.append("边界/破洞 %d" % data["boundary"])
            if data["multi"]:
                parts.append("多面共边 %d" % data["multi"])
            note = "、".join(parts)
        report[NONMANIFOLD] = {
            "count": data["count"],
            "status": "",
            "note": note,
            "wire": data["wire"],
            "boundary": data["boundary"],
            "multi": data["multi"],
            "bad_verts": data["bad_verts"],
            "loose_verts": data["loose_verts"],
            "positions": limited,
            "markers": len(limited),
            "markers_total": total,
        }


    if cfg["check_overlap"]:
        data = find_overlap(bm, cfg["overlap_tolerance"], cfg["max_markers"])
        limited, total = _limit(data["positions"], cfg["max_markers"])
        note = ""
        if data["count"]:
            note = "%d 组，共 %d 个面完全重合" % (data["groups"], data["count"])
        report[OVERLAP] = {
            "count": data["count"],
            "status": "",
            "note": note,
            "groups": data["groups"],
            "positions": limited,
            "markers": len(limited),
            "markers_total": total,
        }

    if not closed:
        report["warnings"].append("网格不是封闭的（存在边界边），反转法线只做有限判定")


    if matrix is not None:
        for kind in KINDS:
            report[kind]["positions"] = [
                matrix @ Vector(point) for point in report[kind]["positions"]
            ]

    return report

def analyze_mesh(mesh, matrix=None, opts=None):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return analyze_bmesh(bm, matrix=matrix, opts=opts)
    finally:
        bm.free()

def merge_reports(reports):
    merged = {
        "objects": len(reports),
        "verts": 0,
        "edges": 0,
        "faces": 0,
        "all_closed": True,
        "warnings": [],
        FLIP: _blank(FLIP),
        NONMANIFOLD: _blank(NONMANIFOLD),
        OVERLAP: _blank(OVERLAP),
    }
    merged[FLIP].pop("status", None)
    for kind in KINDS:
        merged[kind]["markers_total"] = 0
    for key in ("wire", "boundary", "multi", "bad_verts", "loose_verts"):
        merged[NONMANIFOLD][key] = 0
    merged[OVERLAP]["groups"] = 0

    notes = {kind: [] for kind in KINDS}

    for rep in reports:
        merged["verts"] += rep["verts"]
        merged["edges"] += rep["edges"]
        merged["faces"] += rep["faces"]
        merged["all_closed"] = merged["all_closed"] and rep["closed"]
        for warning in rep.get("warnings", []):
            if warning not in merged["warnings"]:
                merged["warnings"].append(warning)

        for kind in KINDS:
            merged[kind]["count"] += rep[kind]["count"]
            merged[kind]["positions"].extend(rep[kind]["positions"])
            merged[kind]["markers_total"] += rep[kind]["markers_total"]

        for key in ("wire", "boundary", "multi", "bad_verts", "loose_verts"):
            merged[NONMANIFOLD][key] += rep[NONMANIFOLD].get(key, 0)
        merged[OVERLAP]["groups"] += rep[OVERLAP].get("groups", 0)

    for kind in KINDS:
        merged[kind]["markers"] = len(merged[kind]["positions"])


    statuses = []
    for rep in reports:
        flip = rep[FLIP]
        note = flip.get("note") or ""
        status = flip.get("status")
        if note and note not in notes[FLIP]:
            notes[FLIP].append(note)
        if status and status not in statuses:
            statuses.append(status)
    for kind in (NONMANIFOLD, OVERLAP):
        for rep in reports:
            note = rep[kind].get("note") or ""
            if note and note not in notes[kind]:
                notes[kind].append(note)

    merged[FLIP]["status"] = statuses[0] if statuses else ST_OK
    merged[FLIP]["note"] = "；".join(notes[FLIP])
    merged[NONMANIFOLD]["note"] = "；".join(notes[NONMANIFOLD])
    merged[OVERLAP]["note"] = "；".join(notes[OVERLAP])
    return merged

