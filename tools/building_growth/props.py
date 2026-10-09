import bpy

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

TOOL_ID = "BuildingGrowth"
SCENE_ATTR = "mf_building_growth"

_AXIS_ITEMS = (
    ('X', "X 轴", "沿世界 X 轴分布 / 偏移"),
    ('Y', "Y 轴", "沿世界 Y 轴分布 / 偏移"),
    ('Z', "Z 轴", "沿世界 Z 轴分布 / 偏移"),
    ('RANDOM', "随机", "每层在 X/Y/Z 中随机取一轴"),
)

_DIR_ITEMS = (
    ('POS', "正向", "物体从该轴负侧飞入，沿正方向落位"),
    ('NEG', "反向", "物体从该轴正侧飞入，沿负方向落位"),
    ('BOTH', "双向", "每个物体随机取正向或反向"),
)

_SCALE_ITEMS = (
    ('X', "X 轴", "X 轴从 0 长到原尺寸"),
    ('Y', "Y 轴", "Y 轴从 0 长到原尺寸"),
    ('Z', "Z 轴", "Z 轴从 0 长到原尺寸"),
    ('UNIFORM', "等比", "三轴同时从 0 长到原尺寸"),
    ('RANDOM', "随机", "每层在 X/Y/Z 中随机取一轴"),
)

_GROUP_ITEMS = (
    ('HIERARCHY', "父级层级", "拾取任一成员，自动上溯到根父级，取它的全部子物体"),
    ('COLLECTION', "集合", "取指定集合里的全部物体（更符合 Blender 习惯）"),
)

_VIS_ITEMS = (
    ('HARD', "硬切换", "在起始帧直接出现（hide_viewport/hide_render，不动物体材质）"),
    ('FADE', "材质淡入", "在生长周期内从全透明渐显（会为物体建立独占材质）"),
)


class MF_PG_BuildingGrowthSettings(bpy.types.PropertyGroup):

    group_mode: bpy.props.EnumProperty(
        name="组来源", items=_GROUP_ITEMS, default='HIERARCHY')
    group_root: bpy.props.PointerProperty(
        name="组物体",
        description="拾取组里的任一物体（会自动上溯到根父级）或直接指定根父级",
        type=bpy.types.Object)
    group_collection: bpy.props.PointerProperty(
        name="组集合", description="以该集合内的全部物体作为生长成员",
        type=bpy.types.Collection)

    grow_axis: bpy.props.EnumProperty(
        name="生长方向", items=_AXIS_ITEMS, default='Z',
        description="按物体在该轴上的位置决定先后顺序")
    reverse_direction: bpy.props.BoolProperty(
        name="反向", default=False,
        description="勾选后从另一头开始生长（例如从上往下）")

    use_path: bpy.props.BoolProperty(
        name="沿路径生长", default=False, description="改用样条曲线的最近点参数排序")
    path_object: bpy.props.PointerProperty(
        name="路径", type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
        description="只接受曲线类型物体")
    path_arc_length: bpy.props.BoolProperty(
        name="按弧长归一", default=True,
        description="勾选=按曲线实际长度归一（更直观）；"
                    "取消=按控制段序号归一")

    use_visibility: bpy.props.BoolProperty(name="可见性", default=True)
    use_move: bpy.props.BoolProperty(name="移动", default=False)
    use_rotate: bpy.props.BoolProperty(name="旋转", default=False)
    use_scale: bpy.props.BoolProperty(name="缩放", default=False)

    prob_v: bpy.props.IntProperty(name="几率", default=100, min=0, max=100, subtype='PERCENTAGE')
    prob_m: bpy.props.IntProperty(name="几率", default=100, min=0, max=100, subtype='PERCENTAGE')
    prob_r: bpy.props.IntProperty(name="几率", default=100, min=0, max=100, subtype='PERCENTAGE')
    prob_s: bpy.props.IntProperty(name="几率", default=100, min=0, max=100, subtype='PERCENTAGE')

    visibility_mode: bpy.props.EnumProperty(
        name="可见性模式", items=_VIS_ITEMS, default='HARD')

    frame_start: bpy.props.IntProperty(
        name="始帧", default=1, min=1, max=500,
        description="整组生长的起始帧")
    frame_end: bpy.props.IntProperty(
        name="末帧", default=50, min=2, max=1000,
        description="整组生长的结束帧")

    period_v: bpy.props.IntProperty(name="周期", default=1, min=1, max=200)
    period_m: bpy.props.IntProperty(name="周期", default=3, min=1, max=200)
    period_r: bpy.props.IntProperty(name="周期", default=3, min=1, max=200)
    period_s: bpy.props.IntProperty(name="周期", default=3, min=1, max=200)

    period_rnd_v: bpy.props.IntProperty(name="周期随机", default=2, min=0, max=200)
    period_rnd_m: bpy.props.IntProperty(name="周期随机", default=4, min=0, max=200)
    period_rnd_r: bpy.props.IntProperty(name="周期随机", default=4, min=0, max=200)
    period_rnd_s: bpy.props.IntProperty(name="周期随机", default=4, min=0, max=200)

    start_rnd_v: bpy.props.IntProperty(name="始帧随机", default=3, min=0, max=100)
    start_rnd_m: bpy.props.IntProperty(name="始帧随机", default=5, min=0, max=100)
    start_rnd_r: bpy.props.IntProperty(name="始帧随机", default=5, min=0, max=100)
    start_rnd_s: bpy.props.IntProperty(name="始帧随机", default=5, min=0, max=100)

    seq_m: bpy.props.FloatProperty(name="排序", default=3.0, min=0.0, max=5.0, precision=1)
    seq_r: bpy.props.FloatProperty(name="排序", default=2.0, min=0.0, max=5.0, precision=1)
    seq_s: bpy.props.FloatProperty(name="排序", default=1.0, min=0.0, max=5.0, precision=1)

    amp_move: bpy.props.FloatProperty(
        name="移动幅度", default=1.8, min=0.0, max=10.0, precision=2,
        description="偏移距离 = 幅度 × 物体沿该轴的自身包围盒边长")
    amp_rotate: bpy.props.FloatProperty(
        name="旋转幅度", default=1.0, min=0.0, max=10.0, precision=2,
        description="偏移角度 = 幅度 × 180°")

    move_axis: bpy.props.EnumProperty(name="方向", items=_AXIS_ITEMS, default='RANDOM')
    move_direction: bpy.props.EnumProperty(name="朝向", items=_DIR_ITEMS, default='BOTH')
    rot_axis: bpy.props.EnumProperty(name="方向", items=_AXIS_ITEMS, default='RANDOM')
    rot_direction: bpy.props.EnumProperty(name="朝向", items=_DIR_ITEMS, default='BOTH')
    scale_mode: bpy.props.EnumProperty(name="缩放方式", items=_SCALE_ITEMS, default='RANDOM')

    random_seed: bpy.props.IntProperty(
        name="随机种子", default=0, min=0, max=9999,
        description="0 = 每次不同；非 0 则固定，方便复现同一版动画")
    clear_existing: bpy.props.BoolProperty(
        name="创建前先清除同通道旧动画", default=True,
        description="勾选则先删除（并烘焙）可见性/移动/旋转/缩放上的既有动画，"
                    "注意这是破坏性操作")


classes = (MF_PG_BuildingGrowthSettings,)


def register():
    utils.register_classes(classes)
    setattr(bpy.types.Scene, SCENE_ATTR,
            bpy.props.PointerProperty(type=MF_PG_BuildingGrowthSettings))


def unregister():
    delattr(bpy.types.Scene, SCENE_ATTR)
    utils.unregister_classes(classes)
