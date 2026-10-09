import bpy
import sys
import os
import re
import json

R = {}
FAIL = []


def chk(name, cond, extra=""):
    R[name] = ("PASS" if cond else "FAIL") + ((" | " + str(extra)) if extra else "")
    if not cond:
        FAIL.append(name)


ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(ADDON_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import spline

spline.register()

import spline.operators as mod
import spline.ui as uimod
from mathutils import Vector

OPS = dir(bpy.ops.mf) if hasattr(bpy.ops, "mf") else []
chk("ops.registered", "spline_line" in OPS and "spline_line_close" in OPS, sorted(OPS))
chk("state.module", isinstance(mod.STATE, dict) and "active_tool" in mod.STATE)

chk("no.scene_prop", not hasattr(bpy.context.scene, "mf_maxline_setting"))
chk("no.curve_prop", "mf_maxline_data" not in bpy.types.Curve.bl_rna.properties.keys())
chk("no.mesh_prop", "mf_maxline_data" not in bpy.types.Mesh.bl_rna.properties.keys())

OPS_CLASSES = [getattr(c, "bl_idname", "") for c in mod.classes]
chk("idname.mf_prefix", all(n.startswith("mf.") for n in OPS_CLASSES), OPS_CLASSES)
chk("idname.no_legacy_prefix",
    not any(n.split(".")[0] in {"create", "curve"} for n in OPS_CLASSES))

PANELS = [c for c in uimod.classes if issubclass(c, bpy.types.Panel)]
chk("panel.single", len(PANELS) == 1)
base_name = PANELS[0].__mro__[1].__name__
chk("panel.inherit",
    base_name in {"MF_ToolPanel", "Panel"},
    base_name)
chk("panel.category", PANELS[0].bl_category == "木风工具箱", PANELS[0].bl_category)
chk("panel.default_closed", 'DEFAULT_CLOSED' in PANELS[0].bl_options)
chk("panel.has_draw_header", hasattr(PANELS[0], "draw_header"))
chk("panel.has_keywords", bool(getattr(PANELS[0], "MF_SEARCH_KEYWORDS", ())))

src = ""
for fname in ("operators.py", "ui.py"):
    with open(os.path.join(ADDON_DIR, fname), encoding="utf-8") as fh:
        src += fh.read()
icons_used = set(re.findall(r"icon='([A-Z0-9_]+)'", src))
icons_enum = set(bpy.types.UILayout.bl_rna.functions["label"]
                 .parameters["icon"].enum_items.keys())
chk("icons.valid", icons_used <= icons_enum, sorted(icons_used - icons_enum))

imports = [ln.strip() for ln in src.splitlines() if ln.startswith(("import ", "from "))]
chk("deps.clean", not any(k in ln for ln in imports for k in ("numpy", "bsmax")), imports)

chk("no.max_reference",
    not re.search(r"maxline|max_line|3ds\s*max|MaxLine|Max创建", src, re.IGNORECASE))

lock = mod._lock_axis
chk("axis.x", tuple(lock(Vector((0, 0, 0)), Vector((5, 1, 1)))) == (5, 0, 0))
chk("axis.y", tuple(lock(Vector((0, 0, 0)), Vector((1, 5, 1)))) == (0, 5, 0))
chk("axis.z", tuple(lock(Vector((0, 0, 0)), Vector((1, 1, 5)))) == (0, 0, 5))
chk("axis.offset",
    tuple(lock(Vector((10, 10, 10)), Vector((12, 11, 11)))) == (12, 10, 10))

k = mod._smooth_knot(Vector((0, 0, 0)), Vector((2, 0, 0)))
chk("knot.mirror", k[1] == Vector((-2, 0, 0)) and k[2] == Vector((2, 0, 0))
    and k[3] == "ALIGNED")
chk("knot.corner",
    mod._corner_knot(Vector((1, 2, 3))) == (Vector((1, 2, 3)),) * 3 + ("VECTOR",))


class FakeCtx:
    def __init__(self, scene):
        self.scene = scene
        self.view_layer = bpy.context.view_layer

    @property
    def selected_objects(self):
        return [o for o in self.view_layer.objects if o.select_get()]

    def __getattr__(self, _n):
        return None


scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
ctx = FakeCtx(scene)

obj = mod._create_curve_object(ctx)
chk("obj.created", obj is not None and obj.type == "CURVE"
    and obj.name in bpy.data.objects)
chk("obj.active", ctx.view_layer.objects.active is obj)

knots = [mod._corner_knot(Vector((0, 0, 0))),
         mod._corner_knot(Vector((2, 0, 0))),
         mod._corner_knot(Vector((2, 2, 0)))]

mod._apply_shape(obj.data, knots, False)
sp = obj.data.splines[0]
chk("shape.count", len(sp.bezier_points) == 3, len(sp.bezier_points))
chk("shape.coord", (sp.bezier_points[1].co - Vector((2, 0, 0))).length < 1e-6)
chk("shape.open", sp.use_cyclic_u is False)
chk("shape.handle_type", sp.bezier_points[0].handle_right_type == "VECTOR")

mod._apply_shape(obj.data, knots, True)
chk("shape.cyclic", obj.data.splines[0].use_cyclic_u is True)

mod._apply_shape(obj.data, [], False)
chk("shape.empty_safe", len(obj.data.splines) == 1
    and len(obj.data.splines[0].bezier_points) == 1)

mod._apply_shape(obj.data, knots[:2], False)
chk("shape.rebuild_clears", len(obj.data.splines) == 1
    and len(obj.data.splines[0].bezier_points) == 2)

obj_name = obj.name
bpy.data.objects.remove(obj, do_unlink=True)
chk("obj.removed", obj_name not in bpy.data.objects)

spline.unregister()
LEFT_OPS = dir(bpy.ops.mf) if hasattr(bpy.ops, "mf") else []
chk("unreg.ops", "spline_line" not in LEFT_OPS and "spline_line_close" not in LEFT_OPS,
    sorted(LEFT_OPS))
chk("unreg.panel", not hasattr(bpy.types, "MF_PT_Spline"))
chk("unreg.scene_prop", not hasattr(bpy.context.scene, "mf_maxline_setting"))
chk("unreg.curve_prop",
    "mf_maxline_data" not in bpy.types.Curve.bl_rna.properties.keys())
chk("unreg.mesh_prop",
    "mf_maxline_data" not in bpy.types.Mesh.bl_rna.properties.keys())

print("JSON_START")
print(json.dumps({"checks": R, "failed": FAIL,
                  "total": len(R), "fail_count": len(FAIL)},
                 ensure_ascii=False, indent=1))
print("JSON_END")
