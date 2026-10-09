import bpy
from bpy.props import (BoolProperty, IntProperty, FloatProperty, EnumProperty,
                       CollectionProperty, PointerProperty)

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
        register_classes=_fallback_register,
        unregister_classes=_fallback_unregister,
    )

ROW_AXIS_ITEMS = (
    ('AUTO', '自动', '按书架物体的朝向决定：一排沿「垂直于物体局部 +Y」的那条层板边展开。'
                     '物体不旋转时沿 X 排，物体绕 Z 转 90° 时沿 Y 排'),
    ('X', '沿X轴', '强制一排沿世界 X 轴展开'),
    ('Y', '沿Y轴', '强制一排沿世界 Y 轴展开'),
)

COPY_ITEMS = (
    ('COPY', '复制', '完全独立的副本（网格数据也复制一份）'),
    ('INSTANCE', '实例', '共享网格数据的关联副本，改一个全变'),
)

LEAN_DIR_ITEMS = (
    ('LEFT', '左', '一律向左倾'),
    ('RIGHT', '右', '一律向右倾'),
    ('BOTH', '兼有', '左右随机'),
)

STACK_ALIGN_ITEMS = (
    ('CENTER', '居中', '对齐到中心：每本书按自己的包围盒中心叠放'),
    ('FRONT', '靠前', '对齐到前面：不做中心对齐，沿书厚方向偏半本，让一侧齐平'),
)

STACK_INIT_ITEMS = (
    ('BACK', '背面', '初始绕 Y 转 -90°'),
    ('FRONT', '前面', '初始绕 Y 转 +90°'),
)


def derived_stacks_prob(s):
    if not s.use_stacks:
        return 0.0
    st = s.standing_prob if s.use_standing else 0.0
    ln = s.leaning_prob if s.use_leaning else 0.0
    return max(0.0, 100.0 - st - ln)


_PROB_BUSY = False

_NO_APPLY = False


def _on_standing_prob(self, context):
    global _PROB_BUSY
    if _PROB_BUSY:
        return
    _PROB_BUSY = True
    try:
        if self.standing_prob >= (100.0 - self.leaning_prob):
            if self.leaning_prob > 0.0:
                self.leaning_prob = max(0.0, 100.0 - self.standing_prob)
    finally:
        _PROB_BUSY = False


def _on_leaning_prob(self, context):
    global _PROB_BUSY
    if _PROB_BUSY:
        return
    _PROB_BUSY = True
    try:
        if self.leaning_prob >= (100.0 - self.standing_prob):
            if self.standing_prob > 0.0:
                self.standing_prob = max(0.0, 100.0 - self.leaning_prob)
    finally:
        _PROB_BUSY = False


def _toggle_kind(s, kind):
    global _PROB_BUSY
    if _PROB_BUSY:
        return
    enabled = getattr(s, 'use_' + kind)
    if enabled:
        return
    if (not s.use_standing) and (not s.use_leaning) and (not s.use_stacks):
        _PROB_BUSY = True
        try:
            setattr(s, 'use_' + kind, True)
        finally:
            _PROB_BUSY = False
        return

    _PROB_BUSY = True
    try:
        val = getattr(s, kind + '_prob')
        others = [k for k in ('standing', 'leaning') if k != kind and getattr(s, 'use_' + k)]
        share = val * 0.5 if (others and s.use_stacks) else val
        if others and not s.use_stacks:
            share = val / float(len(others))
        for k in others:
            setattr(s, k + '_prob', min(100.0, getattr(s, k + '_prob') + share))
        setattr(s, kind + '_prob', 0.0)
    finally:
        _PROB_BUSY = False


def _on_use_standing(self, context):
    _toggle_kind(self, 'standing')


def _on_use_leaning(self, context):
    _toggle_kind(self, 'leaning')


def _on_use_stacks(self, context):
    global _PROB_BUSY
    if _PROB_BUSY:
        return
    if self.use_stacks:
        return
    if (not self.use_standing) and (not self.use_leaning):
        _PROB_BUSY = True
        try:
            self.use_stacks = True
        finally:
            _PROB_BUSY = False


def _clamp_pair(s, lo_name, hi_name, changed):
    if getattr(s, lo_name) > getattr(s, hi_name):
        if changed == 'lo':
            setattr(s, hi_name, getattr(s, lo_name))
        else:
            setattr(s, lo_name, getattr(s, hi_name))


def _on_standing_min(self, context):
    _clamp_pair(self, 'standing_min_books', 'standing_max_books', 'lo')


def _on_standing_max(self, context):
    _clamp_pair(self, 'standing_min_books', 'standing_max_books', 'hi')


def _on_leaning_min(self, context):
    _clamp_pair(self, 'leaning_min_books', 'leaning_max_books', 'lo')


def _on_leaning_max(self, context):
    _clamp_pair(self, 'leaning_min_books', 'leaning_max_books', 'hi')


def _on_stacks_min(self, context):
    _clamp_pair(self, 'stacks_min_books', 'stacks_max_books', 'lo')


def _on_stacks_max(self, context):
    _clamp_pair(self, 'stacks_min_books', 'stacks_max_books', 'hi')


def _on_leaning_min_angle(self, context):
    _clamp_pair(self, 'leaning_min_angle', 'leaning_max_angle', 'lo')


def _on_leaning_max_angle(self, context):
    _clamp_pair(self, 'leaning_min_angle', 'leaning_max_angle', 'hi')


def _on_edit_prop(self, context):
    if _NO_APPLY:
        return
    try:
        from . import operators
        operators.op_apply_edit(context)
    except Exception:
        pass


class MF_BookShelf_Item(bpy.types.PropertyGroup):
    ob: PointerProperty(type=bpy.types.Object, name="书")


class MF_BookShelf_Face(bpy.types.PropertyGroup):
    index: IntProperty(name="面索引", default=-1)


class MF_BookShelf_Settings(bpy.types.PropertyGroup):

    books: CollectionProperty(type=MF_BookShelf_Item, name="书籍库")

    copy_type: EnumProperty(name="复制方式", items=COPY_ITEMS, default='COPY')
    hor_flip: FloatProperty(name="水平翻转 (%)", default=5.0, min=0.0, max=100.0,
                            description="每本书水平（绕 Z）翻转 180° 的概率")
    vert_flip: FloatProperty(name="垂直翻转 (%)", default=5.0, min=0.0, max=100.0,
                             description="每本书垂直（绕 Y）翻转 180° 的概率")

    use_standing: BoolProperty(name="站立的书籍", default=True, update=_on_use_standing)
    standing_prob: FloatProperty(name="概率 (%)", default=60.0, min=0.0, max=100.0,
                                 update=_on_standing_prob)
    standing_min_books: IntProperty(name="最小数量", default=1, min=1, max=10000,
                                    update=_on_standing_min)
    standing_max_books: IntProperty(name="最大数量", default=3, min=1, max=10000,
                                    update=_on_standing_max)

    use_leaning: BoolProperty(name="倾斜的书籍", default=True, update=_on_use_leaning)
    lean_dir: EnumProperty(name="方向", items=LEAN_DIR_ITEMS, default='BOTH')
    leaning_prob: FloatProperty(name="概率 (%)", default=30.0, min=0.0, max=100.0,
                                update=_on_leaning_prob)
    leaning_min_books: IntProperty(name="最小数量", default=1, min=1, max=10000,
                                   update=_on_leaning_min)
    leaning_max_books: IntProperty(name="最大数量", default=3, min=1, max=10000,
                                   update=_on_leaning_max)
    leaning_min_angle: FloatProperty(name="最小角度", default=5.0, min=0.0, max=70.0,
                                     update=_on_leaning_min_angle)
    leaning_max_angle: FloatProperty(name="最大角度", default=25.0, min=0.0, max=70.0,
                                     update=_on_leaning_max_angle)
    leaning_divergence: FloatProperty(name="不同概率 (%)", default=80.0, min=0.0, max=100.0,
                                      description="同一批倾斜书里各本角度互不相同（而非全部相同）的概率")

    use_stacks: BoolProperty(name="堆叠的书籍", default=True, update=_on_use_stacks)
    stacks_align: EnumProperty(name="对齐方式", items=STACK_ALIGN_ITEMS, default='CENTER')
    stacks_initial: EnumProperty(name="初始旋转", items=STACK_INIT_ITEMS, default='BACK')
    stacks_min_books: IntProperty(name="最小数量", default=1, min=1, max=10000,
                                  update=_on_stacks_min)
    stacks_max_books: IntProperty(name="最大数量", default=3, min=1, max=10000,
                                  update=_on_stacks_max)
    stacks_rotation: FloatProperty(name="随机旋转 (°)", default=10.0, min=0.0, max=180.0)
    stacks_offset: FloatProperty(name="随机偏移 (%)", default=10.0, min=0.0, max=100.0)
    stacks_divergence: FloatProperty(name="不同概率 (%)", default=50.0, min=0.0, max=100.0,
                                     description="书堆里的书错落摆放（而非码放整齐）的概率")

    row_axis: EnumProperty(name="排列方向", items=ROW_AXIS_ITEMS, default='AUTO')
    avoid_collision: BoolProperty(
        name="自动避让碰撞", default=True,
        description="生成后检测这一批书之间有没有穿模；发现就换个随机种子重新生成"
                    "（最多 8 次），最后取穿透最轻的一次")
    shelf_obj: PointerProperty(type=bpy.types.Object, name="书架")
    shelf_faces: CollectionProperty(type=MF_BookShelf_Face, name="层板面")

    edit_collection: PointerProperty(
        type=bpy.types.Collection, name="作用集合",
        description="「偏移 / 变化 / 随机种子」只作用在这个集合里的生成结果上。"
                    "每次点「生成」会自动切到刚生成的这一批")
    move_offset: FloatProperty(name="偏移", default=0.0, soft_min=-10.0, soft_max=10.0,
                               unit='LENGTH', precision=4, update=_on_edit_prop,
                               description="沿层板进深方向整体推拉已生成的书")
    variation: FloatProperty(name="变化", default=0.0, soft_min=-10.0, soft_max=10.0,
                             unit='LENGTH', precision=4, update=_on_edit_prop,
                             description="在偏移基础上叠加每本书不同的随机量")
    seed: IntProperty(name="随机种子", default=0, min=0,
                      description="0 = 每次随机；非 0 = 固定种子，可复现同一结果")


CLASSES = (MF_BookShelf_Item, MF_BookShelf_Face, MF_BookShelf_Settings)

SCENE_ATTR = "book_shelf"


def register():
    utils.register_classes(CLASSES)
    # 场景数据例外：不是配置，是当前 .blend 的数据，应随场景保存。
    setattr(bpy.types.Scene, SCENE_ATTR,
            PointerProperty(type=MF_BookShelf_Settings, name="一键摆书"))


def unregister():
    if hasattr(bpy.types.Scene, SCENE_ATTR):
        delattr(bpy.types.Scene, SCENE_ATTR)
    utils.unregister_classes(CLASSES)
