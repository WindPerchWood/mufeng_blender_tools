from . import markers
from . import operators
from . import ui


def register():
    markers.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    markers.unregister()


def selftest():
    from . import selftest as st
    return st.run()
