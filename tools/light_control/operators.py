import bpy


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

TOOL_ID = "LightControl"
OFF_ID = "mf.light_off"
ON_ID = "mf.light_on"
HIDE_ID = "mf.light_hide"
UNHIDE_ID = "mf.light_unhide"


ENERGY_PROP = "mf_light_energy"

CAMERA_PROP = "mf_light_camera"


def all_lights(context):
    scene = context.scene
    source = scene.objects if scene is not None else bpy.data.objects
    return [o for o in source if o.type == 'LIGHT']


def selected_lights(context):
    return [o for o in context.selected_objects if o.type == 'LIGHT']


def _scope_by_selection(context):
    sel = selected_lights(context)
    if sel:
        return sel, True
    return all_lights(context), False


def _scope_hide(context):
    lights = all_lights(context)
    if context.selected_objects:
        chosen = set(context.selected_objects)
        return [o for o in lights if o in chosen], True
    return lights, False


def iter_3d_views(context):
    wm = getattr(context, 'window_manager', None) or bpy.context.window_manager
    for win in wm.windows:
        screen = getattr(win, 'screen', None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = getattr(area, 'spaces', None)
            space = getattr(space, 'active', None)
            if space is not None:
                yield area, space


def set_icon_overlay(context, show):
    count = 0
    for area, space in iter_3d_views(context):
        overlay = getattr(space, 'overlay', None)
        if overlay is None:
            continue
        try:
            overlay.show_extras = bool(show)
            area.tag_redraw()
            count += 1
        except Exception as exc:
            utils.report("WARNING", f"叠加层开关设置失败: {exc}")
    return count


def _has_animation(light_data):
    try:
        ad = light_data.animation_data
        return bool(ad is not None and ad.action is not None)
    except Exception:
        return False


def set_lights_off(lights):
    done, animated, failed = 0, 0, []
    for obj in lights:
        try:
            data = obj.data
            if ENERGY_PROP not in data.keys():
                data[ENERGY_PROP] = float(data.energy)
            data.energy = 0.0
            if _has_animation(data):
                animated += 1
            done += 1
        except Exception as exc:
            failed.append(obj.name)
            utils.report("WARNING", f"{obj.name}: {exc}")
    return done, animated, failed


def set_lights_on(lights):
    done, restored, failed = 0, 0, []
    for obj in lights:
        try:
            data = obj.data
            if ENERGY_PROP in data.keys():
                data.energy = float(data[ENERGY_PROP])
                del data[ENERGY_PROP]
                restored += 1
            done += 1
        except Exception as exc:
            failed.append(obj.name)
            utils.report("WARNING", f"{obj.name}: {exc}")
    return done, restored, failed


def hide_lights(lights):
    done, healed, failed = 0, 0, []
    for obj in lights:
        try:
            if obj.hide_viewport or obj.hide_render:
                healed += 1
            if CAMERA_PROP not in obj.keys():
                obj[CAMERA_PROP] = bool(obj.visible_camera)
            obj.visible_camera = False
            obj.hide_viewport = False
            obj.hide_render = False
            done += 1
        except Exception as exc:
            failed.append(obj.name)
            utils.report("WARNING", f"{obj.name}: {exc}")
    return done, healed, failed


def unhide_lights(lights):
    done, failed = 0, []
    for obj in lights:
        try:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_set(False)
            if CAMERA_PROP in obj.keys():
                obj.visible_camera = bool(obj[CAMERA_PROP])
                del obj[CAMERA_PROP]
            done += 1
        except Exception as exc:
            failed.append(obj.name)
            utils.report("WARNING", f"{obj.name}: {exc}")
    return done, failed


def _report_op(self, text, failed):
    if failed:
        self.report({'WARNING'}, f"{text}，{len(failed)} 盏失败（详见控制台）")
    else:
        self.report({'INFO'}, text)


class MF_OT_Light_Off(bpy.types.Operator):
    bl_idname = OFF_ID
    bl_label = "关闭所有/选中灯光"
    bl_description = ("选中集合里有灯光 → 只关闭这些灯；未选中或选中的都不是灯光 → 关闭全部灯光。\n"
                      "关闭 = 记住原亮度后把强度置 0：灯在视口里仍显示、仍可选中，"
                      "点「打开」可完整还原原强度")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights, only_selected = _scope_by_selection(context)
        if not lights:
            self.report({'WARNING'}, "场景里没有灯光")
            return {'CANCELLED'}
        done, animated, failed = set_lights_off(lights)
        text = f"已关闭{'选中' if only_selected else '全部'} {done} 盏灯光"
        if animated:
            text += f"（其中 {animated} 盏的亮度受动画驱动，画面可能不变）"
        _report_op(self, text, failed)
        return {'FINISHED'}


class MF_OT_Light_On(bpy.types.Operator):
    bl_idname = ON_ID
    bl_label = "打开所有/选中灯光"
    bl_description = ("选中集合里有灯光 → 只打开这些灯；未选中或选中的都不是灯光 → 打开全部灯光。\n"
                      "打开 = 把「关闭」时记住的原亮度还回去")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights, only_selected = _scope_by_selection(context)
        if not lights:
            self.report({'WARNING'}, "场景里没有灯光")
            return {'CANCELLED'}
        done, restored, failed = set_lights_on(lights)
        text = f"已打开{'选中' if only_selected else '全部'} {done} 盏灯光"
        if restored < done:
            text += f"（{restored} 盏还原了原亮度，{done - restored} 盏原本就是打开的）"
        _report_op(self, text, failed)
        return {'FINISHED'}


class MF_OT_Light_Hide(bpy.types.Operator):
    bl_idname = HIDE_ID
    bl_label = "隐藏灯光"
    bl_description = ("把「看得见」的部分藏起来，照明一律保留：\n"
                      "① 关闭视口叠加层的『附加项』→ 灯图标不再绘制"
                      "（视图级开关，会连相机/空物体图标一起关；Blender 没有逐物体只关图标的属性）\n"
                      "② 目标灯光（选中含灯光 → 那几盏，否则全部）的「相机可见性」关掉"
                      " → 渲染里也看不到光源本身\n"
                      "灯光照明与渲染画面完全不变；另外会清掉残留的视口/渲染隐藏，"
                      "免得光照被误掐\n恢复请点「显示灯光」")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights, only_selected = _scope_hide(context)
        views = set_icon_overlay(context, False)
        parts = []
        if views:
            parts.append(f"已关闭 {views} 个 3D 视图的『附加项』叠加"
                         "（灯图标不再绘制，顺带相机/空物体图标）")
        if lights:
            done, healed, failed = hide_lights(lights)
            parts.append(f"{done} 盏灯（{'选中' if only_selected else '全部'}）"
                         "在渲染中也不再显示光源本身")
            if healed:
                parts.append(f"顺带恢复 {healed} 盏灯被隐藏的照明")
        elif context.selected_objects:

            failed = []
            parts.append("但选中的不是灯光，未处理任何灯")
        else:
            failed = []
            parts.append("场景里没有灯光")
        parts.append("照明与渲染画面不变")
        _report_op(self, "；".join(parts), failed)
        return {'FINISHED'}


class MF_OT_Light_Unhide(bpy.types.Operator):
    bl_idname = UNHIDE_ID
    bl_label = "显示灯光"
    bl_description = ("打开灯图标叠加显示，并恢复全部灯光（不需要选择，与 Max 的 unhide lights 一致）\n"
                      "相机可见性按「隐藏」时记住的原值放回")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lights = all_lights(context)
        views = set_icon_overlay(context, True)
        if not lights:
            self.report({'WARNING'}, f"场景里没有灯光；已打开 {views} 个 3D 视图的灯图标显示")
            return {'CANCELLED'}
        done, failed = unhide_lights(lights)
        _report_op(self, f"已显示全部 {done} 盏灯光，并打开 {views} 个 3D 视图的图标叠加", failed)
        return {'FINISHED'}


classes = (MF_OT_Light_Off, MF_OT_Light_On, MF_OT_Light_Hide, MF_OT_Light_Unhide)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
