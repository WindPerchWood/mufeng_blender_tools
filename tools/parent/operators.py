import bpy
from mathutils import Matrix


try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    utils = types.SimpleNamespace(
        PANEL_CATEGORY="MF Tools",
        MF_ToolPanel=bpy.types.Panel,
        report=lambda level, msg: print(f"[MF Tools] {level}: {msg}"),
    )

PARENT_OP_ID = "mf.parent_max"
UNPARENT_OP_ID = "mf.unparent_max"


class MF_OT_ParentMax(bpy.types.Operator):
    bl_idname = PARENT_OP_ID
    bl_label = "绑定到活动物体"
    bl_description = "绑定到活动物体，位置不跳，location 即相对父级坐标"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        parent = context.active_object
        if parent is None:
            self.report({'WARNING'}, "没有活动物体：先点选父级，再加选子物体")
            return {'CANCELLED'}
        if parent.library:
            self.report({'WARNING'}, "活动物体是链接库数据，不能作为父级")
            return {'CANCELLED'}
        children = [o for o in context.selected_objects
                    if o is not parent and not o.library]
        if not children:
            self.report({'WARNING'}, "没有可绑定的子物体")
            return {'CANCELLED'}

        pinv = parent.matrix_world.inverted()
        for child in children:
            world = child.matrix_world.copy()
            child.parent = parent
            child.parent_type = 'OBJECT'
            child.parent_bone = ""
            child.matrix_parent_inverse = Matrix.Identity(4)
            child.matrix_basis = pinv @ world

        self.report({'INFO'}, "已绑定 %d 个物体到 %s" % (len(children), parent.name))
        return {'FINISHED'}


class MF_OT_UnparentMax(bpy.types.Operator):
    bl_idname = UNPARENT_OP_ID
    bl_label = "解除父级"
    bl_description = "原地解除父子关系，位置不跳"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects
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


classes = (
    MF_OT_ParentMax,
    MF_OT_UnparentMax,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
