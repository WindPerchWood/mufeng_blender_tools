
import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from . import core
from . import units
from .operators import (
    OP_ADD,
    OP_COPY_TO_DRAFT,
    OP_PRESET_BEARING,
    OP_PRESET_CHAIN,
    OP_PRESET_GEAR_MODULE,
    OP_PRESET_SPRING_WIRE,
    OP_REBUILD,
    OP_RESET,
    OP_TOGGLE_PANEL,
)

_INFO_ROWS = {
    'SPUR_GEAR': [
        ('pitch_dia', "分度圆直径", True),
        ('tip_dia', "齿顶圆直径", True),
        ('root_dia', "齿根圆直径", True),
        ('base_dia', "基圆直径", True),
        ('module_normal', "法面模数", True),
        ('tooth_height', "全齿高", True),
        ('width', "齿宽", True),
        ('pressure_angle_transverse_deg', "端面压力角", False),
    ],
    'HELICAL_GEAR': [
        ('pitch_dia', "分度圆直径", True),
        ('tip_dia', "齿顶圆直径", True),
        ('root_dia', "齿根圆直径", True),
        ('module_transverse', "端面模数", True),
        ('lead', "导程", True),
        ('helix_deg', "螺旋角", False),
        ('width', "齿宽", True),
        ('twist_total_deg', "总扭转角", False),
    ],
    'SPRING': [
        ('outer_dia', "外径 D", True),
        ('mean_dia', "中径 D₂", True),
        ('inner_dia', "内径 D₁", True),
        ('wire_dia', "线径 d", True),
        ('free_height', "自由高度 H", True),
        ('turns_total', "总圈数 n₁", False),
        ('pitch', "节距 p", True),
        ('helix_deg', "螺旋升角", False),
        ('spring_index', "弹簧指数 D₂/d", False),
    ],
    'BEARING': [
        ('bore_dia', "内径 d", True),
        ('outer_dia', "外径 D", True),
        ('width', "宽度 B", True),
        ('ball_dia', "钢球直径 D_w", True),
        ('ball_circle_dia', "球组分布圆直径", True),
        ('ball_gap', "相邻球间隙", True),
        ('balls', "球数 Z", False),
        ('ring_thickness', "圈壁厚", True),
    ],
    'CHAIN': [
        ('pitch', "节距 p", True),
        ('links', "节数", False),
        ('length', "链条总长（节距×节数）", True),
        ('ring_dia', "环形直径", True),
        ('roller_dia', "滚子直径 d₁", True),
        ('inner_width', "内链节内宽 b₁", True),
        ('plate_height', "链板高", True),
        ('pin_dia', "销轴直径", True),
    ],
}

_FMT = {
    'SPUR_GEAR': {'pressure_angle_transverse_deg': "%.2f°"},
    'HELICAL_GEAR': {'helix_deg': "%.2f°", 'twist_total_deg': "%.2f°"},
    'SPRING': {'helix_deg': "%.2f°", 'turns_total': "%.2f", 'spring_index': "%.3f"},
    'BEARING': {'balls': "%d"},
    'CHAIN': {'links': "%d"},
}


def _conv(info, value):
    """把 Blender 单位长度换回用户界面单位。"""
    return units.from_blender(value, info.get('unit', 'MM'),
                              info.get('length_mode', 'SCENE'),
                              float(info.get('scale_length', 1.0) or 1.0))


def _suffix(info):
    return {'MM': " mm", 'CM': " cm", 'M': " m", 'IN': " in"}.get(info.get('unit', 'MM'), "")


def type_label(ident):
    """标准件类型的可读名称。"""
    for key, label, _desc in core.PART_TYPE_ITEMS:
        if key == ident:
            return label
    return ident


def draw_dimensions(layout, info, stats=True):
    """特征尺寸 + 警告 + 网格统计。草稿预览与对象信息都走这里。"""
    if info.get('error'):
        box = layout.box()
        box.alert = True
        box.label(text="参数不合法：", icon='ERROR')
        for line in str(info['error']).splitlines()[:4]:
            box.label(text=line)
        return

    warn = info.get('warning')
    if warn:
        box = layout.box()
        box.alert = True
        box.label(text=warn, icon='ERROR')

    if info.get('pointed_tip'):
        box = layout.box()
        box.alert = True
        box.label(text="齿数偏少：齿顶已收缩为尖点", icon='ERROR')

    t = info.get('part_type', 'SPUR_GEAR')
    suffixes = _suffix(info)
    hints = _FMT.get(t, {})

    col = layout.column(align=True)
    shown = 0
    for key, label, is_len in _INFO_ROWS.get(t, []):
        val = info.get(key)
        if val is None or isinstance(val, (list, tuple)):
            continue
        fmt = hints.get(key)
        if fmt:
            text = fmt % val
        elif is_len:
            text = units.fmt_mm(_conv(info, val), 4) + suffixes
        else:
            text = str(val)
        col.label(text="%s：%s" % (label, text))
        shown += 1
    if not shown:
        col.label(text="（暂无尺寸）", icon='INFO')

    if stats:
        box = layout.box()
        box.label(text="网格", icon='MESH_DATA')
        b = info.get('bbox_size')
        if b:
            box.label(text="外廓：%s × %s × %s%s" % (
                units.fmt_mm(_conv(info, b[0]), 4), units.fmt_mm(_conv(info, b[1]), 4),
                units.fmt_mm(_conv(info, b[2]), 4), suffixes))
        box.label(text="顶点 %s ／ 面 %s" % (info.get('vert_count', '-'),
                                             info.get('face_count', '-')))


def draw_preset_row(layout, props, op_idname, enum_name, use_draft, apply_text="套用"):
    """一行预设：左边选规格，右边套用。use_draft 决定套到草稿还是选中对象。"""
    row = layout.row(align=True)
    row.prop(props, enum_name, text="")
    op = row.operator(op_idname, text=apply_text)
    op.use_draft = use_draft


def draw_presets(layout, props, use_draft):
    """按标准件类型给出对应的国标预设行。"""
    t = props.part_type
    box = layout.box()
    box.label(text="标准规格（公开国标公称尺寸）", icon='PRESET')
    if t in ('SPUR_GEAR', 'HELICAL_GEAR'):
        draw_preset_row(box, props, OP_PRESET_GEAR_MODULE,
                        "preset_gear_module", use_draft, "套用模数")
    elif t == 'SPRING':
        draw_preset_row(box, props, OP_PRESET_SPRING_WIRE,
                        "preset_spring_wire", use_draft, "套用线径")
    elif t == 'BEARING':
        draw_preset_row(box, props, OP_PRESET_BEARING,
                        "preset_bearing", use_draft, "套用规格")
    elif t == 'CHAIN':
        draw_preset_row(box, props, OP_PRESET_CHAIN,
                        "preset_chain", use_draft, "套用规格")


def draw_params(layout, p):
    """参数区。草稿面板与对象面板共用。"""
    t = p.part_type

    if t in ('SPUR_GEAR', 'HELICAL_GEAR'):
        box = layout.box()
        box.label(text="齿轮参数", icon='MESH_CIRCLE')
        col = box.column(align=True)
        col.prop(p, "gear_module")
        col.prop(p, "gear_teeth")
        col.prop(p, "gear_pressure")
        if t == 'HELICAL_GEAR':
            col.prop(p, "gear_helix")
        col.prop(p, "gear_width")
        col.prop(p, "gear_shift")

        box = layout.box()
        box.label(text="轴孔与键槽", icon='MOD_BOOLEAN')
        col = box.column(align=True)
        col.prop(p, "gear_bore")
        sub = col.column(align=True)
        sub.enabled = p.gear_bore > 0.0
        sub.prop(p, "gear_keyway_w")
        sub.prop(p, "gear_keyway_h")

        box = layout.box()
        box.label(text="精度", icon='MOD_DISPLACE')
        box.prop(p, "gear_inv_seg")

    elif t == 'SPRING':
        box = layout.box()
        box.label(text="弹簧参数", icon='MOD_SCREW')
        col = box.column(align=True)
        col.prop(p, "spring_outer")
        col.prop(p, "spring_wire")
        col.prop(p, "spring_turns")
        col.prop(p, "spring_height")
        col.prop(p, "spring_hand")
        col.prop(p, "spring_end")

        box = layout.box()
        box.label(text="精度", icon='MOD_DISPLACE')
        col = box.column(align=True)
        col.prop(p, "spring_path_seg")
        col.prop(p, "spring_ring_seg")

    elif t == 'BEARING':
        box = layout.box()
        box.label(text="轴承参数", icon='MESH_TORUS')
        col = box.column(align=True)
        col.prop(p, "brg_bore")
        col.prop(p, "brg_outer")
        col.prop(p, "brg_width")
        col.prop(p, "brg_balls")
        col.prop(p, "brg_ball_dia")
        col.prop(p, "brg_ring")

        box = layout.box()
        box.label(text="精度", icon='MOD_DISPLACE')
        box.prop(p, "brg_seg")

    elif t == 'CHAIN':
        box = layout.box()
        box.label(text="链条参数", icon='MOD_ARRAY')
        col = box.column(align=True)
        col.prop(p, "chain_pitch")
        col.prop(p, "chain_links")
        col.prop(p, "chain_layout")
        col.prop(p, "chain_roller", text="滚子直径 d₁")
        col.prop(p, "chain_width", text="内宽 b₁")
        col.prop(p, "chain_plate_h", text="链板高")
        col.prop(p, "chain_plate_t", text="链板厚")


def draw_panel_title(layout, label, panel, is_open):
    row = layout.row(align=True)
    row.alignment = 'LEFT'
    op = row.operator(OP_TOGGLE_PANEL,
                      text=label,
                      icon='DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT',
                      emboss=False)
    op.panel = panel


class MF_PT_StdParts(utils.MF_ToolPanel):

    bl_idname = "MF_PT_StdParts"
    bl_label = "标准件生成器"
    bl_description = "先把参数调好（尺寸实时算出来），再点一键生成"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 15
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("bzj", "stdparts", "标准件", "齿轮", "弹簧", "轴承", "链条")

    def draw_header(self, context):
        self.layout.label(text="", icon='MESH_CIRCLE')

    def draw(self, context):
        layout = self.layout
        self._section(layout, core.PANEL_BUILD, context, self._draw_build)
        if core.active_stdpart(context) is None:
            return
        self._section(layout, core.PANEL_PARAMS, context, self._draw_params)
        self._section(layout, core.PANEL_INFO, context, self._draw_info)

    @staticmethod
    def _section(layout, panel, context, draw_content):
        """一段可收展区：先画标题行，展开着才画内容。"""
        is_open = core.panel_is_open(context, panel)
        draw_panel_title(layout, core.PANEL_LABELS[panel], panel, is_open)
        if is_open:
            draw_content(layout, context)

    def _draw_build(self, layout, context):
        p = core.draft(context)
        if p is None:
            layout.label(text="参数区不可用，请重新启用插件", icon='ERROR')
            return

        col = layout.column(align=True)
        col.prop(p, "part_type", text="")

        row = layout.row(align=True)
        row.prop(p, "unit", text="")
        row.prop(p, "length_mode", text="")

        draw_params(layout, p)
        draw_presets(layout, p, use_draft=True)

        box = layout.box()
        box.label(text="生成后的尺寸（实时预览）", icon='DRIVER_DISTANCE')
        draw_dimensions(box, core.preview_info(p, context), stats=True)

        row = layout.row()
        row.scale_y = 1.5
        row.operator(OP_ADD, text="一键生成", icon='ADD').use_draft = True

        col = layout.column(align=True)
        col.label(text="生成后不会自动选中物体，本段也会自动收起", icon='INFO')
        col.label(text="点一下模型，②③ 两段才会出现")

    def _draw_params(self, layout, context):
        obj = core.active_stdpart(context)
        if obj is None:
            return
        p = obj.mf_stdparts

        box = layout.box()
        box.label(text=obj.name, icon='OBJECT_DATA')
        box.label(text="标准件类型：%s（不可更改）" % type_label(p.part_type))

        row = layout.row(align=True)
        row.prop(p, "unit", text="")
        row.prop(p, "length_mode", text="")

        draw_params(layout, p)
        draw_presets(layout, p, use_draft=False)

        row = layout.row(align=True)
        row.operator(OP_REBUILD, icon='FILE_REFRESH')
        row.operator(OP_RESET, icon='LOOP_BACK')
        layout.operator(OP_COPY_TO_DRAFT, icon='COPYDOWN',
                        text="把当前参数存为新建默认值")

    def _draw_info(self, layout, context):
        obj = core.active_stdpart(context)
        if obj is None:
            return
        draw_dimensions(layout, core.read_info(obj), stats=True)


classes = (
    MF_PT_StdParts,
)


def _menu_add(self, context):
    self.layout.separator()
    for ident, label, _desc in core.PART_TYPE_ITEMS:
        op = self.layout.operator(OP_ADD, text=label, icon='MESH_DATA')
        op.part_type = ident
        op.use_draft = False


def register():
    utils.register_classes(classes)
    bpy.types.VIEW3D_MT_add.append(_menu_add)


def unregister():
    try:
        bpy.types.VIEW3D_MT_add.remove(_menu_add)
    except Exception:
        pass
    utils.unregister_classes(classes)
