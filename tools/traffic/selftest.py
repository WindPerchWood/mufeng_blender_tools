
import ast
import importlib
import os
import re
import sys
import traceback

import bpy

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

PKG = os.path.basename(THIS_DIR)

PROD_FILES = ("operators.py", "ui.py", "props.py")

SCENE_ATTR = "mf_traffic"


class Checker:
    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, name, cond):
        if cond:
            self.passed += 1
        else:
            self.failed.append(name)

    def eq(self, name, got, want):
        if got == want:
            self.passed += 1
        else:
            self.failed.append("%s  (得到 %r，期望 %r)" % (name, got, want))

    def report(self):
        total = self.passed + len(self.failed)
        print("\n" + "=" * 62)
        if self.failed:
            print("[FAIL] 自检结果：%d/%d 通过，%d 项失败" % (
                self.passed, total, len(self.failed)))
            for name in self.failed:
                print("   ✗ " + name)
        else:
            print("[OK] 自检结果：%d/%d 全部通过" % (self.passed, total))
        print("=" * 62 + "\n")
        return len(self.failed)


class FakeLayout:
    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.enabled = True
        self.alignment = "LEFT"

    def _sub(self):
        return FakeLayout(self.log)

    def row(self, align=False):
        self.log.append(("row", align))
        return self._sub()

    def column(self, align=False):
        self.log.append(("column", align))
        return self._sub()

    def box(self):
        self.log.append(("box",))
        return self._sub()

    def separator(self, factor=1.0):
        self.log.append(("separator", factor))

    def label(self, text="", icon=None, **kw):
        self.log.append(("label", text, icon))

    def prop(self, data, name, **kw):
        self.log.append(("prop", name, kw))

    def operator(self, idname, **kw):
        self.log.append(("operator", idname, kw))
        return _FakeOpProps()

    def template_list(self, *a, **kw):
        raise AssertionError("面板不该再使用 template_list（底部会有关不掉的 ▶ 行）")


class _FakeOpProps:
    def __init__(self):
        self.index = -1

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)


class FakePanel:
    def __init__(self, layout, owner):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        attr = getattr(self._owner, name)
        if isinstance(attr, staticmethod):
            return attr.__func__
        return attr.__get__(self, type(self))


def make_road(name, closed=True):
    cu = bpy.data.curves.new(name + "_curve", "CURVE")
    cu.dimensions = "2D"
    sp = cu.splines.new("POLY")
    pts = [(0, 0, 0, 1), (20, 0, 0, 1), (20, 20, 0, 1), (0, 20, 0, 1)]
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = p
    sp.use_cyclic_u = closed
    cu.use_fill_caps = True
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def make_car_template(name):
    m = bpy.data.meshes.new(name + "_mesh")
    m.from_pydata([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new(name, m)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def select_only(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


def st():
    return getattr(bpy.context.scene, SCENE_ATTR)


def _ops():
    return importlib.import_module(PKG + ".operators")


def all_units():
    ops = _ops()
    return [o for o in bpy.data.objects if ops.is_unit(o)]


def fcurve_of(ob):
    ops = _ops()
    cons = [x for x in ob.constraints if x.type == "FOLLOW_PATH"]
    if not cons:
        return None
    return ops._find_offset_fcurve(ob, cons[0])


def keystart_of(ob):
    fc = fcurve_of(ob)
    if fc is None or not len(fc.keyframe_points):
        return None
    return fc.keyframe_points[0].co[0]


def keyspan_of(ob):
    fc = fcurve_of(ob)
    if fc is None or len(fc.keyframe_points) < 2:
        return None
    k = fc.keyframe_points
    return k[-1].co[0] - k[0].co[0]


def op_registered(short):
    try:
        getattr(bpy.ops.mf, short).get_rna_type()
        return True
    except Exception:
        return False


def _src(fn):
    return open(os.path.join(THIS_DIR, fn), encoding="utf-8").read()


def _strip_comments(src):
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(ln.split("#")[0] for ln in src.splitlines())


def _func_body(code, name):
    m = re.search(r"\ndef %s\(\):([\s\S]*?)(?=\ndef |\Z)" % name, code)
    return m.group(1) if m else ""


def t_syntax(C):
    names = sorted(n for n in os.listdir(THIS_DIR) if n.endswith(".py"))
    C.check("确实扫到了 py 文件（守卫非空跑）", len(names) >= 4)
    for n in names:
        try:
            ast.parse(open(os.path.join(THIS_DIR, n), encoding="utf-8").read())
            ok, err = True, ""
        except SyntaxError as exc:
            ok, err = False, "第 %s 行: %s" % (exc.lineno, exc.msg)
        C.check("%s 语法正确%s" % (n, (" —— " + err) if not ok else ""), ok)


def t_contract(C, root):
    for fn in ("__init__.py", "operators.py", "ui.py"):
        C.check("模板必备文件存在：%s" % fn,
                os.path.exists(os.path.join(THIS_DIR, fn)))
    C.check("目录名是小写英文/下划线",
            re.fullmatch(r"[a-z][a-z0-9_]*", PKG) is not None)
    C.check("__init__ 有 register()", callable(getattr(root, "register", None)))
    C.check("__init__ 有 unregister()", callable(getattr(root, "unregister", None)))
    C.check("子包不写 bl_info（由根插件统一提供）", not hasattr(root, "bl_info"))

    for fn in PROD_FILES:
        code = _strip_comments(_src(fn))
        C.check("%s 用三层相对导入拿 core.utils" % fn,
                "from ...core import utils" in code)
        C.check("%s 的 core 导入有降级兜底" % fn,
                "except (ImportError, ValueError)" in code)
        C.check("%s 的 register() 走 utils.register_classes" % fn,
                "utils.register_classes" in _func_body(code, "register"))
        C.check("%s 的 unregister() 走 utils.unregister_classes" % fn,
                "utils.unregister_classes" in _func_body(code, "unregister"))

    ui_code = _strip_comments(_src("ui.py"))
    C.check("面板继承 utils.MF_ToolPanel",
            "class MF_PT_Traffic(utils.MF_ToolPanel)" in ui_code)
    C.check("面板分类用 utils.PANEL_CATEGORY",
            "bl_category = utils.PANEL_CATEGORY" in ui_code)
    C.check("面板默认折叠",
            re.search(r"bl_options\s*=\s*\{[\"']DEFAULT_CLOSED[\"']\}", ui_code) is not None)
    C.check("面板写了 draw_header", "def draw_header" in ui_code)
    C.check("draw_header 里给了图标",
            re.search(r"def draw_header[\s\S]{0,300}?icon=", ui_code) is not None)
    C.check("面板有 MF_SEARCH_KEYWORDS",
            re.search(r"MF_SEARCH_KEYWORDS\s*=\s*\(", ui_code) is not None)

    m = re.search(r"bl_order\s*=\s*(-?\d+)", ui_code)
    order = int(m.group(1)) if m else None
    C.check("面板写了 bl_order 且 >= 16（-100 搜索条，2~15 已被占用）",
            order is not None and order >= 16)

    C.check("draw 里不做 bl_rna 自省（重载后会画面板断掉）",
            "bl_rna" not in ui_code)
    C.check("面板不用 template_list", "template_list" not in ui_code)

    ops_code = _strip_comments(_src("operators.py"))
    C.check("算子文件有 TOOL_ID 常量",
            re.search(r"TOOL_ID\s*=\s*[\"']Traffic[\"']", ops_code) is not None)
    C.check("算子 idname 走 mf.{TOOL_ID.lower()}_ 模板",
            'f"mf.{TOOL_ID.lower()}_' in ops_code)
    C.check("算子文件没有裸写 register_class 的 register()",
            "bpy.utils.register_class" not in _func_body(ops_code, "register"))


def t_units(C, ops, props):
    p = st()
    prop = props.MF_PG_TrafficSettings.bl_rna.properties["loop_frames"]
    lo = getattr(prop, "hard_min", getattr(prop, "min", 1))
    C.eq("loop_frames 的下限是 1 帧", int(lo), 1)

    for v in (1, 75, 240, 5000):
        p.loop_frames = v
        C.eq("%d 帧原样取用" % v, ops.period_frames(p), v)
    p.loop_frames = 75


def t_registration(C, ops, props, ui):
    C.eq("props 里的 Scene 属性名是 mf_traffic", props.SCENE_ATTR, SCENE_ATTR)
    rna = set(props.MF_PG_TrafficSettings.bl_rna.properties.keys())
    for want in ("car_count", "global_offset", "anim_start_frame",
                 "loop_frames",
                 "roads", "cars", "road_index", "car_index",
                 "last_report", "show_report"):
        C.check("属性组里有 %s" % want, want in rna)
    C.check("Scene 上挂了 mf_traffic 属性", hasattr(bpy.context.scene, SCENE_ATTR))

    p = st()
    C.eq("car_count 默认 10", p.car_count, 10)
    C.eq("global_offset 默认 0", p.global_offset, 0.0)
    C.eq("anim_start_frame 默认 1", p.anim_start_frame, 1)
    C.eq("loop_frames 默认 75 帧", p.loop_frames, 75)
    C.eq("road_index 默认 -1", p.road_index, -1)
    C.eq("car_index 默认 -1", p.car_index, -1)
    C.eq("show_report 默认 True", p.show_report, True)

    C.check("入口名单项类已注册",
            props.MF_PG_TrafficItem.bl_rna is not None)
    C.check("面板类已注册", hasattr(bpy.types, "MF_PT_Traffic"))

    for short in ("traffic_pick_roads", "traffic_pick_cars",
                  "traffic_remove_road", "traffic_remove_car",
                  "traffic_activate_road", "traffic_activate_car",
                  "traffic_compute", "traffic_offset_all",
                  "traffic_apply_duration", "traffic_clear_all"):
        C.check("算子 mf.%s 已注册" % short, op_registered(short))

    for cls in ops.classes:
        C.check("算子类名以 MF_OT_Traffic_ 开头：%s" % cls.__name__,
                cls.__name__.startswith("MF_OT_Traffic_"))
        C.check("算子 idname 以 mf.traffic_ 开头：%s" % cls.bl_idname,
                cls.bl_idname.startswith("mf.traffic_"))
        C.check("算子有 bl_description：%s" % cls.__name__,
                bool(getattr(cls, "bl_description", "")))
        C.check("算子没有 invoke()（不留对话框残留）：%s" % cls.__name__,
                "invoke" not in cls.__dict__)

    pm = ui.MF_PT_Traffic
    tool_utils = getattr(ui, "utils")
    C.eq("面板分类等于 utils.PANEL_CATEGORY", pm.bl_category,
         tool_utils.PANEL_CATEGORY)
    C.eq("面板在 3D 视图", pm.bl_space_type, "VIEW_3D")
    C.eq("面板在侧栏区域", pm.bl_region_type, "UI")
    C.check("面板有可读标题", bool(pm.bl_label))
    C.eq("面板标题与源码一致（重构未擅自改名）", pm.bl_label, "车辆道路生成系统")
    C.check("面板有一组搜索别名", len(pm.MF_SEARCH_KEYWORDS) >= 3)


def t_pick(C, ops):
    clear_scene()
    p = st()
    p.roads.clear()
    p.cars.clear()

    bpy.ops.object.select_all(action="DESELECT")
    status, msg = ops.op_pick_roads(bpy.context)
    C.eq("无选中时拾取道路返回 CANCELLED", status, ops.CANCELLED)
    C.check("无选中时给出可读提示", bool(msg))

    road = make_road("road_A")
    road_b = make_road("road_B")
    select_only([road, road_b])
    status, msg = ops.op_pick_roads(bpy.context)
    C.eq("拾取道路成功", status, ops.FINISHED)
    C.eq("道路名单记了 2 条", len(p.roads), 2)
    C.eq("道路名正确", p.roads[0].name, "road_A")
    C.eq("道路图标按类型写入", p.roads[0].icon, "CURVE_DATA")
    C.check("拾取后已取消选择",
            not any(o.select_get() for o in bpy.context.view_layer.objects))

    tpl = make_car_template("car_A")
    tpl_b = make_car_template("car_B")
    tpl_c = make_car_template("car_C")
    select_only([tpl, tpl_b, tpl_c])
    status, msg = ops.op_pick_cars(bpy.context)
    C.eq("拾取车辆成功", status, ops.FINISHED)
    C.eq("车辆名单记了 3 个", len(p.cars), 3)
    C.eq("车辆图标按类型写入", p.cars[0].icon, "MESH_DATA")


def t_remove(C, ops):
    p = st()
    before = len(p.cars)
    p.car_index = 0
    status, _ = ops.op_remove_car(bpy.context)
    C.eq("移除车辆成功", status, ops.FINISHED)
    C.eq("车辆名单减少 1", len(p.cars), before - 1)

    before = len(p.roads)
    p.road_index = 0
    status, msg = ops.op_remove_road(bpy.context)
    C.eq("移除道路成功", status, ops.FINISHED)
    C.eq("道路名单减少 1", len(p.roads), before - 1)

    p.road_index = 99
    status, msg = ops.op_remove_road(bpy.context)
    C.eq("索引越界时拒绝移除", status, ops.CANCELLED)

    p.car_index = 99
    status, _ = ops.op_remove_car(bpy.context)
    C.eq("车辆索引越界时拒绝移除", status, ops.CANCELLED)


def t_generate(C, ops):
    clear_scene()
    p = st()
    p.roads.clear()
    p.cars.clear()

    road = make_road("road_A")
    tpl = make_car_template("car_A")
    select_only([road])
    ops.op_pick_roads(bpy.context)
    select_only([tpl])
    ops.op_pick_cars(bpy.context)

    p.car_count = 8
    templates = ops.resolve_names(p.cars)
    C.eq("车辆模板解析出 1 个", len(templates), 1)
    units, cars = ops._generate_cars(bpy.context, 8, templates)

    C.eq("占位 Empty 数量 == 车辆数量", len(units), 8)
    C.eq("车辆实例数量 == 车辆数量", len(cars), 8)
    C.check("占位名字带 mf_unit_ 前缀",
            all(o.name.startswith("mf_unit_") for o in units))
    C.check("实例名字带 mf_car_ 前缀",
            all(o.name.startswith("mf_car_") for o in cars))

    C.check("每辆车都有父级", all(c.parent is not None for c in cars))
    C.check("父级都是占位 Empty", all(ops.is_unit(c.parent) for c in cars))
    C.check("占位自身无数据（是 Empty）", all(o.data is None for o in units))

    meshes = {c.data.as_pointer() for c in cars}
    C.eq("每辆车有独立的网格数据块", len(meshes), 8)

    C.check("占位 Empty 都在原点（防父级平移污染路径）",
            all(o.location.length < 1e-6 for o in units))
    C.check("车辆局部位置已归零",
            all(c.location.length < 1e-6 for c in cars))
    C.check("车辆父级逆矩阵是单位阵",
            all(all(abs(c.matrix_parent_inverse[r][k] - (1.0 if r == k else 0.0)) < 1e-6
                    for r in range(4) for k in range(4)) for c in cars))
    C.eq("生成出来的都是本插件认得的车",
         len(ops.all_generated_cars()), 8)


def t_compute(C, ops):
    clear_scene()
    p = st()
    p.roads.clear()
    p.cars.clear()
    road = make_road("road_A")
    tpl = make_car_template("car_A")
    select_only([road])
    ops.op_pick_roads(bpy.context)
    select_only([tpl])
    ops.op_pick_cars(bpy.context)

    p.car_count = 8
    p.anim_start_frame = 1
    p.loop_frames = 150

    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("计算当前道路成功", status, ops.FINISHED)
    C.check("回执里带了道路名（%r）" % (msg,), road.name in str(msg))

    cars = ops.cars_on_road(road)
    C.eq("这条路上正好 8 辆车", len(cars), 8)
    C.eq("场景里没有别的车（刚生成的都挂在这条路上）",
         len(ops.all_generated_cars()), 8)
    period = ops.period_frames(p)

    for c in cars:
        cons = [x for x in c.constraints if x.type == "FOLLOW_PATH"]
        C.check("%s 有且仅有一个 Follow Path 约束" % c.name, len(cons) == 1)
        if not cons:
            continue
        con = cons[0]
        C.check("%s 的约束指向道路" % c.name, con.target == road)
        C.check("%s use_fixed_location 已开" % c.name, con.use_fixed_location)
        C.check("%s use_curve_follow 已开" % c.name, con.use_curve_follow)
        C.eq("%s forward_axis 为 FORWARD_Y" % c.name, con.forward_axis, "FORWARD_Y")
        C.eq("%s up_axis 为 UP_Z" % c.name, con.up_axis, "UP_Z")
        fc = ops._find_offset_fcurve(c, con)
        ks = fc.keyframe_points if fc is not None else []
        C.check("%s 的关键帧跨越一个周期（实得 %s，期望 %d 帧）"
                % (c.name, [round(k.co[0], 3) for k in ks], period),
                len(ks) == 2
                and abs((ks[-1].co[0] - ks[0].co[0]) - period) < 1e-3)
        C.check("%s 的 offset 走完整条路 0 → 1（实得 %s）"
                % (c.name, [round(k.co[1], 4) for k in ks]),
                len(ks) == 2 and abs(ks[0].co[1]) < 1e-6
                and abs(ks[-1].co[1] - 1.0) < 1e-6)
        mods = list(fc.modifiers) if fc is not None else []
        C.check("%s 挂着 CYCLES 循环修饰器" % c.name,
                [m.type for m in mods] == ["CYCLES"])
        C.check("%s 循环模式是 REPEAT（不是 REPEAT_OFFSET，开放路径才不会被送出去）"
                % c.name,
                all(m.mode_before == "REPEAT" and m.mode_after == "REPEAT"
                    for m in mods))

    step = 100.0 / (8 + 1.0)
    starts = [keystart_of(c) for c in cars]
    C.check("8 辆车的出发相位按顺序均匀错开（实得 %s）"
            % [round(s, 2) for s in starts],
            all(abs((starts[i] - starts[0]) - period * (i * step / 100.0)) < 0.01
                for i in range(len(starts))))
    C.check("相位都落在一个周期之内（实得最大偏移 %.2f 帧）"
            % (starts[-1] - starts[0]),
            0.0 <= (starts[-1] - starts[0]) < period)

    p.roads.clear()
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("没有当前道路时返回 CANCELLED", status, ops.CANCELLED)
    C.check("拒绝时给出可读提示", bool(msg))
    C.eq("拒绝时一辆车都没动", len(ops.cars_on_road(road)), 8)
    select_only([road])
    ops.op_pick_roads(bpy.context)


def t_compute_rebuild(C, ops):
    p = st()
    road = bpy.data.objects.get("road_A")
    C.check("前置条件：当前道路上有车", len(ops.cars_on_road(road)) > 0)

    p.car_count = 5
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("重建成功", status, ops.FINISHED)
    C.eq("数量跟着 car_count 变成 5", len(ops.cars_on_road(road)), 5)
    C.eq("占位也正好 5 个", len(all_units()), 5)
    C.eq("没留下孤儿车（场景里只有这 5 辆）", len(ops.all_generated_cars()), 5)
    C.check("回执里带了道路名（%r）" % (msg,), road.name in str(msg))

    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("再点一次仍成功", status, ops.FINISHED)
    C.eq("数量不变（不会越点越多）", len(ops.cars_on_road(road)), 5)

    names_before = [it.name for it in p.cars]
    p.cars.clear()
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("车辆名单为空时返回 CANCELLED", status, ops.CANCELLED)
    C.eq("拒绝时不会动场景里的车", len(ops.cars_on_road(road)), 5)

    p.car_count = 0
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("车辆数量为 0 时返回 CANCELLED", status, ops.CANCELLED)
    C.eq("拒绝时同样不动场景里的车", len(ops.cars_on_road(road)), 5)

    for nm in names_before:
        p.cars.add().name = nm
    p.car_count = 8
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("收尾：恢复 8 辆成功", status, ops.FINISHED)
    C.eq("收尾：确实 8 辆", len(ops.cars_on_road(road)), 8)


def t_multi_set(C, ops):
    clear_scene()
    p = st()
    p.roads.clear()
    p.cars.clear()
    road_a = make_road("set_A")
    road_b = make_road("set_B")
    tpl = make_car_template("car_tpl")
    select_only([road_a, road_b])
    ops.op_pick_roads(bpy.context)
    select_only([tpl])
    ops.op_pick_cars(bpy.context)
    C.eq("道路列表里有两条路", len(p.roads), 2)

    def starts_of(cars):
        return sorted(round(keystart_of(c), 3) for c in cars)

    def span_of_first(cars):
        return round(keyspan_of(cars[0]), 3)

    p.road_index = 0
    p.car_count = 4
    p.loop_frames = 100
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("在路 A 上建第一套成功", status, ops.FINISHED)
    cars_a = ops.cars_on_road(road_a)
    C.eq("路 A 上 4 辆车", len(cars_a), 4)
    C.eq("路 A 的周期是 100 帧", span_of_first(cars_a), 100.0)
    a_starts_before = starts_of(cars_a)
    a_names_before = sorted(c.name for c in cars_a)

    p.road_index = 1
    p.car_count = 6
    p.loop_frames = 200
    status, msg = ops.op_compute_paths(bpy.context)
    C.eq("在路 B 上建第二套成功", status, ops.FINISHED)
    cars_b = ops.cars_on_road(road_b)
    C.eq("路 B 上 6 辆车", len(cars_b), 6)
    C.eq("路 B 的周期是 200 帧", span_of_first(cars_b), 200.0)
    C.eq("路 A 的车一辆没少、没被重建",
         sorted(c.name for c in ops.cars_on_road(road_a)), a_names_before)
    C.eq("路 A 的关键帧起点一点没动（相位没被打乱）",
         starts_of(ops.cars_on_road(road_a)), a_starts_before)
    C.eq("路 A 的周期仍是 100 帧", span_of_first(ops.cars_on_road(road_a)), 100.0)
    C.eq("两套合起来 10 辆车", len(ops.all_generated_cars()), 10)

    p.road_index = 1
    p.loop_frames = 50
    status, _ = ops.op_apply_duration(bpy.context)
    C.eq("只调当前道路（B）的速度成功", status, ops.FINISHED)
    C.eq("路 B 变成 50 帧", span_of_first(ops.cars_on_road(road_b)), 50.0)
    C.eq("路 A 仍是 100 帧（没被连带）",
         span_of_first(ops.cars_on_road(road_a)), 100.0)

    status, msg = ops.op_clear_all(bpy.context)
    C.eq("删除当前道路的车成功", status, ops.FINISHED)
    C.eq("路 B 清空", len(ops.cars_on_road(road_b)), 0)
    C.eq("路 A 完好无损（4 辆还在）", len(ops.cars_on_road(road_a)), 4)
    C.eq("占位也只剩 A 那 4 个", len(all_units()), 4)

    p.roads.clear()
    for label, fn in (("计算", ops.op_compute_paths),
                      ("调速", ops.op_apply_duration),
                      ("偏移", ops.op_offset_all),
                      ("删除", ops.op_clear_all)):
        p.global_offset = 5.0
        status, msg = fn(bpy.context)
        C.eq("没选道路时「%s」返回 CANCELLED" % label, status, ops.CANCELLED)
    C.eq("拒绝期间路 A 的车没被动", len(ops.cars_on_road(road_a)), 4)

    select_only([road_a])
    ops.op_pick_roads(bpy.context)
    p.global_offset = 0.0
    ops.op_clear_all(bpy.context)


def t_cars_ride_the_path(C, ops):
    p = st()
    road = bpy.data.objects.get("road_A")
    cars = ops.cars_on_road(road)
    if not cars:
        C.check("端到端：当前道路上有车可测", False)
        return

    p.anim_start_frame = 1
    p.loop_frames = 150
    ops.op_apply_duration(bpy.context)
    period = ops.period_frames(p)

    dg = bpy.context.evaluated_depsgraph_get()

    def positions(frame):
        bpy.context.scene.frame_set(frame)
        dg.update()
        return [c.evaluated_get(dg).matrix_world.translation.copy() for c in cars]

    def max_shift(f1, f2):
        a, b = positions(f1), positions(f2)
        return max((a[i] - b[i]).length for i in range(len(a)))

    def min_gap(pts):
        best = None
        for i in range(len(pts)):
            for k in range(i + 1, len(pts)):
                d = (pts[i] - pts[k]).length
                if best is None or d < best:
                    best = d
        return best

    half = max(period // 2, 1)
    C.check("中途真的在跑（帧 1 → 帧 %d 最大位移 %.4f）" % (half, max_shift(1, half)),
            max_shift(1, half) > 1e-2)
    C.check("走满一个周期（%d 帧）后回到起点（帧 1 与帧 %d 最大位移 %.6f）"
            % (period, 1 + period, max_shift(1, 1 + period)),
            max_shift(1, 1 + period) < 1e-4)
    C.check("第二个周期仍在走（帧 %d → 帧 %d 最大位移 %.4f）"
            % (1 + period, 1 + period + half,
               max_shift(1 + period, 1 + period + half)),
            max_shift(1 + period, 1 + period + half) > 1e-2)

    on_path, gaps = [], {}
    for f in (1, 1 + half, 1 + period, 1 + period + half, 1 + 2 * period):
        pts = positions(f)
        for i, v in enumerate(pts):
            if not (-0.01 <= v.x <= 20.01 and -0.01 <= v.y <= 20.01):
                on_path.append((f, cars[i].name, round(v.x, 2), round(v.y, 2)))
        gaps[f] = min_gap(pts)
    C.eq("任何一帧车辆都在道路范围内（循环也没把它们送出去）", on_path, [])
    C.check("全程任意两辆车都不重叠 —— 各帧最小间距 %s"
            % {k: round(v, 2) for k, v in gaps.items()},
            all(v > 0.5 for v in gaps.values()))

    bpy.context.scene.frame_set(bpy.context.scene.frame_start)


def t_path_cache_poison(C, ops):
    main_scene = bpy.context.scene
    saved_gen = list(ops.all_generated_cars())
    saved_units = list(all_units())
    scratch = bpy.data.scenes.new("_traf_poison_scratch")
    bpy.context.window.scene = scratch
    try:
        road = make_road("poison_road")
        dg0 = bpy.context.evaluated_depsgraph_get()
        dg0.update()
        C.check("毒化前 use_path 为 False", road.data.use_path is False)

        car = make_car_template("poison_car")
        ops.ensure_path_enabled(road)
        poison_con = ops.assign_path(car, road)
        poison_con.offset_factor = 0.5

        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        pos = car.evaluated_get(dg).matrix_world.translation
        C.check("被毒化过的道路，挂上约束后车辆仍落在路径上（非原点）",
                pos.length > 1e-3)
        C.check("位置落在方块四角之一（证明确实骑在路径上）",
                (abs(pos.x) < 0.5 or abs(pos.x - 20.0) < 0.5)
                and (abs(pos.y) < 0.5 or abs(pos.y - 20.0) < 0.5))

        C.check("ensure_path_enabled 对曲线返回 True",
                ops.ensure_path_enabled(road) is True)
        C.check("ensure_path_enabled 对非曲线返回 False",
                ops.ensure_path_enabled(car) is False)

        corners = set()
        for i in range(4):
            c = make_car_template("poison_c%d" % i)
            corner_con = ops.assign_path(c, road)
            corner_con.offset_factor = i / 4.0
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            q = c.evaluated_get(dg).matrix_world.translation
            corners.add((round(q.x), round(q.y), round(q.z)))
        C.check("四个相位覆盖方块四角（缓存已正确重建）",
                {(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0)} == corners)
    finally:
        bpy.context.window.scene = main_scene
        bpy.data.scenes.remove(scratch, do_unlink=True)

    C.check("毒化回归测试后主场景车辆数不变",
            len(ops.all_generated_cars()) == len(saved_gen))
    C.check("毒化回归测试后主场景占位数不变",
            len(all_units()) == len(saved_units))


def t_offset(C, ops):
    p = st()
    road = bpy.data.objects.get("road_A")
    cars = ops.cars_on_road(road)
    target = cars[0]
    period = ops.period_frames(p)

    before = keystart_of(target)

    p.global_offset = 5.0
    status, _ = ops.op_offset_all(bpy.context)
    C.eq("整体偏移成功", status, ops.FINISHED)
    after1 = keystart_of(target)
    C.check("偏移后相位确实变了（实得 %.3f 帧）" % (after1 - before),
            abs(after1 - before) > 1e-6)
    C.check("偏移量不超过 ±5%% 的周期（实得 %.3f 帧，上限 %.3f）"
            % (after1 - before, period * 0.05),
            abs(after1 - before) <= period * 0.05 + 1e-3)

    p.global_offset = 5.0
    ops.op_offset_all(bpy.context)
    after2 = keystart_of(target)
    C.check("第二次偏移仍在现值上累加（实得 %.3f 帧）" % (after2 - after1),
            abs(after2 - after1) > 1e-6)
    C.check("第二次偏移量同样不超过 ±5% 周期",
            abs(after2 - after1) <= period * 0.05 + 1e-3)

    before_all = {c.name: keystart_of(c) for c in cars}
    p.global_offset = 5.0
    ops.op_offset_all(bpy.context)
    moved = [c.name for c in cars if abs(keystart_of(c) - before_all[c.name]) > 1e-6]
    C.eq("偏移作用于全部车辆", len(moved), len(cars))

    p.global_offset = 0.0
    status, _ = ops.op_offset_all(bpy.context)
    C.eq("偏移量为 0 时返回 CANCELLED", status, ops.CANCELLED)

    C.check("偏移不会改动周期长度（实得 %s）" % [round(keyspan_of(c), 2) for c in cars],
            all(abs(keyspan_of(c) - period) < 1e-3 for c in cars))


def t_duration(C, ops):
    p = st()
    road = bpy.data.objects.get("road_A")
    cars = ops.cars_on_road(road)

    probe = make_car_template("dur_probe")
    probe_con = ops.assign_path(probe, road)
    fc = ops.build_loop_animation(probe, probe_con, 30, 10)
    k = fc.keyframe_points
    C.check("build_loop_animation：关键帧落在 10 / 40 帧（实得 %s）"
            % [round(x.co[0], 3) for x in k],
            len(k) == 2 and abs(k[0].co[0] - 10.0) < 1e-3
            and abs(k[-1].co[0] - 40.0) < 1e-3)
    C.check("build_loop_animation：offset 走完整条路 0 → 1（实得 %s）"
            % [round(x.co[1], 4) for x in k],
            abs(k[0].co[1]) < 1e-6 and abs(k[-1].co[1] - 1.0) < 1e-6)
    cyc = [m for m in fc.modifiers if m.type == "CYCLES"]
    C.check("build_loop_animation：挂了一个 CYCLES 修饰器", len(cyc) == 1)
    C.check("build_loop_animation：模式是 REPEAT（不是 REPEAT_OFFSET）",
            bool(cyc) and cyc[0].mode_before == "REPEAT"
            and cyc[0].mode_after == "REPEAT")
    C.check("build_loop_animation：插值为 LINEAR（全程匀速）",
            all(x.interpolation == "LINEAR" for x in k))
    bpy.data.objects.remove(probe, do_unlink=True)

    p.loop_frames = 60
    C.eq("填 60 帧就是 60 帧", ops.period_frames(p), 60)
    p.loop_frames = 240
    C.eq("填 240 帧就是 240 帧", ops.period_frames(p), 240)

    p.anim_start_frame = 1
    p.loop_frames = 120
    period = ops.period_frames(p)
    status, msg = ops.op_apply_duration(bpy.context)
    C.eq("应用循环时长成功", status, ops.FINISHED)
    C.check("回执里写了帧数（%r）" % (msg,), ("%d 帧" % period) in str(msg))

    spans, starts = [], []
    for c in cars:
        fc = fcurve_of(c)
        if fc is None:
            spans.append(None)
            starts.append(None)
            continue
        ks = fc.keyframe_points
        spans.append(round(ks[-1].co[0] - ks[0].co[0], 3))
        starts.append(round(ks[0].co[0], 3))
    C.eq("每辆车的一个周期都等于 %d 帧（实得 %r）" % (period, spans),
         len(set(spans)), 1)
    C.eq("周期数值正确", spans[0], float(period))
    C.eq("出发相位互不相同", len(set(starts)), len(starts))
    C.check("出发相位按顺序递增（实得 %r）" % (starts,), starts == sorted(starts))
    C.check("第一辆车从起始帧出发（实得 %.3f）" % starts[0],
            abs(starts[0] - 1.0) < 1e-3)
    C.check("最后一个相位仍在一个周期之内（实得 %.2f 帧）" % (starts[-1] - starts[0]),
            0.0 < (starts[-1] - starts[0]) < period)

    p.loop_frames = 75
    status, msg = ops.op_apply_duration(bpy.context)
    C.eq("收尾：恢复默认 75 帧成功", status, ops.FINISHED)
    C.eq("收尾：周期就是 75 帧", ops.period_frames(p), 75)


def t_clear(C, ops):
    road = bpy.data.objects.get("road_A")
    C.check("前置条件：当前道路上有车", len(ops.cars_on_road(road)) > 0)

    status, msg = ops.op_clear_all(bpy.context)
    C.eq("删除当前道路的车成功", status, ops.FINISHED)
    C.eq("这条路清空了", len(ops.cars_on_road(road)), 0)
    C.eq("占位也清了", len(all_units()), 0)
    C.check("回执里带了道路名（%r）" % (msg,), road.name in str(msg))

    status, msg = ops.op_clear_all(bpy.context)
    C.eq("再次删除返回 CANCELLED（这条路上没车了）", status, ops.CANCELLED)
    C.check("再次删除给出可读提示", bool(msg))

    decoy = bpy.data.objects.new("mf_unit_用户自己的", None)
    bpy.context.scene.collection.objects.link(decoy)
    ops.op_clear_all(bpy.context)
    C.check("不按名字猜：用户同名物体未被误删",
            bpy.data.objects.get("mf_unit_用户自己的") is not None)
    bpy.data.objects.remove(decoy, do_unlink=True)


def t_unique_item(C, ops):
    clear_scene()
    p = st()
    p.roads.clear()
    p.cars.clear()

    road = make_road("r")
    tpl = make_car_template("c")
    select_only([road])
    ops.op_pick_roads(bpy.context)
    select_only([tpl])
    ops.op_pick_cars(bpy.context)
    p.car_count = 4
    ops._generate_cars(bpy.context, p.car_count, ops.resolve_names(p.cars))

    names = [c.name for c in ops.all_generated_cars()]
    C.eq("生成的名字互不重复", len(set(names)), len(names))
    C.check("名字按序号连续", names == sorted(names))

    C.eq("这些是裸车（还没挂路，算无主车）", len(ops._orphan_cars()), 4)
    status, msg = ops.op_clear_all(bpy.context)
    C.eq("删除时顺带清掉无主车", status, ops.FINISHED)
    C.check("回执里写明了清理无主车", "无主" in str(msg))
    C.eq("无主车已清干净", len(ops._orphan_cars()), 0)
    C.eq("场景里再没有本插件的车", len(ops.all_generated_cars()), 0)


def t_panel_draw(C, ops, props, ui):
    log = []
    panel = FakePanel(FakeLayout(log), ui.MF_PT_Traffic)
    p = st()
    p.roads.clear()
    p.cars.clear()

    try:
        ui.MF_PT_Traffic.draw(panel, bpy.context)
    except AssertionError:
        C.check("面板 draw 不使用 template_list", False)
        return
    except Exception as e:
        C.check("面板 draw 不抛异常（空列表）", False)
        C.failed.append("  空列表 draw 异常：%r" % (e,))
        return
    C.check("面板 draw 不抛异常（空列表）", True)

    ops_drawn = {e[1] for e in log if e[0] == "operator"}
    for want in ("mf.traffic_pick_roads", "mf.traffic_pick_cars",
                 "mf.traffic_compute",
                 "mf.traffic_offset_all", "mf.traffic_apply_duration",
                 "mf.traffic_clear_all"):
        C.check("空列表时画出了 %s" % want, want in ops_drawn)

    road = make_road("road_pd")
    select_only([road])
    ops.op_pick_roads(bpy.context)
    p.car_count = 3
    tpl = make_car_template("car_pd")
    select_only([tpl])
    ops.op_pick_cars(bpy.context)
    ops.op_compute_paths(bpy.context)

    log2 = []
    panel2 = FakePanel(FakeLayout(log2), ui.MF_PT_Traffic)
    try:
        ui.MF_PT_Traffic.draw(panel2, bpy.context)
    except Exception as e:
        C.check("面板 draw 不抛异常（有内容）", False)
        C.failed.append("  有内容 draw 异常：%r" % (e,))
        return
    C.check("面板 draw 不抛异常（有内容）", True)

    rna = set(props.MF_PG_TrafficSettings.bl_rna.properties.keys())
    missing = [e[1] for e in log2 if e[0] == "prop" and e[1] not in rna]
    C.eq("面板引用的属性全部存在", missing, [])

    drawn_ops = {e[1] for e in log2 if e[0] == "operator"}
    C.check("面板确实画出了控件（守卫非空跑）", len(drawn_ops) > 0)
    for idname in drawn_ops:
        short = idname.split(".", 1)[1]
        C.check("面板引用的算子 %s 已注册" % idname, op_registered(short))

    C.check("面板画出了激活道路的按钮",
            "mf.traffic_activate_road" in drawn_ops)
    C.check("面板画出了激活车辆的按钮",
            "mf.traffic_activate_car" in drawn_ops)

    ops.op_clear_all(bpy.context)
    p.roads.clear()
    p.cars.clear()


def t_icons(C):
    icons = {i.identifier for i in
             bpy.types.UILayout.bl_rna.functions["label"]
             .parameters["icon"].enum_items}
    src = _src("ui.py")
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    found = set(re.findall(r'icon=(?:"([A-Z_0-9]+)"|\'([A-Z_0-9]+)\')', src))
    used = {a or b for a, b in found}
    C.check("确实扫到了 icon 字面量（守卫非空跑）", len(used) > 0)
    bad = sorted(i for i in used if i not in icons)
    C.eq("ui.py 里的 icon 全部有效", bad, [])


def t_static(C):
    wm_funcs = {p.identifier for p in bpy.types.WindowManager.bl_rna.functions}

    files = {}
    for fn in ("operators.py", "ui.py", "props.py", "selftest.py"):
        path = os.path.join(THIS_DIR, fn)
        if os.path.exists(path):
            files[fn] = open(path, encoding="utf-8").read()

    called = set()
    for fn, src in files.items():
        code = _strip_comments(src)
        called |= set(re.findall(r"(?<!ops\.)\bwm\.([a-z_]+)\(", code))
        called |= set(re.findall(r"window_manager\.([a-z_]+)\(", code))
    bad_wm = sorted(c for c in called if c not in wm_funcs)
    C.eq("源码里没有不存在的 window_manager 方法", bad_wm, [])

    ops_code = _strip_comments(files["operators.py"])
    for fn_name in ("op_pick_roads", "op_pick_cars",
                    "op_compute_paths", "op_offset_all",
                    "op_apply_duration",
                    "op_clear_all", "op_remove_road", "op_remove_car",
                    "ensure_path_enabled", "build_loop_animation",
                    "period_frames", "current_road", "cars_on_road", "_orphan_cars",
                    "_remove_cars", "_generate_cars"):
        C.check("operators 里还有业务函数 %s" % fn_name,
                re.search(r"\bdef %s\b" % fn_name, ops_code) is not None)

    C.check("assign_path 里调用了 ensure_path_enabled",
            re.search(r"def\s+assign_path\b[\s\S]*?ensure_path_enabled\s*\(",
                      ops_code) is not None)
    C.check("ensure_path_enabled 里会先关后开 use_path（强制重建缓存）",
            re.search(r"def\s+ensure_path_enabled\b[\s\S]*?"
                      r"use_path\s*=\s*False[\s\S]*?use_path\s*=\s*True",
                      ops_code) is not None)


def t_legacy_gone(C, ops, props, ui):
    prod_code = "\n".join(_strip_comments(files) for files in
                          (_src("operators.py"), _src("ui.py"), _src("props.py")))

    for gone in ("TRAF_OT_", "TRAF_PG_", "TRAF_PT_",
                 "_TrafPanelBase", "_TrafBase", "ID_PREFIX",
                 "交通流生成"):
        C.check("产品代码里已搜不到旧类名/旧常量 %s" % gone, gone not in prod_code)

    for gone in ("op_offset_road", "op_speed_road", "op_scale_cars",
                 "children_of", "_active_road", "_cars_on_road", "_draw_road",
                 "road_offset", "road_speed", "car_scale",
                 "ztzy", "alzy", "offset_side", "side_offset", "lateral",
                 "left_right", "clsf", "alqh", "alcs",
                 "TRAF_PT_help", "使用顺序", "按路调节",
                 "未选中道路", "左右偏移"):
        C.check("产品代码里已搜不到 %s" % gone, gone not in prod_code)

    C.check("产品代码里已不再引用 Scene.traffic",
            "scene.traffic" not in prod_code)

    for gone in ("op_offset_road", "op_speed_road", "op_scale_cars",
                 "children_of", "_active_road", "_cars_on_road"):
        C.check("operators 里已没有 %s" % gone, not hasattr(ops, gone))

    pg_rna = set(props.MF_PG_TrafficSettings.bl_rna.properties.keys())
    for gone in ("road_offset", "road_speed", "car_scale",
                 "side_offset", "lateral_offset", "global_side", "road_side",
                 "global_speed", "lap_frames_min", "lap_frames_max",
                 "anim_end_frame", "loop_seconds"):
        C.check("属性组里已没有 %s" % gone, gone not in pg_rna)

    for gone in ("pick_roads", "pick_cars", "compute", "offset_all",
                 "speed_all", "clear_all", "generate", "scale_cars",
                 "offset_road", "speed_road", "traffic_speed_all"):
        C.check("旧 idname mf.%s 已注销" % gone, not op_registered(gone))

    ops_code = _strip_comments(_src("operators.py"))
    for gone in ("BASE_FRAMES", "global_speed", "op_speed_all",
                 "_apply_speed", "车速", "lap_span", "lap_frames",
                 "anim_end_frame", "build_run_animation",
                 "_shift_fcurve_phase", "get_offset_percent",
                 "set_offset_percent", "_set_fcurve_offset", "_car_offsets",
                 "percent_to_factor", "factor_to_percent",
                 "offset_from", "offset_to", "REPEAT_OFFSET", "停住",
                 "scene_fps", "loop_seconds", "fps_base", "秒",
                 "_road_batches", "计算所有", "删除所有"):
        C.check("operators.py 里已搜不到 %s" % gone, gone not in ops_code)
    C.check("operators.py 里已没有反算车速的写法",
            "100.0 / max(float(speed)" not in ops_code)
    C.check("循环修饰器明确用 REPEAT（源码里出现 \"REPEAT\"）",
            '"REPEAT"' in ops_code)
    C.check("走的是「走完回到起点」而不是「值一圈圈往上加」",
            "offset_factor = float(offset_from)" not in ops_code)

    C.check("ui 里已没有 _draw_road", not hasattr(ui, "_draw_road"))
    C.check("ui 里已没有 TRAF_PT_help", not hasattr(ui, "TRAF_PT_help"))
    C.check("ui.CLASSES 只剩主面板", len(ui.classes) == 1)
    C.check("主面板没有子面板",
            not bool(getattr(ui.MF_PT_Traffic, "bl_parent_id", "")))


def t_no_dead_code(C):
    srcs = {}
    for fn in PROD_FILES:
        path = os.path.join(THIS_DIR, fn)
        if os.path.exists(path):
            srcs[fn] = open(path, encoding="utf-8").read()
    C.check("确实读到了产品源码（守卫非空跑）", len(srcs) == len(PROD_FILES))

    unused = []
    for fn, src in srcs.items():
        code = _strip_comments(src)
        body = code
        for line in code.splitlines():
            m_imp = re.match(r"\s*import\s+([A-Za-z_][\w.]*)", line)
            m_frm = re.match(r"\s*from\s+[\w.]+\s+import\s+\(?\s*([A-Za-z_]\w*)", line)
            if m_imp:
                name = m_imp.group(1).split(".")[0]
            elif m_frm:
                name = m_frm.group(1)
            else:
                continue
            if name in ("bpy",):
                continue
            rest = "\n".join(ln for ln in body.splitlines()
                             if not re.match(r"\s*(import|from)\s", ln))
            if not re.search(r"\b%s\b" % re.escape(name), rest):
                unused.append("%s: %s" % (fn, name))
    C.eq("产品代码里没有未使用的 import", unused, [])

    all_src = "\n".join(_strip_comments(s) for s in srcs.values())
    dead = []
    for fn, src in srcs.items():
        for m in re.finditer(r"^def\s+([A-Za-z_]\w*)\s*\(", src, re.M):
            name = m.group(1)
            if name.startswith("__"):
                continue
            if name in ("register", "unregister"):
                continue
            refs = 0
            for ln in all_src.splitlines():
                if re.match(r"\s*def\s+%s\s*\(" % re.escape(name), ln):
                    continue
                if re.search(r"\b%s\b" % re.escape(name), ln):
                    refs += 1
            if refs == 0:
                dead.append("%s.%s" % (fn[:-3], name))
    C.eq("产品代码里没有定义了却没人引用的函数", dead, [])


def t_no_dialog(C, ops):
    for cls in ops.classes:
        name = cls.bl_idname.split(".")[-1]
        C.check("%s 没有定义 invoke()" % name, "invoke" not in cls.__dict__)
        C.check("%s 有 bl_description" % name,
                bool(getattr(cls, "bl_description", "")))


def t_unregister_and_cleanup(C, root):
    root.unregister()

    C.check("Scene 上的 mf_traffic 属性已清掉",
            not hasattr(bpy.context.scene, SCENE_ATTR))
    C.check("属性组类已注销", not hasattr(bpy.types, "MF_PG_TrafficSettings"))
    C.check("名单项类已注销", not hasattr(bpy.types, "MF_PG_TrafficItem"))
    C.check("面板类已注销", not hasattr(bpy.types, "MF_PT_Traffic"))

    left = [s for s in ("traffic_pick_roads", "traffic_pick_cars",
                        "traffic_remove_road", "traffic_remove_car",
                        "traffic_activate_road", "traffic_activate_car",
                        "traffic_compute", "traffic_offset_all",
                        "traffic_apply_duration", "traffic_clear_all") if op_registered(s)]
    C.eq("全部算子已注销", left, [])


def run():
    clear_scene()

    for key in [k for k in list(sys.modules)
                if k == PKG or k.startswith(PKG + ".")]:
        del sys.modules[key]

    root = importlib.import_module(PKG)
    root.register()

    ops = importlib.import_module(PKG + ".operators")
    props = importlib.import_module(PKG + ".props")
    ui = importlib.import_module(PKG + ".ui")

    C = Checker()
    groups = (
        ("包内语法自检", lambda: t_syntax(C)),
        ("模板契约（静态）", lambda: t_contract(C, root)),
        ("帧数与速度取值", lambda: t_units(C, ops, props)),
        ("注册面（属性组/面板/算子）", lambda: t_registration(C, ops, props, ui)),
        ("拾取", lambda: t_pick(C, ops)),
        ("移除列表项", lambda: t_remove(C, ops)),
        ("生成车辆", lambda: t_generate(C, ops)),
        ("计算路径（当前道路）", lambda: t_compute(C, ops)),
        ("重建这一套", lambda: t_compute_rebuild(C, ops)),
        ("车辆真的在路上行驶", lambda: t_cars_ride_the_path(C, ops)),
        ("路径缓存毒化回归", lambda: t_path_cache_poison(C, ops)),
        ("前后偏移", lambda: t_offset(C, ops)),
        ("循环速度（帧）与相位", lambda: t_duration(C, ops)),
        ("删除当前道路的车", lambda: t_clear(C, ops)),
        ("名字唯一性", lambda: t_unique_item(C, ops)),
        ("一个场景两套动画互不干扰", lambda: t_multi_set(C, ops)),
        ("面板绘制", lambda: t_panel_draw(C, ops, props, ui)),
        ("图标有效性", lambda: t_icons(C)),
        ("静态体检", lambda: t_static(C)),
        ("旧名已彻底消失", lambda: t_legacy_gone(C, ops, props, ui)),
        ("无死代码", lambda: t_no_dead_code(C)),
        ("无对话框残留", lambda: t_no_dialog(C, ops)),
        ("注销与清理", lambda: t_unregister_and_cleanup(C, root)),
    )

    for label, fn in groups:
        try:
            fn()
        except Exception:
            C.failed.append("测试组「%s」抛出异常" % label)
            traceback.print_exc()

    return C.report()


def main():
    try:
        return run()
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
