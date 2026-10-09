import bpy

from . import cube_overlay

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
    )

from .operators import PICK_ID


class MF_GZ_ViewCube(bpy.types.Gizmo):
    bl_idname = "MF_GZ_ViewCube"

    def draw(self, context):
        pass

    def draw_select(self, context, select_id):
        pass

    def test_select(self, context, location):
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        if region is None or rv3d is None:
            return -1
        hit = cube_overlay.hit_test(region, rv3d, location[0], location[1])
        if hit != cube_overlay.get_hover():
            cube_overlay.set_hover(hit)
            area = getattr(context, "area", None)
            if area is not None:
                area.tag_redraw()
        return -1 if hit is None else 0


class MF_GZG_ViewCube(bpy.types.GizmoGroup):
    bl_label = "视图魔方"

    bl_idname = "MF_GGT_viewcube"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        return cube_overlay.is_enabled()

    def setup(self, context):
        gz = self.gizmos.new("MF_GZ_ViewCube")
        gz.target_set_operator(PICK_ID)
        gz.color = (0.0, 0.0, 0.0)
        gz.alpha = 0.0
        gz.color_highlight = (0.0, 0.0, 0.0)
        gz.alpha_highlight = 0.0
        gz.use_tooltip = False
        gz.show_drag = False
        self.hot_zone = gz

    def draw_prepare(self, context):
        region = context.region
        gz = getattr(self, "hot_zone", None)
        if gz is None:
            return
        gz.matrix_basis[0][3] = region.width - cube_overlay.MARGIN_X
        gz.matrix_basis[1][3] = region.height - cube_overlay.MARGIN_Y
        gz.scale_basis = cube_overlay.HOT_RADIUS


classes = (MF_GZ_ViewCube, MF_GZG_ViewCube)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
