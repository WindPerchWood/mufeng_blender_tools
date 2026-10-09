import bpy
from bpy.props import FloatProperty, PointerProperty


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

TOOL_ID = "Visibility"
OP_ID = "mf.visibility_set"
KEY_OP_ID = "mf.visibility_keyframe"
WM_ATTR = "mf_visibility"

DEFAULT_VALUE = 0.5


FADE_GROUP_NAME = "MF_Fade"
FADE_NODE_NAME = "MF_Fade"
FADE_SRC_PROP = "mf_fade_src"
FADE_FAKEUSER_PROP = "mf_fade_fakeuser"
FADE_SUFFIX = "_MF"
ALPHA_SOCK_NAME = "Alpha"


def alpha_socket_index(group_node):
    for i, sock in enumerate(group_node.inputs):
        if sock.name == ALPHA_SOCK_NAME:
            return i
    return None


def ensure_fade_group():
    ng = bpy.data.node_groups.get(FADE_GROUP_NAME)
    if ng is not None and ng.nodes.get('FadeMix') is not None:
        return ng
    if ng is not None:
        ng = None

    ng = bpy.data.node_groups.new(FADE_GROUP_NAME, 'ShaderNodeTree')
    ng.interface.new_socket('Shader', in_out='INPUT', socket_type='NodeSocketShader')
    alpha_item = ng.interface.new_socket(ALPHA_SOCK_NAME, in_out='INPUT',
                                         socket_type='NodeSocketFloat')
    alpha_item.default_value = 1.0
    alpha_item.min_value = 0.0
    alpha_item.max_value = 1.0
    ng.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')

    n_in = ng.nodes.new('NodeGroupInput')
    n_out = ng.nodes.new('NodeGroupOutput')
    n_trans = ng.nodes.new('ShaderNodeBsdfTransparent')
    n_mix = ng.nodes.new('ShaderNodeMixShader')
    n_mix.name = n_mix.label = 'FadeMix'

    ng.links.new(n_trans.outputs['BSDF'], n_mix.inputs[1])
    ng.links.new(n_in.outputs['Shader'], n_mix.inputs[2])
    ng.links.new(n_in.outputs[ALPHA_SOCK_NAME], n_mix.inputs['Fac'])
    ng.links.new(n_mix.outputs['Shader'], n_out.inputs['Shader'])
    return ng


def _insert_fade_into(mat_copy, group):
    if not mat_copy.use_nodes or mat_copy.node_tree is None:
        mat_copy.use_nodes = True
    tree = mat_copy.node_tree
    out = next((n for n in tree.nodes if n.bl_idname == 'ShaderNodeOutputMaterial'), None)
    if out is None:
        out = tree.nodes.new('ShaderNodeOutputMaterial')

    src_socket = None
    if out.inputs['Surface'].is_linked:
        src_socket = out.inputs['Surface'].links[0].from_socket

    node = tree.nodes.new('ShaderNodeGroup')
    node.node_tree = group
    node.name = node.label = FADE_NODE_NAME
    node.location = (out.location.x - 200.0, out.location.y)
    if src_socket is not None:
        tree.links.new(src_socket, node.inputs['Shader'])
    else:
        bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
        tree.links.new(bsdf.outputs['BSDF'], node.inputs['Shader'])
    tree.links.new(node.outputs['Shader'], out.inputs['Surface'])
    return node


def _make_fade_copy(mat, group):
    copy = mat.copy()
    copy.name = mat.name + FADE_SUFFIX
    copy[FADE_SRC_PROP] = mat.name

    if not mat.use_fake_user:
        mat.use_fake_user = True
        copy[FADE_FAKEUSER_PROP] = mat.name
    _insert_fade_into(copy, group)

    for attr_name, value in (('surface_render_method', 'BLENDED'),
                             ('blend_method', 'BLEND')):
        if hasattr(copy, attr_name):
            try:
                setattr(copy, attr_name, value)
            except Exception:
                pass
    return copy


def _fade_node(mat):
    if not mat.use_nodes or mat.node_tree is None:
        return None
    node = mat.node_tree.nodes.get(FADE_NODE_NAME)
    if node is None or node.bl_idname != 'ShaderNodeGroup':
        return None
    return node


def apply_fade(obj, value):
    group = ensure_fade_group()
    made = {}
    touched = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        if FADE_SRC_PROP in mat.keys():
            copy = mat
        else:
            copy = made.get(mat.name)
            if copy is None:
                copy = _make_fade_copy(mat, group)
                made[mat.name] = copy
            slot.material = copy
        node = _fade_node(copy) or _insert_fade_into(copy, group)
        node.inputs[ALPHA_SOCK_NAME].default_value = max(0.0, min(1.0, float(value)))
        touched.append(copy)
    return touched


def _is_animated(mat):
    tree = mat.node_tree
    ad = tree.animation_data if tree is not None else None
    return ad is not None and ad.action is not None


def clear_fade(obj, keep_animated=True):
    removed, kept = 0, 0
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or FADE_SRC_PROP not in mat.keys():
            continue
        if keep_animated and _is_animated(mat):
            node = _fade_node(mat)
            if node is not None:
                node.inputs[ALPHA_SOCK_NAME].default_value = 1.0
            kept += 1
            continue
        src = bpy.data.materials.get(str(mat[FADE_SRC_PROP]))
        if src is None:
            continue
        slot.material = src

        if (FADE_FAKEUSER_PROP in mat.keys()
                and str(mat[FADE_FAKEUSER_PROP]) == src.name
                and src.users > 0):
            src.use_fake_user = False
        if mat.users == 0:
            bpy.data.materials.remove(mat)
            removed += 1
    return removed, kept


def clear_hidden(obj, view_layer):
    obj.hide_viewport = False
    obj.hide_render = False
    try:
        obj.hide_set(False, view_layer=view_layer)
    except RuntimeError:
        pass


class MF_PG_VisibilitySettings(bpy.types.PropertyGroup):
    value: FloatProperty(
        name="可见性",
        description="只改材质透明度，不动任何隐藏开关：0 = 全透明；0~1 = 整物体淡出（保留贴图）；1 = 完全可见并恢复原样。透明效果在「材质预览」或「渲染」视图下可见，实体模式看不出",
        default=DEFAULT_VALUE,
        min=0.0,
        max=1.0,
        precision=2,
    )


class MF_OT_Visibility_Set(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "更改可见性"
    bl_description = ("把选中物体的可见性设为 0~1（只改材质透明度，贴图、颜色、多材质槽都保留）："
                      "0 = 全透明；0~1 = 淡出；1 = 完全可见并恢复原样。\n"
                      "物体始终留在场景里、视口里始终选得到，不会出现物体消失后找不到的情况；"
                      "要用真正隐藏（视口里点不到）就用大纲视图的「眼睛」栏\n"
                      "透明差异要在「材质预览」或「渲染」视图下才看得到，实体模式（Solid）是硬限制，看不出透明")
    bl_options = {'REGISTER', 'UNDO'}

    value: FloatProperty(
        name="可见性",
        description="0 = 全透明；0~1 = 整体淡出；1 = 完全可见",
        default=DEFAULT_VALUE,
        min=0.0,
        max=1.0,
        precision=2,
    )

    def execute(self, context):
        targets = list(context.selected_objects)
        if not targets:
            self.report({'WARNING'}, "没有选中任何物体")
            return {'CANCELLED'}

        value = max(0.0, min(1.0, float(self.value)))
        view_layer = context.view_layer
        done, faded, parked, failed = 0, 0, 0, []
        for obj in targets:
            try:
                clear_hidden(obj, view_layer)
                if value >= 1.0:
                    _, kept = clear_fade(obj)
                    parked += kept
                else:
                    faded += len(apply_fade(obj, value))
                done += 1
            except Exception as exc:
                failed.append(obj.name)
                utils.report("WARNING", f"{obj.name}: {exc}")

        if value >= 1.0:
            text = f"已把 {done} 个物体恢复成完全可见"
        elif faded:
            level = "全透明" if value <= 0.0 else "半透明"
            text = f"已把 {done} 个物体设为{level}（alpha={value:.2f}，含 {faded} 个材质槽）"
        else:
            text = f"{done} 个物体没有材质槽，无可淡出内容"
        if parked:
            text += f"；{parked} 个带关键帧的副本按原样保留（值已设回 1）"
        if failed:
            self.report({'WARNING'}, f"{text}，{len(failed)} 个失败")
        else:
            self.report({'INFO'}, text)
        return {'FINISHED'}


class MF_OT_Visibility_Keyframe(bpy.types.Operator):
    bl_idname = KEY_OP_ID
    bl_label = "打可见性关键帧"
    bl_description = ("在当前帧把选中物体的淡出值写成关键帧（0 = 全透明，1 = 完全可见），"
                      "换一帧再点一次即可做出渐隐/渐现动画。\n"
                      "和左边的「更改可见性」同一套值：都只驱动材质 alpha，不动任何隐藏开关，"
                      "也不会撤掉淡出副本；0 值时物体仍在原处，视口里照样能点中/框选，方便接着调曲线\n"
                      "透明差异要在「材质预览」或「渲染」视图下才看得到")
    bl_options = {'REGISTER', 'UNDO'}

    value: FloatProperty(
        name="可见性",
        description="0 = 全透明；0~1 = 半透明；1 = 完全可见",
        default=DEFAULT_VALUE,
        min=0.0,
        max=1.0,
        precision=2,
    )

    def execute(self, context):
        targets = list(context.selected_objects)
        if not targets:
            self.report({'WARNING'}, "没有选中任何物体")
            return {'CANCELLED'}

        scene = context.scene
        frame = scene.frame_current
        view_layer = context.view_layer
        value = max(0.0, min(1.0, float(self.value)))
        done, keys, failed = 0, 0, []
        for obj in targets:
            try:
                clear_hidden(obj, view_layer)

                mats = apply_fade(obj, value)
                marked = 0
                for mat in {m.name: m for m in mats}.values():
                    node = _fade_node(mat)
                    idx = alpha_socket_index(node) if node is not None else None
                    if idx is None or mat.node_tree is None:
                        continue

                    mat.node_tree.keyframe_insert(
                        data_path='nodes["%s"].inputs[%d].default_value' % (FADE_NODE_NAME, idx),
                        frame=frame)
                    marked += 1
                if marked:
                    done += 1
                    keys += marked
            except Exception as exc:
                failed.append(obj.name)
                utils.report("WARNING", f"{obj.name}: {exc}")

        text = (f"已在第 {frame} 帧给 {done} 个物体的淡出值打关键帧"
                f"（alpha={value:.2f}，共 {keys} 个材质槽）")
        if failed:
            self.report({'WARNING'}, f"{text}，{len(failed)} 个失败")
        else:
            self.report({'INFO'}, text)
        return {'FINISHED'}


classes = (MF_PG_VisibilitySettings, MF_OT_Visibility_Set, MF_OT_Visibility_Keyframe)


def register():
    utils.register_classes(classes)

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    setattr(bpy.types.WindowManager, WM_ATTR,
            PointerProperty(type=MF_PG_VisibilitySettings))


def unregister():

    if hasattr(bpy.types.WindowManager, WM_ATTR):
        delattr(bpy.types.WindowManager, WM_ATTR)
    utils.unregister_classes(classes)
