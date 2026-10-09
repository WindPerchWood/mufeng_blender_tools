import bpy

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

from . import bake as B
from . import keyframes as K
from . import plan as P
from . import props


TOOL_ID = "FloorGrowth"
_PREFIX = f"mf.{TOOL_ID.lower()}"

OP_GROW = f"{_PREFIX}_do"
OP_CLEAR = f"{_PREFIX}_clear"
OP_SELECT = f"{_PREFIX}_select"
OP_ESTIMATE = f"{_PREFIX}_estimate"

BAKED_CLOUD_NAME = "MF_BakedCloud"


def _settings(context):
    return getattr(context.scene, props.SCENE_ATTR, None)


def _collect_targets(context, st):
    mode = st.target_mode
    objs = []

    if mode == 'SELECTED':
        objs = [o for o in context.selected_objects if o.type in ('MESH', 'CURVE', 'SURFACE')]
    elif mode == 'COLLECTION':
        col = st.target_collection
        if col:
            objs = [o for o in col.all_objects if o.type in ('MESH', 'CURVE', 'SURFACE')]
    elif mode == 'PREFIX':
        pre = st.target_prefix
        if pre:
            objs = [o for o in context.scene.objects
                    if o.type in ('MESH', 'CURVE', 'SURFACE') and o.name.startswith(pre)]
    elif mode == 'MARKED':
        objs = [o for o in context.scene.objects if o.get(K.MF_MARK)]

    objs.sort(key=lambda o: o.name)
    return objs


def _resolve_origin(context, st):
    from mathutils import Vector

    mode = st.origin_mode
    if mode == 'CURSOR':
        c = context.scene.cursor.location
        return (c.x, c.y, c.z)
    if mode == 'OBJECT':
        ob = st.origin_object
        if ob:
            t = ob.matrix_world.translation
            return (t.x, t.y, t.z)
        return (0.0, 0.0, 0.0)
    if mode == 'CENTER':
        objs = _collect_targets(context, st)
        if not objs:
            return (0.0, 0.0, 0.0)
        acc = Vector((0.0, 0.0, 0.0))
        cnt = 0
        for ob in objs:
            mw = ob.matrix_world
            for c in ob.bound_box:
                acc += mw @ Vector(c)
                cnt += 1
        if cnt == 0:
            return (0.0, 0.0, 0.0)
        acc /= cnt
        return (acc.x, acc.y, acc.z)
    if mode == 'CORNER':
        objs = _collect_targets(context, st)
        if not objs:
            return (0.0, 0.0, 0.0)
        pts = []
        for ob in objs:
            mw = ob.matrix_world
            for c in ob.bound_box:
                pts.append(mw @ Vector(c))
        return (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
    return (0.0, 0.0, 0.0)


def _build_params(context, st):
    origin = _resolve_origin(context, st)
    origin = (origin[0] + st.origin_offset[0],
              origin[1] + st.origin_offset[1],
              origin[2] + st.origin_offset[2])

    roll_dir = None
    sm = st.spread_mode
    if sm == P.SPREAD_AXIS_X:
        roll_dir = (1.0, 0.0, 0.0)
    elif sm == P.SPREAD_AXIS_NX:
        roll_dir = (-1.0, 0.0, 0.0)
    elif sm == P.SPREAD_AXIS_Y:
        roll_dir = (0.0, 1.0, 0.0)
    elif sm == P.SPREAD_AXIS_NY:
        roll_dir = (0.0, -1.0, 0.0)
    elif sm == P.SPREAD_AXIS_Z:
        roll_dir = (0.0, 0.0, 1.0)
    elif sm == P.SPREAD_AXIS_NZ:
        roll_dir = (0.0, 0.0, -1.0)
    elif sm == P.SPREAD_VECTOR:
        roll_dir = tuple(st.direction)

    return {
        "spread_mode": sm,
        "origin": origin,
        "direction": tuple(st.direction),
        "wave_axis": st.wave_axis,
        "wave_period": st.wave_period,
        "random_seed": st.random_seed,
        "ease_mode": st.ease_mode,
        "jitter": st.jitter,
        "start_frame": st.start_frame,
        "spread_frames": st.spread_frames,
        "per_tile_frames": st.per_tile_frames,
        "appear_mode": st.appear_mode,
        "appear_frames": st.appear_frames,
        "gap_after_appear": st.gap_after_appear,
        "flip_angle": st.flip_angle,
        "flip_axis": st.flip_axis,
        "custom_axis": tuple(st.custom_axis),
        "lift_height": st.lift_height,
        "lift_mode": st.lift_mode,
        "interpolate": st.interpolate,
        "use_bounce": st.use_bounce,
        "bounce_amount": st.bounce_amount,
        "roll_dir": roll_dir,
    }


class MF_OT_FloorGrowth_Do(bpy.types.Operator):
    bl_idname = OP_GROW
    bl_label = "生成生长动画"
    bl_description = "为目标地砖生成逐个翻滚生长的动画（关键帧或几何节点烘焙）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        st = _settings(context)
        if st is None:
            self.report({'ERROR'}, "参数未就绪，请重新启用插件")
            return {'CANCELLED'}

        objs = _collect_targets(context, st)
        if not objs:
            self.report({'ERROR'}, "没有找到目标物体，请检查目标模式")
            return {'CANCELLED'}

        params = _build_params(context, st)
        centers = K.world_centers(objs)
        plan_items = P.build_plan(centers, params)

        use_bake = st.use_baking
        if (not use_bake) and st.baking_auto_hint and len(objs) > st.baking_threshold:
            use_bake = True

        if use_bake:
            return _do_bake(self, context, st, objs, plan_items, params, centers)

        if st.auto_clear_before:
            K.clear_keys(objs)

        try:
            result = K.apply_plan(objs, plan_items, params, context.scene)
        except Exception as e:
            self.report({'ERROR'}, "写入失败: %r" % (e,))
            return {'CANCELLED'}

        self.report({'INFO'},
                    "已生成: %d 个物体 / %d 个关键帧 / 结束帧 %d"
                    % (result["objects"], result["keyframes"], int(result["frame_end"])))
        return {'FINISHED'}


def _do_bake(op, context, st, objs, plan_items, params, centers):
    if st.auto_clear_before:
        B.clear_baking(objs=None)

    try:
        res = B.apply_baking(
            context, objs, plan_items, params, centers,
            brick_obj=objs[0],
            name=BAKED_CLOUD_NAME,
            realize=st.baking_realize,
        )
    except Exception as e:
        op.report({'ERROR'}, "烘焙失败: %r" % (e,))
        return {'CANCELLED'}

    if st.baking_keep_source:
        for o in objs:
            o.hide_viewport = False
            o.hide_render = False

    total = P.total_frames(plan_items, tail=10.0)
    if total > 0:
        context.scene.frame_start = int(params.get("start_frame", 1))
        context.scene.frame_end = int(total)

    op.report({'INFO'},
              "烘焙完成: %d 块砖 → 1 个点云 + 1 个修改器（实体化=%s）/ 结束帧 %d"
              % (res["count"], "开" if res["realize"] else "关", int(total)))
    return {'FINISHED'}


class MF_OT_FloorGrowth_Clear(bpy.types.Operator):
    bl_idname = OP_CLEAR
    bl_label = "清除本工具关键帧"
    bl_description = "清除由本工具生成的关键帧与烘焙点云（可安全重复执行）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        st = _settings(context)
        if st is None:
            self.report({'ERROR'}, "参数未就绪，请重新启用插件")
            return {'CANCELLED'}

        if st.clear_scope == 'MARKED':
            objs = K.find_marked(context.scene.objects)
        else:
            objs = _collect_targets(context, st)

        n_bake = B.clear_baking(objs=None)

        if not objs and n_bake == 0:
            self.report({'WARNING'}, "没有可清除的对象")
            return {'CANCELLED'}

        n = K.clear_keys(objs)

        if n == 0 and n_bake > 0:
            self.report({'INFO'}, "已清除 %d 个烘焙点云并恢复原砖" % n_bake)
            return {'FINISHED'}
        self.report({'INFO'},
                    "已清除 %d 个对象的动画" % n +
                    ("，以及 %d 个烘焙点云" % n_bake if n_bake else ""))
        return {'FINISHED'}


class MF_OT_FloorGrowth_Select(bpy.types.Operator):
    bl_idname = OP_SELECT
    bl_label = "选中目标"
    bl_description = "按当前目标模式，在场景中选中将被处理的物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        st = _settings(context)
        if st is None:
            self.report({'ERROR'}, "参数未就绪，请重新启用插件")
            return {'CANCELLED'}

        objs = _collect_targets(context, st)
        bpy.ops.object.select_all(action='DESELECT')
        for ob in objs:
            ob.select_set(True)
        if objs:
            context.view_layer.objects.active = objs[0]
        self.report({'INFO'}, "已选中 %d 个对象" % len(objs))
        return {'FINISHED'}


class MF_OT_FloorGrowth_Estimate(bpy.types.Operator):
    bl_idname = OP_ESTIMATE
    bl_label = "预估总时长"
    bl_description = "根据当前参数估算动画总帧数，不改动场景"

    def execute(self, context):
        st = _settings(context)
        if st is None:
            self.report({'ERROR'}, "参数未就绪，请重新启用插件")
            return {'CANCELLED'}

        objs = _collect_targets(context, st)
        if not objs:
            self.report({'WARNING'}, "没有目标物体")
            return {'CANCELLED'}

        params = _build_params(context, st)
        centers = K.world_centers(objs)
        items = P.build_plan(centers, params)
        total = P.total_frames(items, tail=10.0)

        hint = ""
        if len(objs) > st.baking_threshold:
            hint = "（超过烘焙阈值 %d，建议切烘焙模式）" % st.baking_threshold
        self.report({'INFO'},
                    "%d 块砖，预计总时长 %d 帧（约 %.1f 秒 @24fps）%s"
                    % (len(objs), int(total), total / 24.0, hint))
        return {'FINISHED'}


classes = (
    MF_OT_FloorGrowth_Do,
    MF_OT_FloorGrowth_Clear,
    MF_OT_FloorGrowth_Select,
    MF_OT_FloorGrowth_Estimate,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
