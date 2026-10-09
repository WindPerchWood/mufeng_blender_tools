import math

import bpy
from mathutils import Matrix, Vector

from . import plan as P


MF_MARK = "mf_fg_generated"
MF_BASE = "mf_fg_base"


def world_centers(objs):
    out = []
    for ob in objs:
        mw = ob.matrix_world
        if ob.data and hasattr(ob.data, "vertices") and len(ob.data.vertices):
            acc = Vector((0.0, 0.0, 0.0))
            n = len(ob.data.vertices)
            for v in ob.data.vertices:
                acc += mw @ v.co
            c = acc / n
        else:
            c = mw.translation.copy()
        out.append((c.x, c.y, c.z))
    return out


def _rot_matrix_world(axis, angle_rad):
    return Matrix.Rotation(angle_rad, 3, Vector(axis))


def _set_euler_key(ob, frame, euler3, loc3=None):
    ob.rotation_mode = 'XYZ'
    ob.rotation_euler = euler3
    ob.keyframe_insert("rotation_euler", frame=int(round(frame)))
    if loc3 is not None:
        ob.location = loc3
        ob.keyframe_insert("location", frame=int(round(frame)))


def _set_scale_key(ob, frame, s, base_scale=None):
    if base_scale is None:
        base_scale = (1.0, 1.0, 1.0)
    ob.scale = (base_scale[0] * s, base_scale[1] * s, base_scale[2] * s)
    ob.keyframe_insert("scale", frame=int(round(frame)))


def _set_hide_keys(ob, frame, hidden):
    ob.hide_viewport = bool(hidden)
    ob.keyframe_insert("hide_viewport", frame=int(round(frame)))
    ob.hide_render = bool(hidden)
    ob.keyframe_insert("hide_render", frame=int(round(frame)))


def _apply_world_matrix(ob, mtx):
    ob.matrix_world = Matrix.Identity(4)
    ob.matrix_world = mtx


def _obj_center_world(ob):
    mw = ob.matrix_world
    lc = Vector((0.0, 0.0, 0.0))
    if ob.data and hasattr(ob.data, "vertices") and len(ob.data.vertices):
        acc = Vector((0.0, 0.0, 0.0))
        n = len(ob.data.vertices)
        for v in ob.data.vertices:
            acc += v.co
        lc = acc / n
    return mw @ lc


def _obj_world_dims(ob):
    mw = ob.matrix_world
    if not (ob.data and hasattr(ob.data, "vertices")) or not len(ob.data.vertices):
        return (1.0, 1.0, 1.0)
    xs = [v.co.x for v in ob.data.vertices]
    ys = [v.co.y for v in ob.data.vertices]
    zs = [v.co.z for v in ob.data.vertices]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    z0, z1 = min(zs), max(zs)
    pts = [Vector((x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    ws = [mw @ p for p in pts]
    wx = [p.x for p in ws]
    wy = [p.y for p in ws]
    wz = [p.z for p in ws]
    return (max(wx) - min(wx), max(wy) - min(wy), max(wz) - min(wz))


def apply_plan(objs, plan_items, params, scene=None):
    interp = params.get("interpolate", "BEZIER")
    bounce = bool(params.get("use_bounce", False))
    bounce_amt = float(params.get("bounce_amount", 0.12))
    appear_mode = params.get("appear_mode", P.APPEAR_SCALE)
    lift_mode = params.get("lift_mode", P.LIFT_PARABOLA)
    flip_angle = float(params.get("flip_angle", 90.0))
    lift_height = float(params.get("lift_height", 0.0))

    roll_dir = params.get("roll_dir", None)

    max_frame = 0.0

    for ob, item in zip(objs, plan_items):
        axis_w = Vector(item["axis"])
        flip_s = item["flip_start"]
        flip_e = item["flip_end"]
        lift_max = item["lift_max"]

        ob.rotation_mode = 'XYZ'
        base_loc = Vector(ob.location)
        base_euler = ob.rotation_euler.copy()
        base_scale = (ob.scale.x, ob.scale.y, ob.scale.z)

        m_base = ob.matrix_world.copy()

        c_final = _obj_center_world(ob)

        ax = axis_w.normalized() if axis_w.length > 1e-9 else Vector((1.0, 0.0, 0.0))

        up_w = Vector((0.0, 0.0, 1.0))
        fwd = None
        if roll_dir is not None:
            rd = Vector(roll_dir)
            if rd.length > 1e-9:
                rd = rd - up_w * rd.dot(up_w)
                rd = rd - ax * rd.dot(ax)
                if rd.length > 1e-9:
                    fwd = rd.normalized()
        if fwd is None:
            o = Vector(params.get("origin", (0.0, 0.0, 0.0)))
            rd = Vector((c_final.x - o.x, c_final.y - o.y, 0.0))
            rd = rd - ax * rd.dot(ax)
            if rd.length > 1e-9:
                fwd = rd.normalized()
        if fwd is None:
            fwd = up_w.cross(ax)
            if fwd.length < 1e-9:
                fwd = Vector((1.0, 0.0, 0.0))
            fwd.normalize()

        ax_n = up_w.cross(fwd)
        if ax_n.length < 1e-9:
            ax_n = ax
        else:
            ax_n.normalize()
        ax_rot = ax_n

        mw = ob.matrix_world
        wdim = _obj_world_dims(ob)

        if ob.data and hasattr(ob.data, "vertices") and len(ob.data.vertices):
            wverts = [mw @ v.co for v in ob.data.vertices]
        else:
            wverts = []

        half_fwd = 0.0
        for w in wverts:
            half_fwd = max(half_fwd, abs((w - c_final).dot(fwd)))
        if half_fwd < 1e-6:
            half_fwd = max(wdim) * 0.5

        if wverts:
            ground_z = min(w.z for w in wverts)
        else:
            ground_z = c_final.z - wdim[2] * 0.5
        pivot = Vector((c_final.x - fwd.x * half_fwd,
                        c_final.y - fwd.y * half_fwd,
                        ground_z))

        used_frames = set()

        def write_pose(progress, frame, extra_lift=0.0):
            f_int = int(round(frame))
            if f_int in used_frames:
                return
            used_frames.add(f_int)

            ang = math.radians(-flip_angle) * (1.0 - progress)
            Rot_w = _rot_matrix_world(ax_rot, ang)

            mtx = Matrix.Translation(pivot) @ Rot_w.to_4x4() @ Matrix.Translation(-pivot) @ m_base

            lift = 0.0
            if lift_max > 0.0 and 0.0 < progress < 1.0:
                lift += lift_max * P.lift_curve(progress, lift_mode)
            lift += float(extra_lift)
            if lift:
                mtx = Matrix.Translation(up_w * lift) @ mtx

            _apply_world_matrix(ob, mtx)

            ob.scale = base_scale
            _set_euler_key(ob, f_int,
                           (ob.rotation_euler.x, ob.rotation_euler.y, ob.rotation_euler.z),
                           (ob.location.x, ob.location.y, ob.location.z))

        def write_pose_free(progress, frame, extra_lift=0.0):
            f_int = int(round(frame))
            span = 1
            while f_int in used_frames and span < 200:
                f_int += span
                span += 1
            write_pose(progress, f_int, extra_lift)

        if appear_mode == P.APPEAR_SCALE:
            _set_scale_key(ob, item["appear_start"], 0.0, base_scale)
            _set_scale_key(ob, item["appear_end"], 1.0, base_scale)
            max_frame = max(max_frame, item["appear_end"])
        elif appear_mode == P.APPEAR_HIDE:
            _set_hide_keys(ob, item["appear_start"], True)
            _set_hide_keys(ob, item["appear_end"], False)
            max_frame = max(max_frame, item["appear_end"])

        span_f = max(1.0, float(flip_e - flip_s))
        n_steps = max(2, int(math.ceil(span_f / 2.0)))
        n_steps = min(n_steps, 60)
        for k in range(n_steps + 1):
            t = k / float(n_steps)
            write_pose(t, flip_s + span_f * t)
        max_frame = max(max_frame, flip_e)

        if bounce:
            span = max(1.0, (flip_e - flip_s))
            f1 = flip_e + span * 0.45
            write_pose_free(1.0 - bounce_amt, f1)
            f2 = f1 + span * 0.35
            write_pose_free(1.0, f2)
            max_frame = max(max_frame, f2)

        ob[MF_MARK] = True

        stored = [base_loc.x, base_loc.y, base_loc.z,
                  base_euler.x, base_euler.y, base_euler.z,
                  base_scale[0], base_scale[1], base_scale[2]]
        if MF_BASE not in ob:
            ob[MF_BASE] = stored

    for ob in objs:
        _set_interpolation(ob, interp)

    kf_count_actual = count_keyframes(objs)

    if scene is not None:
        scene.frame_start = int(params.get("start_frame", 1))
        scene.frame_end = int(round(max_frame)) + 10

    return {"objects": len(objs), "keyframes": kf_count_actual,
            "frame_end": max_frame}


def iter_fcurves(ob):
    ad = ob.animation_data
    if not ad or not ad.action:
        return
    act = ad.action
    for layer in act.layers:
        for strip in layer.strips:
            if strip.type != 'KEYFRAME':
                continue
            for cb in strip.channelbags:
                for fc in cb.fcurves:
                    yield fc


def _set_interpolation(ob, mode):
    try:
        for fc in iter_fcurves(ob):
            for kp in fc.keyframe_points:
                kp.interpolation = mode
            fc.update()
    except Exception:
        pass


def count_keyframes(objs):
    n = 0
    for ob in objs:
        for fc in iter_fcurves(ob):
            n += len(fc.keyframe_points)
    return n


def clear_keys(objs):
    n = 0
    for ob in objs:
        ad = ob.animation_data
        if ad and ad.action:
            try:
                ad.action = None
            except Exception:
                pass
            n += 1

        stored = ob.get(MF_BASE)
        if stored is not None and len(stored) >= 9:
            try:
                ob.rotation_mode = 'XYZ'
                ob.location = (stored[0], stored[1], stored[2])
                ob.rotation_euler = (stored[3], stored[4], stored[5])
                ob.scale = (stored[6], stored[7], stored[8])
            except Exception:
                pass

        for key in (MF_MARK, MF_BASE):
            if key in ob:
                try:
                    del ob[key]
                except Exception:
                    pass

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    return n


def find_marked(objs=None):
    if objs is None:
        objs = bpy.data.objects
    return [ob for ob in objs if ob.get(MF_MARK)]
