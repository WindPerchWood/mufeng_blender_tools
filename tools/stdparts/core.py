
import json

import bpy
import bmesh
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
)

from . import geom
from . import presets
from . import units

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

MESH_NAME_PREFIX = "MF_StdParts_"
INFO_KEY = "mf_stdparts_info"
PART_KEY = "mf_stdparts_part"

_SUSPEND = [False]


class suspend_rebuild:
    """with suspend_rebuild(): ... 期间不触发网格重建。"""

    def __enter__(self):
        _SUSPEND[0] = True
        return self

    def __exit__(self, *exc):
        _SUSPEND[0] = False
        return False


PART_TYPE_ITEMS = [
    ('SPUR_GEAR', "直齿轮", "渐开线直齿圆柱齿轮：模数 / 齿数 / 压力角 / 齿宽 / 孔径 / 键槽"),
    ('HELICAL_GEAR', "斜齿轮", "渐开线斜齿圆柱齿轮：在直齿基础上增加螺旋角"),
    ('CHAIN', "链条", "滚子链：环形闭环或直线段，节距 / 节数可调"),
    ('SPRING', "压缩弹簧", "圆柱螺旋压缩弹簧：圈数 / 线径 / 外径 / 自由高度 / 端部形式"),
    ('BEARING', "深沟球轴承", "内圈 + 外圈 + 钢球阵列：内径 / 外径 / 宽度 / 球数"),
]

PRESET_ITEMS = {
    'gear_module': presets.gear_module_items(),
    'spring_wire': presets.spring_wire_items(),
    'bearing': [(c, c, "d=%g  D=%g  B=%g" % v)
                for c, v in sorted(presets.BALL_BEARINGS.items())],
    'chain': [(c, c, "节距 %g  滚子 %g  内宽 %g" % (v[0], v[1], v[2]))
              for c, v in sorted(presets.ROLLER_CHAINS.items())],
}


def _upd(self, context):
    if _SUSPEND[0]:
        return
    obj = self.id_data
    if isinstance(obj, bpy.types.Object):
        refresh(obj, context)
    else:
        tag_redraw(context)


def tag_redraw(context=None):
    """请求重绘 3D 视图的侧栏（草稿参数改动时用）。后台模式下是空操作。"""
    try:
        ctx = context or bpy.context
        wm = ctx.window_manager
        if wm is None:
            return
        for win in wm.windows:
            screen = getattr(win, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


class MF_StdParts_Settings(bpy.types.PropertyGroup):
    """一个标准件的全部参数。挂在对象上，随对象保存。"""

    part_type: EnumProperty(
        name="标准件类型", items=PART_TYPE_ITEMS, default='SPRING',
        description="切换类型会立即用当前参数重新生成", update=_upd)

    unit: EnumProperty(
        name="输入单位", items=units.UNIT_ITEMS, default='MM',
        description="下面所有尺寸参数按这个单位输入", update=_upd)
    length_mode: EnumProperty(
        name="长度尺度", items=units.LENGTH_MODE_ITEMS, default='SCENE',
        description="如何把输入的毫米换算成 Blender 单位", update=_upd)

    gear_module: FloatProperty(
        name="模数 m", description="法面模数（毫米）。分度圆直径 = 模数 × 齿数 / cos(螺旋角)",
        default=2.0, min=0.05, soft_max=50.0, precision=4, update=_upd)
    gear_teeth: IntProperty(
        name="齿数 z", description="少于 17 齿（20° 压力角）会根切，仅提示不阻止",
        default=20, min=3, soft_max=200, update=_upd)
    gear_pressure: FloatProperty(
        name="压力角 α", description="常用 14.5° / 20° / 25°，标准值 20°",
        default=20.0, min=5.0, max=40.0, precision=2, subtype='ANGLE', unit='ROTATION', update=_upd)
    gear_helix: FloatProperty(
        name="螺旋角 β", description="0 = 直齿。8°~20° 为常用斜齿轮范围",
        default=15.0, min=-45.0, max=45.0, precision=2, subtype='ANGLE', unit='ROTATION', update=_upd)
    gear_width: FloatProperty(
        name="齿宽 B", default=10.0, min=0.1, soft_max=500.0, precision=4, update=_upd)
    gear_shift: FloatProperty(
        name="变位系数 x", description="0 为标准齿轮。正值可避免小齿数根切",
        default=0.0, min=-0.8, max=0.8, precision=3, update=_upd)
    gear_bore: FloatProperty(
        name="孔径 d₀", description="中心孔直径，0 表示不开孔",
        default=8.0, min=0.0, soft_max=500.0, precision=4, update=_upd)
    gear_keyway_w: FloatProperty(
        name="键槽宽 b", description="GB/T 1095 平键键槽宽度，0 表示不开键槽",
        default=0.0, min=0.0, soft_max=200.0, precision=3, update=_upd)
    gear_keyway_h: FloatProperty(
        name="键槽深 t", description="自孔壁向外的深度（毂槽深度）",
        default=0.0, min=0.0, soft_max=200.0, precision=3, update=_upd)
    gear_inv_seg: IntProperty(
        name="齿廓精度", description="单侧渐开线分段数，越大齿面越光滑",
        default=8, min=3, max=64, update=_upd)

    spring_outer: FloatProperty(
        name="外径 D", default=20.0, min=0.5, soft_max=1000.0, precision=3, update=_upd)
    spring_wire: FloatProperty(
        name="线径 d", default=1.5, min=0.05, soft_max=200.0, precision=3, update=_upd)
    spring_turns: FloatProperty(
        name="有效圈数 n", default=8.0, min=0.5, soft_max=500.0, precision=2, update=_upd)
    spring_height: FloatProperty(
        name="自由高度 H", description="弹簧总高（含线径）",
        default=40.0, min=0.2, soft_max=3000.0, precision=3, update=_upd)
    spring_hand: EnumProperty(
        name="旋向", items=[('RIGHT', "右旋", "顺时针上升"), ('LEFT', "左旋", "逆时针上升")],
        default='RIGHT', update=_upd)
    spring_end: EnumProperty(
        name="端部形式",
        items=[('OPEN', "开口端", "两端不做处理，节距均匀"),
               ('CLOSED', "并紧端", "两端各一圈并紧，外形是平的（常用）")],
        default='CLOSED', update=_upd)
    spring_ring_seg: IntProperty(
        name="截面精度", description="钢丝圆截面的分段数",
        default=12, min=8, max=32, update=_upd)
    spring_path_seg: IntProperty(
        name="每圈分段", description="每一圈的分段数，越大越光滑",
        default=16, min=8, max=120, update=_upd)

    brg_bore: FloatProperty(
        name="内径 d", default=8.0, min=0.5, soft_max=2000.0, precision=3, update=_upd)
    brg_outer: FloatProperty(
        name="外径 D", default=22.0, min=0.6, soft_max=3000.0, precision=3, update=_upd)
    brg_width: FloatProperty(
        name="宽度 B", default=7.0, min=0.1, soft_max=500.0, precision=3, update=_upd)
    brg_balls: IntProperty(
        name="球数 Z", default=8, min=3, max=60, update=_upd)
    brg_ball_dia: FloatProperty(
        name="球径 D_w", description="0 = 按内、外径自动取",
        default=0.0, min=0.0, soft_max=200.0, precision=4, update=_upd)
    brg_ring: FloatProperty(
        name="圈厚", description="内、外圈壁厚，0 = 自动",
        default=0.0, min=0.0, soft_max=500.0, precision=3, update=_upd)
    brg_seg: IntProperty(
        name="圆周精度", default=72, min=16, max=360, update=_upd)

    chain_pitch: FloatProperty(
        name="节距 p", default=12.7, min=0.5, soft_max=200.0, precision=4, update=_upd)
    chain_links: IntProperty(
        name="节数", default=20, min=4, soft_max=2000, update=_upd)
    chain_layout: EnumProperty(
        name="布置形式", items=[('LINEAR', "直线", "沿 X 轴排开"), ('RING', "环形", "首尾相接成闭环")],
        default='LINEAR', update=_upd)
    chain_roller: FloatProperty(
        name="滚子直径 d₁", description="0 = 按节距自动取",
        default=0.0, min=0.0, soft_max=200.0, precision=4, update=_upd)
    chain_width: FloatProperty(
        name="内链节内宽 b₁", description="0 = 按节距自动取",
        default=0.0, min=0.0, soft_max=200.0, precision=4, update=_upd)
    chain_plate_t: FloatProperty(
        name="链板厚", description="0 = 按节距自动取",
        default=0.0, min=0.0, soft_max=100.0, precision=4, update=_upd)
    chain_plate_h: FloatProperty(
        name="链板高", description="0 = 按节距自动取",
        default=0.0, min=0.0, soft_max=200.0, precision=4, update=_upd)

    preset_gear_module: EnumProperty(
        name="标准模数", items=PRESET_ITEMS['gear_module'],
        default=presets.pick_default(PRESET_ITEMS['gear_module'], 2))
    preset_spring_wire: EnumProperty(
        name="标准线径", items=PRESET_ITEMS['spring_wire'],
        default=presets.pick_default(PRESET_ITEMS['spring_wire'], 1.5))
    preset_bearing: EnumProperty(
        name="轴承代号", items=PRESET_ITEMS['bearing'],
        default=presets.pick_default(PRESET_ITEMS['bearing'], "608"))
    preset_chain: EnumProperty(
        name="链条代号", items=PRESET_ITEMS['chain'],
        default=presets.pick_default(PRESET_ITEMS['chain'], "08A-1"))


def params_in_units(props, scale_length):
    """把界面参数换算成 Blender 单位，交给 geom。"""
    u = props.unit
    mode = props.length_mode

    def L(v):
        return units.to_blender(v, u, mode, scale_length)

    p = {}
    t = props.part_type

    if t in ('SPUR_GEAR', 'HELICAL_GEAR'):
        p.update({
            'module': L(props.gear_module),
            'teeth': int(props.gear_teeth),
            'pressure_deg': props.gear_pressure,
            'helix_deg': props.gear_helix if t == 'HELICAL_GEAR' else 0.0,
            'shift': props.gear_shift,
            'width': L(props.gear_width),
            'bore_d': L(props.gear_bore),
            'keyway_w': L(props.gear_keyway_w),
            'keyway_h': L(props.gear_keyway_h),
            'inv_seg': int(props.gear_inv_seg),
        })
    elif t == 'SPRING':
        p.update({
            'outer_dia': L(props.spring_outer),
            'wire_dia': L(props.spring_wire),
            'turns': props.spring_turns,
            'free_height': L(props.spring_height),
            'hand': props.spring_hand,
            'end_type': props.spring_end,
            'ring_seg': int(props.spring_ring_seg),
            'seg_per_turn': int(props.spring_path_seg),
        })
    elif t == 'BEARING':
        p.update({
            'bore_dia': L(props.brg_bore),
            'outer_dia': L(props.brg_outer),
            'width': L(props.brg_width),
            'balls': int(props.brg_balls),
            'ball_dia': L(props.brg_ball_dia),
            'ring_thickness': L(props.brg_ring),
            'seg': int(props.brg_seg),
        })
    elif t == 'CHAIN':
        p.update({
            'pitch': L(props.chain_pitch),
            'links': int(props.chain_links),
            'layout': props.chain_layout,
            'roller_dia': L(props.chain_roller),
            'inner_width': L(props.chain_width),
            'plate_thickness': L(props.chain_plate_t),
            'plate_height': L(props.chain_plate_h),
        })
    return p


def _shading_mode(part_type):
    if part_type in ('SPUR_GEAR', 'HELICAL_GEAR', 'BEARING'):
        return 'AXIS_Z'
    if part_type == 'SPRING':
        return 'ALL_SMOOTH'
    return 'FLAT'


def scene_scale(context=None):
    try:
        sc = (context.scene if context is not None else None) or bpy.context.scene
        if sc is not None:
            return float(sc.unit_settings.scale_length or 1.0)
    except Exception:
        pass
    return 1.0


def compute(props, context=None):
    part = props.part_type
    try:
        verts, faces, info = geom.build(part, params_in_units(props, scene_scale(context)))
    except Exception as exc:
        return [], [], {'error': "%s: %s" % (type(exc).__name__, exc), 'part_type': part}

    info = dict(info)
    info['part_type'] = part
    info['vert_count'] = len(verts)
    info['face_count'] = len(faces)
    if verts:
        lo, hi = geom.bounds(verts)
        info['bbox_min'] = lo
        info['bbox_max'] = hi
        info['bbox_size'] = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    info['scale_length'] = scene_scale(context)
    info['unit'] = props.unit
    info['length_mode'] = props.length_mode
    return verts, faces, info


def preview_info(props, context=None):
    """只要特征尺寸，不要网格 —— 给草稿参数的实时预览用。"""
    return compute(props, context)[2]


def copy_settings(src, dst):
    """把一套参数整体复制到另一套（新建时从草稿复制到新对象）。"""
    rna = dst.bl_rna.properties
    with suspend_rebuild():
        for key in list(rna.keys()):
            if key == 'rna_type':
                continue
            try:
                setattr(dst, key, getattr(src, key))
            except Exception:
                pass


def draft(context=None):
    """取当前场景上的「新建草稿参数」。未注册时返回 None。"""
    try:
        sc = (context.scene if context is not None else None) or bpy.context.scene
        return getattr(sc, 'mf_stdparts_draft', None) if sc is not None else None
    except Exception:
        return None


PANEL_BUILD = 'BUILD'
PANEL_PARAMS = 'PARAMS'
PANEL_INFO = 'INFO'

PANEL_ALL = 'ALL'

PANEL_OPEN_PROP = "mf_stdparts_create_open"

PANEL_OPEN_PROPS = {
    PANEL_BUILD: PANEL_OPEN_PROP,
    PANEL_PARAMS: "mf_stdparts_params_open",
    PANEL_INFO: "mf_stdparts_info_open",
}

PANEL_LABELS = {
    PANEL_BUILD: "① 标准件一键生成器",
    PANEL_PARAMS: "② 选中对象的参数（实时联动）",
    PANEL_INFO: "③ 选中对象的尺寸信息",
}


def _open_upd(self, context):
    tag_redraw(context)


def _is_one_open(context, panel):
    try:
        sc = (context.scene if context is not None else None) or bpy.context.scene
        return bool(getattr(sc, PANEL_OPEN_PROPS.get(panel, PANEL_OPEN_PROP), True))
    except Exception:
        return True


def panel_is_open(context, panel=PANEL_BUILD):
    keys = tuple(PANEL_OPEN_PROPS) if panel == PANEL_ALL else (panel,)
    return all(_is_one_open(context, key) for key in keys)


def _set_one_open(context, is_open, panel):
    try:
        sc = (context.scene if context is not None else None) or bpy.context.scene
        if sc is not None:
            setattr(sc, PANEL_OPEN_PROPS.get(panel, PANEL_OPEN_PROP), bool(is_open))
            tag_redraw(context)
            return True
    except Exception:
        pass
    return False


def set_panel_open(context, is_open, panel=PANEL_BUILD):
    """代码控制某块面板的展开/收起；传 PANEL_ALL 就是三块一起。返回是否全部设置成功。"""
    keys = tuple(PANEL_OPEN_PROPS) if panel == PANEL_ALL else (panel,)
    done = True
    for key in keys:
        done = _set_one_open(context, is_open, key) and done
    return done


def set_create_panel_open(context, is_open):
    """代码控制①面板的展开/收起（旧接口，等价于 set_panel_open(panel=PANEL_BUILD)）。"""
    return set_panel_open(context, is_open, PANEL_BUILD)


def make_mesh(name, verts, faces, part_type):
    """由 (verts, faces) 建立网格对象数据，并处理法线与着色。"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    mesh.validate(verbose=False, clean_customdata=False)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    if len(bm.faces):
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()

    mode = _shading_mode(part_type)
    if mode == 'FLAT':
        for poly in mesh.polygons:
            poly.use_smooth = False
    elif mode == 'ALL_SMOOTH':
        for poly in mesh.polygons:
            poly.use_smooth = True
    else:
        for poly in mesh.polygons:
            poly.use_smooth = abs(poly.normal.z) < 0.85

    mesh.update()
    return mesh


def refresh(obj, context=None):
    """按对象当前参数重建网格。返回 info 字典（失败时含 'error'）。"""
    props = obj.mf_stdparts if hasattr(obj, 'mf_stdparts') else None
    if props is None:
        return None

    verts, faces, info = compute(props, context)

    if verts:
        mesh = make_mesh(MESH_NAME_PREFIX + props.part_type, verts, faces, props.part_type)
        old = obj.data
        obj.data = mesh
        if old is not None and old.users == 0 and old is not mesh:
            try:
                bpy.data.meshes.remove(old)
            except Exception:
                pass

    obj[INFO_KEY] = json.dumps(info, ensure_ascii=False)
    obj[PART_KEY] = props.part_type
    return info


def read_info(obj):
    """读回上一次重建写入的特征尺寸。"""
    raw = obj.get(INFO_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def is_stdpart(obj):
    return isinstance(obj, bpy.types.Object) and hasattr(obj, 'mf_stdparts') \
        and obj.get(PART_KEY) is not None


def active_stdpart(context=None):
    try:
        ctx = context or bpy.context
        obj = ctx.active_object
        if not is_stdpart(obj):
            return None
        return obj if obj.select_get() else None
    except Exception:
        return None


CLASSES = (MF_StdParts_Settings,)


def register():
    utils.register_classes(CLASSES)
    bpy.types.Object.mf_stdparts = PointerProperty(type=MF_StdParts_Settings)
    bpy.types.Scene.mf_stdparts_draft = PointerProperty(type=MF_StdParts_Settings)
    for panel, name in PANEL_OPEN_PROPS.items():
        setattr(bpy.types.Scene, name, BoolProperty(
            name="展开「%s」" % PANEL_LABELS[panel],
            description="点标题栏上的折角切换；①在「一键生成」后会自动收起",
            default=True, update=_open_upd))


def unregister():
    holders = [(bpy.types.Scene, 'mf_stdparts_draft'),
               (bpy.types.Object, 'mf_stdparts')]
    holders += [(bpy.types.Scene, name) for name in PANEL_OPEN_PROPS.values()]
    for holder, name in holders:
        if hasattr(holder, name):
            delattr(holder, name)
    utils.unregister_classes(CLASSES)
