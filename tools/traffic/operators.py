
import random

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from . import props

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
        PANEL_CATEGORY="木风工具箱",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

TOOL_ID = "Traffic"
OP_PICK_ROADS = f"mf.{TOOL_ID.lower()}_pick_roads"
OP_PICK_CARS = f"mf.{TOOL_ID.lower()}_pick_cars"
OP_REMOVE_ROAD = f"mf.{TOOL_ID.lower()}_remove_road"
OP_REMOVE_CAR = f"mf.{TOOL_ID.lower()}_remove_car"
OP_ACTIVATE_ROAD = f"mf.{TOOL_ID.lower()}_activate_road"
OP_ACTIVATE_CAR = f"mf.{TOOL_ID.lower()}_activate_car"
OP_COMPUTE = f"mf.{TOOL_ID.lower()}_compute"
OP_OFFSET_ALL = f"mf.{TOOL_ID.lower()}_offset_all"
OP_APPLY_DURATION = f"mf.{TOOL_ID.lower()}_apply_duration"
OP_CLEAR_ALL = f"mf.{TOOL_ID.lower()}_clear_all"

FINISHED = "FINISHED"
CANCELLED = "CANCELLED"


def settings(context):
    return getattr(context.scene, props.SCENE_ATTR)


def find_by_name(name):
    return bpy.data.objects.get(name)


def resolve_names(items):
    out = []
    for it in items:
        ob = find_by_name(it.name)
        if ob is not None:
            out.append(ob)
    return out


def is_unit(ob):
    return ob is not None and bool(ob.get(props.TAG_UNIT))


def is_generated_car(ob):
    return ob is not None and bool(ob.get(props.TAG_CAR))


def all_generated_cars():
    return [o for o in bpy.data.objects if is_generated_car(o)]


def current_road(st):
    idx = int(st.road_index)
    if idx < 0 or idx >= len(st.roads):
        return None
    return find_by_name(st.roads[idx].name)


def cars_on_road(road):
    if road is None:
        return []
    out = []
    for car in all_generated_cars():
        for con in _constraints_by_target(car):
            if con.target == road:
                out.append(car)
                break
    return out


def _orphan_cars():
    out = []
    for car in all_generated_cars():
        cons = _constraints_by_target(car)
        if not cons or cons[0].target is None:
            out.append(car)
    return out


def _constraints_by_target(ob):
    return [c for c in ob.constraints if c.type == "FOLLOW_PATH"]


def _find_offset_fcurve(con_owner, con):
    ad = con_owner.animation_data
    if ad is None or ad.action is None:
        return None
    needle = 'constraints["%s"].offset_factor' % con.name
    for layer in ad.action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for cb in strip.channelbags:
                for fc in cb.fcurves:
                    if fc.data_path == needle and fc.array_index == 0:
                        return fc
    return None


def _keyframes(car, con):
    fc = _find_offset_fcurve(car, con)
    if fc is None or len(fc.keyframe_points) < 2:
        return None
    return fc


def _shift_phase_frames(fc, frames):
    for kp in fc.keyframe_points:
        kp.co[0] += frames
    fc.update()


def period_frames(st):
    return max(int(st.loop_frames), 1)


def ensure_path_enabled(road):
    if road.type not in {"CURVE", "SURFACE"}:
        return False
    data = road.data
    if not hasattr(data, "use_path"):
        return False
    if data.use_path:
        data.use_path = False
    data.use_path = True
    return True


def assign_path(car, road):
    ensure_path_enabled(road)
    con = car.constraints.new("FOLLOW_PATH")
    con.name = "交通路径"
    con.target = road
    con.use_fixed_location = True
    con.use_curve_follow = True
    con.forward_axis = "FORWARD_Y"
    con.up_axis = "UP_Z"
    return con


def build_loop_animation(car, con, period, start_frame):
    period = max(float(period), 1.0)
    start = float(start_frame)
    con.use_fixed_location = True
    con.offset_factor = 0.0
    con.keyframe_insert("offset_factor", frame=start)
    con.offset_factor = 1.0
    con.keyframe_insert("offset_factor", frame=start + period)
    fc = _find_offset_fcurve(car, con)
    if fc is None:
        return None
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
    mod = fc.modifiers.new("CYCLES")
    mod.mode_before = "REPEAT"
    mod.mode_after = "REPEAT"
    fc.update()
    return fc


def _phase_start(st, period, index, count):
    step = 100.0 / (count + 1.0)
    return st.anim_start_frame + period * (index * step / 100.0)


def op_pick_roads(context):
    st = settings(context)
    selected = [o for o in context.selected_objects if o is not None]
    if not selected:
        return CANCELLED, "没有选中任何物体，请先在视图里选中道路曲线"
    st.roads.clear()
    for ob in selected:
        it = st.roads.add()
        it.name = ob.name
        it.icon = "CURVE_DATA" if ob.type in {"CURVE", "SURFACE"} else "OBJECT_DATA"
    st.road_index = len(st.roads) - 1
    _deselect_all(context)
    return FINISHED, "已拾取 %d 条道路" % len(st.roads)


def op_pick_cars(context):
    st = settings(context)
    selected = [o for o in context.selected_objects if o is not None]
    if not selected:
        return CANCELLED, "没有选中任何物体，请先在视图里选中车辆模型"
    st.cars.clear()
    for ob in selected:
        it = st.cars.add()
        it.name = ob.name
        it.icon = "MESH_DATA" if ob.type == "MESH" else "OBJECT_DATA"
    st.car_index = len(st.cars) - 1
    _deselect_all(context)
    return FINISHED, "已拾取 %d 个车辆模板" % len(st.cars)


def op_remove_road(context, index=None):
    st = settings(context)
    if index is None:
        index = st.road_index
    if index < 0 or index >= len(st.roads):
        return CANCELLED, "没有选中要移除的道路"
    st.roads.remove(index)
    st.road_index = min(index, len(st.roads) - 1)
    return FINISHED, "已移除 1 条道路，剩余 %d 条" % len(st.roads)


def op_remove_car(context, index=None):
    st = settings(context)
    if index is None:
        index = st.car_index
    if index < 0 or index >= len(st.cars):
        return CANCELLED, "没有选中要移除的车辆"
    st.cars.remove(index)
    st.car_index = min(index, len(st.cars) - 1)
    return FINISHED, "已移除 1 个车辆模板，剩余 %d 个" % len(st.cars)


def _generate_cars(context, count, templates):
    collection = context.scene.collection

    units = []
    for i in range(count):
        e = bpy.data.objects.new("%s%03d" % (props.PREFIX_UNIT, i + 1), None)
        e.empty_display_type = "PLAIN_AXES"
        e.empty_display_size = 0.3
        e[props.TAG_UNIT] = 1
        e.location = (0.0, 0.0, 0.0)
        collection.objects.link(e)
        units.append(e)

    cars = []
    for i in range(count):
        src = random.choice(templates)
        new = src.copy()
        if src.data is not None:
            new.data = src.data.copy()
        new.name = "%s%03d" % (props.PREFIX_CAR, i + 1)
        new[props.TAG_CAR] = 1
        collection.objects.link(new)
        new.parent = units[i]
        new.matrix_parent_inverse.identity()
        new.location = (0.0, 0.0, 0.0)
        cars.append(new)
    return units, cars


def _remove_cars(cars):
    units = []
    for car in cars:
        parent = car.parent
        if parent is not None and is_unit(parent):
            units.append(parent)

    removed_cars = 0
    for ob in cars:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed_cars += 1
        except Exception:
            pass

    removed_units = 0
    for ob in units:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed_units += 1
        except Exception:
            pass
    return removed_cars, removed_units


def op_compute_paths(context):
    st = settings(context)
    road = current_road(st)
    if road is None:
        return CANCELLED, "请先在「道路」列表里点一条路，作为当前道路"

    count = int(st.car_count)
    if count <= 0:
        return CANCELLED, "车辆数量必须大于 0"
    templates = resolve_names(st.cars)
    if not templates:
        return CANCELLED, "车辆名单为空或物体已不存在，请先拾取车辆"

    removed_cars, removed_units = _remove_cars(cars_on_road(road))
    _units, cars = _generate_cars(context, count, templates)

    period = period_frames(st)
    for i, car in enumerate(cars):
        con = assign_path(car, road)
        build_loop_animation(car, con, period, _phase_start(st, period, i, len(cars)))

    _deselect_all(context)
    if removed_cars or removed_units:
        st.last_report = ("已在「%s」上重建 %d 辆车（原有 %d 辆 / %d 个占位已清掉，"
                          "每辆 %d 帧走完一圈，循环播放）"
                          % (road.name, len(cars), removed_cars, removed_units, period))
    else:
        st.last_report = ("已在「%s」上生成 %d 辆车（每辆 %d 帧走完一圈，循环播放）"
                          % (road.name, len(cars), period))
    return FINISHED, st.last_report


def _apply_offset(cars, amount, period):
    if amount <= 0.0:
        return 0
    changed = 0
    for car in cars:
        cons = _constraints_by_target(car)
        if not cons:
            continue
        fc = _keyframes(car, cons[0])
        if fc is None:
            continue
        delta = random.uniform(-amount, amount)
        _shift_phase_frames(fc, period * delta / 100.0)
        changed += 1
    return changed


def op_offset_all(context):
    st = settings(context)
    amount = float(st.global_offset)
    if amount <= 0.0:
        return CANCELLED, "偏移量为 0，没有变化"
    road = current_road(st)
    if road is None:
        return CANCELLED, "请先在「道路」列表里点一条路，作为当前道路"
    cars = cars_on_road(road)
    if not cars:
        return CANCELLED, "「%s」上还没有车，请先点「计算当前道路」" % road.name
    n = _apply_offset(cars, amount, period_frames(st))
    st.last_report = ("已对「%s」的 %d 辆车施加 ±%.2f%% 随机前后错位"
                      % (road.name, n, amount))
    return FINISHED, st.last_report


def _apply_period(cars, st, period):
    ordered = sorted(cars, key=lambda o: o.name)
    changed = 0
    for i, car in enumerate(ordered):
        cons = _constraints_by_target(car)
        if not cons:
            continue
        if car.animation_data is not None:
            car.animation_data.action = None
        build_loop_animation(car, cons[0], period,
                             _phase_start(st, period, i, len(ordered)))
        changed += 1
    return changed


def op_apply_duration(context):
    st = settings(context)
    road = current_road(st)
    if road is None:
        return CANCELLED, "请先在「道路」列表里点一条路，作为当前道路"
    cars = cars_on_road(road)
    if not cars:
        return CANCELLED, "「%s」上还没有车，请先点「计算当前道路」" % road.name
    period = period_frames(st)
    n = _apply_period(cars, st, period)
    st.last_report = "已把「%s」的 %d 辆车设为 %d 帧走完一圈（循环播放）" % (
        road.name, n, period)
    return FINISHED, st.last_report


def op_clear_all(context):
    st = settings(context)
    road = current_road(st)
    if road is None:
        return CANCELLED, "请先在「道路」列表里点一条路，作为当前道路"

    cars = cars_on_road(road)
    orphans = _orphan_cars()
    if not cars and not orphans:
        st.last_report = "「%s」上没有本插件生成的车" % road.name
        return CANCELLED, st.last_report

    removed_cars, removed_units = _remove_cars(cars + orphans)
    _deselect_all(context)
    st.last_report = "已从「%s」删除 %d 辆车、%d 个占位%s" % (
        road.name, removed_cars, removed_units,
        ("（另清理了 %d 辆无主车）" % len(orphans)) if orphans else "")
    return FINISHED, st.last_report


def _deselect_all(context):
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        for ob in context.view_layer.objects:
            if ob is not None:
                try:
                    ob.select_set(False)
                except Exception:
                    pass


class _TrafficBase:

    bl_options = {"REGISTER", "UNDO"}

    def _report(self, status, msg):
        if msg:
            self.report({"INFO"} if status == FINISHED else {"WARNING"}, msg)
        return {status}


class MF_OT_Traffic_PickRoads(_TrafficBase, Operator):
    bl_idname = OP_PICK_ROADS
    bl_label = "拾取道路"
    bl_description = "把当前选中的物体记入道路列表，然后取消选择"

    def execute(self, context):
        return self._report(*op_pick_roads(context))


class MF_OT_Traffic_PickCars(_TrafficBase, Operator):
    bl_idname = OP_PICK_CARS
    bl_label = "拾取车辆"
    bl_description = "把当前选中的物体记入车辆列表，然后取消选择"

    def execute(self, context):
        return self._report(*op_pick_cars(context))


class MF_OT_Traffic_RemoveRoad(_TrafficBase, Operator):
    bl_idname = OP_REMOVE_ROAD
    bl_label = "移除选中道路"
    bl_description = "从道路列表中移除当前选中的那一条"

    index: IntProperty(default=-1)

    def execute(self, context):
        idx = self.index if self.index >= 0 else None
        return self._report(*op_remove_road(context, idx))


class MF_OT_Traffic_RemoveCar(_TrafficBase, Operator):
    bl_idname = OP_REMOVE_CAR
    bl_label = "移除选中车辆"
    bl_description = "从车辆列表中移除当前选中的那一个"

    index: IntProperty(default=-1)

    def execute(self, context):
        idx = self.index if self.index >= 0 else None
        return self._report(*op_remove_car(context, idx))


class MF_OT_Traffic_ActivateRoad(_TrafficBase, Operator):
    bl_idname = OP_ACTIVATE_ROAD
    bl_label = "设为当前道路"
    bl_description = "把这一条设为当前道路（决定「移除选中道路」删的是哪一条）"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0)

    def execute(self, context):
        settings(context).road_index = self.index
        return {"FINISHED"}


class MF_OT_Traffic_ActivateCar(_TrafficBase, Operator):
    bl_idname = OP_ACTIVATE_CAR
    bl_label = "设为当前车辆"
    bl_description = "把这一个设为当前车辆模板"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0)

    def execute(self, context):
        settings(context).car_index = self.index
        return {"FINISHED"}


class MF_OT_Traffic_Compute(_TrafficBase, Operator):
    bl_idname = OP_COMPUTE
    bl_label = "计算当前道路"
    bl_description = ("给「当前道路」重建一套车流：清掉这条路上原有的车，"
                      "按车辆数量重新生成并铺路（同一条路上的车均匀铺开、同速循环）。"
                      "只动当前道路，别条路上的车不受影响")

    def execute(self, context):
        return self._report(*op_compute_paths(context))


class MF_OT_Traffic_OffsetAll(_TrafficBase, Operator):
    bl_idname = OP_OFFSET_ALL
    bl_label = "整体前后偏移"
    bl_description = "给「当前道路」上的车叠一个随机前后错位，每次点击都在现值上累加"

    def execute(self, context):
        return self._report(*op_offset_all(context))


class MF_OT_Traffic_ApplyDuration(_TrafficBase, Operator):
    bl_idname = OP_APPLY_DURATION
    bl_label = "应用循环时长"
    bl_description = ("按「起始帧 / 走完一圈帧数」重铺「当前道路」上的循环动画；"
                      "这条路上的车同一帧数（同速），相位按顺序重新错开")

    def execute(self, context):
        return self._report(*op_apply_duration(context))


class MF_OT_Traffic_ClearAll(_TrafficBase, Operator):
    bl_idname = OP_CLEAR_ALL
    bl_label = "删除当前道路的车"
    bl_description = "删除挂在「当前道路」上的全部车辆实例与占位 Empty（别条路不受影响）"

    def execute(self, context):
        return self._report(*op_clear_all(context))


classes = (
    MF_OT_Traffic_PickRoads,
    MF_OT_Traffic_PickCars,
    MF_OT_Traffic_RemoveRoad,
    MF_OT_Traffic_RemoveCar,
    MF_OT_Traffic_ActivateRoad,
    MF_OT_Traffic_ActivateCar,
    MF_OT_Traffic_Compute,
    MF_OT_Traffic_OffsetAll,
    MF_OT_Traffic_ApplyDuration,
    MF_OT_Traffic_ClearAll,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
