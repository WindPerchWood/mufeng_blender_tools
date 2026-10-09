import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, PointerProperty, StringProperty,
)
from bpy.types import PropertyGroup

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

from . import plan as P


SCENE_ATTR = "mf_floor_growth"


TARGET_MODES = (
    ('SELECTED',   "选中物体",   "处理当前选中的物体"),
    ('COLLECTION', "整个集合",   "处理指定集合下的所有物体"),
    ('PREFIX',     "按名称前缀", "处理名称以指定前缀开头的物体"),
    ('MARKED',     "上次生成的", "只处理带本工具标记的物体"),
)

ORIGIN_MODES = (
    ('CURSOR', "3D游标",     "以 3D 游标为传播起点"),
    ('OBJECT', "指定物体",   "以某个物体的原点为传播起点"),
    ('CENTER', "包围盒中心", "以所有目标物体的包围盒中心为起点"),
    ('CORNER', "包围盒角点", "以所有目标物体的最小角点为起点"),
)

SPREAD_ITEMS = (
    (P.SPREAD_DISTANCE, "距离扩散", "从起点向四周辐射，越远越晚"),
    (P.SPREAD_AXIS_X,   "沿 +X",   "沿世界 +X 方向推进"),
    (P.SPREAD_AXIS_NX,  "沿 -X",   "沿世界 -X 方向推进"),
    (P.SPREAD_AXIS_Y,   "沿 +Y",   "沿世界 +Y 方向推进"),
    (P.SPREAD_AXIS_NY,  "沿 -Y",   "沿世界 -Y 方向推进"),
    (P.SPREAD_AXIS_Z,   "沿 +Z",   "沿世界 +Z 方向推进（自下而上）"),
    (P.SPREAD_AXIS_NZ,  "沿 -Z",   "沿世界 -Z 方向推进（自上而下）"),
    (P.SPREAD_VECTOR,   "自定义向量", "沿自定义方向向量推进"),
    (P.SPREAD_WAVE,     "波浪",     "按正弦叠加推进，形成波前"),
    (P.SPREAD_SPIRAL,   "螺旋",     "按极角绕起点旋转推进"),
    (P.SPREAD_RANDOM,   "随机",     "完全随机顺序触发"),
)

EASE_ITEMS = (
    (P.EASE_LINEAR, "线性", "匀速推进"),
    (P.EASE_IN,     "缓入", "开头慢、后面快"),
    (P.EASE_OUT,    "缓出", "开头快、后面慢"),
    (P.EASE_S,      "S 型", "两头慢、中间快（smoothstep）"),
)

APPEAR_ITEMS = (
    (P.APPEAR_SCALE, "缩放出现", "砖从 0 放大到 1"),
    (P.APPEAR_HIDE,  "隐藏出现", "砖由隐藏变为显示（更干脆）"),
    (P.APPEAR_NONE,  "直接翻转", "没有出现阶段，直接开始翻"),
)

FLIP_AXIS_ITEMS = (
    (P.AXIS_AUTO,   "自动",     "根据传播方向自动选择翻转轴"),
    (P.AXIS_X,      "绕 X 轴",  "绕物体本地 X 轴翻转"),
    (P.AXIS_Y,      "绕 Y 轴",  "绕物体本地 Y 轴翻转"),
    (P.AXIS_CUSTOM, "自定义轴", "绕自定义方向轴翻转"),
)

LIFT_ITEMS = (
    (P.LIFT_PARABOLA, "抛物线", "中间最高的抛物线抬起"),
    (P.LIFT_SINE,     "正弦",   "正弦式抬起"),
)

INTERP_ITEMS = (
    ('BEZIER',   "贝塞尔", "平滑缓动（默认）"),
    ('LINEAR',   "线性",   "匀速，机械感强"),
    ('CONSTANT', "常量",   "阶跃，硬切"),
)

CLEAR_SCOPE_ITEMS = (
    ('MARKED', "仅本工具生成的", "只清除带标记的物体"),
    ('TARGET', "当前目标",       "清除当前目标范围内的物体"),
)

WAVE_AXIS_ITEMS = (
    ('X', 'X 轴', '沿 X 轴波动'),
    ('Y', 'Y 轴', '沿 Y 轴波动'),
    ('Z', 'Z 轴', '沿 Z 轴波动'),
)


class MF_PG_FloorGrowthSettings(PropertyGroup):

    target_mode: EnumProperty(
        name="目标来源", items=TARGET_MODES, default='SELECTED',
        description="决定处理哪些物体")
    target_collection: PointerProperty(
        name="集合", type=bpy.types.Collection,
        description="目标模式为「整个集合」时使用")
    target_prefix: StringProperty(
        name="名称前缀", default="",
        description="目标模式为「按名称前缀」时使用，如 TILE_")

    origin_mode: EnumProperty(
        name="起点来源", items=ORIGIN_MODES, default='CENTER')
    origin_object: PointerProperty(
        name="起点物体", type=bpy.types.Object,
        description="起点模式为「指定物体」时使用")
    origin_offset: FloatVectorProperty(
        name="起点偏移", size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    spread_mode: EnumProperty(
        name="传播方式", items=SPREAD_ITEMS, default=P.SPREAD_DISTANCE)
    direction: FloatVectorProperty(
        name="方向向量", size=3, default=(1.0, 0.0, 0.0), subtype='DIRECTION')
    wave_axis: EnumProperty(
        name="波浪轴", items=WAVE_AXIS_ITEMS, default='Z')
    wave_period: FloatProperty(
        name="波浪周期", default=100.0, min=0.001, soft_max=1000.0,
        description="波浪一个完整周期对应的世界单位")
    random_seed: IntProperty(
        name="随机种子", default=0, min=0)
    ease_mode: EnumProperty(
        name="节奏曲线", items=EASE_ITEMS, default=P.EASE_LINEAR)
    jitter: FloatProperty(
        name="随机抖动", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="在传播顺序上叠加随机偏移，让节奏更自然")

    start_frame: IntProperty(
        name="起始帧", default=1, min=0)
    spread_frames: IntProperty(
        name="蔓延跨度", default=120, min=1, soft_max=2000,
        description="从第一块到最后一块的触发间隔（帧）")
    per_tile_frames: IntProperty(
        name="单块翻转时长", default=6, min=1, soft_max=120,
        description="每块砖完成翻转所用的帧数")

    appear_mode: EnumProperty(
        name="出现方式", items=APPEAR_ITEMS, default=P.APPEAR_SCALE)
    appear_frames: IntProperty(
        name="出现时长", default=0, min=0, soft_max=120,
        description="从出现开始到完全显示所用的帧数（0 表示瞬间出现）")
    gap_after_appear: IntProperty(
        name="出现后停顿", default=0, min=0, soft_max=120,
        description="出现完成后，隔多少帧再开始翻转")

    flip_angle: FloatProperty(
        name="翻转角度", default=90.0, min=-360.0, max=360.0, subtype='ANGLE',
        description="每块砖翻转的角度")
    flip_axis: EnumProperty(
        name="翻转轴", items=FLIP_AXIS_ITEMS, default=P.AXIS_AUTO)
    custom_axis: FloatVectorProperty(
        name="自定义轴", size=3, default=(1.0, 0.0, 0.0), subtype='DIRECTION')
    lift_height: FloatProperty(
        name="翻滚抬起", default=0.0, min=0.0, soft_max=5.0, subtype='DISTANCE',
        description="翻转过程中向上抬起的高度，做出「滚动」而非「转动」的感觉")
    lift_mode: EnumProperty(
        name="抬起曲线", items=LIFT_ITEMS, default=P.LIFT_PARABOLA)
    use_bounce: BoolProperty(
        name="结束回弹", default=False,
        description="翻到位后轻微回弹再归位，增加弹性感")
    bounce_amount: FloatProperty(
        name="回弹量", default=0.12, min=0.0, max=0.9, subtype='FACTOR')

    interpolate: EnumProperty(
        name="插值方式", items=INTERP_ITEMS, default='BEZIER')
    auto_clear_before: BoolProperty(
        name="生成前先清除", default=True,
        description="重跑时先清掉上一次生成的关键帧，避免叠加")
    clear_scope: EnumProperty(
        name="清除范围", items=CLEAR_SCOPE_ITEMS, default='MARKED')

    use_baking: BoolProperty(
        name="烘焙模式（几何节点）", default=False,
        description="砖数很多时改用几何节点承载时序：一个点云 + 一个修改器，"
                    "零关键帧开销，几千块砖也能实时拖动时间轴。\n"
                    "注意：原砖会被隐藏，改由几何节点实例化")
    baking_threshold: IntProperty(
        name="烘焙阈值", default=1000, min=100, soft_max=20000,
        description="砖数超过此值时建议切换到烘焙模式（不强制）")
    baking_realize: BoolProperty(
        name="实体化实例", default=True,
        description="开启：几何真正生成（可再编辑/导出/被下游读取），但几千块砖占内存；\n"
                    "关闭：保持实例化，省内存、渲染一样正常，但不能在编辑模式里改单块")
    baking_keep_source: BoolProperty(
        name="保留原砖", default=False,
        description="烘焙后不隐藏原始砖物体（一般不勾，否则会和实例重叠）")
    baking_auto_hint: BoolProperty(
        name="超阈值自动切烘焙", default=True,
        description="目标数量超过「烘焙阈值」时，生成前自动切到烘焙模式")


classes = (MF_PG_FloorGrowthSettings,)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    setattr(bpy.types.Scene, SCENE_ATTR, PointerProperty(
        type=MF_PG_FloorGrowthSettings,
        name="地板生长设置",
        description="地砖逐个翻滚生长的动画参数",
    ))


def unregister():
    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    utils.unregister_classes(classes)
