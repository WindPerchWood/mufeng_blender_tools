import os
import re
import shutil
import time
import bpy
ST_PENDING = "待处理"
ST_OK = "成功"
ST_FAIL = "失败"
ST_SKIP = "跳过"
STATUS_ORDER = (ST_OK, ST_FAIL, ST_SKIP, ST_PENDING)
NUM_WIDTH = 4
MAX_RECORDS = 4000
GROUPS = (
    ("material", "材质名", "mat_"),
    ("image", "贴图", "map_"),
    ("hdri", "环境贴图", "hdri_"),
    ("cache", "外部缓存", "cache_"),
    ("library", "链接库", "lib_"),
    ("ies", "IES 光域网", "ies_"),
    ("pointcache", "点缓存", "pts_"),
    ("object", "物体名", "obj_"),
)
GROUP_LABEL = {tag: label for tag, label, _p in GROUPS}
GROUP_PREFIX = {tag: pfx for tag, _l, pfx in GROUPS}
GROUP_DESC = {
    "material": "bpy.data.materials 的名字（全部材质数据块）",
    "image": "图片数据块名（bpy.data.images[*].name，同步改引用它的图像纹理节点名）"
             "＋ 磁盘上的图片文件（另存英文名副本，引用指向副本）",
    "hdri": "被 ShaderNodeTexEnvironment 当作环境贴图用的图片",
    "cache": "bpy.data.cache_files 指向的 .abc / .usd 等外部缓存文件",
    "library": "bpy.data.libraries 链接的外部 .blend",
    "ies": "IES 光域网文件（ShaderNodeTexIES）+ 节点名",
    "pointcache": "布料/软体/粒子/动态绘制的 point_cache、流体域缓存目录、"
                  "几何节点烘焙目录",
    "object": "bpy.data.objects 的名字",
}
def illegal_char_count(name):
    if not name:
        return 0
    return sum(1 for ch in name if ord(ch) > 127)
def needs_rename(name):
    return illegal_char_count(name) > 0
def convert_str(text):
    if text is None:
        return ""
    return "".join(ch if ord(ch) <= 127 else "?" for ch in text)
def sanitize(text, replace="_"):
    if not text:
        return ""
    return "".join(ch if ord(ch) <= 127 else replace for ch in text)
def pad_num(num):
    return str(int(num)).zfill(NUM_WIDTH)
def sanitize_prefix(text):
    if not text:
        return ""
    out = []
    for char in text:
        if char in "abcdefghijklmnopqrstuvwxyz0123456789-":
            out.append(char)
        elif char.isascii() and char.isalnum():
            out.append(char.lower())
        else:
            out.append("_")
    collapsed = re.sub(r"_{2,}", "_", "".join(out)).strip("_")
    return collapsed
def build_prefix(blend_stem, tag, short=None):
    fallback = short or (tag + "_")
    stem = sanitize_prefix(blend_stem or "")
    if stem:
        return "%s_%s_" % (stem, tag)
    return fallback
class NumberPool(object):
    def __init__(self, start=1):
        self._next = int(start)
    def take(self, is_taken=None, limit=1000000):
        n = self._next
        guard = 0
        if is_taken is not None:
            while is_taken(n):
                n += 1
                guard += 1
                if guard > limit:
                    break
        self._next = n + 1
        return n
    @property
    def next_value(self):
        return self._next
class Taken(object):
    def __init__(self, items=(), fold_case=True):
        self._fold = fold_case
        self._set = set()
        self.update(items)
    def _key(self, value):
        return value.lower() if self._fold else value
    def add(self, value):
        self._set.add(self._key(value))
    def update(self, items):
        for it in items:
            self.add(it)
    def __contains__(self, value):
        return self._key(value) in self._set
    def __len__(self):
        return len(self._set)
def norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))
def split_ext(path):
    base, ext = os.path.splitext(path)
    return base, ext
_HASH_RE = re.compile(r"(#+)")
def split_sequence_pattern(path):
    folder, base = os.path.split(path)
    match = _HASH_RE.search(base)
    if match is None:
        return None
    return folder, base[:match.start()], len(match.group(1)), base[match.end():]
def find_sequence_frames(path):
    parts = split_sequence_pattern(path)
    if parts is None:
        return []
    folder, head, _hlen, tail = parts
    if not head:
        return []
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return []
    out = []
    for name in names:
        if not name.startswith(head) or not name.endswith(tail):
            continue
        middle = name[len(head): len(name) - len(tail)] if tail else name[len(head):]
        if middle.isdigit():
            out.append((int(middle), os.path.join(folder, name), middle))
    out.sort(key=lambda item: item[0])
    return out
def sequence_frame_width(frames, fallback=4):
    if frames:
        return max(len(digits) for _frame, _path, digits in frames)
    return max(1, int(fallback))
_EXT_RE = re.compile(r"(\.[A-Za-z0-9]{1,6})$")
def split_sequence_tail(tail):
    tail = tail or ""
    match = _EXT_RE.search(tail)
    if match is None:
        return tail, ""
    return tail[:match.start()], match.group(1)
def make_sequence_pattern(folder, new_stem, width, tail):
    return os.path.join(folder or "", new_stem + "#" * max(1, int(width)) + tail)
def sequence_frame_path(pattern, frame):
    parts = split_sequence_pattern(pattern)
    if parts is None:
        return pattern
    folder, head, width, tail = parts
    return os.path.join(folder or "", head + str(int(frame)).zfill(width) + tail)
class Settings(object):
    def __init__(self):
        self.blend_stem = ""
        self.groups = {tag: True for tag, _l, _p in GROUPS}
        self.prefixes = {tag: pfx for tag, _l, pfx in GROUPS}
    def enabled(self, tag):
        return bool(self.groups.get(tag))
    def prefix(self, tag):
        return (self.prefixes.get(tag) or "").strip()
def auto_prefixes(blend_stem):
    return {tag: build_prefix(blend_stem, tag, GROUP_PREFIX[tag])
            for tag, _label, _pfx in GROUPS}
def default_settings(blend_stem=""):
    settings = Settings()
    settings.blend_stem = blend_stem or ""
    return settings
def count_groups(settings):
    return sum(1 for tag, _l, _p in GROUPS if settings.enabled(tag))
def abs_path(path):
    return os.path.normpath(bpy.path.abspath(path))
def write_path(absolute):
    if not bpy.data.filepath:
        return absolute
    try:
        return bpy.path.relpath(absolute)
    except Exception:
        return absolute
def is_linked(datablock):
    try:
        return datablock.library is not None
    except Exception:
        return False
def blend_stem():
    try:
        return os.path.splitext(os.path.basename(bpy.data.filepath or ""))[0]
    except Exception:
        return ""
def copy_file(src, dst):
    if norm_path(src) == norm_path(dst):
        return False, "源与目标相同"
    if os.path.exists(dst):
        return False, "目标已存在"
    folder = os.path.dirname(dst)
    try:
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if not os.path.exists(dst):
        return False, "复制后目标仍不存在"
    return True, ""
class Record(object):
    __slots__ = ("kind", "old", "new", "status", "detail", "run")
    def __init__(self, kind, old, new, status, detail="", run=None):
        self.kind = kind
        self.old = old
        self.new = new
        self.status = status
        self.detail = detail
        self.run = run
    def execute(self):
        if self.run is None:
            return False, self.detail
        try:
            return self.run()
        except Exception as exc:
            return False, "%s: %s" % (type(exc).__name__, exc)
class FilePool(object):
    def __init__(self):
        self._reserved = set()
    def reserve(self, path):
        self._reserved.add(norm_path(path))
    def is_taken(self, path):
        if norm_path(path) in self._reserved:
            return True
        return os.path.exists(path)
class Plan(object):
    def __init__(self, settings):
        self.settings = settings
        self.files = FilePool()
        self.records = []
        self.truncated = False
    def add(self, record):
        if len(self.records) >= MAX_RECORDS:
            self.truncated = True
            return
        self.records.append(record)
    def group(self, tag):
        return self.settings.prefix(tag) or GROUP_PREFIX[tag]
def iter_node_trees():
    seen = set()
    out = []
    def consider(tree):
        if tree is None:
            return
        try:
            pointer = tree.as_pointer()
        except Exception:
            return
        if pointer in seen:
            return
        seen.add(pointer)
        out.append(tree)
    for group in bpy.data.node_groups:
        consider(group)
    for holder_name in ("materials", "worlds", "lights", "textures",
                        "metaballs", "grease_pencils", "line_styles"):
        holder = getattr(bpy.data, holder_name, None)
        if holder is None:
            continue
        for data in holder:
            if getattr(data, "use_nodes", True):
                consider(getattr(data, "node_tree", None))
    for obj in bpy.data.objects:
        inner = getattr(obj, "data", None)
        if inner is not None and getattr(inner, "use_nodes", True):
            consider(getattr(inner, "node_tree", None))
        if getattr(obj, "use_nodes", True):
            consider(getattr(obj, "node_tree", None))
    for scene in bpy.data.scenes:
        consider(getattr(scene, "compositing_node_group", None))
        consider(getattr(scene, "node_tree", None))
        world = getattr(scene, "world", None)
        if world is not None and getattr(world, "use_nodes", True):
            consider(getattr(world, "node_tree", None))
    return out
def collect_nodes(idnames):
    wanted = set(idnames)
    out = []
    for tree in iter_node_trees():
        for node in tree.nodes:
            if node.bl_idname in wanted:
                out.append((tree, node))
    return out
def _image_index():
    env = set()
    node_map = {}
    for _tree, node in collect_nodes(("ShaderNodeTexImage", "ShaderNodeTexEnvironment")):
        image = getattr(node, "image", None)
        if image is None:
            continue
        pointer = image.as_pointer()
        if node.bl_idname == "ShaderNodeTexEnvironment":
            env.add(pointer)
        else:
            node_map.setdefault(pointer, []).append(node)
    return env, node_map
def iter_modifier_caches():
    out = []
    seen = set()
    def push_point_cache(desc, owner, attr, path):
        key = ("pc", id(owner), attr)
        if key in seen:
            return
        seen.add(key)
        out.append((desc, owner, attr, path or ""))
    for obj in bpy.data.objects:
        for mod in getattr(obj, "modifiers", ()):
            cache = getattr(mod, "point_cache", None)
            if cache is not None:
                push_point_cache("%s / %s" % (obj.name, mod.name), cache,
                                 "filepath", getattr(cache, "filepath", ""))
            domain = getattr(mod, "domain_settings", None)
            if domain is not None:
                key = ("fluid", id(domain))
                if key not in seen:
                    seen.add(key)
                    out.append(("%s / 流体域" % obj.name, domain,
                                "cache_directory",
                                getattr(domain, "cache_directory", "") or ""))
            if mod.bl_rna.identifier == "NodesModifier":
                bake = getattr(mod, "bake_directory", "") or ""
                key = ("bake", id(mod))
                if bake and key not in seen:
                    seen.add(key)
                    out.append(("%s / 几何节点烘焙" % obj.name, mod,
                                "bake_directory", bake))
            canvas = getattr(mod, "canvas_settings", None)
            if canvas is not None:
                for surface in getattr(canvas, "canvas_surfaces", ()):
                    cache = getattr(surface, "point_cache", None)
                    if cache is not None:
                        push_point_cache("%s / 动态绘制 %s" % (obj.name, surface.name),
                                         cache, "filepath",
                                         getattr(cache, "filepath", ""))
        for system in getattr(obj, "particle_systems", ()):
            cache = getattr(system, "point_cache", None)
            if cache is not None:
                push_point_cache("%s / 粒子 %s" % (obj.name, system.name), cache,
                                 "filepath", getattr(cache, "filepath", ""))
    return out
def _name_runner(datablock, new_name, extra_nodes=()):
    def _run():
        datablock.name = new_name
        actual = datablock.name
        for node in extra_nodes:
            try:
                if needs_rename(node.name):
                    node.name = actual
            except Exception:
                pass
        if actual != new_name:
            return True, "Blender 自动去重为 %s" % actual
        return True, ""
    return _run
def _copy_then_set(src, dst, apply_new_path, note=""):
    def _run():
        ok, detail = copy_file(src, dst)
        if not ok:
            return False, detail
        try:
            apply_new_path()
        except Exception as exc:
            return False, "文件已复制，但引用未更新：%s: %s" % (type(exc).__name__, exc)
        return True, note
    return _run
def _plan_datablock_renames(plan, tag, datablocks):
    label = GROUP_LABEL[tag]
    prefix = plan.group(tag)
    pool = NumberPool()
    taken = Taken([d.name for d in datablocks])
    for datablock in datablocks:
        old = datablock.name
        if not needs_rename(old):
            continue
        if is_linked(datablock):
            plan.add(Record(label, old, "", ST_SKIP, "来自链接库，只读，无法改名"))
            continue
        num = pool.take(lambda v, _t=taken, _p=prefix: (_p + pad_num(v)) in _t)
        new = prefix + pad_num(num)
        taken.add(new)
        plan.add(Record(label, old, new, ST_PENDING,
                        run=_name_runner(datablock, new)))
def plan_materials(plan):
    items = [m for m in bpy.data.materials
             if m.users != 0]
    _plan_datablock_renames(plan, "material", items)
def plan_objects(plan):
    items = [o for o in bpy.data.objects
             if o.users != 0]
    _plan_datablock_renames(plan, "object", items)
def _plan_image_sequence(plan, label, prefix, image, raw, abs_old, pool):
    parts = split_sequence_pattern(abs_old)
    if parts is None:
        return
    folder, head, hash_len, tail = parts
    tail_stem, tail_ext = split_sequence_tail(tail)
    if not needs_rename(head + tail_stem):
        return
    frames = find_sequence_frames(abs_old)
    if not frames:
        plan.add(Record(label + " · 文件", raw, "", ST_SKIP,
                        "序列图：磁盘上找不到匹配的帧文件"))
        return
    width = sequence_frame_width(frames, hash_len)
    tail_clean = sanitize(tail_stem) + tail_ext
    def _is_taken(value):
        stem = prefix + pad_num(value) + "_"
        for frame, _path, _digits in frames:
            if plan.files.is_taken(os.path.join(
                    folder, stem + str(frame).zfill(width) + tail_clean)):
                return True
        return False
    num = pool.take(_is_taken)
    new_pattern = make_sequence_pattern(
        folder, prefix + pad_num(num) + "_", width, tail_clean)
    plan.files.reserve(new_pattern)
    for frame, _path, _digits in frames:
        plan.files.reserve(sequence_frame_path(new_pattern, frame))
    new_raw = write_path(new_pattern)
    def _run():
        copied = 0
        for frame, path, _digits in frames:
            target = sequence_frame_path(new_pattern, frame)
            ok, detail = copy_file(path, target)
            if not ok:
                return False, "第 %d 帧失败：%s" % (frame, detail)
            copied += 1
        image.filepath = new_raw
        try:
            image.reload()
        except Exception:
            pass
        return True, "序列图，共 %d 帧" % copied
    plan.add(Record(label + " · 文件", raw, new_raw, ST_PENDING, run=_run))
def _plan_image_file(plan, label, prefix, image, pool):
    raw = image.filepath
    if not raw or image.source in ("GENERATED", "VIEWER"):
        return
    if is_linked(image):
        plan.add(Record(label + " · 文件", raw, "", ST_SKIP, "来自链接库，只读，无法改名"))
        return
    if image.source == "TILED" or "<UDIM>" in raw or "<UVTILE>" in raw:
        plan.add(Record(label + " · 文件", raw, "", ST_SKIP, "UDIM 平铺图，请手动处理"))
        return
    abs_old = abs_path(raw)
    if "#" in os.path.basename(abs_old):
        _plan_image_sequence(plan, label, prefix, image, raw, abs_old, pool)
        return
    if not os.path.exists(abs_old):
        detail = "已内嵌，且磁盘文件不存在" if image.packed_file else "磁盘文件不存在"
        plan.add(Record(label + " · 文件", raw, "", ST_SKIP, detail))
        return
    folder = os.path.dirname(abs_old)
    stem, ext = split_ext(os.path.basename(abs_old))
    if not needs_rename(stem):
        return
    num = pool.take(lambda v: plan.files.is_taken(
        os.path.join(folder, prefix + pad_num(v) + ext)))
    new_abs = os.path.join(folder, prefix + pad_num(num) + ext)
    new_raw = write_path(new_abs)
    plan.files.reserve(new_abs)
    def _apply(_image=image, _raw=new_raw):
        _image.filepath = _raw
        try:
            _image.reload()
        except Exception:
            pass
    note = "已内嵌，另存英文名副本" if image.packed_file is not None else ""
    plan.add(Record(label + " · 文件", raw, new_raw, ST_PENDING,
                    run=_copy_then_set(abs_old, new_abs, _apply, note)))
def _plan_image_group(plan, tag):
    label = GROUP_LABEL[tag]
    prefix = plan.group(tag)
    env_ptrs, node_map = _image_index()
    name_pool = NumberPool()
    file_pool = NumberPool()
    taken_names = Taken([i.name for i in bpy.data.images])
    for image in bpy.data.images:
        if image.users == 0:
            continue
        if image.source == "VIEWER":
            continue
        is_env = image.as_pointer() in env_ptrs
        if (tag == "hdri") != is_env:
            continue
        if is_linked(image):
            if needs_rename(image.name):
                plan.add(Record(label + " · 名称", image.name, "", ST_SKIP,
                                "来自链接库，只读，无法改名"))
            _plan_image_file(plan, label, prefix, image, file_pool)
            continue
        if needs_rename(image.name):
            num = name_pool.take(
                lambda v, _t=taken_names, _p=prefix: (_p + pad_num(v)) in _t)
            new = prefix + pad_num(num)
            taken_names.add(new)
            extra_nodes = node_map.get(image.as_pointer(), ())
            plan.add(Record(label + " · 名称", image.name, new, ST_PENDING,
                            run=_name_runner(image, new, extra_nodes)))
        _plan_image_file(plan, label, prefix, image, file_pool)
def plan_ies(plan):
    label = GROUP_LABEL["ies"]
    prefix = plan.group("ies")
    file_pool = NumberPool()
    name_pool = NumberPool()
    taken_names = Taken(n.name for n in bpy.data.node_groups)
    for _tree, node in collect_nodes(("ShaderNodeTexIES",)):
        if _tree is not None and is_linked(_tree):
            plan.add(Record(label, node.name, "", ST_SKIP, "来自链接库，只读，无法改名"))
            continue
        if needs_rename(node.name):
            num = name_pool.take(
                lambda v, _t=taken_names, _p=prefix: (_p + pad_num(v)) in _t)
            new = prefix + pad_num(num)
            taken_names.add(new)
            plan.add(Record(label + " · 名称", node.name, new, ST_PENDING,
                            run=_name_runner(node, new)))
        mode = getattr(node, "mode", "INTERNAL")
        raw = getattr(node, "filepath", "") or ""
        if mode != "EXTERNAL" or not raw:
            plan.add(Record(label + " · 文件", raw or "(内嵌)", "", ST_SKIP,
                            "IES 为内嵌数据，没有磁盘文件可改名"))
            continue
        abs_old = abs_path(raw)
        if not os.path.exists(abs_old):
            plan.add(Record(label + " · 文件", raw, "", ST_SKIP, "磁盘文件不存在"))
            continue
        folder = os.path.dirname(abs_old)
        stem, ext = split_ext(os.path.basename(abs_old))
        if not needs_rename(stem):
            continue
        final_ext = ext or ".ies"
        num = file_pool.take(lambda v: plan.files.is_taken(
            os.path.join(folder, prefix + pad_num(v) + final_ext)))
        new_abs = os.path.join(folder, prefix + pad_num(num) + final_ext)
        new_raw = write_path(new_abs)
        plan.files.reserve(new_abs)
        def _apply(_node=node, _raw=new_raw):
            _node.filepath = _raw
        plan.add(Record(label + " · 文件", raw, new_raw, ST_PENDING,
                        run=_copy_then_set(abs_old, new_abs, _apply)))
def _plan_single_path(plan, label, prefix, pool, raw, owner, attr):
    if not raw:
        return
    if is_linked(owner):
        plan.add(Record(label, raw, "", ST_SKIP, "来自链接库，只读，无法改名"))
        return
    abs_old = abs_path(raw)
    if not os.path.exists(abs_old):
        plan.add(Record(label, raw, "", ST_SKIP, "路径不存在"))
        return
    is_dir = os.path.isdir(abs_old)
    if is_dir:
        plan.add(Record(label + " · 目录", raw, "", ST_SKIP,
                        "缓存目录不处理（整目录体积大，需要时请手动改名）"))
        return
    folder = os.path.dirname(abs_old)
    basename = os.path.basename(abs_old.rstrip("/\\"))
    stem, ext = split_ext(basename)
    if not needs_rename(stem):
        return
    num = pool.take(lambda v: plan.files.is_taken(
        os.path.join(folder, prefix + pad_num(v) + ext)))
    new_abs = os.path.join(folder, prefix + pad_num(num) + ext)
    plan.files.reserve(new_abs)
    new_raw = write_path(new_abs)
    def _apply_file(_owner=owner, _attr=attr, _raw=new_raw):
        setattr(_owner, _attr, _raw)
    plan.add(Record(label, raw, new_raw, ST_PENDING,
                    run=_copy_then_set(abs_old, new_abs, _apply_file)))
def plan_cache_files(plan):
    label = GROUP_LABEL["cache"]
    pool = NumberPool()
    for cache in bpy.data.cache_files:
        if cache.users == 0:
            continue
        _plan_single_path(plan, label, plan.group("cache"), pool,
                          cache.filepath, cache, "filepath")
def plan_libraries(plan):
    label = GROUP_LABEL["library"]
    pool = NumberPool()
    for library in bpy.data.libraries:
        if getattr(library, "packed_file", None) is not None:
            plan.add(Record(label, library.filepath, "", ST_SKIP, "链接库已内嵌"))
            continue
        _plan_single_path(plan, label, plan.group("library"), pool,
                          library.filepath, library, "filepath")
def plan_point_caches(plan):
    label = GROUP_LABEL["pointcache"]
    prefix = plan.group("pointcache")
    pool = NumberPool()
    for desc, owner, attr, path in iter_modifier_caches():
        _plan_single_path(plan, "%s · %s" % (label, desc), prefix, pool,
                          path, owner, attr)
def build_plan(settings):
    plan = Plan(settings)
    if settings.enabled("material"):
        plan_materials(plan)
    if settings.enabled("image"):
        _plan_image_group(plan, "image")
    if settings.enabled("hdri"):
        _plan_image_group(plan, "hdri")
    if settings.enabled("cache"):
        plan_cache_files(plan)
    if settings.enabled("library"):
        plan_libraries(plan)
    if settings.enabled("ies"):
        plan_ies(plan)
    if settings.enabled("pointcache"):
        plan_point_caches(plan)
    if settings.enabled("object"):
        plan_objects(plan)
    return plan
def run_plan(records):
    stats = {status: 0 for status in STATUS_ORDER}
    start = time.time()
    for record in records:
        if record.run is None:
            stats[record.status if record.status in stats else ST_SKIP] += 1
            continue
        ok, detail = record.execute()
        record.status = ST_OK if ok else ST_FAIL
        if detail:
            record.detail = detail
        stats[record.status] += 1
    return stats, time.time() - start
def format_stats(stats, elapsed):
    parts = ["%s %d" % (status, stats[status])
             for status in STATUS_ORDER if stats.get(status)]
    if not parts:
        parts.append("没有需要处理的项")
    return "%s ｜ 用时 %.2f 秒" % ("，".join(parts), elapsed)
