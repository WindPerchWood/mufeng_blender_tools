import importlib
import os
import re
import sys
import tempfile
import traceback
import types

import bpy

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

PKG = os.path.basename(THIS_DIR)
PROD_FILES = ("__init__.py", "operators.py", "ui.py")
PREFIX = "自检_IDS_"


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

    def eq(self, got, want, label):
        self.ok(got == want, label, "got=%r want=%r" % (got, want))

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


def call_texts(call):
    _name, args, kwargs = call
    out = [v for v in args if isinstance(v, str)]
    out += [v for v in kwargs.values() if isinstance(v, str)]
    return out


def read_sources():
    out = {}
    for fn in PROD_FILES:
        with open(os.path.join(THIS_DIR, fn), encoding="utf-8") as fh:
            out[fn] = fh.read()
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


def rna_names(pg):
    return set(pg.bl_rna.properties.keys()) - {"rna_type", "name"}


def op_registered(short):
    try:
        getattr(bpy.ops.mf, short).get_rna_type()
        return True
    except Exception:
        return False


def make_object(name, mesh=False):
    data = None
    if mesh:
        data = bpy.data.meshes.new(PREFIX + name)
        data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        data.update()
    obj = bpy.data.objects.new(PREFIX + name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def baseline_max(m):
    used = [v for v in (m.id_of(o) for o in bpy.data.objects) if v is not None]
    return max(used) if used else 0


def cleanup():
    for obj in [o for o in bpy.data.objects if o.name.startswith(PREFIX)]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in [x for x in bpy.data.meshes if x.name.startswith(PREFIX)]:
        bpy.data.meshes.remove(mesh)
    for mat in [x for x in bpy.data.materials if x.name.startswith(PREFIX)]:
        bpy.data.materials.remove(mat)
    for coll in [x for x in bpy.data.collections if x.name.startswith(PREFIX)]:
        bpy.data.collections.remove(coll)


def t_parse_ids(c, m):
    c.section("parse_ids 输入解析")

    c.eq(m.parse_ids("1001,1002")[0], [1001, 1002], "逗号分隔")
    c.eq(m.parse_ids("1001，1002；1003 1004\n1005、1006")[0],
         [1001, 1002, 1003, 1004, 1005, 1006], "中英文分隔符混排")
    c.eq(m.parse_ids("1005-1010")[0], [1005, 1006, 1007, 1008, 1009, 1010], "区间展开")
    c.eq(m.parse_ids("1010~1005")[0], [1005, 1006, 1007, 1008, 1009, 1010], "倒序区间归一")
    c.eq(m.parse_ids(" 1007 - 1009 ")[0], [1007, 1008, 1009], "区间两侧留白")
    c.eq(m.parse_ids("1001,1001,1002")[0], [1001, 1002], "重复 ID 去重")
    c.eq(m.parse_ids("")[0], [], "空字符串")
    c.eq(m.parse_ids(None)[0], [], "None 不崩")
    c.eq(m.parse_ids("   \n  ")[0], [], "只有空白字符")

    c.eq(m.parse_ids("abc,12a")[0], [], "非数字不产生 ID")
    c.eq(m.parse_ids("abc,12a")[1], ["abc", "12a"], "无法解析的 token 被收集")
    c.eq(m.parse_ids("1001-1002-1003")[1], ["1001-1002-1003"], "三段连字符判为非法")
    c.eq(m.parse_ids("-5")[1], ["-5"], "负数判为非法")

    c.eq(m.parse_ids("1-999999")[1], ["1-999999"], "超大区间被拦下（不卡死）")
    c.eq(m.parse_ids("1-1")[0], [1], "单点区间")

    both = m.parse_ids("1001, bad, 1005-1006")
    c.eq(both[0], [1001, 1005, 1006], "合法与非法混排时只取合法的")
    c.eq(both[1], ["bad"], "非法项单独返回")


def t_id_system(c, m):
    c.section("自建 ID：自动编号 / 查表 / 重复重排")

    m.ensure_ids()
    base = baseline_max(m)

    a = make_object("甲")
    b = make_object("乙")
    d = make_object("丙")

    c.eq(m.id_of(a), None, "刚建出来还没有 ID")

    assigned, fixed, skipped = m.ensure_ids()
    c.eq(len(assigned), 3, "三个新物体各分配一个 ID")
    c.eq(fixed, [], "没有重复号要重排")
    c.eq(skipped, [], "没有跳过项")
    c.eq([v for _o, v in assigned], [base + 1, base + 2, base + 3],
         "按创建先后从现有最大值往后连号")
    c.eq([obj.name for obj, _v in assigned], [a.name, b.name, d.name], "先建的拿小号")
    c.eq(m.id_of(a), base + 1, "甲的 ID 写进自定义属性")
    c.eq(a.get(m.ID_PROP), base + 1, "确实落成自定义属性（随 .blend 保存）")

    assigned, fixed, skipped = m.ensure_ids()
    c.eq(assigned, [], "已经编好的不重复分配")
    c.eq(fixed, [], "稳定：再跑一次什么都不改")

    table = m.id_map()
    c.eq(table[m.id_of(a)], [a], "id_map 反查到甲")

    b_id = m.id_of(b)
    dup = make_object("副本")
    dup[m.ID_PROP] = b_id
    assigned, fixed, skipped = m.ensure_ids()
    c.eq(assigned, [], "复制品已经有号，不算新分配")
    c.eq(len(fixed), 1, "重复号被重排一个")
    c.eq(fixed[0][0].name, dup.name, "重排的是后建的副本，原件保号")
    c.eq(fixed[0][1], b_id, "记下了原来的重复号")
    c.ok(m.id_of(dup) != b_id, "重排后不再撞号")
    c.eq(m.id_of(b), b_id, "原件 ID 没被动过")

    renamed = make_object("0最前面")
    renamed[m.ID_PROP] = b_id
    assigned, fixed, skipped = m.ensure_ids()
    c.eq(fixed[0][0].name, renamed.name,
         "名字排在最前也抢不走原件的号（看的是创建先后不是名称）")
    c.eq(m.id_of(b), b_id, "原件 ID 依然没被动")

    bad = make_object("脏值")
    bad[m.ID_PROP] = "abc"
    c.eq(m.id_of(bad), None, "非法属性值读回 None 而不是崩")
    assigned, fixed, skipped = m.ensure_ids()
    c.ok(any(obj.name == bad.name for obj, _v in assigned), "脏值会被当成缺号重新分配")

    holder = make_object("占位")
    holder[m.ID_PROP] = 9001
    make_object("新号")
    assigned, _fixed, _skipped = m.ensure_ids()
    c.eq([v for _o, v in assigned], [9002], "新号接着全场景最大值 +1")

    gone = make_object("被删的")
    m.ensure_ids()
    gone_id = m.id_of(gone)
    bpy.data.objects.remove(gone, do_unlink=True)

    filler = make_object("替补")
    assigned, _fixed, _skipped = m.ensure_ids()
    c.eq([v for _o, v in assigned], [gone_id + 1],
         "最高号被删掉也不复用，新物体接着空号往上走")
    c.ok(gone_id not in [m.id_of(o) for o in bpy.data.objects if m.id_of(o) is not None],
         "被删的号确实没人占用")

    m.ensure_ids()
    c.eq(m.watermark(), gone_id + 1, "水位线随场景保存，记录到分配过的最大号")


def t_auto(c, m):
    c.section("自动写 ID：钩子与去抖")

    m._cancel_timer()
    for name, func in zip(m.HANDLER_NAMES, m.HANDLER_FUNCS):
        c.eq(getattr(bpy.app.handlers, name).count(func), 1, "%s 上恰好挂了一个钩子" % name)

    m.attach()
    m._cancel_timer()
    for name, func in zip(m.HANDLER_NAMES, m.HANDLER_FUNCS):
        c.eq(getattr(bpy.app.handlers, name).count(func), 1, "重复 attach 不叠加：%s" % name)
        c.ok("_bpy_persistent" in func.__dict__, "钩子带 @persistent：%s" % name)

    m._cancel_timer()
    m._STATE["pending"] = True
    m._STATE["count"] = -1
    m._on_depsgraph()
    c.ok(bpy.app.timers.is_registered(m._run),
         "排队标志与定时器脱节时自愈（旧代码会永久僵死，再也不补号）")
    m._cancel_timer()

    m._STATE["count"] = len(bpy.data.objects)
    m._on_depsgraph()
    c.eq(m._STATE["pending"], False, "物体数没变时不安排修补")

    obj = make_object("自动甲")
    m._on_depsgraph()
    c.ok(m._STATE["pending"], "新物体一出现就安排一次修补")
    c.ok(bpy.app.timers.is_registered(m._run), "修补真的进了定时器队列")
    m._on_depsgraph()
    c.eq(m._STATE["pending"], True, "反复触发只排队一次（去抖）")
    m._cancel_timer()
    c.eq(m._STATE["pending"], False, "取消后不再排队")
    c.eq(bpy.app.timers.is_registered(m._run), False, "取消后定时器真的摘掉了")

    m._run()
    c.ok(m.id_of(obj) is not None, "修补后自动拿到 ID")
    c.eq(m._STATE["count"], len(bpy.data.objects), "修补后同步物体数")
    c.eq(m._STATE["busy"], False, "修补结束后忙标志复位")
    c.eq(m._STATE["pending"], False, "修补结束后不再排队")

    m._STATE["busy"] = True
    m._STATE["count"] = -1
    m._on_depsgraph()
    c.eq(m._STATE["pending"], False, "修补进行中不再重复排队")
    m._STATE["busy"] = False

    fresh = make_object("自动乙")
    m._on_save()
    c.ok(m.id_of(fresh) is not None, "保存前同步补号")
    c.eq(m._STATE["busy"], False, "保存钩子结束后忙标志复位")

    m._STATE["count"] = -1
    m._on_load()
    c.ok(m._STATE["pending"], "打开文件后安排一次修补")
    m._cancel_timer()

    m._STATE["count"] = -1
    m._on_depsgraph()
    c.ok(m._STATE["pending"], "count 被重置时也会安排修补")
    m._cancel_timer()
    m._STATE["count"] = len(bpy.data.objects)


def t_linked(c, m):
    c.section("链接库物体不写 ID")

    keeper = make_object("本地甲")
    m.ensure_ids()
    keeper_id = m.id_of(keeper)
    c.ok(keeper_id is not None, "本地甲已经有 ID")

    path = os.path.join(tempfile.gettempdir(), "id_select_selftest_lib.blend")
    if os.path.exists(path):
        os.remove(path)

    src = make_object("库源")
    src[m.ID_PROP] = keeper_id
    m.detach()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        saved = True
    except Exception as exc:
        c.ok(False, "无法生成测试库文件", repr(exc))
        saved = False
    finally:
        m.attach()
        m._cancel_timer()
    if not saved:
        return

    bpy.data.objects.remove(src, do_unlink=True)

    linked = None
    try:
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            data_to.objects = [name for name in data_from.objects if name == PREFIX + "库源"]
        linked = data_to.objects[0] if data_to.objects else None
    except Exception as exc:
        c.ok(False, "无法链接库物体", repr(exc))

    if linked is None:
        c.ok(False, "库文件里没取到物体")
        try:
            os.remove(path)
        except OSError:
            pass
        return

    c.ok(linked.library is not None, "确实拿到的是链接库物体")
    c.eq(m.id_of(linked), keeper_id, "链接物体带着库里那个号过来，与本地撞号")
    bpy.context.scene.collection.objects.link(linked)

    _assigned, _fixed, skipped = m.ensure_ids()
    c.ok(linked in skipped, "链接库物体被跳过（不能往库里写）")
    c.eq(m.id_of(linked), keeper_id, "链接数据的属性没被改写")
    c.eq(m.id_of(keeper), keeper_id, "本地甲保号，没被链接物体顶掉")

    bpy.data.objects.remove(linked, do_unlink=True)
    try:
        os.remove(path)
    except OSError:
        pass


def t_selection(c, m):
    c.section("选中 / 反隐藏 / 跨集合")

    view_layer = bpy.context.view_layer
    a = make_object("选中甲")
    b = make_object("选中乙")

    selected, blocked, revealed = m.select_objects(bpy.context, [a])
    c.eq(len(selected), 1, "选中一个")
    c.eq(blocked, [], "没有阻塞项")
    c.ok(a.select_get(), "甲的选中状态为真")
    c.eq(view_layer.objects.active, a, "甲成为活动物体")

    m.select_objects(bpy.context, [b])
    c.ok(not a.select_get(), "换选后上一次的选择被清掉")
    c.ok(b.select_get(), "乙被选中")

    hidden = make_object("隐藏者")
    hidden.hide_set(True)
    c.ok(hidden.hide_get(), "先把它藏起来")
    selected, _blocked, revealed = m.select_objects(bpy.context, [hidden])
    c.ok(hidden in revealed, "隐藏物体被列进已反隐藏清单")
    c.ok(not hidden.hide_get(), "真的显示出来了")
    c.ok(hidden.select_get(), "并且被选中")

    view_hidden = make_object("视口禁用者")
    view_hidden.hide_viewport = True
    selected, _blocked, _revealed = m.select_objects(bpy.context, [view_hidden])
    c.ok(not view_hidden.hide_viewport, "视口禁用开关被清掉")
    c.ok(view_hidden.select_get(), "被选中")

    coll = bpy.data.collections.new(PREFIX + "集合")
    bpy.context.scene.collection.children.link(coll)
    inner = bpy.data.objects.new(PREFIX + "集合内", None)
    coll.objects.link(inner)
    layer_coll = view_layer.layer_collection.children[coll.name]
    layer_coll.exclude = True
    view_layer.update()
    c.ok(inner.name not in view_layer.objects, "排除后它确实不在视图层里")

    selected, _blocked, revealed = m.select_objects(bpy.context, [inner])
    c.eq(layer_coll.exclude, False, "排除开关被自动清掉")
    c.ok(inner.select_get(), "折叠集合里的物体也能被选中")

    loose = bpy.data.objects.new(PREFIX + "游离", None)
    c.eq(len(loose.users_collection), 0, "游离物体不属于任何集合")
    selected, blocked, _revealed = m.select_objects(bpy.context, [loose])
    c.eq(selected, [], "不在视图层的物体选不中")
    c.eq(len(blocked), 1, "被归入阻塞清单而不是静默丢弃")

    selected, _blocked, _revealed = m.select_objects(bpy.context, [a, loose, b])
    c.eq(len(selected), 2, "混合输入只选中可选的")
    c.eq(view_layer.objects.active, a, "活动物体取第一个命中的")

    m.clear_selection()
    c.eq(list(bpy.context.selected_objects), [], "清空选择")


def t_frame(c, m):
    c.section("缩放到物体")

    c.ok(isinstance(m.frame_selected(bpy.context), bool), "有窗口时返回布尔值且不崩")
    c.eq(m.frame_selected(types.SimpleNamespace(window=None)), False, "无窗口时返回 False")
    c.eq(m.frame_selected(types.SimpleNamespace()), False, "没有 window 字段时返回 False")
    c.eq(m.frame_selected(types.SimpleNamespace(
        window=types.SimpleNamespace(screen=types.SimpleNamespace(areas=[])))), False,
        "没有 3D 视图区域时返回 False")


def t_operators(c, m):
    c.section("按 ID 选择算子端到端")

    a = make_object("算子甲")
    b = make_object("算子乙")
    m.ensure_ids()

    state = getattr(bpy.context.window_manager, m.STATE_ATTR)

    state.ids_input = ""
    c.ok('CANCELLED' in bpy.ops.mf.idselect_select(), "空输入返回 CANCELLED")

    state.ids_input = "abc"
    c.ok('CANCELLED' in bpy.ops.mf.idselect_select(), "无法解析的输入返回 CANCELLED")

    state.ids_input = "999999"
    c.ok('CANCELLED' in bpy.ops.mf.idselect_select(), "查不到返回 CANCELLED")

    m.clear_selection()
    state.ids_input = str(m.id_of(a))
    c.ok('FINISHED' in bpy.ops.mf.idselect_select(), "按 ID 选择跑通")
    c.ok(a.select_get(), "目标物体被选中")
    c.eq(bpy.context.view_layer.objects.active, a, "目标成为活动物体")

    state.ids_input = "%d-%d" % (m.id_of(a), m.id_of(b))
    c.ok('FINISHED' in bpy.ops.mf.idselect_select(), "区间输入跑通")
    c.eq(sorted(o.name for o in bpy.context.selected_objects), sorted([a.name, b.name]),
         "区间把两个物体都选中")

    state.ids_input = "%d, 888888" % m.id_of(a)
    c.ok('FINISHED' in bpy.ops.mf.idselect_select(), "部分命中仍返回 FINISHED")


def t_metadata(c, m, uimod):
    c.section("元数据与工具箱命名约定")

    cls = uimod.MF_PT_IdSelect
    c.eq(cls.__name__, "MF_PT_IdSelect", "面板类名 MF_PT_*")
    c.eq(cls.bl_idname, "MF_PT_IdSelect", "面板 bl_idname 与类名一致")
    c.eq(cls.bl_space_type, 'VIEW_3D', "面板在 3D 视图")
    c.eq(cls.bl_region_type, 'UI', "面板在侧边栏")
    c.eq(cls.bl_category, uimod.utils.PANEL_CATEGORY, "bl_category 取自 core.utils.PANEL_CATEGORY")
    c.eq(cls.bl_label, "ID 选择查询", "面板标题")
    c.ok(isinstance(cls.bl_order, int) and cls.bl_order >= 0, "bl_order 是非负整数占位")
    c.ok('DEFAULT_CLOSED' in cls.bl_options, "默认折叠（模板要求）")
    c.ok("draw_header" in cls.__dict__, "面板自己写了 draw_header")
    c.ok(bool(getattr(cls, "MF_SEARCH_KEYWORDS", ())), "配了顶部搜索别名")
    c.ok("中文" not in str(cls.MF_SEARCH_KEYWORDS[:1]), "关键字表里有拼音缩写")
    c.ok(any(ord(ch) > 127 for kw in cls.MF_SEARCH_KEYWORDS for ch in kw), "关键字表里有中文别名")
    base = cls.__mro__[1].__name__
    c.ok(base in {"MF_ToolPanel", "Panel"}, "面板基类是 MF_ToolPanel（搜索条才过滤得到）", base)

    c.eq(m.MF_OT_IdSelect_SelectById.__name__, "MF_OT_IdSelect_SelectById", "算子类名 MF_OT_*")
    c.eq(m.MF_PG_IdSelectState.__name__, "MF_PG_IdSelectState", "参数组类名 MF_PG_*")
    c.eq(m.OP_SELECT, "mf.idselect_select", "按 ID 选择算子 idname")
    c.ok(m.OP_SELECT.startswith("mf."), "算子 idname 用 mf. 前缀")
    c.eq(m.OP_SELECT, m.MF_OT_IdSelect_SelectById.bl_idname, "算子 idname 与类同源")
    c.ok(bool(m.MF_OT_IdSelect_SelectById.bl_description), "按 ID 选择算子有 bl_description")
    c.eq(m.STATE_ATTR, "mf_idselect", "状态属性名带 mf_ 前缀")
    c.eq(m.ID_PROP, "mf_id", "写入物体的 ID 属性名带 mf_ 前缀")
    c.eq(m.TOOL_ID, "IdSelect", "TOOL_ID 用英文")

    c.eq(sorted(rna_names(m.MF_PG_IdSelectState)), ["ids_input"], "状态组字段只剩输入框")
    c.eq(m.MF_PG_IdSelectState.bl_rna.properties["ids_input"].default, "", "输入框默认空")

    c.eq(m.HANDLER_NAMES, ("depsgraph_update_post", "load_post", "save_pre"),
         "监听的三个钩子")
    c.eq(len(m.HANDLER_FUNCS), 3, "钩子函数正好三个")
    c.eq(sorted(m._STATE), ["busy", "count", "pending"], "内部状态只有三个键")


def t_panel_draw(c, m, uimod):
    c.section("面板 draw() 真跑一遍（假 layout）")

    cls = uimod.MF_PT_IdSelect
    state = getattr(bpy.context.window_manager, m.STATE_ATTR)

    obj = make_object("面板测试")
    m.select_objects(bpy.context, [obj])

    log = []
    cls.draw(FakePanel(FakeLayout(log), cls), bpy.context)
    c.ok(bool(log), "draw() 画出了控件")

    ops = [call[1][0] for call in log if call[0] == "operator" and call[1]]
    c.ok(m.OP_SELECT in ops, "面板画了「按 ID 选择查询」")
    c.ok(len(ops) == 1, "面板只剩一个按钮（取 ID 按钮已删除）", ops)

    props = [call[1][1] for call in log if call[0] == "prop" and len(call[1]) > 1]
    c.eq(props, ["ids_input"], "输入框指向 state.ids_input")
    c.ok(not any(call[0] == "box" for call in log), "结果区已删除，不再画 box")

    labels = [t for call in log if call[0] == "label" for t in call_texts(call)]
    c.ok(any("已选" in t for t in labels), "画出已选统计", labels)
    c.ok(not any("参数未就绪" in t for t in labels), "参数就绪时不画错误行")

    m.clear_selection()
    log = []
    cls.draw(FakePanel(FakeLayout(log), cls), bpy.context)
    labels = [t for call in log if call[0] == "label" for t in call_texts(call)]
    c.ok(any("未选中" in t for t in labels), "未选中时画提示行")

    log = []
    cls.draw(FakePanel(FakeLayout(log), cls),
             types.SimpleNamespace(window_manager=types.SimpleNamespace()))
    labels = [t for call in log if call[0] == "label" for t in call_texts(call)]
    c.ok(any("参数未就绪" in t for t in labels), "状态未就绪时画错误行而不是崩掉")

    hlog = []
    cls.draw_header(FakePanel(FakeLayout(hlog), cls), bpy.context)
    c.ok(any(call[0] == "label" for call in hlog), "draw_header 画了图标")


def t_conventions(c):
    c.section("工具箱约定（对照 mufeng_tool_template）")

    src = read_sources()
    all_src = "\n".join(src.values())

    c.ok(PKG.islower() and PKG.isascii() and " " not in PKG,
         "文件夹名全小写英文无空格（会变成工具 id）：%s" % PKG)
    c.ok(bool(re.fullmatch(r"[a-z][a-z0-9_]*", PKG)), "文件夹名只含小写字母/数字/下划线")

    c.ok('"""' not in all_src, "源码零 docstring")
    c.ok(not re.search(r"(?m)^\s*#", all_src), "源码零注释")

    c.ok("from ...core import utils" in src["operators.py"], "operators.py 三层相对导入 core")
    c.ok("from ...core import utils" in src["ui.py"], "ui.py 三层相对导入 core")
    c.ok("from .operators import" in src["ui.py"], "ui.py 同包内相对导入 operators")
    c.ok("except (ImportError, ValueError)" in all_src, "降级桩同时捕获 ImportError 与 ValueError")
    c.ok('bpy.types.Panel' in src["ui.py"], "ui.py 降级桩给独立的 MF_ToolPanel 兜底")
    c.ok("PANEL_CATEGORY=" in src["ui.py"], "ui.py 降级桩给 PANEL_CATEGORY 兜底")

    c.ok("utils.register_classes(classes)" in func_body(src["operators.py"], "register"),
         "operators.register 走 utils.register_classes")
    c.ok("utils.unregister_classes(classes)" in func_body(src["operators.py"], "unregister"),
         "operators.unregister 走 utils.unregister_classes")
    c.ok("utils.register_classes(classes)" in func_body(src["ui.py"], "register"),
         "ui.register 走 utils.register_classes")
    c.ok("utils.unregister_classes(classes)" in func_body(src["ui.py"], "unregister"),
         "ui.unregister 走 utils.unregister_classes")
    c.ok("bpy.utils.register_class" not in func_body(src["operators.py"], "register"),
         "operators.register 没裸写 register_class")

    c.ok("bl_category = utils.PANEL_CATEGORY" in src["ui.py"], "bl_category 取自 utils")
    c.ok("DEFAULT_CLOSED" in src["ui.py"], "面板带 DEFAULT_CLOSED")
    c.ok("def draw_header" in src["ui.py"], "写了 draw_header")
    c.ok("MF_SEARCH_KEYWORDS" in src["ui.py"], "配了搜索别名")
    c.ok("bl_rna" not in src["ui.py"], "draw 里不做 bl_rna 自省（模板红线 3）")
    c.ok("template_list" not in all_src, "没有用 template_list")
    c.ok("bpy.types.Scene" not in all_src, "没有往 Scene 挂全局属性（模板红线 4）")
    c.ok("bpy.types.WindowManager" in src["operators.py"],
         "面板状态挂 WindowManager（与本箱其它工具一致）")
    c.ok("bl_info" not in src["__init__.py"], "子包没有 bl_info（全箱只有根包一份）")
    c.ok("pkgutil" not in all_src, "子包不自建自动发现（根包统一扫）")
    c.ok("selftest" not in src["__init__.py"], "__init__ 不导入 selftest")
    c.ok("from . import operators" in src["__init__.py"], "子包导出 operators")
    c.ok("from . import ui" in src["__init__.py"], "子包导出 ui")

    imports = [ln.strip() for ln in all_src.splitlines() if ln.startswith(("import ", "from "))]
    bad = [ln for ln in imports if any(k in ln for k in ("numpy", "bsmax", "PIL", "third_party"))]
    c.ok(not bad, "没有引入第三方依赖", bad)

    icons_used = set(re.findall(r"icon='([A-Z0-9_]+)'", all_src))
    icons_enum = set(bpy.types.UILayout.bl_rna.functions["label"]
                     .parameters["icon"].enum_items.keys())
    c.ok(bool(icons_used), "确实扫到了图标字面量（守卫非空跑）", sorted(icons_used))
    c.ok(icons_used <= icons_enum, "图标全在 RNA 枚举内", sorted(icons_used - icons_enum))

    c.ok("bpy.app.handlers" in src["operators.py"], "自动补号挂了应用钩子")
    c.ok("depsgraph_update_post" in src["operators.py"], "监控 depsgraph 更新")
    c.ok("load_post" in src["operators.py"], "打开文件有兜底")
    c.ok("save_pre" in src["operators.py"], "保存前有兜底")
    c.ok("bpy.app.timers.register" in src["operators.py"], "补号延到定时器里做")
    c.ok("from bpy.app.handlers import persistent" in src["operators.py"],
         "钩子用 bpy.app.handlers.persistent 标记")
    c.eq(src["operators.py"].count("@persistent"), 3,
         "三个钩子各戴一个 @persistent（否则打开文件就被 Blender 清光）")
    c.ok("persistent=True" in src["operators.py"], "补号定时器跨文件加载也存活")
    c.ok("bpy.app.timers.is_registered(_run)" in src["operators.py"],
         "排队标志按定时器实际情况自愈，不会假排队僵死")
    c.ok("timers.unregister(_run)" in src["operators.py"],
         "取消定时器按函数名注销（5.2 的 register 不返回句柄）")
    c.ok("session_uid" in src["operators.py"],
         "按 session_uid 定创建先后（bpy.data.objects 是按名称迭代的，不能直接用）")
    c.ok("WATERMARK_KEY" in src["operators.py"],
         "水位线存在场景自定义属性（删掉的 ID 永不复用）")

    for fn in PROD_FILES:
        c.ok(fn in src and bool(src[fn].strip()), "%s 非空" % fn)


def t_registration(c, m, uimod, root, external):
    c.section("注册 / 注销往返")
    if external:
        c.ok(True, "[跳过] 已在别处注册，不做往返测试")
        return

    c.ok(hasattr(bpy.types.WindowManager, m.STATE_ATTR), "WindowManager 上出现状态组")
    c.ok(not hasattr(bpy.context.scene, m.STATE_ATTR), "Scene 上没有同名属性")
    c.ok(hasattr(bpy.types, uimod.MF_PT_IdSelect.bl_idname), "面板类出现在 bpy.types")
    c.ok(op_registered("idselect_select"), "算子 mf.idselect_select 已注册")

    state = getattr(bpy.context.window_manager, m.STATE_ATTR)
    state.ids_input = "7,8"
    c.eq(state.ids_input, "7,8", "状态可写")

    root.unregister()
    c.ok(not hasattr(bpy.types.WindowManager, m.STATE_ATTR), "注销后 WindowManager 属性已移除")
    c.ok(not hasattr(bpy.types, uimod.MF_PT_IdSelect.bl_idname), "注销后面板类已移除")
    c.ok(not op_registered("idselect_select"), "注销后算子已移除")
    for name, func in zip(m.HANDLER_NAMES, m.HANDLER_FUNCS):
        c.eq(getattr(bpy.app.handlers, name).count(func), 0, "注销后钩子摘掉：%s" % name)
    c.eq(bpy.app.timers.is_registered(m._run), False, "注销后待执行的修补被取消")

    root.register()
    c.ok(hasattr(bpy.types.WindowManager, m.STATE_ATTR), "二次注册成功")
    c.ok(op_registered("idselect_select"), "二次注册后算子回来")
    c.ok(hasattr(bpy.types, uimod.MF_PT_IdSelect.bl_idname), "二次注册后面板回来")
    for name, func in zip(m.HANDLER_NAMES, m.HANDLER_FUNCS):
        c.eq(getattr(bpy.app.handlers, name).count(func), 1, "二次注册后钩子回来：%s" % name)
    m._cancel_timer()

    again = getattr(bpy.context.window_manager, m.STATE_ATTR)
    c.eq(again.ids_input, "7,8",
         "二次注册后沿用上次的值（WindowManager 存量不随注销清除）")
    again.ids_input = ""


def t_reload(c, m):
    c.section("打开 .blend 后钩子仍在（@persistent 回归）")

    objs = [make_object("重载%d" % i) for i in range(3)]
    path = os.path.join(tempfile.gettempdir(), "id_select_selftest_reload.blend")
    if os.path.exists(path):
        os.remove(path)

    m.detach()
    try:
        for obj in objs:
            if m.ID_PROP in obj:
                del obj[m.ID_PROP]
        c.ok(all(m.id_of(o) is None for o in objs),
             "存盘前清掉 ID（模拟工程文件里本来就没有号）")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        saved = True
    except Exception as exc:
        c.ok(False, "无法生成测试文件", repr(exc))
        saved = False
    finally:
        m.attach()
    if not saved:
        return

    bpy.ops.wm.open_mainfile(filepath=path)

    c.ok(all("_bpy_persistent" in f.__dict__ for f in m.HANDLER_FUNCS),
         "打开文件后三个钩子没被 Blender 清掉")
    c.ok(m._on_load in bpy.app.handlers.load_post, "load_post 上还挂着打开文件的兜底")
    c.ok(m._on_depsgraph in bpy.app.handlers.depsgraph_update_post, "depsgraph 上还挂着监控")
    c.ok(m._on_save in bpy.app.handlers.save_pre, "save_pre 上还挂着保存前兜底")
    c.eq(m._STATE["count"], -1, "打开文件后物体数缓存作废，会重算")
    c.ok(bpy.app.timers.is_registered(m._run),
         "已经排好一次补号（定时器跨文件加载也存活）")

    m._cancel_timer()
    m._run()
    ids = [m.id_of(o) for o in bpy.data.objects]
    c.ok(bool(ids) and all(v is not None for v in ids),
         "打开文件后场景里所有物体都补上了 ID", ids)

    try:
        os.remove(path)
    except OSError:
        pass


def main():
    print("=" * 72)
    print("id_select 子工具自检  |  Blender %s" % bpy.app.version_string)
    print("目录：%s" % THIS_DIR)
    print("=" * 72)

    cleanup()

    root = importlib.import_module(PKG)
    m = importlib.import_module(PKG + ".operators")
    uimod = importlib.import_module(PKG + ".ui")

    c = Checker()
    external = hasattr(bpy.types.WindowManager, m.STATE_ATTR)
    if external:
        print("\n[注意] 检测到状态已注册（模块可能已在工具箱里启用）")
    else:
        root.register()

    groups = (
        ("输入解析", lambda: t_parse_ids(c, m)),
        ("自建 ID", lambda: t_id_system(c, m)),
        ("自动写 ID 钩子", lambda: t_auto(c, m)),
        ("链接库跳过", lambda: t_linked(c, m)),
        ("选中 / 反隐藏 / 跨集合", lambda: t_selection(c, m)),
        ("缩放到物体", lambda: t_frame(c, m)),
        ("算子端到端", lambda: t_operators(c, m)),
        ("元数据与命名约定", lambda: t_metadata(c, m, uimod)),
        ("面板绘制", lambda: t_panel_draw(c, m, uimod)),
        ("工具箱约定", lambda: t_conventions(c)),
        ("注册 / 注销往返", lambda: t_registration(c, m, uimod, root, external)),
        ("打开文件后仍工作", lambda: t_reload(c, m)),
    )

    for label, fn in groups:
        try:
            fn()
        except Exception:
            c.failed += 1
            c.failures.append("测试组「%s」抛出异常" % label)
            print("  [FAIL] 测试组「%s」抛出异常" % label)
            traceback.print_exc()

    cleanup()

    if not external:
        try:
            root.unregister()
        except Exception:
            c.failed += 1
            c.failures.append("收尾注销失败")
            traceback.print_exc()
        c.ok(not hasattr(bpy.types.WindowManager, m.STATE_ATTR), "收尾后 WindowManager 属性已清掉")
        c.ok(not hasattr(bpy.types, uimod.MF_PT_IdSelect.bl_idname), "收尾后面板类已清掉")
        for name, func in zip(m.HANDLER_NAMES, m.HANDLER_FUNCS):
            c.eq(getattr(bpy.app.handlers, name).count(func), 0, "收尾后钩子已摘掉：%s" % name)
        c.eq(bpy.app.timers.is_registered(m._run), False, "收尾后没有排队中的修补")

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
