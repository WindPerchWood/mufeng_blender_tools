"""操作符层：只做「读参数 → 调几何 → 落对象」，几何计算一律不写在这里。"""

import bpy
from bpy.props import EnumProperty

from . import core
from . import presets

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

TOOL_ID = "StdParts"
OP_ADD = f"mf.{TOOL_ID.lower()}_add"
OP_REBUILD = f"mf.{TOOL_ID.lower()}_rebuild"
OP_RESET = f"mf.{TOOL_ID.lower()}_reset"
OP_COPY_TO_DRAFT = f"mf.{TOOL_ID.lower()}_copy_to_draft"
OP_TOGGLE_PANEL = f"mf.{TOOL_ID.lower()}_toggle_panel"
OP_PRESET_BEARING = f"mf.{TOOL_ID.lower()}_preset_bearing"
OP_PRESET_CHAIN = f"mf.{TOOL_ID.lower()}_preset_chain"
OP_PRESET_GEAR_MODULE = f"mf.{TOOL_ID.lower()}_preset_gear_module"
OP_PRESET_SPRING_WIRE = f"mf.{TOOL_ID.lower()}_preset_spring_wire"


def deselect_all(context):
    try:
        for o in context.view_layer.objects:
            o.select_set(False)
    except Exception:
        pass
    try:
        context.view_layer.objects.active = None
    except Exception:
        pass


def new_stdpart(context, source=None, part_type=None):
    if part_type is None:
        part_type = source.part_type if source is not None else 'SPRING'

    name = {ident: label for ident, label, _desc in core.PART_TYPE_ITEMS}.get(part_type, part_type)
    obj = bpy.data.objects.new("MF_" + part_type.title(),
                               bpy.data.meshes.new("MF_StdParts_init"))

    if source is not None:
        core.copy_settings(source, obj.mf_stdparts)
    with core.suspend_rebuild():
        obj.mf_stdparts.part_type = part_type

    try:
        obj.location = context.scene.cursor.location.copy()
    except Exception:
        pass

    coll = getattr(context, "collection", None) or context.scene.collection
    coll.objects.link(obj)

    core.refresh(obj, context)
    obj.name = name if name not in bpy.data.objects else obj.name
    deselect_all(context)
    return obj


class MF_OT_StdParts_Add(bpy.types.Operator):
    bl_idname = OP_ADD
    bl_label = "一键生成标准件"
    bl_description = "按新建面板里的参数生成一个标准件实体模型（生成后参数仍可实时调整）"
    bl_options = {'REGISTER', 'UNDO'}

    part_type: EnumProperty(name="标准件类型", items=core.PART_TYPE_ITEMS, default='SPRING')
    use_draft: bpy.props.BoolProperty(
        name="使用新建面板的参数", default=True,
        description="勾选：用侧栏「标准件一键生成器」面板里的参数（含类型）。"
                    "不勾：用该类型的出厂默认值，并且不改动面板")

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        if self.use_draft:
            obj = new_stdpart(context, source=core.draft(context))
            core.set_create_panel_open(context, False)
        else:
            obj = new_stdpart(context, source=None, part_type=self.part_type)

        info = core.read_info(obj)
        if info.get('error'):
            self.report({'ERROR'}, "生成失败：%s" % info['error'])
            return {'CANCELLED'}
        self.report({'INFO'}, "已生成 %s（%d 面）" % (obj.name, info.get('face_count', 0)))
        return {'FINISHED'}


class MF_OT_StdParts_CopyToDraft(bpy.types.Operator):
    bl_idname = OP_COPY_TO_DRAFT
    bl_label = "把选中对象的参数存为新建默认值"
    bl_description = "把当前选中标准件的全部参数复制到「标准件一键生成器」面板，随后生成的就是这套参数"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not core.is_stdpart(obj):
            self.report({'WARNING'}, "请先选中一个标准件")
            return {'CANCELLED'}
        src = core.draft(context)
        if src is None:
            self.report({'ERROR'}, "新建草稿参数不可用")
            return {'CANCELLED'}
        core.copy_settings(obj.mf_stdparts, src)
        core.tag_redraw(context)
        self.report({'INFO'}, "已复制为新建默认值")
        return {'FINISHED'}


class MF_OT_StdParts_Rebuild(bpy.types.Operator):
    bl_idname = OP_REBUILD
    bl_label = "重新生成"
    bl_description = "用当前参数重新计算网格（正常情况下改参数会实时生效，这个按钮用于强制刷新）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        done = 0
        targets = [o for o in context.selected_objects if core.is_stdpart(o)]
        if not targets:
            a = context.active_object
            if core.is_stdpart(a):
                targets = [a]
        for obj in targets:
            core.refresh(obj, context)
            done += 1
        if not done:
            self.report({'WARNING'}, "请先选中一个由本工具生成的标准件")
            return {'CANCELLED'}
        self.report({'INFO'}, "已重新生成 %d 个对象" % done)
        return {'FINISHED'}


class MF_OT_StdParts_Reset(bpy.types.Operator):
    bl_idname = OP_RESET
    bl_label = "恢复默认参数"
    bl_description = "把当前标准件的所有参数恢复为出厂默认值"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not core.is_stdpart(obj):
            self.report({'WARNING'}, "请先选中一个标准件")
            return {'CANCELLED'}
        props = obj.mf_stdparts
        skip = {'rna_type', 'part_type', 'unit', 'length_mode', 'name'}
        rna = props.bl_rna.properties
        with core.suspend_rebuild():
            for key in list(rna.keys()):
                if key in skip:
                    continue
                prop = rna[key]
                if not hasattr(prop, 'default'):
                    continue
                try:
                    setattr(props, key, prop.default)
                except Exception:
                    pass
        core.refresh(obj, context)
        self.report({'INFO'}, "参数已恢复默认")
        return {'FINISHED'}


class MF_OT_StdParts_PresetBase(bpy.types.Operator):

    bl_options = {'REGISTER', 'UNDO'}

    use_draft: bpy.props.BoolProperty(
        name="作用于新建面板", default=True,
        description="勾选：改的是「标准件一键生成器」面板里的参数；不勾：改的是选中对象")

    def _target(self, context):
        if self.use_draft:
            return core.draft(context)
        obj = context.active_object
        return obj.mf_stdparts if core.is_stdpart(obj) else None

    def _finish(self, context, props):
        owner = props.id_data
        if isinstance(owner, bpy.types.Object):
            core.refresh(owner, context)
        else:
            core.tag_redraw(context)
        return {'FINISHED'}

    def _run(self, context, setter):
        props = self._target(context)
        if props is None:
            self.report({'WARNING'}, "请先选中一个标准件，或改用「作用于新建面板」")
            return {'CANCELLED'}
        with core.suspend_rebuild():
            setter(props)
        return self._finish(context, props)


class MF_OT_StdParts_PresetBearing(MF_OT_StdParts_PresetBase):
    bl_idname = OP_PRESET_BEARING
    bl_label = "套用轴承规格"
    bl_description = "按公开的国家标准公称尺寸设置轴承的内径 / 外径 / 宽度"

    def execute(self, context):
        def setter(p):
            d, D, B = presets.BALL_BEARINGS.get(p.preset_bearing, (8.0, 22.0, 7.0))
            p.brg_bore, p.brg_outer, p.brg_width = d, D, B
        return self._run(context, setter)


class MF_OT_StdParts_PresetChain(MF_OT_StdParts_PresetBase):
    bl_idname = OP_PRESET_CHAIN
    bl_label = "套用链条规格"
    bl_description = "按公开的国家标准公称尺寸设置链条的节距 / 滚子 / 内宽 / 链板高"

    def execute(self, context):
        def setter(p):
            pitch, d1, b1, h2 = presets.ROLLER_CHAINS.get(
                p.preset_chain, (12.7, 7.92, 7.85, 11.8))
            p.chain_pitch, p.chain_roller = pitch, d1
            p.chain_width, p.chain_plate_h = b1, h2
        return self._run(context, setter)


class MF_OT_StdParts_PresetGearModule(MF_OT_StdParts_PresetBase):
    bl_idname = OP_PRESET_GEAR_MODULE
    bl_label = "套用标准模数"
    bl_description = "按公开的国家标准模数系列设置模数"

    def execute(self, context):
        def setter(p):
            p.gear_module = float(p.preset_gear_module)
        return self._run(context, setter)


class MF_OT_StdParts_PresetSpringWire(MF_OT_StdParts_PresetBase):
    bl_idname = OP_PRESET_SPRING_WIRE
    bl_label = "套用标准线径"
    bl_description = "按公开的国家标准线径系列设置弹簧线径"

    def execute(self, context):
        def setter(p):
            p.spring_wire = float(p.preset_spring_wire)
        return self._run(context, setter)


class MF_OT_StdParts_TogglePanel(bpy.types.Operator):
    bl_idname = OP_TOGGLE_PANEL
    bl_label = "展开 / 收起侧栏面板"
    bl_description = "折叠或展开对应的那块面板（三块面板的标题行都走这里）"
    bl_options = {'INTERNAL'}

    panel: EnumProperty(
        name="面板",
        description="要展开或收起的面板",
        items=[(core.PANEL_BUILD, core.PANEL_LABELS[core.PANEL_BUILD], "新建面板"),
               (core.PANEL_PARAMS, core.PANEL_LABELS[core.PANEL_PARAMS], "对象参数面板"),
               (core.PANEL_INFO, core.PANEL_LABELS[core.PANEL_INFO], "尺寸信息面板")],
        default=core.PANEL_BUILD)

    def execute(self, context):
        core.set_panel_open(context, not core.panel_is_open(context, self.panel), self.panel)
        return {'FINISHED'}


classes = (
    MF_OT_StdParts_Add,
    MF_OT_StdParts_Rebuild,
    MF_OT_StdParts_Reset,
    MF_OT_StdParts_CopyToDraft,
    MF_OT_StdParts_TogglePanel,
    MF_OT_StdParts_PresetBearing,
    MF_OT_StdParts_PresetChain,
    MF_OT_StdParts_PresetGearModule,
    MF_OT_StdParts_PresetSpringWire,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
