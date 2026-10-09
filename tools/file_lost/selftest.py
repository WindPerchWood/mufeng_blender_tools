"""Blender 内无头自检：工具箱启用状态下运行 selftest.run()。"""

import base64
import importlib
import ntpath
import os
import re
import tempfile

import bpy

from . import operators, ui

PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
           "+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg==")

EXPECTED_OPS = {'filelost_scan', 'filelost_reconnect', 'filelost_root_add',
                'filelost_root_remove', 'filelost_item_activate'}


class _Log:
    def __init__(self):
        self.calls = []
        self.texts = []
        self.icons = set()
        self.op_ids = []
        self.op_props = []


class FakeLayout:
    def __init__(self, log=None):
        self._log = log if log is not None else _Log()

    @property
    def log(self):
        return self._log

    def _rec(self, kind, *args, **kw):
        self._log.calls.append((kind, list(args), dict(kw)))
        for a in args:
            if isinstance(a, str):
                self._log.texts.append(a)
        for v in kw.values():
            if isinstance(v, str):
                self._log.texts.append(v)
        if kw.get('icon'):
            self._log.icons.add(kw['icon'])

    def row(self, *a, **k):
        self._rec('row', *a, **k)
        return FakeLayout(self._log)

    def column(self, *a, **k):
        self._rec('column', *a, **k)
        return FakeLayout(self._log)

    def box(self, *a, **k):
        self._rec('box', *a, **k)
        return FakeLayout(self._log)

    def split(self, *a, **k):
        self._rec('split', *a, **k)
        return FakeLayout(self._log)

    def label(self, *a, **k):
        self._rec('label', *a, **k)

    def prop(self, *a, **k):
        self._rec('prop', *a, **k)

    def separator(self, *a, **k):
        self._rec('separator', *a, **k)

    def operator(self, *a, **k):
        self._rec('operator', *a, **k)
        if a:
            self._log.op_ids.append(a[0])
        return _OpHandle(self._log, a[0] if a else "")


class _OpHandle:
    def __init__(self, log=None, idname=""):
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_idname", idname)
        object.__setattr__(self, "name", "")

    def __setattr__(self, key, value):
        log = object.__getattribute__(self, "_log")
        if log is not None and not key.startswith("_"):
            log.op_props.append((object.__getattribute__(self, "_idname"), key, value))
        object.__setattr__(self, key, value)


class _FakePanel:
    def __init__(self, layout, owner):
        self.layout = layout
        self._owner = owner

    def __getattr__(self, name):
        raw = self._owner.__dict__.get(name)
        if isinstance(raw, staticmethod):
            return raw.__func__
        return getattr(self._owner, name).__get__(self, type(self))


class Check:
    def __init__(self):
        self.failed = 0
        self.total = 0

    def check(self, name, cond):
        self.total += 1
        if cond:
            print("  [PASS] %s" % name)
        else:
            self.failed += 1
            print("  [FAIL] %s" % name)

    def check_err(self, name, fn):
        self.total += 1
        try:
            fn()
            print("  [PASS] %s" % name)
        except Exception as e:
            self.failed += 1
            print("  [FAIL] %s  -> %r" % (name, e))


def _build_scene():
    root = tempfile.mkdtemp(prefix="fltest_root_")
    sub = os.path.join(root, "sub")
    os.makedirs(sub)
    png = os.path.join(root, "LostTex.png")
    png2 = os.path.join(root, "LostTex2.png")
    deep = os.path.join(sub, "DeepTex.png")
    for p in (png, png2, deep):
        with open(p, "wb") as f:
            f.write(base64.b64decode(PNG_B64))

    imgs = []
    for nm in ("LostTex", "LostTex2", "DeepTex"):
        im = bpy.data.images.new(nm, 1, 1)
        im.source = 'FILE'
        im.filepath = "//q\\%s.png" % nm
        imgs.append(im)
    img, img2, img3 = imgs

    return root, png, deep, img, img2, img3


def _draw_panel(ui):
    log = _Log()
    ui.MF_PT_FileLost.draw(_FakePanel(FakeLayout(log), ui.MF_PT_FileLost), bpy.context)
    return log


def _count(calls, kind, *args):
    return len([c for c in calls
                if c[0] == kind and c[1][:len(args)] == list(args)])


def _has_token(src, token):
    return re.search(r'\b%s\b' % re.escape(token), src) is not None


def run():
    print("=== file_lost 无头自检 ===")
    C = Check()

    root, png, deep, img, img2, img3 = _build_scene()
    st = bpy.context.scene.mf_filelost_settings
    view = bpy.context.window_manager.mf_filelost_view

    C.check_err("扫描执行", lambda: bpy.ops.mf.filelost_scan())
    C.check("扫描发现 3 项", len(st.items) == 3)
    labels = [i.label for i in st.items]
    C.check("包含 LostTex / LostTex2 / DeepTex",
            all(n in labels for n in ("LostTex", "LostTex2", "DeepTex")))
    C.check("不误报 Render Result", "Render Result" not in labels)

    item = next(i for i in st.items if i.label == "LostTex")
    item2 = next(i for i in st.items if i.label == "LostTex2")
    item3 = next(i for i in st.items if i.label == "DeepTex")

    C.check("operators.basename 认得 // 相对路径",
            operators.basename("//q\\LostTex.png") == "LostTex.png")
    C.check("operators.basename 认得正斜杠版本",
            operators.basename("//q/LostTex.png") == "LostTex.png")
    C.check("operators.basename 对普通绝对路径照常",
            operators.basename("C:\\a\\b\\c.png") == "c.png")
    C.check("（对照）ntpath.basename 对 // 路径返回空",
            ntpath.basename("//q\\LostTex.png") == "")
    C.check("用 // 相对路径也能按文件名搜到",
            operators.search_file("//q\\" + os.path.basename(png), [root]) == png)
    C.check("子目录里的文件也能搜到（递归已写死开启）",
            operators.search_file("//q\\DeepTex.png", [root]) == deep)

    st.search_roots.add()
    st.search_roots[0].path = root
    C.check_err("重连执行", lambda: bpy.ops.mf.filelost_reconnect())
    C.check("三条都变成 FOUND（含子目录那张）",
            all(i.status == "FOUND" for i in (item, item2, item3)))
    C.check("三张图都指向真实文件",
            all(os.path.exists(bpy.path.abspath(im.filepath))
                for im in (img, img2, img3)))
    C.check("面板状态栏报了结果", st.last_message.startswith("重连 "))

    C.check("五个算子都挂在 mf. 下",
            all(hasattr(bpy.ops.mf, n) for n in EXPECTED_OPS))
    C.check("operators 已无旧版遗留函数",
            not hasattr(operators, "op_select_all")
            and not hasattr(operators, "find_user_objects")
            and not hasattr(operators, "op_clear_one")
            and not hasattr(operators, "resolve_block"))
    item_props = list(st.items[0].bl_rna.properties.keys())
    C.check("条目属性已无 selected / found_path / readonly / block_type / node_ref",
            not ({'selected', 'found_path', 'readonly', 'block_type', 'node_ref'}
                 & set(item_props)))
    C.check("条目属性改叫 label，不再和内置 name 撞名（name 只剩内置那一份）",
            'label' in item_props and item_props.count('name') == 1)
    custom = {k for k in item_props if k not in ('rna_type', 'name')}
    C.check("条目属性正好是这 5 个",
            custom == {'label', 'kind', 'filepath', 'block_name', 'status'})
    C.check("设置属性已无 last_count / list_scroll / use_multidir",
            not ({'last_count', 'list_scroll', 'use_multidir'}
                 & set(st.bl_rna.properties.keys())))
    C.check("设置挂在 Scene 上（mf_filelost_settings）",
            'mf_filelost_settings' in bpy.types.Scene.bl_rna.properties)
    C.check("滚动状态挂在 WindowManager 上（mf_filelost_view）",
            'mf_filelost_view' in bpy.types.WindowManager.bl_rna.properties)
    C.check("Scene 上没有混进视图状态",
            'mf_filelost_view' not in bpy.types.Scene.bl_rna.properties)
    C.check("operators 已无没人用的 KIND_LABELS", not hasattr(operators, "KIND_LABELS"))

    with open(operators.__file__, encoding="utf-8") as f:
        op_src = f.read()
    C.check("operators 已无其它资源类型的常量",
            not [n for n in ('KIND_IES', 'KIND_FONT', 'KIND_SOUND', 'KIND_MOVIE',
                             'KIND_VOLUME', 'KIND_CACHE', 'KIND_LIBRARY')
                 if hasattr(operators, n)])
    C.check("operators 里不再引用 fonts/sounds/movieclips/volumes/cache_files/libraries",
            not [t for t in ('bpy.data.fonts', 'bpy.data.sounds',
                             'bpy.data.movieclips', 'bpy.data.volumes',
                             'bpy.data.cache_files', 'bpy.data.libraries')
                 if t in op_src])
    C.check("扫描会跳过链接进来的贴图", "img.library is not None" in op_src)
    C.check("只判贴图：image_is_missing 在、block_is_missing 已删",
            hasattr(operators, "image_is_missing")
            and not hasattr(operators, "block_is_missing"))

    valid_icons = {i.identifier for i in
                   bpy.types.UILayout.bl_rna.functions['label']
                   .parameters['icon'].enum_items}
    log1 = _draw_panel(ui)
    C.check("绘制引用了 scan 算子", operators.OP_SCAN in log1.op_ids)
    C.check("绘制引用了 reconnect 算子", operators.OP_RECONNECT in log1.op_ids)
    C.check("绘制引用了 root_add / root_remove",
            operators.OP_ROOT_ADD in log1.op_ids
            and operators.OP_ROOT_REMOVE in log1.op_ids)
    C.check("绘制引用了 item_activate（名称就是那一行的按钮）",
            operators.OP_ITEM_ACTIVATE in log1.op_ids)
    C.check("面板不再画选取/清除按钮",
            "mf.select" not in log1.op_ids and "mf.force_clear" not in log1.op_ids)
    C.check("行里画出了资源名", "LostTex" in log1.texts)
    C.check("路径不再单独占一行（行内只画名称）",
            "//q\\LostTex.png" not in log1.texts)
    C.check("面板不再画「多目录递归搜索」开关",
            not [c for c in log1.calls
                 if c[0] == 'prop' and c[1][1:2] == ['use_multidir']])
    C.check("勾选框已删净（没有 selected 属性可画）",
            not [c for c in log1.calls if c[0] == 'prop' and c[1][1:2] == ['selected']])
    C.check("活动行仍可辨认（按钮呈按下态）",
            any(c[2].get('depress') for c in log1.calls
                if c[0] == 'operator' and c[1][0] == operators.OP_ITEM_ACTIVATE))

    with open(ui.__file__, encoding="utf-8") as f:
        ui_src = f.read()
    body = ui_src.split('"""', 2)[-1]
    code = "\n".join(ln.split('#')[0] for ln in body.splitlines())
    C.check("守卫按整词匹配（_draw_items 不算 draw_item）",
            not _has_token("self._draw_items(layout, st)", "draw_item"))
    for gone in ("template_list", "use_filter_show", "draw_filter",
                 "filter_items", "UIList", "draw_item", "select", "force_clear"):
        C.check("ui.py 代码里已搜不到 %s" % gone, not _has_token(code, gone))
    C.check("ui 模块已无 UIList 子类",
            not [v for v in vars(ui).values()
                 if isinstance(v, type) and issubclass(v, bpy.types.UIList)])
    C.check("已无列表类被注册", not hasattr(bpy.types, 'MF_UL_items'))
    C.check("假 UI 不提供 template_list（回退即报错）",
            not hasattr(FakeLayout, 'template_list'))

    st.items.clear()
    for i in range(25):
        it = st.items.add()
        it.label = "D%02d" % i
    st.active_index = 0
    view.scroll = 0.0

    log2 = _draw_panel(ui)
    drawn = [i for i in range(25) if ("D%02d" % i) in log2.texts]
    C.check("首页只画 VIEW_ROWS 行", drawn == list(range(ui.VIEW_ROWS)))
    C.check("一屏一行 = 一个资源（按钮数 == 行数）",
            _count(log2.calls, 'operator', operators.OP_ITEM_ACTIVATE) == ui.VIEW_ROWS)
    C.check("条目超一屏时画出滚动条",
            _count(log2.calls, 'prop', view, "scroll") == 1)

    view.scroll = 1.0
    log3 = _draw_panel(ui)
    C.check("拖到底看得见最后一条（D24）", "D24" in log3.texts)
    C.check("拖到底不再画第一条（D00）", "D00" not in log3.texts)
    C.check("拖到底仍是 VIEW_ROWS 行",
            len([i for i in range(25) if ("D%02d" % i) in log3.texts]) == ui.VIEW_ROWS)

    view.scroll = 0.5
    log4 = _draw_panel(ui)
    exp_start = int(round(0.5 * (25 - ui.VIEW_ROWS)))
    C.check("滑到中间时从第 %d 行开始" % exp_start,
            ("D%02d" % exp_start) in log4.texts
            and ("D%02d" % (exp_start - 1)) not in log4.texts)

    C.check_err("设为活动项", lambda: bpy.ops.mf.filelost_item_activate(index=7))
    C.check("active_index == 7", st.active_index == 7)
    C.check_err("越界索引不炸", lambda: bpy.ops.mf.filelost_item_activate(index=999))
    C.check("越界后活动项不变", st.active_index == 7)

    st.items.clear()
    for i in range(3):
        it = st.items.add()
        it.label = "E%d" % i
    view.scroll = 0.0
    log5 = _draw_panel(ui)
    C.check("少于一屏时行数 == 条目数",
            _count(log5.calls, 'operator', operators.OP_ITEM_ACTIVATE) == 3)
    C.check("少于一屏时不画滚动条",
            _count(log5.calls, 'prop', view, "scroll") == 0)

    all_icons = set(log1.icons) | set(log2.icons) | set(log3.icons) | set(log5.icons)
    bad_icons = sorted(ic for ic in all_icons if ic not in valid_icons)
    C.check("图标全部有效（含选中圆点）", not bad_icons)

    st.search_roots.clear()
    for p in ("C:/a", "C:/b", "C:/c"):
        r = st.search_roots.add()
        r.path = p
    log6 = _draw_panel(ui)
    C.check("每个目录行都有 ✕（数量 == 目录数）",
            _count(log6.calls, 'operator', operators.OP_ROOT_REMOVE) == 3)
    C.check("✕ 用的就是 X 图标", "X" in log6.icons)
    C.check("每个 ✕ 带着自己那一行的索引",
            sorted(v for (opn, k, v) in log6.op_props
                   if opn == operators.OP_ROOT_REMOVE and k == "index") == [0, 1, 2])
    C.check("多目录行不再有单选圆点（那套已删）",
            "RADIOBUT_ON" not in log6.icons and "RADIOBUT_OFF" not in log6.icons)
    C.check_err("✕ 删第 2 行", lambda: bpy.ops.mf.filelost_root_remove(index=1))
    C.check("剩余 2 个搜索目录", len(st.search_roots) == 2)
    C.check("删掉的正是第 2 行", [r.path for r in st.search_roots] == ["C:/a", "C:/c"])
    C.check_err("越界索引不炸", lambda: bpy.ops.mf.filelost_root_remove(index=99))
    C.check("越界后目录数不变", len(st.search_roots) == 2)
    C.check("设置里已无 active_root", 'active_root' not in st.bl_rna.properties)
    C.check("目录路径属性不带 DIR_PATH（否则行尾会多出打开文件夹按钮）",
            st.search_roots[0].bl_rna.properties['path'].subtype == 'NONE')

    pkg = importlib.import_module(__package__)
    C.check_err("注销", pkg.unregister)
    C.check("注销后面板类移除", not hasattr(bpy.types, 'MF_PT_FileLost'))
    C.check("注销后场景属性移除", not hasattr(bpy.context.scene, 'mf_filelost_settings'))
    C.check("注销后 WindowManager 视图属性移除",
            'mf_filelost_view' not in bpy.types.WindowManager.bl_rna.properties)
    C.check_err("重新注册", pkg.register)
    C.check("重新注册后面板类存在", hasattr(bpy.types, 'MF_PT_FileLost'))
    C.check("重新注册后场景属性恢复", hasattr(bpy.context.scene, 'mf_filelost_settings'))

    print("=== 自检结果：%d/%d 通过，%d 失败 ===" % (
        C.total - C.failed, C.total, C.failed))
    return C.failed


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
