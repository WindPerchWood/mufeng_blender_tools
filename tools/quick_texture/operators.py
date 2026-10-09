import os

import bmesh
import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types

    def _reg(classes):
        for c in classes:
            bpy.utils.register_class(c)

    def _unreg(classes):
        for c in reversed(classes):
            bpy.utils.unregister_class(c)

    utils = types.SimpleNamespace(
        PANEL_CATEGORY="Toolbox",
        register_classes=_reg,
        unregister_classes=_unreg,
        report=lambda level, msg: print(f"[Toolbox] {level}: {msg}"),
    )

TOOL_ID = "QuickTexture"
OP_ID = f"mf.{TOOL_ID.lower()}_apply"

MESH_TYPES = {'MESH'}


def load_image(filepath):
    return bpy.data.images.load(filepath, check_existing=True)


def ensure_material(name):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    return mat


def ensure_image_node(mat, image):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = nodes.get('Principled BSDF')
    if bsdf is None:
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        output = nodes.get('Material Output') or nodes.new('ShaderNodeOutputMaterial')
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    tex = None
    for link in bsdf.inputs['Base Color'].links:
        if link.from_node.type == 'TEX_IMAGE':
            tex = link.from_node
            break
    if tex is None:
        tex = next((n for n in nodes if n.type == 'TEX_IMAGE'), None)
    created = False
    if tex is None:
        tex = nodes.new('ShaderNodeTexImage')
        tex.location = (bsdf.location.x - 320, bsdf.location.y + 120)
        created = True

    tex.image = image
    if created:
        links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    return created


def slot_index(obj, mat):
    for i, slot in enumerate(obj.material_slots):
        if slot.material is mat:
            return i
    obj.data.materials.append(mat)
    return len(obj.material_slots) - 1


def ensure_base_material():
    base = ensure_material("基础材质")
    if base.node_tree:
        bsdf = base.node_tree.nodes.get('Principled BSDF')
        if bsdf is not None:
            bsdf.inputs['Base Color'].default_value = (0.6, 0.6, 0.6, 1.0)
    return base


def collect_edit_selection():
    result = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.mode != 'EDIT':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        sel = [f.index for f in bm.faces if f.select]
        if sel:
            result[obj] = sel
    return result


def _select_faces(obj, faces):
    if faces is None:
        bpy.ops.mesh.select_all(action='SELECT')
        return
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    for i in faces:
        if 0 <= i < len(bm.faces):
            bm.faces[i].select_set(True)
    bmesh.update_edit_mesh(obj.data)


def apply_to_object(context, obj, mat, faces, auto_uv, force_uv):
    with context.temp_override(active_object=obj, selected_objects=[obj], object=obj):
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        if faces is None:
            idx = slot_index(obj, mat)
            bpy.ops.mesh.select_all(action='SELECT')
        else:

            if not obj.material_slots:
                obj.data.materials.append(ensure_base_material())
            elif all(s.material is None for s in obj.material_slots):
                obj.data.materials[0] = ensure_base_material()
            idx = slot_index(obj, mat)
            _select_faces(obj, faces)

        obj.active_material_index = idx
        bpy.ops.object.material_slot_assign()

        uv_done = False
        need_uv = force_uv or (auto_uv and not obj.data.uv_layers)
        if need_uv:
            bpy.ops.uv.smart_project(island_margin=0.02)
            uv_done = True

        bpy.ops.object.mode_set(mode='OBJECT')
    return uv_done


class QUICKTEXTURE_OT_apply(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "选择贴图并应用"
    bl_description = "给整个物体或仅给选中的面自动建材质、挂贴图，缺 UV 时自动展开"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(name="贴图文件", subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tif;*.tiff;*.webp;*.exr",
        options={'HIDDEN'},
    )
    target_mode: bpy.props.EnumProperty(
        name="贴图范围",
        items=(('AUTO', "自动判断", "编辑模式下有选中面就只给选中面上贴图，否则整个物体"),
               ('OBJECT', "整个物体", "忽略面选择，整件一个材质"),
               ('FACES', "仅选中面", "只把贴图给到选中的那些面（需要先进编辑模式选面）")),
        default='AUTO',
    )
    auto_uv: bpy.props.BoolProperty(name="自动展开 UV", default=True,
                                    description="没有 UV 时自动做一次智能 UV 展开")
    force_uv: bpy.props.BoolProperty(name="强制重算 UV", default=False,
                                     description="不管有没有 UV，都重新展开一次")
    mat_mode: bpy.props.EnumProperty(
        name="材质方式",
        items=(('SHARED', "全体共用一个材质", "选中物体共用一份材质，改一处全变"),
               ('PER_OBJECT', "每个物体独立材质", "各建各的，互不影响")),
        default='SHARED',
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "filepath")
        layout.prop(self, "target_mode")
        layout.prop(self, "auto_uv")
        layout.prop(self, "force_uv")
        layout.prop(self, "mat_mode")

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "//"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        edit_sel = collect_edit_selection()
        if context.mode == 'EDIT_MESH':
            targets = list(edit_sel.keys()) or [o for o in context.selected_objects if o.type in MESH_TYPES] or [context.active_object]
        else:
            targets = [o for o in context.selected_objects if o.type in MESH_TYPES and o.data is not None]

        targets = [o for o in targets if o is not None and o.type in MESH_TYPES and o.data is not None]
        if not targets:
            self.report({'WARNING'}, "没有可用的网格对象")
            return {'CANCELLED'}
        if not self.filepath or not os.path.isfile(bpy.path.abspath(self.filepath)):
            self.report({'ERROR'}, "贴图路径无效")
            return {'CANCELLED'}

        mode = self.target_mode
        if mode == 'AUTO':
            mode = 'FACES' if edit_sel else 'OBJECT'
        if mode == 'FACES' and not any(obj in edit_sel for obj in targets):
            self.report({'WARNING'}, "没有选中任何面：先进编辑模式选面，或把范围改成「整个物体」")
            return {'CANCELLED'}

        try:
            image = load_image(bpy.path.abspath(self.filepath))
        except Exception as exc:
            self.report({'ERROR'}, f"读图失败: {exc}")
            return {'CANCELLED'}

        base_name = os.path.splitext(os.path.basename(image.filepath) or image.name)[0]
        done, uv_done, face_done = 0, 0, 0
        for obj in targets:
            faces = edit_sel.get(obj) if mode == 'FACES' else None
            mat_name = base_name if self.mat_mode == 'SHARED' else f"{base_name}_{obj.name}"
            try:
                mat = ensure_material(mat_name)
                ensure_image_node(mat, image)
                if apply_to_object(context, obj, mat, faces, self.auto_uv, self.force_uv):
                    uv_done += 1
                done += 1
                if faces:
                    face_done += len(faces)
            except Exception as exc:
                utils.report("WARNING", f"{obj.name} 贴图失败: {exc}")

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D' and space.shading.type != 'MATERIAL':
                        space.shading.type = 'MATERIAL'

        tip = f"（{face_done} 个面）" if mode == 'FACES' else ""
        utils.report("INFO", f"{done} 个对象已贴图《{base_name}》{tip}，其中 {uv_done} 个自动展了 UV")
        return {'FINISHED'}


classes = (QUICKTEXTURE_OT_apply,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
