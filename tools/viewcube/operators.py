import bpy

from mathutils import Quaternion

from . import cube_overlay


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

TOOL_ID = "ViewCube"
OP_ID = f"mf.{TOOL_ID.lower()}_set"
PICK_ID = f"mf.{TOOL_ID.lower()}_pick"


def _view_quat(cam_dir):
    from mathutils import Vector, Matrix
    z = Vector(cam_dir).normalized()
    if abs(z[2]) > 0.9999:
        x = Vector((1.0, 0.0, 0.0))
    else:
        x = Vector((0.0, 0.0, 1.0)).cross(z)
    x.normalize()
    y = z.cross(x)
    m = Matrix.Identity(3)
    m.col[0] = x
    m.col[1] = y
    m.col[2] = z
    return m.to_quaternion()


VIEW_DIRS = cube_overlay.VIEW_DIRS
VIEW_QUATS = {key: _view_quat(direction) for key, (direction, _label) in VIEW_DIRS.items()}


_NAV = {"dragging": False, "last": None, "hit": None, "moved": 0.0, "area": None}


def _region_view3d(context):
    space = getattr(context, "space_data", None)
    if space is not None and getattr(space, "type", None) == 'VIEW_3D':
        return space.region_3d
    screen = getattr(context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                return area.spaces.active.region_3d
    return None


def _apply_view_to(rv3d, key):
    target = VIEW_QUATS.get(key)
    if target is None:
        return False
    if rv3d.view_perspective == 'CAMERA':
        rv3d.view_perspective = 'PERSP'
    rv3d.view_rotation = target
    try:
        rv3d.update()
    except Exception:
        pass
    return True


def _orbit(rv3d, dx, dy):
    s = 0.007
    qz = Quaternion((0.0, 0.0, 1.0), dx * s)
    qx = Quaternion((1.0, 0.0, 0.0), dy * s)
    rv3d.view_rotation = (qz @ rv3d.view_rotation @ qx).normalized()


def _pick_at(context, mx_win, my_win):
    for area in context.window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            mx = mx_win - region.x
            my = my_win - region.y
            inside = 0 <= mx < region.width and 0 <= my < region.height
            if inside:
                rv3d = area.spaces.active.region_3d
                return cube_overlay.hit_test(region, rv3d, mx, my), area
    return None, None


class MF_OT_ViewCube_Set(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "切换视图"
    bl_description = ("把 3D 视口切到指定方向；TOGGLE_ORTHO 切正交/透视，"
                      "OVERLAY_TOGGLE 开关右上角悬浮魔方")
    bl_options = {'REGISTER'}

    view_key: bpy.props.StringProperty(name="视图", default="FRONT")

    def execute(self, context):
        key = self.view_key

        if key == 'OVERLAY_TOGGLE':
            enable = not cube_overlay.is_enabled()
            cube_overlay.set_enabled(enable)
            for area in context.window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return {'FINISHED'}

        if key == 'TOGGLE_ORTHO':
            rv3d = _region_view3d(context)
            if rv3d is None:
                self.report({'WARNING'}, "没有找到 3D 视口")
                return {'CANCELLED'}
            rv3d.view_perspective = 'ORTHO' if rv3d.view_perspective != 'ORTHO' else 'PERSP'
            return {'FINISHED'}

        rv3d = _region_view3d(context)
        if rv3d is None:
            self.report({'WARNING'}, "没有找到 3D 视口")
            return {'CANCELLED'}
        if not _apply_view_to(rv3d, key):
            self.report({'WARNING'}, f"未知视图方向: {key}")
            return {'CANCELLED'}
        return {'FINISHED'}


class MF_OT_ViewCube_Pick(bpy.types.Operator):
    bl_idname = PICK_ID
    bl_label = "视图魔方点击/拖拽"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        hit, area = _pick_at(context, event.mouse_x, event.mouse_y)
        if hit is None:
            return {'CANCELLED'}
        cube_overlay.set_hover(hit)

        if event.type == 'LEFTMOUSE' and event.value in {'CLICK', 'DOUBLE_CLICK'}:
            self._apply(context, hit, area)
            return {'FINISHED'}

        _NAV.update(dragging=True, moved=0.0,
                    last=(event.mouse_x, event.mouse_y), hit=hit, area=area)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    @staticmethod
    def _apply(context, hit, area):
        if hit is None:
            return
        kind, key = hit
        if kind in {'FACE', 'EDGE', 'CORNER'} and key and area is not None:
            rv3d = area.spaces.active.region_3d
            if _apply_view_to(rv3d, key):
                cube_overlay.set_hover(None)
                area.tag_redraw()

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            area = _NAV["area"]
            if _NAV["dragging"] and area is not None and _NAV["last"]:
                dx = event.mouse_x - _NAV["last"][0]
                dy = event.mouse_y - _NAV["last"][1]
                _NAV["last"] = (event.mouse_x, event.mouse_y)
                _NAV["moved"] += abs(dx) + abs(dy)
                _orbit(area.spaces.active.region_3d, dx, dy)
                area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            hit = _NAV["hit"]
            area = _NAV["area"]
            if _NAV["moved"] < cube_overlay.CLICK_SLOP:
                self._apply(context, hit, area)
            _NAV.update(dragging=False, last=None, hit=None, moved=0.0, area=None)
            cube_overlay.set_hover(None)
            if area is not None:
                area.tag_redraw()
            return {'FINISHED'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            _NAV.update(dragging=False, last=None, hit=None, moved=0.0, area=None)
            cube_overlay.set_hover(None)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}


classes = (MF_OT_ViewCube_Set, MF_OT_ViewCube_Pick)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
