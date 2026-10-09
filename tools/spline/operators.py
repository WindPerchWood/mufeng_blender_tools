"""样条线子工具 · 操作符：业务逻辑放这里，UI 不要写算法。"""

import bpy

from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector, geometry

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

TOOL_ID = "Spline"
OP_ID_DRAW = "mf.spline_line"
OP_ID_CLOSE = "mf.spline_line_close"

STATE = {"active_tool": ""}

CURVE_NAME = "Line"
CLOSE_PIXELS = 10
BACKSPACE_LIMIT = 2

_close_answer = None


def _rv3d(ctx):
    rv3d = getattr(ctx, "region_data", None)
    if rv3d is None and ctx.space_data is not None:
        rv3d = ctx.space_data.region_3d
    return rv3d


def _plane_normal(ctx):
    rv3d = _rv3d(ctx)
    if rv3d is None or rv3d.view_perspective != 'ORTHO':
        return Vector((0.0, 0.0, 1.0))
    view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    axis = max(range(3), key=lambda i: abs(view_dir[i]))
    if axis == 2:
        return Vector((0.0, 0.0, 1.0))
    n = Vector((0.0, 0.0, 0.0))
    n[axis] = 1.0
    return n


def _floor_point(ctx, x, y):
    region = getattr(ctx, "region", None)
    rv3d = _rv3d(ctx)
    if region is None or rv3d is None:
        return Vector((0.0, 0.0, 0.0))
    normal = _plane_normal(ctx)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
    hit = geometry.intersect_line_plane(
        origin, origin + direction * 100000.0,
        Vector((0.0, 0.0, 0.0)), normal)
    if hit is not None:
        for i in range(3):
            if normal[i]:
                hit[i] = 0.0
        return hit
    return view3d_utils.region_2d_to_location_3d(
        region, rv3d, (x, y), Vector((0.0, 0.0, 0.0)))


def _to_screen(ctx, co):
    region = getattr(ctx, "region", None)
    rv3d = _rv3d(ctx)
    if region is None or rv3d is None:
        return None
    return view3d_utils.location_3d_to_region_2d(region, rv3d, co)


def _lock_axis(anchor, target):
    dx = abs(target.x - anchor.x)
    dy = abs(target.y - anchor.y)
    dz = abs(target.z - anchor.z)
    m = max(dx, dy, dz)
    if dx == m:
        return Vector((target.x, anchor.y, anchor.z))
    if dy == m:
        return Vector((anchor.x, target.y, anchor.z))
    return Vector((anchor.x, anchor.y, target.z))


def _corner_knot(co):
    return (co.copy(), co.copy(), co.copy(), 'VECTOR')


def _smooth_knot(co, handle):
    mirrored = co * 2.0 - handle
    return (co.copy(), mirrored, handle.copy(), 'ALIGNED')


def _apply_shape(curve, knots, closed):
    curve.splines.clear()
    spline = curve.splines.new('BEZIER')
    if knots:
        spline.bezier_points.add(len(knots) - 1)
        for bp, (co, hl, hr, ht) in zip(spline.bezier_points, knots):
            bp.co = co
            bp.handle_left = hl
            bp.handle_right = hr
            bp.handle_left_type = ht
            bp.handle_right_type = ht
    spline.use_cyclic_u = closed


def _link_active_collection(ctx, obj):
    layer = getattr(ctx.view_layer, "active_layer_collection", None)
    name = layer.name if layer else ""
    if name in {'Master Collection', 'Scene Collection', ''}:
        collection = ctx.scene.collection
    else:
        collection = bpy.data.collections.get(name) or ctx.scene.collection
    if collection not in obj.users_collection:
        collection.objects.link(obj)


def _create_curve_object(ctx):
    curve = bpy.data.curves.new(CURVE_NAME, type='CURVE')
    curve.dimensions = '3D'
    obj = bpy.data.objects.new(CURVE_NAME, curve)
    _link_active_collection(ctx, obj)
    for o in ctx.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    ctx.view_layer.objects.active = obj
    return obj


def _draw_cursor(op):
    import gpu
    from gpu_extras.batch import batch_for_shader

    x, y = op.mouse_xy
    s = 20.0
    t = 3.0
    coords = (
        (x - s, y - t * 0.5), (x + s, y - t * 0.5),
        (x + s, y + t * 0.5), (x - s, y + t * 0.5),
        (x - t * 0.5, y - s), (x + t * 0.5, y - s),
        (x + t * 0.5, y + s), (x - t * 0.5, y + s),
    )
    indices = ((0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=indices)
    shader.bind()
    shader.uniform_float("color", (0.8, 0.8, 0.8, 0.6))
    batch.draw(shader)


def _add_cursor(op):
    return bpy.types.SpaceView3D.draw_handler_add(
        _draw_cursor, (op,), 'WINDOW', 'POST_PIXEL')


def _remove_cursor(handle):
    if handle is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    except Exception:
        pass


class MF_OT_Spline_LineClose(Operator):
    bl_idname = OP_ID_CLOSE
    bl_label = "闭合样条线？"
    bl_description = "把首尾两点接起来，形成闭合曲线"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, _ctx):
        global _close_answer
        _close_answer = True
        return {'FINISHED'}

    def cancel(self, _ctx):
        global _close_answer
        _close_answer = False

    def invoke(self, ctx, event):
        return ctx.window_manager.invoke_confirm(self, event)


class MF_OT_Spline_Line(Operator):
    bl_idname = OP_ID_DRAW
    bl_label = "直线"
    bl_description = "连续点击落点画直线；按住左键拖动可拉出曲率；Shift 锁定单轴；Backspace 退点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        return ctx.mode == 'OBJECT'

    def invoke(self, ctx, event):
        if ctx.area is None or ctx.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        self.points = []
        self.obj = None
        self.closed = False
        self.pressed = False
        self.press_pos = None
        self.press_xy = None
        self.dragging = False
        self.shifting = False
        self.dialog_open = False
        self.mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        self.cursor_handle = None
        self._set_tool(ctx, "直线")
        self.cursor_handle = _add_cursor(self)
        ctx.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set_tool(self, ctx, text):
        STATE["active_tool"] = text

    def _target_point(self, ctx):
        pt = _floor_point(ctx, *self.mouse_xy)
        if self.shifting and self.points:
            pt = _lock_axis(self.points[-1][0], pt)
        return pt

    def _pending_knot(self, ctx):
        if self.press_pos is None or not self.dragging:
            return None
        return _smooth_knot(self.press_pos, self._target_point(ctx))

    def _refresh(self, ctx):
        if self.obj is None or self.closed:
            return
        knots = list(self.points)
        pending = self._pending_knot(ctx)
        if pending is not None:
            knots.append(pending)
        else:
            knots.append(_corner_knot(self._target_point(ctx)))
        _apply_shape(self.obj.data, knots, False)

    def _confirm(self, ctx):
        if self.obj is None:
            self.obj = _create_curve_object(ctx)
        if self.dragging:
            knot = self._pending_knot(ctx)
        else:
            knot = _corner_knot(self._target_point(ctx))
        self.points.append(knot)
        self.pressed = False
        self.press_pos = None
        self.press_xy = None
        self.dragging = False
        self._refresh(ctx)
        if len(self.points) >= 3:
            sp = _to_screen(ctx, self.points[0][0])
            if sp is not None:
                x, y = self.mouse_xy
                if abs(sp.x - x) < CLOSE_PIXELS and abs(sp.y - y) < CLOSE_PIXELS:
                    self._ask_close(ctx)

    def _ask_close(self, ctx):
        global _close_answer
        _close_answer = None
        self.dialog_open = True
        bpy.ops.mf.spline_line_close('INVOKE_DEFAULT')

    def _end(self, ctx):
        kept = self.obj is not None and len(self.points) >= 2
        if kept:
            _apply_shape(self.obj.data, list(self.points), self.closed)
            try:
                bpy.ops.object.origin_set(
                    type='ORIGIN_CENTER_OF_VOLUME', center='MEDIAN')
            except Exception:
                pass
            bpy.ops.ed.undo_push()
        elif self.obj is not None:
            bpy.data.objects.remove(self.obj, do_unlink=True)
            self.obj = None
        _remove_cursor(self.cursor_handle)
        self.cursor_handle = None
        self._set_tool(ctx, "")
        return kept

    def modal(self, ctx, event):
        if ctx.area is None:
            self._end(ctx)
            return {'CANCELLED'}
        ctx.area.tag_redraw()
        self.mouse_xy = (event.mouse_region_x, event.mouse_region_y)

        if self.dialog_open:
            answer = _close_answer
            if answer is None:
                return {'RUNNING_MODAL'}
            self.dialog_open = False
            if answer:
                self.closed = True
                if self.obj is not None:
                    _apply_shape(self.obj.data, list(self.points), True)
                    try:
                        bpy.ops.object.origin_set(
                            type='ORIGIN_CENTER_OF_VOLUME', center='MEDIAN')
                    except Exception:
                        pass
                    bpy.ops.ed.undo_push()
                _remove_cursor(self.cursor_handle)
                self.cursor_handle = None
                self._set_tool(ctx, "")
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'}:
            self.shifting = (event.value == 'PRESS')
            self._refresh(ctx)
        elif event.type == 'MOUSEMOVE':
            if self.pressed and self.press_pos is not None \
                    and self.mouse_xy != self.press_xy:
                self.dragging = True
            self._refresh(ctx)
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.pressed = True
                self.press_pos = _floor_point(ctx, *self.mouse_xy)
                self.press_xy = self.mouse_xy
                self.dragging = False
            elif event.value == 'RELEASE' and self.press_pos is not None:
                self._confirm(ctx)
        elif event.type == 'BACK_SPACE':
            if event.value == 'RELEASE' and len(self.points) > BACKSPACE_LIMIT:
                self.points.pop()
                self._refresh(ctx)
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._end(ctx)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


classes = (MF_OT_Spline_LineClose, MF_OT_Spline_Line)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
