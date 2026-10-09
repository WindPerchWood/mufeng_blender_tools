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
        PANEL_CATEGORY="MF Toolbox",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[MF Toolbox] {level}: {msg}"),
    )

TOOL_ID = "ObjectGroup"

JOIN_ID = f"mf.{TOOL_ID.lower()}_join"
MAKE_ID = f"mf.{TOOL_ID.lower()}_make"
DISSOLVE_ID = f"mf.{TOOL_ID.lower()}_dissolve"


JOINABLE = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META',
            'ARMATURE', 'LATTICE', 'POINTCLOUD'}


def _unique_collection_name(base):
    base = base or "组"
    name = base
    idx = 0
    while bpy.data.collections.get(name):
        idx += 1
        name = f"{base}.{idx:03d}"
    return name


def _split_joinable(objs):
    ok, bad = [], []
    for obj in objs:
        if obj.type == 'EMPTY' or obj.data is None:
            bad.append(f"{obj.name}(无数据)")
        elif obj.type not in JOINABLE:
            bad.append(f"{obj.name}({obj.type})")
        elif obj.library is not None:
            bad.append(f"{obj.name}(链接库数据)")
        else:
            ok.append(obj)
    return ok, bad


def _force_object_mode(context):
    active = context.view_layer.objects.active
    if active is not None and active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _first_parent(coll):
    for candidate in bpy.data.collections:
        if coll.name in candidate.children:
            return candidate
    return None


def _walk(coll, out):
    out.append(coll)
    for child in coll.children:
        _walk(child, out)


class MF_OT_ObjectGroup_Join(bpy.types.Operator):
    bl_idname = JOIN_ID
    bl_label = "合并成一个对象"
    bl_description = "把选中的多个对象合并为活动对象（等价 Ctrl+J）"
    bl_options = {'REGISTER', 'UNDO'}

    SET_ORIGIN_CENTER = True

    def execute(self, context):
        selected = list(context.selected_objects)
        if len(selected) < 2:
            self.report({'WARNING'}, "至少选中 2 个对象")
            return {'CANCELLED'}

        _force_object_mode(context)

        targets, skipped = _split_joinable(selected)
        if len(targets) < 2:
            self.report({'WARNING'}, f"可合并对象不足 2 个（跳过: {', '.join(skipped)}）")
            return {'CANCELLED'}

        active = context.view_layer.objects.active
        base_obj = active if (active is not None and active in targets) else targets[0]

        bpy.ops.object.select_all(action='DESELECT')
        for obj in targets:
            obj.select_set(True)
        context.view_layer.objects.active = base_obj

        try:
            bpy.ops.object.join()
        except Exception as exc:
            self.report({'ERROR'}, f"合并失败: {exc}")
            return {'CANCELLED'}

        result = context.view_layer.objects.active
        if MF_OT_ObjectGroup_Join.SET_ORIGIN_CENTER and result is not None:
            bpy.ops.object.select_all(action='DESELECT')
            result.select_set(True)
            context.view_layer.objects.active = result
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')

        name = result.name if result is not None else "(未知)"
        utils.report("INFO", f"{len(targets)} 个对象已合并为 '{name}'")
        if skipped:
            utils.report("WARNING", "跳过: " + ", ".join(skipped))
        self.report({'INFO'}, f"已合并 {len(targets)} 个对象")
        return {'FINISHED'}


class MF_OT_ObjectGroup_Make(bpy.types.Operator):
    bl_idname = MAKE_ID
    bl_label = "选中对象成集合"
    bl_description = "新建一个集合并把选中对象移进去"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = list(context.selected_objects)
        if not objs:
            self.report({'WARNING'}, "没有选中任何对象")
            return {'CANCELLED'}

        parent = None
        active = context.view_layer.objects.active
        ref = active if active is not None else objs[0]
        cols = list(ref.users_collection)
        if cols:
            parent = cols[0]
        if parent is None:
            parent = context.scene.collection

        new_coll = bpy.data.collections.new(_unique_collection_name(None))
        parent.children.link(new_coll)

        moved = 0
        for obj in objs:
            if obj.name not in new_coll.objects:
                new_coll.objects.link(obj)

            for col in list(obj.users_collection):
                if col is not new_coll:
                    col.objects.unlink(obj)
            moved += 1

        utils.report("INFO", f"{moved} 个对象已移入集合 '{new_coll.name}'（父集合: {parent.name}）")
        self.report({'INFO'}, f"已创建集合 '{new_coll.name}'")
        return {'FINISHED'}


class MF_OT_ObjectGroup_Dissolve(bpy.types.Operator):
    bl_idname = DISSOLVE_ID
    bl_label = "解散集合"
    bl_description = "删除选中对象所在的集合（含所有嵌套子集合），对象提到各自的父集合"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene_root = context.scene.collection
        roots = []

        selected = list(context.selected_objects)
        if selected:
            for obj in selected:
                for col in list(obj.users_collection):
                    if col is scene_root:
                        continue
                    if col not in roots:
                        roots.append(col)
        else:

            roots = [c for c in scene_root.children]

        if not roots:
            self.report({'WARNING'},
                        "没有可解散的集合（选中对象可能直接在场景根集合里）")
            return {'CANCELLED'}

        total_objs = 0
        removed = 0
        notes = []

        for root in roots:
            if root is scene_root:
                continue

            chain = []
            _walk(root, chain)

            dest = _first_parent(root) or scene_root
            if dest in chain:
                dest = scene_root

            names_used = set()
            for col in chain:
                for obj in list(col.objects):
                    if obj.name not in names_used:
                        dest.objects.link(obj)
                        names_used.add(obj.name)
                        total_objs += 1

            for col in reversed(chain):
                try:
                    bpy.data.collections.remove(col)
                    removed += 1
                except Exception as exc:
                    notes.append(f"{col.name}({exc})")

        if removed:
            utils.report("INFO", f"已解散 {removed} 个集合，保留 {total_objs} 个对象")
            self.report({'INFO'}, f"已解散 {removed} 个集合")
        if notes:
            utils.report("WARNING", "未能删除: " + ", ".join(notes))
        if not removed:
            self.report({'WARNING'}, "没有任何集合被解散")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MF_OT_ObjectGroup_Join,
    MF_OT_ObjectGroup_Make,
    MF_OT_ObjectGroup_Dissolve,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
