import math
import random

import bpy
from bpy.props import (BoolProperty, FloatProperty, IntProperty,
                       PointerProperty)
from mathutils import Matrix, Quaternion, Vector

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

TOOL_ID = "BookStack"
OP_ID = "mf.bookstack_generate"
WM_ATTR = "mf_bookstack"

COLL_BASE = "MF_书本堆叠"


class MF_PG_BookStackSettings(bpy.types.PropertyGroup):
    count: IntProperty(
        name="数量",
        description="一共堆叠多少本",
        default=100, min=1, max=1000000,
    )
    rot_x_prob: IntProperty(
        name="X 翻转概率 %",
        description="每本书绕 X 轴翻转 180° 的概率 (0-100)",
        default=25, min=0, max=100,
    )
    rot_y_prob: IntProperty(
        name="Y 翻转概率 %",
        description="每本书绕 Y 轴翻转 180° 的概率 (0-100)",
        default=25, min=0, max=100,
    )
    rot_xy_deg: FloatProperty(
        name="XY 旋转角度",
        description="绕 Z 轴（竖直）的随机旋转幅度，实际角度在 ±该值/2 之间",
        default=5.0, min=0.0, max=360.0,
    )
    offset: FloatProperty(
        name="书本偏移",
        description="每本书在 X/Y 平面上的随机偏移幅度（世界单位·米），实际偏移在 ±该值/2 之间",
        default=0.05, min=0.0, soft_max=1.0, max=100000.0,
    )
    no_repeat: BoolProperty(
        name="相邻不重复",
        description="相邻两本书不会选用同一个源物体（源物体需 >1 个才生效）",
        default=False,
    )


def _get_props(context):
    return getattr(context.window_manager, WM_ATTR, None)


def _unique_collection_name():
    base = COLL_BASE
    name = base
    n = 1
    while name in bpy.data.collections:
        n += 1
        name = f"{base}_{n}"
    return name


class MF_OT_BookStack_Generate(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "开始堆叠"
    bl_description = "把选中的源物体随机堆成一摞，归入新集合"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}

        sources = list(context.selected_objects)
        name = _unique_collection_name()
        coll = bpy.data.collections.new(name)
        context.scene.collection.children.link(coll)

        count = props.count
        rx_prob = props.rot_x_prob
        ry_prob = props.rot_y_prob
        xy_deg = props.rot_xy_deg
        off = props.offset
        no_repeat = props.no_repeat

        base_co = Vector((0.0, 0.0, 0.0))
        for s in sources:
            base_co += s.matrix_world.translation
        base_co /= len(sources)

        current_z = base_co.z
        prev_idx = -1

        for _ in range(count):
            idx = random.randint(0, len(sources) - 1)
            if no_repeat and len(sources) > 1:
                guard = 0
                while idx == prev_idx and guard < 100:
                    idx = random.randint(0, len(sources) - 1)
                    guard += 1
            prev_idx = idx
            src = sources[idx]

            new = src.copy()
            new.parent = None
            coll.objects.link(new)

            new.rotation_mode = 'QUATERNION'
            rx = math.pi if (random.random() * 100.0 < rx_prob) else 0.0
            ry = math.pi if (random.random() * 100.0 < ry_prob) else 0.0
            rz = math.radians(random.uniform(-xy_deg / 2.0, xy_deg / 2.0))
            q = Quaternion((1, 0, 0), rx) @ Quaternion((0, 1, 0), ry) @ Quaternion((0, 0, 1), rz)
            new.rotation_quaternion = q

            ox = random.uniform(-off / 2.0, off / 2.0)
            oy = random.uniform(-off / 2.0, off / 2.0)
            new.location = (base_co.x + ox, base_co.y + oy, current_z)

            m = Matrix.Translation(new.location) @ new.rotation_quaternion.to_matrix().to_4x4()
            s = Matrix.Diagonal((new.scale.x, new.scale.y, new.scale.z, 1.0))
            m = m @ s

            bbox = new.bound_box
            if bbox:
                zs = [(m @ Vector(c)).z for c in bbox]
                zmin = min(zs)
                zmax = max(zs)
                new.location.z += (current_z - zmin)
                current_z += (zmax - zmin)

        self.report({'INFO'}, f"已生成 {count} 个实例，归入集合「{name}」")
        return {'FINISHED'}


classes = (
    MF_PG_BookStackSettings,
    MF_OT_BookStack_Generate,
)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_BookStackSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
