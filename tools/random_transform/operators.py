import random
from math import radians

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       PointerProperty, StringProperty)
from mathutils import Euler, Matrix, Vector


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

TOOL_ID = "RandomXform"
DO_OP_ID = "mf.randxform_do"
RESET_OP_ID = "mf.randxform_reset"
WM_ATTR = "mf_randxform"

AXES = ("x", "y", "z")
_FAR = 9999999.0

MODE_ITEMS = (
    ('MOVE', "移动", "随机位移"),
    ('ROTATE', "旋转", "随机旋转（单位：度）"),
    ('SCALE', "缩放", "随机缩放倍率"),
)
COORD_ITEMS = (
    ('WORLD', "世界", "沿世界坐标轴"),
    ('LOCAL', "局部", "沿物体自身坐标轴"),
    ('PARENT', "父级", "沿父对象坐标轴（无父级等同世界）"),
)

MODE_LABEL = {item[0]: item[1] for item in MODE_ITEMS}


_MODE_DEFAULTS = {
    'MOVE': dict(min_x=-10.0, max_x=10.0, axis_x=True,
                 min_y=-10.0, max_y=10.0, axis_y=True,
                 min_z=-10.0, max_z=10.0, axis_z=False,
                 coord='WORLD', link_all=True, link_xy=False, link_yz=False),
    'ROTATE': dict(min_x=-360.0, max_x=360.0, axis_x=False,
                   min_y=-360.0, max_y=360.0, axis_y=False,
                   min_z=-360.0, max_z=360.0, axis_z=True,
                   coord='WORLD', link_all=True, link_xy=False, link_yz=False),
    'SCALE': dict(min_x=0.8, max_x=1.2, axis_x=True,
                  min_y=0.8, max_y=1.2, axis_y=True,
                  min_z=0.8, max_z=1.2, axis_z=True,
                  coord='LOCAL', link_all=True, link_xy=False, link_yz=False,
                  reset_scale=False),
}


_SLOTS = ("min_x", "max_x", "axis_x", "min_y", "max_y", "axis_y",
          "min_z", "max_z", "axis_z", "coord", "link_all", "link_xy", "link_yz",
          "reset_scale")

_SAVED = {}
_FLAGS = {"skip_save": False, "link": False}


def _link_sync(props, src):
    if _FLAGS["link"]:
        return
    _FLAGS["link"] = True
    try:
        def copy_to(dst):
            setattr(props, f"min_{dst}", getattr(props, f"min_{src}"))
            setattr(props, f"max_{dst}", getattr(props, f"max_{src}"))

        if props.link_all:
            for axis in AXES:
                if axis != src:
                    copy_to(axis)
        elif src == 'x':
            if props.link_xy:
                copy_to('z' if props.link_yz else 'y')
        elif src == 'y':
            if props.link_xy and not props.link_yz:
                copy_to('x')
            if props.link_yz and not props.link_xy:
                copy_to('z')
        elif src == 'z':
            if props.link_yz:
                copy_to('x' if props.link_xy else 'y')
    finally:
        _FLAGS["link"] = False


def _make_axis_update(axis):
    def _update(props, context):
        _link_sync(props, axis)
    return _update


def _on_link_all(props, context):
    if _FLAGS["link"] or not props.link_all:
        return
    _FLAGS["link"] = True
    try:
        props.link_xy = False
        props.link_yz = False
        props.min_y, props.max_y = props.min_x, props.max_x
        props.min_z, props.max_z = props.min_x, props.max_x
    finally:
        _FLAGS["link"] = False


def _on_link_xy(props, context):
    if _FLAGS["link"] or not props.link_xy:
        return
    _FLAGS["link"] = True
    try:
        props.link_all = False
        if props.link_yz:
            props.min_z, props.max_z = props.min_x, props.max_x
        else:
            props.min_y, props.max_y = props.min_x, props.max_x
    finally:
        _FLAGS["link"] = False


def _on_link_yz(props, context):
    if _FLAGS["link"] or not props.link_yz:
        return
    _FLAGS["link"] = True
    try:
        props.link_all = False
        props.min_z, props.max_z = props.min_y, props.max_y
    finally:
        _FLAGS["link"] = False


def _apply_defaults(props, mode):
    defaults = _MODE_DEFAULTS.get(mode)
    if not defaults:
        return
    _FLAGS["link"] = True
    try:
        for key, value in defaults.items():
            setattr(props, key, value)
    finally:
        _FLAGS["link"] = False


def _on_mode_change(props, context):
    previous = props.last_mode
    if previous == props.mode:
        return
    if previous and not _FLAGS["skip_save"]:
        _SAVED[previous] = {key: getattr(props, key) for key in _SLOTS}
    props.last_mode = props.mode
    saved = _SAVED.get(props.mode)
    if not saved:
        _apply_defaults(props, props.mode)
        return
    _FLAGS["link"] = True
    try:
        for key, value in saved.items():
            setattr(props, key, value)
    finally:
        _FLAGS["link"] = False


class MF_PG_RandomXformSettings(bpy.types.PropertyGroup):
    mode: EnumProperty(name="类型", items=MODE_ITEMS, default='MOVE',
                       update=_on_mode_change)
    last_mode: StringProperty(default="MOVE")
    coord: EnumProperty(name="坐标系", items=COORD_ITEMS, default='WORLD')

    axis_x: BoolProperty(name="X", default=True)
    axis_y: BoolProperty(name="Y", default=True)
    axis_z: BoolProperty(name="Z", default=False)
    min_x: FloatProperty(name="最小", default=-10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('x'))
    max_x: FloatProperty(name="最大", default=10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('x'))
    min_y: FloatProperty(name="最小", default=-10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('y'))
    max_y: FloatProperty(name="最大", default=10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('y'))
    min_z: FloatProperty(name="最小", default=-10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('z'))
    max_z: FloatProperty(name="最大", default=10.0, soft_min=-_FAR, soft_max=_FAR,
                         update=_make_axis_update('z'))

    link_all: BoolProperty(name="XYZ 同时", default=True, update=_on_link_all)
    link_xy: BoolProperty(name="X 与 Y 相同", default=False, update=_on_link_xy)
    link_yz: BoolProperty(name="Y 与 Z 相同", default=False, update=_on_link_yz)

    reset_scale: BoolProperty(name="按初始缩放", default=False)


def _axis_range(props, axis):
    low = getattr(props, f"min_{axis}")
    high = getattr(props, f"max_{axis}")
    if low > high:
        low, high = high, low
    return low, high


def _raw_random(props, axis):
    low, high = _axis_range(props, axis)
    return random.uniform(low, high)


def _random_axis(props, axis):
    if not getattr(props, f"axis_{axis}"):
        return 0.0
    return _raw_random(props, axis)


def _random_vector(props):
    return Vector((_random_axis(props, 'x'),
                   _random_axis(props, 'y'),
                   _random_axis(props, 'z')))


def _random_rotation(props):
    rx = _random_axis(props, 'x')
    ry = _random_axis(props, 'y')
    rz = _random_axis(props, 'z')
    if rx == 0.0 and ry == 0.0 and rz == 0.0:
        return None

    return Euler((radians(rx), radians(ry), radians(rz)), 'XYZ').to_matrix()


def _frame_3x3(obj, coord):
    if coord == 'LOCAL':
        return obj.matrix_world.to_3x3()
    if coord == 'PARENT' and obj.parent is not None:
        return obj.parent.matrix_world.to_3x3()
    return Matrix.Identity(3)


def _move_object(obj, delta, coord):
    world_delta = _frame_3x3(obj, coord) @ delta
    matrix = obj.matrix_world.copy()
    matrix.translation = matrix.translation + world_delta
    obj.matrix_world = matrix


def _rotate_object(obj, rotation, coord):
    matrix = obj.matrix_world.copy()
    if coord == 'LOCAL':
        new3 = matrix.to_3x3() @ rotation
    else:
        frame = _frame_3x3(obj, coord)
        new3 = (frame @ rotation @ frame.inverted()) @ matrix.to_3x3()
    new_matrix = new3.to_4x4()
    new_matrix.translation = matrix.translation
    obj.matrix_world = new_matrix


def _scale_object(obj, props):
    sx = _raw_random(props, 'x')
    sy = _raw_random(props, 'y')
    sz = _raw_random(props, 'z')

    if props.link_all:
        sz = sy = sx
    if props.link_xy and not props.link_yz:
        sy = sx
    if props.link_yz and not props.link_xy:
        sz = sy
    if props.link_xy and props.link_yz:
        sz = sx

    factors = (max(0.0, sx) if props.axis_x else 1.0,
               max(0.0, sy) if props.axis_y else 1.0,
               max(0.0, sz) if props.axis_z else 1.0)

    if props.reset_scale:
        obj.scale = (1.0, 1.0, 1.0)
    obj.scale = (obj.scale[0] * factors[0],
                 obj.scale[1] * factors[1],
                 obj.scale[2] * factors[2])


def _sorted_parents_first(objs):
    def depth(obj):
        level = 0
        parent = obj.parent
        while parent is not None:
            level += 1
            parent = parent.parent
        return level

    return sorted(objs, key=depth)


def _get_props(context):
    return getattr(context.window_manager, WM_ATTR, None)


class MF_OT_RandomXform_Do(bpy.types.Operator):
    bl_idname = DO_OP_ID
    bl_label = "随机变换"
    bl_description = ("按当前参数对每个选中物体抽一次随机值（移动/旋转/缩放三选一，"
                      "坐标系按面板设置）")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            self.report({'WARNING'}, "请先在物体模式下操作（编辑模式下物体变换不生效）")
            return {'CANCELLED'}

        targets = _sorted_parents_first(context.selected_objects)
        if not targets:
            self.report({'WARNING'}, "没有选中任何物体")
            return {'CANCELLED'}

        for obj in targets:
            if props.mode == 'MOVE':
                _move_object(obj, _random_vector(props), props.coord)
            elif props.mode == 'ROTATE':
                rotation = _random_rotation(props)
                if rotation is not None:
                    _rotate_object(obj, rotation, props.coord)
            else:
                _scale_object(obj, props)

        _SAVED[props.mode] = {key: getattr(props, key) for key in _SLOTS}
        self.report({'INFO'}, f"{len(targets)} 个物体已随机{MODE_LABEL.get(props.mode, '')}")
        return {'FINISHED'}


class MF_OT_RandomXform_Reset(bpy.types.Operator):
    bl_idname = RESET_OP_ID
    bl_label = "重设参数"
    bl_description = "参数恢复默认，并清掉移动/旋转/缩放各自记下的参数"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}
        _SAVED.clear()
        _FLAGS["skip_save"] = True
        try:
            props.mode = 'MOVE'
        finally:
            _FLAGS["skip_save"] = False
        _apply_defaults(props, 'MOVE')
        props.last_mode = 'MOVE'
        self.report({'INFO'}, "参数已重设为默认")
        return {'FINISHED'}


classes = (
    MF_PG_RandomXformSettings,
    MF_OT_RandomXform_Do,
    MF_OT_RandomXform_Reset,
)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_RandomXformSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
