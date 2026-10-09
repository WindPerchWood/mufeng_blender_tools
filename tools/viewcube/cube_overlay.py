import itertools
import os

import bpy
import blf
import gpu
from math import cos, pi, sin
from mathutils import Matrix, Vector

from gpu_extras.batch import batch_for_shader


CUBE_HALF = 46.0
MARGIN_X = 96.0
MARGIN_Y = 120.0
HOT_RADIUS = 72.0
FONT_FACE = 30
CLICK_SLOP = 4.0


STATUS_ANCHOR = 'CUBE'
STATUS_ALIGN = ('LEFT', 'TOP')
STATUS_OFFSET = (-3.0, 15.0)
STATUS_REGION_POS = (16.0, 16.0)
STATUS_SIZE = 19
STATUS_EDGE_PAD = 10.0
STATUS_MIN_X = 10.0


BASE_FACE = (0.50, 0.50, 0.55)
COL_FACE_HOVER = (0.30, 0.62, 0.95, 1.0)
COL_HILITE = (0.30, 0.65, 1.00, 0.95)
COL_EDGE = (0.10, 0.10, 0.12, 1.0)
COL_TEXT_FACE = (1.0, 1.0, 1.0, 1.0)
COL_STATUS = (1.0, 1.0, 1.0, 0.92)


FACES = (
    ("FRONT",  (0, -1, 0), "前", ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
    ("BACK",   (0, 1, 0),  "后", ((-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1))),
    ("RIGHT",  (1, 0, 0),  "右", ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1))),
    ("LEFT",   (-1, 0, 0), "左", ((-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1))),
    ("TOP",    (0, 0, 1),  "顶", ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
    ("BOTTOM", (0, 0, -1), "底", ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1))),
)

_FACE_BY_NORMAL = {tuple(n): (key, label) for key, n, label, _v in FACES}
_LETTER = {(1, 0, 0): "R", (-1, 0, 0): "L", (0, 1, 0): "B", (0, -1, 0): "F",
           (0, 0, 1): "T", (0, 0, -1): "D"}


def key_for_normals(normals):
    if len(normals) == 1:
        return _FACE_BY_NORMAL[tuple(normals[0])][0]
    letters = "".join(sorted(_LETTER[tuple(n)] for n in normals))
    prefix = "EDGE_" if len(normals) == 2 else "CORNER_"
    return prefix + letters


VIEW_DIRS = {key: (tuple(n), label) for key, n, label, _v in FACES}
for _i, (_k1, _n1, _l1, _v1) in enumerate(FACES):
    for _k2, _n2, _l2, _v2 in FACES[_i + 1:]:
        if sum(a * b for a, b in zip(_n1, _n2)) == 0:
            VIEW_DIRS[key_for_normals((_n1, _n2))] = (
                tuple(a + b for a, b in zip(_n1, _n2)), _l1 + _l2)
for _i, (_k1, _n1, _l1, _v1) in enumerate(FACES):
    for _j, (_k2, _n2, _l2, _v2) in enumerate(FACES[_i + 1:], _i + 1):
        for _k3, _n3, _l3, _v3 in FACES[_j + 1:]:
            pairs = ((_n1, _n2), (_n1, _n3), (_n2, _n3))
            if all(sum(a * b for a, b in zip(p, q)) == 0 for p, q in pairs):
                VIEW_DIRS[key_for_normals((_n1, _n2, _n3))] = (
                    tuple(a + b + c for a, b, c in zip(_n1, _n2, _n3)), _l1 + _l2 + _l3)


_VIEW_UNIT = {key: (Vector(d).normalized(), label)
              for key, (d, label) in VIEW_DIRS.items()}


FACE_INNER = 0.28

_STATE = {"enabled": True, "hover": None, "in_draw": False,
          "font_retry": 0, "font_dead": False}
_draw_handler = None
_font_id = None


FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
_FONT_MAX_RETRY = 5


def _usable(fid):
    try:
        blf.size(fid, 20)
        w, h = blf.dimensions(fid, "前")
    except Exception:
        return False
    return w > 1.0 and h > 1.0


def load_font():
    global _font_id
    for path in FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            fid = blf.load(path)
        except Exception:
            continue
        if _usable(fid):
            _font_id = fid
            _STATE["font_dead"] = False
            return fid
    _font_id = None
    return None


def invalidate_font():
    global _font_id
    _font_id = None


def _font():
    global _font_id
    if _font_id is not None:
        if _usable(_font_id):
            return _font_id
        _font_id = None
        if _STATE.get("in_draw"):
            _STATE["font_dead"] = True
            schedule_font_retry()
            return 0
    if not _STATE.get("in_draw"):
        load_font()
    return _font_id if _font_id is not None else 0


def schedule_font_retry():
    if _font_id is not None and not _STATE.get("font_dead"):
        return
    if _STATE.get("font_retry"):
        return
    tries = _STATE.get("font_retry", 0)
    if tries >= _FONT_MAX_RETRY:
        return
    _STATE["font_retry"] = tries + 1

    def _retry():
        _STATE["font_retry"] = 0
        if load_font() is not None:
            for area in getattr(bpy.context.screen, "areas", ()) or ():
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return None
        schedule_font_retry()
        return None

    try:
        bpy.app.timers.register(_retry, first_interval=0.2)
    except Exception:
        pass


def _text_local(text, size, color, shadow=True):
    fid = _font()
    try:
        blf.size(fid, size)
    except TypeError:
        blf.size(fid, int(size), 72)
    if shadow:

        try:
            blf.enable(fid, blf.SHADOW)
            blf.shadow(fid, 3, 0.0, 0.0, 0.0, 0.9)
            blf.shadow_offset(fid, 1, -1)
        except Exception:
            pass
    blf.color(fid, *color)
    width, height = blf.dimensions(fid, text)
    try:
        blf.rotation(fid, 0.0)
    except Exception:
        pass
    blf.position(fid, -width / 2.0, -height / 2.0, 0)
    blf.draw(fid, text)


def _face_basis(normal):
    n = Vector(normal).normalized()
    up = Vector((0.0, 0.0, 1.0))
    up = up - n * up.dot(n)
    if up.length < 1e-4:
        up = Vector((0.0, 1.0, 0.0)) - n * Vector((0.0, 1.0, 0.0)).dot(n)
    up.normalize()
    return up.cross(n), up


def _draw_face_labels(visible, qc, cx, cy):
    if not visible:
        return
    for key, label, _pts, depth in visible:
        normal = next(n for k, n, _l, _v in FACES if k == key)
        right, up = _face_basis(normal)
        a = qc @ right
        b = qc @ up
        n_view = qc @ Vector(normal)
        ox = cx + n_view.x * CUBE_HALF
        oy = cy + n_view.y * CUBE_HALF

        alpha = min(1.0, max(0.0, depth) * 3.0) * COL_TEXT_FACE[3]
        if alpha < 0.05:
            continue
        m = Matrix((
            (a.x, b.x, 0.0, ox),
            (a.y, b.y, 0.0, oy),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        gpu.matrix.push()
        try:
            gpu.matrix.load_matrix(m)
            _text_local(label, FONT_FACE, (1.0, 1.0, 1.0, alpha))
        finally:
            gpu.matrix.pop()


def view_name(qc):
    look = qc.inverted() @ Vector((0.0, 0.0, 1.0))
    for _key, (unit, label) in _VIEW_UNIT.items():
        if look.dot(unit) > 0.9999:
            return label
    return "自定义角度"


def _cube_bounds(qc, cx, cy):
    m = qc.to_matrix()
    rx = abs(m[0][0]) + abs(m[0][1]) + abs(m[0][2])
    ry = abs(m[1][0]) + abs(m[1][1]) + abs(m[1][2])
    return (cx - CUBE_HALF * rx, cx + CUBE_HALF * rx,
            cy - CUBE_HALF * ry, cy + CUBE_HALF * ry)


def _status_anchor(qc, cx, cy):
    if STATUS_ANCHOR == 'REGION':

        rx = None if STATUS_REGION_POS[0] is None else STATUS_REGION_POS[0]
        ry = None if STATUS_REGION_POS[1] is None else STATUS_REGION_POS[1]
        if rx is None:
            rx = STATUS_EDGE_PAD if STATUS_ALIGN[0] == 'LEFT' else cx + MARGIN_X - STATUS_EDGE_PAD
        if ry is None:
            ry = STATUS_EDGE_PAD if STATUS_ALIGN[1] == 'BOTTOM' else cy + MARGIN_Y - STATUS_EDGE_PAD
    else:
        left, _right, _bottom, top = _cube_bounds(qc, cx, cy)
        rx, ry = left, top
    return rx + STATUS_OFFSET[0], ry + STATUS_OFFSET[1]


def _draw_status_text(text, qc, cx, cy):
    if not text:
        return
    fid = _font()
    try:
        blf.size(fid, STATUS_SIZE)
    except TypeError:
        blf.size(fid, int(STATUS_SIZE), 72)
    width, height = blf.dimensions(fid, text)
    ax, ay = _status_anchor(qc, cx, cy)
    x = ax if STATUS_ALIGN[0] == 'LEFT' else ax - width
    y = ay if STATUS_ALIGN[1] == 'BOTTOM' else ay - height
    x = max(STATUS_MIN_X, x)
    try:
        blf.enable(fid, blf.SHADOW)
        blf.shadow(fid, 3, 0.0, 0.0, 0.0, 0.9)
        blf.shadow_offset(fid, 1, -1)
    except Exception:
        pass
    blf.color(fid, *COL_STATUS)
    try:
        blf.rotation(fid, 0.0)
    except Exception:
        pass
    gpu.matrix.push()
    try:
        try:
            gpu.matrix.load_identity()
        except AttributeError:
            gpu.matrix.load_matrix(Matrix.Identity(4))
        blf.position(fid, x, y, 0)
        blf.draw(fid, text)
    finally:
        gpu.matrix.pop()


def is_enabled():
    return _STATE["enabled"]


def set_enabled(value):
    _STATE["enabled"] = bool(value)


def get_hover():
    return _STATE["hover"]


def set_hover(value):
    _STATE["hover"] = value


_LETTER_AXIS = {"R": (0, 1), "L": (0, -1), "B": (1, 1), "F": (1, -1), "T": (2, 1), "D": (2, -1)}


def element_verts(key):
    for face_key, _n, _label, verts in FACES:
        if key == face_key:
            return list(verts)
    letters = key.split("_", 1)[1] if "_" in key else ""
    fixed = {}
    for ch in letters:
        axis, value = _LETTER_AXIS[ch]
        fixed[axis] = value
    free = [i for i in (0, 1, 2) if i not in fixed]
    pts = []
    for combo in itertools.product((1, -1), repeat=len(free)):
        v = [0, 0, 0]
        for axis, value in fixed.items():
            v[axis] = value
        for i, axis in enumerate(free):
            v[axis] = combo[i]
        pts.append(tuple(v))
    return pts


def _fill_poly(shader, pts, color):
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": pts})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _fill_disc(shader, center, radius, color, segments=16):
    pts = [(center[0] + cos(2.0 * pi * i / segments) * radius,
            center[1] + sin(2.0 * pi * i / segments) * radius)
           for i in range(segments)]
    _fill_poly(shader, pts, color)


def _fill_band(shader, p1, p2, width, color):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-6:
        _fill_disc(shader, p1, width / 2.0, color)
        return
    nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
    pts = [(p1[0] + nx, p1[1] + ny), (p2[0] + nx, p2[1] + ny),
           (p2[0] - nx, p2[1] - ny), (p1[0] - nx, p1[1] - ny)]
    _fill_poly(shader, pts, color)


def _draw_hilite(shader, cx, cy, qc, hit):
    kind, key = hit
    if kind == 'FACE':
        return
    pts = [(cx + (qc @ Vector(v)).x * CUBE_HALF,
            cy + (qc @ Vector(v)).y * CUBE_HALF) for v in element_verts(key)]
    if len(pts) == 1:
        _fill_disc(shader, pts[0], 11.0, COL_HILITE)
    elif len(pts) == 2:
        _fill_band(shader, pts[0], pts[1], 11.0, COL_HILITE)
    else:
        _fill_poly(shader, pts, COL_HILITE)


def _draw_callback():

    _STATE["in_draw"] = True
    try:
        _draw_callback_inner()
    except Exception:
        pass
    finally:
        _STATE["in_draw"] = False


def _set_ortho_projection(region):
    try:
        gpu.matrix.Ortho(0, region.width, 0, region.height, -1, 1)
    except (AttributeError, TypeError):
        w, h = region.width, region.height
        gpu.matrix.load_projection_matrix(Matrix((
            (2.0 / w, 0.0, 0.0, -1.0),
            (0.0, 2.0 / h, 0.0, -1.0),
            (0.0, 0.0, -1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )))


def _draw_callback_inner():
    context = bpy.context
    region = getattr(context, "region", None)
    space = getattr(context, "space_data", None)
    rv3d = getattr(space, "region_3d", None)
    if region is None or rv3d is None or not _STATE["enabled"]:
        return
    if rv3d.view_perspective == 'CAMERA':
        return
    if (region.width < MARGIN_X * 2 + 20 or region.height < MARGIN_Y * 2 + 20):
        return

    cx = region.width - MARGIN_X
    cy = region.height - MARGIN_Y
    qc = rv3d.view_rotation.conjugated()

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.matrix.push_projection()
    try:
        _set_ortho_projection(region)
        _draw_scene(shader, cx, cy, qc)
    finally:
        gpu.matrix.pop_projection()


def _draw_scene(shader, cx, cy, qc):
    gpu.state.depth_test_set('NONE')

    visible = []
    for key, n_world, label, verts in FACES:
        n_view = qc @ Vector(n_world)
        if n_view.z <= 0.02:
            continue
        pts = []
        for v in verts:
            vv = qc @ Vector(v)
            pts.append((cx + vv.x * CUBE_HALF, cy + vv.y * CUBE_HALF))
        visible.append((key, label, pts, n_view.z))
    visible.sort(key=lambda item: item[3])

    hover = _STATE["hover"]
    gpu.state.blend_set('ALPHA')
    for key, _label, pts, depth in visible:
        if hover == ('FACE', key):
            color = COL_FACE_HOVER
        else:

            shade = 0.62 + 0.50 * min(1.0, max(0.0, depth))
            color = (BASE_FACE[0] * shade, BASE_FACE[1] * shade,
                     BASE_FACE[2] * shade, 1.0)
        _fill_poly(shader, pts, color)

    gpu.state.line_width_set(1.5)
    for _key, _label, pts, _depth in visible:
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": pts + [pts[0]]})
        shader.uniform_float("color", COL_EDGE)
        batch.draw(shader)
    gpu.state.line_width_set(1.0)

    if hover and hover[0] in {'EDGE', 'CORNER'}:
        _draw_hilite(shader, cx, cy, qc, hover)

    _draw_face_labels(visible, qc, cx, cy)

    _draw_status_text(view_name(qc), qc, cx, cy)
    gpu.state.blend_set('NONE')


def _point_in_quad(pts, x, y):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _quad_uv(pts, x, y):
    (x0, y0), (x1, y1), _p2, (x3, y3) = pts
    ax, ay = x1 - x0, y1 - y0
    bx, by = x3 - x0, y3 - y0
    px, py = x - x0, y - y0
    det = ax * by - ay * bx
    if abs(det) < 1e-6:
        return 0.5, 0.5
    u = (px * by - py * bx) / det
    v = (ax * py - ay * px) / det
    return u, v


def _face_local_key(face_key, normal, u, v):
    verts = None
    for key, n, _label, pts in FACES:
        if key == face_key:
            verts = pts
            break
    if verts is None:
        return face_key

    def axis_of(p_from, p_to):
        d = [b - a for a, b in zip(p_from, p_to)]
        for i, comp in enumerate(d):
            if comp != 0:
                axis = [0, 0, 0]
                axis[i] = 1 if comp > 0 else -1
                return tuple(axis)
        return None

    u_axis = axis_of(verts[0], verts[1])
    v_axis = axis_of(verts[0], verts[3])
    normals = [normal]

    lo, hi = FACE_INNER, 1.0 - FACE_INNER
    if u < lo:
        normals.append(tuple(-a for a in u_axis))
    elif u > hi:
        normals.append(u_axis)
    if v < lo:
        normals.append(tuple(-a for a in v_axis))
    elif v > hi:
        normals.append(v_axis)

    if len(normals) == 1:
        return face_key
    return key_for_normals(normals)


def hit_test(region, rv3d, mx, my):
    cx = region.width - MARGIN_X
    cy = region.height - MARGIN_Y
    dx = mx - cx
    dy = my - cy
    if dx * dx + dy * dy > (HOT_RADIUS + 10.0) ** 2:
        return None

    qc = rv3d.view_rotation.conjugated()

    best = None
    for key, n_world, _label, verts in FACES:
        n_view = qc @ Vector(n_world)
        if n_view.z <= 0.0:
            continue
        pts = [(cx + (qc @ Vector(v)).x * CUBE_HALF,
                cy + (qc @ Vector(v)).y * CUBE_HALF) for v in verts]
        if _point_in_quad(pts, mx, my):
            if best is None or n_view.z > best[3]:
                best = (key, tuple(n_world), pts, n_view.z)

    if best is None:
        return ('DRAG', None)

    key, normal, pts, _depth = best
    u, v = _quad_uv(pts, mx, my)
    local = _face_local_key(key, normal, u, v)
    if local == key:
        return ('FACE', key)
    if local.startswith("EDGE_"):
        return ('EDGE', local)
    return ('CORNER', local)


_LOAD_HANDLERS = (
    'load_post',
    'load_factory_startup_post',
    'load_factory_preferences_post',
)


def _on_load(*_args):
    invalidate_font()
    _STATE["font_retry"] = 0
    load_font()
    schedule_font_retry()
    try:
        screen = getattr(bpy.context, "screen", None)
        for area in getattr(screen, "areas", ()) or ():
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    except Exception:
        pass


def _install_load_handlers():
    for name in _LOAD_HANDLERS:
        handlers = getattr(bpy.app.handlers, name, None)
        if handlers is None:
            continue
        if _on_load not in handlers:
            handlers.append(_on_load)


def _remove_load_handlers():
    for name in _LOAD_HANDLERS:
        handlers = getattr(bpy.app.handlers, name, None)
        if not handlers:
            continue
        while _on_load in handlers:
            handlers.remove(_on_load)


def register_draw():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (), 'WINDOW', 'POST_PIXEL')

    invalidate_font()
    _STATE["font_retry"] = 0
    load_font()
    schedule_font_retry()
    _install_load_handlers()


def unregister_draw():
    global _draw_handler
    _remove_load_handlers()
    if _draw_handler is not None:
        try:

            bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
        except TypeError:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(_draw_handler)
            except Exception:
                pass
        except Exception:
            pass
        _draw_handler = None
