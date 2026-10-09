import math
from mathutils import Vector, Matrix, Euler

EPS = 1e-9

OBB_FACES = (
    (0, 1, 3, 2),
    (4, 5, 7, 6),
    (0, 1, 5, 4),
    (2, 3, 7, 6),
    (0, 2, 6, 4),
    (1, 3, 7, 5),
)


def local_bbox(obj):
    cs = obj.bound_box
    xs = [c[0] for c in cs]
    ys = [c[1] for c in cs]
    zs = [c[2] for c in cs]
    return (Vector((min(xs), min(ys), min(zs))),
            Vector((max(xs), max(ys), max(zs))))


def world_bbox(obj):
    m = obj.matrix_world
    pts = [m @ Vector(c) for c in obj.bound_box]
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


def thickness(obj):
    mn, mx = world_bbox(obj)
    return mx.x - mn.x


def depth(obj):
    mn, mx = world_bbox(obj)
    return mx.y - mn.y


def height(obj):
    mn, mx = world_bbox(obj)
    return mx.z - mn.z


def bbox_center(obj):
    mn, mx = world_bbox(obj)
    return (mn + mx) * 0.5


def obb_corners(obj):
    mn, mx = local_bbox(obj)
    m = obj.matrix_world
    out = []
    for i in range(8):
        v = Vector((mx.x if (i & 1) else mn.x,
                    mx.y if (i & 2) else mn.y,
                    mx.z if (i & 4) else mn.z))
        out.append(m @ v)
    return out


def front_face_quad(obj):
    cs = obb_corners(obj)
    best = None
    best_y = None
    for f in OBB_FACES:
        cy = (cs[f[0]].y + cs[f[1]].y + cs[f[2]].y + cs[f[3]].y) * 0.25
        if best_y is None or cy < best_y:
            best_y = cy
            best = f
    return [cs[i] for i in best]


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def is_parallel(v1, v2):
    l1 = math.sqrt(v1[0] * v1[0] + v1[1] * v1[1])
    l2 = math.sqrt(v2[0] * v2[0] + v2[1] * v2[1])
    if l1 < EPS or l2 < EPS:
        return True
    a = (v1[0] / l1, v1[1] / l1)
    b = (v2[0] / l2, v2[1] / l2)
    return abs(_cross2(a, b)) < 1e-12


def line_intersect(pA, pB, pC, pD):
    a = (pB[0] - pA[0], pB[1] - pA[1])
    b = (pD[0] - pC[0], pD[1] - pC[1])
    c = (pC[0] - pA[0], pC[1] - pA[1])
    k1 = _cross2(a, b)
    if abs(k1) < 1e-12:
        return None
    k2 = _cross2(c, b)
    t = k2 / k1
    return (pA[0] + a[0] * t, pA[1] + a[1] * t)


def _in_seg(v, a, b, tol):
    lo = min(a, b) - tol
    hi = max(a, b) + tol
    return lo <= v <= hi


def push_x(objl, objr, tol=1e-5):
    ql = [(v.x, v.z) for v in front_face_quad(objl)]
    qr = [(v.x, v.z) for v in front_face_quad(objr)]
    best = 0.0
    ray = (1.0, 0.0)
    for src, dst in ((qr, ql), (ql, qr)):
        for i in range(4):
            p1 = src[i]
            p2 = (p1[0] + 1.0, p1[1])
            for j in range(4):
                p3 = dst[j]
                p4 = dst[(j + 1) % 4]
                seg = (p4[0] - p3[0], p4[1] - p3[1])
                if is_parallel(ray, seg):
                    continue
                pi = line_intersect(p1, p2, p3, p4)
                if pi is None:
                    continue
                if not _in_seg(pi[0], p3[0], p4[0], tol):
                    continue
                if not _in_seg(pi[1], p3[1], p4[1], tol):
                    continue
                d = abs(pi[0] - p1[0])
                if d > best:
                    best = d
    return best


def move(obj, v):
    obj.matrix_world = Matrix.Translation(v) @ obj.matrix_world
    p = obj.get("mf_pivot")
    if p is not None:
        obj["mf_pivot"] = (p[0] + v[0], p[1] + v[1], p[2] + v[2])


def get_pivot(obj):
    p = obj.get("mf_pivot")
    if p is None:
        return obj.matrix_world.translation.copy()
    return Vector((p[0], p[1], p[2]))


def set_pivot(obj, v):
    obj["mf_pivot"] = (v[0], v[1], v[2])


def fixpivot(obj):
    mn, _mx = world_bbox(obj)
    set_pivot(obj, mn)
    return mn


def center_pivot(obj):
    c = bbox_center(obj)
    set_pivot(obj, c)
    return c


def xform_point(M, v):
    r = M @ Vector((v[0], v[1], v[2], 1.0))
    return Vector((r.x, r.y, r.z))


def rotate_about_point(obj, axis_vec, angle, center):
    R = Matrix.Rotation(angle, 4, axis_vec)
    T = Matrix.Translation(center)
    M = T @ R @ T.inverted()
    obj.matrix_world = M @ obj.matrix_world
    set_pivot(obj, xform_point(M, get_pivot(obj)))


def rotate_about_pivot(obj, axis_vec, angle):
    rotate_about_point(obj, axis_vec, angle, get_pivot(obj))


def _mat3_to_tuple(m):
    return tuple(m[i][j] for i in range(3) for j in range(3))


def _tuple_to_mat3(t):
    m = Matrix.Identity(3)
    for i in range(3):
        for j in range(3):
            m[i][j] = t[i * 3 + j]
    return m


def set_rot(obj, rx, ry, rz):
    m = obj.matrix_world
    loc, _q, sc = m.decompose()
    r0 = obj.get("mf_rot0")
    if r0 is None:
        r0 = _mat3_to_tuple(m.to_3x3().normalized())
        obj["mf_rot0"] = r0
    R = (Euler((rx, ry, rz), 'XYZ').to_matrix() @ _tuple_to_mat3(r0)).to_4x4()
    S = Matrix.Diagonal((sc.x, sc.y, sc.z, 1.0))
    obj.matrix_world = Matrix.Translation(loc) @ R @ S


def y_rot_deg(obj):
    m = obj.matrix_world.to_3x3().normalized()
    r0 = obj.get("mf_rot0")
    if r0 is not None:
        m = m @ _tuple_to_mat3(r0).inverted()
    return math.degrees(m.to_euler('XYZ').y)


def angle_between(v1, v2):
    a = v1.normalized()
    b = v2.normalized()
    d = max(-1.0, min(1.0, a.dot(b)))
    return math.acos(d)


_AXIS_EPS = 1e-12


def obb_of(obj):
    mn, mx = local_bbox(obj)
    c = (mn + mx) * 0.5
    e = (mx - mn) * 0.5
    M = obj.matrix_world
    R = M.to_3x3()
    axes = []
    ext = []
    for i in range(3):
        col = Vector((R[0][i], R[1][i], R[2][i]))
        s = col.length
        axes.append(col / s if s > _AXIS_EPS else Vector((0.0, 0.0, 1.0)))
        ext.append(e[i] * s)
    return (M @ c), axes, ext


def obb_aabb(box):
    c, axes, ext = box
    r = Vector((0.0, 0.0, 0.0))
    for i in range(3):
        r += Vector((abs(axes[i].x), abs(axes[i].y), abs(axes[i].z))) * ext[i]
    return c - r, c + r


def _obb_radius(box, axis):
    _c, axes, ext = box
    return sum(ext[i] * abs(axis.dot(axes[i])) for i in range(3))


def obb_penetration(a, b):
    ca, A, _ea = a
    cb, B, _eb = b
    d = cb - ca
    cand = list(A) + list(B)
    for i in range(3):
        for j in range(3):
            cand.append(A[i].cross(B[j]))
    best = None
    for axis in cand:
        L = axis.length
        if L < _AXIS_EPS:
            continue
        n = axis / L
        overlap = (_obb_radius(a, n) + _obb_radius(b, n) - abs(n.dot(d)))
        if overlap <= 0.0:
            return 0.0
        if best is None or overlap < best:
            best = overlap
    return best if best is not None else 0.0


def count_collisions(objs, tol=1e-3):
    boxes = [obb_of(o) for o in objs]
    n = len(boxes)
    if n < 2:
        return 0, 0.0
    aabbs = [obb_aabb(b) for b in boxes]
    pairs = 0
    worst = 0.0
    for i in range(n):
        a0, a1 = aabbs[i]
        for j in range(i + 1, n):
            b0, b1 = aabbs[j]
            if (a0.x - tol > b1.x or b0.x - tol > a1.x
                    or a0.y - tol > b1.y or b0.y - tol > a1.y
                    or a0.z - tol > b1.z or b0.z - tol > a1.z):
                continue
            d = obb_penetration(boxes[i], boxes[j])
            if d > tol:
                pairs += 1
                if d > worst:
                    worst = d
    return pairs, worst


def radians(d):
    return math.radians(d)


def degrees(r):
    return math.degrees(r)
