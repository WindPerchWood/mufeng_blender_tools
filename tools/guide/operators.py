import bpy
import gpu

from gpu_extras.batch import batch_for_shader
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.view3d_utils import location_3d_to_region_2d

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

TOOL_ID = "Guide"
OP_NOTIFY = "mf.guide_notify"

MSG_NOT_CAMERA = "构图辅助线只在相机视图里显示：按数字键盘 0 切到相机视图"
MSG_BLOCKED = "构图辅助线只在相机视图里显示，已保持关闭：按数字键盘 0 切到相机视图"
WM_ATTR = "mf_guide"

GOLDEN_A = 0.3819660112501051
GOLDEN_B = 0.6180339887498949

DEFAULT_MODE = 'THIRDS'
DEFAULT_COLOR = (1.0, 0.862745, 0.0, 1.0)
DEFAULT_WIDTH = 1.5

MODE_ITEMS = (
    ('THIRDS', "三分法", "在 1/3、2/3 处画井字线"),
    ('GOLDEN', "黄金分割法", "在 0.382、0.618 处画黄金分割线"),
    ('SQUARE', "开方构图法", "画内接居中正方形的边（Blender 无原生对应）"),
    ('CENTER', "中分法", "画水平、垂直中线"),
    ('DIAGONAL', "对角线构图法", "画两条对角线"),
    ('TRIANGLE', "三角构图法", "画两条对角线 + 水平中线"),
)

OVERLAY_MODE = 'WINDOW'
OVERLAY_REGION = 'POST_PIXEL'
CAMERA_VIEW = 'CAMERA'


def guide_segments(mode, w, h):
    w = float(w)
    h = float(h)
    segs = []

    if mode == 'GOLDEN':
        x1, x2 = w * GOLDEN_A, w * GOLDEN_B
        y1, y2 = h * GOLDEN_A, h * GOLDEN_B
        segs += [(x1, 0.0, x1, h), (x2, 0.0, x2, h)]
        segs += [(0.0, y1, w, y1), (0.0, y2, w, y2)]

    elif mode == 'SQUARE':
        if w >= h:
            left = (w - h) / 2.0
            right = left + h
            segs += [(left, 0.0, left, h), (right, 0.0, right, h)]
            segs += [(left, 0.0, right, 0.0), (left, h, right, h)]
        else:
            bottom = (h - w) / 2.0
            top = bottom + w
            segs += [(0.0, bottom, w, bottom), (0.0, top, w, top)]
            segs += [(0.0, bottom, 0.0, top), (w, bottom, w, top)]

    elif mode == 'CENTER':
        segs += [(w / 2.0, 0.0, w / 2.0, h), (0.0, h / 2.0, w, h / 2.0)]

    elif mode == 'DIAGONAL':
        segs += [(0.0, 0.0, w, h), (0.0, h, w, 0.0)]

    elif mode == 'TRIANGLE':
        segs += [(0.0, 0.0, w, h), (0.0, h, w, 0.0), (0.0, h / 2.0, w, h / 2.0)]

    else:
        x1, x2 = w / 3.0, w * 2.0 / 3.0
        y1, y2 = h / 3.0, h * 2.0 / 3.0
        segs += [(x1, 0.0, x1, h), (x2, 0.0, x2, h)]
        segs += [(0.0, y1, w, y1), (0.0, y2, w, y2)]

    return segs


def render_size(scene):
    r = scene.render
    k = r.resolution_percentage / 100.0
    w = abs(r.resolution_x * k * r.pixel_aspect_x)
    h = abs(r.resolution_y * k * r.pixel_aspect_y)
    return (max(w, 1.0), max(h, 1.0))


def fit_rect(vw, vh, tw, th):
    vw = float(vw)
    vh = float(vh)
    if vw <= 0.0 or vh <= 0.0 or tw <= 0.0 or th <= 0.0:
        return (0.0, 0.0, max(vw, 0.0), max(vh, 0.0))

    target_aspect = float(tw) / float(th)
    view_aspect = vw / vh

    if view_aspect > target_aspect:
        w = vh * target_aspect
        return ((vw - w) / 2.0, 0.0, w, vh)
    h = vw / target_aspect
    return (0.0, (vh - h) / 2.0, vw, h)


def build_line_coords(segments, rect):
    rx, ry, rw, rh = rect
    out = []
    for x1, y1, x2, y2 in segments:
        out.append((rx + x1, ry + rh - y1))
        out.append((rx + x2, ry + rh - y2))
    return out


def camera_frame_rect(region, region_3d, scene, camera_obj=None):
    if camera_obj is None:
        camera_obj = getattr(scene, "camera", None)
    if camera_obj is None:
        return None

    cam_data = getattr(camera_obj, "data", None)
    if cam_data is None:
        return None

    try:
        corners = cam_data.view_frame(scene=scene)
    except Exception:
        return None
    if not corners:
        return None

    mw = camera_obj.matrix_world
    xs = []
    ys = []
    for co in corners:
        pt = location_3d_to_region_2d(region, region_3d, mw @ co)
        if pt is None:
            return None
        xs.append(pt.x)
        ys.append(pt.y)

    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if (x1 - x0) <= 1.0 or (y1 - y0) <= 1.0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def frame_rect(region, region_3d, scene, camera_obj=None):
    rect = camera_frame_rect(region, region_3d, scene, camera_obj)
    if rect is not None:
        return rect, True
    tw, th = render_size(scene)
    return fit_rect(region.width, region.height, tw, th), False


def is_camera_view(region_3d):
    return getattr(region_3d, "view_perspective", None) == CAMERA_VIEW


def in_view3d(context):
    try:
        return context.area is not None and context.area.type == 'VIEW_3D'
    except Exception:
        return False


def view_is_camera(context):
    try:
        space = context.space_data
    except Exception:
        return False
    if getattr(space, "type", None) != 'VIEW_3D':
        return False
    return is_camera_view(getattr(space, "region_3d", None))


def _notify(message, level='INFO'):
    op = getattr(bpy.ops.mf, OP_NOTIFY.split(".", 1)[1], None)
    if op is None:
        return
    try:
        op(message=message, level=level)
    except Exception:
        pass


def _tag_redraw(context=None):
    try:
        wm = (context or bpy.context).window_manager
    except Exception:
        return
    for win in wm.windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _on_prop_changed(self, context):
    _tag_redraw(context)


def _blocked(context):
    return in_view3d(context) and not view_is_camera(context)


_REVERTING = False


def _on_enabled_changed(self, context):
    global _REVERTING
    _tag_redraw(context)
    if _REVERTING or not self.enabled or not _blocked(context):
        return
    _REVERTING = True
    try:
        self.enabled = False
    finally:
        _REVERTING = False
    _tag_redraw(context)
    _notify(MSG_BLOCKED, 'WARNING')


def _on_mode_changed(self, context):
    _tag_redraw(context)
    if _blocked(context):
        _notify(MSG_NOT_CAMERA, 'INFO')


def _props():
    try:
        return getattr(bpy.context.window_manager, WM_ATTR, None)
    except Exception:
        return None


class MF_PG_GuideSettings(bpy.types.PropertyGroup):
    enabled: BoolProperty(
        name="启用构图线",
        description="在相机视图里叠加构图辅助线",
        default=False,
        update=_on_enabled_changed,
    )

    mode: EnumProperty(
        name="构图法",
        description="选择要叠加哪一种构图辅助线",
        items=MODE_ITEMS,
        default=DEFAULT_MODE,
        update=_on_mode_changed,
    )

    color: FloatVectorProperty(
        name="颜色",
        description="辅助线颜色",
        subtype='COLOR_GAMMA',
        size=4,
        min=0.0,
        max=1.0,
        default=DEFAULT_COLOR,
        update=_on_prop_changed,
    )

    line_width: FloatProperty(
        name="线宽",
        description="辅助线宽度。注意部分显卡驱动上限就是 1.0，调大可能无效",
        default=DEFAULT_WIDTH,
        min=1.0,
        max=8.0,
        soft_max=3.0,
        update=_on_prop_changed,
    )


class MF_OT_Guide_Notify(bpy.types.Operator):
    bl_idname = OP_NOTIFY
    bl_label = "构图辅助线提示"
    bl_description = "在状态栏提示：构图辅助线只在相机视图里显示"
    bl_options = {'INTERNAL'}

    message: StringProperty(name="提示内容", default="")
    level: EnumProperty(
        name="级别",
        items=[('INFO', "信息", ""), ('WARNING', "警告", "")],
        default='INFO',
    )

    def execute(self, context):
        self.report({self.level}, self.message or MSG_NOT_CAMERA)
        return {'FINISHED'}


_SHADER = None
_HANDLE = None
_ERROR_NOTIFIED = False


def _ensure_shader():
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _SHADER


def _drop_shader():
    global _SHADER
    _SHADER = None


def _draw_callback():
    global _ERROR_NOTIFIED

    try:
        ctx = bpy.context
        region = getattr(ctx, "region", None)
        space = getattr(ctx, "space_data", None)
        if region is None or space is None:
            return
        if getattr(space, "type", None) != 'VIEW_3D':
            return

        rv3d = getattr(space, "region_3d", None)
        if rv3d is None:
            return
        if not is_camera_view(rv3d):
            return
        if region.width <= 1 or region.height <= 1:
            return

        scene = getattr(ctx, "scene", None)
        if scene is None:
            return

        props = _props()
        if props is None or not props.enabled:
            return

        rect, _from_camera = frame_rect(
            region, rv3d, scene,
            camera_obj=getattr(space, "camera", None),
        )
        segs = guide_segments(props.mode, rect[2], rect[3])
        coords = build_line_coords(segs, rect)
        if not coords:
            return

        shader = _ensure_shader()
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})

        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(max(1.0, float(props.line_width)))
        try:
            shader.bind()
            shader.uniform_float("color", tuple(props.color))
            batch.draw(shader)
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set('NONE')

    except Exception as exc:
        _drop_shader()
        if not _ERROR_NOTIFIED:
            _ERROR_NOTIFIED = True
            utils.report("ERROR", f"构图辅助线绘制失败：{exc!r}")


def add_handler():
    global _HANDLE
    if _HANDLE is not None:
        return _HANDLE
    _HANDLE = bpy.types.SpaceView3D.draw_handler_add(
        _draw_callback, (), OVERLAY_MODE, OVERLAY_REGION
    )
    return _HANDLE


def remove_handler():
    global _HANDLE
    if _HANDLE is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, OVERLAY_MODE)
    except Exception:
        pass
    _HANDLE = None


classes = (
    MF_PG_GuideSettings,
    MF_OT_Guide_Notify,
)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_GuideSettings))

    add_handler()


def unregister():
    remove_handler()

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)

    utils.unregister_classes(classes)
