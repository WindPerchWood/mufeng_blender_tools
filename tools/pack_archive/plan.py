
import hashlib
import os

SUBDIR_TEXTURES = "textures"
SUBDIR_HDRI = "hdri"
SUBDIR_FONTS = "fonts"
SUBDIR_AUDIO = "audio"
SUBDIR_CLIPS = "clips"
SUBDIR_VOLUMES = "volumes"
SUBDIR_CACHE = "cache"
SUBDIR_LIB = "lib"

KIND_SUBDIR = {
    "IMAGE": SUBDIR_TEXTURES,
    "HDRI": SUBDIR_HDRI,
    "FONT": SUBDIR_FONTS,
    "SOUND": SUBDIR_AUDIO,
    "CLIP": SUBDIR_CLIPS,
    "VOLUME": SUBDIR_VOLUMES,
    "CACHE_FILE": SUBDIR_CACHE,
    "CACHE_DIR": SUBDIR_CACHE,
    "LIB": SUBDIR_LIB,
}

MANAGED_SUBDIRS = (
    SUBDIR_TEXTURES,
    SUBDIR_HDRI,
    SUBDIR_FONTS,
    SUBDIR_AUDIO,
    SUBDIR_CLIPS,
    SUBDIR_VOLUMES,
    SUBDIR_CACHE,
    SUBDIR_LIB,
)

_WIN_BAD = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)
}

_HASH_FULL_LIMIT = 32 * 1024 * 1024
_HASH_CHUNK = 1 * 1024 * 1024


def sanitize_filename(name, maxlen=118):
    name = name or ""
    stem, ext = os.path.splitext(name)
    cleaned = []
    for ch in stem:
        cleaned.append("_" if (ch in _WIN_BAD or ord(ch) < 32) else ch)
    stem = "".join(cleaned).strip().rstrip(" .")
    if not stem:
        stem = "unnamed"
    if stem.upper() in _RESERVED:
        stem = stem + "_"
    ext = "".join("_" if (c in _WIN_BAD or ord(c) < 32) else c for c in ext)
    limit = max(8, maxlen - len(ext))
    if len(stem) > limit:
        stem = stem[:limit].rstrip(" .")
    return stem + ext


def sanitize_dirname(name, maxlen=118):
    return sanitize_filename(name, maxlen=maxlen)


def file_digest(path, memo=None):
    key = os.path.normcase(os.path.abspath(path))
    if memo is not None and key in memo:
        return memo[key]
    try:
        size = os.path.getsize(path)
    except OSError:
        digest = "MISSING"
    else:
        h = hashlib.sha1()
        h.update(str(size).encode("ascii"))
        try:
            with open(path, "rb") as handle:
                if size <= _HASH_FULL_LIMIT:
                    for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
                        h.update(block)
                else:
                    h.update(handle.read(_HASH_CHUNK))
                    handle.seek(max(0, size - _HASH_CHUNK))
                    h.update(handle.read(_HASH_CHUNK))
            digest = h.hexdigest()
        except OSError:
            digest = "UNREADABLE:" + key
    if memo is not None:
        memo[key] = digest
    return digest


def _abspath(path):
    return os.path.normcase(os.path.abspath(path))


def _basename_of(src, is_dir):
    cleaned = os.path.normpath(src)
    base = os.path.basename(cleaned) or os.path.basename(os.path.dirname(cleaned))
    return base or "unnamed"


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def _source_size(src, is_dir):
    if is_dir:
        return _dir_size(src)
    try:
        return os.path.getsize(src)
    except OSError:
        return 0


def build_plan(
    records,
    archive_root,
    dedupe=True,
    max_name=118,
):
    entries = []
    taken_names = {}
    by_src = {}
    digests = {}
    missing = []
    skipped = []

    for index, rec in enumerate(records):
        src = (rec.get("src") or "").strip()
        if not src:
            skipped.append({"reason": "空路径", "raw": rec.get("raw", "")})
            continue
        is_dir = bool(rec.get("is_dir"))
        if rec.get("missing") or not os.path.exists(src):
            missing.append({"src": src, "raw": rec.get("raw", ""), "owner": rec.get("owner", "")})
            continue

        src_key = _abspath(src)
        if src_key in by_src:
            entries[by_src[src_key]]["record_ids"].append(index)
            continue

        subdir = rec.get("subdir") or KIND_SUBDIR.get(rec.get("kind"), SUBDIR_TEXTURES)
        if subdir not in MANAGED_SUBDIRS:
            subdir = SUBDIR_TEXTURES

        if is_dir:
            hint = rec.get("name_hint") or rec.get("owner") or ""
            base_name = "%s_%s" % (hint, _basename_of(src, True)) if hint else _basename_of(src, True)
        else:
            base_name = _basename_of(src, False)

        base_name = sanitize_dirname(base_name, max_name) if is_dir else sanitize_filename(
            base_name, max_name
        )

        allow_dedupe = dedupe and not is_dir
        name = base_name
        reuse_index = None
        stem, ext = os.path.splitext(base_name)
        counter = 1
        while True:
            name_key = (subdir, name.lower())
            holder = taken_names.get(name_key)
            if holder is None:
                break
            if allow_dedupe:
                other = entries[holder]
                if file_digest(other["src"], digests) == file_digest(src, digests):
                    reuse_index = holder
                    break
            counter += 1
            if counter > 99999:
                reuse_index = None
                name = "%s_%d%s" % (stem, index, ext)
                break
            name = "%s_%d%s" % (stem, counter, ext)

        if reuse_index is not None:
            entries[reuse_index]["record_ids"].append(index)
            by_src[src_key] = reuse_index
            continue

        dst_rel = "%s/%s" % (subdir, name)

        extra_files = []
        extra_bytes = 0
        if not is_dir:
            for extra in rec.get("extra_files") or ():
                if not extra or not os.path.isfile(extra):
                    continue
                extra_files.append(os.path.abspath(extra))
                try:
                    extra_bytes += os.path.getsize(extra)
                except OSError:
                    pass

        entries.append(
            {
                "src": os.path.abspath(src),
                "dst_rel": dst_rel,
                "dst_abs": os.path.join(archive_root, subdir, name),
                "subdir": subdir,
                "name": name,
                "is_dir": is_dir,
                "extra_files": extra_files,
                "bytes": _source_size(src, is_dir) + extra_bytes,
                "kind": rec.get("kind", "IMAGE"),
                "record_ids": [index],
            }
        )
        taken_names[(subdir, name.lower())] = len(entries) - 1
        by_src[src_key] = len(entries) - 1

    return {"entries": entries, "missing": missing, "skipped": skipped}


def summarize(plan):
    stats = {
        "files": 0,
        "dirs": 0,
        "bytes": 0,
        "by_subdir": {},
        "missing": len(plan.get("missing", [])),
        "skipped": len(plan.get("skipped", [])),
        "deduped": 0,
    }
    for entry in plan.get("entries", []):
        if entry["is_dir"]:
            stats["dirs"] += 1
        else:
            stats["files"] += 1 + len(entry.get("extra_files") or ())
        stats["bytes"] += entry["bytes"]
        stats["by_subdir"][entry["subdir"]] = stats["by_subdir"].get(entry["subdir"], 0) + 1
        extra = len(entry["record_ids"]) - 1
        if extra > 0:
            stats["deduped"] += extra
    return stats
