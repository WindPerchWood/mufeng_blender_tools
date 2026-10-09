import bpy
from mathutils import Vector


ATTR_TRIGGER = "mf_fg_trigger"
ATTR_AXIS = "mf_fg_axis"
ATTR_ORIGIN = "mf_fg_origin"
ATTR_PIVOT = "mf_fg_pivot"

NG_NAME = "MF_TileGrowth"
MOD_NAME = "MF 地板生长(烘焙)"
MARK = "mf_fg_baked"
SRC_MARK = "mf_fg_baked_src"


def _roll_fwd(params):
    up = Vector((0.0, 0.0, 1.0))
    rd = params.get("roll_dir", None)
    if rd is not None:
        v = Vector(rd)
        if v.length > 1e-9:
            v = v - up * v.dot(up)
            if v.length > 1e-9:
                return v.normalized()
    return Vector((1.0, 0.0, 0.0))


def _obj_half_along(ob, params):
    fwd = _roll_fwd(params)
    mw = ob.matrix_world
    if not (ob.data and hasattr(ob.data, "vertices")) or not len(ob.data.vertices):
        d = ob.dimensions
        return max(d.x, d.y) * 0.5
    pts = [mw @ v.co for v in ob.data.vertices]
    c = Vector((0.0, 0.0, 0.0))
    for p in pts:
        c += p
    c /= len(pts)
    half = 0.0
    for p in pts:
        half = max(half, abs((p - c).dot(fwd)))
    return half if half > 1e-6 else 0.5


def _obj_min_z_world(ob):
    mw = ob.matrix_world
    if not (ob.data and hasattr(ob.data, "vertices")) or not len(ob.data.vertices):
        return mw.translation.z
    return min((mw @ v.co).z for v in ob.data.vertices)


def compute_baked_data(centers, plan_items, params):
    up = Vector((0.0, 0.0, 1.0))
    roll_dir = params.get("roll_dir", None)
    origin = Vector(params.get("origin", (0.0, 0.0, 0.0)))
    out = []
    for c, item in zip(centers, plan_items):
        c_w = Vector(c)

        fwd = None
        if roll_dir is not None:
            rd = Vector(roll_dir)
            if rd.length > 1e-9:
                rd = rd - up * rd.dot(up)
                if rd.length > 1e-9:
                    fwd = rd.normalized()
        if fwd is None:
            rd = Vector((c_w.x - origin.x, c_w.y - origin.y, 0.0))
            if rd.length > 1e-9:
                fwd = rd.normalized()
        if fwd is None:
            fwd = Vector((1.0, 0.0, 0.0))

        ax_n = up.cross(fwd)
        if ax_n.length < 1e-9:
            ax_n = Vector((0.0, 1.0, 0.0))
        ax_n.normalize()

        half = float(params.get("tile_half_fwd", 0.5))
        ground_z = float(params.get("tile_ground_z", c_w.z - half))
        pivot = Vector((c_w.x - fwd.x * half,
                        c_w.y - fwd.y * half,
                        ground_z))

        out.append({
            "pos": (c_w.x, c_w.y, c_w.z),
            "trigger": float(item["flip_start"]),
            "axis": (ax_n.x, ax_n.y, ax_n.z),
            "pivot": (pivot.x, pivot.y, pivot.z),
        })
    return out


def create_point_cloud(name, baked):
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata([b["pos"] for b in baked], [], [])
    mesh.update()

    attr_t = mesh.attributes.new(name=ATTR_TRIGGER, type='FLOAT', domain='POINT')
    attr_a = mesh.attributes.new(name=ATTR_AXIS, type='FLOAT_VECTOR', domain='POINT')
    attr_p = mesh.attributes.new(name=ATTR_PIVOT, type='FLOAT_VECTOR', domain='POINT')
    attr_o = mesh.attributes.new(name=ATTR_ORIGIN, type='FLOAT_VECTOR', domain='POINT')

    for i, b in enumerate(baked):
        attr_t.data[i].value = b["trigger"]
        attr_a.data[i].vector = b["axis"]
        attr_p.data[i].vector = b["pivot"]
        attr_o.data[i].vector = b["pos"]

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj[MARK] = True
    return obj, mesh


def build_node_group(ng_name=NG_NAME):
    old = bpy.data.node_groups.get(ng_name)
    if old is not None:
        bpy.data.node_groups.remove(old)

    ng = bpy.data.node_groups.new(ng_name, 'GeometryNodeTree')

    iface = ng.interface
    iface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    iface.new_socket("Instance", in_out='INPUT', socket_type='NodeSocketObject')
    iface.new_socket("Per Tile Frames", in_out='INPUT', socket_type='NodeSocketFloat')
    iface.new_socket("Flip Angle", in_out='INPUT', socket_type='NodeSocketFloat')
    iface.new_socket("Tile Half Fwd", in_out='INPUT', socket_type='NodeSocketFloat')
    iface.new_socket("Realize", in_out='INPUT', socket_type='NodeSocketBool')
    iface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    gin = ng.nodes.new("NodeGroupInput")
    gout = ng.nodes.new("NodeGroupOutput")
    gin.location = (-1200, 0)
    gout.location = (900, 0)

    time_n = ng.nodes.new("GeometryNodeInputSceneTime")
    time_n.location = (-1200, -300)

    a_trig = ng.nodes.new("GeometryNodeInputNamedAttribute")
    a_trig.data_type = 'FLOAT'
    a_trig.inputs["Name"].default_value = ATTR_TRIGGER
    a_trig.location = (-1000, -150)

    a_axis = ng.nodes.new("GeometryNodeInputNamedAttribute")
    a_axis.data_type = 'FLOAT_VECTOR'
    a_axis.inputs["Name"].default_value = ATTR_AXIS
    a_axis.location = (-1000, -420)

    a_pivot = ng.nodes.new("GeometryNodeInputNamedAttribute")
    a_pivot.data_type = 'FLOAT_VECTOR'
    a_pivot.inputs["Name"].default_value = ATTR_PIVOT
    a_pivot.location = (-1000, -620)

    a_origin = ng.nodes.new("GeometryNodeInputNamedAttribute")
    a_origin.data_type = 'FLOAT_VECTOR'
    a_origin.inputs["Name"].default_value = ATTR_ORIGIN
    a_origin.location = (-1000, -820)

    sub = ng.nodes.new("ShaderNodeMath")
    sub.operation = 'SUBTRACT'
    sub.location = (-700, -150)
    ng.links.new(time_n.outputs["Frame"], sub.inputs[0])
    ng.links.new(a_trig.outputs["Attribute"], sub.inputs[1])

    div = ng.nodes.new("ShaderNodeMath")
    div.operation = 'DIVIDE'
    div.location = (-500, -150)
    ng.links.new(sub.outputs["Value"], div.inputs[0])
    ng.links.new(gin.outputs["Per Tile Frames"], div.inputs[1])

    clp = ng.nodes.new("ShaderNodeMath")
    clp.operation = 'MAXIMUM'
    clp.location = (-300, -150)
    clp.inputs[1].default_value = 0.0
    ng.links.new(div.outputs["Value"], clp.inputs[0])

    clp2 = ng.nodes.new("ShaderNodeMath")
    clp2.operation = 'MINIMUM'
    clp2.location = (-100, -150)
    clp2.inputs[1].default_value = 1.0
    ng.links.new(clp.outputs["Value"], clp2.inputs[0])

    mul_ang = ng.nodes.new("ShaderNodeMath")
    mul_ang.operation = 'MULTIPLY'
    mul_ang.location = (100, -150)
    ng.links.new(clp2.outputs["Value"], mul_ang.inputs[0])
    ng.links.new(gin.outputs["Flip Angle"], mul_ang.inputs[1])

    sub_off = ng.nodes.new("ShaderNodeMath")
    sub_off.operation = 'SUBTRACT'
    sub_off.location = (300, -150)
    ng.links.new(mul_ang.outputs["Value"], sub_off.inputs[0])
    ng.links.new(gin.outputs["Flip Angle"], sub_off.inputs[1])

    to_rad = ng.nodes.new("ShaderNodeMath")
    to_rad.operation = 'RADIANS'
    to_rad.location = (500, -150)
    ng.links.new(sub_off.outputs["Value"], to_rad.inputs[0])

    axrot = ng.nodes.new("FunctionNodeAxisAngleToRotation")
    axrot.location = (640, -420)
    ng.links.new(a_axis.outputs["Attribute"], axrot.inputs["Axis"])
    ng.links.new(to_rad.outputs["Value"], axrot.inputs["Angle"])

    v_sub = ng.nodes.new("ShaderNodeVectorMath")
    v_sub.operation = 'SUBTRACT'
    v_sub.location = (-700, -650)
    ng.links.new(a_pivot.outputs["Attribute"], v_sub.inputs[0])
    ng.links.new(a_origin.outputs["Attribute"], v_sub.inputs[1])

    v_rot = ng.nodes.new("ShaderNodeVectorRotate")
    v_rot.rotation_type = 'AXIS_ANGLE'
    v_rot.location = (-500, -700)
    v_rot.invert = False
    ng.links.new(v_sub.outputs["Vector"], v_rot.inputs["Vector"])
    ng.links.new(a_axis.outputs["Attribute"], v_rot.inputs["Axis"])
    ng.links.new(to_rad.outputs["Value"], v_rot.inputs["Angle"])

    v_delta = ng.nodes.new("ShaderNodeVectorMath")
    v_delta.operation = 'SUBTRACT'
    v_delta.location = (-300, -700)
    ng.links.new(v_sub.outputs["Vector"], v_delta.inputs[0])
    ng.links.new(v_rot.outputs["Vector"], v_delta.inputs[1])

    setpos = ng.nodes.new("GeometryNodeSetPosition")
    setpos.location = (300, -500)
    ng.links.new(gin.outputs["Geometry"], setpos.inputs["Geometry"])
    ng.links.new(v_delta.outputs["Vector"], setpos.inputs["Offset"])

    oi = ng.nodes.new("GeometryNodeObjectInfo")
    oi.location = (380, 260)
    oi.inputs["As Instance"].default_value = True
    ng.links.new(gin.outputs["Instance"], oi.inputs["Object"])

    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    inst.location = (600, 0)
    ng.links.new(setpos.outputs["Geometry"], inst.inputs["Points"])
    ng.links.new(oi.outputs["Geometry"], inst.inputs["Instance"])
    ng.links.new(axrot.outputs["Rotation"], inst.inputs["Rotation"])

    realize = ng.nodes.new("GeometryNodeRealizeInstances")
    realize.location = (760, 0)
    ng.links.new(inst.outputs["Instances"], realize.inputs["Geometry"])

    sw = ng.nodes.new("GeometryNodeSwitch")
    sw.input_type = 'GEOMETRY'
    sw.location = (940, 0)
    ng.links.new(gin.outputs["Realize"], sw.inputs["Switch"])
    ng.links.new(inst.outputs["Instances"], sw.inputs["False"])
    ng.links.new(realize.outputs["Geometry"], sw.inputs["True"])

    ng.links.new(sw.outputs["Output"], gout.inputs["Geometry"])

    return ng


def _find_iface_socket(ng, socket_name, in_out='INPUT'):
    iface = ng.interface
    for item in iface.items_tree:
        if getattr(item, "item_type", None) != 'SOCKET':
            continue
        if getattr(item, "in_out", None) != in_out:
            continue
        if getattr(item, "name", None) == socket_name:
            return item
    return None


def _set_mod_input(mod, ng, socket_name, value, in_out='INPUT'):
    target = _find_iface_socket(ng, socket_name, in_out)
    if target is None:
        return False
    key = getattr(target, "identifier", None)
    if not key:
        return False
    sock = getattr(mod.properties.inputs, key, None)
    if sock is None or not hasattr(sock, "value"):
        return False
    try:
        sock.value = value
        return True
    except Exception:
        return False


def read_mod_input(mod, ng, socket_name, in_out='INPUT'):
    target = _find_iface_socket(ng, socket_name, in_out)
    if target is None:
        return None
    key = getattr(target, "identifier", None)
    sock = getattr(mod.properties.inputs, key, None) if key else None
    if sock is None or not hasattr(sock, "value"):
        return None
    try:
        return sock.value
    except Exception:
        return None


def apply_baking(context, source_objs, plan_items, params, centers,
                 brick_obj=None, name="MF_BakedCloud", realize=True):
    if brick_obj is None:
        brick_obj = source_objs[0] if source_objs else None

    half = 0.5
    ground_z = 0.0
    if brick_obj is not None:
        half = _obj_half_along(brick_obj, params)
        ground_z = _obj_min_z_world(brick_obj)

    p2 = dict(params)
    p2["tile_half_fwd"] = half
    p2["tile_ground_z"] = ground_z
    p2.setdefault("origin", (0.0, 0.0, 0.0))

    baked = compute_baked_data(centers, plan_items, p2)

    cloud, mesh = create_point_cloud(name, baked)

    ng = build_node_group()

    mod = cloud.modifiers.new(MOD_NAME, 'NODES')
    mod.node_group = ng

    _set_mod_input(mod, ng, "Instance", brick_obj)
    _set_mod_input(mod, ng, "Per Tile Frames", float(params.get("per_tile_frames", 6)))
    _set_mod_input(mod, ng, "Flip Angle", float(params.get("flip_angle", 90.0)))
    _set_mod_input(mod, ng, "Tile Half Fwd", float(half))
    _set_mod_input(mod, ng, "Realize", bool(realize))

    for ob in source_objs:
        ob[SRC_MARK] = True
        ob.hide_viewport = True
        ob.hide_render = True

    return {"cloud": cloud, "mesh": mesh, "node_group": ng, "modifier": mod,
            "count": len(baked), "realize": bool(realize)}


def _cloud_sources(clouds):
    out = {}
    for ob in clouds:
        for mod in ob.modifiers:
            if mod.type != 'NODES' or mod.node_group is None:
                continue
            src = read_mod_input(mod, mod.node_group, "Instance")
            if src is not None:
                out[src.name] = src
    return out


def _restore_source(ob):
    ob.hide_viewport = False
    ob.hide_render = False
    if SRC_MARK in ob:
        try:
            del ob[SRC_MARK]
        except Exception:
            pass


def clear_baking(objs=None, clouds=None):
    if clouds is None:
        clouds = [o for o in bpy.data.objects if o.get(MARK)]

    targets = _cloud_sources(clouds)

    removed = 0
    for ob in clouds:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed += 1
        except Exception:
            pass

    ng = bpy.data.node_groups.get(NG_NAME)
    if ng is not None:
        try:
            bpy.data.node_groups.remove(ng)
        except Exception:
            pass

    if objs is None:
        objs = [o for o in bpy.data.objects if o.get(SRC_MARK)]
    for ob in objs:
        targets[ob.name] = ob

    for ob in targets.values():
        _restore_source(ob)

    return removed


def find_baked_clouds(scene=None):
    if scene is None:
        scene = bpy.context.scene
    return [o for o in scene.objects if o.get(MARK)]
