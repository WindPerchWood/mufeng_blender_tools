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
        PANEL_CATEGORY="木风工具箱",
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
        report=lambda level, msg: print(f"[木风工具箱] {level}: {msg}"),
    )

TOOL_ID = "RotMode"
OP_ID = f"mf.{TOOL_ID.lower()}_set"
UNPARENT_OP_ID = "mf.rotmode_unparent"
SINGLE_USER_OP_ID = "mf.rotmode_single_user"
APPLY_TRS_OP_ID = "mf.rotmode_apply_transform"
WM_ATTR = "mf_rotmode"

ROT_MODES = (
    ('XYZ', "XYZ 欧拉", "按 X→Y→Z 顺序旋转"),
    ('XZY', "XZY 欧拉", "按 X→Z→Y 顺序旋转"),
    ('YXZ', "YXZ 欧拉", "按 Y→X→Z 顺序旋转"),
    ('YZX', "YZX 欧拉", "按 Y→Z→X 顺序旋转"),
    ('ZXY', "ZXY 欧拉", "按 Z→X→Y 顺序旋转"),
    ('ZYX', "ZYX 欧拉", "按 Z→Y→X 顺序旋转"),
    ('QUATERNION', "四元数", "四元数旋转"),
)


class MF_PG_RotModeSettings(bpy.types.PropertyGroup):
    mode: bpy.props.EnumProperty(name="旋转模式", items=ROT_MODES, default='XYZ')


class MF_OT_RotMode_Set(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "设置旋转模式"
    bl_description = "批量更改旋转模式，物体朝向与动画不变，仅切换旋转的表示方式"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(name="旋转模式", items=ROT_MODES, default='XYZ')
    only_selected: bpy.props.BoolProperty(name="仅选中对象", default=False)

    def execute(self, context):
        targets = context.selected_objects if self.only_selected else context.scene.objects
        if not targets:
            self.report({'WARNING'}, "没有可处理的对象")
            return {'CANCELLED'}
        changed = 0
        for obj in targets:
            if obj.rotation_mode != self.mode:
                obj.rotation_mode = self.mode
                changed += 1
        scope = "选中对象" if self.only_selected else "全部对象"
        utils.report("INFO", f"{scope} {len(targets)} 个，已改为 {self.mode} 的 {changed} 个")
        return {'FINISHED'}


class MF_OT_RotMode_Unparent(bpy.types.Operator):
    bl_idname = UNPARENT_OP_ID
    bl_label = "解除父级"
    bl_description = "原地解除父子关系，位置不跳"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.scene.objects
                   if o.parent is not None and not o.library]
        if not targets:
            self.report({'WARNING'}, "选中物体里没有带父级的")
            return {'CANCELLED'}

        for child in targets:
            world = child.matrix_world.copy()
            child.parent = None
            child.matrix_basis = world

        self.report({'INFO'}, "已解除 %d 个物体的父级" % len(targets))
        return {'FINISHED'}


class MF_OT_RotMode_SingleUser(bpy.types.Operator):
    bl_idname = SINGLE_USER_OP_ID
    bl_label = "全部变单体"
    bl_description = "共用数据的物体各拆一份独立数据，等效 Max 把 Instance 转 Unique"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.scene.objects
                   if o.data is not None and o.data.users > 1 and not o.library]
        if not targets:
            self.report({'INFO'}, "没有共用数据的物体，无需处理")
            return {'FINISHED'}
        for obj in targets:
            obj.data = obj.data.copy()
        self.report({'INFO'}, "已把 %d 个共用数据的物体拆成独立数据" % len(targets))
        return {'FINISHED'}


class MF_OT_RotMode_ApplyTransform(bpy.types.Operator):
    bl_idname = APPLY_TRS_OP_ID
    bl_label = "应用全部变换"
    bl_description = "把位置/旋转/缩放烧进物体数据并归零，等效 Max 重置 XForm + 塌陷；共享数据的物体自动跳过"
    bl_options = {'REGISTER', 'UNDO'}

    APPLYABLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LATTICE'}

    def execute(self, context):
        targets = []
        skipped_shared = 0
        skipped_anim = 0
        for obj in context.scene.objects:
            if obj.library or obj.data is None:
                continue
            if obj.data.users > 1:
                skipped_shared += 1
                continue
            if obj.type not in self.APPLYABLE_TYPES:
                continue
            anim = obj.animation_data
            if (anim is not None and anim.action is not None) or len(obj.constraints) > 0:
                skipped_anim += 1
                continue
            targets.append(obj)

        if not targets:
            self.report({'WARNING'}, "没有可应用变换的物体")
            return {'CANCELLED'}

        with context.temp_override(selected_objects=targets,
                                   selected_editable_objects=targets,
                                   active_object=targets[0]):
            result = bpy.ops.object.transform_apply(
                location=True, rotation=True, scale=True)

        if result != {'FINISHED'}:
            self.report({'WARNING'}, "应用变换失败")
            return {'CANCELLED'}

        msg = "已应用全部变换 %d 个" % len(targets)
        if skipped_shared:
            msg += "，跳过共享数据 %d 个（先点全部变单体）" % skipped_shared
        if skipped_anim:
            msg += "，跳过带动画/约束 %d 个" % skipped_anim
        self.report({'INFO'}, msg)
        return {'FINISHED'}


classes = (MF_PG_RotModeSettings, MF_OT_RotMode_Set, MF_OT_RotMode_Unparent,
           MF_OT_RotMode_SingleUser, MF_OT_RotMode_ApplyTransform)


def register():
    utils.register_classes(classes)
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            bpy.props.PointerProperty(type=MF_PG_RotModeSettings))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
