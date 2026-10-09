import bpy, sys, os, json, re, importlib, addon_utils
from math import pi

R = {}
FAIL = []

def chk(name, cond, extra=""):
    R[name] = ("PASS" if cond else "FAIL") + ((" | " + str(extra)) if extra else "")
    if not cond:
        FAIL.append(name)


def report(name, result, ok_status=True):
    status, msg = result
    chk(name, status == ('FINISHED' if ok_status else 'CANCELLED'), status + " | " + str(msg))
    return status


ADDON_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

try:
    addon_utils.enable(ADDON_NAME, default_set=False, persistent=False)
    chk("enable_addon", True)
except Exception as e:
    try:
        parent = os.path.dirname(os.path.abspath(__file__))
        if parent not in sys.path:
            sys.path.append(parent)
        importlib.import_module(ADDON_NAME).register()
        chk("enable_addon", True, "fallback: sys.path import（无 bl_info 属预期）")
    except Exception as e2:
        chk("enable_addon", False, repr(e) + " / fallback: " + repr(e2))
        print("JSON_START"); print(json.dumps(R, ensure_ascii=False, indent=1)); print("JSON_END")
        sys.exit(1)

mod = importlib.import_module(ADDON_NAME + ".operators")
ui_mod = importlib.import_module(ADDON_NAME + ".ui")
ops_src = open(mod.__file__, encoding="utf-8").read()
panel_src = open(ui_mod.__file__, encoding="utf-8").read()

OPS_NS = getattr(bpy.ops, "mf")
REGISTERED_OPS = set(dir(OPS_NS))
op_exists = lambda short: short in REGISTERED_OPS

chk("panel.registered", hasattr(bpy.types, "MF_PT_Camera"))
chk("panel.inherits_search_base",
    "class MF_PT_Camera(utils.MF_ToolPanel):" in panel_src)
chk("scene.prop.attached", hasattr(bpy.context.scene, mod.SCENE_PROP),
    mod.SCENE_PROP)
chk("menu.appended", hasattr(bpy.types, "VIEW3D_MT_view_cameras"))

OP_NAMES = [n for n in dir(mod) if n.startswith("MF_OT_") and n != "MF_OT_Base"]
missing = [getattr(mod, n).bl_idname for n in OP_NAMES
           if not op_exists(getattr(mod, n).bl_idname.split(".", 1)[1])]
chk("ops.all_registered", not missing, "%d个/缺失%s" % (len(OP_NAMES), missing))
chk("ops.count_is_4", len(OP_NAMES) == 4, sorted(OP_NAMES))
chk("ops.idname_prefix", all(getattr(mod, n).bl_idname.startswith("mf.") for n in OP_NAMES))
chk("ops.no_conflict_with_native",
    not any(getattr(mod, n).bl_idname.startswith("camera.") for n in OP_NAMES))
chk("naming.ot_prefix", all(n.startswith("MF_OT_") for n in OP_NAMES))
chk("classes.tuple_count", len(mod.classes) == 5, len(mod.classes))
chk("ui.classes.tuple_count", len(ui_mod.classes) == 1, len(ui_mod.classes))

chk("pg.target_pick.in_rna",
    "target_pick" in set(mod.MF_PG_Settings.bl_rna.properties.keys()))
chk("pg.target_pick.callback_defined", callable(getattr(mod, "on_pick_prop", None)))

used_icons = sorted(set(re.findall(r"icon='([A-Z0-9_]+)'", ops_src + panel_src)))
enum = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
chk("panel.icons_exist", all(i in enum for i in used_icons),
    "用到%s / 缺失%s" % (used_icons, [i for i in used_icons if i not in enum]))

REMOVED = ['cam_create_from_view', 'cam_create_dof_target', 'cam_select_dof_target',
           'cam_dof_picker', 'cam_set_active', 'cam_select', 'cam_lock_to_view',
           'cam_select_active', 'cam_show_safe_area',
           'cam_select_target', 'cam_align_target', 'cam_pick_target']
chk("removed.ops_gone",
    not any(op_exists(n) for n in REMOVED),
    [n for n in REMOVED if op_exists(n)])

chk("removed.no_ray_cast_import", 'region_2d_to_vector_3d' not in ops_src)
chk("removed.no_boolproperty_import", 'BoolProperty' not in ops_src)
chk("removed.no_view3d_ops",
    'bpy.ops.view3d' not in ops_src and 'bpy.ops.object.camera_add' not in ops_src)

psrc = panel_src.split("class MF_PT_Camera")[1]
menu_src = psrc.split("def _extend_camera_menu")[1]
panel_body = psrc.split("def _extend_camera_menu")[0]
panel_ops = re.findall(r'MF_OT_(\w+)\.bl_idname', panel_body)
menu_ops = re.findall(r'MF_OT_(\w+)\.bl_idname', menu_src)

chk("menu.only_target_items",
    menu_ops == ['TargetAdd', 'TargetDrop'], menu_ops)
chk("panel.has_all_buttons",
    all(x in panel_ops for x in ['Add', 'Add', 'TargetAdd', 'TargetDrop', 'Lock']),
    panel_ops)
ANCHOR_CAM_VIEW = 'box.label(text="相机视图"'
ANCHOR_TARGET = 'box.label(text="目标点 Target"'
chk("panel.camera_view_section_found", panel_body.count(ANCHOR_CAM_VIEW) == 1)
cam_view = panel_body.split(ANCHOR_CAM_VIEW)[-1]
chk("panel.camera_view_only_lock", 'MF_OT_Lock.bl_idname' in cam_view
    and 'MF_OT_TargetAdd.bl_idname' not in cam_view
    and 'MF_OT_TargetDrop.bl_idname' not in cam_view)
target_view = panel_body.split(ANCHOR_TARGET)[-1].split(ANCHOR_CAM_VIEW)[0]
chk("panel.target_section_ops",
    'MF_OT_TargetAdd.bl_idname' in target_view and 'MF_OT_TargetDrop.bl_idname' in target_view)
chk("panel.picker_is_property", 'col.prop(settings, "target_pick"' in target_view)
chk("panel.picker_has_label", '拾取物体作为目标' in target_view)
chk("panel.default_closed", "bl_options = {'DEFAULT_CLOSED'}" in panel_body)
chk("panel.category_uses_core",
    'bl_category = utils.PANEL_CATEGORY' in panel_body)
chk("panel.order_set", re.search(r"bl_order\s*=\s*\d+", panel_body) is not None)
chk("panel.search_keywords", "MF_SEARCH_KEYWORDS" in panel_body)
_forbidden = "".join(("m", "a", "x"))
chk("naming.no_max_wording",
    not re.search(_forbidden, (ops_src + panel_src).lower()),
    sorted(set(re.findall(r"\S*" + _forbidden + r"\S*", (ops_src + panel_src).lower(), re.I)))[:5])

scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
chk("scene.cleared", len(bpy.data.objects) == 0, len(bpy.data.objects))
chk("scene.no_camera", scene.camera is None)
scene.cursor.location = (0.0, 0.0, 0.0)

cube = bpy.data.objects.new("SomeObject", bpy.data.meshes.new("SomeObject"))
scene.collection.objects.link(cube)
cube.location = (5.0, 5.0, 2.0)


class FakeCtx:
    def __init__(self, scene, active=None):
        self.scene = scene
        self.view_layer = bpy.context.view_layer
        if active is not None:
            self.set_active(active)

    def set_active(self, obj):
        for o in list(bpy.context.view_layer.objects):
            if o is not None:
                o.select_set(False)
        if obj is not None:
            obj.select_set(True)
        self.view_layer.objects.active = obj

    def clear(self):
        self.set_active(None)

    @property
    def active_object(self):
        return self.view_layer.objects.active

    @property
    def selected_objects(self):
        return [o for o in self.view_layer.objects if o is not None and o.select_get()]

    def __getattr__(self, _n):
        return None


class S:
    def __init__(self, v=None):
        self.target_pick = v


ctx = FakeCtx(scene, None)

report("add_camera.free", mod.core_add(ctx, False))
cam = ctx.active_object
chk("add_camera.created", cam is not None and cam.type == 'CAMERA')
chk("add_camera.auto_active_when_none", scene.camera is cam)
chk("add_camera.rotation_mode_xyz", cam.rotation_mode == 'XYZ', cam.rotation_mode)
chk("add_camera.level_orientation",
    abs(cam.rotation_euler.x - pi / 2.0) < 1e-6 and abs(cam.rotation_euler.z) < 1e-6,
    tuple(cam.rotation_euler))
chk("add_camera.at_cursor", cam.location.length < 1e-6, tuple(cam.location))
cam.location = (0.0, 0.0, 10.0)

report("add_camera.target", mod.core_add(ctx, True))
cam2 = ctx.active_object
chk("add_camera.target_distinct", cam2 is not cam)
chk("add_camera.target_has_lookat", mod.find_track(cam2) is not None)
chk("add_camera.target_tagged",
    mod.find_track(cam2).target.get(mod.MARK_AUTO_TARGET) == 1)
report("add_camera.target_clear", mod.core_untarget(ctx))
chk("add_camera.target_recycled",
    mod.find_track(cam2) is None
    and len([o for o in bpy.data.objects if o.get(mod.MARK_AUTO_TARGET)]) == 0)
bpy.data.objects.remove(cam2, do_unlink=True)
ctx.set_active(cam)

report("create_target", mod.core_target(ctx))
con = mod.find_track(cam)
chk("create_target.constraint", con is not None)
chk("create_target.axes", (con.track_axis, con.up_axis) == ('TRACK_NEGATIVE_Z', 'UP_Y'),
    (con.track_axis, con.up_axis))
tgt = con.target
chk("create_target.empty_name", tgt.name.endswith("_target"), tgt.name)
chk("create_target.is_empty", tgt.type == 'EMPTY')
chk("create_target.tagged", tgt.get(mod.MARK_AUTO_TARGET) == 1)
chk("create_target.display_size_synced",
    abs(tgt.empty_display_size - cam.data.display_size / 10.0) < 1e-6, tgt.empty_display_size)
chk("is_lookat.true", mod.find_track(cam) is not None)

d = mod.dot_distance(cam)
chk("target_distance.value", d is not None and abs(d - cam.data.display_size * 3.0) < 1e-4, d)
chk("create_target.at_front_point",
    (tgt.matrix_world.to_translation() - mod.ahead_of(cam, cam.data.display_size * 3.0)).length < 1e-4)
report("create_target.reject_duplicate", mod.core_target(ctx), ok_status=False)

report("clear_target", mod.core_untarget(ctx))
chk("clear_target.no_constraint", mod.find_track(cam) is None)
chk("clear_target.real_object_survives", cube.name in bpy.data.objects)
chk("clear_target.is_free", mod.find_track(cam) is None)
report("clear_target.reject_when_free", mod.core_untarget(ctx), ok_status=False)

scene.camera = cam
ctx.set_active(cube)
settings = getattr(scene, mod.SCENE_PROP)

report("pick.create_auto_target", mod.core_target(ctx))
auto_name = mod.find_track(cam).target.name
chk("pick.auto_target_exists", auto_name in bpy.data.objects)

settings.target_pick = cube
con_p = mod.find_track(cam)
chk("pick.retargeted", con_p is not None and con_p.target is cube,
    con_p and con_p.target.name)
chk("pick.orphan_recycled", auto_name not in bpy.data.objects, auto_name)
chk("pick.field_cleared_after_use", settings.target_pick is None,
    settings.target_pick and settings.target_pick.name)

report("pick.clear_before_repeat", mod.core_untarget(ctx))
chk("pick.is_free_before_repeat", mod.find_track(cam) is None)
settings.target_pick = cube
con_p2 = mod.find_track(cam)
chk("pick.same_object_again", con_p2 is not None and con_p2.target is cube,
    con_p2 and con_p2.target.name)

settings.target_pick = cam
chk("pick.self_ignored", mod.find_track(cam).target is cube)
chk("pick.self_field_cleared", settings.target_pick is None)

mod.core_untarget(ctx)
scene_cam_backup = scene.camera
scene.camera = None
ctx.clear()
mod.on_pick_prop(S(cube), ctx)
chk("pick_cb.no_camera_noop", mod.find_track(cam) is None)
scene.camera = scene_cam_backup
ctx.set_active(cam)

mod.on_pick_prop(S(None), ctx)
chk("pick_cb.none_noop", mod.find_track(cam) is None)
mod.on_pick_prop(S(cam), ctx)
chk("pick_cb.self_noop", mod.find_track(cam) is None)
mod.on_pick_prop(S(cube), None)
chk("pick_cb.no_ctx_noop", mod.find_track(cam) is None)

report("create_target.suffixed", mod.core_target(ctx))
t_a = mod.find_track(cam).target
blocker = bpy.data.objects.new("blocker", None)
scene.collection.objects.link(blocker)
t_a.name = "tmp_hold"
blocker.name = "Camera_target"
t_a.name = "Camera_target"
suffixed = t_a.name
chk("auto_target.blender_adds_suffix", re.search(r"\.\d+$", suffixed) is not None, suffixed)
chk("auto_target.suffix_keeps_tag", bool(t_a.get(mod.MARK_AUTO_TARGET)), suffixed)
report("clear_target.suffixed", mod.core_untarget(ctx))
chk("clear_target.suffixed_removed", suffixed not in bpy.data.objects, suffixed)
chk("clear_target.cube_still_there", cube.name in bpy.data.objects)
bpy.data.objects.remove(blocker, do_unlink=True)

decoy = bpy.data.objects.new("Camera_target", None)
scene.collection.objects.link(decoy)
chk("cleanup.ignores_untagged_decoy", mod.sweep_dots() == 0)
chk("cleanup.decoy_survives", decoy.name in bpy.data.objects)
bpy.data.objects.remove(decoy, do_unlink=True)

report("create_target.untagged", mod.core_target(ctx))
t_u = mod.find_track(cam).target
del t_u[mod.MARK_AUTO_TARGET]
report("clear_target.untagged", mod.core_untarget(ctx))
chk("clear_target.untagged_survives", t_u.name in bpy.data.objects, t_u.name)
chk("cleanup.untagged_not_swept", t_u.name in bpy.data.objects)
bpy.data.objects.remove(t_u, do_unlink=True)

scene.camera = cam
report("lock_transform.on", mod.core_lock(ctx))
chk("lock_transform.all_locked",
    cam.lock_location[0] and cam.lock_rotation[0] and cam.lock_scale[0])
report("lock_transform.off", mod.core_lock(ctx))
chk("lock_transform.unlocked", not cam.lock_location[0])


def edge(name, fn, expect=None):
    try:
        v = fn()
        chk("edge." + name, (v == expect) if expect is not None else True, v)
    except Exception as e:
        chk("edge." + name, False, "抛异常 " + repr(e))


edge("is_lookat.None", lambda: mod.find_track(None) is None, True)
edge("is_lookat.mesh", lambda: mod.find_track(cube) is None, True)
edge("is_owned_dot.None", lambda: mod.is_owned_dot(None), False)
edge("is_owned_dot.mesh", lambda: mod.is_owned_dot(cube), False)
edge("is_claimed.cube", lambda: mod.is_claimed(cube), False)
edge("pick_camera.no_camera", lambda: mod.pick_camera(FakeCtx(scene, None)) is None, True)
edge("dot_distance.no_lookat", lambda: mod.dot_distance(cube) is None, True)

backup = scene.camera
scene.camera = None
empty = FakeCtx(scene, None)
empty.clear()
edge("pick_camera.empty_falls_back", lambda: mod.pick_camera(empty) is None, True)
edge("create_target.no_camera", lambda: mod.core_target(empty)[0], 'CANCELLED')
edge("clear_target.no_camera", lambda: mod.core_untarget(empty)[0], 'CANCELLED')
edge("lock_transform.no_camera", lambda: mod.core_lock(empty)[0], 'CANCELLED')
edge("add_camera.no_camera_ok", lambda: mod.core_add(empty, False)[0], 'FINISHED')
newcam = empty.active_object
chk("add_camera.sets_scene_camera_when_none", scene.camera is newcam)
bpy.data.objects.remove(newcam, do_unlink=True)
scene.camera = backup

ctx.set_active(cube)
edge("pick_camera.falls_back_to_scene", lambda: mod.pick_camera(ctx) is scene.camera, True)
ctx.set_active(cam)

edge("sweep.empty_scene", lambda: mod.sweep_dots(), 0)

try:
    addon_utils.disable(ADDON_NAME, default_set=False)
except Exception:
    pass
pkg = sys.modules.get(ADDON_NAME)
if pkg is not None and hasattr(bpy.types, "MF_PT_Camera"):
    pkg.unregister()
chk("unreg.panel", not hasattr(bpy.types, "MF_PT_Camera"))
chk("unreg.scene_prop", not hasattr(bpy.context.scene, mod.SCENE_PROP))
chk("unreg.propertygroup", not hasattr(bpy.types, "MF_PG_Settings"))
chk("unreg.op_class", not hasattr(bpy.types, "MF_OT_TargetAdd"))
chk("unreg.op_class_lock", not hasattr(bpy.types, "MF_OT_Lock"))

print("JSON_START")
print(json.dumps({"checks": R, "failed": FAIL,
                  "total": len(R), "fail_count": len(FAIL)}, ensure_ascii=False, indent=1))
print("JSON_END")
