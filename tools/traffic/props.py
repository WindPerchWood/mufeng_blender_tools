
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

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
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

SCENE_ATTR = "mf_traffic"

PREFIX_UNIT = "mf_unit_"
PREFIX_CAR = "mf_car_"

TAG_UNIT = "traf_unit"
TAG_CAR = "traf_car"


class MF_PG_TrafficItem(bpy.types.PropertyGroup):
    name: StringProperty(
        name="名称",
        description="被拾取的物体名",
        default="",
    )
    icon: StringProperty(
        name="图标",
        description="列表里显示的图标标识（由拾取时按物体类型写入）",
        default="OBJECT_DATA",
    )


class MF_PG_TrafficSettings(bpy.types.PropertyGroup):
    roads: CollectionProperty(
        type=MF_PG_TrafficItem,
        name="道路列表",
        description="拾取到的道路曲线名",
    )
    road_index: IntProperty(
        name="道路索引",
        default=-1,
    )
    cars: CollectionProperty(
        type=MF_PG_TrafficItem,
        name="车辆列表",
        description="拾取到的车辆模板名",
    )
    car_index: IntProperty(
        name="车辆索引",
        default=-1,
    )

    car_count: IntProperty(
        name="车辆数量",
        description="要生成的车辆实例数",
        default=10,
        min=0,
        max=2000,
    )

    global_offset: FloatProperty(
        name="前后偏移",
        description="当前道路上的车沿路径随机前后错位。每次调整都在现值上累加",
        default=0.0,
        min=0.0,
        max=100.0,
    )
    anim_start_frame: IntProperty(
        name="起始帧",
        description="动画从第几帧开始算（关键帧的起点；错开各车相位就在这上面加偏移）",
        default=1,
        min=0,
        max=1000000,
    )
    loop_frames: IntProperty(
        name="走完一圈（帧）",
        description="一辆车走完整条曲线用多少帧：闭合曲线 = 绕一圈回到原处，"
                    "开放曲线 = 从这头走到那头再从头开始。帧数越小走得越快。"
                    "同一条路上的车共用这一个帧数（同速，不会互相追上）",
        default=75,
        min=1,
        max=100000,
    )

    last_report: StringProperty(
        name="最近一次结果",
        description="上一次操作的简短回执",
        default="",
    )
    show_report: BoolProperty(
        name="显示结果",
        default=True,
    )


classes = (
    MF_PG_TrafficItem,
    MF_PG_TrafficSettings,
)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    setattr(bpy.types.Scene, SCENE_ATTR, PointerProperty(
        type=MF_PG_TrafficSettings,
        name="交通流设置",
        description="车辆道路生成系统的设置",
    ))


def unregister():
    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    utils.unregister_classes(classes)
