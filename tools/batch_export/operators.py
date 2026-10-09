import os
import re

import bpy
from bpy.props import EnumProperty, BoolProperty, StringProperty

from ...core import utils

TOOL_ID = "BatchExport"


EXPORT_MENU = "TOPBAR_MT_file_export"


SELECTION_PROPS = (
    "export_selected_objects",
    "use_selection",
    "selected_objects_only",
)


class _LayoutSpy:
    def __init__(self, depth=0):
        self.ops = []
        self.depth = depth
        self.layout = self

    def _noop(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self._noop

    def operator(self, idname, text="", **kwargs):
        if idname:
            self.ops.append((idname, text or ""))
        return self

    def menu(self, idname, text="", **kwargs):
        if self.depth > 2:
            return self
        sub = getattr(bpy.types, idname or "", None)
        if sub is None or not hasattr(sub, "draw"):
            return self
        spy = _LayoutSpy(self.depth + 1)
        try:
            sub.draw(spy, bpy.context)
        except Exception:
            return self
        self.ops.extend(spy.ops)
        return self


def _op(idname):
    if not idname or "." not in idname:
        return None
    mod_name, op_name = idname.split(".", 1)
    try:
        return getattr(getattr(bpy.ops, mod_name), op_name)
    except Exception:
        return None


def _op_props(idname):
    op = _op(idname)
    if op is None:
        return set()
    try:
        return set(op.get_rna_type().properties.keys())
    except Exception:
        return set()


def _op_rna_name(idname, fallback=""):
    if fallback:
        return fallback
    op = _op(idname)
    if op is not None:
        try:
            return op.get_rna_type().name
        except Exception:
            pass
    return idname


def _op_label(idname, menu_text=""):
    if menu_text:
        return menu_text
    for other_id, other_text in available_exporters():
        if other_id == idname and other_text:
            return other_text
    return _op_rna_name(idname)


def _ext_of(idname, label):
    match = re.search(r"\(\s*\.?([A-Za-z0-9_]+)", label or "")
    if match:
        return match.group(1).lower()

    parts = [p for p in idname.split(".")[-1].split("_") if p != "export"]
    return (parts[-1] if parts else idname.split(".")[-1]).lower()


def _scan_ops_exporters():
    found = []
    for mod_name in dir(bpy.ops):
        if not mod_name.startswith("export_") and mod_name != "wm":
            continue
        try:
            mod = getattr(bpy.ops, mod_name)
        except Exception:
            continue
        for op_name in dir(mod):
            if not op_name.startswith("export"):
                continue
            found.append((f"{mod_name}.{op_name}", ""))
    return found


def available_exporters():
    raw = []
    menu = getattr(bpy.types, EXPORT_MENU, None)
    if menu is not None and hasattr(menu, "draw"):
        spy = _LayoutSpy()
        try:
            menu.draw(spy, bpy.context)
        except Exception:
            pass
        raw.extend(spy.ops)

    if not raw:
        raw.extend(_scan_ops_exporters())

    result = []
    seen = set()
    for idname, text in raw:
        if not idname or idname in seen:
            continue
        if "." not in idname:
            continue
        seen.add(idname)
        result.append((idname, _op_rna_name(idname, text)))
    return result


def export_format_items(self, context):
    items = []
    for idname, label in available_exporters():
        ext = _ext_of(idname, label)
        items.append((idname, label or idname, f"导出为 {ext} 文件 ({idname})"))
    if not items:
        items.append(("wm.obj_export", "OBJ", "未检测到任何导出器"))
    return items


def _clear_ext_override(self, context):
    self.ext_override = ""

class MF_OT_BatchExport_Run(bpy.types.Operator):
    bl_idname = f"mf.{TOOL_ID.lower()}_run"
    bl_label = "批量导出选中对象"
    bl_description = "把选中的每个对象单独导出为一个文件，格式取自「文件 > 导出」菜单"
    bl_options = {'REGISTER', 'UNDO'}

    fmt: EnumProperty(
        name="格式",
        description="取自当前 Blender「文件 > 导出」菜单中可用的导出器",
        items=export_format_items,
        update=_clear_ext_override,
    )
    ext_override: StringProperty(
        name="扩展名",
        description="留空则按格式自动推断；如 glTF 想导出 .gltf 就填 gltf",
        default="",
    )
    use_prefs_dir: BoolProperty(
        name="用偏好中的目录",
        description="关闭时可自行选择导出目录",
        default=True,
    )
    directory: StringProperty(
        name="导出目录",
        description="不使用偏好目录时，文件导出到这里（点文件夹图标选择）",
        subtype='DIR_PATH',
        default="//export",
    )
    apply_transform: BoolProperty(
        name="应用坐标变换",
        description="仅对支持该参数的格式（如 OBJ）生效",
        default=True,
    )

    def current_ext(self):
        return (self.ext_override or "").strip().lstrip(".").lower() or _ext_of(
            self.fmt, _op_label(self.fmt)
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "fmt")
        row = layout.row()
        row.prop(self, "ext_override", text="扩展名")
        row.enabled = True
        layout.label(text=f"自动推断: .{_ext_of(self.fmt, _op_label(self.fmt))}")
        layout.prop(self, "use_prefs_dir")
        if not self.use_prefs_dir:
            layout.prop(self, "directory")
        layout.prop(self, "apply_transform")
        box = layout.box()
        box.label(text="格式列表 = 文件 > 导出 菜单中的可用项", icon='INFO')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def execute(self, context):
        targets = list(context.selected_objects)
        if not targets:
            self.report({'WARNING'}, "没有选中任何对象")
            return {'CANCELLED'}

        op = _op(self.fmt)
        if op is None:
            self.report({'ERROR'}, f"当前 Blender 不支持该导出器: {self.fmt}")
            return {'CANCELLED'}

        if self.use_prefs_dir:
            root = utils.get_prefs().export_dir
        else:
            root = self.directory or "//export"
        root = bpy.path.abspath(root)
        if not root:
            self.report({'ERROR'}, "未指定导出目录：请先保存 .blend 或手动选择目录")
            return {'CANCELLED'}
        try:
            os.makedirs(root, exist_ok=True)
        except Exception as exc:
            self.report({'ERROR'}, f"无法创建目录: {exc}")
            return {'CANCELLED'}

        label = _op_label(self.fmt)
        ext = self.current_ext()
        props = _op_props(self.fmt)

        kwargs = {"filepath": ""}
        sel_prop = next((p for p in SELECTION_PROPS if p in props), None)
        if sel_prop:
            kwargs[sel_prop] = True
        else:
            utils.report("WARNING", f"{label} 不支持「仅导出选中」，将导出整个场景")
        if "apply_transform" in props:
            kwargs["apply_transform"] = self.apply_transform

        sub_formats = [None]
        if "export_format" in props:
            if ext == "glb":
                sub_formats = ["GLB"]
            elif ext == "gltf":
                sub_formats = ["GLTF", "GLTF_SEPARATE"]

        prev_active = context.view_layer.objects.active
        prev_selection = {obj.name for obj in targets}

        done, failed = 0, 0
        for obj in targets:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                context.view_layer.objects.active = obj
                try:
                    if not op.poll():
                        bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass
                kwargs["filepath"] = os.path.join(root, f"{obj.name}.{ext}")
                last_error = None
                for sub in sub_formats:
                    try:
                        call_kwargs = dict(kwargs)
                        if sub:
                            call_kwargs["export_format"] = sub
                        op(**call_kwargs)
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                if last_error is not None:
                    raise last_error
                done += 1
            except Exception as exc:
                failed += 1
                utils.report("ERROR", f"{obj.name}: {exc}")

        try:
            bpy.ops.object.select_all(action='DESELECT')
            for name in prev_selection:
                if name in context.view_layer.objects:
                    context.view_layer.objects[name].select_set(True)
            context.view_layer.objects.active = prev_active
        except Exception:
            pass

        if failed:
            self.report({'WARNING'}, f"导出 {done} 个，失败 {failed} 个 -> {root}")
        else:
            self.report({'INFO'}, f"已导出 {done} 个 {ext} 文件 -> {root}")
        return {'FINISHED'}


classes = (MF_OT_BatchExport_Run,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
