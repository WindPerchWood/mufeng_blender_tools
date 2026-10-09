import random

import bpy
from mathutils import Vector

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

from . import props
from .geometry import thickness, height, count_collisions
from .row_fill import make_book, flatten
from .shelf_layout import arrange_on_shelves

TOOL_ID = "BookShelf"

OP_ADD = "mf.bookshelf_add_selected"
OP_REMOVE = "mf.bookshelf_remove_selected"
OP_CLEAR = "mf.bookshelf_clear_books"
OP_PICK_FACES = "mf.bookshelf_pick_faces"
OP_CREATE_SHELF = "mf.bookshelf_create_shelf"
OP_DELETE_ROWS = "mf.bookshelf_delete_rows"
OP_NEW_SEED = "mf.bookshelf_new_seed"

FINISHED = "FINISHED"
CANCELLED = "CANCELLED"


def settings(ctx):
    return ctx.scene.book_shelf


def collect_sources(s):
    srcs = []
    seen = set()
    for it in s.books:
        o = it.ob
        if o is None:
            continue
        if o.name in seen:
            continue
        seen.add(o.name)
        srcs.append(o)
    if not srcs:
        return [], [], 1e-5
    by_h = sorted(srcs, key=height)
    by_t = sorted(srcs, key=thickness)
    avg = sum(thickness(o) for o in srcs) / float(len(srcs))
    tol = max(avg * 0.001, 1e-7)
    return by_h, by_t, tol


def make_rnd(s):
    seed = int(getattr(s, "seed", 0))
    if seed > 0:
        return random.Random(seed)
    return random.Random()


def new_collection(scene, base):
    name = base
    i = 1
    while name in bpy.data.collections:
        i += 1
        name = "%s.%03d" % (base, i)
    col = bpy.data.collections.new(name)
    col["mf_gen"] = 1
    scene.collection.children.link(col)
    return col


def target_objects(ctx, s=None):
    if s is None:
        s = settings(ctx)
    coll = s.edit_collection
    if coll is not None and coll.name in bpy.data.collections:
        names = set(coll.objects.keys())
        picked = [o for o in ctx.scene.objects
                  if o.get("mf_gen") and o.name in names]
        if picked:
            return picked
    return [o for o in ctx.scene.objects if o.get("mf_gen")]


def _reset_edit_props(s):
    props._NO_APPLY = True
    try:
        for name in ("move_offset", "variation"):
            if getattr(s, name) != 0.0:
                setattr(s, name, 0.0)
    finally:
        props._NO_APPLY = False


def _tag_created(objs, dir_vec, rnd):
    grp = 0
    coefs = {}
    d = Vector(dir_vec)
    if d.length_squared < 1e-12:
        d = Vector((0.0, 1.0, 0.0))
    d = d.normalized()
    for o in objs:
        g = int(o.get("mf_grp", -1))
        if g < 0:
            g = grp
        if g not in coefs:
            coefs[g] = rnd.uniform(-1.0, 1.0)
        o["mf_gen"] = 1
        t = o.matrix_world.translation
        o["mf_pos0"] = (t.x, t.y, t.z)
        o["mf_dir"] = (d.x, d.y, d.z)
        o["mf_coef"] = coefs[g]
        o["mf_grp"] = g
        grp = max(grp, g + 1)


class _Progress:

    def __init__(self, ctx):
        self.wm = getattr(ctx, "window_manager", None)
        self.on = False
        if self.wm is not None:
            try:
                self.wm.progress_begin(0, 100)
                self.on = True
            except Exception:
                self.on = False

    def update(self, frac):
        if not self.on:
            return
        try:
            self.wm.progress_update(int(max(0.0, min(100.0, frac * 100.0))))
        except Exception:
            pass

    def end(self):
        if self.on:
            try:
                self.wm.progress_end()
            except Exception:
                pass
        self.on = False


def op_add_selected(ctx):
    s = settings(ctx)
    added = 0
    have = set(it.ob.name for it in s.books if it.ob is not None)
    for o in list(ctx.selected_objects):
        if o is None or o.name in have:
            continue
        it = s.books.add()
        it.ob = o
        have.add(o.name)
        added += 1
    if added == 0:
        return CANCELLED, "没有新的可添加对象（先在 3D 视图里选中书）"
    return FINISHED, "已添加 %d 本，共 %d 本" % (added, len(s.books))


def op_remove_selected(ctx):
    s = settings(ctx)
    sel = {o.name for o in getattr(ctx, "selected_objects", []) if o is not None}
    if not sel:
        return CANCELLED, "先在 3D 视图里选中要移除的书"
    kept = [it.ob for it in s.books
            if it.ob is not None and it.ob.name not in sel]
    removed = len(s.books) - len(kept)
    if removed == 0:
        return CANCELLED, "选中的物体不在书籍库里"
    s.books.clear()
    for ob in kept:
        item = s.books.add()
        item.ob = ob
    return FINISHED, "已移除 %d 本，剩 %d 本" % (removed, len(s.books))


def op_clear_books(ctx):
    s = settings(ctx)
    n = len(s.books)
    s.books.clear()
    if n == 0:
        return CANCELLED, "书籍库已经是空的"
    return FINISHED, "已清空 %d 本" % n


def op_pick_faces(ctx):
    obj = getattr(ctx, "edit_object", None) or ctx.active_object
    if obj is None or obj.type != 'MESH':
        return CANCELLED, "请在编辑模式下选中书架物体上的面"
    try:
        obj.update_from_editmode()
    except Exception:
        pass
    polys = obj.data.polygons
    idx = [p.index for p in polys if p.select]
    if not idx:
        return CANCELLED, "没有选中的面"
    quad = [i for i in idx if len(polys[i].vertices) == 4]
    s = settings(ctx)
    s.shelf_obj = obj
    s.shelf_faces.clear()
    for i in quad:
        it = s.shelf_faces.add()
        it.index = i
    dropped = len(idx) - len(quad)
    if not quad:
        return CANCELLED, "选中的面都不是四边形，层板必须是四边形面"
    if dropped:
        return FINISHED, "已记录 %d 个层板面（忽略 %d 个非四边形面）" % (len(quad), dropped)
    return FINISHED, "已记录 %d 个层板面" % len(quad)


COLLISION_TOL = 1e-3
MAX_COLLISION_ATTEMPTS = 8


def _rnd_for_attempt(s, k):
    base = int(getattr(s, "seed", 0))
    if base > 0:
        return random.Random(base + 7919 * k)
    return random.Random()


def _build_attempt(ctx, s, obj, faces, by_h, by_t, tol, k):
    rnd = _rnd_for_attempt(s, k)
    col = new_collection(ctx.scene, "摆书")

    def make(src, pos=(0.0, 0.0, 0.0)):
        return make_book(src, s.copy_type, col, pos)

    pg = _Progress(ctx)
    try:
        rows = arrange_on_shelves(s, obj, faces, by_h, by_t, rnd, tol, make, pg.update)
    finally:
        pg.end()
    objs = [o for row, _d in rows for o in flatten(row)]
    return col, rows, objs, rnd


def _discard_attempt(col, objs):
    for o in objs:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            pass
    if col is not None:
        try:
            bpy.data.collections.remove(col, do_unlink=True)
        except Exception:
            pass


def op_create_shelf(ctx):
    s = settings(ctx)
    obj = s.shelf_obj
    by_h, by_t, tol = collect_sources(s)
    if not by_h:
        return CANCELLED, "书籍库是空的：先在 3D 视图里选中书，再点「添加选中」"
    if obj is None or obj.type != 'MESH':
        return CANCELLED, "还没有拾取书架物体"
    polys = obj.data.polygons
    faces = [f.index for f in s.shelf_faces if 0 <= f.index < len(polys)]
    if not faces:
        return CANCELLED, "还没有层板面：进编辑模式选中四边形面后点「用选中面作层板」"
    bad = [i for i in faces if len(polys[i].vertices) != 4]
    if bad:
        return CANCELLED, "有 %d 个面不是四边形，请重新选择" % len(bad)

    _reset_edit_props(s)

    attempts = MAX_COLLISION_ATTEMPTS if s.avoid_collision else 1
    best = None
    for k in range(attempts):
        col, rows, objs, rnd = _build_attempt(
            ctx, s, obj, faces, by_h, by_t, tol, k)
        if not objs:
            _discard_attempt(col, objs)
            continue
        _, worst = count_collisions(objs, COLLISION_TOL)
        if best is None or worst < best[0]:
            if best is not None:
                _discard_attempt(best[1], best[3])
            best = (worst, col, rows, objs, rnd, k)
        else:
            _discard_attempt(col, objs)
        if worst <= COLLISION_TOL:
            break

    if best is None:
        return CANCELLED, "一块层板都没生成：检查层板面是否可用、长度是否为 0"

    worst, col, rows, objs, rnd, used = best
    total = 0
    for gi, (row, dvec) in enumerate(rows):
        group = flatten(row)
        for kk, el in enumerate(row):
            members = el.books if hasattr(el, "books") else [el]
            for o in members:
                o["mf_grp"] = gi * 100000 + kk
        _tag_created(group, dvec, rnd)
        total += len(group)
    s.edit_collection = col
    op_apply_edit(ctx)

    msg = "已生成 %d 块层板、共 %d 个对象" % (len(rows), total)
    if used:
        msg += "（第 %d 次尝试避开碰撞）" % (used + 1)
    if worst > COLLISION_TOL:
        msg += "；注意：仍有 %.1f mm 穿透，试了 %d 次没完全避开" % (
            worst * 1000.0, attempts)
    return FINISHED, msg


def op_apply_edit(ctx):
    s = settings(ctx)
    n = 0
    for o in target_objects(ctx, s):
        p0 = o.get("mf_pos0")
        dv = o.get("mf_dir")
        if p0 is None or dv is None:
            continue
        p0 = Vector((p0[0], p0[1], p0[2]))
        d = Vector((dv[0], dv[1], dv[2]))
        if d.length_squared < 1e-12:
            d = Vector((0.0, 1.0, 0.0))
        nd = d.normalized()
        v = float(s.variation) * float(o.get("mf_coef", 0.0))
        m = float(s.move_offset)
        if m > 0.0:
            pos = p0 + nd * (m + v)
        elif m < 0.0:
            pos = p0 + nd * (m - v)
        else:
            pos = p0 + nd * v
        o.matrix_world.translation = pos
        n += 1
    return n


def op_new_seed(ctx):
    s = settings(ctx)
    rnd = make_rnd(s)
    objs = target_objects(ctx, s)
    groups = {}
    n = 0
    for o in objs:
        g = int(o.get("mf_grp", 0))
        if g not in groups:
            groups[g] = rnd.uniform(-1.0, 1.0)
        o["mf_coef"] = groups[g]
        n += 1
    if n == 0:
        return CANCELLED, "作用集合里还没有生成过书"
    op_apply_edit(ctx)
    return FINISHED, "已重掷 %d 个对象的随机系数" % n


def op_delete_rows(ctx):
    n = 0
    for o in [o for o in ctx.scene.objects if o.get("mf_gen")]:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
            n += 1
        except Exception:
            pass
    for c in [c for c in bpy.data.collections if c.get("mf_gen")]:
        try:
            bpy.data.collections.remove(c, do_unlink=True)
        except Exception:
            pass
    if n == 0:
        return CANCELLED, "没有可删除的生成结果"
    return FINISHED, "已删除 %d 个生成的对象" % n


class MF_OT_BookShelf_AddSelected(bpy.types.Operator):
    bl_idname = OP_ADD
    bl_label = "添加选中"
    bl_description = "把当前选中的物体加入书籍库"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        st, msg = op_add_selected(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_RemoveSelected(bpy.types.Operator):
    bl_idname = OP_REMOVE
    bl_label = "移除选中"
    bl_description = "把当前选中的物体从书籍库里移除"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        s = settings(ctx)
        return len(s.books) > 0

    def execute(self, ctx):
        st, msg = op_remove_selected(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_ClearBooks(bpy.types.Operator):
    bl_idname = OP_CLEAR
    bl_label = "清空"
    bl_description = "清空书籍库"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        return len(settings(ctx).books) > 0

    def execute(self, ctx):
        st, msg = op_clear_books(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_PickFaces(bpy.types.Operator):
    bl_idname = OP_PICK_FACES
    bl_label = "用选中面作层板"
    bl_description = "进入编辑模式，选中书架层板的四边形面后点这个"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        return ctx.mode == 'EDIT_MESH' and ctx.active_object is not None

    def execute(self, ctx):
        st, msg = op_pick_faces(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_CreateShelf(bpy.types.Operator):
    bl_idname = OP_CREATE_SHELF
    bl_label = "生成"
    bl_description = "把书籍库里的书随机摆满所有层板"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        s = settings(ctx)
        return len(s.books) > 0 and s.shelf_obj is not None and len(s.shelf_faces) > 0

    def execute(self, ctx):
        st, msg = op_create_shelf(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_DeleteRows(bpy.types.Operator):
    bl_idname = OP_DELETE_ROWS
    bl_label = "删除上步操作"
    bl_description = "删除所有生成的书和自建集合"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        st, msg = op_delete_rows(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


class MF_OT_BookShelf_NewSeed(bpy.types.Operator):
    bl_idname = OP_NEW_SEED
    bl_label = "随机种子"
    bl_description = "重掷随机系数，改变「变化」的分布"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, ctx):
        st, msg = op_new_seed(ctx)
        if msg:
            self.report({'INFO'} if st == FINISHED else {'ERROR'}, msg)
        return {st}


classes = (
    MF_OT_BookShelf_AddSelected,
    MF_OT_BookShelf_RemoveSelected,
    MF_OT_BookShelf_ClearBooks,
    MF_OT_BookShelf_PickFaces,
    MF_OT_BookShelf_CreateShelf,
    MF_OT_BookShelf_DeleteRows,
    MF_OT_BookShelf_NewSeed,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
