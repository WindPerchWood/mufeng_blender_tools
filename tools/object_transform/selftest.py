import importlib
import os
import sys
import tempfile
import traceback

import bpy

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

PKG = os.path.basename(THIS_DIR)
PROD_FILES = ("__init__.py", "operators.py", "ui.py")
PREFIX = "自检_OT_"
LIB_NAME = "object_transform_selftest_lib.blend"
SCENE_ATTR = "mf_ot_selftest_holder"
WM_TEST_ATTR = "mf_ot_selftest_wm"


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


class SelfHolder(bpy.types.PropertyGroup):
    target: bpy.props.PointerProperty(type=bpy.types.Object)


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


def op_registered(short):
    try:
        getattr(bpy.ops.mf, short).get_rna_type()
        return True
    except Exception:
        return False


def wipe_objects():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def cleanup():
    for obj in [o for o in bpy.data.objects if o.name.startswith(PREFIX)]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in [x for x in bpy.data.meshes if x.name.startswith(PREFIX)]:
        bpy.data.meshes.remove(mesh)
    for cam in [x for x in bpy.data.cameras if x.name.startswith(PREFIX)]:
        bpy.data.cameras.remove(cam)
    for group in [x for x in bpy.data.node_groups if x.name.startswith(PREFIX)]:
        bpy.data.node_groups.remove(group)
    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    if hasattr(bpy.types.WindowManager, WM_TEST_ATTR):
        delattr(bpy.types.WindowManager, WM_TEST_ATTR)
    for holder in [x for x in bpy.data.materials if x.name.startswith(PREFIX)]:
        bpy.data.materials.remove(holder)


def make_empty(name):
    obj = bpy.data.objects.new(PREFIX + name, None)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_mesh(name):
    data = bpy.data.meshes.new(PREFIX + name)
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    data.update()
    obj = bpy.data.objects.new(PREFIX + name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def names(objects):
    return sorted(o.name for o in objects)


REFERENCED_NAMES = ("约束目标", "修改器目标", "对焦目标", "驱动目标", "参数组目标", "节点默认值")
EXPECTED_DELETED = ("普通空物体", "有子级的子")


def build_reference_scene():
    make_empty("普通空物体")

    parent = make_empty("有子级")
    child = make_empty("有子级的子")
    child.parent = parent

    host = make_mesh("宿主")

    con_target = make_empty("约束目标")
    con = host.constraints.new('COPY_LOCATION')
    con.target = con_target

    mod_target = make_empty("修改器目标")
    mod = host.modifiers.new(PREFIX + "镜像", 'MIRROR')
    mod.mirror_object = mod_target

    dof_target = make_empty("对焦目标")
    cam = bpy.data.objects.new(PREFIX + "相机", bpy.data.cameras.new(PREFIX + "相机"))
    bpy.context.scene.collection.objects.link(cam)
    cam.data.dof.focus_object = dof_target

    driver_target = make_empty("驱动目标")
    curve = host.driver_add("location", 0)
    curve.driver.type = 'SUM'
    var = curve.driver.variables.new()
    var.type = 'TRANSFORMS'
    var.targets[0].id = driver_target
    var.targets[0].transform_type = 'LOC_X'

    pg_target = make_empty("参数组目标")
    bpy.types.Scene.mf_ot_selftest_holder = bpy.props.PointerProperty(type=SelfHolder)
    bpy.context.scene.mf_ot_selftest_holder.target = pg_target

    socket_target = make_empty("节点默认值")
    group = bpy.data.node_groups.new(PREFIX + "节点组", 'GeometryNodeTree')
    sock = group.interface.new_socket("OBJ", in_out='INPUT', socket_type='NodeSocketObject')
    sock.default_value = socket_target


def t_detection(c, m):
    c.section("识别可删空物体")
    cleanup()
    build_reference_scene()

    targets, skipped = m.collect_clearable_empties(bpy.context)
    c.eq(names(targets), [PREFIX + n for n in EXPECTED_DELETED], "只挑出无子级且无引用的空物体")
    c.eq(skipped["children"], 1, "有子级的空物体被跳过")
    c.eq(skipped["referenced"], len(REFERENCED_NAMES), "被引用的空物体全部被跳过")
    c.eq(skipped["linked"], 0, "没有链接库物体")

    for name in REFERENCED_NAMES:
        obj = bpy.data.objects.get(PREFIX + name)
        c.ok(obj is not None, "%s 还在场景里" % name)

    used = m.referenced_pointers(bpy.context)
    c.ok(bpy.data.objects[PREFIX + "约束目标"].as_pointer() in used, "约束目标被认出")
    c.ok(bpy.data.objects[PREFIX + "普通空物体"].as_pointer() not in used, "普通空物体不在引用集合里")
    c.ok(bpy.data.objects[PREFIX + "驱动目标"].as_pointer() in used, "驱动目标被认出")
    c.ok(bpy.data.objects[PREFIX + "参数组目标"].as_pointer() in used, "参数组里的目标被认出")
    c.ok(bpy.data.objects[PREFIX + "节点默认值"].as_pointer() in used, "节点组 socket 默认值被认出")
    c.ok(bpy.data.objects[PREFIX + "有子级"].as_pointer() in used, "父级关系被认出")


def t_nothing_to_do(c, m):
    c.section("没有可删空物体时的返回")
    cleanup()
    make_mesh("孤立网格")
    status, message = m.op_clear_empties(bpy.context)
    c.eq(status, 'CANCELLED', "场景里没有空物体时返回 CANCELLED")
    c.eq(message, "没有可清除的空物体", "提示说明没有可清除的")

    cleanup()
    keep = make_empty("被引用的空物体")
    host = make_mesh("宿主甲")
    host.constraints.new('COPY_LOCATION').target = keep
    status, message = m.op_clear_empties(bpy.context)
    c.eq(status, 'CANCELLED', "空物体全被引用时返回 CANCELLED")
    c.ok("被引用 1" in message, "提示里写清了跳过原因", message)

    cleanup()
    parent = make_empty("唯一父级")
    make_empty("唯一子级").parent = parent
    child_name = bpy.data.objects[PREFIX + "唯一子级"].name
    status, message = m.op_clear_empties(bpy.context)
    c.eq(status, 'FINISHED', "有子级的空物体本身不删，但它的叶子子物体可以删")
    c.ok(parent.name in bpy.data.objects, "有子级的空物体被保留")
    c.ok(child_name not in bpy.data.objects, "无子级的子物体被清掉")
    c.ok("有子级 1" in message, "报告里写明了有子级跳过", message)
    bpy.context.view_layer.update()
    c.eq(len(parent.children), 0, "保留下来后它变成叶子")


def t_operator(c, m):
    c.section("算子端到端")
    cleanup()
    build_reference_scene()

    before = set(o.name for o in bpy.data.objects)
    mesh_before = len([o for o in bpy.data.objects if o.type == 'MESH'])

    result = bpy.ops.mf.rotmode_clear_empties()
    c.eq(result, {'FINISHED'}, "算子返回 FINISHED")

    after = set(o.name for o in bpy.data.objects)
    c.eq(sorted(before - after), [PREFIX + n for n in EXPECTED_DELETED], "只删掉该删的两个空物体")
    c.eq(sorted(after - before), [], "没有意外新增对象")

    for name in REFERENCED_NAMES + ("有子级",):
        c.ok(PREFIX + name in bpy.data.objects, "保留了 %s" % name)
    c.eq(len([o for o in bpy.data.objects if o.type == 'MESH']), mesh_before, "网格物体一个没少")

    remaining = [o.name for o in bpy.data.objects if o.type == 'EMPTY']
    c.eq(sorted(remaining), sorted(PREFIX + n for n in REFERENCED_NAMES + ("有子级",)),
         "剩下的空物体正是被保护的那些")

    host = bpy.data.objects[PREFIX + "宿主"]
    c.eq(len(host.constraints), 1, "宿主的约束还在")
    c.eq(len(host.modifiers), 1, "宿主的修改器还在")
    c.eq(host.modifiers[0].mirror_object.name, PREFIX + "修改器目标", "修改器目标没被删")
    c.eq(host.constraints[0].target.name, PREFIX + "约束目标", "约束目标没被删")

    cam = bpy.data.objects[PREFIX + "相机"]
    c.eq(cam.data.dof.focus_object.name, PREFIX + "对焦目标", "相机对焦目标没被删")


def t_metadata_note(c, m):
    c.section("自定义数据提示")
    cleanup()
    plain = make_empty("干净空物体")
    rich = make_empty("带数据空物体")
    rich["ElementID"] = 319420
    rich["mf_id"] = 2179

    status, message = m.op_clear_empties(bpy.context)
    c.eq(status, 'FINISHED', "两个空物体都被清掉")
    c.ok("已清除空物体 2 个" in message, "数量正确", message)
    c.ok("其中 1 个带自定义数据" in message, "只把带额外数据的那个算进去", message)
    c.ok(bpy.data.objects.get(PREFIX + "干净空物体") is None, "干净空物体已删除")
    c.ok(bpy.data.objects.get(PREFIX + "带数据空物体") is None, "带数据空物体已删除")


def t_mf_id_not_counted(c, m):
    c.section("mf_id 不算自定义数据")
    cleanup()
    for index in range(3):
        make_empty("带号空物体%d" % index)["mf_id"] = 1000 + index
    status, message = m.op_clear_empties(bpy.context)
    c.eq(status, 'FINISHED', "三个空物体都被清掉")
    c.ok("带自定义数据" not in message, "只有 mf_id 时不提示自定义数据", message)


def t_linked(c, m):
    c.section("链接库里的空物体不删")
    cleanup()
    path = os.path.join(tempfile.gettempdir(), LIB_NAME)
    if os.path.exists(path):
        os.remove(path)

    src = make_empty("库源空物体")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        saved = True
    except Exception as exc:
        c.ok(False, "无法生成测试库文件", repr(exc))
        saved = False
    if not saved:
        return

    bpy.data.objects.remove(src, do_unlink=True)

    linked = None
    try:
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            data_to.objects = [n for n in data_from.objects if n == PREFIX + "库源空物体"]
        linked = data_to.objects[0] if data_to.objects else None
    except Exception as exc:
        c.ok(False, "无法链接库物体", repr(exc))

    if linked is None:
        c.ok(False, "库文件里没取到空物体")
        return

    try:
        bpy.context.scene.collection.objects.link(linked)
        c.ok(linked.library is not None, "取到的物体确实来自链接库")

        local = make_empty("本地空物体")
        local_name = local.name
        targets, skipped = m.collect_clearable_empties(bpy.context)
        c.eq(skipped["linked"], 1, "链接库空物体计入跳过")
        c.ok(linked.name not in [o.name for o in targets], "链接库空物体不在删除名单里")
        c.eq(names(targets), [local_name], "只挑出本地那个")

        status, message = m.op_clear_empties(bpy.context)
        c.eq(status, 'FINISHED', "算子正常完成")
        c.ok(linked.name in bpy.data.objects, "链接库空物体被保留")
        c.ok(local_name not in bpy.data.objects, "本地空物体被清掉")
        c.ok("来自链接库 1" in message, "报告里写清了链接库跳过", message)
    finally:
        for obj in [o for o in bpy.data.objects if o.name.startswith(PREFIX)]:
            bpy.data.objects.remove(obj, do_unlink=True)
        for lib in [x for x in bpy.data.libraries if x.filepath == path]:
            bpy.data.libraries.remove(lib)
        if os.path.exists(path):
            os.remove(path)


def t_wm_holder(c, m):
    c.section("工具参数里的引用（WindowManager 属性组）")
    cleanup()
    target = make_empty("工具参数目标")
    unused = make_empty("无引用空物体")
    target_name = target.name
    unused_name = unused.name

    setattr(bpy.types.WindowManager, WM_TEST_ATTR,
            bpy.props.PointerProperty(type=SelfHolder))
    try:
        holder = getattr(bpy.context.window_manager, WM_TEST_ATTR)
        c.ok(holder is not None, "WindowManager 上的属性组可读")
        holder.target = target
        c.ok(holder.target is target, "值写进去了")

        used = m.referenced_pointers(bpy.context)
        c.ok(target.as_pointer() in used, "工具参数里的物体指针被认出")
        c.ok(unused.as_pointer() not in used, "没被引用的空物体没被误判")

        targets, skipped = m.collect_clearable_empties(bpy.context)
        c.eq(names(targets), [unused_name], "被工具参数引用的空物体不删")
        c.eq(skipped["referenced"], 1, "该跳过 1 个")

        status, message = m.op_clear_empties(bpy.context)
        c.eq(status, 'FINISHED', "算子正常完成")
        c.ok(target_name in bpy.data.objects, "被工具参数引用的空物体被保留")
        c.ok(unused_name not in bpy.data.objects, "无引用的空物体被清掉")
        c.ok("被引用 1" in message, "报告里写明了被引用跳过", message)
    finally:
        try:
            delattr(bpy.types.WindowManager, WM_TEST_ATTR)
        except Exception:
            c.ok(False, "临时 WindowManager 属性没能清掉")


def t_prefs_scan(c, m):
    c.section("插件偏好设置扫描不报错")
    out = set()
    scanned = 0
    for entry in bpy.context.preferences.addons:
        try:
            prefs = entry.preferences
        except Exception:
            continue
        if prefs is None:
            continue
        m._collect(prefs, out)
        scanned += 1
    c.ok(scanned > 0, "确实扫到了插件的偏好设置对象（守卫不是空跑）")
    c.ok(isinstance(out, set), "扫描结果是个集合")

    used = m.referenced_pointers(bpy.context)
    c.ok(isinstance(used, set), "完整扫描流程不抛异常")
    c.eq(out - used, set(), "偏好设置扫出来的东西都包含在完整结果里")


def t_existing_ops(c, m):
    c.section("原有算子回归")
    cleanup()

    for short in ("rotmode_set", "rotmode_unparent", "rotmode_single_user",
                  "rotmode_apply_transform"):
        c.ok(op_registered(short), "算子仍在：%s" % short)

    make_empty("甲")
    make_empty("乙")
    c.eq(bpy.ops.mf.rotmode_set(mode='QUATERNION'), {'FINISHED'}, "设置旋转模式返回 FINISHED")
    c.eq(bpy.data.objects[PREFIX + "甲"].rotation_mode, 'QUATERNION', "旋转模式已改")
    c.eq(bpy.data.objects[PREFIX + "乙"].rotation_mode, 'QUATERNION', "全场景都改了")

    parent = make_empty("父")
    parent.location = (5.0, 0.0, 0.0)
    parent.scale = (2.0, 2.0, 2.0)
    kid = make_empty("子")
    kid.location = (1.0, 0.0, 0.0)
    kid.parent = parent
    bpy.context.view_layer.update()
    world_before = kid.matrix_world.translation.copy()
    c.ok(bpy.ops.mf.rotmode_unparent() in ({'FINISHED'}, {'CANCELLED'}), "解除父级算子可执行")
    bpy.context.view_layer.update()
    c.ok(kid.parent is None, "父级已解除")
    c.ok((kid.matrix_world.translation - world_before).length < 1e-4, "解除父级后位置没跳")

    shared = bpy.data.meshes.new(PREFIX + "共享网格")
    shared.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    shared.update()
    o1 = bpy.data.objects.new(PREFIX + "共享甲", shared)
    o2 = bpy.data.objects.new(PREFIX + "共享乙", shared)
    for obj in (o1, o2):
        bpy.context.scene.collection.objects.link(obj)
    c.eq(shared.users, 2, "两个物体确实共用一份网格")
    bpy.ops.mf.rotmode_single_user()
    c.ok(o1.data.users == 1 and o2.data.users == 1, "全部变单体后各自独立")
    c.ok(o1.data is not o2.data, "网格数据已拆开")

    box = make_mesh("待应用")
    box.location = (3.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    bpy.ops.mf.rotmode_apply_transform()
    bpy.context.view_layer.update()
    c.ok(box.location.length < 1e-5, "应用变换后位置归零")
    c.ok(abs(box.data.vertices[0].co.x - 3.0) < 1e-4, "位移已烧进网格数据")


def t_metadata(c, m, uimod):
    c.section("元数据与命名约定")
    c.eq(m.CLEAR_EMPTIES_OP_ID, "mf.rotmode_clear_empties", "新算子 idname")
    c.ok(m.CLEAR_EMPTIES_OP_ID.startswith("mf."), "idname 带 mf. 前缀")
    cls = m.MF_OT_RotMode_ClearEmpties
    c.eq(cls.bl_idname, m.CLEAR_EMPTIES_OP_ID, "算子类与 idname 对应")
    c.ok(cls.__name__.startswith("MF_OT_"), "算子类名前缀 MF_OT_")
    c.ok(bool(cls.bl_description), "算子有 bl_description")
    c.eq(cls.bl_label, "清除空物体", "算子 bl_label")
    c.ok("UNDO" in cls.bl_options, "算子注册了 UNDO")

    panel = uimod.MF_PT_RotMode
    c.eq(panel.bl_idname, "MF_PT_RotMode", "面板 bl_idname 未变")
    c.ok(panel.__name__.startswith("MF_PT_"), "面板类名前缀 MF_PT_")
    c.ok(issubclass(panel, uimod.utils.MF_ToolPanel), "面板继承 MF_ToolPanel")
    c.eq(panel.bl_category, uimod.utils.PANEL_CATEGORY, "面板分类走 PANEL_CATEGORY")
    c.ok("DEFAULT_CLOSED" in panel.bl_options, "面板默认折叠")
    for kw in ("空物体", "kongwuti", "empty", "qingchu", "clear"):
        c.ok(kw in panel.MF_SEARCH_KEYWORDS, "搜索关键词含 %s" % kw)
    c.eq(m.WM_ATTR, "mf_rotmode", "WindowManager 属性名未变")
    c.eq(len(m.classes), 6, "operators 注册 6 个类")
    c.eq([x.__name__ for x in uimod.classes], ["MF_PT_RotMode"], "ui 只注册一个面板")
    c.ok(op_registered("rotmode_clear_empties"), "新算子已注册")


def t_panel_draw(c, m, uimod):
    c.section("面板绘制")
    log = []
    panel = FakePanel(FakeLayout(log), uimod.MF_PT_RotMode)
    uimod.MF_PT_RotMode.draw(panel, bpy.context)

    texts = [t for call in log for t in call_texts(call)]
    c.ok("清除空物体" in texts, "画出了「清除空物体」按钮")
    c.ok(m.CLEAR_EMPTIES_OP_ID in texts, "按钮绑定了正确算子")
    ops_drawn = sorted(t for t in texts if t.startswith("mf."))
    c.eq(ops_drawn, sorted([m.OP_ID, m.UNPARENT_OP_ID, m.SINGLE_USER_OP_ID,
                            m.APPLY_TRS_OP_ID, m.CLEAR_EMPTIES_OP_ID]),
         "五个算子按钮全部画出来")

    call_names = [call[0] for call in log]
    c.ok("separator" not in call_names, "按钮之间不留间隔（面板不画 separator）")
    c.eq(call_names.count("operator"), 5, "算子按钮恰好五个")

    log2 = []
    panel2 = FakePanel(FakeLayout(log2), uimod.MF_PT_RotMode)
    uimod.MF_PT_RotMode.draw_header(panel2, bpy.context)
    header_texts = [t for call in log2 for t in call_texts(call)]
    c.ok("LOOP_FORWARDS" in header_texts, "标题图标没变")


def t_conventions(c, m):
    c.section("源码约定")
    sources = read_sources()
    for fn, src in sources.items():
        c.ok('"""' not in src and "'''" not in src, "%s 没有 docstring" % fn)
        c.ok("#" not in src, "%s 没有行注释" % fn)
    c.eq(sorted(sources), sorted(PROD_FILES), "三个必备文件都在")

    code = sources["operators.py"]
    for dead in ("_pg_objects", "_pointer_objects", "_add_object", "SKIPPED_POINTERS"):
        c.ok(dead not in code, "operators.py 里没有遗留的旧函数名 %s" % dead)
    c.ok("_collect(" in code, "引用扫描统一走 _collect")
    c.eq(code.count("def _collect("), 1, "_collect 只有一个定义")


def t_registration(c, m, uimod, root, external):
    c.section("注册 / 注销往返")
    if external:
        c.ok(True, "模块已由工具箱注册，跳过往返测试")
        return
    root.unregister()
    c.ok(not hasattr(bpy.types, uimod.MF_PT_RotMode.bl_idname), "注销后面板类已清掉")
    c.ok(not hasattr(bpy.types.WindowManager, m.WM_ATTR), "注销后 WindowManager 属性已清掉")
    c.ok(not op_registered("rotmode_clear_empties"), "注销后新算子不可用")
    root.register()
    c.ok(op_registered("rotmode_clear_empties"), "重新注册后新算子可用")
    c.ok(hasattr(bpy.types, uimod.MF_PT_RotMode.bl_idname), "重新注册后面板可用")
    c.ok(hasattr(bpy.types.WindowManager, m.WM_ATTR), "重新注册后 WindowManager 属性回来了")


def main():
    print("=" * 72)
    print("object_transform 自检")

    wipe_objects()
    bpy.utils.register_class(SelfHolder)

    root = importlib.import_module(PKG)
    m = importlib.import_module(PKG + ".operators")
    uimod = importlib.import_module(PKG + ".ui")

    c = Checker()
    external = hasattr(bpy.types.WindowManager, m.WM_ATTR)
    if external:
        print("\n[注意] 检测到状态已注册（模块可能已在工具箱里启用）")
    else:
        root.register()

    groups = (
        ("识别可删空物体", lambda: t_detection(c, m)),
        ("无可删时的返回", lambda: t_nothing_to_do(c, m)),
        ("算子端到端", lambda: t_operator(c, m)),
        ("自定义数据提示", lambda: t_metadata_note(c, m)),
        ("mf_id 不算自定义数据", lambda: t_mf_id_not_counted(c, m)),
        ("链接库跳过", lambda: t_linked(c, m)),
        ("工具参数引用", lambda: t_wm_holder(c, m)),
        ("偏好设置扫描", lambda: t_prefs_scan(c, m)),
        ("原有算子回归", lambda: t_existing_ops(c, m)),
        ("元数据与命名约定", lambda: t_metadata(c, m, uimod)),
        ("面板绘制", lambda: t_panel_draw(c, m, uimod)),
        ("源码约定", lambda: t_conventions(c, m)),
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

    cleanup()

    if not external:
        try:
            root.unregister()
        except Exception:
            c.failed += 1
            c.failures.append("收尾注销失败")
            traceback.print_exc()
        c.ok(not hasattr(bpy.types.WindowManager, m.WM_ATTR), "收尾后 WindowManager 属性已清掉")
        c.ok(not hasattr(bpy.types, uimod.MF_PT_RotMode.bl_idname), "收尾后面板类已清掉")

    try:
        bpy.utils.unregister_class(SelfHolder)
    except Exception:
        c.ok(False, "SelfHolder 注销失败")

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
