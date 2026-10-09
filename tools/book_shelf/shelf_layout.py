import math

from mathutils import Vector, Matrix

from .geometry import line_intersect, angle_between, get_pivot, set_pivot, xform_point
from .row_fill import make_row, flatten


def face_world_verts(obj, face):
    mw = obj.matrix_world
    return [mw @ obj.data.vertices[i].co.copy() for i in face.vertices]


def face_world_normal(obj, face):
    mw = obj.matrix_world
    n = mw.to_3x3().inverted_safe().transposed() @ face.normal
    if n.length_squared < 1e-12:
        return Vector((0.0, 0.0, 1.0))
    return n.normalized()


def reference_dir(obj, axis):
    if axis == 'X':
        return Vector((0.0, 1.0, 0.0))
    if axis == 'Y':
        return Vector((1.0, 0.0, 0.0))
    wy = obj.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))
    if wy.length_squared < 1e-12:
        wy = Vector((0.0, 1.0, 0.0))
    return wy


def board_frame(obj, face, axis='AUTO'):
    verts = face_world_verts(obj, face)
    n = len(verts)
    if n < 3:
        return None

    center = Vector((0.0, 0.0, 0.0))
    for v in verts:
        center += v
    center = center / float(n)

    wy = reference_dir(obj, axis)
    w2 = Vector((wy.x, wy.y))
    if w2.length_squared < 1e-12:
        w2 = Vector((0.0, 1.0))
    w2 = w2.normalized()
    c2 = Vector((center.x, center.y))

    crossings = []
    for k in range(n):
        i1 = k
        i2 = (k + 1) % n
        a1 = Vector((verts[i1].x, verts[i1].y)) - c2
        a2 = Vector((verts[i2].x, verts[i2].y)) - c2
        cross_a = a1.x * w2.y - a1.y * w2.x
        cross_b = a2.x * w2.y - a2.y * w2.x
        if (cross_a * cross_b) < 1e-5:
            if cross_a >= 0.0:
                crossings.append((i1, i2))
            else:
                crossings.append((i2, i1))
    if not crossings:
        return None

    ray_a = (c2.x, c2.y)
    ray_b = (c2.x + w2.x, c2.y + w2.y)

    def _inter(i1, i2):
        return line_intersect(ray_a, ray_b,
                              (verts[i1].x, verts[i1].y),
                              (verts[i2].x, verts[i2].y))

    pi0 = _inter(*crossings[0])
    if pi0 is None:
        return None
    w3 = Vector((w2.x, w2.y, 0.0))
    best = 0
    best_ang = angle_between(w3, Vector((pi0[0] - c2.x, pi0[1] - c2.y, 0.0)))
    for t in range(1, len(crossings)):
        pit = _inter(*crossings[t])
        if pit is None:
            continue
        a = angle_between(w3, Vector((pit[0] - c2.x, pit[1] - c2.y, 0.0)))
        if a < best_ang:
            best_ang = a
            best = t

    idx_a, idx_b = crossings[best]
    p_start = verts[idx_a].copy()
    p_x = verts[idx_b] - p_start
    normal = face_world_normal(obj, face)
    cross = p_x.cross(normal)
    if cross.length_squared < 1e-12:
        return None

    other_idx = None
    for k in range(n):
        i1 = k
        i2 = (k + 1) % n
        if i1 == idx_a and i2 != idx_b:
            other_idx = i2
            break
        if i2 == idx_a and i1 != idx_b:
            other_idx = i1
            break

    if other_idx is None:
        p_y = cross
    else:
        wz = verts[other_idx] - p_start
        if math.degrees(angle_between(wz, cross)) < 90.0:
            p_y = cross
        else:
            p_y = -cross

    return (p_start, p_x, p_y, normal)


def board_matrix(frame):
    _p1, p_x, _p_y, nrm = frame
    nx = p_x.normalized()
    nz = nrm.normalized()
    if abs(nx.dot(nz)) > 1e-6:
        nx = (nx - nz * nx.dot(nz))
        if nx.length_squared < 1e-12:
            nx = Vector((1.0, 0.0, 0.0))
        nx = nx.normalized()
    ny = nz.cross(nx)
    if ny.length_squared < 1e-12:
        ny = Vector((0.0, 1.0, 0.0))
    ny = ny.normalized()
    nx = ny.cross(nz).normalized()
    r3 = Matrix((nx, ny, nz)).transposed()
    return r3.to_4x4()


def arrange_on_shelves(s, shelf_obj, face_indices, srcs_by_h, srcs_by_t,
                       rnd, tol, make, progress=None):
    rows = []
    mesh = shelf_obj.data
    n = len(face_indices)
    if n == 0:
        return rows

    for fi, fidx in enumerate(face_indices):
        if fidx < 0 or fidx >= len(mesh.polygons):
            continue
        face = mesh.polygons[fidx]
        frame = board_frame(shelf_obj, face, s.row_axis)
        if frame is None:
            continue
        p1, p_x, p_y, _nrm = frame
        length = p_x.length
        if length <= 1e-9:
            continue

        def _sub(f, _fi=fi):
            if progress is not None:
                progress((float(_fi) + min(1.0, max(0.0, f))) / float(n))

        row = make_row(s, srcs_by_h, srcs_by_t, length, rnd, tol, make, _sub)
        if not row:
            continue

        R = board_matrix(frame)
        M = Matrix.Translation(p1) @ R
        for o in flatten(row):
            o.matrix_world = M @ o.matrix_world
            set_pivot(o, xform_point(M, get_pivot(o)))

        d = p_y.normalized()
        if d.length_squared < 1e-12:
            d = Vector((0.0, 1.0, 0.0))
        rows.append((row, d))

        if progress is not None:
            progress(float(fi + 1) / float(n))

    return rows
