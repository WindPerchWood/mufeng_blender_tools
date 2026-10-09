import bpy
import os

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
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

TOOL_ID = "FileLost"
OP_ID_PREFIX = f"mf.{TOOL_ID.lower()}_"
OP_SCAN = OP_ID_PREFIX + "scan"
OP_RECONNECT = OP_ID_PREFIX + "reconnect"
OP_ROOT_ADD = OP_ID_PREFIX + "root_add"
OP_ROOT_REMOVE = OP_ID_PREFIX + "root_remove"
OP_ITEM_ACTIVATE = OP_ID_PREFIX + "item_activate"

KIND_IMAGE = "IMAGE"
KIND_HDRI = "HDRI"

KIND_ICONS = {
    KIND_IMAGE: 'IMAGE_DATA',
    KIND_HDRI: 'WORLD',
}


# ---------------------------------------------------------------------------
# 属性组
# ---------------------------------------------------------------------------

class MF_PG_FileLostRoot(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(name="搜索目录")


class MF_PG_FileLostItem(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty(name="名称")
    kind: bpy.props.StringProperty(name="类型")
    filepath: bpy.props.StringProperty(name="路径")
    block_name: bpy.props.StringProperty()
    status: bpy.props.StringProperty()


class MF_PG_FileLostSettings(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=MF_PG_FileLostItem)
    active_index: bpy.props.IntProperty()
    search_roots: bpy.props.CollectionProperty(type=MF_PG_FileLostRoot)
    last_message: bpy.props.StringProperty()


# ---------------------------------------------------------------------------
# 扫描 / 搜索 / 重连 业务函数
# ---------------------------------------------------------------------------

def _iter_mat_nodes(pred):
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if pred(node):
                yield mat, node


def _hdri_image_names():
    names = set()
    for _mat, node in _iter_mat_nodes(lambda n: n.type == 'TEX_ENVIRONMENT'):
        if node.image is not None:
            names.add(node.image.name)
    return names


def basename(fp):
    return fp.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _is_sequence_fp(fp):
    return '#' in fp


def _seq_parts(fp):
    d = os.path.dirname(bpy.path.abspath(fp))
    base = basename(fp)
    ext = os.path.splitext(base)[1]
    prefix = base.split('#')[0]
    return d, prefix, ext


def _sequence_has_frames(fp):
    d, prefix, ext = _seq_parts(fp)
    if not d:
        d = os.getcwd()
    try:
        names = os.listdir(d)
    except OSError:
        return False
    for nm in names:
        if nm.startswith(prefix) and nm.endswith(ext) and '#' not in nm:
            return True
    return False


def image_is_missing(img):
    fp = getattr(img, 'filepath', '')
    if not fp:
        return False
    if img.packed_file is not None:
        return False
    if img.source == 'VIEWER':
        return False
    if img.source == 'SEQUENCE':
        return not _sequence_has_frames(fp)
    resolved = bpy.path.abspath(fp)
    if not os.path.isabs(resolved):
        return True
    return not os.path.exists(resolved)


def _add_item(settings, label, kind, fp, bname):
    it = settings.items.add()
    it.label = label
    it.kind = kind
    it.filepath = fp
    it.block_name = bname
    it.status = "MISSING"


def op_scan(settings):
    hdri = _hdri_image_names()
    settings.items.clear()

    for img in bpy.data.images:
        if img.library is not None:
            continue
        if not image_is_missing(img):
            continue
        kind = KIND_HDRI if img.name in hdri else KIND_IMAGE
        _add_item(settings, img.name, kind, img.filepath, img.name)

    settings.last_message = ("未检测到丢失的外部贴图" if not settings.items
                             else "发现 %d 项丢失贴图" % len(settings.items))


def search_file(fp, roots):
    seq = _is_sequence_fp(fp)
    if seq:
        _d, prefix, ext = _seq_parts(fp)
        target_prefix, target_ext = prefix, ext
    else:
        target_prefix = basename(fp)
        target_ext = None

    for root in roots:
        root = (root or "").strip()
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if _match(f, seq, target_prefix, target_ext):
                    return os.path.join(dirpath, f)
    return None


def _match(fname, seq, prefix, ext):
    if seq:
        return fname.startswith(prefix) and fname.endswith(ext) and '#' not in fname
    return fname == prefix


def _rebuild_seq_pattern(found_file, original_fp):
    d = os.path.dirname(found_file)
    _d0, prefix, ext = _seq_parts(original_fp)
    n_hash = original_fp.count('#')
    return os.path.join(d, prefix + ('#' * n_hash) + ext)


def op_reconnect_one(settings, item):
    roots = [r.path for r in settings.search_roots]
    found = search_file(item.filepath, roots)
    if not found:
        return 'CANCELLED', "未找到匹配文件：%s" % basename(item.filepath)
    block = bpy.data.images.get(item.block_name)
    if block is None:
        return 'CANCELLED', "对应的贴图数据块已不存在"
    try:
        if _is_sequence_fp(item.filepath):
            block.source = 'SEQUENCE'
            block.filepath = _rebuild_seq_pattern(found, item.filepath)
        else:
            block.filepath = found
    except Exception as e:
        return 'CANCELLED', "设置路径失败：%s" % e
    if hasattr(block, 'reload'):
        try:
            block.reload()
        except Exception:
            pass
    item.status = "FOUND"
    return 'FINISHED', "已重连：%s" % found


# ---------------------------------------------------------------------------
# 操作符
# ---------------------------------------------------------------------------

class MF_OT_Scan(bpy.types.Operator):
    bl_idname = OP_SCAN
    bl_label = "检查丢失资源"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        core = context.scene.mf_filelost_settings
        op_scan(core)
        self.report({'INFO'}, core.last_message)
        return {'FINISHED'}


class MF_OT_Reconnect(bpy.types.Operator):
    bl_idname = OP_RECONNECT
    bl_label = "搜索并重新连接"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        st = context.scene.mf_filelost_settings
        ok = fail = 0
        for it in st.items:
            status, msg = op_reconnect_one(st, it)
            if status == 'FINISHED':
                ok += 1
            else:
                fail += 1
                self.report({'WARNING'}, msg)
        st.last_message = "重连 %d 成功 / %d 失败" % (ok, fail)
        self.report({'INFO'}, st.last_message)
        return {'FINISHED'}


class MF_OT_RootAdd(bpy.types.Operator):
    bl_idname = OP_ROOT_ADD
    bl_label = "添加搜索目录"
    bl_options = {'REGISTER'}

    directory: bpy.props.StringProperty(
        name="搜索目录", subtype='DIR_PATH', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        d = (self.directory or "").strip()
        if not d:
            self.report({'INFO'}, "未选择目录")
            return {'CANCELLED'}
        item = context.scene.mf_filelost_settings.search_roots.add()
        item.path = d
        self.report({'INFO'}, "已添加搜索目录：%s" % d)
        return {'FINISHED'}


class MF_OT_RootRemove(bpy.types.Operator):
    bl_idname = OP_ROOT_REMOVE
    bl_label = "移除搜索目录"
    bl_options = {'REGISTER'}

    index: bpy.props.IntProperty(default=-1, description="要移除的搜索目录在列表中的位置")

    def execute(self, context):
        st = context.scene.mf_filelost_settings
        if not 0 <= self.index < len(st.search_roots):
            return {'CANCELLED'}
        st.search_roots.remove(self.index)
        return {'FINISHED'}


class MF_OT_ItemActivate(bpy.types.Operator):
    bl_idname = OP_ITEM_ACTIVATE
    bl_label = "设为活动项"
    bl_options = {'INTERNAL'}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        st = context.scene.mf_filelost_settings
        if 0 <= self.index < len(st.items):
            st.active_index = self.index
        return {'FINISHED'}


classes = (
    MF_PG_FileLostRoot,
    MF_PG_FileLostItem,
    MF_PG_FileLostSettings,
    MF_OT_Scan,
    MF_OT_Reconnect,
    MF_OT_RootAdd,
    MF_OT_RootRemove,
    MF_OT_ItemActivate,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
