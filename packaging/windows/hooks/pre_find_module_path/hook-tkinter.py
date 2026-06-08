"""Keep stdlib tkinter visible for this Windows build.

Python 3.14 on this machine has a working tkinter runtime, but PyInstaller's
Tcl/Tk probe reports it as unavailable. The spec explicitly bundles Tcl/Tk
resources, so this pre-find hook only needs to avoid clearing tkinter's search
path.
"""


def pre_find_module_path(hook_api):
    return
