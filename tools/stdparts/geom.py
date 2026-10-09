
import math

EPS = 1e-12
TAU = 2.0 * math.pi


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _append(verts, faces, sub_verts, sub_faces):
    """把子网格并入总网格，自动做索引偏移。"""
    off = len(verts)
    verts.extend(sub_verts)
    for f in sub_faces:
        faces.append(tuple(i + off for i in f))


def _rotate_z(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2])


def _place(verts, translate=(0.0, 0.0, 0.0), rotate_z=0.0):
    """先绕 Z 旋转，再平移。"""
    tx, ty, tz = translate
    out = []
    for p in verts:
        q = _rotate_z(p, rotate_z) if rotate_z else p
        out.append((q[0] + tx, q[1] + ty, q[2] + tz))
    return out


def _push_point(pts, p, tol=1e-9):
    """压入二维点，自动跳过与前一点重合的退化点。"""
    if pts:
        a = pts[-1]
        if abs(a[0] - p[0]) < tol and abs(a[1] - p[1]) < tol:
            return
    pts.append((p[0], p[1]))


def _circle_pts(radius, count, phase=0.0):
    """逆时针圆点列。"""
    count = max(3, int(count))
    return [(radius * math.cos(phase + TAU * i / count),
             radius * math.sin(phase + TAU * i / count)) for i in range(count)]


def _stadium(length, height, arc_seg=8):
    """圆角跑道形轮廓（长圆孔状），长边沿 X，逆时针。"""
    length = max(float(length), 1e-9)
    height = max(float(height), 1e-9)
    r = min(height, length) * 0.5
    cx = max(length * 0.5 - r, 0.0)
    n = max(2, int(arc_seg))
    pts = []
    for i in range(n + 1):
        a = -math.pi * 0.5 + math.pi * i / n
        _push_point(pts, (cx + r * math.cos(a), r * math.sin(a)))
    for i in range(1, n + 1):
        a = math.pi * 0.5 + math.pi * i / n
        _push_point(pts, (-cx + r * math.cos(a), r * math.sin(a)))
    return pts


def _prism(outer_pts, inner_pts, slices):
    n = len(outer_pts)
    nz = len(slices)
    if n < 3 or nz < 2:
        return [], []

    verts = []
    for (z, tw) in slices:
        c, s = math.cos(tw), math.sin(tw)
        for (x, y) in outer_pts:
            verts.append((x * c - y * s, x * s + y * c, z))

    base_in = len(verts)
    if inner_pts is not None:
        for (z, tw) in slices:
            c, s = math.cos(tw), math.sin(tw)
            for (x, y) in inner_pts:
                verts.append((x * c - y * s, x * s + y * c, z))

    faces = []

    for j in range(nz - 1):
        for i in range(n):
            i2 = (i + 1) % n
            faces.append((j * n + i, j * n + i2, (j + 1) * n + i2, (j + 1) * n + i))

    if inner_pts is not None:
        for j in range(nz - 1):
            for i in range(n):
                i2 = (i + 1) % n
                a = base_in + j * n + i
                b = base_in + j * n + i2
                c = base_in + (j + 1) * n + i2
                d = base_in + (j + 1) * n + i
                faces.append((a, d, c, b))
        for j in (0, nz - 1):
            for i in range(n):
                i2 = (i + 1) % n
                o1 = j * n + i
                o2 = j * n + i2
                n1 = base_in + j * n + i
                n2 = base_in + j * n + i2
                if j == 0:
                    faces.append((o1, n1, n2, o2))
                else:
                    faces.append((o1, o2, n2, n1))
    else:
        cb = len(verts)
        verts.append((0.0, 0.0, slices[0][0]))
        ct = len(verts)
        verts.append((0.0, 0.0, slices[-1][0]))
        last = (nz - 1) * n
        for i in range(n):
            i2 = (i + 1) % n
            faces.append((cb, i2, i))
            faces.append((ct, last + i, last + i2))

    return verts, faces


def _tube(path, section_r, section_n, cap=True):
    """沿空间路径扫掠圆截面，生成管状实体（弹簧用）。"""
    m = len(path)
    if m < 2 or section_r <= 0.0:
        return [], []

    frames = []
    for i in range(m):
        if i == 0:
            t = (path[1][0] - path[0][0], path[1][1] - path[0][1], path[1][2] - path[0][2])
        elif i == m - 1:
            t = (path[-1][0] - path[-2][0], path[-1][1] - path[-2][1], path[-1][2] - path[-2][2])
        else:
            t = (path[i + 1][0] - path[i - 1][0],
                 path[i + 1][1] - path[i - 1][1],
                 path[i + 1][2] - path[i - 1][2])
        tl = math.sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]) or 1.0
        t = (t[0] / tl, t[1] / tl, t[2] / tl)

        rx, ry = path[i][0], path[i][1]
        rl = math.hypot(rx, ry)
        if rl < 1e-9:
            rx, ry, rl = 1.0, 0.0, 1.0
        ref = (rx / rl, ry / rl, 0.0)

        dot = ref[0] * t[0] + ref[1] * t[1] + ref[2] * t[2]
        nx, ny, nz = (ref[0] - dot * t[0], ref[1] - dot * t[1], ref[2] - dot * t[2])
        nl = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nl < 1e-9:
            nx, ny, nz = (0.0, 1.0, 0.0)
            dot2 = ny * t[1]
            nx, ny, nz = (-dot2 * t[0], 1.0 - dot2 * t[1], -dot2 * t[2])
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        nrm = (nx / nl, ny / nl, nz / nl)
        bin_ = (t[1] * nrm[2] - t[2] * nrm[1],
                t[2] * nrm[0] - t[0] * nrm[2],
                t[0] * nrm[1] - t[1] * nrm[0])
        frames.append((nrm, bin_))

    sn = max(4, int(section_n))
    verts = []
    for i, c in enumerate(path):
        nrm, bin_ = frames[i]
        for j in range(sn):
            a = TAU * j / sn
            ca, sa = math.cos(a), math.sin(a)
            verts.append((c[0] + section_r * (ca * nrm[0] + sa * bin_[0]),
                          c[1] + section_r * (ca * nrm[1] + sa * bin_[1]),
                          c[2] + section_r * (ca * nrm[2] + sa * bin_[2])))

    faces = []
    for i in range(m - 1):
        for j in range(sn):
            j2 = (j + 1) % sn
            faces.append((i * sn + j, i * sn + j2, (i + 1) * sn + j2, (i + 1) * sn + j))

    if cap:
        c0 = len(verts)
        verts.append(path[0])
        c1 = len(verts)
        verts.append(path[-1])
        base = (m - 1) * sn
        for j in range(sn):
            j2 = (j + 1) % sn
            faces.append((c0, j2, j))
            faces.append((c1, base + j, base + j2))

    return verts, faces


def _uv_sphere(radius, rings=8, segs=16):
    """经纬球。rings = 纬向分段（不含两极），segs = 经向分段。"""
    rings = max(2, int(rings))
    segs = max(4, int(segs))
    verts = [(0.0, 0.0, radius)]          
    for i in range(1, rings):
        phi = math.pi * i / rings
        z = radius * math.cos(phi)
        rr = radius * math.sin(phi)
        for j in range(segs):
            a = TAU * j / segs
            verts.append((rr * math.cos(a), rr * math.sin(a), z))
    verts.append((0.0, 0.0, -radius))      
    north = 0
    south = len(verts) - 1

    def ring(i):        
        return 1 + (i - 1) * segs

    faces = []
    for j in range(segs):
        j2 = (j + 1) % segs
        faces.append((north, ring(1) + j, ring(1) + j2))
    for i in range(1, rings - 1):
        a0, a1 = ring(i), ring(i + 1)
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append((a0 + j, a1 + j, a1 + j2, a0 + j2))
    last = ring(rings - 1)
    for j in range(segs):
        j2 = (j + 1) % segs
        faces.append((south, last + j2, last + j))
    return verts, faces


def involute(a):
    """渐开线函数 inv(a) = tan(a) - a。"""
    return math.tan(a) - a


def involute_inverse(y, iters=40):
    """求 inv(a) = y 的 a（牛顿迭代）。"""
    if y <= 0.0:
        return 0.0
    a = (3.0 * y) ** (1.0 / 3.0)          
    for _ in range(iters):
        ta = math.tan(a)
        f = ta - a - y
        fp = ta * ta
        if fp < 1e-14:
            break
        step = f / fp
        a -= step
        a = _clamp(a, 1e-9, math.pi * 0.5 - 1e-6)
        if abs(step) < 1e-14:
            break
    return a


def gear_profile(module, teeth, pressure_deg=20.0, helix_deg=0.0, shift=0.0,
                 root_seg=3, inv_seg=8, tip_seg=3, arc_seg=3):
    z = max(3, int(round(teeth)))
    mn = max(1e-6, float(module))
    alpha_n = math.radians(_clamp(pressure_deg, 5.0, 40.0))
    beta = math.radians(_clamp(helix_deg, -80.0, 80.0))
    shift = _clamp(float(shift), -0.9, 0.9)
    cb = math.cos(beta)

    mt = mn / cb                                   
    alpha_t = math.atan(math.tan(alpha_n) / cb)     
    d = mt * z
    r = d * 0.5
    rb = r * math.cos(alpha_t)
    ha = mn * (1.0 + shift)
    hf = mn * (1.25 - shift)
    ra = r + ha
    rf = max(r - hf, rb * 0.02)

    half = math.pi / (2.0 * z)                      
    inv_a = involute(alpha_t)
    psi_rb = half + inv_a

    ra = max(ra, rb * 1.0000001)
    alpha_a = math.acos(_clamp(rb / ra, -1.0, 1.0))
    psi_a = half + inv_a - involute(alpha_a)
    pointed = False
    if psi_a <= 1e-6:
        pointed = True
        alpha_p = involute_inverse(psi_rb)
        ra = rb / math.cos(alpha_p)
        alpha_a = alpha_p
        psi_a = 0.0

    thetas = []
    radii = []

    def _push(theta, rad):
        if thetas:
            prev = thetas[-1]
            if abs(theta - prev) < 1e-12 and abs(rad - radii[-1]) < 1e-12:
                return
        thetas.append(theta)
        radii.append(rad)

    for k in range(z):
        tk = TAU * k / z                        

        for s in range(int(root_seg)):
            f = s / max(1, root_seg - 1)
            _push(tk - psi_rb, rf + (rb - rf) * f)

        for s in range(1, int(inv_seg) + 1):
            f = s / float(inv_seg)
            ai = alpha_a * f
            ri = rb / math.cos(ai)
            _push(tk - (half + inv_a - involute(ai)), ri)

        if pointed or int(tip_seg) <= 1:
            _push(tk, ra)
        else:
            for s in range(0, int(tip_seg)):
                f = s / float(int(tip_seg) - 1)
                _push(tk - psi_a + 2.0 * psi_a * f, ra)

        for s in range(int(inv_seg) - 1, -1, -1):
            f = s / float(inv_seg)
            ai = alpha_a * f
            ri = rb / math.cos(ai)
            _push(tk + (half + inv_a - involute(ai)), ri)

        for s in range(int(root_seg) - 1, -1, -1):
            f = s / max(1, root_seg - 1)
            _push(tk + psi_rb, rf + (rb - rf) * f)

        if int(arc_seg) >= 2:
            a0 = tk + psi_rb
            a1 = TAU * (k + 1) / z - psi_rb
            if a1 <= a0:
                a1 = TAU - psi_rb   
            span = a1 - a0
            for s in range(1, int(arc_seg)):
                _push(a0 + span * s / float(int(arc_seg)), rf)

    feat = {
        'teeth': z,
        'module_normal': mn,
        'module_transverse': mt,
        'pressure_angle_normal_deg': math.degrees(alpha_n),
        'pressure_angle_transverse_deg': math.degrees(alpha_t),
        'helix_deg': math.degrees(beta),
        'pitch_dia': d,
        'base_dia': 2.0 * rb,
        'tip_dia': 2.0 * ra,
        'root_dia': 2.0 * rf,
        'addendum': ra - r,
        'dedendum': r - rf,
        'tooth_height': ra - rf,
        'pointed_tip': pointed,
        'lead': (d * math.pi / math.tan(abs(beta))) if abs(beta) > 1e-9 else 0.0,
    }
    return thetas, radii, feat


def _sample_radius(thetas, radii, angle):
    """按角度线性插值半径（齿廓按极角是单值函数，可直接插）。"""
    n = len(thetas)
    a = angle % TAU
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if thetas[mid] < a:
            lo = mid + 1
        else:
            hi = mid
    i1 = lo % n
    i0 = (i1 - 1) % n
    t0 = thetas[i0]
    t1 = thetas[i1]
    if i1 == 0:
        t1 += TAU
    if a < thetas[0]:
        t0 = thetas[-1] - TAU
    span = t1 - t0
    if span <= EPS:
        return radii[i0]
    f = _clamp((a - t0) / span, 0.0, 1.0)
    return radii[i0] + (radii[i1] - radii[i0]) * f


def build_gear(module, teeth, width, pressure_deg=20.0, helix_deg=0.0, shift=0.0,
               bore_d=0.0, keyway_w=0.0, keyway_h=0.0,
               root_seg=3, inv_seg=8, tip_seg=3, arc_seg=3, z_slices=0):
    """齿轮实体（直齿 / 斜齿通用）。helix_deg = 0 即直齿。"""
    thetas, radii, feat = gear_profile(
        module, teeth, pressure_deg, helix_deg, shift,
        root_seg, inv_seg, tip_seg, arc_seg)

    bore_r = max(0.0, float(bore_d)) * 0.5
    kw_w = max(0.0, float(keyway_w))
    kw_h = max(0.0, float(keyway_h))
    if kw_w > 0.0 and kw_h > 0.0 and bore_r > 0.0:
        kw_w = min(kw_w, 2.0 * bore_r * 0.9)
    else:
        kw_w = 0.0
        kw_h = 0.0

    kw_half = (kw_w * 0.5) / bore_r if bore_r > 0 else 0.0
    kw_warn = ''
    if bore_r > 0:
        if 2.0 * bore_r >= feat['root_dia'] - 2.0 * module:
            kw_warn = "孔径过大：已接近齿根圆，齿体可能被掏空"
        elif feat['tip_dia'] * 0.5 - bore_r < 1.2 * module:
            kw_warn = "孔壁偏薄（小于 1.2 倍模数），强度不足"

    angles = list(thetas)
    if kw_half > 0.0:
        for dlt in (-kw_half, 0.0, kw_half):
            a = dlt % TAU
            if not any(abs(a - b) < 1e-9 for b in angles):
                angles.append(a)
    angles.sort()

    clean = []
    for a in angles:
        if clean and abs(a - clean[-1]) < 1e-9:
            continue
        clean.append(a)
    angles = clean

    outer = []
    inner = []
    for a in angles:
        ro = _sample_radius(thetas, radii, a)
        outer.append((ro * math.cos(a), ro * math.sin(a)))
        if bore_r > 0.0:
            ri = bore_r
            if kw_half > 0.0:
                da = abs(((a + math.pi) % TAU) - math.pi)   
                if da <= kw_half + 1e-12:
                    ri = bore_r + kw_h
            ri = min(ri, ro * 0.85)
            inner.append((ri * math.cos(a), ri * math.sin(a)))

    w = max(float(width), 1e-6)
    beta = math.radians(_clamp(helix_deg, -80.0, 80.0))
    if abs(beta) > 1e-9:
        nsl = int(z_slices) if int(z_slices) >= 2 else 6
        pitch_r = max(feat['pitch_dia'] * 0.5, 1e-9)
        total_twist = w * math.tan(beta) / pitch_r
    else:
        nsl = 2
        total_twist = 0.0
    slices = [(w * i / (nsl - 1), total_twist * i / (nsl - 1)) for i in range(nsl)]

    verts, faces = _prism(outer, inner if bore_r > 0.0 else None, slices)

    feat['width'] = w
    feat['bore_dia'] = 2.0 * bore_r
    feat['keyway_w'] = kw_w
    feat['keyway_h'] = kw_h
    feat['twist_total_deg'] = math.degrees(total_twist)
    feat['warning'] = kw_warn
    return verts, faces, feat


def build_spring(outer_dia, wire_dia, turns, free_height,
                 hand='RIGHT', end_type='CLOSED',
                 seg_per_turn=18, ring_seg=12):
    D = max(float(outer_dia), 1e-6)
    d = max(float(wire_dia), 1e-6)
    n = max(float(turns), 0.5)
    H = max(float(free_height), d * 1.05)

    warn = ''
    if d >= D * 0.5:
        warn = "线径过大：应小于外径的一半"
    mean_r = max(D * 0.5 - d * 0.5, d * 0.25)

    closed = (end_type == 'CLOSED')
    n1 = n + 2.0 if closed else n            

    z0 = d * 0.5
    z1 = H - d * 0.5
    if z1 <= z0:
        z0, z1 = d * 0.5, max(H - d * 0.5, d * 0.6)
    active_span = max(z1 - z0, 0.0)

    def height_at(t):
        """t ∈ [0,1] 沿螺旋线的归一化位置 -> z。"""
        if not closed:
            return z0 + active_span * t
        edge = 1.0 / n1
        if t <= edge:
            return z0
        if t >= 1.0 - edge:
            return z1
        f = (t - edge) / max(1e-9, (1.0 - 2.0 * edge))
        return z0 + active_span * f

    steps = max(8, int(round(n1 * max(6, int(seg_per_turn)))))
    ring_seg = max(8, (int(ring_seg) // 4) * 4)
    seg_per_turn = max(8, (int(seg_per_turn) // 4) * 4)
    steps = max(8, int(round(n1 * seg_per_turn)))
    sign = 1.0 if hand == 'RIGHT' else -1.0
    path = []
    for i in range(steps + 1):
        t = i / float(steps)
        ang = sign * TAU * n1 * t
        path.append((mean_r * math.cos(ang), mean_r * math.sin(ang), height_at(t)))

    verts, faces = _tube(path, d * 0.5, ring_seg, cap=True)

    n_eff = n
    pitch = active_span / n_eff if n_eff > 0 else 0.0
    mean_d = 2.0 * mean_r
    lead = math.atan(pitch / (math.pi * mean_d)) if mean_d > 0 else 0.0
    if not warn and pitch > 0 and pitch < d:
        warn = "节距小于线径：圈会自交，请增大自由高度或减少圈数"
    if not warn and mean_d / d < 3.0:
        warn = "弹簧指数 D/d 过小（<3）：易失稳，不建议"

    info = {
        'outer_dia': D,
        'wire_dia': d,
        'mean_dia': mean_d,
        'inner_dia': D - 2.0 * d,
        'turns_total': n1,
        'turns_active': n_eff,
        'free_height': H,
        'pitch': pitch,
        'helix_deg': math.degrees(lead),
        'hand': hand,
        'end_type': end_type,
        'spring_index': mean_d / d,
        'warning': warn,
    }
    return verts, faces, info


def build_bearing(bore_dia, outer_dia, width, balls=8, ball_dia=0.0,
                  ring_thickness=0.0, seg=72, ball_rings=6, ball_segs=12):
    d = max(float(bore_dia), 1e-6)
    D = max(float(outer_dia), d * 1.05)
    B = max(float(width), 1e-6)
    ri = d * 0.5
    ro = D * 0.5
    radial = ro - ri

    t = float(ring_thickness)
    if t <= 0.0:
        t = radial * 0.22
    t = _clamp(t, radial * 0.05, radial * 0.40)

    seg = max(12, int(seg))
    warn = ''

    inner_ring = _prism(_circle_pts(ri + t, seg), _circle_pts(ri, seg),
                        [(0.0, 0.0), (B, 0.0)])
    outer_ring = _prism(_circle_pts(ro, seg), _circle_pts(ro - t, seg),
                        [(0.0, 0.0), (B, 0.0)])

    rm = (ri + t + ro - t) * 0.5               
    max_br = max((ro - t - (ri + t)) * 0.5, radial * 0.02)

    Z = max(3, int(round(balls)))
    db = float(ball_dia)
    if db <= 0.0:
        db = min(0.30 * (D - d), 2.0 * max_br * 0.92)
    br = db * 0.5
    if br > max_br:
        br = max_br
        db = 2.0 * br
        warn = "球径超出内、外圈之间的空间，已自动收小"
    if 2.0 * br > B * 0.98:
        warn = "球径大于轴承宽度，钢球会凸出端面"

    chord = 2.0 * rm * math.sin(math.pi / Z)
    if chord < db * 1.02:
        zmax = max(3, int(math.floor(math.pi / math.asin(min(0.999, br * 1.02 / rm)))))
        warn = "球数过多，相邻钢球会重叠（建议不超过 %d 个）" % zmax

    verts = []
    faces = []
    _append(verts, faces, *outer_ring)
    _append(verts, faces, *inner_ring)

    bv, bf = _uv_sphere(br, ball_rings, ball_segs)
    for i in range(Z):
        a = TAU * i / Z
        _append(verts, faces, _place(bv, (rm * math.cos(a), rm * math.sin(a), B * 0.5)), bf)

    info = {
        'bore_dia': d,
        'outer_dia': D,
        'width': B,
        'balls': Z,
        'ball_dia': db,
        'ring_thickness': t,
        'ball_circle_dia': 2.0 * rm,
        'ball_gap': max(0.0, chord - db),
        'warning': warn,
    }
    return verts, faces, info


def _chain_link(pitch, inner_w, plate_t, plate_h, roller_d, pin_d,
                outer_link, arc_seg=6, pin_seg=10):
    """单个链节的实体：2 块链板 + 2 根销轴 + 1 个滚子（沿 +X 展开，长度 = 节距）。"""
    p = max(float(pitch), 1e-6)
    w = max(float(inner_w), 1e-6)
    tp = max(float(plate_t), 1e-6)
    hp = max(float(plate_h), 1e-6)
    rd = _clamp(float(roller_d), p * 0.15, p * 0.95)
    rr = rd * 0.5
    rp = max(float(pin_d), 1e-6) * 0.5

    if outer_link:
        plate_z = w * 0.5 + tp * 1.5
    else:
        plate_z = w * 0.5 + tp * 0.5

    verts = []
    faces = []

    prof = _stadium(p, hp, arc_seg=arc_seg)
    pv, pf = _prism(prof, None, [(-tp * 0.5, 0.0), (tp * 0.5, 0.0)])
    for zc in (plate_z, -plate_z):
        _append(verts, faces, _place(pv, (p * 0.5, 0.0, zc)), pf)

    rv, rf = _prism(_circle_pts(rr, max(8, pin_seg * 2)), None,
                    [(-w * 0.5, 0.0), (w * 0.5, 0.0)])
    _append(verts, faces, _place(rv, (p, 0.0, 0.0)), rf)

    pin_total = 2.0 * (w * 0.5 + tp * (2.0 if outer_link else 1.0))
    pv2, pf2 = _prism(_circle_pts(rp, max(6, pin_seg)), None,
                      [(-pin_total * 0.5, 0.0), (pin_total * 0.5, 0.0)])
    _append(verts, faces, _place(pv2, (0.0, 0.0, 0.0)), pf2)
    _append(verts, faces, _place(pv2, (p, 0.0, 0.0)), pf2)

    return verts, faces


def build_chain(pitch, links, layout='LINEAR', roller_dia=0.0, inner_width=0.0,
                plate_thickness=0.0, plate_height=0.0, arc_seg=6, pin_seg=10):
    p = max(float(pitch), 1e-6)
    N = max(4, int(round(links)))

    rd = float(roller_dia) if float(roller_dia) > 0 else p * 0.625
    w = float(inner_width) if float(inner_width) > 0 else p * 0.62
    tp = float(plate_thickness) if float(plate_thickness) > 0 else p * 0.12
    hp = float(plate_height) if float(plate_height) > 0 else p * 0.92
    if hp < rd * 1.05:
        hp = rd * 1.05
    pin_d = rd * 0.34

    warn = ''
    ring = (layout == 'RING')
    if ring:
        radius = N * p / TAU
        if radius <= hp:
            warn = "节数太少，环半径小于链板高度，链条会自我干涉"
    else:
        radius = 0.0

    lv_out, lf_out = _chain_link(p, w, tp, hp, rd, pin_d, True, arc_seg, pin_seg)
    lv_in, lf_in = _chain_link(p, w, tp, hp, rd, pin_d, False, arc_seg, pin_seg)

    verts = []
    faces = []
    for i in range(N):
        if ring:
            a = TAU * i / N
            tx, ty = radius * math.cos(a), radius * math.sin(a)
            rz = a + math.pi * 0.5
        else:
            tx, ty, rz = i * p, 0.0, 0.0
        if (i % 2) == 0:
            _append(verts, faces, _place(lv_out, (tx, ty, 0.0), rz), lf_out)
        else:
            _append(verts, faces, _place(lv_in, (tx, ty, 0.0), rz), lf_in)

    info = {
        'pitch': p,
        'links': N,
        'layout': layout,
        'length': N * p,
        'ring_dia': 2.0 * radius if ring else 0.0,
        'roller_dia': rd,
        'inner_width': w,
        'plate_thickness': tp,
        'plate_height': hp,
        'pin_dia': pin_d,
        'warning': warn,
    }
    return verts, faces, info


def build(part_type, params):
    """按类型分派。params 内所有长度均已是 Blender 单位。"""
    if part_type == 'SPUR_GEAR':
        return build_gear(
            module=params['module'], teeth=params['teeth'], width=params['width'],
            pressure_deg=params.get('pressure_deg', 20.0),
            helix_deg=0.0,
            shift=params.get('shift', 0.0),
            bore_d=params.get('bore_d', 0.0),
            keyway_w=params.get('keyway_w', 0.0),
            keyway_h=params.get('keyway_h', 0.0),
            inv_seg=params.get('inv_seg', 8),
            root_seg=params.get('root_seg', 3),
            tip_seg=params.get('tip_seg', 3),
            arc_seg=params.get('arc_seg', 3),
        )
    if part_type == 'HELICAL_GEAR':
        return build_gear(
            module=params['module'], teeth=params['teeth'], width=params['width'],
            pressure_deg=params.get('pressure_deg', 20.0),
            helix_deg=params.get('helix_deg', 20.0),
            shift=params.get('shift', 0.0),
            bore_d=params.get('bore_d', 0.0),
            keyway_w=params.get('keyway_w', 0.0),
            keyway_h=params.get('keyway_h', 0.0),
            inv_seg=params.get('inv_seg', 8),
            root_seg=params.get('root_seg', 3),
            tip_seg=params.get('tip_seg', 3),
            arc_seg=params.get('arc_seg', 3),
            z_slices=params.get('z_slices', 0),
        )
    if part_type == 'SPRING':
        return build_spring(
            outer_dia=params['outer_dia'], wire_dia=params['wire_dia'],
            turns=params['turns'], free_height=params['free_height'],
            hand=params.get('hand', 'RIGHT'), end_type=params.get('end_type', 'CLOSED'),
            seg_per_turn=params.get('seg_per_turn', 18),
            ring_seg=params.get('ring_seg', 12),
        )
    if part_type == 'BEARING':
        return build_bearing(
            bore_dia=params['bore_dia'], outer_dia=params['outer_dia'],
            width=params['width'], balls=params.get('balls', 8),
            ball_dia=params.get('ball_dia', 0.0),
            ring_thickness=params.get('ring_thickness', 0.0),
            seg=params.get('seg', 72),
        )
    if part_type == 'CHAIN':
        return build_chain(
            pitch=params['pitch'], links=params['links'],
            layout=params.get('layout', 'LINEAR'),
            roller_dia=params.get('roller_dia', 0.0),
            inner_width=params.get('inner_width', 0.0),
            plate_thickness=params.get('plate_thickness', 0.0),
            plate_height=params.get('plate_height', 0.0),
        )
    raise ValueError("未知标准件类型: %r" % (part_type,))


def bounds(verts):
    """返回 ((minx, miny, minz), (maxx, maxy, maxz))。"""
    if not verts:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
