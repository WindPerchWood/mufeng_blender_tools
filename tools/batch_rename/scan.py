import os
import re

import bpy

from . import naming

R_LINKED = "来自链接库，只读，改不了名"
R_VIEWER = "Blender 内置预览图（Render Result / Viewer Node）"
R_GENERATED = "程序生成图，磁盘上没有文件"
R_PACKED = "已内嵌进 .blend，磁盘文件不受本工具管理"
R_TILED = "UDIM 拼贴图，涉及多张文件，本版不改磁盘"
R_NOFILE = "数据块没有磁盘路径"
R_MISSING = "磁盘文件已不存在"
R_UNSAVED = "工程尚未存盘，// 相对路径解析不了，不碰磁盘"
R_SEQ_EMPTY = "序列图在磁盘上找不到任何帧"

SCOPE_SELECTED = "SELECTED"
SCOPE_ALL = "ALL"

class Entry(object):

    __slots__ = ("kind", "id", "label", "writable", "skip", "skip_disk",
                 "file_abs", "seq_frames")

    def __init__(self, kind, idb, label):
        self.kind = kind
        self.id = idb
        self.label = label
        self.writable = True
        self.skip = ""
        self.skip_disk = ""
        self.file_abs = None
        self.seq_frames = None

    @property
    def kind_label(self):
        return naming.KIND_LABELS.get(self.kind, self.kind)

    @property
    def has_disk(self):
        return bool(self.file_abs or self.seq_frames)

def _lib_ok(idb):
    return getattr(idb, "library", None) is None

def _selected_objects(context):
    out = []
    for o in context.view_layer.objects:
        if o is None:
            continue
        try:
            if o.select_get():
                out.append(o)
        except Exception:
            pass
    return out

def _scene_objects(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return []
    return [o for o in scene.objects if o is not None]

def _materials_of(objs):
    mats = []
    seen = set()

    def _add(m):
        if m is None:
            return
        key = m.as_pointer() if hasattr(m, "as_pointer") else id(m)
        if key in seen:
            return
        seen.add(key)
        mats.append(m)

    for o in objs:
        for slot in getattr(o, "material_slots", ()) or ():
            if slot is not None:
                _add(slot.material)
        data = getattr(o, "data", None)
        for m in getattr(data, "materials", None) or ():
            _add(m)
    return mats

def _images_of(mats):
    imgs = []
    seen = set()
    for m in mats:
        if not getattr(m, "use_nodes", False):
            continue
        tree = getattr(m, "node_tree", None)
        if tree is None:
            continue
        for node in tree.nodes:
            img = getattr(node, "image", None)
            if img is None:
                continue
            key = img.as_pointer() if hasattr(img, "as_pointer") else id(img)
            if key in seen:
                continue
            seen.add(key)
            imgs.append(img)
    return imgs

def find_sequence_frames(abs_pattern):
    if not abs_pattern:
        return []
    folder = os.path.dirname(abs_pattern)
    base = os.path.basename(abs_pattern)
    m = re.search(r"(#+)", base)
    if m:
        pre, post = base[:m.start()], base[m.end():]
        width = len(m.group(1))
        rx = re.compile(r"^" + re.escape(pre) + r"(\d{%d,})" % width + re.escape(post) + r"$",
                        re.IGNORECASE)
    else:
        rx = re.compile(r"^" + re.escape(base) + r"$", re.IGNORECASE)

    try:
        names = os.listdir(folder)
    except OSError:
        return []

    out = []
    for nm in names:
        mm = rx.match(nm)
        if not mm:
            continue
        digits = mm.group(1) if mm.groups() else ""
        out.append((int(digits) if digits else 0, os.path.join(folder, nm), digits))
    out.sort(key=lambda t: t[0])
    return out

def _scan_image_disk(entry, img):
    if img.source == "VIEWER":
        entry.writable = False
        entry.skip = R_VIEWER
        entry.skip_disk = R_VIEWER
        return

    if not _lib_ok(img):
        entry.writable = False
        entry.skip = R_LINKED
        entry.skip_disk = R_LINKED
        return

    if img.packed_file is not None:
        entry.skip_disk = R_PACKED
        return

    if img.source == "GENERATED":
        entry.skip_disk = R_GENERATED
        return

    if img.source == "TILED":
        entry.skip_disk = R_TILED
        return

    raw = img.filepath or ""
    if not raw:
        entry.skip_disk = R_NOFILE
        return

    abs_path = bpy.path.abspath(raw)
    if not os.path.isabs(abs_path):
        entry.skip_disk = R_UNSAVED
        return

    if img.source == "SEQUENCE":
        if not re.search(r"#+", os.path.basename(abs_path)):
            if os.path.exists(abs_path):
                entry.file_abs = abs_path
            else:
                entry.skip_disk = R_MISSING
            return
        frames = find_sequence_frames(abs_path)
        if not frames:
            entry.skip_disk = R_SEQ_EMPTY
            return
        entry.seq_frames = frames
        return

    if not os.path.exists(abs_path):
        entry.skip_disk = R_MISSING
        return
    entry.file_abs = abs_path

def _make_image_entry(img):
    entry = Entry(naming.KIND_IMAGE, img, img.name)
    _scan_image_disk(entry, img)
    if entry.file_abs:
        entry.label = os.path.basename(entry.file_abs)
    elif entry.seq_frames:
        entry.label = os.path.basename(bpy.path.abspath(img.filepath))
    return entry

def collect(context, snap):
    entries = []
    notes = []

    selected = None
    if snap.get("scope") == SCOPE_SELECTED:
        selected = _selected_objects(context)

    if snap.get("do_object"):
        pool = selected if selected is not None else _scene_objects(context)
        skipped_cam = skipped_light = 0
        for o in pool:
            if snap.get("skip_cameras") and o.type == "CAMERA":
                skipped_cam += 1
                continue
            if snap.get("skip_lights") and o.type == "LIGHT":
                skipped_light += 1
                continue
            e = Entry(naming.KIND_OBJECT, o, o.name)
            if not _lib_ok(o):
                e.writable = False
                e.skip = R_LINKED
            entries.append(e)
        if skipped_cam:
            notes.append("已按选项跳过 %d 个相机" % skipped_cam)
        if skipped_light:
            notes.append("已按选项跳过 %d 个灯光" % skipped_light)

    if snap.get("do_material"):
        if selected is not None:
            pool = _materials_of(selected)
        else:
            pool = list(bpy.data.materials)
        for m in pool:
            e = Entry(naming.KIND_MATERIAL, m, m.name)
            if not _lib_ok(m):
                e.writable = False
                e.skip = R_LINKED
            entries.append(e)

    if snap.get("do_image"):
        if selected is not None:
            pool = _images_of(_materials_of(selected))
        else:
            pool = list(bpy.data.images)
        for img in pool:
            if img.source == "VIEWER":
                continue
            entries.append(_make_image_entry(img))

    return entries, notes
