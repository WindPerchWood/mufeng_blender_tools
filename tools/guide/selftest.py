import importlib
import os
import re
import sys
import traceback
import types

import bpy

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

PKG = os.path.basename(THIS_DIR)
PROD_FILES = ("__init__.py", "operators.py", "ui.py")

TOL = 1e-5
DEFAULT_KEYS = ("enabled", "mode", "color", "line_width")
REMOVED_NAMES = ("MF_OT_Guide_Reset", "core_reset", "default_values", "reset_props",
                 "use_camera_frame", "guide_reset", "OP_ID", "OP_WARN",
                 "_on_click_prop", "invoke_popup")


class Checker:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def ok(self, cond, label, detail=""):
        if cond:
            self.passed += 1
        else:
            self.failed += 1
            msg = label if not detail else "%s | %s" % (label, detail)
            self.failures.append(msg)
            print("  [FAIL] %s" % msg)

    def eq(self, got, want, label, tol=None):
        if tol is None:
            cond = got == want
        else:
            try:
                cond = abs(float(got) - float(want)) <= tol
            except (TypeError, ValueError):
                cond = False
        self.ok(cond, label, "got=%r want=%r" % (got, want))

    def near(self, got, want, label, tol=TOL):
        self.eq(got, want, label, tol=tol)

    def section(self, title):
        print("\n--- %s ---" % title)


class FakeLayout:
    def __init__(self, log):
        object.__setattr__(self, "log", log)

    def __setattr__(self, name, value):
        self.log.append(("set:%s" % name, (value,), {}))

    def _rec(self, name, *args, **kwargs):
        self.log.append((name, args, kwargs))
        return self

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self._rec(name, *a, **k)


class FakePanel:
    def __init__(self, layout, owner):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._owner, name).__get__(self, type(self))


class FakeProps:
    def __init__(self):
        self.enabled = True
        self.mode = 'SQUARE'
        self.color = (0.0, 0.0, 0.0, 1.0)
        self.line_width = 7.0


class FakeRegion:
    width = 400
    height = 400


def op_registered(short):
    try:
        getattr(bpy.ops.mf, short).get_rna_type()
        return True
    except Exception:
        return False


def rna_names(pg):
    return set(pg.bl_rna.properties.keys()) - {"rna_type", "name"}


def call_texts(call):
    _name, args, kwargs = call
    out = [v for v in args if isinstance(v, str)]
    out += [v for v in kwargs.values() if isinstance(v, str)]
    return out


def func_body(src, name):
    marker = "def %s(" % name
    if marker not in src:
        return ""
    tail = src.split(marker, 1)[1]
    for stop in ("\ndef ", "\nclass "):
        if stop in tail:
            tail = tail.split(stop, 1)[0]
    return tail


def class_body(src, name):
    marker = "class %s(" % name
    if marker not in src:
        return ""
    tail = src.split(marker, 1)[1]
    if "\nclass " in tail:
        tail = tail.split("\nclass ", 1)[0]
    return tail


def read_sources():
    out = {}
    for fn in PROD_FILES:
        with open(os.path.join(THIS_DIR, fn), encoding="utf-8") as fh:
            out[fn] = fh.read()
    return out


def t_camera_view_guard(c, m):
    c.section("只在相机视图显示（view_perspective 守卫）")

    c.eq(m.CAMERA_VIEW, 'CAMERA', "相机视图常量")

    class RV:
        pass

    for value, want in (('CAMERA', True), ('PERSP', False), ('ORTHO', False),
                        ('camera', False), ('', False)):
        rv = RV()
        rv.view_perspective = value
        c.eq(m.is_camera_view(rv), want, "view_perspective=%r 的判定" % value)

    c.eq(m.is_camera_view(object()), False, "没有 view_perspective 的对象不崩")
    c.eq(m.is_camera_view(None), False, "None 不崩")

    def ctx(view_perspective, area_type='VIEW_3D', space_type='VIEW_3D'):
        space = types.SimpleNamespace(type=space_type,
                                      region_3d=types.SimpleNamespace(
                                          view_perspective=view_perspective))
        return types.SimpleNamespace(area=types.SimpleNamespace(type=area_type),
                                     space_data=space)

    c.eq(m.view_is_camera(ctx('CAMERA')), True, "整context：相机视图")
    c.eq(m.view_is_camera(ctx('PERSP')), False, "整context：透视视图")
    c.eq(m.view_is_camera(ctx('CAMERA', space_type='SEQUENCER')), False,
         "space_data 不是 3D 视图时判 False")
    c.eq(m.view_is_camera(types.SimpleNamespace()), False, "context 没有 space_data 不崩")
    c.eq(m.view_is_camera(None), False, "context 为 None 不崩")

    c.eq(m.in_view3d(ctx('PERSP')), True, "in_view3d：3D 视图区域")
    c.eq(m.in_view3d(ctx('PERSP', area_type='OUTLINER')), False, "in_view3d：非 3D 区域")
    c.eq(m.in_view3d(types.SimpleNamespace(area=None)), False, "in_view3d：没有区域")
    c.eq(m.in_view3d(None), False, "in_view3d：None 不崩")

    body = func_body(read_sources()["operators.py"], "_draw_callback")
    guard = body.find("not is_camera_view(rv3d)")
    shader = body.find("_ensure_shader()")
    enabled = body.find("not props.enabled")
    c.ok(guard != -1, "绘制回调里有相机视图守卫")
    c.ok(shader != -1, "绘制回调里仍然取 shader（守卫不是把整段删了）")
    c.ok(guard != -1 and shader != -1 and guard < shader,
         "守卫排在取 shader 之前（非相机视图先挡住）")
    c.ok(enabled != -1 and enabled > guard, "启用开关的判断也排在守卫之后")

    src_op = read_sources()["operators.py"]

    blk = func_body(src_op, "_blocked")
    c.ok("in_view3d(context)" in blk and "view_is_camera(context)" in blk,
         "「该不该挡」只看确实身处非相机视叾（拿不准就不挡）")

    en = func_body(src_op, "_on_enabled_changed")
    c.ok("self.enabled = False" in en, "非相机视叾下打开会被复位（不启动）")
    c.ok("_REVERTING" in en, "复位自身时防重入")
    c.ok("_notify(" in en, "被挡住时会发提示")

    md = func_body(src_op, "_on_mode_changed")
    c.ok("_notify(" in md, "切构图法时也会发提示")

    nt = func_body(src_op, "_notify")
    c.ok("try" in nt and "except" in nt, "发提示失败不往上抛（不打断属性写入）")
    c.ok("invoke_popup" not in nt, "提示不再走弹窗")

    nb = class_body(src_op, "MF_OT_Guide_Notify")
    c.ok("self.report" in nb, "提示走算子的 report（落到状态栏）")
    c.ok("invoke_popup" not in nb, "提示算子里没有弹窗")
    c.ok("def draw" not in nb, "提示算子不画 popup 内容")

    c.ok(bool(m.MSG_NOT_CAMERA) and bool(m.MSG_BLOCKED), "两条提示文案都在")



def t_segment_counts(c, m):
    c.section("guide_segments 数量与未知模式兜底")

    expected = {
        'THIRDS': 4,
        'GOLDEN': 4,
        'SQUARE': 4,
        'CENTER': 2,
        'DIAGONAL': 2,
        'TRIANGLE': 3,
    }
    for mode, want in expected.items():
        segs = m.guide_segments(mode, 300.0, 200.0)
        c.eq(len(segs), want, "%s 线段数" % mode)
        c.ok(all(len(s) == 4 for s in segs), "%s 每段都是 4 元组" % mode)

    fallback = m.guide_segments('NOT_A_MODE', 300.0, 200.0)
    thirds = m.guide_segments('THIRDS', 300.0, 200.0)
    c.eq(fallback, thirds, "未知模式退回三分法")

    c.eq(len(m.MODE_ITEMS), len(expected), "枚举项数量与用例一致")
    for identifier, _label, _desc in m.MODE_ITEMS:
        segs = m.guide_segments(identifier, 300.0, 200.0)
        c.ok(len(segs) > 0, "枚举项 %s 有输出" % identifier)
        if identifier != 'THIRDS':
            c.ok(segs != thirds, "枚举项 %s 有自己的几何（不是兜底）" % identifier)


def t_thirds(c, m):
    c.section("三分法坐标（w=300 h=200）")
    segs = m.guide_segments('THIRDS', 300.0, 200.0)
    vx = sorted({s[0] for s in segs if abs(s[0] - s[2]) < TOL})
    hy = sorted({s[1] for s in segs if abs(s[1] - s[3]) < TOL})
    c.eq(len(vx), 2, "竖线两条")
    c.near(vx[0], 100.0, "竖线 x1 = w/3")
    c.near(vx[1], 200.0, "竖线 x2 = 2w/3")
    c.eq(len(hy), 2, "横线两条")
    c.near(hy[0], 200.0 / 3.0, "横线 y1 = h/3")
    c.near(hy[1], 400.0 / 3.0, "横线 y2 = 2h/3")


def t_golden(c, m):
    c.section("黄金分割坐标（w=h=1000）")
    segs = m.guide_segments('GOLDEN', 1000.0, 1000.0)
    vx = sorted({s[0] for s in segs if abs(s[0] - s[2]) < TOL})
    hy = sorted({s[1] for s in segs if abs(s[1] - s[3]) < TOL})
    c.eq(len(vx), 2, "竖线两条")
    c.near(vx[0], 381.9660112501051, "x1 = w·0.381966", tol=1e-6)
    c.near(vx[1], 618.0339887498949, "x2 = w·0.618034", tol=1e-6)
    c.eq(len(hy), 2, "横线两条")
    c.near(hy[0], 381.9660112501051, "y1 = h·0.381966", tol=1e-6)
    c.near(hy[1], 618.0339887498949, "y2 = h·0.618034", tol=1e-6)
    c.near(m.GOLDEN_A + m.GOLDEN_B, 1.0, "GOLDEN_A + GOLDEN_B = 1", tol=1e-9)


def t_square(c, m):
    c.section("开方构图（横竖两个分支）")

    segs = m.guide_segments('SQUARE', 300.0, 200.0)
    left = (300.0 - 200.0) / 2.0
    right = left + 200.0
    got_left = min(s[0] for s in segs)
    got_right = max(s[0] for s in segs)
    c.near(got_left, left, "横构图左边界 = (w-h)/2")
    c.near(got_right, right, "横构图右边界 = (w-h)/2 + h")
    c.near(got_right - got_left, 200.0, "横构图正方形边长 = h")
    c.ok(all(s[1] >= -TOL and s[3] <= 200.0 + TOL for s in segs), "横构图不越界")

    segs = m.guide_segments('SQUARE', 200.0, 300.0)
    bottom = (300.0 - 200.0) / 2.0
    top = bottom + 200.0
    got_bottom = min(s[1] for s in segs)
    got_top = max(s[1] for s in segs)
    c.near(got_bottom, bottom, "竖构图下边界 = (h-w)/2")
    c.near(got_top, top, "竖构图上边界 = (h-w)/2 + w")
    c.near(got_top - got_bottom, 200.0, "竖构图正方形边长 = w")
    c.ok(all(s[0] >= -TOL and s[2] <= 200.0 + TOL for s in segs), "竖构图不越界")

    sq = m.guide_segments('SQUARE', 200.0, 200.0)
    c.ok(all(s[0] >= -TOL and s[2] <= 200.0 + TOL for s in sq), "正方形画幅不越界")


def t_center_diagonal_triangle(c, m):
    c.section("中分 / 对角线 / 三角")

    segs = m.guide_segments('CENTER', 300.0, 200.0)
    c.eq([tuple(s) for s in segs], [
        (150.0, 0.0, 150.0, 200.0),
        (0.0, 100.0, 300.0, 100.0),
    ], "中分法 = 中线十字")

    segs = m.guide_segments('DIAGONAL', 300.0, 200.0)
    c.eq([tuple(s) for s in segs], [
        (0.0, 0.0, 300.0, 200.0),
        (0.0, 200.0, 300.0, 0.0),
    ], "对角线 = 两条对角")

    segs = m.guide_segments('TRIANGLE', 300.0, 200.0)
    c.eq(len(segs), 3, "三角 = 对角线 + 中线")
    c.ok((0.0, 100.0, 300.0, 100.0) in [tuple(s) for s in segs], "三角含水平中线")
    c.ok((0.0, 0.0, 300.0, 200.0) in [tuple(s) for s in segs], "三角含主对角线")


def t_render_size(c, m):
    c.section("render_size（分辨率 / 百分比 / 像素宽高比）")
    r = bpy.context.scene.render
    old = (r.resolution_x, r.resolution_y, r.resolution_percentage,
           r.pixel_aspect_x, r.pixel_aspect_y)
    try:
        r.resolution_x, r.resolution_y = 1920, 1080
        r.resolution_percentage = 100
        r.pixel_aspect_x, r.pixel_aspect_y = 1.0, 1.0
        c.eq(m.render_size(bpy.context.scene), (1920.0, 1080.0), "1920x1080 @100%")

        r.resolution_percentage = 50
        c.eq(m.render_size(bpy.context.scene), (960.0, 540.0), "@50% 减半")

        r.resolution_percentage = 100
        r.pixel_aspect_x, r.pixel_aspect_y = 2.0, 1.0
        c.eq(m.render_size(bpy.context.scene), (3840.0, 1080.0), "像素宽高比 2:1 计入")

        r.resolution_x, r.resolution_y = 0, 0
        w, h = m.render_size(bpy.context.scene)
        c.ok(w >= 1.0 and h >= 1.0, "零分辨率不返回 0", "got=%r" % ((w, h),))
    finally:
        (r.resolution_x, r.resolution_y, r.resolution_percentage,
         r.pixel_aspect_x, r.pixel_aspect_y) = old


def t_fit_rect(c, m):
    c.section("fit_rect（letterbox 居中）")

    x, y, w, h = m.fit_rect(400.0, 400.0, 1920.0, 1080.0)
    c.near(x, 0.0, "方形视口 x = 0")
    c.near(w, 400.0, "方形视口宽铺满")
    c.near(h, 225.0, "方形视口高 = 400/(16/9)")
    c.near(y, 87.5, "方形视口上下各留 87.5")

    x, y, w, h = m.fit_rect(800.0, 300.0, 4.0, 3.0)
    c.near(x, 200.0, "宽视口左右各留 200")
    c.near(w, 400.0, "宽视口宽 = 300·(4/3)")
    c.near(h, 300.0, "宽视口高铺满")
    c.near(y, 0.0, "宽视口 y = 0")

    x, y, w, h = m.fit_rect(160.0, 90.0, 1920.0, 1080.0)
    c.eq((x, y, w, h), (0.0, 0.0, 160.0, 90.0), "比例一致时铺满")

    for bad in [(0.0, 100.0, 16.0, 9.0), (100.0, 0.0, 16.0, 9.0),
                (100.0, 100.0, 0.0, 9.0), (100.0, 100.0, 16.0, 0.0)]:
        x, y, w, h = m.fit_rect(*bad)
        c.ok(w >= 0.0 and h >= 0.0, "退化输入 %r 不崩" % (bad,))

    x, y, w, h = m.fit_rect(1234.0, 567.0, 1920.0, 1080.0)
    c.near(w / h, 1920.0 / 1080.0, "输出保持目标比例", tol=1e-9)


def t_build_line_coords(c, m):
    c.section("build_line_coords（y 轴翻转）")

    coords = m.build_line_coords([(0.0, 0.0, 300.0, 200.0)], (0.0, 0.0, 300.0, 200.0))
    c.eq(coords, [(0.0, 200.0), (300.0, 0.0)], "左上→左下 y 翻转")

    coords = m.build_line_coords([(0.0, 0.0, 10.0, 10.0)], (100.0, 50.0, 10.0, 10.0))
    c.eq(coords, [(100.0, 60.0), (110.0, 50.0)], "带偏移的画幅")

    segs = m.guide_segments('THIRDS', 300.0, 200.0)
    coords = m.build_line_coords(segs, (0.0, 0.0, 300.0, 200.0))
    c.eq(len(coords), len(segs) * 2, "顶点数 = 线段数 × 2")

    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    c.ok(min(xs) >= -TOL and max(xs) <= 300.0 + TOL, "x 在画幅内")
    c.ok(min(ys) >= -TOL and max(ys) <= 200.0 + TOL, "y 在画幅内")


def t_defaults_and_removed(c, m):
    c.section("默认值 与 已删功能不留残骸")

    props = m.MF_PG_GuideSettings.bl_rna.properties
    c.eq(sorted(rna_names(m.MF_PG_GuideSettings)), sorted(DEFAULT_KEYS), "参数组字段正好四个")
    c.eq(props["enabled"].default, False, "默认不启用")
    c.eq(props["mode"].default, m.DEFAULT_MODE, "默认模式")
    cdef = getattr(props["color"], "default_array", None)
    c.ok(cdef is not None and len(cdef) == 4
         and all(abs(float(a) - float(b)) <= 1e-6 for a, b in zip(cdef, m.DEFAULT_COLOR)),
         "默认颜色（含 Eevee 用的线性色，用容差比）", cdef)
    c.near(m.DEFAULT_COLOR[1], 220.0 / 255.0, "默认色绿通道", tol=1e-5)
    c.eq(m.DEFAULT_COLOR[2], 0.0, "默认色蓝通道为 0")
    c.eq(props["line_width"].default, m.DEFAULT_WIDTH, "默认线宽")

    src = read_sources()
    all_src = "\n".join(src.values())
    for name in REMOVED_NAMES:
        c.ok(name not in all_src, "已删干净：源码里搜不到 %s" % name)
    c.ok(not hasattr(m, "MF_OT_Guide_Reset"), "模块上没有 MF_OT_Guide_Reset")
    c.ok(not hasattr(m, "core_reset"), "模块上没有 core_reset")
    c.ok(not hasattr(m, "default_values"), "模块上没有 default_values")
    c.ok(not hasattr(m, "reset_props"), "模块上没有 reset_props")
    c.ok(not op_registered("guide_reset"), "算子 mf.guide_reset 已不存在")
    c.ok("use_camera_frame" not in rna_names(m.MF_PG_GuideSettings), "画幅开关已从参数组移除")
    c.ok(not hasattr(m, "FINISHED") and not hasattr(m, "CANCELLED"),
         "模块级 FINISHED / CANCELLED 常量已删（只剩算子返回字面量）")


def t_frame_rect_fallback(c, m):
    c.section("frame_rect 无相机时回退（纯逻辑）")

    scene = bpy.context.scene
    old_cam = scene.camera
    try:
        scene.camera = None
        rect, from_camera = m.frame_rect(FakeRegion(), object(), scene, camera_obj=None)
        c.eq(from_camera, False, "无相机时标记为回退")
        tw, th = m.render_size(scene)
        c.near(rect[2] / rect[3], tw / th, "回退矩形保持输出比例", tol=1e-6)
        c.near(rect[2], 400.0, "回退矩形宽铺满视口")
    finally:
        scene.camera = old_cam


def t_metadata(c, m, uimod):
    c.section("面板 / 算子元数据 与 命名约定")

    cls = uimod.MF_PT_Guide
    c.eq(cls.bl_space_type, 'VIEW_3D', "面板在 3D 视图")
    c.eq(cls.bl_region_type, 'UI', "面板在侧边栏区域")
    c.eq(cls.bl_category, uimod.utils.PANEL_CATEGORY, "面板分类 = utils.PANEL_CATEGORY")
    c.eq(cls.bl_category, "MF Tools", "面板分类值就是工具箱那一栏（没另起标签页）")
    c.eq(cls.bl_label, "构图辅助线", "面板标题")
    c.ok('DEFAULT_CLOSED' in cls.bl_options, "面板默认折叠")
    c.ok(isinstance(cls.bl_order, int) and cls.bl_order >= 0,
         "bl_order 已由挂载层按文件夹字母序自动分配 (%s)" % cls.bl_order)
    c.ok(bool(getattr(cls, "MF_SEARCH_KEYWORDS", ())), "配了顶部搜索别名")
    c.ok("draw_header" in cls.__dict__, "面板自己写了 draw_header")
    c.ok(bool(getattr(cls, "bl_description", "")), "面板有 bl_description")
    base = cls.__mro__[1].__name__
    c.ok(base in {"MF_ToolPanel", "Panel"}, "面板基类是 MF_ToolPanel（搜索条才过滤得到）", base)

    c.eq(cls.__name__, "MF_PT_Guide", "面板类名 MF_PT_*")
    c.eq(cls.bl_idname, "MF_PT_Guide", "面板 bl_idname 与类名一致")
    c.eq(m.MF_OT_Guide_Notify.__name__, "MF_OT_Guide_Notify", "算子类名 MF_OT_*")
    c.eq(m.MF_OT_Guide_Notify.bl_idname, "mf.guide_notify", "算子 idname")
    c.ok(m.MF_OT_Guide_Notify.bl_idname.startswith("mf."), "算子 idname 用 mf. 前缀")
    c.ok(bool(m.MF_OT_Guide_Notify.bl_description), "算子有 bl_description（悬停说明）")
    c.ok('INTERNAL' in m.MF_OT_Guide_Notify.bl_options, "提示算子用 INTERNAL（不进搜索条）")
    op_rna = bpy.ops.mf.guide_notify.get_rna_type().properties.keys()
    c.ok("message" in op_rna, "提示算子能收 message")
    c.ok("level" in op_rna, "提示算子能收 level")
    c.ok(m.MF_PG_GuideSettings.__name__.startswith("MF_PG_"), "参数组类名 MF_PG_*")
    c.eq(m.WM_ATTR, "mf_guide", "属性名带 mf_ 前缀")
    c.eq(m.OP_NOTIFY, m.MF_OT_Guide_Notify.bl_idname, "OP_WARN 与算子 bl_idname 同源")
    c.eq(m.OP_NOTIFY, "mf.guide_notify", "提示算子 idname 未被改写")

    rna_names_set = rna_names(m.MF_PG_GuideSettings)
    c.eq(sorted(rna_names_set), sorted(DEFAULT_KEYS), "参数组字段正好四个")

    prop = m.MF_PG_GuideSettings.bl_rna.properties["mode"]
    c.eq([i.identifier for i in prop.enum_items], [i[0] for i in m.MODE_ITEMS], "枚举顺序一致")
    c.eq(prop.default, m.DEFAULT_MODE, "枚举默认值")
    c.eq(m.MF_PG_GuideSettings.bl_rna.properties["color"].array_length, 4, "颜色 4 通道")
    c.eq(m.MF_PG_GuideSettings.bl_rna.properties["line_width"].soft_max, 3.0, "线宽软上限")

    exp_ok = False
    try:
        exp_ok = m.MF_PG_GuideSettings.bl_rna.properties["mode"].enum_items[0].identifier == \
            m.MODE_ITEMS[0][0]
    except Exception:
        exp_ok = False
    c.ok(exp_ok, "首个枚举项与 MODE_ITEMS 对齐")


def t_panel_draw(c, m, uimod):
    c.section("面板 draw() 真跑一遍（假 layout）")

    cls = uimod.MF_PT_Guide
    log = []
    cls.draw(FakePanel(FakeLayout(log), cls), bpy.context)
    c.ok(bool(log), "draw() 画出了控件")

    prop_refs = [call[1][1] for call in log
                 if call[0] in ("prop", "prop_enum") and len(call[1]) > 1
                 and isinstance(call[1][1], str)]
    rna_set = rna_names(m.MF_PG_GuideSettings)
    missing = [n for n in prop_refs if n not in rna_set]
    c.ok(not missing, "面板引用的属性都存在于 RNA", missing)
    for want in ("enabled", "color", "line_width"):
        c.ok(want in prop_refs, "常驻画出 %s" % want)

    modes = [call[1][2] for call in log
             if call[0] == "prop_enum" and len(call[1]) > 2]
    c.eq(modes, [item[0] for item in m.MODE_ITEMS], "六个构图法按钮按表顺序画全")

    op_refs = [call[1][0] for call in log if call[0] == "operator" and call[1]]
    c.eq(op_refs, [], "面板上不再画任何按钮（恢复默认按钮已删）")
    c.ok(op_registered("guide_notify"), "提示算子已注册（面板不画它，触发属性时才用）")

    hlog = []
    cls.draw_header(FakePanel(FakeLayout(hlog), cls), bpy.context)
    c.ok(any(call[0] == "label" for call in hlog), "draw_header 画了标题图标")

    nlog = []
    cls.draw(FakePanel(FakeLayout(nlog), cls),
             types.SimpleNamespace(window_manager=types.SimpleNamespace()))
    c.ok(any(call[0] == "label" for call in nlog), "参数未就绪时画提示而不是崩掉")

    busy_props = types.SimpleNamespace(enabled=True, mode='THIRDS',
                                       color=(1.0, 1.0, 0.0, 1.0),
                                       line_width=1.5)

    def draw_log(view_perspective, camera=None, props=busy_props, with_wm=True):
        wm = types.SimpleNamespace(**{m.WM_ATTR: props}) if with_wm \
            else types.SimpleNamespace()
        space = types.SimpleNamespace(
            type='VIEW_3D',
            region_3d=types.SimpleNamespace(view_perspective=view_perspective))
        ctx = types.SimpleNamespace(window_manager=wm,
                                    scene=types.SimpleNamespace(camera=camera),
                                    space_data=space)
        log = []
        cls.draw(FakePanel(FakeLayout(log), cls), ctx)
        return log

    def labels_of(*a, **k):
        return [t for call in draw_log(*a, **k) if call[0] == "label"
                for t in call_texts(call)]

    def alerts_of(*a, **k):
        return [call[1][0] for call in draw_log(*a, **k) if call[0] == "set:alert"]

    for vp in ('PERSP', 'ORTHO', 'CAMERA'):
        texts = labels_of(vp, camera=object())
        c.ok(not any("相机视图" in t for t in texts),
             "%s 下面板不再画视图提示" % vp, texts)
        c.ok(not any("数字键盘" in t for t in texts),
             "%s 下面板不画切视图文案" % vp, texts)
        c.eq(alerts_of(vp, camera=object()), [],
             "%s 下面板没有警告块（alert）" % vp)

    c.eq([call[0] for call in draw_log('PERSP')],
         [call[0] for call in draw_log('CAMERA', camera=object())],
         "面板画什么不再随视口状态分叉（提示已挪到状态栏）")


def t_static(c):
    c.section("静态体检（源码扫描）")

    src = read_sources()
    all_src = "\n".join(src.values())

    icons_used = set(re.findall(r"icon='([A-Z0-9_]+)'", all_src))
    icons_enum = set(bpy.types.UILayout.bl_rna.functions["label"]
                     .parameters["icon"].enum_items.keys())
    c.ok(bool(icons_used), "确实扫到了图标字面量（守卫非空跑）", sorted(icons_used))
    c.ok(icons_used <= icons_enum, "图标全在 RNA 枚举内（不会画到一半报错）",
         sorted(icons_used - icons_enum))

    imports = [ln.strip() for ln in all_src.splitlines() if ln.startswith(("import ", "from "))]
    bad = [ln for ln in imports if any(k in ln for k in ("numpy", "bsmax", "PIL", "third_party"))]
    c.ok(not bad, "没有引入第三方依赖", bad)

    c.ok("from ...core import utils" in src["operators.py"], "operators.py 三层相对导入 core")
    c.ok("from ...core import utils" in src["ui.py"], "ui.py 三层相对导入 core")
    c.ok("except (ImportError, ValueError)" in all_src, "降级桩同时捕获 ImportError 与 ValueError")

    c.ok("utils.register_classes" in func_body(src["operators.py"], "register"),
         "operators.register 走 utils.register_classes")
    c.ok("utils.unregister_classes" in func_body(src["operators.py"], "unregister"),
         "operators.unregister 走 utils.unregister_classes")
    c.ok("utils.register_classes" in func_body(src["ui.py"], "register"),
         "ui.register 走 utils.register_classes")
    c.ok("bpy.utils.register_class" not in func_body(src["operators.py"], "register"),
         "operators.register 没裸写 register_class")

    c.ok("bpy.types.Scene" not in all_src, "没有往 Scene 上挂属性（参数不写进 .blend）")
    c.ok("bpy.types.WindowManager" in src["operators.py"], "参数挂在 WindowManager 上")
    c.ok("bl_category = utils.PANEL_CATEGORY" in src["ui.py"], "bl_category 取自 utils")
    c.ok("alert" not in src["ui.py"], "面板不再画 alert 警告块")
    c.ok("只在相机视图" not in src["ui.py"], "面板不再画「只在相机视图」提示行")
    c.ok("数字键盘" not in src["ui.py"], "面板不再画切视图文案")
    c.ok("view_is_camera" not in src["ui.py"], "面板不再读视口状态（提示改由状态栏负责）")

    c.ok("bl_info" not in src["__init__.py"], "子包没有 bl_info（全箱只有根包一份）")
    c.ok("pkgutil" not in all_src, "子包不自建自动发现（根包统一扫）")
    c.ok("selftest" not in src["__init__.py"], "__init__ 不导入 selftest")
    c.ok("draw_handler_add" in src["operators.py"], "绘制钩子注册在 operators.py")
    c.ok("template_list" not in all_src, "没有用 template_list")

    c.ok('"""' not in all_src, "源码零 docstring")
    c.ok(not re.search(r"(?m)^\s*#", all_src), "源码零注释")


def t_registration(c, m, uimod, root, external):
    c.section("注册 / 注销往返")
    if external:
        c.ok(True, "[跳过] 插件已在别处注册，不做往返测试")
        return

    c.ok(hasattr(bpy.types.WindowManager, m.WM_ATTR), "WindowManager 上出现参数组")
    c.ok(not hasattr(bpy.context.scene, m.WM_ATTR), "Scene 上没有同名属性")
    c.ok(hasattr(bpy.types, uimod.MF_PT_Guide.bl_idname), "面板类出现在 bpy.types")
    c.ok(op_registered("guide_notify"), "算子 mf.guide_view_warn 已注册")
    c.ok(m._HANDLE is not None, "绘制钩子已注册")

    props = getattr(bpy.context.window_manager, m.WM_ATTR)
    c.eq(props.enabled, False, "默认不启用")
    c.eq(props.mode, m.DEFAULT_MODE, "默认模式正确")

    first = m._HANDLE
    m.add_handler()
    c.eq(m._HANDLE, first, "add_handler 幂等（不叠加）")

    try:
        props.mode = 'TRIANGLE'
        props.enabled = True
        props.line_width = 3.0
        props.color = (0.2, 0.4, 0.6, 1.0)
        c.eq(props.mode, 'TRIANGLE', "mode 可写")
        c.eq(props.enabled, True, "enabled 可写")
        c.eq(props.line_width, 3.0, "line_width 可写")
    except Exception as exc:
        c.ok(False, "属性写入不应抛异常", repr(exc))

    m._on_prop_changed(props, types.SimpleNamespace())
    m._on_mode_changed(props, types.SimpleNamespace())
    m._notify(m.MSG_NOT_CAMERA)
    c.ok(True, "属性回调与状态栏提示在空 context / 无窗口环境下都不抛异常")

    real_in, real_vis, real_notify = m.in_view3d, m.view_is_camera, m._notify
    seen = []
    try:
        m.in_view3d = lambda ctx: True
        m.view_is_camera = lambda ctx: True
        props.enabled = False
        props.enabled = True
        c.eq(props.enabled, True, "相机视图下开关能正常打开")

        m.view_is_camera = lambda ctx: False
        props.enabled = False
        props.enabled = True
        c.eq(props.enabled, False, "非相机视图下打开会被挡回去（不启动）")

        m._notify = lambda message, level='INFO': seen.append((level, message))
        props.enabled = False
        props.enabled = True
        c.ok(seen and seen[-1][0] == 'WARNING', "被挡住时用 WARNING 级别", seen)

        props.mode = 'GOLDEN'
        c.ok(seen and seen[-1][1] == m.MSG_NOT_CAMERA,
             "切构图法时提示先切相机视图", seen)

        m.in_view3d = lambda ctx: False
        props.enabled = False
        props.enabled = True
        c.eq(props.enabled, True, "判断不了视口时不拦（拿不准就放行）")
    finally:
        m.in_view3d, m.view_is_camera, m._notify = real_in, real_vis, real_notify

    last_mode = props.mode

    root.unregister()
    c.ok(not hasattr(bpy.types.WindowManager, m.WM_ATTR), "注销后 WindowManager 属性已移除")
    c.ok(not hasattr(bpy.types, uimod.MF_PT_Guide.bl_idname), "注销后面板类已移除")
    c.ok(not op_registered("guide_notify"), "注销后算子已移除")
    c.ok(m._HANDLE is None, "注销后绘制钩子已摘掉")
    m.remove_handler()
    c.ok(m._HANDLE is None, "remove_handler 幂等")

    root.register()
    c.ok(hasattr(bpy.types.WindowManager, m.WM_ATTR), "二次注册成功")
    c.ok(op_registered("guide_notify"), "二次注册后算子回来")
    c.ok(m._HANDLE is not None, "二次注册后绘制钩子回来")
    again = getattr(bpy.context.window_manager, m.WM_ATTR)
    c.eq(again.mode, last_mode,
         "二次注册后沿用上次的值（WindowManager 存量不随注销清除，与本箱其他工具一致）")
    again.enabled = False
    c.eq(again.enabled, False, "二次注册后属性仍可写")


def main():
    print("=" * 72)
    print("构图辅助线自检  |  Blender %s" % bpy.app.version_string)
    print("目录：%s" % THIS_DIR)
    print("=" * 72)

    root = importlib.import_module(PKG)
    m = importlib.import_module(PKG + ".operators")
    uimod = importlib.import_module(PKG + ".ui")

    c = Checker()
    external = hasattr(bpy.types.WindowManager, m.WM_ATTR)
    if external:
        print("\n[注意] 检测到参数已注册（插件可能已在别处启用）")
    else:
        root.register()

    groups = (
        ("guide_segments 数量与未知模式兜底", lambda: t_segment_counts(c, m)),
        ("三分法坐标", lambda: t_thirds(c, m)),
        ("黄金分割坐标", lambda: t_golden(c, m)),
        ("开方构图", lambda: t_square(c, m)),
        ("中分 / 对角线 / 三角", lambda: t_center_diagonal_triangle(c, m)),
        ("render_size", lambda: t_render_size(c, m)),
        ("fit_rect", lambda: t_fit_rect(c, m)),
        ("build_line_coords", lambda: t_build_line_coords(c, m)),
        ("默认值与已删功能守卫", lambda: t_defaults_and_removed(c, m)),
        ("frame_rect 回退", lambda: t_frame_rect_fallback(c, m)),
        ("只在相机视图显示", lambda: t_camera_view_guard(c, m)),
        ("元数据与命名约定", lambda: t_metadata(c, m, uimod)),
        ("面板绘制", lambda: t_panel_draw(c, m, uimod)),
        ("静态体检", lambda: t_static(c)),
        ("注册 / 注销往返", lambda: t_registration(c, m, uimod, root, external)),
    )

    for label, fn in groups:
        try:
            fn()
        except Exception:
            c.failed += 1
            c.failures.append("测试组「%s」抛出异常" % label)
            print("  [FAIL] 测试组「%s」抛出异常" % label)
            traceback.print_exc()

    if not external:
        try:
            root.unregister()
        except Exception:
            c.failed += 1
            c.failures.append("收尾注销失败")
            traceback.print_exc()
        c.ok(not hasattr(bpy.types.WindowManager, m.WM_ATTR), "收尾后 WindowManager 属性已清掉")
        c.ok(not hasattr(bpy.types, uimod.MF_PT_Guide.bl_idname), "收尾后面板类已清掉")
        c.ok(m._HANDLE is None, "收尾后绘制钩子已清掉")

    print("\n" + "=" * 72)
    total = c.passed + c.failed
    if c.failed == 0:
        print("全部通过：%d / %d" % (c.passed, total))
    else:
        print("通过 %d / %d，失败 %d 项：" % (c.passed, total, c.failed))
        for msg in c.failures:
            print("  - %s" % msg)
    print("=" * 72)
    return 0 if c.failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("\n[自检中断] 未捕获异常，见上方 Traceback")
        raise SystemExit(1)
