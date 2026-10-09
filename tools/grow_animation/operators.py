import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty
from mathutils import Vector
from mathutils.geometry import interpolate_bezier

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

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
except Exception:
    gpu = None
    batch_for_shader = None
    region_2d_to_origin_3d = None
    region_2d_to_vector_3d = None


TOOL_ID = "GrowAnimation"
WM_ATTR = "mf_growanim"

OP_VIS_KEY = "mf.growanim_vis_key"
OP_UNVIS_KEY = "mf.growanim_unvis_key"
OP_AXIS_SHIFT = "mf.growanim_axis_shift"
OP_PATH_SHIFT = "mf.growanim_path_shift"
OP_DRAW_PATH = "mf.growanim_draw_path"

PATH_NAME = "MF_生长路径"
AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}
FAR = 999999

_ALPHA_PATH = 'nodes["%s"].inputs[%d].default_value'
_REDRAW_AREAS = {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'TIMELINE'}
_HEADER = "生长路径：左键落点 / 回车或右键结束 / Esc 取消（落点投影到世界 Z=0 平面）"
_WARN_NO_KEY = "选中物体没有可移动的关键帧"
_WARN_NO_SEL_KEY = ("没有选中的关键帧可移动（先在摄影表/曲线编辑器里选键，"
                    "或关掉「仅移动选中帧」）")


def _get_props(context):
    return getattr(context.window_manager, WM_ATTR, None)


def _slot_pointer(anim):
    slot = getattr(anim, "action_slot", None)
    return slot.as_pointer() if slot is not None else 0


def _tag_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for win in wm.windows:
        screen = getattr(win, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type in _REDRAW_AREAS:
                area.tag_redraw()


def _refresh(context):
    try:
        context.scene.frame_set(context.scene.frame_current)
    except Exception:
        context.view_layer.update()
    _tag_redraw()


def _extend_frame_end(scene, last_frame):
    if last_frame is not None and last_frame > scene.frame_end:
        scene.frame_end = int(last_frame)
        return True
    return False


def _fade_api():
    try:
        from ..visibility import operators as vis_ops
    except Exception as exc:
        utils.report("ERROR", f"生长动画：载入「更改可见性」淡出逻辑失败（{exc}）")
        return None
    return vis_ops


def _has_material(obj):
    return any(slot.material is not None for slot in obj.material_slots)


def _key_alpha(obj, value, frame):
    vis = _fade_api()
    if vis is None:
        return 0, 0
    touched = vis.apply_fade(obj, value)
    uniq = {m.as_pointer(): m for m in touched}
    keys = 0
    for mat in uniq.values():
        node = vis._fade_node(mat)
        idx = vis.alpha_socket_index(node) if node is not None else None
        if idx is None or mat.node_tree is None:
            continue
        mat.node_tree.keyframe_insert(
            data_path=_ALPHA_PATH % (vis.FADE_NODE_NAME, idx), frame=frame)
        keys += 1
    return len(uniq), keys


def _key_hide(obj, hidden, frame):
    obj.hide_render = bool(hidden)
    obj.keyframe_insert('hide_render', frame=frame)


def _action_fcurves(anim):
    action = anim.action if anim is not None else None
    if action is None:
        return ()

    layers = getattr(action, "layers", None)
    if layers is None:
        return tuple(getattr(action, "fcurves", ()))

    slot = getattr(anim, "action_slot", None)
    slot_ptr = slot.as_pointer() if slot is not None else 0

    found = []
    for layer in layers:
        for strip in layer.strips:
            if getattr(strip, "type", "") != 'KEYFRAME':
                continue
            for bag in getattr(strip, "channelbags", ()):
                bag_slot = getattr(bag, "slot", None)
                if slot_ptr and bag_slot is not None \
                        and bag_slot.as_pointer() != slot_ptr:
                    continue
                found.extend(bag.fcurves)
    return tuple(found)


def _anim_sources(obj):
    raw = [obj.animation_data]

    data = getattr(obj, "data", None)
    if data is not None:
        raw.append(getattr(data, "animation_data", None))
        shape_keys = getattr(data, "shape_keys", None)
        if shape_keys is not None:
            raw.append(getattr(shape_keys, "animation_data", None))

    for slot in getattr(obj, "material_slots", ()):
        mat = slot.material
        if mat is None:
            continue
        raw.append(getattr(mat, "animation_data", None))
        node_tree = getattr(mat, "node_tree", None)
        if node_tree is not None:
            raw.append(getattr(node_tree, "animation_data", None))

    out = []
    seen = set()
    for anim in raw:
        if anim is None:
            continue
        ptr = anim.as_pointer()
        if ptr in seen:
            continue
        seen.add(ptr)
        out.append(anim)
    return out


def _collect_fcurves(obj, seen):
    groups = []
    for anim in _anim_sources(obj):
        action = anim.action
        if action is None:
            continue
        combo = (action.as_pointer(), _slot_pointer(anim))
        if combo in seen:
            continue
        seen.add(combo)
        groups.append((_action_fcurves(anim), anim.id_data))
    return groups


def _shift_fcurve(fcurve, delta, selected_only):
    moved = 0
    negative = 0
    max_x = None
    for kp in fcurve.keyframe_points:
        if selected_only and not kp.select_control_point:
            continue
        x, y = kp.co_ui
        x += delta
        kp.co_ui = (x, y)
        moved += 1
        if x < 0.0:
            negative += 1
        if max_x is None or x > max_x:
            max_x = x
    if moved:
        fcurve.update()
    return moved, negative, max_x


def _shift_object(obj, delta, selected_only, seen):
    moved = 0
    negative = 0
    max_x = None

    for fcurves, owner in _collect_fcurves(obj, seen):
        owner_keys = 0
        for fcurve in fcurves:
            hit, neg, top = _shift_fcurve(fcurve, delta, selected_only)
            owner_keys += hit
            negative += neg
            if top is not None and (max_x is None or top > max_x):
                max_x = top
        if owner_keys and owner is not obj:
            try:
                owner.update_tag()
            except Exception:
                pass
        moved += owner_keys

    return moved, negative, max_x


def _path_samples(path_obj):
    data = path_obj.data
    if not data.splines:
        return []
    spline = data.splines[0]
    points = []

    if spline.type == 'BEZIER':
        res = max(2, int(getattr(spline, "resolution_u", 12)) + 1)
        bps = spline.bezier_points
        count = len(bps)
        if count < 2:
            return []
        segments = count if spline.use_cyclic_u else count - 1
        for i in range(segments):
            b0 = bps[i]
            b1 = bps[(i + 1) % count]
            chunk = interpolate_bezier(b0.co, b0.handle_right, b1.handle_left, b1.co, res)
            if i:
                chunk = chunk[1:]
            points.extend(chunk)
    else:
        points = [Vector(p.co[:3]) for p in spline.points]
        if spline.use_cyclic_u and len(points) > 1:
            points.append(points[0].copy())

    if len(points) < 2:
        return []
    matrix = path_obj.matrix_world
    return [matrix @ p for p in points]


def _nearest_param(points, co):
    total = len(points) - 1
    if total <= 0:
        return 0.0

    best = None
    for k in range(total):
        a = points[k]
        b = points[k + 1]
        ab = b - a
        denom = ab.length_squared
        if denom <= 1e-12:
            ratio = 0.0
            proj = a
        else:
            ratio = (co - a).dot(ab) / denom
            ratio = 0.0 if ratio < 0.0 else (1.0 if ratio > 1.0 else ratio)
            proj = a + ab * ratio
        dist = (co - proj).length_squared
        if best is None or dist < best[0]:
            best = (dist, k, ratio)

    return (best[1] + best[2]) / total


def world_from_region(region, rv3d, mco):
    if region_2d_to_origin_3d is None:
        return None
    origin = region_2d_to_origin_3d(region, rv3d, mco)
    direction = region_2d_to_vector_3d(region, rv3d, mco)
    if abs(direction.z) < 1e-6:
        return None
    return origin + direction * (-origin.z / direction.z)


def make_path_object(context, points):
    curve = bpy.data.curves.new(PATH_NAME, 'CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.points[i].co = (p.x, p.y, p.z, 1.0)

    obj = bpy.data.objects.new(PATH_NAME, curve)
    collection = getattr(context, "collection", None) or context.scene.collection
    collection.objects.link(obj)
    return obj


def _path_poll(self, obj):
    return obj is not None and obj.type == 'CURVE'


class MF_PG_GrowAnimSettings(bpy.types.PropertyGroup):
    axis: EnumProperty(
        name="轴",
        description="按物体世界坐标原点在该轴上的数值排序后错帧",
        items=(('X', "X", "按世界 X 轴排序"),
               ('Y', "Y", "按世界 Y 轴排序"),
               ('Z', "Z", "按世界 Z 轴排序")),
        default='Z',
    )
    descending: BoolProperty(
        name="降序",
        description="勾选 = 从大到小；不勾 = 从小到大",
        default=False,
    )
    step: IntProperty(
        name="步幅",
        description="排序后第 i 个（i 从 0 起）整体平移 步幅 × i 帧",
        default=5, min=-FAR, max=FAR, soft_min=-1000, soft_max=1000,
    )
    selected_only: BoolProperty(
        name="仅移动选中帧",
        description="只平移摄影表/曲线编辑器里被选中的关键帧；勾选时若没有任何键被选中则不做任何操作",
        default=False,
    )
    path_object: PointerProperty(
        name="路径",
        description="错帧依据的曲线；点「绘制直线」会自动填这里（也可用吸管改选别的曲线）",
        type=bpy.types.Object, poll=_path_poll,
    )
    path_frames: IntProperty(
        name="帧/总数",
        description="路径末端物体整体平移的帧数；中间按最近点参数 0~1 线性插值（取整向零截断）",
        default=100, min=-FAR, max=FAR, soft_min=-1000, soft_max=1000,
    )
    path_selected_only: BoolProperty(
        name="仅移动选中帧",
        description="只平移被选中的关键帧",
        default=False,
    )


class _VisKeyBase(bpy.types.Operator):
    bl_options = {'REGISTER', 'UNDO'}

    START_HIDDEN = True

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        targets = list(context.selected_objects)
        if not targets:
            self.report({'WARNING'}, "没有选中任何物体")
            return {'CANCELLED'}

        scene = context.scene
        frame = scene.frame_current
        next_frame = frame + 1
        alpha_now = 0.0 if self.START_HIDDEN else 1.0
        alpha_next = 1.0 - alpha_now

        alpha_objs = 0
        hide_objs = 0
        mats = 0
        keys = 0
        failed = []

        for obj in targets:
            try:
                if _has_material(obj):
                    n_mat, k1 = _key_alpha(obj, alpha_now, frame)
                    _, k2 = _key_alpha(obj, alpha_next, next_frame)
                    if k1 or k2:
                        alpha_objs += 1
                        mats = max(mats, n_mat)
                        keys += k1 + k2
                        continue
                _key_hide(obj, self.START_HIDDEN, frame)
                _key_hide(obj, not self.START_HIDDEN, next_frame)
                hide_objs += 1
            except Exception as exc:
                failed.append(obj.name)
                utils.report("WARNING", f"{obj.name}: {exc}")

        done = alpha_objs + hide_objs
        if not done:
            self.report({'WARNING'}, "没有可打可见性关键帧的物体")
            return {'CANCELLED'}

        extended = _extend_frame_end(scene, next_frame)
        _refresh(context)

        text = (f"已在第 {frame} / {next_frame} 帧给 {done} 个物体打可见性关键帧"
                f"（{alpha_objs} 个走材质淡出，共 {mats} 个材质槽；"
                f"{hide_objs} 个无材质槽走渲染隐藏）")
        if extended:
            text += f"；场景结束帧已延到 {next_frame}"
        if failed:
            self.report({'WARNING'}, f"{text}，{len(failed)} 个失败")
        else:
            self.report({'INFO'}, text)
        return {'FINISHED'}


class MF_OT_GrowAnim_HideToShow(_VisKeyBase):
    bl_idname = OP_VIS_KEY
    bl_label = "不可见-可见"
    bl_description = ("当前帧全透明、下一帧完全显示；"
                      "有材质走材质淡出关键帧，无材质槽走渲染隐藏关键帧"
                      "（视口里始终保持可见可选，F12 渲染准确）")
    START_HIDDEN = True


class MF_OT_GrowAnim_ShowToHide(_VisKeyBase):
    bl_idname = OP_UNVIS_KEY
    bl_label = "可见-不可见"
    bl_description = "当前帧完全显示、下一帧全透明"
    START_HIDDEN = False


class MF_OT_GrowAnim_AxisShift(bpy.types.Operator):
    bl_idname = OP_AXIS_SHIFT
    bl_label = "按轴向排序移动帧"
    bl_description = ("选中物体按世界坐标轴排序（可选升/降序），排序后第 i 个整体平移 步幅 × i 帧；"
                      "物体自身轨道、物体数据、形态键与材质淡出关键帧一起平移")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}

        axis = AXIS_INDEX.get(props.axis, 2)
        step = int(props.step)
        selected_only = props.selected_only
        scene_order = {o.name: i for i, o in enumerate(context.view_layer.objects)}
        targets = sorted(
            context.selected_objects,
            key=lambda o: (o.matrix_world.translation[axis], scene_order.get(o.name, 0)),
            reverse=bool(props.descending),
        )

        seen = set()
        moved_objs = 0
        keys = 0
        negative = 0
        max_x = None

        for i, obj in enumerate(targets):
            delta = int(step * i)
            count, neg, frame_max = _shift_object(obj, delta, selected_only, seen)
            if not count:
                continue
            moved_objs += 1
            keys += count
            negative += neg
            if frame_max is not None and (max_x is None or frame_max > max_x):
                max_x = frame_max
            obj.update_tag(refresh={'OBJECT', 'TIME'})

        if not keys:
            self.report({'WARNING'}, _WARN_NO_SEL_KEY if selected_only else _WARN_NO_KEY)
            return {'CANCELLED'}

        extended = _extend_frame_end(context.scene, max_x)
        _refresh(context)

        text = (f"{moved_objs} 个物体 / {keys} 个关键帧已按 {props.axis} "
                f"{'降' if props.descending else '升'}序错帧（步幅 {step}）")
        if negative:
            text += f"（{negative} 个键落到 0 帧以前）"
        if extended:
            text += f"；场景结束帧已延到 {int(max_x)}"
        self.report({'INFO'}, text)
        return {'FINISHED'}


class MF_OT_GrowAnim_PathShift(bpy.types.Operator):
    bl_idname = OP_PATH_SHIFT
    bl_label = "按路径移动关键帧"
    bl_description = ("按物体到路径的最近点参数错帧："
                      "整体平移 int(帧/总数 × 参数) 帧")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        props = _get_props(context)
        if props is None:
            self.report({'ERROR'}, "参数未就绪，请重载插件")
            return {'CANCELLED'}

        path = props.path_object
        if path is None or path.type != 'CURVE':
            self.report({'WARNING'}, "请先点「绘制直线」画一条路径")
            return {'CANCELLED'}

        samples = _path_samples(path)
        if len(samples) < 2:
            self.report({'WARNING'}, f"路径「{path.name}」没有可用的点")
            return {'CANCELLED'}

        total = int(props.path_frames)
        selected_only = props.path_selected_only

        seen = set()
        moved_objs = 0
        keys = 0
        negative = 0
        max_x = None
        params = []

        for obj in context.selected_objects:
            param = _nearest_param(samples, obj.matrix_world.translation)
            delta = int(total * param)
            params.append(param)
            count, neg, frame_max = _shift_object(obj, delta, selected_only, seen)
            if not count:
                continue
            moved_objs += 1
            keys += count
            negative += neg
            if frame_max is not None and (max_x is None or frame_max > max_x):
                max_x = frame_max
            obj.update_tag(refresh={'OBJECT', 'TIME'})

        if not keys:
            self.report({'WARNING'}, _WARN_NO_SEL_KEY if selected_only else _WARN_NO_KEY)
            return {'CANCELLED'}

        extended = _extend_frame_end(context.scene, max_x)
        _refresh(context)

        span = f"{min(params):.3f}~{max(params):.3f}" if params else "-"
        text = (f"{moved_objs} 个物体 / {keys} 个关键帧已按路径「{path.name}」错帧"
                f"（帧/总数 {total}，参数跨度 {span}）")
        if negative:
            text += f"（{negative} 个键落到 0 帧以前）"
        if extended:
            text += f"；场景结束帧已延到 {int(max_x)}"
        self.report({'INFO'}, text)
        return {'FINISHED'}


class MF_OT_GrowAnim_DrawPath(bpy.types.Operator):
    bl_idname = OP_DRAW_PATH
    bl_label = "绘制直线"
    bl_description = ("在 3D 视图里画线：左键连续落点、回车或右键结束、Esc 取消，"
                      "落点投影到世界 Z=0 构造面；画完生成 MF_生长路径 曲线并自动设为路径")
    bl_options = {'REGISTER', 'UNDO'}

    _handle = None

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == 'VIEW_3D'
                and getattr(context, "region", None) is not None)

    def invoke(self, context, event):
        area = context.area
        region = getattr(context, "region", None)
        rv3d = getattr(context.space_data, "region_3d", None)
        if area is None or area.type != 'VIEW_3D' or region is None or rv3d is None:
            self.report({'WARNING'}, "请在 3D 视图里使用绘制")
            return {'CANCELLED'}

        cls = type(self)
        self._remove_handle()

        self._points = []
        self._area = area
        self._region = region
        self._rv3d = rv3d
        self._mouse = (event.mouse_region_x, event.mouse_region_y)

        if gpu is not None:
            cls._handle = bpy.types.SpaceView3D.draw_handler_add(
                self._draw, (), 'WINDOW', 'POST_PIXEL')

        context.window_manager.modal_handler_add(self)
        area.header_text_set(_HEADER)
        return {'RUNNING_MODAL'}

    @classmethod
    def _remove_handle(cls):
        if cls._handle is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handle, 'WINDOW')
        except Exception:
            pass
        cls._handle = None

    def _cleanup(self, context):
        self._remove_handle()
        try:
            self._area.header_text_set(None)
            self._area.tag_redraw()
        except Exception:
            pass
        self._points = []

    def _finish(self, context):
        points = list(self._points)
        self._cleanup(context)
        if len(points) < 2:
            self.report({'WARNING'}, "至少两个点才能成线，已取消")
            return {'CANCELLED'}

        obj = make_path_object(context, points)
        props = _get_props(context)
        if props is not None:
            props.path_object = obj
        try:
            bpy.ops.ed.undo_push(message="绘制生长路径")
        except Exception:
            pass
        _tag_redraw()
        self.report({'INFO'},
                    f"已创建路径「{obj.name}」（{len(points)} 个点），可直接执行按路径错帧")
        return {'FINISHED'}

    def modal(self, context, event):
        area = self._area
        if event.type == 'MOUSEMOVE':
            self._mouse = (event.mouse_region_x, event.mouse_region_y)
            area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            point = world_from_region(self._region, self._rv3d, self._mouse)
            if point is None:
                self.report({'WARNING'}, "当前视角与构造面近乎平行，换角度再落点")
            else:
                self._points.append(point)
                self.report({'INFO'}, f"已落 {len(self._points)} 个点")
            area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self._finish(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            self._cleanup(context)
            self.report({'INFO'}, "已取消绘制")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._cleanup(context)

    def _draw(self):
        if gpu is None or batch_for_shader is None:
            return
        points = list(self._points)
        hover = None
        if self._mouse is not None:
            hover = world_from_region(self._region, self._rv3d, self._mouse)

        lines = []
        for i in range(len(points) - 1):
            lines.extend((points[i][:], points[i + 1][:]))
        if hover is not None and points:
            lines.extend((points[-1][:], hover[:]))

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        try:
            gpu.state.depth_test_set('NONE')
        except Exception:
            pass

        if lines:
            gpu.state.line_width_set(2.0)
            batch = batch_for_shader(shader, 'LINES', {"pos": lines})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.55, 0.05, 1.0))
            batch.draw(shader)

        if points:
            gpu.state.point_size_set(7.0)
            batch = batch_for_shader(shader, 'POINTS', {"pos": [p[:] for p in points]})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.85, 0.1, 1.0))
            batch.draw(shader)

        if hover is not None:
            gpu.state.point_size_set(5.0)
            batch = batch_for_shader(shader, 'POINTS', {"pos": [hover[:]]})
            shader.bind()
            shader.uniform_float("color", (0.2, 0.9, 1.0, 1.0))
            batch.draw(shader)

        gpu.state.point_size_set(1.0)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


classes = (
    MF_PG_GrowAnimSettings,
    MF_OT_GrowAnim_HideToShow,
    MF_OT_GrowAnim_ShowToHide,
    MF_OT_GrowAnim_AxisShift,
    MF_OT_GrowAnim_PathShift,
    MF_OT_GrowAnim_DrawPath,
)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_GrowAnimSettings))


def unregister():
    MF_OT_GrowAnim_DrawPath._remove_handle()

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
