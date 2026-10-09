import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

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
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

from .algorithms import FLIP, NONMANIFOLD, OVERLAP, SCENE_PROP

TOOL_ID = "MeshCheck"

TAG_OBJECT = "meshcheck_marker_obj"
TAG_MESH = "meshcheck_marker_mesh"
TAG_MATERIAL = "meshcheck_marker_mat"
TAG_COLLECTION = "meshcheck_marker_coll"

MARKER_COLLECTION_NAME = "MF_模型体检标记"

KIND_LABELS = {
    FLIP: "反转法线",
    NONMANIFOLD: "非流形边",
    OVERLAP: "重叠面",
}

DIRECTIONAL_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)

DEFAULT_COLORS = {
    FLIP: (1.0, 0.12, 0.10, 1.0),
    NONMANIFOLD: (1.0, 0.78, 0.05, 1.0),
    OVERLAP: (0.10, 0.42, 1.0, 1.0),
}

def _redraw(self, context=None):
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

class MF_PG_MeshCheckSettings(bpy.types.PropertyGroup):
    check_flip: BoolProperty(
        name="反转法线",
        description="检测面朝向内侧的错误（红方块标记）",
        default=True,
        update=_redraw,
    )
    check_nonmanifold: BoolProperty(
        name="非流形边",
        description="检测悬空线、边界/破洞、多面共边（黄方块标记）",
        default=True,
        update=_redraw,
    )
    check_overlap: BoolProperty(
        name="重叠面",
        description="检测空间完全重合的重复面（蓝方块标记）",
        default=True,
        update=_redraw,
    )
    flip_on_open: BoolProperty(
        name="开放网格也查法线",
        description=(
            "默认关闭：网格不封闭时跳过反转法线检测，避免误报。"
            "打开后只报出法向互相矛盾的面，不做整体朝向判定"
        ),
        default=False,
        update=_redraw,
    )

    overlap_tolerance: FloatProperty(
        name="重叠判定容差",
        description="顶点坐标相差小于这个距离时视为同一个位置",
        default=1e-4,
        min=1e-9,
        max=1.0,
        precision=6,
    )
    max_markers: IntProperty(
        name="每类标记上限",
        description="同类错误最多画多少个方块；0 表示不限制",
        default=500,
        min=0,
        max=20000,
    )
    marker_percent: FloatProperty(
        name="方块大小（% 对角线）",
        description="方块边长占被检测物体包围盒对角线的百分比",
        default=8.0,
        min=0.05,
        max=40.0,
        precision=2,
    )
    markers_show_in_front: BoolProperty(
        name="方块穿透显示",
        description="方块始终画在模型前面，不会被模型挡住",
        default=True,
    )
    markers_hide_render: BoolProperty(
        name="方块不参与渲染",
        description="只作视口提示，不进入最终渲染或渲染层可见性",
        default=True,
    )
    use_evaluated: BoolProperty(
        name="按修改器后的网格检测",
        description=(
            "打开后检测的是修改器（细分、布尔等）求值之后的网格；"
            "关闭则检测物体自身的原始网格"
        ),
        default=False,
    )
    show_popup: BoolProperty(
        name="完成后弹窗",
        description="体检结束后弹出结果窗口，直接列出三类错误的个数",
        default=True,
    )

    color_flip: FloatVectorProperty(
        name="反转法线",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.12, 0.10, 1.0),
        update=_redraw,
    )
    color_nonmanifold: FloatVectorProperty(
        name="非流形边",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.78, 0.05, 1.0),
        update=_redraw,
    )
    color_overlap: FloatVectorProperty(
        name="重叠面",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.10, 0.42, 1.0, 1.0),
        update=_redraw,
    )

    has_result: BoolProperty(default=False)
    result_objects: IntProperty(default=0)
    result_flip: IntProperty(default=0)
    result_nonmanifold: IntProperty(default=0)
    result_overlap: IntProperty(default=0)
    note_flip: StringProperty(default="")
    note_nonmanifold: StringProperty(default="")
    note_overlap: StringProperty(default="")
    result_text: StringProperty(default="")
    marker_objects: IntProperty(default=0)

    sec_check: BoolProperty(default=True, update=_redraw)
    sec_param: BoolProperty(default=True, update=_redraw)
    sec_help: BoolProperty(default=False, update=_redraw)

SECTION_PROPS = {
    "check": "sec_check",
    "param": "sec_param",
    "help": "sec_help",
}

def settings(context=None):
    ctx = context if context is not None else bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        return None
    return getattr(scene, SCENE_PROP, None)

def options_from_settings(st):
    if st is None:
        return {}
    return {
        "check_flip": st.check_flip,
        "check_nonmanifold": st.check_nonmanifold,
        "check_overlap": st.check_overlap,
        "flip_on_open": st.flip_on_open,
        "overlap_tolerance": st.overlap_tolerance,
        "max_markers": st.max_markers,
    }

def colors_from_settings(st):
    if st is None:
        return dict(DEFAULT_COLORS)
    return {
        FLIP: tuple(st.color_flip),
        NONMANIFOLD: tuple(st.color_nonmanifold),
        OVERLAP: tuple(st.color_overlap),
    }

def marker_collection(create=True):
    for coll in bpy.data.collections:
        if coll.get(TAG_COLLECTION):
            return coll
    if not create:
        return None
    coll = bpy.data.collections.new(MARKER_COLLECTION_NAME)
    coll[TAG_COLLECTION] = 1
    try:
        bpy.context.scene.collection.children.link(coll)
    except Exception:
        pass
    return coll

def marker_material(kind, rgba):
    name = "MF_模型体检-" + KIND_LABELS.get(kind, kind)
    material = None
    for mat in bpy.data.materials:
        if mat.get(TAG_MATERIAL) == kind:
            material = mat
            break
    if material is None:
        material = bpy.data.materials.new(name)
        material[TAG_MATERIAL] = kind
        material.use_nodes = True

    color = (float(rgba[0]), float(rgba[1]), float(rgba[2]), 1.0)
    material.diffuse_color = color
    material.roughness = 0.35

    tree = material.node_tree
    if tree is not None:
        principled = None
        for node in tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                principled = node
                break
        if principled is None:
            principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
            output = None
            for node in tree.nodes:
                if node.type == "OUTPUT_MATERIAL":
                    output = node
                    break
            if output is None:
                output = tree.nodes.new("ShaderNodeOutputMaterial")
            tree.links.new(principled.outputs[0], output.inputs[0])
        for socket_name, value in (("Base Color", color), ("Emission Color", color)):
            socket = principled.inputs.get(socket_name)
            if socket is not None:
                socket.default_value = value
        for socket_name, value in (("Roughness", 0.35), ("Emission Strength", 2.0)):
            socket = principled.inputs.get(socket_name)
            if socket is not None:
                socket.default_value = value
    return material

def _cube_block(center, half):
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    x0, x1 = cx - half, cx + half
    y0, y1 = cy - half, cy + half
    z0, z1 = cz - half, cz + half
    return [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]

def build_marker_mesh(items):
    verts = []
    faces = []
    for position, half in items:
        base = len(verts)
        verts.extend(_cube_block(position, half))
        for face in DIRECTIONAL_FACES:
            faces.append(tuple(base + i for i in face))
    return verts, faces

def build_markers(bundles, colors, half=0.05, show_in_front=True, hide_render=True):
    clear_markers()
    coll = marker_collection(create=True)
    if coll is None:
        return 0
    coll.hide_viewport = False
    coll.hide_render = bool(hide_render)

    created = 0
    for kind in (FLIP, NONMANIFOLD, OVERLAP):
        raw = bundles.get(kind) or []
        items = []
        for entry in raw:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                items.append((entry[0], float(entry[1])))
            else:
                items.append((entry, float(half)))
        if not items:
            continue
        verts, faces = build_marker_mesh(items)
        if not faces:
            continue

        mesh = bpy.data.meshes.new("MF_模型体检标记-" + KIND_LABELS.get(kind, kind))
        mesh[TAG_MESH] = 1
        mesh.from_pydata(verts, [], faces)
        try:
            mesh.validate(verbose=False)
        except Exception:
            pass
        mesh.update()

        obj = bpy.data.objects.new(mesh.name, mesh)
        obj[TAG_OBJECT] = kind
        obj.show_in_front = bool(show_in_front)
        obj.hide_render = bool(hide_render)
        obj.display_type = "SOLID"

        material = marker_material(kind, colors.get(kind, (1.0, 1.0, 1.0, 1.0)))
        if material is not None:
            mesh.materials.append(material)

        coll.objects.link(obj)
        created += 1
    return created

def clear_markers():
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.get(TAG_OBJECT):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
            except Exception:
                pass
    for mesh in list(bpy.data.meshes):
        if mesh.get(TAG_MESH) and mesh.users == 0:
            try:
                bpy.data.meshes.remove(mesh)
            except Exception:
                pass
    for mat in list(bpy.data.materials):
        if mat.get(TAG_MATERIAL) and mat.users == 0:
            try:
                bpy.data.materials.remove(mat)
            except Exception:
                pass
    for coll in list(bpy.data.collections):
        if coll.get(TAG_COLLECTION):
            try:
                bpy.data.collections.remove(coll)
            except Exception:
                pass
    return removed

def marker_object_count():
    return sum(1 for obj in bpy.data.objects if obj.get(TAG_OBJECT))

classes = (
    MF_PG_MeshCheckSettings,
)

def register():
    utils.register_classes(classes)
    setattr(bpy.types.Scene, SCENE_PROP, PointerProperty(type=MF_PG_MeshCheckSettings))

def unregister():
    if hasattr(bpy.types.Scene, SCENE_PROP):
        delattr(bpy.types.Scene, SCENE_PROP)
    utils.unregister_classes(classes)
