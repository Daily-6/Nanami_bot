"""Enable native Windows rendering before Tk creates its first window."""

from __future__ import annotations

import os


def enable_high_dpi() -> None:
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        configure = user32.SetProcessDpiAwarenessContext
    except AttributeError:
        # Compatibility fallback for Windows versions before Per-Monitor V2.
        user32.SetProcessDPIAware()
    else:
        configure.argtypes = [ctypes.c_void_p]
        configure.restype = wintypes.BOOL
        configure(ctypes.c_void_p(-4))


def configure_window(root) -> float:
    """Keep point-sized fonts and pixel-sized geometry at the same display scale."""
    dpi = float(root.winfo_fpixels("1i"))
    work = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        import win32api

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            get_dpi = user32.GetDpiForWindow
        except AttributeError:
            pass
        else:
            get_dpi.argtypes = [wintypes.HWND]
            get_dpi.restype = wintypes.UINT
            dpi = float(get_dpi(root.winfo_id()) or dpi)
        monitor = win32api.MonitorFromWindow(root.winfo_id(), 2)
        work = win32api.GetMonitorInfo(monitor)["Work"]
    root.tk.call("tk", "scaling", dpi / 72)
    scale = dpi / 96
    width = min(round(1060 * scale), work[2] - work[0] - round(32 * scale))
    height = min(round(830 * scale), work[3] - work[1] - round(48 * scale))
    root.geometry(f"{width}x{height}")
    root.minsize(min(round(960 * scale), width), min(round(760 * scale), height))
    return scale


def pixels(value, scale):
    if isinstance(value, (tuple, list)):
        return tuple(pixels(item, scale) for item in value)
    return round(value * scale)
