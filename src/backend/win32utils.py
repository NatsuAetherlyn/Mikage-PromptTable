"""Win32 window helpers shared by app.py (chrome/icon) and api.py (user commands).

All window operations use plain ctypes on the native HWND — never WinForms.
pywebview invokes js_api callbacks on a worker thread, and touching WinForms
controls from there deadlocks the UI thread (that is what froze the app on
maximize). ctypes SendMessage/SetWindowPos are safe from any thread.
"""
import sys
import ctypes
import time
from ctypes import wintypes

WIN32 = sys.platform == "win32"

WM_SETICON = 0x0080
WM_NCLBUTTONDOWN = 0x00A1
WM_CLOSE = 0x0010
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
SW_MINIMIZE = 6
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10

MONITOR_DEFAULTTONEAREST = 2
SPI_GETWORKAREA = 0x0030
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34


# Use the stdlib structures: they are created once per process, so declaring
# argtypes with them is safe even if this module gets imported twice (which
# happens when the app is frozen with PyInstaller). A locally defined
# Structure would be a *different* class on the second import and ctypes would
# then reject the pointer with "expected LP_RECT instance instead of pointer
# to RECT".
RECT = wintypes.RECT


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", ctypes.c_ulong)]


if WIN32:
    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi

    _user32.LoadImageW.restype = wintypes.HICON
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SendMessageW.restype = wintypes.LPARAM
    _user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                                     ctypes.c_void_p]
    _user32.ReleaseCapture.argtypes = []
    _user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_void_p]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.IsZoomed.argtypes = [ctypes.c_void_p]
    _user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]

    _user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_uint]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                              ctypes.POINTER(wintypes.RECT), ctypes.c_uint]
    _user32.SystemParametersInfoW.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint]
    _user32.SetWindowPos.restype = wintypes.BOOL

# hwnd -> (left, top, right, bottom) captured before we hand-maximized
_restore_rects = {}


# ---------------- handle / simple helpers ----------------

def get_hwnd(window, timeout: float = 30.0):
    """Resolve a plain HWND int from a pywebview window."""
    if not WIN32:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        native = getattr(window, "native", None)
        if native is not None:
            try:
                return int(native.Handle.ToInt64())
            except Exception:
                pass
            try:
                return int(native.Handle)
            except Exception:
                pass
        time.sleep(0.2)
    return None


def _get_rect(hwnd):
    r = RECT()
    if not _user32.GetWindowRect(_hwnd_arg(hwnd), ctypes.byref(r)):
        return None
    return r


def _work_area(hwnd):
    """rcWork of the monitor the window is on (falls back to the primary one)."""
    mon = _user32.MonitorFromWindow(_hwnd_arg(hwnd), MONITOR_DEFAULTTONEAREST)
    if mon:
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return mi.rcWork
    r = RECT()
    if _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
        return r
    return None


def _looks_maximized(rect, work) -> bool:
    if not rect or not work:
        return False
    tol = 3
    return (abs(rect.left - work.left) <= tol and abs(rect.top - work.top) <= tol
            and abs(rect.right - work.right) <= tol
            and abs(rect.bottom - work.bottom) <= tol)


def is_maximized(hwnd) -> bool:
    """True when the window fills its monitor's work area (our manual maximize)."""
    if not hwnd:
        return False
    return _looks_maximized(_get_rect(hwnd), _work_area(hwnd))


def _hwnd_arg(hwnd):
    """Normalise a handle to a c_void_p for the APIs that declare argtypes."""
    try:
        return ctypes.c_void_p(int(hwnd)) if hwnd else None
    except (TypeError, ValueError):
        return hwnd


# ---------------- maximize / restore ----------------

def maximize(hwnd) -> bool:
    """Fill the monitor work area (taskbar stays visible) and remember the
    previous geometry so restore can put it back."""
    if not hwnd:
        return False
    work = _work_area(hwnd)
    if not work:
        # no monitor info: fall back to the OS maximize
        _user32.ShowWindow(_hwnd_arg(hwnd), 3)   # SW_MAXIMIZE
        return True

    if is_maximized(hwnd):
        return True

    rect = _get_rect(hwnd)
    if rect:
        _restore_rects[hwnd] = (rect.left, rect.top, rect.right, rect.bottom)

    _user32.SetWindowPos(
        _hwnd_arg(hwnd), None,
        work.left, work.top,
        work.right - work.left, work.bottom - work.top,
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    return True


def restore(hwnd) -> bool:
    """Return to the geometry captured by maximize()."""
    if not hwnd:
        return False
    saved = _restore_rects.pop(hwnd, None)
    if saved:
        left, top, right, bottom = saved
        _user32.SetWindowPos(_hwnd_arg(hwnd), None, left, top, right - left, bottom - top,
                             SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    # nothing remembered (e.g. OS-maximized before): let the OS restore
    _user32.ShowWindow(_hwnd_arg(hwnd), 9)   # SW_RESTORE
    return False


def toggle_maximize(hwnd) -> bool:
    if is_maximized(hwnd):
        restore(hwnd)
        return False
    maximize(hwnd)
    return True


# ---------------- icon / chrome ----------------

# ---------------- manual window dragging ----------------
#
# pywebview ships a drag-region helper, but its Windows move() implementation
# raises "TypeError: 'NoneType' object cannot be interpreted as an integer"
# (it forwards None to SetWindowPos), so dragging silently does nothing.
# We drive the window ourselves with a proven SetWindowPos path instead.

_drag_state = {"hwnd": None, "ax": 0, "ay": 0, "wx": 0, "wy": 0, "active": False}

# window resizing, driven the same way as dragging
_resize_state = {"hwnd": None, "edge": "", "ax": 0, "ay": 0,
                 "rect": None, "active": False}
# Resize floor. pywebview also enforces create_window(min_size=...) at the OS
# level, so call set_min_size() with the same values to keep both in agreement.
MIN_WINDOW_W = 1020
MIN_WINDOW_H = 640


def set_min_size(width: int, height: int):
    """Match the app's create_window(min_size=...) so the two never disagree."""
    global MIN_WINDOW_W, MIN_WINDOW_H
    MIN_WINDOW_W = max(320, int(width))
    MIN_WINDOW_H = max(240, int(height))


def resize_begin(window, edge: str) -> bool:
    """Start resizing from `edge` (top/bottom/left/right/tl/tr/bl/br)."""
    if not WIN32 or not edge:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    # a maximized window has no meaningful geometry to resize from
    if is_maximized(hwnd):
        return False
    rect = _get_rect(hwnd)
    if not rect:
        return False
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    _resize_state.update({
        "hwnd": hwnd, "edge": edge.lower(), "ax": pt.x, "ay": pt.y,
        "rect": (rect.left, rect.top, rect.right, rect.bottom), "active": True})
    return True


def resize_move() -> bool:
    """Recompute the rect from the cursor position (called while dragging)."""
    if not WIN32 or not _resize_state["active"]:
        return False
    st = _resize_state
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    dx, dy = pt.x - st["ax"], pt.y - st["ay"]
    left, top, right, bottom = st["rect"]
    edge = st["edge"]

    if "l" in edge:
        left += dx
    if "r" in edge:
        right += dx
    if "t" in edge:
        top += dy
    if "b" in edge:
        bottom += dy

    # keep a usable minimum, anchored to the opposite side
    min_w, min_h = MIN_WINDOW_W, MIN_WINDOW_H
    if right - left < min_w:
        if "l" in edge:
            left = right - min_w
        else:
            right = left + min_w
    if bottom - top < min_h:
        if "t" in edge:
            top = bottom - min_h
        else:
            bottom = top + min_h

    _user32.SetWindowPos(_hwnd_arg(st["hwnd"]), None, left, top,
                         right - left, bottom - top,
                         SWP_NOZORDER | SWP_NOACTIVATE)
    return True


def resize_end() -> bool:
    _resize_state["active"] = False
    return True


def drag_begin(window) -> bool:
    """Capture the mouse anchor and the window origin."""
    if not WIN32:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    rect = _get_rect(hwnd)
    if not rect:
        return False
    _drag_state.update({"hwnd": hwnd, "ax": pt.x, "ay": pt.y,
                        "wx": rect.left, "wy": rect.top, "active": True})
    return True


def drag_move() -> bool:
    """Move the window to follow the cursor (call repeatedly while dragging)."""
    if not WIN32 or not _drag_state["active"]:
        return False
    hwnd = _drag_state["hwnd"]
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    dx = pt.x - _drag_state["ax"]
    dy = pt.y - _drag_state["ay"]
    _user32.SetWindowPos(_hwnd_arg(hwnd), None,
                         _drag_state["wx"] + dx, _drag_state["wy"] + dy,
                         0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    return True


def drag_end() -> bool:
    _drag_state["active"] = False
    return True


def _dwm_set(hwnd, attr, value):
    try:
        v = ctypes.c_uint(value)
        _dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                      ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def apply_window_chrome(hwnd):
    """Frameless window polish: Win11 rounded corners + subtle border."""
    if not WIN32 or not hwnd:
        return
    _dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, 2)   # DWMWCP_ROUND
    _dwm_set(hwnd, DWMWA_BORDER_COLOR, 0x452F2A)        # subtle dark border


def apply_window_icon(hwnd, icon_path: str):
    if not WIN32 or not hwnd or not icon_path:
        return
    small = _user32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
    big = _user32.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
    if small:
        _user32.SendMessageW(_hwnd_arg(hwnd), WM_SETICON, ICON_SMALL, small)
    if big:
        _user32.SendMessageW(_hwnd_arg(hwnd), WM_SETICON, ICON_BIG, big)


# ---------------- command dispatcher (called from js_api) ----------------

def window_command(window, action: str, arg: str = ""):
    """Title-bar drag / edge resize / min / max / close, entered from the web UI."""
    if not WIN32:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False

    if action == "is_max":
        return is_maximized(hwnd)

    if action == "max_toggle":
        return toggle_maximize(hwnd)

    if action == "drag":
        # dragging a maximized window should restore it first (like the OS does)
        if is_maximized(hwnd):
            restore(hwnd)
        return drag_begin(window)

    if action == "drag_move":
        return drag_move()

    if action == "drag_end":
        return drag_end()

    if action == "edge_begin":
        return resize_begin(window, arg)

    if action == "edge_move":
        return resize_move()

    if action == "edge_end":
        return resize_end()

    if action == "edge":
        ht = {"left": HTLEFT, "right": HTRIGHT, "top": HTTOP, "bottom": HTBOTTOM,
              "tl": HTTOPLEFT, "tr": HTTOPRIGHT, "bl": HTBOTTOMLEFT,
              "br": HTBOTTOMRIGHT}.get(arg)
        if not ht:
            return False
        _user32.ReleaseCapture()
        _user32.SendMessageW(_hwnd_arg(hwnd), WM_NCLBUTTONDOWN, ht, 0)
        return True

    if action == "min":
        _user32.ShowWindow(_hwnd_arg(hwnd), SW_MINIMIZE)
        return True

    if action == "close":
        _user32.PostMessageW(_hwnd_arg(hwnd), WM_CLOSE, 0, 0)
        return True

    return False


def wait_for_hwnd_and_theme(window, icon_path: str):
    """Background: wait for the native handle, then apply icon + rounded chrome."""
    import threading

    def worker():
        hwnd = get_hwnd(window, timeout=30)
        if hwnd:
            apply_window_icon(hwnd, icon_path)
            apply_window_chrome(hwnd)

    threading.Thread(target=worker, daemon=True).start()
