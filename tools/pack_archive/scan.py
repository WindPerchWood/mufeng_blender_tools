
import os
import re

import bpy

_plan_mod = None


def _import_plan():
    global _plan_mod
    if _plan_mod is not None:
        return _plan_mod
    try:
        from . import plan as mod
    except (ImportError, ValueError):
        import plan as mod
    _plan_mod = mod
    return mod


def resolve_path(raw):
    if not raw:
        return ""
    text = raw.strip()
    if not text:
        return ""
    try:
        resolved = bpy.path.abspath(text)
    except Exception:
        resolved = text
    if os.path.isabs(resolved):
        return os.path.normpath(resolved)
    return resolved


def _exists(path):
    return bool(path) and os.path.exists(path)


def _iter_node_trees():
    seen = set()
    collections = (
        getattr(bpy.data, "node_groups", ()),
        bpy.data.materials,
        bpy.data.worlds,
        bpy.data.lights,
        bpy.data.scenes,
        getattr(bpy.data, "textures", ()),
    )
    for coll in collections:
        for owner in coll:
            tree = getattr(owner, "node_tree", None)
            if tree is None:
                continue
            key = tree.as_pointer()
            if key in seen:
                continue
            seen.add(key)
            yield tree


def collect_hdri_images():
    result = set()
    for tree in _iter_node_trees():
        for node in getattr(tree, "nodes", ()):
            if getattr(node, "bl_idname", "") != "ShaderNodeTexEnvironment":
                continue
            image = getattr(node, "image", None)
            if image is not None:
                result.add(image.as_pointer())
    return result


_SEQ_TOKEN = re.compile(r"#+")


def expand_sequence(abspath):
    directory = os.path.dirname(abspath)
    pattern = os.path.basename(abspath)
    if not os.path.isdir(directory):
        return []
    match = _SEQ_TOKEN.search(pattern)
    if not match:
        return []
    digits = len(match.group(0))
    regex = re.compile(
        "^"
        + re.escape(pattern[: match.start()])
        + r"(\d{%d})" % digits
        + re.escape(pattern[match.end():])
        + "$"
    )
    hits = []
    try:
        for fn in os.listdir(directory):
            if regex.match(fn):
                hits.append(os.path.join(directory, fn))
    except OSError:
        return []
    return sorted(hits)


def sequence_raw_basename(raw):
    if not raw or not _SEQ_TOKEN.search(raw):
        return ""
    return os.path.basename(raw.replace("\\", "/"))


def _image_records(only_used=True):
    mod = _import_plan()
    hdri_ids = collect_hdri_images()
    records = []
    for image in bpy.data.images:
        try:
            source = image.source
        except Exception:
            continue
        if source in {"GENERATED", "VIEWER"}:
            continue
        if getattr(image, "packed_file", None) is not None:
            continue
        if only_used and not image.users and not image.use_fake_user:
            continue
        raw = image.filepath or ""
        if not raw:
            continue

        ref = {"how": "block", "coll": "images", "name": image.name}
        src = resolve_path(raw)
        if not src:
            continue

        if source == "TILED":
            records.append(
                {
                    "src": src,
                    "raw": raw,
                    "kind": "IMAGE",
                    "subdir": mod.SUBDIR_TEXTURES,
                    "owner": "Image(UDIM):%s" % image.name,
                    "is_dir": True,
                    "name_hint": image.name,
                    "seq_pattern": "",
                    "ref": ref,
                    "missing": not _exists(src),
                }
            )
            continue

        is_hdri = image.as_pointer() in hdri_ids
        kind = "HDRI" if is_hdri else "IMAGE"
        subdir = mod.SUBDIR_HDRI if is_hdri else mod.SUBDIR_TEXTURES

        extras = []
        pattern_base = ""
        if source in {"SEQUENCE", "MOVIE"}:
            pattern_base = sequence_raw_basename(raw)
            if pattern_base:
                frames = expand_sequence(src)
                if frames:
                    src = frames[0]
                    extras = frames[1:]
                else:
                    pattern_base = ""

        records.append(
            {
                "src": src,
                "raw": raw,
                "kind": kind,
                "subdir": subdir,
                "owner": "Image:%s" % image.name,
                "is_dir": False,
                "extra_files": extras,
                "seq_pattern": pattern_base,
                "ref": ref,
                "missing": not _exists(src),
            }
        )
    return records


def _simple_records(coll_name, kind, subdir, label, packable=True, dir_like=False):
    records = []
    collection = getattr(bpy.data, coll_name)
    for block in collection:
        if packable and getattr(block, "packed_file", None) is not None:
            continue
        raw = getattr(block, "filepath", "") or ""
        if not raw:
            continue
        src = resolve_path(raw)
        if not src:
            continue
        records.append(
            {
                "src": src,
                "raw": raw,
                "kind": kind,
                "subdir": subdir,
                "owner": "%s:%s" % (label, block.name),
                "is_dir": bool(dir_like),
                "name_hint": block.name if dir_like else "",
                "seq_pattern": "",
                "ref": {"how": "block", "coll": coll_name, "name": block.name},
                "missing": not _exists(src),
            }
        )
    return records


def _cache_dir_record(src, raw, owner, name_hint, ref):
    mod = _import_plan()
    return {
        "src": src,
        "raw": raw,
        "kind": "CACHE_DIR",
        "subdir": mod.SUBDIR_CACHE,
        "owner": owner,
        "is_dir": True,
        "name_hint": name_hint,
        "seq_pattern": "",
        "ref": ref,
        "missing": False,
        "soft": True,
    }


def _point_cache_records():
    records = []
    seen_cache = set()

    def handle_pointcache(cache, owner, ref):
        if cache is None:
            return
        key = cache.as_pointer()
        if key in seen_cache:
            return
        seen_cache.add(key)
        raw = getattr(cache, "filepath", "") or ""
        if not raw:
            return
        src = resolve_path(raw)
        if not src:
            return
        flagged = bool(getattr(cache, "use_disk_cache", False)
                       or getattr(cache, "use_external", False))
        if not flagged and not os.path.isdir(src):
            return
        records.append(_cache_dir_record(src, raw, owner, "sim_%s" % owner, ref))

    for obj in bpy.data.objects:
        for m in getattr(obj, "modifiers", ()):
            handle_pointcache(
                getattr(m, "point_cache", None),
                "%s.%s" % (obj.name, m.name),
                {"how": "modifier", "obj": obj.name, "mod": m.name, "attr": "point_cache.filepath"},
            )
            domain = getattr(m, "domain_settings", None)
            if domain is not None:
                raw = getattr(domain, "cache_directory", "") or ""
                if raw:
                    src = resolve_path(raw)
                    if src:
                        records.append(
                            _cache_dir_record(
                                src,
                                raw,
                                "Fluid:%s.%s" % (obj.name, m.name),
                                "fluid_%s" % obj.name,
                                {
                                    "how": "modifier",
                                    "obj": obj.name,
                                    "mod": m.name,
                                    "attr": "domain_settings.cache_directory",
                                },
                            )
                        )
            if getattr(m, "type", "") == "NODES":
                raw = getattr(m, "bake_directory", "") or ""
                if raw:
                    src = resolve_path(raw)
                    if src:
                        records.append(
                            _cache_dir_record(
                                src,
                                raw,
                                "GeoNodes:%s.%s" % (obj.name, m.name),
                                "geo_%s" % obj.name,
                                {
                                    "how": "modifier",
                                    "obj": obj.name,
                                    "mod": m.name,
                                    "attr": "bake_directory",
                                },
                            )
                        )
        for ps in getattr(obj, "particle_systems", ()) or ():
            handle_pointcache(
                getattr(ps, "point_cache", None),
                "Particles:%s.%s" % (obj.name, ps.name),
                {"how": "particles", "obj": obj.name, "ps": ps.name, "attr": "point_cache.filepath"},
            )
    return records


def _apply_attr(target, attr, value):
    parts = attr.split(".")
    holder = target
    for part in parts[:-1]:
        holder = getattr(holder, part, None)
        if holder is None:
            return False
    if holder is None or not hasattr(holder, parts[-1]):
        return False
    try:
        setattr(holder, parts[-1], value)
        return True
    except Exception:
        return False


def apply_ref(ref, value, as_dir=False):
    if not ref:
        return False
    if as_dir:
        value = value.rstrip("/\\") + "/"

    how = ref.get("how")
    if how == "block":
        block = getattr(bpy.data, ref["coll"], {}).get(ref["name"])
        if block is None:
            return False
        try:
            block.filepath = value
        except Exception:
            return False
        if ref["coll"] == "images":
            try:
                block.reload()
            except Exception:
                pass
        return True
    if how == "modifier":
        obj = bpy.data.objects.get(ref["obj"])
        if obj is None:
            return False
        mod = obj.modifiers.get(ref["mod"])
        if mod is None:
            return False
        return _apply_attr(mod, ref["attr"], value)
    if how == "particles":
        obj = bpy.data.objects.get(ref["obj"])
        if obj is None:
            return False
        ps = obj.particle_systems.get(ref["ps"])
        if ps is None:
            return False
        return _apply_attr(ps, ref["attr"], value)
    return False


def scan(only_used=True):
    mod = _import_plan()
    records = []
    warnings = []

    def guard(label, fn):
        try:
            found = fn()
        except Exception as exc:
            warnings.append("%s 扫描失败：%r" % (label, exc))
            return
        records.extend(found)

    guard("贴图", lambda: _image_records(only_used))
    guard("字体", lambda: _simple_records("fonts", "FONT", mod.SUBDIR_FONTS, "Font"))
    guard("音频", lambda: _simple_records("sounds", "SOUND", mod.SUBDIR_AUDIO, "Sound"))
    guard(
        "影片剪辑",
        lambda: _simple_records("movieclips", "CLIP", mod.SUBDIR_CLIPS, "MovieClip", packable=False),
    )
    guard("体积", lambda: _simple_records("volumes", "VOLUME", mod.SUBDIR_VOLUMES, "Volume"))
    guard(
        "链接库",
        lambda: _simple_records("libraries", "LIB", mod.SUBDIR_LIB, "Library", packable=False),
    )
    guard(
        "缓存文件",
        lambda: _simple_records(
            "cache_files", "CACHE_FILE", mod.SUBDIR_CACHE, "CacheFile", packable=False
        ),
    )
    guard("模拟缓存", _point_cache_records)

    if any(rec.get("kind") == "LIB" for rec in records):
        warnings.append(
            "检测到链接库（Link 进场景的 .blend）：已收集库文件本身，"
            "但库内部的依赖尚未递归扫描，属于已知限制。"
        )
    return records, warnings


def missing_only(records):
    return [rec for rec in records if rec.get("missing")]
