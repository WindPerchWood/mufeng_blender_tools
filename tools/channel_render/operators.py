import colorsys
import os

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup

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
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

TOOL_ID = "ChannelRender"

CHANNEL_OBJECT_TYPES = frozenset({"MESH", "CURVE", "SURFACE", "FONT", "META"})

CHANNEL_VIEW_TRANSFORM = "Standard"

COLOR_IS_LINEAR = True

_GOLDEN_ANGLE = 0.6180339887498949

_SHADING_KEYS = (
    "light",
    "color_type",
    "show_object_outline",
    "show_specular_highlight",
    "show_shadows",
    "background_type",
    "background_color",
)

_SAVED = {"colors": [], "temps": [], "active": False}


def srgb_to_linear(c):
    c = max(0.0, min(1.0, float(c)))
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def encode_for_viewport(rgb):
    if not COLOR_IS_LINEAR:
        return tuple(float(c) for c in rgb)
    return tuple(srgb_to_linear(c) for c in rgb)


def make_palette(count, seed=0):
    count = max(0, int(count))
    saturation = 1.0
    value = 1.0

    out = []
    hue = (float(seed) * _GOLDEN_ANGLE) % 1.0
    for _ in range(count):
        out.append(colorsys.hsv_to_rgb(hue, saturation, value))
        hue = (hue + _GOLDEN_ANGLE) % 1.0
    return out


def _prop_names(item):
    try:
        return {p.identifier for p in item.bl_rna.properties}
    except Exception:
        return set()


def iter_target_objects(context, only_selected=False):
    out = []
    for obj in context.view_layer.objects:
        if obj.type not in CHANNEL_OBJECT_TYPES:
            continue
        if obj.hide_render:
            continue
        if only_selected and not obj.select_get():
            continue
        out.append(obj)
    out.sort(key=lambda o: o.name)
    return out


def collect_materials(objects):
    table = {}
    for obj in objects:
        for slot in getattr(obj, "material_slots", ()):
            mat = slot.material
            if mat is not None:
                table[mat.name] = mat
    return [table[k] for k in sorted(table)]


def collect_materialless(objects):
    result = []
    for obj in objects:
        data = getattr(obj, "data", None)
        mats = getattr(data, "materials", None) if data is not None else None
        if mats is None:
            continue
        try:
            length = len(mats)
        except Exception:
            continue
        if length == 0:
            result.append((obj, data, "APPEND", 0))
            continue
        for index in range(length):
            if mats[index] is None:
                result.append((obj, data, "REPLACE", index))
                break
    return result


def apply_colors(items, colors, attr):
    backup = []
    for item, rgb in zip(items, colors):
        try:
            old = tuple(getattr(item, attr))
        except Exception:
            continue
        backup.append((item, attr, old))
        r, g, b = encode_for_viewport(rgb)
        try:
            setattr(item, attr, (r, g, b, 1.0))
        except Exception:
            pass
    return backup


def restore_colors(backup):
    done = 0
    for item, attr, old in backup:
        try:
            setattr(item, attr, old)
            done += 1
        except Exception:
            pass
    return done


def install_temp_materials(entries, colors):
    created = []
    for (obj, data, mode, index), rgb in zip(entries, colors):
        mat = bpy.data.materials.new("MF_channel_tmp")
        try:
            mat.diffuse_color = (*encode_for_viewport(rgb), 1.0)
        except Exception:
            pass
        try:
            if mode == "APPEND":
                data.materials.append(mat)
                created.append((data, "APPEND", len(data.materials) - 1, mat))
            else:
                data.materials[index] = mat
                created.append((data, "REPLACE", index, mat))
        except Exception:
            try:
                bpy.data.materials.remove(mat)
            except Exception:
                pass
    return created


def remove_temp_materials(created):
    for data, mode, index, mat in reversed(created):
        try:
            if mode == "APPEND":
                data.materials.pop(index=index)
            else:
                data.materials[index] = None
        except Exception:
            pass
        try:
            bpy.data.materials.remove(mat)
        except Exception:
            pass


def _read_value(holder, key):
    value = getattr(holder, key)
    if hasattr(value, "__len__") and not isinstance(value, str):
        return tuple(value)
    return value


def snapshot_scene(scene):
    snap = {
        "engine": scene.render.engine,
        "filepath": scene.render.filepath,
        "film_transparent": scene.render.film_transparent,
        "dither_intensity": scene.render.dither_intensity,
        "file_format": scene.render.image_settings.file_format,
        "color_mode": scene.render.image_settings.color_mode,
        "color_depth": scene.render.image_settings.color_depth,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "render_aa": None,
        "shading": {},
    }
    display = scene.display
    if "render_aa" in _prop_names(display):
        snap["render_aa"] = display.render_aa
    shading = display.shading
    for key in _SHADING_KEYS:
        if key in _prop_names(shading):
            snap["shading"][key] = _read_value(shading, key)
    return snap


def apply_channel_settings(scene, color_type, transparent=False, render_aa=None):
    scene.render.engine = "BLENDER_WORKBENCH"

    shading = scene.display.shading
    names = _prop_names(shading)
    if "light" in names:
        shading.light = "FLAT"
    if "color_type" in names:
        shading.color_type = color_type
    if "show_object_outline" in names:
        shading.show_object_outline = False
    if "show_specular_highlight" in names:
        shading.show_specular_highlight = False
    if "show_shadows" in names:
        shading.show_shadows = False
    if not transparent:
        if "background_type" in names:
            shading.background_type = "VIEWPORT"
        if "background_color" in names:
            shading.background_color = (0.0, 0.0, 0.0)

    scene.render.film_transparent = bool(transparent)
    scene.render.dither_intensity = 0.0

    if render_aa:
        try:
            scene.display.render_aa = render_aa
        except Exception:
            pass

    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGBA" if transparent else "RGB"
    settings.color_depth = "8"

    view = scene.view_settings
    try:
        view.view_transform = CHANNEL_VIEW_TRANSFORM
    except Exception:
        pass
    try:
        view.look = "None"
    except Exception:
        pass
    view.exposure = 0.0
    view.gamma = 1.0


def restore_scene(scene, snap):
    if not snap:
        return
    try:
        scene.render.engine = snap["engine"]
    except Exception:
        pass
    try:
        scene.render.filepath = snap["filepath"]
    except Exception:
        pass
    settings = scene.render.image_settings
    for key, value in (
        ("file_format", snap["file_format"]),
        ("color_mode", snap["color_mode"]),
        ("color_depth", snap["color_depth"]),
    ):
        try:
            setattr(settings, key, value)
        except Exception:
            pass
    try:
        scene.render.film_transparent = snap["film_transparent"]
    except Exception:
        pass
    if snap.get("dither_intensity") is not None:
        try:
            scene.render.dither_intensity = snap["dither_intensity"]
        except Exception:
            pass

    view = scene.view_settings
    for key in ("view_transform", "look", "exposure", "gamma"):
        value = snap.get(key)
        if value is None:
            continue
        try:
            setattr(view, key, value)
        except Exception:
            pass

    if snap.get("render_aa") is not None:
        try:
            scene.display.render_aa = snap["render_aa"]
        except Exception:
            pass

    shading = scene.display.shading
    names = _prop_names(shading)
    for key, value in (snap.get("shading") or {}).items():
        if key in names:
            try:
                setattr(shading, key, value)
            except Exception:
                pass


def resolve_output_dir(scene, output_dir):
    raw = (output_dir or "").strip()
    if not raw:
        raw = "//"
    fallback = False
    if raw.startswith("//") and not bpy.data.filepath:
        fallback = True
        base = os.path.join(bpy.app.tempdir, "channel")
    else:
        base = bpy.path.abspath(raw)
        if not os.path.isabs(base):
            fallback = True
            base = os.path.join(bpy.app.tempdir, "channel")
    return base, fallback


def resolve_output_filepath(scene, output_dir, prefix):
    base, _fallback = resolve_output_dir(scene, output_dir)
    name = "{}{:04d}".format(prefix or "MF_", scene.frame_current)
    return os.path.join(base, name)


def unique_output_filepath(scene, output_dir, prefix):
    base = resolve_output_filepath(scene, output_dir, prefix)
    candidate = bpy.path.ensure_ext(base, ".png")
    index = 1
    while os.path.exists(candidate):
        index += 1
        candidate = bpy.path.ensure_ext("{}_{:03d}".format(base, index), ".png")
    return os.path.splitext(candidate)[0]


def show_result_window(context, path):
    if not path or not os.path.exists(path):
        return False, "结果文件不存在：{}".format(path)
    if bpy.app.background:
        return False, "后台模式不弹窗（结果已写入文件）"

    try:
        target = bpy.path.abspath(path)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "IMAGE_EDITOR":
                    continue
                space = area.spaces.active
                exist = getattr(space, "image", None) if space is not None else None
                if exist is not None and bpy.path.abspath(exist.filepath) == target:
                    exist.reload()
                    return True, "结果窗口已在显示"
    except Exception:
        pass

    try:
        image = bpy.data.images.load(path, check_existing=True)
        image.reload()
    except Exception as exc:
        return False, "读不到结果图：{}".format(exc)

    ok, why = _open_image_window(context, image)
    if ok:
        return True, "已弹出结果窗口"

    try:
        bpy.ops.render.view_show()
        return True, "已用 Blender 自带渲染窗口显示"
    except Exception as exc:
        return False, "{}；自带渲染窗口也不可用（{}）".format(why, exc)


def _open_image_window(context, image):
    try:
        before = len(context.window_manager.windows)
        bpy.ops.wm.window_new()
        windows = context.window_manager.windows
        if len(windows) <= before:
            return False, "没能新建窗口"
        window = windows[-1]
        areas = sorted(window.screen.areas,
                       key=lambda a: a.width * a.height, reverse=True)
        if not areas:
            return False, "新窗口里没有可用区域"
        area = areas[0]
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = image
    except Exception as exc:
        return False, "弹窗失败：{}".format(exc)
    return True, ""


def popup_alert(context, message):
    if bpy.app.background or not message:
        return False
    try:
        bpy.ops.mf.channel_alert("INVOKE_DEFAULT", message=message)
        return True
    except Exception:
        return False


def _clear_saved():
    _SAVED["colors"] = []
    _SAVED["temps"] = []
    _SAVED["active"] = False


def restore_saved_colors():
    if not _SAVED["active"]:
        return 0
    count = 0
    try:
        remove_temp_materials(_SAVED["temps"])
        count = restore_colors(_SAVED["colors"])
    finally:
        _clear_saved()
    return count


def run_channel_render(context, settings):
    scene = context.scene

    if scene.camera is None:
        return False, "场景没有设置相机，无法渲染"

    objects = iter_target_objects(context, settings.only_selected)
    if not objects:
        return False, "没有找到可处理的几何物体"

    if _SAVED["active"]:
        restore_saved_colors()

    snapshot = snapshot_scene(scene)
    color_backup = []
    temp_records = []
    color_type = "OBJECT" if settings.mode == "OBJECT" else "MATERIAL"

    try:
        if settings.mode == "OBJECT":
            palette = make_palette(len(objects), settings.seed)
            color_backup += apply_colors(objects, palette, "color")
        else:
            materials = collect_materials(objects)
            palette = make_palette(len(materials), settings.seed)
            color_backup += apply_colors(materials, palette, "diffuse_color")

            entries = collect_materialless(objects)
            if entries:
                extra = make_palette(len(entries), settings.seed + len(materials))
                temp_records = install_temp_materials(entries, extra)

        apply_channel_settings(
            scene, color_type,
            transparent=settings.transparent,
            render_aa="OFF",
        )

        filepath = unique_output_filepath(
            scene, settings.output_dir, "MF_",
        )
        _dir, used_fallback = resolve_output_dir(scene, settings.output_dir)
        scene.render.filepath = filepath

        bpy.ops.render.render(write_still=True)
        written = bpy.path.ensure_ext(filepath, ".png")

    except Exception as exc:
        return False, "通道渲染失败：{}".format(exc)

    finally:
        try:
            remove_temp_materials(temp_records)
        except Exception:
            pass
        try:
            restore_colors(color_backup)
        except Exception:
            pass
        try:
            restore_scene(scene, snapshot)
        except Exception:
            pass

    settings.last_output = written

    notes = []
    if used_fallback:
        notes.append("注意：当前 .blend 尚未存盘，通道图输出到了临时目录")

    if settings.show_result:
        shown, why = show_result_window(context, written)
        if not shown and why:
            notes.append(why)

    count = len(objects) if settings.mode == "OBJECT" else None
    detail = "{} 个物体".format(count) if count is not None else "材质级配色"
    message = "通道图已输出：{}\n（{}）".format(written, detail)
    if notes:
        message += "\n" + "\n".join(notes)
    return True, message


class MF_ChannelSettings(PropertyGroup):
    mode: EnumProperty(
        name="模式",
        description="物体通道 = 每个物体一个纯色；子材质通道 = 每个材质（含每个材质槽）一个纯色",
        items=(
            ("OBJECT", "物体通道", "每个物体一个随机纯色，整物体同色"),
            ("MATERIAL", "子材质通道", "每个材质一个随机纯色；一个物体有多个材质槽时，各槽颜色不同"),
        ),
        default="OBJECT",
    )

    seed: IntProperty(
        name="随机种子",
        description="同一个种子 + 同一套物体 = 同一套颜色，便于跨版本对比",
        default=0,
        min=0,
    )

    transparent: BoolProperty(
        name="透明背景",
        description="输出带 alpha 的图；关闭时背景压成纯黑，便于直接看轮廓",
        default=False,
    )

    only_selected: BoolProperty(
        name="仅选中物体",
        description="只处理当前选中的物体",
        default=False,
    )

    show_result: BoolProperty(
        name="渲染后弹出结果",
        description="渲完自动弹一个窗口显示通道图。关掉的话就只写文件，不弹窗",
        default=True,
    )

    last_output: StringProperty(
        name="最近输出",
        description="上一次通道图的完整路径",
        default="",
    )

    output_dir: StringProperty(
        name="输出目录",
        description="默认 // 表示与 .blend 同目录",
        default="//channel",
        subtype="DIR_PATH",
    )


class MF_OT_channel_render(Operator):
    bl_idname = "mf.channel_render"
    bl_label = "渲染通道图"
    bl_description = ("把场景临时切成通道图状态并渲染，渲完自动还原（不会动真实材质）；"
                      "渲完会弹一个窗口把结果显示出来")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        ok, message = run_channel_render(context, context.scene.mf_channel)
        if not ok:
            self.report({"ERROR"}, message)
            popup_alert(context, message)
            return {"CANCELLED"}
        for line in message.splitlines():
            self.report({"INFO"}, line)
        return {"FINISHED"}


class MF_OT_channel_restore(Operator):
    bl_idname = "mf.channel_restore"
    bl_label = "还原颜色"
    bl_description = "把显示色还原为通道渲染之前的数值"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(_SAVED["active"])

    def execute(self, context):
        count = restore_saved_colors()
        if not count:
            self.report({"INFO"}, "没有需要还原的颜色")
        else:
            self.report({"INFO"}, "已还原 {} 处颜色".format(count))
        return {"FINISHED"}


class MF_OT_channel_open_folder(Operator):
    bl_idname = "mf.channel_open_folder"
    bl_label = "打开所在文件夹"
    bl_description = "在文件管理器里打开最近一次通道图的输出位置"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.mf_channel.last_output)

    def execute(self, context):
        folder = os.path.dirname(context.scene.mf_channel.last_output)
        if not os.path.isdir(folder):
            message = "文件夹不存在：\n{}".format(folder)
            self.report({"ERROR"}, message)
            popup_alert(context, message)
            return {"CANCELLED"}
        try:
            bpy.ops.wm.path_open(filepath=folder)
        except Exception as exc:
            self.report({"ERROR"}, "打开文件夹失败：{}".format(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class MF_OT_channel_alert(Operator):
    bl_idname = "mf.channel_alert"
    bl_label = "通道渲染"
    bl_options = {"REGISTER"}

    message: StringProperty(name="message", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        layout = self.layout
        for line in (self.message or "").splitlines():
            layout.label(text=line)

    def execute(self, context):
        return {"FINISHED"}


classes = (
    MF_ChannelSettings,
    MF_OT_channel_render,
    MF_OT_channel_restore,
    MF_OT_channel_open_folder,
    MF_OT_channel_alert,
)


def register():
    utils.register_classes(classes)
    bpy.types.Scene.mf_channel = PointerProperty(type=MF_ChannelSettings)


def unregister():
    if hasattr(bpy.types.Scene, "mf_channel"):
        del bpy.types.Scene.mf_channel
    utils.unregister_classes(classes)
