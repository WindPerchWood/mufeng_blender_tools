import bpy

try:
    from ...core import utils
except (ImportError, ValueError):
    import types
    utils = types.SimpleNamespace(PANEL_CATEGORY="木风工具箱",
                                  MF_ToolPanel=bpy.types.Panel)

from . import props
from .operators import (OP_ADD, OP_REMOVE, OP_CLEAR, OP_PICK_FACES,
                        OP_CREATE_SHELF, OP_NEW_SEED, target_objects)

PANEL_MAIN = "MF_PT_BookShelf"


class _Panel(utils.MF_ToolPanel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = utils.PANEL_CATEGORY
    bl_options = {'DEFAULT_CLOSED'}
    MF_SEARCH_KEYWORDS = ()

    def _s(self, ctx):
        return ctx.scene.book_shelf


class MF_PT_BookShelf(_Panel):
    bl_label = "一键摆书"
    bl_idname = PANEL_MAIN
    bl_order = 15
    MF_SEARCH_KEYWORDS = ("ybs", "bookshelf", "摆书", "书架")

    def draw_header(self, ctx):
        self.layout.label(text="", icon='BOOKMARKS')

    def draw(self, ctx):
        pass


class MF_PT_BookShelf_Books(_Panel):
    bl_label = "① 书籍库"
    bl_idname = "MF_PT_BookShelf_Books"
    bl_parent_id = PANEL_MAIN
    bl_order = 1
    MF_SEARCH_KEYWORDS = ("shujuku", "books", "书库", "收录")

    def draw(self, ctx):
        s = self._s(ctx)
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator(OP_ADD, icon='ADD')
        row.operator(OP_REMOVE, icon='REMOVE')
        row.operator(OP_CLEAR, text="", icon='X')

        col.separator()
        col.label(text="已收录 [ %d ] 本书" % len(s.books), icon='INFO')


class MF_PT_BookShelf_Props(_Panel):
    bl_label = "② 属性"
    bl_idname = "MF_PT_BookShelf_Props"
    bl_parent_id = PANEL_MAIN
    bl_order = 2
    MF_SEARCH_KEYWORDS = ("shuxing", "properties", "属性", "参数")

    def draw(self, ctx):
        s = self._s(ctx)
        self.layout.use_property_split = True
        self.layout.use_property_decorate = False
        self.layout.prop(s, "copy_type", expand=True)
        self.layout.prop(s, "hor_flip")
        self.layout.prop(s, "vert_flip")
        self.layout.prop(s, "seed")


class MF_PT_BookShelf_Standing(_Panel):
    bl_label = "③ 站立的书籍"
    bl_idname = "MF_PT_BookShelf_Standing"
    bl_parent_id = PANEL_MAIN
    bl_order = 3
    MF_SEARCH_KEYWORDS = ("zhanli", "standing", "站立", "直立")

    def draw_header(self, ctx):
        s = self._s(ctx)
        self.layout.prop(s, "use_standing", text="")

    def draw(self, ctx):
        s = self._s(ctx)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.enabled = s.use_standing

        alone = s.use_standing and (not s.use_leaning) and (not s.use_stacks)
        row = layout.row()
        row.enabled = not alone
        row.prop(s, "standing_prob")
        layout.prop(s, "standing_min_books")
        layout.prop(s, "standing_max_books")
        layout.label(text="一次连续放这么多本。这个数越大，"
                          "倾斜和书堆就越少", icon='INFO')


class MF_PT_BookShelf_Leaning(_Panel):
    bl_label = "④ 倾斜的书籍"
    bl_idname = "MF_PT_BookShelf_Leaning"
    bl_parent_id = PANEL_MAIN
    bl_order = 4
    MF_SEARCH_KEYWORDS = ("qingxie", "leaning", "倾斜", "斜靠")

    def draw_header(self, ctx):
        s = self._s(ctx)
        self.layout.prop(s, "use_leaning", text="")

    def draw(self, ctx):
        s = self._s(ctx)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.enabled = s.use_leaning

        layout.prop(s, "lean_dir", expand=True)
        alone = s.use_leaning and (not s.use_standing) and (not s.use_stacks)
        row = layout.row()
        row.enabled = not alone
        row.prop(s, "leaning_prob")
        layout.prop(s, "leaning_min_books")
        layout.prop(s, "leaning_max_books")
        layout.prop(s, "leaning_min_angle")
        layout.prop(s, "leaning_max_angle")
        layout.prop(s, "leaning_divergence")
        layout.label(text="概率 = 抽到「倾斜批次」的概率，不是每本书的概率。"
                          "想让倾斜书变多，把③站立的「最大数量」调小（1~3）",
                     icon='INFO')


class MF_PT_BookShelf_Stacks(_Panel):
    bl_label = "⑤ 堆叠的书籍"
    bl_idname = "MF_PT_BookShelf_Stacks"
    bl_parent_id = PANEL_MAIN
    bl_order = 5
    MF_SEARCH_KEYWORDS = ("duidie", "stacks", "堆叠", "书堆")

    def draw_header(self, ctx):
        s = self._s(ctx)
        self.layout.prop(s, "use_stacks", text="")

    def draw(self, ctx):
        s = self._s(ctx)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.enabled = s.use_stacks

        layout.prop(s, "stacks_align", expand=True)
        layout.prop(s, "stacks_initial", expand=True)
        box = layout.box()
        box.label(text="概率：%.4g %%（= 100 − 站立 − 倾斜）"
                  % props.derived_stacks_prob(s), icon='INFO')
        layout.prop(s, "stacks_min_books")
        layout.prop(s, "stacks_max_books")
        layout.prop(s, "stacks_rotation")
        layout.prop(s, "stacks_offset")
        layout.prop(s, "stacks_divergence")
        layout.label(text="书堆概率是剩余值（100−站立−倾斜），一排只抽几次类型，"
                          "默认常常一本都不出。把③站立的「最大数量」调小即可",
                     icon='INFO')


class MF_PT_BookShelf_Shelf(_Panel):
    bl_label = "⑦ 书架"
    bl_idname = "MF_PT_BookShelf_Shelf"
    bl_parent_id = PANEL_MAIN
    bl_order = 6
    MF_SEARCH_KEYWORDS = ("shujia", "shelf", "书架", "层板")

    def draw(self, ctx):
        s = self._s(ctx)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "shelf_obj")
        layout.prop(s, "row_axis", expand=True)
        n = len(s.shelf_faces)
        if s.shelf_obj is not None:
            layout.label(text="已选 %d 个层板面" % n, icon='INFO')
        else:
            layout.label(text="请选择书架物体", icon='INFO')
        layout.operator(OP_PICK_FACES, icon='EYEDROPPER')
        layout.label(text="用法：进入编辑模式 → 选中层板面 → 点上面这个按钮",
                     icon='INFO')
        layout.prop(s, "avoid_collision")
        layout.operator(OP_CREATE_SHELF, icon='PLAY')


class MF_PT_BookShelf_Edit(_Panel):
    bl_label = "⑧ 编辑"
    bl_idname = "MF_PT_BookShelf_Edit"
    bl_parent_id = PANEL_MAIN
    bl_order = 7
    MF_SEARCH_KEYWORDS = ("bianji", "edit", "编辑", "偏移")

    def draw(self, ctx):
        s = self._s(ctx)
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "edit_collection")
        n_tgt = len(target_objects(ctx, s))
        if n_tgt == 0:
            layout.label(text="还没有生成结果" if s.edit_collection is None
                         else "该集合里没有生成结果", icon='INFO')
        elif s.edit_collection is None:
            layout.label(text="未选集合 → 作用于全部 %d 个" % n_tgt, icon='INFO')
        else:
            layout.label(text="该集合 %d 个对象" % n_tgt, icon='INFO')
        layout.prop(s, "move_offset")
        layout.prop(s, "variation")
        layout.operator(OP_NEW_SEED, icon='FILE_REFRESH')


classes = (
    MF_PT_BookShelf,
    MF_PT_BookShelf_Books,
    MF_PT_BookShelf_Props,
    MF_PT_BookShelf_Standing,
    MF_PT_BookShelf_Leaning,
    MF_PT_BookShelf_Stacks,
    MF_PT_BookShelf_Shelf,
    MF_PT_BookShelf_Edit,
)


def register():
    utils.register_classes(classes)


def unregister():
    utils.unregister_classes(classes)
