import re

KIND_OBJECT = "object"
KIND_MATERIAL = "material"
KIND_IMAGE = "image"
KINDS = (KIND_OBJECT, KIND_MATERIAL, KIND_IMAGE)
KIND_LABELS = {KIND_OBJECT: "物体", KIND_MATERIAL: "材质", KIND_IMAGE: "贴图"}

A_PREFIX = "PREFIX"
A_SUFFIX = "SUFFIX"
A_STRIP_PREFIX = "STRIP_PREFIX"
A_STRIP_SUFFIX = "STRIP_SUFFIX"
A_RENAME = "RENAME"
ACTION_KEYS = (A_PREFIX, A_SUFFIX, A_STRIP_PREFIX, A_STRIP_SUFFIX, A_RENAME)

SEPARATORS = "_- "

DEFAULT_WIDTH = 4
DEFAULT_START = 1

_ILLEGAL = '<>:"/\\|?*'
_CTRL_RE = re.compile(r"[\x00-\x1f]")
_EXT_RE = re.compile(r"\.([A-Za-z0-9]{1,6})$")
_HASH_RE = re.compile(r"(#+)")
_RESERVED = ({"CON", "PRN", "AUX", "NUL"}
             | {"COM%d" % i for i in range(1, 10)}
             | {"LPT%d" % i for i in range(1, 10)})

MAX_FILENAME = 180

def split_ext(name):
    name = name or ""
    m = _EXT_RE.search(name)
    if m:
        return name[:m.start()], name[m.start():]
    return name, ""

class Shape(object):

    __slots__ = ("head", "hashes", "post", "ext")

    def __init__(self, head, hashes, post, ext):
        self.head = head
        self.hashes = hashes
        self.post = post
        self.ext = ext

    @property
    def is_sequence(self):
        return bool(self.hashes)

    def render(self):
        return self.head + self.hashes + self.post + self.ext

def parse(name, with_ext):
    name = name or ""
    if with_ext:
        stem, ext = split_ext(name)
    else:
        stem, ext = name, ""
    m = _HASH_RE.search(stem)
    if m:
        return Shape(stem[:m.start()], m.group(1), stem[m.end():], ext)
    return Shape(stem, "", "", ext)

def pad(n, width=DEFAULT_WIDTH):
    return str(int(n)).zfill(int(width))

def _cut_first_sep(head):
    for i, ch in enumerate(head):
        if ch in SEPARATORS:
            rest = head[i + 1:]
            if rest:
                return rest
            return None
    return None

def _cut_last_sep(head):
    for i in range(len(head) - 1, -1, -1):
        if head[i] in SEPARATORS:
            rest = head[:i]
            if rest:
                return rest
            return None
    return None

def strip_prefix(head, kw):
    if kw and head.startswith(kw) and len(head) > len(kw):
        return head[len(kw):]
    return _cut_first_sep(head)

def strip_suffix(head, kw):
    if kw and head.endswith(kw) and len(head) > len(kw):
        return head[:-len(kw)]
    return _cut_last_sep(head)

def transform(name, action, kw, with_ext, serial=None):
    sh = parse(name, with_ext)
    old = sh.render()
    kw = kw or ""

    if action == A_PREFIX:
        if not kw:
            return None
        sh.head = kw + sh.head

    elif action == A_SUFFIX:
        if not kw:
            return None
        sh.head = sh.head + kw

    elif action == A_STRIP_PREFIX:
        new_head = strip_prefix(sh.head, kw)
        if new_head is None:
            return None
        sh.head = new_head

    elif action == A_STRIP_SUFFIX:
        new_head = strip_suffix(sh.head, kw)
        if new_head is None:
            return None
        sh.head = new_head

    elif action == A_RENAME:
        if not kw:
            return None
        num = pad(serial if serial is not None else DEFAULT_START)
        if sh.is_sequence:
            sh.head = kw + num + "_"
        else:
            sh.head = kw + num
        sh.post = ""

    else:
        raise ValueError("unknown action: %r" % (action,))

    new = sh.render()
    if new == old or not new:
        return None
    return new

def sanitize_keyword(kw):
    raw = kw or ""
    out = _CTRL_RE.sub("", raw)
    for ch in _ILLEGAL:
        out = out.replace(ch, "_")
    out = out.rstrip(" .")
    return out, (out != raw)

def sanitize_filename(name):
    s = _CTRL_RE.sub("", name or "")
    for ch in _ILLEGAL:
        s = s.replace(ch, "_")
    s = s.rstrip(" .").strip()
    if not s:
        return ""
    stem, ext = split_ext(s)
    if (stem or s).upper() in _RESERVED:
        s = "_" + s
        stem, ext = split_ext(s)
    if len(s) > MAX_FILENAME:
        keep = MAX_FILENAME - len(ext)
        s = (stem[:keep] if keep > 0 else "") + ext
    return s

def sequence_frame_name(pattern, digits):
    m = _HASH_RE.search(pattern or "")
    if not m:
        return pattern
    return pattern[:m.start()] + (digits or "") + pattern[m.end():]
