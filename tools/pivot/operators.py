import random

import bpy
from bpy.props import BoolProperty, EnumProperty
from mathutils import Matrix, Vector

from ...core import utils

TOOL_ID = "Pivot"

ITEMS = (
    ('X_MAX', "X 最大", "轴心移到 X 方向最大面中心"),
    ('X_MIN', "X 最小", "轴心移到 X 方向最小面中心"),
    ('Y_MAX', "Y 最大", "轴心移到 Y 方向最大面中心"),
    ('Y_MIN', "Y 最小", "轴心移到 Y 方向最小面中心"),
    ('Z_MAX', "Z 最大", "轴心移到 Z 方向最大面中心"),
    ('Z_MIN', "Z 最小", "轴心移到 Z 方向最小面中心"),
    ('CENTER', "包围盒中心", "轴心移到包围盒正中心"),
    ('RANDOM', "随机", "轴心移到包围盒内随机一点"),
)


def bbox_extents(obj):
    corners = [Vector(c) for c in obj.bound_box]
    xs = [v.x for v in corners]
    ys = [v.y for v in corners]
    zs = [v.z for v in corners]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def target_local_pos(obj, pos_type):
    lo, hi = bbox_extents(obj)
    mid = (lo + hi) / 2.0
    if pos_type == 'X_MAX':
        return Vector((hi.x, mid.y, mid.z))
    if pos_type == 'X_MIN':
        return Vector((lo.x, mid.y, mid.z))
    if pos_type == 'Y_MAX':
        return Vector((mid.x, hi.y, mid.z))
    if pos_type == 'Y_MIN':
        return Vector((mid.x, lo.y, mid.z))
    if pos_type == 'Z_MAX':
        return Vector((mid.x, mid.y, hi.z))
    if pos_type == 'Z_MIN':
        return Vector((mid.x, mid.y, lo.z))
    if pos_type == 'CENTER':
        return mid
    if pos_type == 'RANDOM':
        return Vector((random.uniform(lo.x, hi.x),
                       random.uniform(lo.y, hi.y),
                       random.uniform(lo.z, hi.z)))
    raise ValueError(f"未知轴心类型: {pos_type}")


def set_origin(obj, pos_type):
    local_pos = target_local_pos(obj, pos_type)
    world_pos = obj.matrix_world @ local_pos

    if hasattr(obj.data, "transform"):
        obj.data.transform(Matrix.Translation(-local_pos))
        obj.data.update()
        obj.matrix_world.translation = world_pos
        return True

    scene = bpy.context.scene
    saved = scene.cursor.location.copy()
    try:
        scene.cursor.location = world_pos
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
        return True
    except Exception:
        return False
    finally:
        scene.cursor.location = saved


class MF_OT_Pivot_Set(bpy.types.Operator):
    bl_idname = f"mf.{TOOL_ID.lower()}_set"
    bl_label = "设置轴心点"
    bl_description = "把选中对象的轴心对齐到包围盒的指定位置，物体本身不位移"
    bl_options = {'REGISTER', 'UNDO'}

    pos_type: EnumProperty(name="轴心位置", items=ITEMS, default='Z_MIN')
    keep_world_transform: BoolProperty(name="保持世界变换", default=True,
                                       description="关闭后物体会跟着轴心一起移动")

    def execute(self, context):
        targets = context.selected_objects
        if not targets:
            self.report({'WARNING'}, "没有选中任何对象")
            return {'CANCELLED'}

        if not self.keep_world_transform:

            self.report({'INFO'}, "该功能暂不支持关闭保持世界变换")
            return {'CANCELLED'}

        done, failed = 0, []
        for obj in targets:
            if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'LATTICE', 'FONT',
                                'META', 'ARMATURE', 'EMPTY', 'GPENCIL'}:
                failed.append(f"{obj.name}({obj.type})")
                continue
            if obj.type == 'EMPTY' or obj.data is None:
                failed.append(f"{obj.name}(无数据)")
                continue
            try:
                if set_origin(obj, self.pos_type):
                    done += 1
                else:
                    failed.append(obj.name)
            except Exception as exc:
                failed.append(f"{obj.name}({exc})")

        if done:
            label = dict((i[0], i[1]) for i in ITEMS).get(self.pos_type, self.pos_type)
            utils.report("INFO", f"{done} 个对象轴心已对齐到 {label}")
        if failed:
            utils.report("WARNING", "跳过: " + ", ".join(failed))
        return {'FINISHED'}


classes = (MF_OT_Pivot_Set,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
