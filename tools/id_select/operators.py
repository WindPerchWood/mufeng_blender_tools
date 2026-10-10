import re

import bpy
from bpy.props import PointerProperty, StringProperty

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

TOOL_ID = "IdSelect"
OP_SELECT = f"mf.{TOOL_ID.lower()}_select"
STATE_ATTR = f"mf_{TOOL_ID.lower()}"
ID_PROP = "mf_id"
WATERMARK_KEY = "mf_id_watermark"

MAX_RANGE = 5000
FIX_DELAY = 0.05

SPLIT_RE = re.compile(r"[,，;；、\s]+")
RANGE_RE = re.compile(r"^(\d+)\s*[-~]\s*(\d+)$")

HANDLER_NAMES = ("depsgraph_update_post", "load_post", "save_pre")

_STATE = {"pending": False, "count": -1, "busy": False}


def id_of(obj):
    value = obj.get(ID_PROP)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def id_map():
    table = {}
    for obj in bpy.data.objects:
        value = id_of(obj)
        if value is None:
            continue
        table.setdefault(value, []).append(obj)
    return table


def _ordered():
    return sorted(bpy.data.objects, key=lambda obj: getattr(obj, "session_uid", 0))


def watermark():
    values = []
    for scene in bpy.data.scenes:
        value = scene.get(WATERMARK_KEY)
        if isinstance(value, (int, float)):
            values.append(int(value))
    return max(values) if values else 0


def bump_watermark(value):
    for scene in bpy.data.scenes:
        if scene.library is not None:
            continue
        current = scene.get(WATERMARK_KEY)
        if not isinstance(current, (int, float)) or int(current) < value:
            scene[WATERMARK_KEY] = value


def ensure_ids():
    ordered = _ordered()

    owners = {}
    for obj in ordered:
        value = id_of(obj)
        if value is None:
            continue
        owner = owners.get(value)
        if owner is None:
            owners[value] = obj.name
        elif obj.library is None:
            holder = bpy.data.objects.get(owner)
            if holder is not None and holder.library is not None:
                owners[value] = obj.name

    used = set(owners)
    nxt = max(used | {watermark()}) + 1

    assigned = []
    fixed = []
    skipped = []
    for obj in ordered:
        value = id_of(obj)
        if value is not None and owners.get(value) == obj.name:
            continue
        if obj.library is not None:
            skipped.append(obj)
            continue
        while nxt in used:
            nxt += 1
        try:
            obj[ID_PROP] = nxt
        except Exception:
            skipped.append(obj)
            continue
        used.add(nxt)
        if value is None:
            assigned.append((obj, nxt))
        else:
            fixed.append((obj, value, nxt))
        nxt += 1
    if assigned or fixed:
        bump_watermark(nxt - 1)
    return assigned, fixed, skipped


def parse_ids(text):
    ids = []
    bad = []
    source = re.sub(r"[ \t]*([-~])[ \t]*", r"\1", str(text or ""))
    for raw in SPLIT_RE.split(source):
        if not raw:
            continue
        match = RANGE_RE.match(raw)
        if match:
            low, high = int(match.group(1)), int(match.group(2))
            if low > high:
                low, high = high, low
            if high - low > MAX_RANGE:
                bad.append(raw)
                continue
            ids.extend(range(low, high + 1))
            continue
        if raw.isdigit():
            ids.append(int(raw))
            continue
        bad.append(raw)
    return sorted(set(ids)), bad


def _layer_chain(layer_collection, collection, path):
    if layer_collection.collection == collection:
        return path + [layer_collection]
    for child in layer_collection.children:
        found = _layer_chain(child, collection, path + [layer_collection])
        if found is not None:
            return found
    return None


def reveal(obj, view_layer):
    changed = False
    for collection in obj.users_collection:
        chain = _layer_chain(view_layer.layer_collection, collection, [])
        if chain:
            for node in chain:
                if node.exclude:
                    node.exclude = False
                    changed = True
                if node.hide_viewport:
                    node.hide_viewport = False
                    changed = True
        if collection.hide_viewport:
            collection.hide_viewport = False
            changed = True
    if obj.hide_viewport:
        obj.hide_viewport = False
        changed = True
    try:
        if obj.hide_get(view_layer=view_layer):
            obj.hide_set(False, view_layer=view_layer)
            changed = True
    except RuntimeError:
        pass
    return changed


def clear_selection():
    for obj in bpy.data.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            pass


def select_objects(context, objects):
    view_layer = context.view_layer
    revealed = []
    for obj in objects:
        try:
            if reveal(obj, view_layer):
                revealed.append(obj)
        except Exception:
            pass
    if revealed:
        view_layer.update()

    clear_selection()
    selected = []
    blocked = []
    for obj in objects:
        if obj.name not in view_layer.objects:
            blocked.append(obj)
            continue
        try:
            obj.select_set(True)
            selected.append(obj)
        except RuntimeError:
            blocked.append(obj)
    if selected:
        try:
            view_layer.objects.active = selected[0]
        except Exception:
            pass
    return selected, blocked, revealed


def frame_selected(context):
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None)
    if screen is None:
        return False
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        try:
            with context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_selected()
            return True
        except Exception:
            return False
    return False


def _cancel_timer():
    if not _STATE["pending"]:
        return
    _STATE["pending"] = False
    try:
        bpy.app.timers.unregister(_run)
    except Exception:
        pass


def _run():
    _STATE["pending"] = False
    _STATE["busy"] = True
    try:
        ensure_ids()
    except Exception as exc:
        utils.report("WARNING", f"自动写 ID 失败: {exc}")
    finally:
        _STATE["count"] = len(bpy.data.objects)
        _STATE["busy"] = False
    return None


def _schedule():
    if _STATE["pending"]:
        return
    _STATE["pending"] = True
    try:
        bpy.app.timers.register(_run, first_interval=FIX_DELAY)
    except Exception:
        _STATE["pending"] = False
        _run()


def _on_depsgraph(*args):
    if _STATE["busy"]:
        return
    if len(bpy.data.objects) == _STATE["count"]:
        return
    _schedule()


def _on_load(*args):
    _STATE["count"] = -1
    _schedule()


def _on_save(*args):
    if _STATE["busy"]:
        return
    _STATE["busy"] = True
    try:
        ensure_ids()
    except Exception:
        pass
    finally:
        _STATE["busy"] = False


HANDLER_FUNCS = (_on_depsgraph, _on_load, _on_save)


def attach():
    detach()
    for name, func in zip(HANDLER_NAMES, HANDLER_FUNCS):
        holder = getattr(bpy.app.handlers, name)
        if func not in holder:
            holder.append(func)
    _STATE["count"] = -1
    _schedule()


def detach():
    _cancel_timer()
    for name, func in zip(HANDLER_NAMES, HANDLER_FUNCS):
        holder = getattr(bpy.app.handlers, name)
        while func in holder:
            holder.remove(func)


def _state(context):
    return getattr(context.window_manager, STATE_ATTR, None)


class MF_PG_IdSelectState(bpy.types.PropertyGroup):
    ids_input: StringProperty(
        name="ID",
        description="要查询的 ID。支持逗号、空格、换行、分号分隔，也支持区间：1001,1002,1005-1010",
        default="",
    )


class MF_OT_IdSelect_SelectById(bpy.types.Operator):
    bl_idname = OP_SELECT
    bl_label = "按 ID 选择查询"
    bl_description = ("输入 ID 反查并选中物体：支持多 ID 与区间（1001,1002 或 1005-1010）。\n"
                      "命中后自动选中、设为活动物体并缩放到它；被隐藏或藏在折叠集合里的物体"
                      "会自动取消隐藏/展开，跨集合也能选中。\n"
                      "查不到的 ID 与重复 ID 会在结果区列出来，不会静默跳过")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = _state(context)
        text = state.ids_input if state is not None else ""
        ids, bad = parse_ids(text)
        if not ids:
            self.report({'WARNING'}, "请先输入 ID")
            return {'CANCELLED'}

        table = id_map()
        found = []
        missing = []
        duplicated = []
        for value in ids:
            hits = table.get(value)
            if not hits:
                missing.append(value)
                continue
            if len(hits) > 1:
                duplicated.append((value, len(hits)))
            found.extend(hits)

        if not found:
            self.report({'WARNING'}, "输入的 %d 个 ID 都没找到" % len(ids))
            return {'CANCELLED'}

        selected, blocked, revealed = select_objects(context, found)
        framed = frame_selected(context) if selected else False

        head = "命中 %d 个（输入 %d 个 ID）" % (len(selected), len(ids))
        if len(selected) < len(found):
            head += "；%d 个不在当前视图层" % (len(found) - len(selected))
        if missing:
            head += "；未找到 " + ", ".join(str(v) for v in missing[:3])
            if len(missing) > 3:
                head += " 等 %d 个" % len(missing)
        for pair in duplicated:
            head += "；重复 ID %d 命中 %d 个物体" % pair
        if bad:
            head += "；忽略无法解析的输入 " + ", ".join(bad[:3])
        if revealed:
            head += "；取消隐藏 %d 个" % len(revealed)
        if framed:
            head += "；已缩放到物体"

        self.report({'INFO'}, head)
        return {'FINISHED'}


classes = (MF_PG_IdSelectState, MF_OT_IdSelect_SelectById)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, STATE_ATTR):
        delattr(bpy.types.WindowManager, STATE_ATTR)
    setattr(bpy.types.WindowManager, STATE_ATTR,
            PointerProperty(type=MF_PG_IdSelectState))

    attach()


def unregister():
    detach()

    if hasattr(bpy.types.WindowManager, STATE_ATTR):
        delattr(bpy.types.WindowManager, STATE_ATTR)
    utils.unregister_classes(classes)
