import math
import random


SPREAD_DISTANCE = 'DISTANCE'
SPREAD_AXIS_X   = 'AXIS_X'
SPREAD_AXIS_NX  = 'AXIS_NX'
SPREAD_AXIS_Y   = 'AXIS_Y'
SPREAD_AXIS_NY  = 'AXIS_NY'
SPREAD_AXIS_Z   = 'AXIS_Z'
SPREAD_AXIS_NZ  = 'AXIS_NZ'
SPREAD_VECTOR   = 'VECTOR'
SPREAD_WAVE     = 'WAVE'
SPREAD_SPIRAL   = 'SPIRAL'
SPREAD_RANDOM   = 'RANDOM'

SPREAD_MODES = (
    SPREAD_DISTANCE, SPREAD_AXIS_X, SPREAD_AXIS_NX,
    SPREAD_AXIS_Y, SPREAD_AXIS_NY, SPREAD_AXIS_Z, SPREAD_AXIS_NZ,
    SPREAD_VECTOR, SPREAD_WAVE, SPREAD_SPIRAL, SPREAD_RANDOM,
)


EASE_LINEAR = 'LINEAR'
EASE_IN     = 'EASE_IN'
EASE_OUT    = 'EASE_OUT'
EASE_S      = 'EASE_S'

EASE_MODES = (EASE_LINEAR, EASE_IN, EASE_OUT, EASE_S)


APPEAR_SCALE  = 'SCALE'
APPEAR_HIDE   = 'HIDE'
APPEAR_NONE   = 'NONE'

APPEAR_MODES = (APPEAR_SCALE, APPEAR_HIDE, APPEAR_NONE)


AXIS_AUTO   = 'AUTO'
AXIS_X      = 'X'
AXIS_Y      = 'Y'
AXIS_CUSTOM = 'CUSTOM'

FLIP_AXIS_MODES = (AXIS_AUTO, AXIS_X, AXIS_Y, AXIS_CUSTOM)


LIFT_PARABOLA = 'PARABOLA'
LIFT_SINE     = 'SINE'
LIFT_MODES = (LIFT_PARABOLA, LIFT_SINE)


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def ease(t, mode=EASE_LINEAR):
    t = clamp(t, 0.0, 1.0)
    if mode == EASE_LINEAR:
        return t
    if mode == EASE_IN:
        return t * t
    if mode == EASE_OUT:
        return 1.0 - (1.0 - t) * (1.0 - t)
    if mode == EASE_S:
        return t * t * (3.0 - 2.0 * t)
    return t


def lift_curve(t, mode=LIFT_PARABOLA):
    t = clamp(t, 0.0, 1.0)
    if mode == LIFT_SINE:
        return math.sin(t * math.pi)
    return 4.0 * t * (1.0 - t)


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vlen(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def vnorm(a):
    d = vlen(a)
    if d < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / d, a[1] / d, a[2] / d)


def compute_order_keys(positions, params):
    mode = params.get("spread_mode", SPREAD_DISTANCE)
    origin = params.get("origin", (0.0, 0.0, 0.0))
    keys = []

    if mode == SPREAD_DISTANCE:
        for p in positions:
            keys.append(vlen(vsub(p, origin)))

    elif mode in (SPREAD_AXIS_X, SPREAD_AXIS_NX,
                  SPREAD_AXIS_Y, SPREAD_AXIS_NY,
                  SPREAD_AXIS_Z, SPREAD_AXIS_NZ):
        axis = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[mode[-1]]
        sign = -1.0 if mode.startswith('AXIS_N') else 1.0
        for p in positions:
            d = vsub(p, origin)
            keys.append(sign * vdot(d, axis))

    elif mode == SPREAD_VECTOR:
        d = vnorm(params.get("direction", (1.0, 0.0, 0.0)))
        for p in positions:
            keys.append(vdot(vsub(p, origin), d))

    elif mode == SPREAD_WAVE:
        axis = params.get("wave_axis", 'Z')
        axis_v = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[axis]
        period = float(params.get("wave_period", 100.0)) or 100.0
        for p in positions:
            t = vdot(vsub(p, origin), axis_v)
            keys.append(t + math.sin(t / period * 2.0 * math.pi) * (period / 4.0))

    elif mode == SPREAD_SPIRAL:
        for p in positions:
            d = vsub(p, origin)
            ang = math.atan2(d[1], d[0])
            if ang < 0:
                ang += 2.0 * math.pi
            keys.append(ang * max(vlen((d[0], d[1], 0.0)), 1e-6))

    elif mode == SPREAD_RANDOM:
        rnd = random.Random(int(params.get("random_seed", 0)))
        keys = [rnd.random() for _ in positions]

    else:
        for p in positions:
            keys.append(vlen(vsub(p, origin)))

    return keys


def normalize_orders(keys, ease_mode=EASE_LINEAR):
    if not keys:
        return []
    lo, hi = min(keys), max(keys)
    span = hi - lo
    if span < 1e-12:
        return [0.0 for _ in keys]
    raw = [(k - lo) / span for k in keys]
    return [ease(r, ease_mode) for r in raw]


def resolve_axis(flip_axis, custom_axis, spread_mode, direction):
    if flip_axis == AXIS_CUSTOM:
        return vnorm(custom_axis)
    if flip_axis == AXIS_X:
        return (1.0, 0.0, 0.0)
    if flip_axis == AXIS_Y:
        return (0.0, 1.0, 0.0)

    if spread_mode in (SPREAD_AXIS_X, SPREAD_AXIS_NX):
        d = (1.0, 0.0, 0.0)
    elif spread_mode in (SPREAD_AXIS_Y, SPREAD_AXIS_NY):
        d = (0.0, 1.0, 0.0)
    elif spread_mode in (SPREAD_AXIS_Z, SPREAD_AXIS_NZ):
        d = (0.0, 0.0, 1.0)
    elif spread_mode == SPREAD_VECTOR:
        d = vnorm(direction)
    else:
        d = (1.0, 0.0, 0.0)

    up = (0.0, 0.0, 1.0)
    ax = (d[1] * up[2] - d[2] * up[1],
          d[2] * up[0] - d[0] * up[2],
          d[0] * up[1] - d[1] * up[0])
    if vlen(ax) < 1e-6:
        ax = (1.0, 0.0, 0.0)
    return vnorm(ax)


DEFAULTS = {
    "spread_mode": SPREAD_DISTANCE,
    "origin": (0.0, 0.0, 0.0),
    "direction": (1.0, 0.0, 0.0),
    "wave_axis": 'Z',
    "wave_period": 100.0,
    "random_seed": 0,
    "ease_mode": EASE_LINEAR,
    "jitter": 0.0,

    "start_frame": 1.0,
    "spread_frames": 120.0,
    "per_tile_frames": 6.0,

    "appear_mode": APPEAR_SCALE,
    "appear_frames": 0.0,
    "gap_after_appear": 0.0,

    "flip_angle": 90.0,
    "flip_axis": AXIS_AUTO,
    "custom_axis": (1.0, 0.0, 0.0),
    "lift_height": 0.0,
    "lift_mode": LIFT_PARABOLA,
}


def build_plan(positions, params):
    p = dict(DEFAULTS)
    p.update(params or {})

    keys = compute_order_keys(positions, p)
    orders = normalize_orders(keys, p.get("ease_mode", EASE_LINEAR))

    result = []
    for i, pos in enumerate(positions):
        order = orders[i] if i < len(orders) else 0.0

        if p.get("jitter", 0.0):
            rnd = random.Random(int(p.get("random_seed", 0)) * 7919 + i)
            order = clamp(order + (rnd.random() * 2.0 - 1.0) * float(p["jitter"]), 0.0, 1.0)

        base = float(p["start_frame"])
        spread = float(p["spread_frames"])
        per = float(p["per_tile_frames"])

        trigger = base + order * spread

        appear_start = None
        appear_end = None
        appear_mode = p.get("appear_mode", APPEAR_SCALE)
        if appear_mode != APPEAR_NONE:
            appear_dur = float(p["appear_frames"])
            appear_start = trigger
            appear_end = trigger + appear_dur
            flip_start = appear_end + float(p["gap_after_appear"])
        else:
            flip_start = trigger

        flip_end = flip_start + per

        axis = resolve_axis(p.get("flip_axis", AXIS_AUTO),
                            p.get("custom_axis", (1.0, 0.0, 0.0)),
                            p.get("spread_mode", SPREAD_DISTANCE),
                            p.get("direction", (1.0, 0.0, 0.0)))

        result.append({
            "index": i,
            "pos": tuple(pos),
            "order": order,
            "appear_start": appear_start,
            "appear_end": appear_end,
            "flip_start": flip_start,
            "flip_end": flip_end,
            "lift_max": float(p["lift_height"]),
            "axis": axis,
            "angle": float(p["flip_angle"]),
        })

    return result


def total_frames(plan, tail=10.0):
    if not plan:
        return 0.0
    last = 0.0
    for item in plan:
        last = max(last, item["flip_end"])
    return last + tail
