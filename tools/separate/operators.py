import time

import bmesh
import bpy
from bpy.props import EnumProperty, PointerProperty


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

TOOL_ID = "Separate"
OP_ID = "mf.separate_do"
WM_ATTR = "mf_separate"

MODE_ELEMENT = "ELEMENT"
MODE_MATERIAL = "MATERIAL"

MODE_ITEMS = (
    (MODE_ELEMENT, "按元素分离",
     "把每个独立元素（共享边连通的面）拆成单独物体，命名 原名_MF1、_MF2…"),
    (MODE_MATERIAL, "按ID分离",
     "按面的材质ID（材质槽序号，从 1 开始）拆开，命名 原名_ID1、_ID2…"),
)


MAX_PIECES = 5000


def selected_mesh_objects(context):
    try:
        return [o for o in context.selected_objects if o.type == 'MESH']
    except Exception:
        return []


def face_groups_by_element(bm):
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    groups = []
    for face in bm.faces:
        if seen[face.index]:
            continue
        seen[face.index] = True
        stack = [face]
        group = []
        while stack:
            cur = stack.pop()
            group.append(cur.index)
            for edge in cur.edges:
                for nbr in edge.link_faces:
                    if not seen[nbr.index]:
                        seen[nbr.index] = True
                        stack.append(nbr)
        group.sort()
        groups.append(group)
    return groups


def face_groups_by_material(bm):
    bm.faces.ensure_lookup_table()
    buckets = {}
    order = []
    for face in bm.faces:
        key = face.material_index
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(face.index)
    return [(key, buckets[key]) for key in order]


def subset_mesh(me, keep):
    new_me = me.copy()
    bm = bmesh.new()
    bm.from_mesh(new_me)
    bm.faces.ensure_lookup_table()
    kill = [f for f in bm.faces if f.index not in keep]
    if kill:

        bmesh.ops.delete(bm, geom=kill, context='FACES')
    bm.to_mesh(new_me)
    bm.free()
    new_me.update()
    return new_me


def split_object(obj, groups, names, coll):
    me = obj.data
    old_me = me

    obj.data = subset_mesh(me, set(groups[0]))
    obj.name = names[0]
    parts = [obj]

    for grp, name in zip(groups[1:], names[1:]):
        new_obj = obj.copy()
        new_obj.data = subset_mesh(me, set(grp))
        new_obj.name = name
        coll.objects.link(new_obj)
        parts.append(new_obj)

    if old_me.users == 0 and not old_me.use_fake_user:
        try:
            bpy.data.meshes.remove(old_me)
        except Exception:
            pass
    return parts


def _select_only(context, objs):
    if not objs:
        return
    try:
        for o in context.selected_objects:
            o.select_set(False)
    except Exception:
        pass
    for o in objs:
        try:
            o.select_set(True)
        except Exception:
            pass
    try:
        context.view_layer.objects.active = objs[0]
    except Exception:
        pass


def _progress_begin(context, total):
    try:
        context.window_manager.progress_begin(0, max(int(total), 1))
    except Exception:
        pass


def _progress_update(context, value):
    try:
        context.window_manager.progress_update(int(value))
    except Exception:
        pass


def _progress_end(context):
    try:
        context.window_manager.progress_end()
    except Exception:
        pass


def plan_object(obj, mode):
    me = obj.data
    if me is None or not me.polygons:
        return [], []

    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        if mode == MODE_MATERIAL:
            pairs = face_groups_by_material(bm)
            groups = [grp for _key, grp in pairs]
            names = [f"{obj.name}_ID{key + 1}" for key, _grp in pairs]
        else:
            groups = face_groups_by_element(bm)
            names = [f"{obj.name}_MF{i + 1}" for i in range(len(groups))]
    finally:
        bm.free()

    if len(groups) > MAX_PIECES:
        return None, len(groups)
    return groups, names


class MF_PG_SeparateSettings(bpy.types.PropertyGroup):
    mode: EnumProperty(
        name="分离方式",
        description="按元素分离 = 每个独立元素一份；按ID分离 = 每个材质ID一份",
        items=MODE_ITEMS,
        default=MODE_ELEMENT,
    )


class MF_OT_Separate_Do(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "分离物体"
    bl_description = "把选中物体按「独立元素」或「材质ID」拆成多个物体"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="分离方式", items=MODE_ITEMS, default=MODE_ELEMENT)

    def execute(self, context):
        targets = selected_mesh_objects(context)
        if not targets:
            self.report({'WARNING'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        jobs = []
        skipped = 0
        too_many = 0
        for obj in targets:
            groups, names = plan_object(obj, self.mode)
            if groups is None:
                too_many += 1
                utils.report("ERROR",
                             f"{obj.name} 会被拆成 {names} 份，超过上限 {MAX_PIECES}，已跳过")
                continue
            if len(groups) <= 1:

                skipped += 1
                continue
            jobs.append((obj, groups, names))

        if not jobs:
            if too_many:
                self.report({'ERROR'},
                            f"有 {too_many} 个物体拆出来的份数超过上限 {MAX_PIECES}，未处理")
            else:
                self.report({'WARNING'},
                            "选中的物体都是单一元素（或单一材质ID），没有可分离的内容")
            return {'CANCELLED'}

        non_mesh = max(len(context.selected_objects) - len(targets), 0)
        start = time.perf_counter()
        made = []
        total = sum(len(groups) for _o, groups, _n in jobs)
        _progress_begin(context, total)
        done = 0
        try:
            for obj, groups, names in jobs:
                coll = obj.users_collection[0] if obj.users_collection else context.scene.collection
                parts = split_object(obj, groups, names, coll)
                made.extend(parts)
                done += len(parts)
                _progress_update(context, done)
        finally:
            _progress_end(context)

        _select_only(context, made)

        cost = time.perf_counter() - start
        notes = []
        if skipped:
            notes.append(f"跳过 {skipped} 个单元素/单ID物体")
        if non_mesh:
            notes.append(f"忽略 {non_mesh} 个非网格物体")
        note = ("，" + "，".join(notes)) if notes else ""
        utils.report("INFO", f"物体分离（{'按ID' if self.mode == MODE_MATERIAL else '按元素'}）"
                             f"{len(jobs)} 个物体 -> {len(made)} 个，耗时 {cost:.2f} 秒")
        self.report({'INFO'}, f"已分离出 {len(made)} 个物体（{cost:.1f} 秒）{note}")
        return {'FINISHED'}


classes = (MF_PG_SeparateSettings, MF_OT_Separate_Do)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR, PointerProperty(type=MF_PG_SeparateSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
