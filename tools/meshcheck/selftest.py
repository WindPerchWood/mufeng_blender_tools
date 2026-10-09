import inspect
import re
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import algorithms as core
from . import markers
from . import operators as ops
from . import ui

class Harness:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.lines = []

    def title(self, text):
        self.lines.append("")
        self.lines.append("── %s " % text + "─" * max(0, 46 - len(text)))

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            self.lines.append("  PASS  %s" % name)
        else:
            self.failed += 1
            suffix = "   <- %s" % detail if detail else ""
            self.lines.append("  FAIL  %s%s" % (name, suffix))

    def eq(self, name, got, want):
        self.check(name, got == want, "得到 %r，期望 %r" % (got, want))

    def ge(self, name, got, least):
        self.check(name, got >= least, "得到 %r，至少应为 %r" % (got, least))

def _wipe_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.collections, bpy.data.cameras):
        for item in list(block):
            if item.users == 0:
                try:
                    block.remove(item)
                except Exception:
                    pass

def _deselect_all():
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        for obj in bpy.context.view_layer.objects:
            if obj is not None:
                obj.select_set(False)
    bpy.context.view_layer.objects.active = None

def _select(objs):
    _deselect_all()
    for obj in objs:
        obj.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]

def _sample(kind, size=1.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if kind == "clean":
        return bm

    if kind == "one_flipped":
        bm.faces[0].normal_flip()
        return bm

    if kind == "all_flipped":
        for face in bm.faces:
            face.normal_flip()
        return bm

    if kind == "hole":
        bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES_ONLY")
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    if kind == "loose":

        first = bm.verts.new((size * 3.0, 0.0, 0.0))
        second = bm.verts.new((size * 3.0, size, 0.0))
        bm.edges.new((first, second))
        bm.verts.new((0.0, size * 3.0, 0.0))
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        return bm

    if kind == "duplicate_face":
        face = bm.faces[1]
        bmesh.ops.duplicate(bm, geom=[face] + list(face.edges) + list(face.verts))
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    if kind == "near_duplicate":
        face = bm.faces[2]
        result = bmesh.ops.duplicate(bm, geom=[face] + list(face.edges) + list(face.verts))
        for element in result.get("geom", []):
            if isinstance(element, bmesh.types.BMVert):
                element.co.x += 1e-6
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    if kind == "vertex_touch":


        bmesh.ops.create_cube(bm, size=size)
        bmesh.ops.create_cube(
            bm,
            size=size,
            matrix=Matrix.Translation((size, size, size)),
        )
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    if kind == "triple_edge":
        edge = bm.edges[0]
        v0, v1 = edge.verts[0], edge.verts[1]
        apex = bm.verts.new((v0.co + v1.co) * 0.5 + Vector((0.0, 0.0, size * 2.0)))
        bm.faces.new((v0, v1, apex))
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    return bm

def _analyze(bm, opts=None, max_markers=None):
    try:
        return core.analyze_bmesh(bm, opts=opts, max_markers=max_markers)
    finally:
        bm.free()

def _object_from_bmesh(name, bm):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj

def _test_flip(h):
    h.title("① 反转法线")

    rep = _analyze(_sample("clean"))
    h.eq("干净立方体：封闭", rep["closed"], True)
    h.eq("干净立方体：状态 OK", rep[core.FLIP]["status"], core.ST_OK)
    h.eq("干净立方体：反转面 0", rep[core.FLIP]["count"], 0)

    rep = _analyze(_sample("one_flipped"))
    h.eq("单面翻转：检出 1 个面", rep[core.FLIP]["count"], 1)
    h.eq("单面翻转：状态为 OK（非整体反转）", rep[core.FLIP]["status"], core.ST_OK)
    h.eq("单面翻转：给出 1 个标记位", len(rep[core.FLIP]["positions"]), 1)

    rep = _analyze(_sample("all_flipped"))
    h.eq("整体翻转：6 个面全部反了", rep[core.FLIP]["count"], 6)
    h.eq("整体翻转：状态 WHOLE_INWARD", rep[core.FLIP]["status"], core.ST_WHOLE_INWARD)
    h.check("整体翻转：有文字说明", bool(rep[core.FLIP]["note"]))

    rep = _analyze(_sample("hole"))
    h.eq("开放网格：判定为不封闭", rep["closed"], False)
    h.eq("开放网格：默认跳过反转法线", rep[core.FLIP]["status"], core.ST_SKIPPED_OPEN)
    h.eq("开放网格：跳过时计数为 0", rep[core.FLIP]["count"], 0)
    h.check("开放网格：不会产生红标记", len(rep[core.FLIP]["positions"]) == 0)

    rep = _analyze(_sample("hole"), opts={"flip_on_open": True})
    h.eq("开放网格+开启开关：状态 PARTIAL_OPEN", rep[core.FLIP]["status"], core.ST_PARTIAL_OPEN)

    rep = _analyze(_sample("clean"), opts={"check_flip": False})
    h.eq("关掉开关后不检测", rep[core.FLIP]["count"], 0)

def _test_nonmanifold(h):
    h.title("② 非流形边")

    rep = _analyze(_sample("clean"))
    h.eq("干净立方体：非流形 0", rep[core.NONMANIFOLD]["count"], 0)

    rep = _analyze(_sample("hole"))
    h.eq("挖掉一个面：边界边 4 条", rep[core.NONMANIFOLD]["boundary"], 4)
    h.eq("挖掉一个面：非流形合计 4", rep[core.NONMANIFOLD]["count"], 4)
    h.eq("挖掉一个面：无悬空线", rep[core.NONMANIFOLD]["wire"], 0)

    rep = _analyze(_sample("loose"))
    h.eq("悬空线 1 条", rep[core.NONMANIFOLD]["wire"], 1)
    h.eq("孤立点 1 个", rep[core.NONMANIFOLD]["loose_verts"], 1)
    h.eq("悬空线端点不重复算作非流形点", rep[core.NONMANIFOLD]["bad_verts"], 0)
    h.eq("标记位 = 悬空线 1 + 孤立点 1（端点不重复标）",
         len(rep[core.NONMANIFOLD]["positions"]), 2)

    rep = _analyze(_sample("vertex_touch"))
    h.eq("仅顶点相连：仍判定为封闭", rep["closed"], True)
    h.eq("仅顶点相连：没有异常边", rep[core.NONMANIFOLD]["count"], 0)
    h.eq("仅顶点相连：检出 1 个非流形点", rep[core.NONMANIFOLD]["bad_verts"], 1)

    rep = _analyze(_sample("triple_edge"))
    h.eq("三个面共用一条边：多面共边 1 条", rep[core.NONMANIFOLD]["multi"], 1)

    h.eq("三个面共用一条边：新增边界边 2 条", rep[core.NONMANIFOLD]["boundary"], 2)
    h.eq("三个面共用一条边：合计 3", rep[core.NONMANIFOLD]["count"], 3)

    rep = _analyze(_sample("hole"), opts={"check_nonmanifold": False})
    h.eq("关掉开关后不检测", rep[core.NONMANIFOLD]["count"], 0)

def _test_overlap(h):
    h.title("③ 重叠面")

    rep = _analyze(_sample("clean"))
    h.eq("干净立方体：重叠 0", rep[core.OVERLAP]["count"], 0)

    rep = _analyze(_sample("duplicate_face"))
    h.eq("原位复制一个面：1 组", rep[core.OVERLAP]["groups"], 1)
    h.eq("原位复制一个面：2 个面重合", rep[core.OVERLAP]["count"], 2)
    h.eq("原位复制一个面：只给 1 个标记位（同位置不叠标记）",
         len(rep[core.OVERLAP]["positions"]), 1)

    rep = _analyze(_sample("near_duplicate"))
    h.eq("偏移 1e-6，默认容差 1e-4 下算重合", rep[core.OVERLAP]["count"], 2)

    rep = _analyze(_sample("near_duplicate"), opts={"overlap_tolerance": 1e-9})
    h.eq("容差收紧到 1e-9 后不再算重合", rep[core.OVERLAP]["count"], 0)

    rep = _analyze(_sample("duplicate_face"), opts={"check_overlap": False})
    h.eq("关掉开关后不检测", rep[core.OVERLAP]["count"], 0)


    bm = _sample("duplicate_face")
    signature_a = core.face_signature([tuple(v.co) for v in bm.faces[1].verts], 1e-4)
    bm.faces.ensure_lookup_table()
    coords = [tuple(v.co) for v in bm.faces[1].verts]
    signature_b = core.face_signature(list(reversed(coords)), 1e-4)
    signature_c = core.face_signature(coords[1:] + coords[:1], 1e-4)
    bm.free()
    h.check("签名与顶点书写顺序无关", signature_a == signature_c)
    h.check("签名与面绕向无关", signature_a == signature_b)

def _test_limits(h):
    h.title("④ 标记上限 / 空网格")

    rep = _analyze(_sample("hole"), max_markers=2)
    h.eq("上限 2：标记位被截到 2", len(rep[core.NONMANIFOLD]["positions"]), 2)
    h.eq("上限 2：真实计数仍是 4", rep[core.NONMANIFOLD]["count"], 4)
    h.eq("上限 2：真实标记需求仍是 4", rep[core.NONMANIFOLD]["markers_total"], 4)

    empty = bmesh.new()
    rep = _analyze(empty)
    h.eq("空网格：面数 0", rep["faces"], 0)
    h.eq("空网格：不判为封闭", rep["closed"], False)
    h.eq("空网格：反转法线状态 EMPTY", rep[core.FLIP]["status"], core.ST_EMPTY)
    h.eq("空网格：重叠 0", rep[core.OVERLAP]["count"], 0)

    merged = core.merge_reports([
        _analyze(_sample("one_flipped")),
        _analyze(_sample("duplicate_face")),
    ])
    h.eq("合并报告：物体数 2", merged["objects"], 2)
    h.eq("合并报告：反转面合计 1", merged[core.FLIP]["count"], 1)
    h.eq("合并报告：重叠面合计 2", merged[core.OVERLAP]["count"], 2)
    h.ge("合并报告：非流形合计 >= 3", merged[core.NONMANIFOLD]["count"], 3)

def _test_readonly(h):
    h.title("⑤ 只读性（绝不动原始网格）")

    obj = _object_from_bmesh("体检样本A", _sample("one_flipped"))
    before_co = [tuple(vertex.co) for vertex in obj.data.vertices]
    before_polys = len(obj.data.polygons)
    before_edges = len(obj.data.edges)
    before_meshes = len(bpy.data.meshes)

    _select([obj])
    status, message = ops.op_run_check(bpy.context)
    h.eq("体检执行成功", status, ops.OK)
    h.check("返回了提示文字", bool(message))

    after_co = [tuple(vertex.co) for vertex in obj.data.vertices]
    h.check("顶点坐标一字未改", before_co == after_co)
    h.eq("面数未变", len(obj.data.polygons), before_polys)
    h.eq("边数未变", len(obj.data.edges), before_edges)

    extra_meshes = len(bpy.data.meshes) - before_meshes
    h.eq("新增网格数据块只来自标记", extra_meshes, markers.marker_object_count())

def _test_markers(h):
    h.title("⑥ 标记生成与清理")

    obj = _object_from_bmesh("体检样本B", _sample("one_flipped"))
    _select([obj])
    status, _message = ops.op_run_check(bpy.context)
    h.eq("体检执行成功", status, ops.OK)

    st = markers.settings(bpy.context)
    h.check("结果已写入设置", bool(st.has_result))
    h.eq("结果：反转法线 1", st.result_flip, 1)
    h.eq("标记物体 1 个（只有反转法线有错）", markers.marker_object_count(), 1)
    h.eq("设置里的标记物体数一致", st.marker_objects, 1)

    coll = markers.marker_collection(create=False)
    h.check("标记集合已建立", coll is not None)
    marker_objs = [o for o in bpy.data.objects if o.get(markers.TAG_OBJECT)]
    h.eq("标记物体都在标记集合里", len(marker_objs),
         len([o for o in coll.objects]) if coll else 0)
    h.check("标记物体会穿透显示", all(o.show_in_front for o in marker_objs))
    h.eq("标记物体有材质", len(marker_objs[0].data.materials), 1)


    user_mesh = bpy.data.meshes.new("用户网格")
    user_obj = bpy.data.objects.new("用户自己的方块", user_mesh)
    bpy.context.scene.collection.objects.link(user_obj)
    user_coll = bpy.data.collections.new("用户集合")
    bpy.context.scene.collection.children.link(user_coll)

    removed = markers.clear_markers()
    h.eq("清理返回被删数量 1", removed, 1)
    h.eq("标记物体清零", markers.marker_object_count(), 0)
    h.check("用户自己的物体还在", user_obj.name in bpy.data.objects)
    h.check("用户自己的网格还在", user_mesh.name in bpy.data.meshes)
    h.check("用户自己的集合还在", user_coll.name in bpy.data.collections)
    h.check("标记集合已删除", markers.marker_collection(create=False) is None)
    h.check("标记材质已删除",
            not any(m.get(markers.TAG_MATERIAL) for m in bpy.data.materials))
    h.check("标记网格已删除",
            not any(m.get(markers.TAG_MESH) for m in bpy.data.meshes))

    status, _message = ops.op_run_check(bpy.context)
    h.eq("重跑体检仍然成功", status, ops.OK)
    h.eq("重跑后标记物体仍是 1", markers.marker_object_count(), 1)

    fresh = [o for o in bpy.data.objects if o.get(markers.TAG_OBJECT)]
    h.eq("标记网格都是立方体岛（8 顶点 / 6 面 / 1 材质）",
         (len(fresh[0].data.vertices), len(fresh[0].data.polygons),
          len(fresh[0].data.materials)),
         (8, 6, 1))

    ops.op_reset_result(bpy.context)
    st = markers.settings(bpy.context)
    h.check("重置后结果标记被清掉", not st.has_result)
    h.eq("重置后标记物体 0", markers.marker_object_count(), 0)

def _test_edge_cases(h):
    h.title("⑦ 边界条件")

    _deselect_all()
    status, message = ops.op_run_check(bpy.context)
    h.eq("没有任何选中/激活物体：返回 CANCELLED", status, ops.NO)
    h.check("给出了可读的提示", "选中" in message)

    camera = bpy.data.objects.new("测试相机", bpy.data.cameras.new("测试相机"))
    bpy.context.scene.collection.objects.link(camera)
    _select([camera])
    status, _message = ops.op_run_check(bpy.context)
    h.eq("只选了非网格物体：返回 CANCELLED", status, ops.NO)

    h.eq("板块切换：未知段落返回 CANCELLED",
         ops.op_set_section(bpy.context, "不存在的段落")[0], ops.NO)

    st = markers.settings(bpy.context)
    before = bool(st.sec_check)
    ops.op_set_section(bpy.context, "check")
    h.eq("板块切换：check 段取反", bool(st.sec_check), not before)
    ops.op_set_section(bpy.context, "check")
    h.eq("板块切换：再切一次切回来", bool(st.sec_check), before)

def _test_registration(h):
    h.title("⑧ 注册 / 注销")

    package = sys.modules[__package__.split(".")[0]]

    short = "meshcheck_"

    h.check("算子 run 已注册", _operator_registered(short + "run"))
    h.check("算子 clear 已注册", _operator_registered(short + "clear"))
    h.check("算子 toggle 已注册", _operator_registered(short + "toggle"))
    h.check("面板已注册", hasattr(bpy.types, ui.MF_PT_MeshCheck.bl_idname))
    h.check("场景属性已挂载", hasattr(bpy.context.scene, core.SCENE_PROP))
    h.check("设置组可访问", markers.settings(bpy.context) is not None)

    package.unregister()
    h.check("注销后算子消失", not _operator_registered(short + "run"))
    h.check("注销后 toggle 也消失", not _operator_registered(short + "toggle"))
    h.check("注销后面板消失", not hasattr(bpy.types, ui.MF_PT_MeshCheck.bl_idname))
    h.check("注销后场景属性消失", not hasattr(bpy.context.scene, core.SCENE_PROP))

    package.register()
    h.check("重新注册后算子回来", _operator_registered(short + "run"))
    h.check("重新注册后面板回来", hasattr(bpy.types, ui.MF_PT_MeshCheck.bl_idname))
    h.check("重新注册后场景属性回来", hasattr(bpy.context.scene, core.SCENE_PROP))

def _test_static_hygiene(h):
    h.title("⑨ 面板静态体检（防一片空白）")

    rna = set(markers.MF_PG_MeshCheckSettings.bl_rna.properties.keys())

    referenced = set(markers.SECTION_PROPS.values())
    for module in (ui, ops):
        source = inspect.getsource(module)
        referenced |= set(re.findall(r'\.prop\(\s*st\s*,\s*"([A-Za-z0-9_]+)"', source))
        referenced |= set(re.findall(r'getattr\(\s*st\s*,\s*"([A-Za-z0-9_]+)"', source))
        referenced |= set(re.findall(r'\bst\.([A-Za-z_][A-Za-z0-9_]*)', source))

    missing = sorted(name for name in referenced if name not in rna)
    h.check("面板/算子里引用的设置项都存在", not missing, "缺少 %s" % missing)

    icons = {
        item.identifier
        for item in bpy.types.UILayout.bl_rna.functions["label"]
        .parameters["icon"].enum_items
    }
    used_icons = {ui.ICON_OPEN, ui.ICON_CLOSED}
    for module in (ui, ops, markers):
        used_icons |= set(re.findall(r'icon\s*=\s*"([A-Za-z0-9_]+)"', inspect.getsource(module)))
    bad_icons = sorted(name for name in used_icons if name not in icons)
    h.check("用到的图标名都存在", not bad_icons, "无效图标 %s" % bad_icons)

    h.check("检测项开关齐全",
            {"check_flip", "check_nonmanifold", "check_overlap"} <= rna)
    h.check("结果字段齐全",
            {"has_result", "result_flip", "result_nonmanifold", "result_overlap"} <= rna)

def _test_end_to_end(h):
    h.title("⑩ 端到端：多物体 + 三类错误")

    obj_a = _object_from_bmesh("端到端A", _sample("one_flipped"))
    obj_b = _object_from_bmesh("端到端B", _sample("duplicate_face"))

    _select([obj_a, obj_b])
    status, message = ops.op_run_check(bpy.context)
    h.eq("体检执行成功", status, ops.OK)

    st = markers.settings(bpy.context)
    h.eq("统计到 2 个物体", st.result_objects, 2)
    h.eq("反转法线合计 1", st.result_flip, 1)
    h.ge("非流形边至少 3（重复面的三条边）", st.result_nonmanifold, 3)
    h.eq("重叠面合计 2", st.result_overlap, 2)
    h.check("非流形明细有悬空/边界/多面共边的说明", bool(st.note_nonmanifold))
    h.check("摘要文字非空", bool(st.result_text))

    h.eq("建了 3 个标记物体（三类错误各一）", markers.marker_object_count(), 3)
    h.eq("设置里的标记物体数一致", st.marker_objects, 3)
    h.check("状态栏文案包含三类计数", "反转法线" in message and "重叠面" in message)

    ops.op_reset_result(bpy.context)

def _test_operator_paths(h):
    h.title("⑪ 算子的两条调用路径")

    obj = _object_from_bmesh("路径样本", _sample("one_flipped"))
    _select([obj])
    st = markers.settings(bpy.context)


    bpy.ops.mf.meshcheck_run(show_popup=False)
    h.eq("EXEC 路径确实执行了（反转法线 1）", st.result_flip, 1)
    h.check("EXEC 路径写了提示文字", bool(st.result_text))

    ops.op_reset_result(bpy.context)
    h.check("重置后结果被清空", not st.has_result)


    try:
        bpy.ops.mf.meshcheck_run("INVOKE_DEFAULT", show_popup=False)
        invoked = True
    except Exception as error:
        invoked = False
        h.lines.append("       invoke 调用异常：%s" % error)
    h.check("INVOKE 路径可调用（无头下自动退回不弹窗）", invoked)
    h.eq("INVOKE 路径同样得到反转法线 1", st.result_flip, 1)


    bpy.ops.mf.meshcheck_clear()
    h.eq("清除算子把标记删干净", markers.marker_object_count(), 0)
    h.check("清除算子重置了结果", not st.has_result)


    _deselect_all()
    try:
        bpy.ops.mf.meshcheck_run(show_popup=False)
        raised = ""
    except RuntimeError as error:
        raised = str(error)
    h.check("无目标时算子报错而不是静默通过", "选中" in raised, "实际：%r" % raised)

def _test_marker_sizing(h):
    h.title("⑫ 标记尺寸随物体大小自适应")

    small = _object_from_bmesh("小模型", _sample("one_flipped", size=1.0))
    big = _object_from_bmesh("大模型", _sample("one_flipped", size=4.0))
    big.location = (10.0, 0.0, 0.0)

    _select([small, big])
    status, _message = ops.op_run_check(bpy.context)
    h.eq("体检执行成功", status, ops.OK)
    h.eq("两个物体各 1 个反转面 → 反转法线共 2", markers.settings(bpy.context).result_flip, 2)

    flip_objects = [o for o in bpy.data.objects
                    if o.get(markers.TAG_OBJECT) == core.FLIP]
    h.eq("反转法线只有 1 个标记物体", len(flip_objects), 1)

    mesh = flip_objects[0].data
    h.eq("标记网格里是 2 个立方体岛（16 顶点）", len(mesh.vertices), 16)
    sizes = []
    for start in range(0, 16, 8):
        xs = [mesh.vertices[start + i].co.x for i in range(8)]
        sizes.append(round(max(xs) - min(xs), 6))
    h.eq("两个方块尺寸不同", len(set(sizes)), 2)
    h.check("尺寸比约等于物体尺寸比 4:1",
            min(sizes) > 0 and 3.5 < (max(sizes) / min(sizes)) < 4.5,
            "得到 %s" % sizes)

    ops.op_reset_result(bpy.context)

class _FakeOperator:
    def __init__(self):
        self.section = None
        self.show_popup = None
        self.text = ""

class _FakeLayout:


    def __init__(self, log):
        self._log = log
        self.alignment = None
        self.scale_y = 1.0

    def row(self, **kwargs):
        self._log.append(("row", kwargs))
        return _FakeLayout(self._log)

    def column(self, **kwargs):
        self._log.append(("column", kwargs))
        return _FakeLayout(self._log)

    def box(self):
        self._log.append(("box", {}))
        return _FakeLayout(self._log)

    def separator(self):
        self._log.append(("separator", {}))

    def label(self, **kwargs):
        self._log.append(("label", kwargs))

    def prop(self, data, name, **kwargs):
        self._log.append(("prop", {"name": name, **kwargs}))

    def operator(self, idname, **kwargs):
        self._log.append(("operator", {"idname": idname, **kwargs}))
        return _FakeOperator()

class _FakePanel:
    def __init__(self, layout, owner=None):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        owner = self.__dict__.get("_owner")
        if owner is None:
            raise AttributeError(name)
        return getattr(owner, name).__get__(self, type(self))

def _operator_registered(short_name):


    try:
        getattr(bpy.ops.mf, short_name).get_rna_type()
        return True
    except Exception:
        return False

def _test_panel_draw(h):
    h.title("⑬ 面板 draw() 真跑一遍")

    log = []
    panel = _FakePanel(_FakeLayout(log), ui.MF_PT_MeshCheck)

    st = markers.settings(bpy.context)
    try:
        ui.MF_PT_MeshCheck.draw(panel, bpy.context)
        h.check("面板 draw() 无异常（未选/无结果状态）", True)
    except Exception as error:
        h.check("面板 draw() 无异常（未选/无结果状态）", False, repr(error))


    obj = _object_from_bmesh("面板样本", _sample("one_flipped"))
    _select([obj])
    ops.op_run_check(bpy.context)
    log.clear()
    try:
        ui.MF_PT_MeshCheck.draw(panel, bpy.context)
        h.check("面板 draw() 无异常（有结果状态）", True)
    except Exception as error:
        h.check("面板 draw() 无异常（有结果状态）", False, repr(error))

    icons = {
        item.identifier
        for item in bpy.types.UILayout.bl_rna.functions["label"]
        .parameters["icon"].enum_items
    }
    bad = sorted({
        entry[1]["icon"] for entry in log
        if entry[0] in ("label", "operator") and entry[1].get("icon") not in (None, "")
        and entry[1]["icon"] not in icons
    })
    h.check("draw 里用到的图标都真实存在", not bad, "无效：%s" % bad)

    used_ops = {entry[1]["idname"] for entry in log if entry[0] == "operator"}
    unregistered = sorted(
        name for name in used_ops
        if not _operator_registered(name.split(".", 1)[-1])
    )
    h.check("draw 里调用的算子都已注册", not unregistered,
            "未注册：%s" % unregistered)
    h.check("主按钮确实画出来了", any(e[1].get("text") == "模型体检" for e in log if e[0] == "operator"))


    st.sec_check = False
    collapsed = []
    try:
        ui.MF_PT_MeshCheck.draw(
            _FakePanel(_FakeLayout(collapsed), ui.MF_PT_MeshCheck), bpy.context)
        h.check("面板 draw() 无异常（① 检测项目折叠状态）", True)
    except Exception as error:
        h.check("面板 draw() 无异常（① 检测项目折叠状态）", False, repr(error))
    h.check("折叠 ① 后不画检测项开关",
            not any(e[0] == "prop" and e[1].get("name") == "check_flip" for e in collapsed))
    st.sec_check = True


    popup_log = []
    try:
        ops.MF_OT_MeshCheck_Run.draw(_FakePanel(_FakeLayout(popup_log)), bpy.context)
        h.check("结果弹窗 draw() 无异常", True)
    except Exception as error:
        h.check("结果弹窗 draw() 无异常", False, repr(error))
    h.check("弹窗里画出了三类结果",
            len([e for e in popup_log if e[0] == "prop"]) == 3,
            "实际 %d 个色块" % len([e for e in popup_log if e[0] == "prop"]))

    ops.op_reset_result(bpy.context)

def run():
    h = Harness()
    h.lines.append("=" * 58)
    h.lines.append("模型体检 无头自检")
    h.lines.append("Blender %s   后台模式：%s" % (bpy.app.version_string, bpy.app.background))
    h.lines.append("=" * 58)

    _wipe_scene()

    groups = (
        _test_flip,
        _test_nonmanifold,
        _test_overlap,
        _test_limits,
        _test_readonly,
        _test_markers,
        _test_edge_cases,
        _test_registration,
        _test_static_hygiene,
        _test_end_to_end,
        _test_operator_paths,
        _test_marker_sizing,
        _test_panel_draw,
    )
    for group in groups:
        try:
            group(h)
        except Exception as error:
            import traceback
            h.failed += 1
            h.lines.append("  FAIL  %s 抛出异常：%s" % (group.__name__, error))
            h.lines.append(indent(traceback.format_exc()))


    try:
        markers.clear_markers()
    except Exception:
        pass
    _wipe_scene()

    h.lines.append("")
    h.lines.append("=" * 58)
    h.lines.append("结果：通过 %d 项，失败 %d 项 %s"
                   % (h.passed, h.failed, "—— 全部通过" if not h.failed else "—— 有失败"))
    h.lines.append("=" * 58)
    return h.passed, h.failed, h.lines

def indent(text, prefix="        "):
    return "\n".join(prefix + line for line in text.rstrip().splitlines())

def main():
    passed, failed, lines = run()
    for line in lines:
        print(line)
    return passed, failed

if __name__ == "__main__":
    main()
