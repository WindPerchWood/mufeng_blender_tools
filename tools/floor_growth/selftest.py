import ast
import importlib
import math
import os
import pkgutil
import re
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(HERE)
ADDON_DIR = os.path.dirname(TOOLS_DIR)

import bpy


RESULTS = []


def chk(cond, name):
    RESULTS.append((bool(cond), name))
    return bool(cond)


def section(title):
    RESULTS.append((None, "=== " + title + " ==="))


section("A. 导入与注册")

for _p in (os.path.dirname(ADDON_DIR), TOOLS_DIR):
    if _p and os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)

MODE = "standalone"
PKG = "floor_growth"

TB = None
if os.environ.get("MF_FG_MODE", "").lower() != "standalone":
    try:
        TB = importlib.import_module("mufeng_blender_tools.tools")
    except Exception:
        TB = None

if TB is not None:
    try:
        _found = [i.name for i in pkgutil.iter_modules(TB.__path__)]
    except Exception:
        _found = []
    chk("floor_growth" in _found,
        "★工具箱 pkgutil 能扫到 floor_growth 子包（本轮共扫到 %d 个）" % len(_found))
    MODE = "toolbox"
    PKG = "mufeng_blender_tools.tools.floor_growth"
else:
    chk(True, "未检出工具箱父包，按独立模式自检（相对导入走降级分支）")

chk(True, "自检模式 = %s" % MODE)

try:
    tg = importlib.import_module(PKG)
    chk(True, "导入 %s 成功" % PKG)
except Exception as e:
    print("SELFTEST_START")
    print("致命: 无法导入插件包 %s: %r" % (PKG, e))
    print("SELFTEST_END")
    print("SELFTEST_RESULT:FATAL_IMPORT")
    sys.exit(1)

P = importlib.import_module(PKG + ".plan")
KF = importlib.import_module(PKG + ".keyframes")
BK = importlib.import_module(PKG + ".bake")
OPS = importlib.import_module(PKG + ".operators")
UIM = importlib.import_module(PKG + ".ui")
PR = importlib.import_module(PKG + ".props")

try:
    tg.register()
    chk(True, "register() 未抛异常")
except Exception as e:
    chk(False, "register() 失败: %r" % (e,))

chk(hasattr(bpy.context.scene, PR.SCENE_ATTR),
    "Scene.%s 属性组已挂载" % PR.SCENE_ATTR)
chk(hasattr(bpy.types, "MF_PT_FloorGrowth"), "面板类 MF_PT_FloorGrowth 已注册")
chk(bpy.context.scene.bl_rna.properties[PR.SCENE_ATTR].type == 'POINTER',
    "Scene.%s 是 PointerProperty" % PR.SCENE_ATTR)
chk(getattr(bpy.context.scene, PR.SCENE_ATTR).bl_rna.identifier
    == "MF_PG_FloorGrowthSettings",
    "Scene 属性指向已注册的 MF_PG_FloorGrowthSettings")


def op_short(idname):
    return idname.split(".", 1)[1]


def _is_unregistered(cls):
    try:
        bpy.utils.register_class(cls)
    except Exception:
        return False
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        pass
    return True


OPS_NS = set(dir(bpy.ops.mf))

for _id, _n in ((OPS.OP_GROW, "生成"), (OPS.OP_CLEAR, "清除"),
                (OPS.OP_SELECT, "选中"), (OPS.OP_ESTIMATE, "预估")):
    chk(op_short(_id) in OPS_NS, "算子 %s 可用（%s）" % (_id, _n))

chk("nonexistent_op_xyz" not in OPS_NS, "判据自检：不存在的算子名确实不在集合里")
chk("floor_growth" not in OPS_NS,
    "旧的 mf.floor_growth* 未同时存在（不会出现两套面板/两套算子）")


section("B. plan.py 纯逻辑")

chk(abs(P.ease(0.5, P.EASE_LINEAR) - 0.5) < 1e-9, "ease LINEAR(0.5)=0.5")
chk(abs(P.ease(0.5, P.EASE_IN) - 0.25) < 1e-9, "ease EASE_IN(0.5)=0.25")
chk(abs(P.ease(0.5, P.EASE_OUT) - 0.75) < 1e-9, "ease EASE_OUT(0.5)=0.75")
chk(abs(P.ease(0.5, P.EASE_S) - 0.5) < 1e-9, "ease EASE_S(0.5)=0.5")
chk(P.ease(-9, P.EASE_LINEAR) == 0.0, "ease 下限夹取")
chk(P.ease(9, P.EASE_LINEAR) == 1.0, "ease 上限夹取")

chk(abs(P.lift_curve(0.5) - 1.0) < 1e-9, "lift 抛物线峰值=1")
chk(abs(P.lift_curve(0.0)) < 1e-9, "lift t=0 为 0")
chk(abs(P.lift_curve(1.0)) < 1e-9, "lift t=1 为 0")
chk(abs(P.lift_curve(0.5, P.LIFT_SINE) - 1.0) < 1e-9, "lift 正弦峰值=1")

POS = [(0, 0, 0), (10, 0, 0), (5, 0, 0), (20, 0, 0)]
k = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_DISTANCE})
chk(k == [0.0, 10.0, 5.0, 20.0], "距离排序键正确")

n = P.normalize_orders(k)
chk(n[0] == 0.0 and n[3] == 1.0, "归一化首=0 尾=1")
chk(abs(n[1] - 0.5) < 1e-9, "归一化中间=0.5")

k = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_AXIS_X})
chk(k == [0.0, 10.0, 5.0, 20.0], "+X 排序正确")
k = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_AXIS_NX})
chk(k == [0.0, -10.0, -5.0, -20.0], "-X 排序正确")
n = P.normalize_orders(k)
chk(abs(n[0] - 1.0) < 1e-9 and n[3] == 0.0, "-X 顺序反转")

k = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_VECTOR, "direction": (0, 1, 0)})
chk(all(x == 0.0 for x in k), "自定义向量(垂直)全 0")

ka = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_RANDOM, "random_seed": 42})
kb = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_RANDOM, "random_seed": 42})
kc = P.compute_order_keys(POS, {"spread_mode": P.SPREAD_RANDOM, "random_seed": 43})
chk(ka == kb, "随机可复现")
chk(ka != kc, "随机随种子变化")

pl = P.build_plan(POS, {"spread_mode": P.SPREAD_DISTANCE, "start_frame": 1,
                        "spread_frames": 100, "per_tile_frames": 6,
                        "appear_mode": P.APPEAR_NONE})
chk(len(pl) == 4, "plan 长度 = 4")
chk(abs(pl[0]["flip_start"] - 1.0) < 1e-9, "首块 flip_start=1")
chk(abs(pl[3]["flip_start"] - 101.0) < 1e-9, "末块 flip_start=101")
chk(abs(pl[0]["flip_end"] - 7.0) < 1e-9, "首块 flip_end=7")

pl2 = P.build_plan(POS, {"spread_mode": P.SPREAD_DISTANCE, "start_frame": 1,
                         "spread_frames": 100, "per_tile_frames": 6,
                         "appear_mode": P.APPEAR_SCALE, "appear_frames": 4,
                         "gap_after_appear": 2})
chk(pl2[0]["appear_start"] == 1.0, "出现 start=1")
chk(pl2[0]["appear_end"] == 5.0, "出现 end=5")
chk(pl2[0]["flip_start"] == 7.0, "出现后停顿 2 帧再翻")
chk(pl2[0]["flip_end"] == 13.0, "出现模式 flip_end=13")

ja = P.build_plan(POS, {"jitter": 0.1, "random_seed": 7, "spread_frames": 100})
jb = P.build_plan(POS, {"jitter": 0.1, "random_seed": 7, "spread_frames": 100})
chk([x["order"] for x in ja] == [x["order"] for x in jb], "抖动可复现")
chk(all(0.0 <= x["order"] <= 1.0 for x in ja), "抖动后仍夹取在 0..1")

ax = P.resolve_axis(P.AXIS_AUTO, (1, 0, 0), P.SPREAD_AXIS_X, (1, 0, 0))
chk(abs(ax[0]) < 1e-9 and abs(abs(ax[1]) - 1.0) < 1e-9, "自动轴(X 传播) 沿 Y")
ax = P.resolve_axis(P.AXIS_X, (0, 0, 0), P.SPREAD_DISTANCE, (0, 0, 0))
chk(ax == (1.0, 0.0, 0.0), "显式 X 轴")
ax = P.resolve_axis(P.AXIS_CUSTOM, (0, 0, 5), P.SPREAD_DISTANCE, (0, 0, 0))
chk(ax == (0.0, 0.0, 1.0), "自定义轴已归一化")

chk(P.total_frames(pl, tail=10) > 100, "总帧数估算")
chk(P.total_frames([], tail=10) == 0.0, "空计划总帧数=0")
chk(P.build_plan([], {}) == [], "空输入返回空")

chk("spiral_axis" not in P.DEFAULTS, "DEFAULTS 里已无死键 spiral_axis")

same = [(1, 1, 1)] * 3
nr = P.normalize_orders(P.compute_order_keys(same, {"spread_mode": P.SPREAD_DISTANCE}))
chk(all(v == 0.0 for v in nr), "退化(全同位置)返回全 0")

for m in P.SPREAD_MODES:
    kk = P.compute_order_keys(POS, {"spread_mode": m})
    chk(len(kk) == 4, "传播方式 %s 返回 4 个键" % m)


section("C. keyframes 写入")

bpy.ops.wm.read_factory_settings(use_empty=True)

TILE = 1.0
objs = []
for i in range(5):
    for j in range(5):
        bpy.ops.mesh.primitive_cube_add(size=TILE * 0.9, location=(i * TILE, j * TILE, 0.0))
        ob = bpy.context.active_object
        ob.name = "TILE_%02d_%02d" % (i, j)
        objs.append(ob)

chk(len(objs) == 25, "建了 25 块砖")

centers = KF.world_centers(objs)
chk(len(centers) == 25, "取到 25 个质心")

params = {
    "spread_mode": P.SPREAD_DISTANCE, "origin": (-1.0, -1.0, 0.0),
    "start_frame": 1, "spread_frames": 60, "per_tile_frames": 6,
    "appear_mode": P.APPEAR_SCALE, "appear_frames": 3, "gap_after_appear": 1,
    "flip_angle": 90.0, "flip_axis": P.AXIS_AUTO,
    "lift_height": 0.3, "lift_mode": P.LIFT_PARABOLA,
    "interpolate": 'BEZIER', "use_bounce": True, "bounce_amount": 0.12,
}
items = P.build_plan(centers, params)
chk(len(items) == 25, "plan 生成 25 项")

scn = bpy.context.scene
try:
    res = KF.apply_plan(objs, items, params, scn)
    chk(True, "apply_plan 未抛异常")
    chk(res["objects"] == 25, "apply_plan 处理 25 个对象")
    chk(res["keyframes"] > 0, "apply_plan 产生了关键帧 (%d)" % res["keyframes"])
except Exception as e:
    chk(False, "apply_plan 失败: %r" % (e,))
    traceback.print_exc()

kcount = KF.count_keyframes(objs)
chk(kcount > 0, "count_keyframes > 0，实际 %d" % kcount)

has_rot = False
has_loc = False
has_scale = False
for ob in objs:
    for fc in KF.iter_fcurves(ob):
        if "rotation_euler" in fc.data_path:
            has_rot = True
        if fc.data_path == "location":
            has_loc = True
        if fc.data_path == "scale":
            has_scale = True
chk(has_rot, "存在 rotation_euler 曲线")
chk(has_loc, "存在 location 曲线")
chk(has_scale, "存在 scale 曲线（出现阶段）")

last = objs[-1]
li = items[-1]
midf = int(round((li["flip_start"] + li["flip_end"]) * 0.5))
scn.frame_set(midf)
bpy.context.view_layer.update()
mid_ang = math.degrees(math.sqrt(last.rotation_euler.x ** 2 +
                                 last.rotation_euler.y ** 2 +
                                 last.rotation_euler.z ** 2))
chk(mid_ang > 30.0, "翻滚中间帧砖已立起 (%.1f°)" % mid_ang)

endf = int(round(li["flip_end"]))
scn.frame_set(endf)
bpy.context.view_layer.update()
end_ang = math.degrees(math.sqrt(last.rotation_euler.x ** 2 +
                                 last.rotation_euler.y ** 2 +
                                 last.rotation_euler.z ** 2))
chk(end_ang < 5.0, "翻滚结束帧砖已归位平躺 (%.1f°)" % end_ang)

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(50.0, 50.0, 0.0))
solo = bpy.context.active_object
solo.name = "SOLO_TILE"
solo.scale = (1.0, 1.0, 0.06)
bpy.context.view_layer.update()
solo_mesh_z = [(solo.matrix_world @ v.co).z for v in solo.data.vertices]
solo_bottom = min(solo_mesh_z)
solo_top = max(solo_mesh_z)

pr_solo = dict(params)
pr_solo["origin"] = (50.0, 50.0, 0.0)
pr_solo["spread_mode"] = P.SPREAD_AXIS_X
pr_solo["spread_frames"] = 1
pr_solo["per_tile_frames"] = 10
pr_solo["appear_mode"] = P.APPEAR_NONE
pr_solo["lift_height"] = 0.0
pr_solo["use_bounce"] = False
pr_solo["roll_dir"] = (1.0, 0.0, 0.0)
it_solo = P.build_plan(KF.world_centers([solo]), pr_solo)
KF.apply_plan([solo], it_solo, pr_solo, scn)


def solo_z_at(frame):
    scn.frame_set(frame)
    bpy.context.view_layer.update()
    zs = [(solo.matrix_world @ v.co).z for v in solo.data.vertices]
    return (min(zs), max(zs))


sz0 = solo_z_at(int(round(it_solo[0]["flip_start"])))
sz_mid = solo_z_at(int(round((it_solo[0]["flip_start"] + it_solo[0]["flip_end"]) * 0.5)))
sz1 = solo_z_at(int(round(it_solo[0]["flip_end"])) + 2)

chk(sz0[0] > solo_bottom - 0.06,
    "★立起时贴地不穿地 (zmin=%.3f, 底面=%.3f)" % (sz0[0], solo_bottom))
chk(sz0[1] > solo_top + 0.7, "★立起时确实立起 (zmax=%.3f)" % sz0[1])
chk(sz_mid[0] > solo_bottom - 0.08, "★翻滚途中不穿地 (zmin=%.3f)" % sz_mid[0])
chk(abs(sz1[0] - solo_bottom) < 0.01 and abs(sz1[1] - solo_top) < 0.01,
    "★结束时平躺落位 (z=[%.3f,%.3f])" % (sz1[0], sz1[1]))

_fs = int(round(it_solo[0]["flip_start"]))
_fe = int(round(it_solo[0]["flip_end"]))
sweep_min = 1e9
sweep_worst_f = -1
sweep_rises = 0
prev_zmax = None
for f in range(_fs, _fe + 1):
    z0, z1 = solo_z_at(f)
    if z0 < sweep_min:
        sweep_min = z0
        sweep_worst_f = f
    if prev_zmax is not None and z1 < prev_zmax - 1e-6:
        sweep_rises += 1
    prev_zmax = z1
chk(sweep_min > solo_bottom - 0.02,
    "★★翻滚全程逐帧不穿地 (最低 zmin=%.4f @f%d, 底面=%.3f)"
    % (sweep_min, sweep_worst_f, solo_bottom))
chk(sweep_rises >= _fe - _fs - 1,
    "★翻滚单调倒下，无异常回弹 (%d/%d 帧高度递减)" % (sweep_rises, _fe - _fs))

chk(scn.frame_end > 0, "场景 frame_end 已设置 (%d)" % scn.frame_end)

marked = KF.find_marked(objs)
chk(len(marked) == 25, "25 个对象被打上标记")

from mathutils import Vector as _V

pre_pos = {}
for ob in objs:
    pre_pos[ob.name] = _V(ob.matrix_world.translation)

scn.frame_set(int(round(items[-1]["flip_end"])) + 5)
bpy.context.view_layer.update()
max_drift = 0.0
for ob in objs:
    now = _V(ob.matrix_world.translation)
    max_drift = max(max_drift, (now - pre_pos[ob.name]).length)
chk(max_drift < 2.0, "动画结束后砖块位置漂移 < 2.0 (实际 %.4f)" % max_drift)

bad_drift = []
for ob in objs:
    now = _V(ob.matrix_world.translation)
    d = (now - pre_pos[ob.name]).length
    if d > 1.5:
        bad_drift.append((ob.name, round(d, 2)))
chk(len(bad_drift) == 0, "无砖块被搬走 (异常: %s)" % (bad_drift[:3],))

scn.frame_set(int(items[-1]["flip_end"]) + 10)
bpy.context.view_layer.update()
xs = [ob.matrix_world.translation.x for ob in objs]
ys = [ob.matrix_world.translation.y for ob in objs]
chk(max(xs) - min(xs) > 3.0, "阵列 X 跨度 > 3.0 (实际 %.2f)" % (max(xs) - min(xs)))
chk(max(ys) - min(ys) > 3.0, "阵列 Y 跨度 > 3.0 (实际 %.2f)" % (max(ys) - min(ys)))

bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
flat = bpy.context.active_object
flat.scale = (1.0, 1.0, 0.1)
flat.keyframe_insert("scale", frame=0)
flat.animation_data_clear()
flat.scale = (1.0, 1.0, 0.1)
flat.name = "FLAT_TILE"
orig_scale = (flat.scale.x, flat.scale.y, flat.scale.z)

pr2 = dict(params)
pr2["origin"] = (0.0, 0.0, 0.0)
pr2["appear_mode"] = P.APPEAR_SCALE
pr2["spread_frames"] = 10
it2 = P.build_plan([(0.0, 0.0, 0.0)], pr2)
KF.apply_plan([flat], it2, pr2, scn)

scn.frame_set(int(it2[0]["flip_end"]) + 5)
bpy.context.view_layer.update()
now_scale = (flat.scale.x, flat.scale.y, flat.scale.z)
chk(abs(now_scale[2] - orig_scale[2]) < 1e-4,
    "压扁缩放被保留 (原 %.3f -> 现 %.3f)" % (orig_scale[2], now_scale[2]))
chk(abs(now_scale[0] - orig_scale[0]) < 1e-4 and abs(now_scale[1] - orig_scale[1]) < 1e-4,
    "XY 缩放被保留")


section("D. 幂等与清除")

n1 = KF.count_keyframes(objs)
KF.clear_keys(objs)
n_after_clear = KF.count_keyframes(objs)
chk(n_after_clear == 0, "清除后关键帧=0 (清除前 %d)" % n1)

items_b = P.build_plan(KF.world_centers(objs), params)

KF.apply_plan(objs, items_b, params, scn)
n2 = KF.count_keyframes(objs)
chk(n2 == n1, "重跑后关键帧数一致 (%d == %d)" % (n2, n1))

KF.clear_keys(objs)
chk(len(KF.find_marked(objs)) == 0, "清除后标记也清掉")


section("E. 模式全覆盖")

bpy.ops.wm.read_factory_settings(use_empty=True)

scn = bpy.context.scene

sm_objs = []
for i in range(4):
    for j in range(4):
        bpy.ops.mesh.primitive_cube_add(size=0.9, location=(i, j, 0))
        sm_objs.append(bpy.context.active_object)
sm_centers = KF.world_centers(sm_objs)

for sm in P.SPREAD_MODES:
    pr = dict(params)
    pr["spread_mode"] = sm
    pr["origin"] = (-1.0, -1.0, 0.0)
    try:
        it = P.build_plan(sm_centers, pr)
        KF.apply_plan(sm_objs, it, pr, scn)
        chk(True, "传播 %s 完整写入通过" % sm)
        KF.clear_keys(sm_objs)
    except Exception as e:
        chk(False, "传播 %s 失败: %r" % (sm, e))

for am in P.APPEAR_MODES:
    pr = dict(params)
    pr["appear_mode"] = am
    try:
        it = P.build_plan(sm_centers, pr)
        KF.apply_plan(sm_objs, it, pr, scn)
        chk(True, "出现方式 %s 通过" % am)
        KF.clear_keys(sm_objs)
    except Exception as e:
        chk(False, "出现方式 %s 失败: %r" % (am, e))

for axm in P.FLIP_AXIS_MODES:
    pr = dict(params)
    pr["flip_axis"] = axm
    pr["custom_axis"] = (0.0, 0.0, 1.0)
    try:
        it = P.build_plan(sm_centers, pr)
        KF.apply_plan(sm_objs, it, pr, scn)
        chk(True, "翻转轴 %s 通过" % axm)
        KF.clear_keys(sm_objs)
    except Exception as e:
        chk(False, "翻转轴 %s 失败: %r" % (axm, e))

for lm in P.LIFT_MODES:
    pr = dict(params)
    pr["lift_height"] = 0.5
    pr["lift_mode"] = lm
    try:
        it = P.build_plan(sm_centers, pr)
        KF.apply_plan(sm_objs, it, pr, scn)
        chk(True, "抬起曲线 %s 通过" % lm)
        KF.clear_keys(sm_objs)
    except Exception as e:
        chk(False, "抬起曲线 %s 失败: %r" % (lm, e))

for em in P.EASE_MODES:
    pr = dict(params)
    pr["ease_mode"] = em
    try:
        it = P.build_plan(sm_centers, pr)
        chk(len(it) == 16, "节奏 %s 计划正确" % em)
    except Exception as e:
        chk(False, "节奏 %s 失败: %r" % (em, e))

for iv in ('BEZIER', 'LINEAR', 'CONSTANT'):
    pr = dict(params)
    pr["interpolate"] = iv
    try:
        it = P.build_plan(sm_centers, pr)
        KF.apply_plan(sm_objs, it, pr, scn)
        chk(True, "插值 %s 通过" % iv)
        KF.clear_keys(sm_objs)
    except Exception as e:
        chk(False, "插值 %s 失败: %r" % (iv, e))


section("F. 面板五件套与参数")

PANEL = getattr(bpy.types, "MF_PT_FloorGrowth", None)
chk(PANEL is not None, "面板类存在")
if PANEL is not None:
    chk(issubclass(PANEL, UIM.utils.MF_ToolPanel),
        "继承 utils.MF_ToolPanel（顶部搜索条才过滤得到）")
    chk(PANEL.bl_category == UIM.utils.PANEL_CATEGORY,
        "面板分类 = utils.PANEL_CATEGORY (%s)" % UIM.utils.PANEL_CATEGORY)
    chk(PANEL.bl_space_type == 'VIEW_3D', "面板在 3D 视图")
    chk(PANEL.bl_region_type == 'UI', "面板在侧栏 UI")
    chk(isinstance(PANEL.bl_order, int) and PANEL.bl_order >= 0,
        "bl_order 已由挂载层按文件夹字母序自动分配 (%s)" % PANEL.bl_order)
    chk('DEFAULT_CLOSED' in PANEL.bl_options, "统一默认折叠（DEFAULT_CLOSED）")
    chk(callable(getattr(PANEL, "draw_header", None)), "写了 draw_header（标题图标）")
    _kws = getattr(PANEL, "MF_SEARCH_KEYWORDS", ())
    chk(len(_kws) >= 6, "MF_SEARCH_KEYWORDS 有 %d 个搜索别名" % len(_kws))
    chk(any(k.isascii() for k in _kws), "搜索别名含拼音/英文")
    chk(any(not k.isascii() for k in _kws), "搜索别名含中文常见叫法")

st = getattr(bpy.context.scene, PR.SCENE_ATTR, None)
chk(st is not None, "当前场景能取到参数组")

chk(st.target_mode == 'SELECTED', "默认目标模式=选中")
chk(st.appear_mode == P.APPEAR_SCALE, "默认出现方式=缩放")
chk(st.interpolate == 'BEZIER', "默认插值=贝塞尔")
chk(st.auto_clear_before is True, "默认生成前清除=True")
chk(st.per_tile_frames == 6, "默认单块时长=6")
chk(st.spread_frames == 120, "默认蔓延跨度=120")

chk(len(st.bl_rna.properties["spread_mode"].enum_items) == len(P.SPREAD_MODES),
    "传播方式枚举项数 = %d" % len(P.SPREAD_MODES))
chk(len(st.bl_rna.properties["appear_mode"].enum_items) == len(P.APPEAR_MODES),
    "出现方式枚举项数 = %d" % len(P.APPEAR_MODES))

chk(hasattr(st, "use_baking"), "烘焙开关存在")
chk(hasattr(st, "baking_threshold"), "烘焙阈值存在")
chk(hasattr(st, "baking_realize"), "实体化开关存在")
chk(hasattr(st, "baking_keep_source"), "保留原砖开关存在")
chk(hasattr(st, "baking_auto_hint"), "自动切烘焙开关存在")
chk(st.baking_realize is True, "实体化默认开")
chk(st.baking_keep_source is False, "保留原砖默认关")
chk(st.baking_auto_hint is True, "自动切烘焙默认开")

chk(not hasattr(st, "show_advanced"), "无用的 show_advanced 已删除")


section("G. 烘焙模式")
bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene

ng = BK.build_node_group("MF_Test")
chk(ng is not None, "节点组建成")
chk(ng.bl_idname == 'GeometryNodeTree', "节点组类型正确")

iface_names = [i.name for i in ng.interface.items_tree
               if getattr(i, "item_type", None) == 'SOCKET']
for want in ("Instance", "Per Tile Frames", "Flip Angle", "Tile Half Fwd", "Realize"):
    chk(want in iface_names, "接口含 %s" % want)

has_objinfo = any(n.bl_idname == "GeometryNodeObjectInfo" for n in ng.nodes)
chk(has_objinfo, "节点组内有 Object Info（Object→Geometry 必需）")

inst_node = None
for n in ng.nodes:
    if n.bl_idname == "GeometryNodeInstanceOnPoints":
        inst_node = n
if inst_node is not None:
    src = inst_node.inputs["Instance"]
    chk(src.is_linked, "InstanceOnPoints.Instance 已连线")
    if src.is_linked:
        chk(src.links[0].from_node.bl_idname == "GeometryNodeObjectInfo",
            "Instance 来源是 Object Info（而非裸 Object socket）")

rad_count = sum(1 for n in ng.nodes
                if n.bl_idname == "ShaderNodeMath" and n.operation == "RADIANS")
chk(rad_count == 1, "角度链只有 1 次 RADIANS（实际 %d）" % rad_count)

bk_objs = []
bk_centers = []
PITCH = 1.06
for iy in range(4):
    for ix in range(4):
        cx, cy = (ix - 1.5) * PITCH, (iy - 1.5) * PITCH
        m = bpy.data.meshes.new("bk_%d_%d" % (ix, iy))
        b, t = 0.5, 0.06
        m.from_pydata(
            [(-b, -b, 0), (b, -b, 0), (b, b, 0), (-b, b, 0),
             (-b, -b, t), (b, -b, t), (b, b, t), (-b, b, t)],
            [], [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
        m.update()
        ob = bpy.data.objects.new("BKT_%d_%d" % (ix, iy), m)
        ob.location = (cx, cy, 0)
        bpy.context.collection.objects.link(ob)
        bk_objs.append(ob)
        bk_centers.append((cx, cy, 0.0))

chk(len(bk_objs) == 16, "建了 16 块砖")

bk_params = {
    "spread_mode": P.SPREAD_DISTANCE, "origin": (0.0, 0.0, 0.0),
    "start_frame": 1, "spread_frames": 30, "per_tile_frames": 10,
    "flip_angle": 90.0, "flip_axis": P.AXIS_AUTO,
    "lift_height": 0.0, "lift_mode": P.LIFT_PARABOLA,
    "appear_mode": P.APPEAR_NONE, "ease_mode": P.EASE_LINEAR,
}
bk_items = P.build_plan(bk_centers, bk_params)
chk(len(bk_items) == 16, "烘焙用 plan 生成 16 项")

bres = None
try:
    bres = BK.apply_baking(bpy.context, bk_objs, bk_items, bk_params, bk_centers,
                           brick_obj=bk_objs[0], name="MF_ST_Cloud", realize=True)
    chk(True, "apply_baking 未抛异常")
    chk(bres["count"] == 16, "烘焙数据 16 项")
except Exception as e:
    chk(False, "apply_baking 失败: %r" % (e,))
    traceback.print_exc()

if bres:
    cloud = bres["cloud"]
    bmesh = bres["mesh"]
    bmod = bres["modifier"]
    bng = bres["node_group"]

    attr_names = [a.name for a in bmesh.attributes]
    for want in (BK.ATTR_TRIGGER, BK.ATTR_AXIS, BK.ATTR_PIVOT, BK.ATTR_ORIGIN):
        chk(want in attr_names, "点云属性含 %s" % want)
    chk("mf_fg_phase" not in attr_names, "已删的死属性 mf_fg_phase 不再出现")

    chk(len(bmesh.vertices) == 16, "点云顶点数 = 16")

    chk(BK.read_mod_input(bmod, bng, "Instance") == bk_objs[0], "Instance 接口 = 第一块砖")
    chk(abs((BK.read_mod_input(bmod, bng, "Per Tile Frames") or 0) - 10.0) < 1e-6,
        "Per Tile Frames 接口 = 10")
    chk(abs((BK.read_mod_input(bmod, bng, "Flip Angle") or 0) - 90.0) < 1e-6,
        "Flip Angle 接口 = 90")
    chk(BK.read_mod_input(bmod, bng, "Realize") is True, "Realize 接口 = True")

    dg = bpy.context.evaluated_depsgraph_get()
    ev = cloud.evaluated_get(dg)
    me = ev.to_mesh()
    vn = len(me.vertices)
    ev.to_mesh_clear()
    chk(vn == 16 * 8, "实体化输出顶点 = 16×8 = 128（实际 %d）" % vn)

    chk(all(o.hide_viewport for o in bk_objs), "原始砖已隐藏（视口）")
    chk(all(o.hide_render for o in bk_objs), "原始砖已隐藏（渲染）")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    m1 = bpy.data.meshes.new("one")
    b, t = 0.5, 0.06
    m1.from_pydata(
        [(-b, -b, 0), (b, -b, 0), (b, b, 0), (-b, b, 0),
         (-b, -b, t), (b, -b, t), (b, b, t), (-b, b, t)],
        [], [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    m1.update()
    one = bpy.data.objects.new("ONE", m1)
    bpy.context.collection.objects.link(one)

    one_params = dict(bk_params)
    one_params["spread_frames"] = 1
    one_items = P.build_plan([(0.0, 0.0, 0.0)], one_params)
    trig = one_items[0]["flip_start"]
    flip_end = one_items[0]["flip_end"]

    ores = BK.apply_baking(bpy.context, [one], one_items, one_params, [(0.0, 0.0, 0.0)],
                           brick_obj=one, name="MF_ST_One", realize=True)
    ocloud = ores["cloud"]

    def _z_span(frame):
        scn.frame_set(frame)
        bpy.context.view_layer.update()
        d = bpy.context.evaluated_depsgraph_get()
        e = ocloud.evaluated_get(d)
        mm = e.to_mesh()
        if len(mm.vertices) == 0:
            e.to_mesh_clear()
            return None
        zs = [v.co.z for v in mm.vertices]
        r = (min(zs), max(zs))
        e.to_mesh_clear()
        return r

    z_start = _z_span(0)
    z_mid = _z_span(int(round((trig + flip_end) * 0.5)))
    z_end = _z_span(int(round(flip_end)) + 3)

    chk(z_start is not None and z_mid is not None and z_end is not None,
        "单块砖逐帧能取到几何")
    if z_start and z_mid and z_end:
        chk(z_start[0] > -0.06, "起始帧砖立起且贴地 (zmin=%.3f)" % z_start[0])
        chk(z_start[1] > 0.9, "起始帧砖立起有高度 (zmax=%.3f)" % z_start[1])
        chk(z_mid[0] > -0.08, "中间帧不穿地 (zmin=%.3f)" % z_mid[0])
        chk(z_mid[1] < z_start[1],
            "中间帧正在倒下 (zmax %.3f < %.3f)" % (z_mid[1], z_start[1]))
        chk(z_end[0] > -0.01 and z_end[1] < 0.2,
            "结束帧平躺 (z=[%.3f,%.3f])" % (z_end[0], z_end[1]))

    removed = BK.clear_baking(objs=None)
    chk(removed >= 1, "clear_baking 删除了点云 (%d)" % removed)
    chk(len(BK.find_baked_clouds()) == 0, "清除后无残留点云")
    chk(not one.hide_viewport and not one.hide_render,
        "★清除后原始砖自动恢复可见（objs=None 路径）")
    chk(BK.SRC_MARK not in one, "★清除后源砖标记已清掉")

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
m2 = bpy.data.meshes.new("two")
b, t = 0.5, 0.06
m2.from_pydata(
    [(-b, -b, 0), (b, -b, 0), (b, b, 0), (-b, b, 0),
     (-b, -b, t), (b, -b, t), (b, b, t), (-b, b, t)],
    [], [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
m2.update()
two = bpy.data.objects.new("TWO", m2)
bpy.context.collection.objects.link(two)
pr_ni = dict(bk_params)
pr_ni["spread_frames"] = 1
it_ni = P.build_plan([(0.0, 0.0, 0.0)], pr_ni)
res_ni = BK.apply_baking(bpy.context, [two], it_ni, pr_ni, [(0.0, 0.0, 0.0)],
                         brick_obj=two, name="MF_ST_NI", realize=False)
chk(BK.read_mod_input(res_ni["modifier"], res_ni["node_group"], "Realize") is False,
    "realize=False 时接口 = False")

scn.frame_set(3)

if scn.camera is None:
    cam_data = bpy.data.cameras.new("ST_Cam")
    cam_obj = bpy.data.objects.new("ST_Cam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = (3.5, -3.5, 3.5)
    cam_obj.rotation_euler = (math.radians(60), 0, math.radians(45))
    scn.camera = cam_obj
chk(scn.camera is not None, "测试场景有相机")

try:
    engines = [e.identifier for e in
               type(scn.render).bl_rna.properties["engine"].enum_items]
except Exception:
    engines = []
pick = None
for cand in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
    if cand in engines:
        pick = cand
        break
if pick:
    scn.render.engine = pick
chk(pick is not None, "找到可用渲染引擎 (%s)" % pick)
scn.render.resolution_x = 160
scn.render.resolution_y = 120
scn.render.filepath = os.path.join(tempfile.gettempdir(), "_mf_fg_ni_render.png")
try:
    bpy.ops.render.render(write_still=True)
    chk(os.path.exists(scn.render.filepath) and os.path.getsize(scn.render.filepath) > 1000,
        "realize=False 仍能渲染出图")
except Exception as e:
    chk(False, "realize=False 渲染失败: %r" % (e,))
finally:
    try:
        os.remove(scn.render.filepath)
    except Exception:
        pass


section("H. 算子端到端")

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
st2 = getattr(scn, PR.SCENE_ATTR, None)

e2e_objs = []
for iy in range(3):
    for ix in range(3):
        bpy.ops.mesh.primitive_cube_add(size=0.9, location=(ix * 1.0, iy * 1.0, 0.0))
        e2e_objs.append(bpy.context.active_object)

bpy.ops.object.select_all(action='DESELECT')
for o in e2e_objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = e2e_objs[0]

st2.target_mode = 'SELECTED'
st2.origin_mode = 'CORNER'
st2.spread_mode = P.SPREAD_DISTANCE
st2.start_frame = 1
st2.spread_frames = 20
st2.per_tile_frames = 5
st2.use_baking = False

try:
    r = bpy.ops.mf.floorgrowth_do()
    chk('FINISHED' in r, "算子(关键帧) 返回 FINISHED: %s" % (r,))
except Exception as e:
    chk(False, "算子(关键帧) 失败: %r" % (e,))

kf = KF.count_keyframes(e2e_objs)
chk(kf > 0, "关键帧模式实际写入关键帧 (%d)" % kf)

st2.use_baking = True
st2.baking_realize = True
st2.baking_keep_source = False

try:
    r2 = bpy.ops.mf.floorgrowth_do()
    chk('FINISHED' in r2, "算子(烘焙) 返回 FINISHED: %s" % (r2,))
except Exception as e:
    chk(False, "算子(烘焙) 失败: %r" % (e,))
    traceback.print_exc()

clouds = BK.find_baked_clouds(scn)
chk(len(clouds) == 1, "场景里有 1 个烘焙点云 (实际 %d)" % len(clouds))
if clouds:
    c0 = clouds[0]
    chk(c0.get(BK.MARK) is True, "点云带上烘焙标记")
    chk(len(c0.modifiers) == 1, "点云挂了 1 个修改器")
    chk(c0.modifiers[0].type == 'NODES', "修改器类型 = NODES")
    chk(c0.modifiers[0].node_group is not None, "修改器绑定了节点组")

    d = bpy.context.evaluated_depsgraph_get()
    e = c0.evaluated_get(d)
    m = e.to_mesh()
    chk(len(m.vertices) == 9 * 8, "烘焙输出顶点 = 9×8 = 72（实际 %d）" % len(m.vertices))
    e.to_mesh_clear()

chk(all(o.hide_viewport for o in e2e_objs), "烘焙后原砖隐藏")
chk(scn.frame_end > 0, "烘焙后 frame_end 已设置 (%d)" % scn.frame_end)

st2.clear_scope = 'MARKED'
try:
    r3 = bpy.ops.mf.floorgrowth_clear()
    chk('FINISHED' in r3 or 'CANCELLED' in r3, "算子(清除) 正常返回: %s" % (r3,))
except Exception as e:
    chk(False, "算子(清除) 失败: %r" % (e,))

chk(len(BK.find_baked_clouds(scn)) == 0, "清除后无烘焙点云残留")
chk(not any(o.hide_viewport for o in e2e_objs), "清除后原砖恢复可见")

_cycle_ok = True
_cycle_msg = ""
for _k in range(3):
    bpy.ops.object.select_all(action='DESELECT')
    for _o in e2e_objs:
        _o.select_set(True)
    bpy.context.view_layer.objects.active = e2e_objs[0]
    st2.use_baking = True
    _rg = bpy.ops.mf.floorgrowth_do()
    _hidden_after_gen = sum(1 for _o in e2e_objs if _o.hide_viewport)
    _rc = bpy.ops.mf.floorgrowth_clear()
    bpy.context.view_layer.update()
    _hidden_after_clear = sum(1 for _o in e2e_objs if _o.hide_viewport)
    _leftover = len([_o for _o in bpy.data.objects if _o.name.startswith("MF_")])
    if _hidden_after_gen != len(e2e_objs):
        _cycle_ok = False
        _cycle_msg = "第%d轮烘焙后应有 %d 块被隐藏，实际 %d" % (
            _k + 1, len(e2e_objs), _hidden_after_gen)
        break
    if _hidden_after_clear != 0 or _leftover != 0:
        _cycle_ok = False
        _cycle_msg = "第%d轮清除后 剩隐藏=%d 剩产物=%d" % (
            _k + 1, _hidden_after_clear, _leftover)
        break
chk(_cycle_ok, "★三轮「烘焙→清除」循环每轮都干净 %s" % _cycle_msg)
st2.use_baking = False

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
st3 = getattr(scn, PR.SCENE_ATTR, None)
auto_objs = []
for i in range(3):
    bpy.ops.mesh.primitive_cube_add(size=0.9, location=(i, 0, 0))
    auto_objs.append(bpy.context.active_object)
bpy.ops.object.select_all(action='DESELECT')
for o in auto_objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = auto_objs[0]

st3.target_mode = 'SELECTED'
st3.use_baking = False
st3.baking_auto_hint = True

chk(st3.baking_threshold >= 100, "烘焙阈值下限 = 100")

st3.baking_threshold = 100
st3.spread_frames = 5
st3.per_tile_frames = 3
try:
    r4 = bpy.ops.mf.floorgrowth_do()
    chk('FINISHED' in r4, "3 块砖(低于阈值) 返回 FINISHED: %s" % (r4,))
except Exception as e:
    chk(False, "3 块砖(低于阈值) 失败: %r" % (e,))
chk(len(BK.find_baked_clouds(scn)) == 0, "低于阈值时走关键帧、不产生点云")

st3.use_baking = True
st3.baking_realize = True
try:
    r5 = bpy.ops.mf.floorgrowth_do()
    chk('FINISHED' in r5, "手动勾选烘焙 返回 FINISHED: %s" % (r5,))
except Exception as e:
    chk(False, "手动勾选烘焙 失败: %r" % (e,))
chk(len(BK.find_baked_clouds(scn)) == 1, "手动勾选烘焙 → 产生点云")
chk(all(o.hide_viewport for o in auto_objs), "烘焙后原砖隐藏")


section("I. 清除不误伤（回归守卫）")

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
st4 = getattr(scn, PR.SCENE_ATTR, None)

bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
keep = bpy.context.active_object
keep.name = "USER_VISIBLE"

bpy.ops.mesh.primitive_cube_add(location=(3.0, 0.0, 0.0))
hid = bpy.context.active_object
hid.name = "USER_HIDDEN"
hid.hide_viewport = True
hid.hide_render = True

chk(BK.SRC_MARK not in hid, "手动隐藏的物体不带本工具任何标记")
chk(len([o for o in bpy.data.objects if o.get(BK.SRC_MARK)]) == 0,
    "场景里没有烘焙源砖标记")

st4.clear_scope = 'MARKED'
try:
    r6 = bpy.ops.mf.floorgrowth_clear()
    chk('CANCELLED' in r6, "无可清除对象时返回 CANCELLED: %s" % (r6,))
except Exception as e:
    chk(False, "清除算子异常: %r" % (e,))

chk(hid.hide_viewport is True and hid.hide_render is True,
    "★★手动隐藏的无关物体在清除后仍然隐藏（不会被误取消隐藏）")
chk(keep.hide_viewport is False, "普通可见物体保持可见")

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene
m3 = bpy.data.meshes.new("three")
b, t = 0.5, 0.06
m3.from_pydata(
    [(-b, -b, 0), (b, -b, 0), (b, b, 0), (-b, b, 0),
     (-b, -b, t), (b, -b, t), (b, b, t), (-b, b, t)],
    [], [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
m3.update()
three = bpy.data.objects.new("THREE", m3)
bpy.context.collection.objects.link(three)
pr3 = dict(bk_params)
pr3["spread_frames"] = 1
it3 = P.build_plan([(0.0, 0.0, 0.0)], pr3)
BK.apply_baking(bpy.context, [three], it3, pr3, [(0.0, 0.0, 0.0)],
                brick_obj=three, name="MF_ST_Three", realize=True)
chk(three.hide_viewport is True, "烘焙后源砖被隐藏")
chk(BK.SRC_MARK in three, "烘焙后源砖带上标记")

if BK.SRC_MARK in three:
    del three[BK.SRC_MARK]
chk(BK.SRC_MARK not in three, "人为抹掉源砖标记（模拟标记丢失）")

BK.clear_baking(objs=None)
chk(not three.hide_viewport and not three.hide_render,
    "★源砖标记丢失后，仍靠点云反查恢复可见")
chk(len(BK.find_baked_clouds(scn)) == 0, "点云已清除")


section("J. 静态体检与回归守卫")

st = getattr(bpy.context.scene, PR.SCENE_ATTR, None)
chk(st is not None, "静态体检前能重新取到参数组（前面的 reset 已换场景）")

SRC_DIR = HERE
src_map = {}
for _f in sorted(os.listdir(SRC_DIR)):
    if _f.endswith(".py") and _f != "selftest.py":
        with open(os.path.join(SRC_DIR, _f), encoding="utf-8") as fh:
            src_map[_f] = fh.read()

chk(len(src_map) == 7, "工具目录下应有 7 个模块（实际 %d：%s）"
    % (len(src_map), sorted(src_map)))

icon_enum = set()
try:
    _fn = bpy.types.UILayout.bl_rna.functions["label"]
    icon_enum = {i.identifier for i in _fn.parameters["icon"].enum_items}
except Exception:
    pass
chk(len(icon_enum) > 100, "取到 icon 枚举（%d 个）" % len(icon_enum))

used_icons = set()
for _s in src_map.values():
    used_icons |= set(re.findall(r"icon\s*=\s*'([A-Za-z0-9_]+)'", _s))
bad_icons = sorted(i for i in used_icons if i not in icon_enum)
chk(not bad_icons,
    "用到的 %d 个 icon 全部存在（越界: %s）" % (len(used_icons), bad_icons))

valid_props = set(st.bl_rna.properties.keys())
used_props = set()
for _s in src_map.values():
    used_props |= set(re.findall(r"\bst\.[a-z_][a-z_0-9]*", _s))
    used_props |= set(re.findall(r"\.prop\(\s*st\s*,\s*\"([a-z_0-9]+)\"", _s))
used_props = {p.split(".", 1)[1] if p.startswith("st.") else p for p in used_props}
used_props -= {"bl_rna"}
bad_props = sorted(p for p in used_props if p not in valid_props)
chk(not bad_props,
    "代码引用的 %d 个参数名全部存在（越界: %s）" % (len(used_props), bad_props))

ui_src = src_map.get("ui.py", "")
chk("from .operators import" in ui_src, "ui.py 从 operators 导入 OP_* 常量")
chk("mf.floorgrowth" not in ui_src, "面板里没有硬编码 idname（只用常量）")

FORBIDDEN = (
    "MF_PT_main", "MF_Settings", "mf.floor_growth", "CLASES", "CLASSES",
    "show_advanced", "ATTR_PHASE", "mf_fg_phase", "MF_INFO", "spiral_axis",
    "_basis_from_axis", "_obj_half_extent", "_obj_dims_local", "_obj_bottom_z",
    "_world_centers", "_iter_fcurves", "bl_info",
    "core.plan", "core.writer", "core.baking",
)
hits = ["%s:%s" % (f, tok) for f, s in src_map.items() for tok in FORBIDDEN if tok in s]
chk(not hits, "源码里搜不到旧类名/旧 idname/死符号（命中: %s）" % (hits[:6],))

dup_names = []
for _f, _s in src_map.items():
    try:
        _tree = ast.parse(_s)
    except Exception:
        continue
    _n = [x.name for x in _tree.body if isinstance(x, (ast.FunctionDef, ast.ClassDef))]
    dup_names += ["%s:%s" % (_f, x) for x in set(_n) if _n.count(x) > 1]
chk(not dup_names, "没有重复定义（%s）" % (dup_names or "无"))

bare_assign = [_f for _f, _s in src_map.items()
               if re.search(r"bpy\.types\.\w+\.\w+\s*=\s*bpy\.props\.", _s)]
chk(not bare_assign,
    "没有往 bpy.types 上直接挂裸 props（%s）" % (bare_assign or "无"))


class _RecLayout:
    def __init__(self):
        self.props_used = []
        self.icons_used = []
        self.ops_used = []

    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        return self

    def prop(self, owner, name, **kw):
        self.props_used.append(name)
        if kw.get("icon"):
            self.icons_used.append(kw["icon"])
        return self

    def label(self, text="", icon=""):
        if icon:
            self.icons_used.append(icon)
        return self

    def operator(self, idname, **kw):
        self.ops_used.append(idname)
        if kw.get("icon"):
            self.icons_used.append(kw["icon"])
        return self


class _FakePanel:
    def __init__(self, layout):
        self.layout = layout


BRANCHES = (
    {},
    {"target_mode": 'COLLECTION'},
    {"target_mode": 'PREFIX'},
    {"origin_mode": 'OBJECT'},
    {"spread_mode": P.SPREAD_WAVE},
    {"spread_mode": P.SPREAD_RANDOM},
    {"appear_mode": P.APPEAR_NONE},
    {"flip_axis": P.AXIS_CUSTOM},
    {"lift_height": 0.5},
    {"use_bounce": True},
    {"use_baking": True},
)

draw_errs = []
draw_ops = set()
if PANEL is not None:
    for over in BRANCHES:
        backup = {}
        for k_, v_ in over.items():
            try:
                backup[k_] = getattr(st, k_)
                setattr(st, k_, v_)
            except Exception as e:
                draw_errs.append("设 %s=%r 失败: %r" % (k_, v_, e))
        rec = _RecLayout()
        try:
            PANEL.draw(_FakePanel(rec), bpy.context)
            draw_ops |= set(rec.ops_used)
            rec2 = _RecLayout()
            PANEL.draw_header(_FakePanel(rec2), bpy.context)
        except Exception as e:
            draw_errs.append("%s -> %r" % (over, e))
        finally:
            for k_, v_ in backup.items():
                setattr(st, k_, v_)
    chk(not draw_errs,
        "面板 draw()/draw_header() 在 %d 组分支下都画得出来（异常: %s）"
        % (len(BRANCHES), draw_errs[:2]))

    bad_op = sorted(o for o in draw_ops if op_short(o) not in OPS_NS)
    chk(not bad_op,
        "面板按钮的 %d 个 idname 都是已注册算子（越界: %s）" % (len(draw_ops), bad_op))
    chk(draw_ops == {OPS.OP_GROW, OPS.OP_CLEAR, OPS.OP_SELECT, OPS.OP_ESTIMATE},
        "面板覆盖全部 4 个算子入口（实际 %d 个）" % len(draw_ops))


section("K. 注销干净度")

chk(hasattr(bpy.types, "MF_PT_FloorGrowth"), "注销前面板确实注册着（判据自检）")

try:
    tg.unregister()
    chk(True, "unregister() 未抛异常")
except Exception as e:
    chk(False, "unregister() 失败: %r" % (e,))

chk(not hasattr(bpy.types, "MF_PT_FloorGrowth"), "面板类已从 bpy.types 摘掉")
chk(not hasattr(bpy.context.scene, PR.SCENE_ATTR), "Scene 属性已清掉")
chk(op_short(OPS.OP_GROW) not in set(dir(bpy.ops.mf)), "算子已从 bpy.ops.mf 摘掉")

for _c in (PR.MF_PG_FloorGrowthSettings, UIM.MF_PT_FloorGrowth) + tuple(OPS.classes):
    chk(_is_unregistered(_c),
        "%s 干净注销（能重新注册 = 无残留）" % _c.__name__)

try:
    tg.register()
    chk(True, "重新 register() 未抛异常（有残留会报 already registered）")
except Exception as e:
    chk(False, "重新 register() 失败: %r" % (e,))
chk(hasattr(bpy.types, "MF_PT_FloorGrowth"), "重注册后面板回来了")
chk(hasattr(bpy.context.scene, PR.SCENE_ATTR), "重注册后 Scene 属性回来了")
chk(getattr(bpy.context.scene, PR.SCENE_ATTR).bl_rna.identifier
    == "MF_PG_FloorGrowthSettings", "重注册后参数组能正常实例化")


ok = 0
bad = 0
lines = []
for cond, name in RESULTS:
    if cond is None:
        lines.append(name)
    elif cond:
        ok += 1
        lines.append("  [OK]   " + name)
    else:
        bad += 1
        lines.append("  [FAIL] " + name)

lines.append("")
lines.append("=" * 50)
lines.append("总计: %d 通过 / %d 失败 / %d 项" % (ok, bad, ok + bad))
lines.append("=" * 50)

report = "\n".join(lines)
print("SELFTEST_START")
print(report)
print("SELFTEST_END")
print("SELFTEST_RESULT:%s" % ("ALL_OK" if bad == 0 else "FAILED_%d" % bad))
