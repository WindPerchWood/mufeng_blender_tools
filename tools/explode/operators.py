import bpy
from bpy.props import EnumProperty, FloatProperty, PointerProperty
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
        PANEL_CATEGORY="MF Tools",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[MF Tools] {level}: {msg}"),
    )

TOOL_ID = "Explode"
OP_ID = f"mf.{TOOL_ID.lower()}_do"
WM_ATTR = "mf_explode"


BBOX_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LATTICE',
              'GPENCIL', 'ARMATURE', 'GREASEPENCIL'}

AXIS_ITEMS = (
    ('X', "X", "只沿世界 X 轴向外推开"),
    ('Y', "Y", "只沿世界 Y 轴向外推开"),
    ('Z', "Z", "只沿世界 Z 轴向外推开"),
    ('XYZ', "XYZ", "三个轴同时向外推开"),
)


def world_aabb(obj):
    if obj.type in BBOX_TYPES:
        try:
            pts = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        except Exception:
            pts = []
        if pts:
            lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
            hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
            return lo, hi

    pos = obj.matrix_world.translation.copy()
    return pos, pos.copy()


def scale_vector(axis, distance):
    factors = Vector((1.0, 1.0, 1.0))
    if axis == 'X':
        factors.x = distance
    elif axis == 'Y':
        factors.y = distance
    elif axis == 'Z':
        factors.z = distance
    else:
        factors = Vector((distance, distance, distance))
    return factors


def hierarchy_depth(obj):
    depth, parent, guard = 0, obj.parent, 0
    while parent is not None and guard < 64:
        depth += 1
        parent = parent.parent
        guard += 1
    return depth


def shift_world(obj, delta):
    mw = obj.matrix_world.copy()
    mw.translation = mw.translation + delta
    obj.matrix_world = mw


class MF_PG_ExplodeSettings(bpy.types.PropertyGroup):
    distance: FloatProperty(
        name="炸开距离",
        description="以选中对象的整体中心为基准向外推开的倍率（2 = 距离翻倍）",
        default=2.0,
        min=1.001,
        max=1000.0,
        soft_max=10.0,
        step=10,
        precision=3,
    )


class MF_OT_Explode_Do(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "原地炸开"
    bl_description = "以选中对象的整体中心为基准，沿指定世界轴按倍率向外推开，整体位置不变"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name="轴向", items=AXIS_ITEMS, default='XYZ')
    distance: FloatProperty(name="炸开距离", default=2.0, min=1.001, max=1000.0)

    def execute(self, context):
        targets = list(context.selected_objects)
        if not targets:

            self.report({'WARNING'}, "请先选择物体")
            return {'CANCELLED'}

        targets.sort(key=hierarchy_depth)

        boxes = [(obj, world_aabb(obj)) for obj in targets]

        lo = Vector((min(b[0].x for _, b in boxes),
                     min(b[0].y for _, b in boxes),
                     min(b[0].z for _, b in boxes)))
        hi = Vector((max(b[1].x for _, b in boxes),
                     max(b[1].y for _, b in boxes),
                     max(b[1].z for _, b in boxes)))
        pivot = (lo + hi) * 0.5

        factors = scale_vector(self.axis, self.distance)
        for obj, (blo, bhi) in boxes:
            center = (blo + bhi) * 0.5
            delta = Vector((
                (center.x - pivot.x) * (factors.x - 1.0),
                (center.y - pivot.y) * (factors.y - 1.0),
                (center.z - pivot.z) * (factors.z - 1.0),
            ))
            shift_world(obj, delta)

        utils.report("INFO", f"原地炸开 {len(targets)} 个对象，轴向 {self.axis}，倍率 {self.distance:g}")
        return {'FINISHED'}


classes = (MF_PG_ExplodeSettings, MF_OT_Explode_Do)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR, PointerProperty(type=MF_PG_ExplodeSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
