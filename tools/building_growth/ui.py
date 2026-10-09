import bpy

try:
    from ...core import utils
except (ImportError, ValueError):  # pragma: no cover - 仅在单独运行时触发
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from .props import SCENE_ATTR
from .operators import (
    MF_OT_PickGroup,
    MF_OT_PickPath,
    MF_OT_CreateGrowth,
    MF_OT_DeleteGrowth,
    _enabled_channels,
    _hierarchy_root,
)


def _scene_settings(context=None):
    return getattr(context.scene, SCENE_ATTR, None)


class MF_PT_BuildingGrowth(utils.MF_ToolPanel):
    bl_label = "施工生长"
    bl_idname = "MF_PT_BuildingGrowth"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_order = 19
    bl_options = {'DEFAULT_CLOSED'}

    MF_SEARCH_KEYWORDS = ("sgsg", "shigong", "building_growth", "施工", "建筑生长")

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_BUILD')

    def draw(self, context):
        layout = self.layout
        s = _scene_settings(context)
        if s is None:
            layout.label(text="参数组未注册", icon='ERROR')
            return

        box = layout.box()
        box.label(text="生长物体组", icon='GROUP')
        box.prop(s, "group_mode", text="")
        if s.group_mode == 'COLLECTION':
            box.prop(s, "group_collection", text="")
            n = len(s.group_collection.all_objects) if s.group_collection else 0
            box.label(text="成员：%d" % n, icon='INFO')
        else:
            row = box.row(align=True)
            row.prop(s, "group_root", text="")
            row.operator(MF_OT_PickGroup.bl_idname, text="", icon='EYEDROPPER')
            if s.group_root is not None:
                root = _hierarchy_root(s.group_root)
                box.label(text="根：%s ｜ 成员：%d" % (root.name, len(root.children)),
                          icon='INFO')

        box = layout.box()
        box.label(text="生长顺序", icon='SORT_ASC')
        box.prop(s, "use_path")
        if s.use_path:
            box.prop(s, "path_object", text="")
            box.operator(MF_OT_PickPath.bl_idname, icon='CURVE_DATA')
            box.prop(s, "path_arc_length")
        else:
            box.prop(s, "grow_axis", text="轴向")
        box.prop(s, "reverse_direction")

        box = layout.box()
        box.label(text="通道（VMRS）", icon='ANIM')

        col = box.column(align=True)
        col.prop(s, "use_visibility")
        if s.use_visibility:
            sub = col.row(align=True)
            sub.prop(s, "prob_v")
            sub.prop(s, "visibility_mode", text="")
        col.prop(s, "use_move")
        if s.use_move:
            col.prop(s, "prob_m")
        col.prop(s, "use_rotate")
        if s.use_rotate:
            col.prop(s, "prob_r")
        col.prop(s, "use_scale")
        if s.use_scale:
            col.prop(s, "prob_s")

        box = layout.box()
        box.label(text="组生长始末帧", icon='TIME')
        row = box.row(align=True)
        row.prop(s, "frame_start")
        row.prop(s, "frame_end")

        box = layout.box()
        box.label(text="每通道参数（V 为可见性）", icon='PRESET')
        grid = box.grid_flow(row_major=True, columns=5, even_columns=False, align=True)

        grid.label(text="")
        grid.label(text="周期")
        grid.label(text="周期随机")
        grid.label(text="始帧随机")
        grid.label(text="排序")

        for label, ch in (("V", "v"), ("M", "m"), ("R", "r"), ("S", "s")):
            grid.label(text=label)
            grid.prop(s, "period_%s" % ch, text="")
            grid.prop(s, "period_rnd_%s" % ch, text="")
            grid.prop(s, "start_rnd_%s" % ch, text="")
            if ch == "v":
                grid.label(text="—")
            else:
                grid.prop(s, "seq_%s" % ch, text="")

        box = layout.box()
        box.label(text="幅度", icon='DRIVER_DISTANCE')
        if s.use_move:
            row = box.row(align=True)
            row.prop(s, "amp_move")
            row.prop(s, "move_axis", text="")
            row.prop(s, "move_direction", text="")
        if s.use_rotate:
            row = box.row(align=True)
            row.prop(s, "amp_rotate")
            row.prop(s, "rot_axis", text="")
            row.prop(s, "rot_direction", text="")
        if s.use_scale:
            box.prop(s, "scale_mode")
        if not (s.use_move or s.use_rotate or s.use_scale):
            box.label(text="（仅启用可见性，无比参数）", icon='INFO')

        box = layout.box()
        box.label(text="其他", icon='PREFERENCES')
        box.prop(s, "random_seed")
        box.prop(s, "clear_existing")

        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.4
        sub = row.row(align=True)
        sub.enabled = bool(_enabled_channels(s))
        sub.operator(MF_OT_CreateGrowth.bl_idname, icon='PLAY')
        row.operator(MF_OT_DeleteGrowth.bl_idname, icon='TRASH')

        box = layout.box()
        box.label(text="说明", icon='HELP')
        col = box.column(align=True)
        for line in (
            "· 创建会先清后建，同通道的旧动画会被覆盖。",
            "· 旋转会自动切到 XYZ 欧拉模式。",
            "· 「惯性生长」未实现。",
        ):
            col.label(text=line)


classes = (MF_PT_BuildingGrowth,)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
