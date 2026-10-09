bl_info = {
    "name": "木风工具箱 · 一键摆书",
    "author": "",
    "version": (1, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D 视图 > 侧栏(N) > 木风工具箱 > 一键摆书",
    "description": "把一组书随机摆成一排或摆满整个书架（站立 / 倾斜 / 书堆）",
    "category": "Object",
}

from . import props
from . import operators
from . import ui


def register():
    props.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    props.unregister()


if __name__ == "__main__":
    register()
