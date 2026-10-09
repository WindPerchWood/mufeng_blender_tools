import math
import random

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types

    def _fallback_register(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _fallback_unregister(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

from .props import SCENE_ATTR


def _scene_settings(context=None):
    ctx = context or bpy.context
    return getattr(ctx.scene, SCENE_ATTR, None)


def _hierarchy_root(obj):
    root = obj
    seen = set()
    while root.parent is not None and root.parent.name not in seen:
        seen.add(root.name)
        root = root.parent
    return root


def _iter_collection_objects(coll):
    yield from coll.all_objects


def _collect_members(settings):
    out = []
    if settings.group_mode == 'COLLECTION':
        coll = settings.group_collection
        if coll is None:
            return []
        out = [o for o in _iter_collection_objects(coll)]
    else:
        picked = settings.group_root
        if picked is None:
            return []
        root = _hierarchy_root(picked)
        out = list(root.children)
    bad = {'CAMERA', 'LIGHT', 'LIGHT_PROBE', 'SPEAKER', 'ARMATURE', 'LATTICE'}
    out = [o for o in out if o.type not in bad]
    out.sort(key=lambda o: o.name)
    return out


def _world_bbox(obj):
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    mn = Vector((min(c[i] for c in corners) for i in range(3)))
    mx = Vector((max(c[i] for c in corners) for i in range(3)))
    return mn, mx


def _group_bbox(objs):
    if not objs:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))
    mins, maxs = [], []
    for o in objs:
        mn, mx = _world_bbox(o)
        mins.append(mn)
        maxs.append(mx)
    mn = Vector((min(v[i] for v in mins) for i in range(3)))
    mx = Vector((max(v[i] for v in maxs) for i in range(3)))
    return mn, mx


def _path_world_points(curve_obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = curve_obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    if mesh is None:
        return []
    mw = curve_obj.matrix_world
    pts = [mw @ v.co for v in mesh.vertices]
    ev.to_mesh_clear()
    return pts


def _nearest_path_param(pts, point, arc_length=True):
    if len(pts) < 2:
        return 0.0, float('inf')

    n = len(pts) - 1
    seg_len = [0.0] * n
    cum = [0.0] * (n + 1)
    for i in range(n):
        seg_len[i] = (pts[i + 1] - pts[i]).length
        cum[i + 1] = cum[i] + seg_len[i]
    total = cum[n]

    kd = KDTree(len(pts))
    for i, p in enumerate(pts):
        kd.insert(p, i)
    kd.balance()
    _co, idx, dist = kd.find(point)

    def param_at(seg_index, t):
        if arc_length:
            if total <= 1e-9:
                return 0.0
            return (cum[seg_index] + seg_len[seg_index] * t) / total
        if n <= 0:
            return 0.0
        return (seg_index + t) / n

    best_dist = dist
    if idx >= n:
        best_param = param_at(n - 1, 1.0)
    else:
        best_param = param_at(idx, 0.0)

    for a, b in ((idx - 1, idx), (idx, idx + 1)):
        if a < 0 or b > n:
            continue
        p0, p1 = pts[a], pts[b]
        d = p1 - p0
        l2 = d.length_squared
        if l2 <= 1e-12:
            continue
        t = (point - p0).dot(d) / l2
        t = max(0.0, min(1.0, t))
        proj = p0 + d * t
        dd = (proj - point).length
        if dd < best_dist:
            best_dist = dd
            best_param = param_at(a, t)
    return best_param, best_dist


def _channelbags(action):
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != 'KEYFRAME':
                continue
            for cb in strip.channelbags:
                yield cb


def _object_fcurves(obj):
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return []
    return [fc for cb in _channelbags(ad.action) for fc in cb.fcurves]


def _remove_fcurve_paths(obj, data_paths):
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return 0
    removed = 0
    for cb in _channelbags(ad.action):
        for fc in [f for f in cb.fcurves if f.data_path in data_paths]:
            cb.fcurves.remove(fc)
            removed += 1
    if not _object_fcurves(obj):
        obj.animation_data_clear()
    return removed


def _set_interpolation(obj, data_paths, mode='LINEAR'):
    for fc in _object_fcurves(obj):
        if fc.data_path in data_paths:
            for kp in fc.keyframe_points:
                kp.interpolation = mode


def _last_key_frame(obj, data_paths):
    frames = []
    for fc in _object_fcurves(obj):
        if fc.data_path in data_paths:
            frames.extend(kp.co[0] for kp in fc.keyframe_points)
    return max(frames) if frames else None


def _principled_node(mat):
    if not mat.use_nodes or mat.node_tree is None:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def _ensure_own_materials(obj):
    data = obj.data
    if data is None or not hasattr(data, "materials"):
        return []
    if len(obj.material_slots) == 0:
        mat = bpy.data.materials.new(name="%s_grow" % obj.name)
        mat.use_nodes = True
        data.materials.append(mat)

    result = []
    for slot in obj.material_slots:
        need_copy = (slot.link != 'OBJECT') or (slot.material is None)
        if need_copy:
            src = slot.material
            new = src.copy() if src is not None else bpy.data.materials.new("%s_grow" % obj.name)
            if not new.use_nodes:
                new.use_nodes = True
            slot.link = 'OBJECT'
            slot.material = new
        mat = slot.material
        if mat is not None:
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = 'DITHERED'
            result.append(mat)
    return result


def _object_alpha_node_trees(obj):
    trees = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'DITHERED'
        node = _principled_node(mat)
        if node is not None:
            trees.append((mat.node_tree, node))
    return trees


def _set_alpha(obj, value, frame):
    for tree, node in _object_alpha_node_trees(obj):
        socket = node.inputs.get("Alpha")
        if socket is None:
            continue
        socket.default_value = value
        socket.keyframe_insert("default_value", frame=frame)


def _set_alpha_interpolation(obj, mode='LINEAR'):
    for tree, _node in _object_alpha_node_trees(obj):
        ad = tree.animation_data
        if ad is None or ad.action is None:
            continue
        for cb in _channelbags(ad.action):
            for fc in cb.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = mode


def _reset_alpha(obj):
    for _tree, node in _object_alpha_node_trees(obj):
        socket = node.inputs.get("Alpha")
        if socket is not None:
            socket.default_value = 1.0


def _remove_alpha_keys(obj):
    for tree, _node in _object_alpha_node_trees(obj):
        ad = tree.animation_data
        if ad is None or ad.action is None:
            continue
        for cb in _channelbags(ad.action):
            for fc in [f for f in cb.fcurves if f.data_path.endswith("default_value")]:
                cb.fcurves.remove(fc)
        if ad.action is not None and not any(
            cb.fcurves for cb in _channelbags(ad.action)
        ):
            tree.animation_data_clear()


def _axis_index(axis):
    return {'X': 0, 'Y': 1, 'Z': 2}[axis]


def _pick_axis(mode, rnd):
    if mode == 'RANDOM':
        return ('X', 'Y', 'Z')[rnd.randint(0, 2)]
    return mode


def _pick_sign(mode, rnd):
    if mode == 'POS':
        return 1
    if mode == 'NEG':
        return -1
    return 1 if rnd.randint(1, 100) <= 50 else -1


def _calc_object_param(obj, gmin, gmax, settings, rnd):
    mn, mx = _world_bbox(obj)
    center = (mn + mx) * 0.5

    if settings.use_path and settings.path_object is not None:
        pts = _path_world_points(settings.path_object)
        if len(pts) >= 2:
            per, _d = _nearest_path_param(
                pts, center, arc_length=settings.path_arc_length
            )
        else:
            per = rnd.random()
    else:
        ax = _axis_index(_pick_axis(settings.grow_axis, rnd))
        span = gmax[ax] - gmin[ax]
        if abs(span) <= 1e-9:
            per = 0.0
        else:
            per = (center[ax] - gmin[ax]) / span

    if settings.reverse_direction:
        per = 1.0 - per
    return per


def _calc_channel_frames(ef, sf, enabled, prob, period, period_rnd,
                         start_rnd, seq, rnd):
    if not enabled:
        return None
    if rnd.randint(1, 100) > prob:
        return None
    start = ef + int((ef - sf) * (seq - 1.0)) + rnd.randint(0, start_rnd)
    end = start + period + rnd.randint(0, period_rnd)
    return start, end


def _calc_move_offset(obj, rest_loc, settings, rnd):
    ax_name = _pick_axis(settings.move_axis, rnd)
    ax = _axis_index(ax_name)
    sign = _pick_sign(settings.move_direction, rnd)

    mn, mx = _world_bbox(obj)
    dim = mx[ax] - mn[ax]
    if abs(dim) <= 1e-9:
        dim = max((mx[i] - mn[i]) for i in range(3))
    dist = settings.amp_move * abs(dim)

    delta_world = Vector((0.0, 0.0, 0.0))
    delta_world[ax] = -sign * dist
    return rest_loc + _world_delta_to_parent(obj, delta_world)


def _world_delta_to_parent(obj, delta_world):
    parent = obj.parent
    if parent is None:
        return delta_world
    m = parent.matrix_world.to_3x3()
    return m.inverted_safe() @ delta_world


def _calc_rotation_offset(rest_rot, settings, rnd):
    ax = _axis_index(_pick_axis(settings.rot_axis, rnd))
    sign = _pick_sign(settings.rot_direction, rnd)
    out = rest_rot.copy()
    out[ax] = out[ax] - sign * settings.amp_rotate * math.pi
    return out


def _calc_scale_offset(rest_scale, settings, rnd):
    mode = settings.scale_mode
    if mode == 'RANDOM':
        mode = ('X', 'Y', 'Z')[rnd.randint(0, 2)]
    out = rest_scale.copy()
    if mode == 'UNIFORM':
        out = Vector((0.0, 0.0, 0.0))
    else:
        out[_axis_index(mode)] = 0.0
    return out


class MF_OT_PickGroup(bpy.types.Operator):
    bl_idname = "mf.pick_group"
    bl_label = "用当前选中作为组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _scene_settings(context)
        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "请先在视口里选中一个物体")
            return {'CANCELLED'}
        if s.group_mode == 'COLLECTION':
            coll = obj.users_collection[0] if obj.users_collection else None
            if coll is None:
                self.report({'ERROR'}, "该物体不属于任何集合")
                return {'CANCELLED'}
            s.group_collection = coll
            self.report({'INFO'}, "组集合：%s" % coll.name)
            return {'FINISHED'}
        root = _hierarchy_root(obj)
        s.group_root = root
        self.report({'INFO'}, "组物体：%s（%d 个成员）" % (root.name, len(root.children)))
        return {'FINISHED'}


class MF_OT_PickPath(bpy.types.Operator):
    bl_idname = "mf.pick_path"
    bl_label = "用当前选中作为路径"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            self.report({'ERROR'}, "请先选中一个曲线（Curve）物体")
            return {'CANCELLED'}
        _scene_settings(context).path_object = obj
        self.report({'INFO'}, "路径：%s" % obj.name)
        return {'FINISHED'}


class MF_OT_DeleteGrowth(bpy.types.Operator):
    bl_idname = "mf.delete_growth"
    bl_label = "删除生长"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = _delete_impl(context)
        self.report({'INFO'}, "已清除 %d 个物体的生长动画" % n)
        return {'FINISHED'}


class MF_OT_CreateGrowth(bpy.types.Operator):
    bl_idname = "mf.create_growth"
    bl_label = "创建生长"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _scene_settings(context)
        members = _collect_members(s)
        if not members:
            self.report({'ERROR'}, "没找到生长物体，请先指定组")
            return {'CANCELLED'}
        if not (s.use_visibility or s.use_move or s.use_rotate or s.use_scale):
            self.report({'ERROR'}, "至少启用一个通道（可见性/移动/旋转/缩放）")
            return {'CANCELLED'}
        if s.frame_end <= s.frame_start:
            self.report({'ERROR'}, "末帧必须大于始帧")
            return {'CANCELLED'}

        saved_frame = context.scene.frame_current

        if s.clear_existing:
            _delete_impl(context)

        try:
            count = _create_impl(context, members)
        finally:
            context.scene.frame_set(saved_frame)

        self.report({'INFO'}, "已为 %d 个物体创建生长动画" % count)
        return {'FINISHED'}


_CHANNEL_PATHS = {
    'V': ("hide_viewport", "hide_render"),
    'M': ("location",),
    'R': ("rotation_euler",),
    'S': ("scale",),
}


def _enabled_channels(s):
    out = []
    if s.use_visibility:
        out.append(('V', s.prob_v, s.period_v, s.period_rnd_v, s.start_rnd_v, 0.0))
    if s.use_move:
        out.append(('M', s.prob_m, s.period_m, s.period_rnd_m, s.start_rnd_m, s.seq_m))
    if s.use_rotate:
        out.append(('R', s.prob_r, s.period_r, s.period_rnd_r, s.start_rnd_r, s.seq_r))
    if s.use_scale:
        out.append(('S', s.prob_s, s.period_s, s.period_rnd_s, s.start_rnd_s, s.seq_s))
    return out


def _delete_impl(context):
    s = _scene_settings(context)
    members = _collect_members(s)
    if not members:
        return 0

    scene = context.scene
    saved_frame = scene.frame_current
    fade = (s.visibility_mode == 'FADE')

    for obj in members:
        bake = {}

        for tag in ('V', 'M', 'R', 'S'):
            paths = _CHANNEL_PATHS[tag]
            if tag == 'V':
                if not s.use_visibility:
                    continue
            elif tag == 'M' and not s.use_move:
                continue
            elif tag == 'R' and not s.use_rotate:
                continue
            elif tag == 'S' and not s.use_scale:
                continue

            last = _last_key_frame(obj, paths)
            if last is None:
                continue
            scene.frame_set(int(round(last)))
            if tag == 'M':
                bake['M'] = obj.location.copy()
            elif tag == 'R':
                bake['R'] = obj.rotation_euler.copy()
            elif tag == 'S':
                bake['S'] = obj.scale.copy()

        for tag in ('V', 'M', 'R', 'S'):
            paths = _CHANNEL_PATHS[tag]
            enabled = {
                'V': s.use_visibility, 'M': s.use_move,
                'R': s.use_rotate, 'S': s.use_scale,
            }[tag]
            if not enabled:
                continue
            if fade and tag == 'V':
                _remove_alpha_keys(obj)
            else:
                _remove_fcurve_paths(obj, paths)

        if 'M' in bake:
            obj.location = bake['M']
        if 'R' in bake:
            obj.rotation_euler = bake['R']
        if 'S' in bake:
            obj.scale = bake['S']
        if s.use_visibility:
            if fade:
                _reset_alpha(obj)
            else:
                obj.hide_viewport = False
                obj.hide_render = False

    scene.frame_set(saved_frame)
    return len(members)


def _create_impl(context, members):
    s = _scene_settings(context)

    rnd = random.Random(s.random_seed) if s.random_seed else random.Random()

    fade_mode = (s.visibility_mode == 'FADE') and s.use_visibility
    for obj in members:
        if obj.rotation_mode != 'XYZ':
            obj.rotation_mode = 'XYZ'
        if fade_mode:
            _ensure_own_materials(obj)

    rest = {}
    for obj in members:
        rest[obj.name] = {
            'loc': obj.location.copy(),
            'rot': obj.rotation_euler.copy(),
            'scl': obj.scale.copy(),
        }

    gmin, gmax = _group_bbox(members)

    channels = _enabled_channels(s)
    fade = (s.visibility_mode == 'FADE')
    touched_paths = set()
    for tag in ('M', 'R', 'S'):
        touched_paths.update(_CHANNEL_PATHS[tag])
    if not fade:
        touched_paths.update(_CHANNEL_PATHS['V'])

    touched_objs = 0

    for obj in members:
        r = rest[obj.name]

        per = _calc_object_param(obj, gmin, gmax, s, rnd)

        span = s.frame_end - s.frame_start
        sf = int(per * span) + s.frame_start + rnd.randint(0, s.start_rnd_v)
        ef = sf + s.period_v + rnd.randint(0, s.period_rnd_v)

        did_anything = False

        for tag, prob, period, period_rnd, start_rnd, seq in channels:
            fs = _calc_channel_frames(
                ef, sf, True, prob, period, period_rnd, start_rnd, seq, rnd)
            if fs is None:
                continue
            start, end = fs

            if tag == 'V':
                if fade:
                    _set_alpha(obj, 0.0, start)
                    _set_alpha(obj, 1.0, end)
                else:
                    obj.hide_viewport = True
                    obj.hide_render = True
                    obj.keyframe_insert("hide_viewport", frame=start)
                    obj.keyframe_insert("hide_render", frame=start)
                    obj.hide_viewport = False
                    obj.hide_render = False
                    obj.keyframe_insert("hide_viewport", frame=end)
                    obj.keyframe_insert("hide_render", frame=end)

            elif tag == 'M':
                offset = _calc_move_offset(obj, r['loc'], s, rnd)
                obj.location = offset
                obj.keyframe_insert("location", frame=start)
                obj.location = r['loc']
                obj.keyframe_insert("location", frame=end)

            elif tag == 'R':
                offset = _calc_rotation_offset(r['rot'], s, rnd)
                obj.rotation_euler = offset
                obj.keyframe_insert("rotation_euler", frame=start)
                obj.rotation_euler = r['rot']
                obj.keyframe_insert("rotation_euler", frame=end)

            elif tag == 'S':
                offset = _calc_scale_offset(r['scl'], s, rnd)
                obj.scale = offset
                obj.keyframe_insert("scale", frame=start)
                obj.scale = r['scl']
                obj.keyframe_insert("scale", frame=end)

            did_anything = True

        obj.location = r['loc']
        obj.rotation_euler = r['rot']
        obj.scale = r['scl']

        if did_anything:
            touched_objs += 1

    for obj in members:
        _set_interpolation(obj, touched_paths, 'LINEAR')
        if fade:
            _set_alpha_interpolation(obj, 'LINEAR')
        else:
            _set_interpolation(obj, ("hide_viewport", "hide_render"), 'CONSTANT')

    context.view_layer.update()
    return touched_objs


classes = (
    MF_OT_PickGroup,
    MF_OT_PickPath,
    MF_OT_CreateGrowth,
    MF_OT_DeleteGrowth,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
