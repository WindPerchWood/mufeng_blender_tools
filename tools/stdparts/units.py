

MM_PER_METER = 1000.0

UNIT_TO_MM = {
    'MM': 1.0,
    'CM': 10.0,
    'M': 1000.0,
    'IN': 25.4,
}

UNIT_ITEMS = [
    ('MM', "毫米 (mm)", "以毫米为输入单位"),
    ('CM', "厘米 (cm)", "以厘米为输入单位"),
    ('M', "米 (m)", "以米为输入单位"),
    ('IN', "英寸 (in)", "以英寸为输入单位"),
]

LENGTH_MODE_ITEMS = [
    ('SCENE', "按场景真实尺寸",
     "换算到场景真实尺度：模型量出来的长度就等于输入的毫米数（推荐，1:1 精确）"),
    ('DIRECT', "1 毫米 = 1 单位",
     "不做换算：输入 20 毫米就得到 20 个 Blender 单位。适合当独立零件使用"),
]


def unit_to_mm(value, unit='MM'):
    """把界面输入值换算成毫米。"""
    return float(value) * UNIT_TO_MM.get(unit, 1.0)


def mm_to_blender(mm, scale_length=1.0):
    """毫米 -> Blender 单位（真实尺度）。"""
    scale = float(scale_length) or 1.0
    return float(mm) * 0.001 / scale


def blender_to_mm(bu, scale_length=1.0):
    """Blender 单位 -> 毫米（真实尺度）。"""
    scale = float(scale_length) or 1.0
    return float(bu) * scale * MM_PER_METER


def to_blender(value, unit='MM', mode='SCENE', scale_length=1.0):
    """界面输入值 -> 建模用的 Blender 单位长度。"""
    mm = unit_to_mm(value, unit)
    if mode == 'DIRECT':
        return mm
    return mm_to_blender(mm, scale_length)


def from_blender(bu, unit='MM', mode='SCENE', scale_length=1.0):
    """建模用的 Blender 单位长度 -> 界面单位值（用于回显）。"""
    if mode == 'DIRECT':
        mm = float(bu)
    else:
        mm = blender_to_mm(bu, scale_length)
    return mm / UNIT_TO_MM.get(unit, 1.0)


def scene_scale_length(context):
    """安全读取当前场景的 scale_length。"""
    try:
        return float(context.scene.unit_settings.scale_length) or 1.0
    except Exception:
        return 1.0


def fmt_mm(value_mm, digits=3):
    """把毫米值格式化成人看的字符串。"""
    try:
        v = float(value_mm)
    except Exception:
        return "-"
    s = ("%%.%df" % int(digits)) % v
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s
