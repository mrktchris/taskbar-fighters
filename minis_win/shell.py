"""Layered always-on-top window (UpdateLayeredWindow, premultiplied BGRA) + taskbar helpers.
Proven by reference/taskbar_spike.py: windows draw over the Windows 11 taskbar but vanish when the taskbar
re-raises itself, so the owner must call reassert_topmost() every <= 250 ms."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
from pathlib import Path
from PIL import Image, ImageChops

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
try:
    shcore = ctypes.WinDLL('shcore')
except OSError:
    shcore = None


def _set_dpi_awareness():
    """Make every coordinate this process sees a PHYSICAL pixel (no DPI virtualisation, no blurry bitmap stretching), so
    sprites drawn at an integer scale stay crisp at 125-200%.  Tries, in order: per-monitor v2 (Windows 10 1703+), per-monitor
    v1, shcore per-monitor (8.1), system aware (Vista).  A call refused because awareness is already set (a manifest, e.g. a
    frozen exe) is fine: dpi_awareness() reports what the process really has.  -> the step that succeeded, or None."""
    for ctx, label in ((-4, 'per-monitor v2'), (-3, 'per-monitor')):
        try:
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(ctx)):
                return label
        except (AttributeError, OSError):
            break                                                    # no such API (before Windows 10 1703)
    try:
        if shcore is not None and shcore.SetProcessDpiAwareness(2) == 0:    # PROCESS_PER_MONITOR_DPI_AWARE
            return 'per-monitor (shcore)'
    except (AttributeError, OSError):
        pass
    try:
        if user32.SetProcessDPIAware():
            return 'system'
    except (AttributeError, OSError):
        pass
    return None


DPI_SET = _set_dpi_awareness()


def dpi_awareness():
    """What the process really has: 'per-monitor v2', 'per-monitor', 'system' or 'unaware' (or 'unknown')."""
    try:
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        ctx = user32.GetThreadDpiAwarenessContext()
        if user32.AreDpiAwarenessContextsEqual(ctx, ctypes.c_void_p(-4)):
            return 'per-monitor v2'
        return {0: 'unaware', 1: 'system', 2: 'per-monitor'}.get(user32.GetAwarenessFromDpiAwarenessContext(ctx), 'unknown')
    except (AttributeError, OSError):
        return DPI_SET or 'unknown'

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('style', wt.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wt.HINSTANCE), ('hIcon', wt.HICON), ('hCursor', wt.HANDLE),
                ('hbrBackground', wt.HBRUSH), ('lpszMenuName', wt.LPCWSTR), ('lpszClassName', wt.LPCWSTR), ('hIconSm', wt.HICON)]


class APPBARDATA(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uCallbackMessage', wt.UINT), ('uEdge', wt.UINT),
                ('rc', wt.RECT), ('lParam', wt.LPARAM)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte), ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG), ('biPlanes', wt.WORD), ('biBitCount', wt.WORD),
                ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG),
                ('biClrUsed', wt.DWORD), ('biClrImportant', wt.DWORD)]


user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                       ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.SetCapture.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.CheckMenuRadioItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT, wt.UINT, wt.UINT]
user32.SetFocus.argtypes = [wt.HWND]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE          # a 64-bit handle must not be truncated to a C int
kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
user32.ReleaseCapture.argtypes = []
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wt.ATOM
shell32.SHAppBarMessage.argtypes = [wt.DWORD, ctypes.POINTER(APPBARDATA)]
shell32.SHAppBarMessage.restype = ctypes.c_size_t

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x8, 0x80, 0x80000, 0x08000000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
HWND_TOPMOST = wt.HWND(-1)
ULW_ALPHA = 2
WM_DESTROY, WM_MOUSEACTIVATE, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_QUIT, WM_NULL = \
    0x2, 0x21, 0x200, 0x201, 0x202, 0x203, 0x205, 0x12, 0x0
WM_TIMER, WM_CAPTURECHANGED = 0x113, 0x215
WM_NCHITTEST, WM_KEYDOWN, WM_KILLFOCUS = 0x84, 0x100, 0x8
HTTRANSPARENT, HTCLIENT = -1, 1
MA_ACTIVATE, MA_NOACTIVATE = 1, 3
WM_ACTIVATE, WM_MOUSEWHEEL, WA_INACTIVE = 0x6, 0x20A, 0
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR, MF_BYCOMMAND = 0x0, 0x1, 0x8, 0x10, 0x800, 0x0
TICK_TIMER_ID = 0x4D49
CS_DBLCLKS = 0x8
CLASS_NAME = 'MinisFighter'

_instances = {}
_class_registered = False
_wndproc_ref = None

# ---------------------------------------------------------------- the app icon (assets/icon/minis.ico)
from minis_core import paths as _paths  # noqa: E402  (checkout / PyInstaller / wheel)
ICON_PATH = _paths.icon_path('minis.ico')
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.LoadImageW.restype = wt.HANDLE
_class_icons = None


def load_icon(path=None, size=16):
    """HICON of `size` px from the .ico (Windows picks the matching entry; every size is hand-drawn), or None."""
    p = Path(path) if path else ICON_PATH
    if not p.exists():
        return None
    # IMAGE_ICON, LR_LOADFROMFILE
    return user32.LoadImageW(None, str(p), 1, int(size), int(size), 0x10) or None


def class_icons():
    """(hIcon, hIconSm) for window classes, loaded once at the system icon sizes (kept for the process lifetime:
    a class icon must outlive every window of the class).  (None, None) when the .ico is missing."""
    global _class_icons
    if _class_icons is None:
        try:
            big = user32.GetSystemMetrics(11) or 32                     # SM_CXICON
            small = user32.GetSystemMetrics(49) or 16                   # SM_CXSMICON
            _class_icons = (load_icon(None, big), load_icon(None, small))
        except Exception:
            _class_icons = (None, None)
    return _class_icons


def make_tray(tip, flags, on_choice, on_left, log=None, icon_path=None):
    """The director's notification-area icon (minis_win.tray), created and added.  Tests never reach this: their fake
    shells have no make_tray."""
    from minis_win import tray
    t = tray.Tray(tray.Win32Api(), str(icon_path or ICON_PATH), tip, flags, on_choice, on_left, log=log)
    t.create()
    return t


# ---------------------------------------------------------------- live re-layout: display, DPI, work area, Explorer restart
WM_DISPLAYCHANGE, WM_SETTINGCHANGE, WM_DPICHANGED, SPI_SETWORKAREA = 0x7E, 0x1A, 0x2E0, 0x2F
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
WM_TASKBARCREATED = user32.RegisterWindowMessageW('TaskbarCreated') or -1      # broadcast when Explorer (re)creates the taskbar
_layout = {'epoch': 0, 'why': None}


def layout_epoch():
    """A counter that every display change, DPI change, work-area change (the taskbar moved or resized) and Explorer restart
    bumps.  The fighter / scoreboard loops re-read the taskbar geometry at once when it moves (instead of within 2 s)."""
    return _layout['epoch']


def note_layout_change(why):
    _layout['epoch'] += 1
    _layout['why'] = why
    _parts_cache.clear()                                   # the taskbar's elements moved: probe them again


def _layout_message(msg, wparam):
    """The layout cause of a window message, or None."""
    if msg == WM_DISPLAYCHANGE:
        return 'display'
    if msg == WM_DPICHANGED:
        return 'dpi'
    if msg == WM_SETTINGCHANGE and wparam == SPI_SETWORKAREA:
        return 'workarea'
    if msg == WM_TASKBARCREATED:
        return 'taskbar-created'
    return None


def _wndproc(hwnd, msg, wparam, lparam):
    why = _layout_message(msg, wparam)
    if why:
        note_layout_change(why)
        if msg == WM_DPICHANGED:
            return 0                                       # we place our layered windows ourselves (no suggested-rect resize)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    ov = _instances.get(hwnd)
    if msg == WM_MOUSEACTIVATE:
        return MA_ACTIVATE if (ov and ov.activatable) else MA_NOACTIVATE      # fighters never steal focus
    if msg == WM_NCHITTEST and ov and ov.on_hittest:  # solid only where the owner says so (buttons); else click-through
        sx = ctypes.c_short(lparam & 0xFFFF).value
        sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        try:
            solid = ov.on_hittest((sx - ov.x) // ov.scale, (sy - ov.y) // ov.scale)
        except Exception:
            solid = False
        return HTCLIENT if solid else HTTRANSPARENT
    if msg == WM_ACTIVATE and ov and ov.on_blur and (wparam & 0xFFFF) == WA_INACTIVE:
        try:
            ov.on_blur()                                 # the select screen cancels when another window takes the focus
        except Exception:
            pass
        return 0
    if msg == WM_MOUSEWHEEL and ov and ov.on_event:
        try:
            ov.on_event('wheel', ctypes.c_short((wparam >> 16) & 0xFFFF).value, 0)
        except Exception:
            pass
        return 0
    if msg == WM_KEYDOWN and ov and ov.on_key:
        try:
            ov.on_key(int(wparam))
        except Exception:
            pass
        return 0
    if msg == WM_CAPTURECHANGED:                         # capture taken away (alt-tab, a menu, another window): the drag is over
        if ov and ov._dragging:
            ov._dragging = False
            if ov.on_event:
                ov.on_event('up', -1, -1)
        return 0
    if msg == WM_TIMER and wparam == TICK_TIMER_ID:     # also delivered inside the modal menu loop
        if ov and ov.on_timer:
            try:
                ov.on_timer()
            except Exception:
                pass
        return 0
    if ov and msg in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE, WM_LBUTTONDBLCLK, WM_RBUTTONUP):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        kind = {WM_LBUTTONDOWN: 'down', WM_LBUTTONUP: 'up', WM_MOUSEMOVE: 'move', WM_LBUTTONDBLCLK: 'dbl', WM_RBUTTONUP: 'rclick'}[msg]
        if msg == WM_LBUTTONDOWN:
            ov._dragging = True
            user32.SetCapture(hwnd)
        elif msg == WM_LBUTTONUP:
            ov._dragging = False
            user32.ReleaseCapture()
        if ov.on_event:
            ov.on_event(kind, x // ov.scale, y // ov.scale)
        return 0
    if msg == WM_DESTROY:
        _instances.pop(hwnd, None)
        if not _instances:   # only the last window ends the loop: closing the select popup used to quit the director
            user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register():
    global _class_registered, _wndproc_ref
    if _class_registered:
        return
    _wndproc_ref = WNDPROC(_wndproc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = CS_DBLCLKS
    wc.lpfnWndProc = _wndproc_ref
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = CLASS_NAME
    wc.hIcon, wc.hIconSm = class_icons()              # alt-tab / task manager; fighters are tool windows (no taskbar button)
    user32.RegisterClassExW(ctypes.byref(wc))
    _class_registered = True


class Overlay:
    """on_hittest(cx, cy) -> bool makes the window click-through except where it answers True (WM_NCHITTEST).
    activatable=True + on_key(vk) lets a window take focus on a click and read keys (the arena's ESC); fighters never do."""

    def __init__(self, title, x, y, w, h, scale=1, on_event=None, on_timer=None, on_hittest=None, on_key=None, activatable=False,
                 on_blur=None):
        _register()
        self.scale, self.on_event, self.on_timer = scale, on_event, on_timer
        self.on_hittest, self.on_key, self.activatable, self.on_blur = on_hittest, on_key, bool(activatable), on_blur
        self._dragging = False
        self._w = self._h = 0
        self.x, self.y, self.w, self.h = x, y, w * scale, h * scale
        ex = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | (0 if activatable else WS_EX_NOACTIVATE)
        self.hwnd = user32.CreateWindowExW(ex, CLASS_NAME, title, WS_POPUP, x, y, self.w, self.h, None, None,
                                           kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            raise OSError('CreateWindowExW failed: %d' % ctypes.get_last_error())
        _instances[self.hwnd] = self
        self._dc = self._bmp = self._old = None
        self._bits = ctypes.c_void_p()
        self.visible = True
        user32.ShowWindow(self.hwnd, 4)                     # SW_SHOWNOACTIVATE: a popup window is created hidden

    def _ensure_dib(self, w, h):
        if self._dc and (w, h) == (self._w, self._h):
            return
        self._free()
        sdc = user32.GetDC(None)
        try:
            dc = gdi32.CreateCompatibleDC(sdc)
            if not dc:
                raise OSError('CreateCompatibleDC failed: %d' % ctypes.get_last_error())
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not bmp or not bits.value:
                gdi32.DeleteDC(dc)
                raise OSError('CreateDIBSection failed: %d' % ctypes.get_last_error())
        finally:
            user32.ReleaseDC(None, sdc)
        self._dc, self._bmp, self._bits = dc, bmp, bits
        self._old = gdi32.SelectObject(self._dc, self._bmp)
        self._w, self._h = w, h

    def _free(self):
        if self._dc:
            gdi32.SelectObject(self._dc, self._old)
            gdi32.DeleteObject(self._bmp)
            gdi32.DeleteDC(self._dc)
            self._dc = None

    def present(self, img: Image.Image, x=None):
        if x is not None:
            self.x = int(x)
        if self.scale != 1:
            img = img.resize((img.width * self.scale, img.height * self.scale), Image.NEAREST)
        w, h = img.size
        r, g, b, a = img.split()
        pm = Image.merge('RGBA', (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a)).tobytes()
        self._ensure_dib(w, h)
        ctypes.memmove(self._bits, pm, len(pm))
        sdc = user32.GetDC(None)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        ok = user32.UpdateLayeredWindow(self.hwnd, sdc, ctypes.byref(wt.POINT(self.x, self.y)), ctypes.byref(wt.SIZE(w, h)),
                                        self._dc, ctypes.byref(wt.POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
        user32.ReleaseDC(None, sdc)
        return bool(ok)

    def reassert_topmost(self):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def set_scale(self, scale):
        self.scale = max(1, int(scale))

    def start_timer(self, ms):
        """A WM_TIMER tick that keeps running while a modal menu is open (the menu loop dispatches it to on_timer)."""
        return bool(self.hwnd and user32.SetTimer(self.hwnd, TICK_TIMER_ID, int(ms), None))

    def stop_timer(self):
        if self.hwnd:
            user32.KillTimer(self.hwnd, TICK_TIMER_ID)

    def move(self, x, y):
        self.x, self.y = x, y
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)

    def show(self, visible):
        if visible != self.visible:
            user32.ShowWindow(self.hwnd, 4 if visible else 0)      # SW_SHOWNOACTIVATE / SW_HIDE
            self.visible = visible

    def focus(self):
        """Take the keyboard focus (only the select screen does, and only while it is open)."""
        if self.hwnd and self.activatable:
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.hwnd)

    @staticmethod
    def build_menu(items):
        """A real Win32 popup menu from a spec (see menu()).  Submenus are owned by their parent: DestroyMenu on the
        returned handle frees them all."""
        hm = user32.CreatePopupMenu()
        for it in menu_entries(items):
            kind = it[0]
            if kind == 'sep':
                user32.AppendMenuW(hm, MF_SEPARATOR, 0, None)
            elif kind == 'sub':
                user32.AppendMenuW(hm, MF_POPUP, Overlay.build_menu(it[2]), it[1])
            else:
                _, mid, label, opt = it
                flags = MF_STRING | (MF_GRAYED if opt.get('disabled') else 0) | (MF_CHECKED if opt.get('checked') and not opt.get('radio') else 0)
                user32.AppendMenuW(hm, flags, mid, label)
                if opt.get('radio') and opt.get('checked'):
                    user32.CheckMenuRadioItem(hm, mid, mid, mid, MF_BYCOMMAND)      # a bullet instead of a tick
        return hm

    def menu(self, items):
        """items: (id, label) | (id, label, {'checked', 'radio', 'disabled'}) | None (separator) | (label, [items]) (submenu)
        -> chosen id or 0."""
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        hm = self.build_menu(items)
        user32.SetForegroundWindow(self.hwnd)
        ticking = self.on_timer is not None and self.start_timer(250)          # heartbeat + keep-on-top while the menu is up
        try:
            choice = user32.TrackPopupMenu(hm, 0x0100 | 0x0080, pt.x, pt.y, 0, self.hwnd, None)     # RETURNCMD | NONOTIFY
        finally:
            if ticking:
                self.stop_timer()
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            user32.DestroyMenu(hm)
        return choice

    def pump(self):
        msg = wt.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == WM_QUIT:
                return False
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True

    def close(self):
        self.stop_timer()
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        self._free()


def menu_entries(items):
    """Normalise a menu spec: -> [('sep',) | ('sub', label, items) | ('item', id, label, opts)].  Pure (tested headless)."""
    out = []
    for it in items or ():
        if it is None or it == '-':
            out.append(('sep',))
        elif len(it) >= 2 and isinstance(it[1], (list, tuple)) and not isinstance(it[0], int):
            out.append(('sub', str(it[0]), list(it[1])))
        else:
            opt = it[2] if len(it) > 2 and isinstance(it[2], dict) else {}
            out.append(('item', int(it[0]), str(it[1]), opt))
    return out


# ---------------------------------------------------------------- taskbar + desktop helpers
def taskbar_rect():
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    shell32.SHAppBarMessage(5, ctypes.byref(abd))          # ABM_GETTASKBARPOS
    r = abd.rc
    return r.left, r.top, r.right, r.bottom, abd.uEdge


def taskbar_autohide():
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    return bool(shell32.SHAppBarMessage(4, ctypes.byref(abd)) & 0x1)       # ABM_GETSTATE & ABS_AUTOHIDE


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ---------------------------------------------------------------- the taskbar's geometry for config.stage(): RECTS only
user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND
user32.MonitorFromRect.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD]
user32.MonitorFromRect.restype = wt.HMONITOR
user32.EnumChildWindows.argtypes = [wt.HWND, ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
user32.GetDpiForSystem.restype = wt.UINT
if shcore is not None:
    shcore.GetDpiForMonitor.argtypes = [wt.HMONITOR, ctypes.c_int, ctypes.POINTER(wt.UINT), ctypes.POINTER(wt.UINT)]

# Taskbar element windows whose rects mark occupied space, Windows 10 and 11 (class names of the shell's own windows; no
# window text is read).  MSTaskListWClass hugs the icon cluster on Windows 11 (build 22000+, where it is a hidden stand-in
# the XAML taskbar keeps in place); on Windows 10 it spans the whole free stretch, so it only counts on 11.
PART_CLASSES = ('Start', 'TrayButton', 'TrayNotifyWnd', 'TrayDummySearchControl')
PARTS_TTL_S = 5.0                                          # the icon cluster is re-probed this often (it grows and shrinks)
_parts_cache = {}


def _rect_of(hwnd):
    r = wt.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def _windows_build():
    try:
        import sys
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def monitor_dpi(rect):
    """The effective DPI scale (1.0 = 100%) of the monitor holding `rect`; the system DPI when the per-monitor call is missing."""
    try:
        hmon = user32.MonitorFromRect(ctypes.byref(wt.RECT(*rect)), 2)            # MONITOR_DEFAULTTONEAREST
        if shcore is not None and hmon:
            x, y = wt.UINT(), wt.UINT()
            if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:   # MDT_EFFECTIVE_DPI
                return x.value / 96.0
    except (AttributeError, OSError):
        pass
    try:
        return (user32.GetDpiForSystem() or 96) / 96.0
    except (AttributeError, OSError):
        return 1.0


def win32_part_rects(tray_hwnd, build=None):
    """Rects of the taskbar's own child windows that mark occupied space (start, task view / search buttons, tray, and on
    Windows 11 the icon cluster's stand-in).  The fallback when UI Automation is unavailable."""
    build = _windows_build() if build is None else build
    out = []

    def cb(h, lp):
        cls = _class_name(h)
        if cls in PART_CLASSES or (cls == 'MSTaskListWClass' and build >= 22000):
            r = _rect_of(h)
            if r and r[2] > r[0] and r[3] > r[1]:
                out.append(r)
        return True
    user32.EnumChildWindows(tray_hwnd, ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    return out


def uia_part_rects(tray_hwnd):
    """BoundingRectangle of every on-screen UI Automation element inside the taskbar (start, search, task view, widgets, each
    app button, tray icons, clock) - the only accurate source for the XAML taskbar of Windows 11, whose buttons have no
    windows.  Raw COM through ctypes (no extra package); ONLY the rect and the offscreen flag are read, never a name, a value
    or a class.  None when UI Automation cannot be used."""
    from minis_win import uia
    return uia.descendant_rects(tray_hwnd)


def taskbar_parts(tray_hwnd, now=None):
    """(rects, source) of the taskbar's elements, cached PARTS_TTL_S per taskbar window (and dropped on any layout change)."""
    import time as _t
    now = _t.monotonic() if now is None else now
    key = int(tray_hwnd or 0)
    got = _parts_cache.get(key)
    if got and now - got[0] < PARTS_TTL_S:
        return got[1], got[2]
    rects, src = None, None
    try:
        rects = uia_part_rects(tray_hwnd)
        src = 'uia' if rects else None
    except Exception:
        rects = None
    if not rects:
        try:
            rects = win32_part_rects(tray_hwnd)
            src = 'win32' if rects else None
        except Exception:
            rects = None
    _parts_cache[key] = (now, rects or None, src)
    return rects or None, src


def _secondary_taskbars():
    out, h = [], None
    while True:
        h = user32.FindWindowExW(None, h, 'Shell_SecondaryTrayWnd', None)
        if not h:
            return out
        r = _rect_of(h)
        if r:
            out.append((h, r))


def _contains(outer, rect):
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    return outer[0] <= cx < outer[2] and outer[1] <= cy < outer[3]


def taskbar_info(monitor=None):
    """Everything config.stage() needs about the taskbar the fighters use, rects only: the primary taskbar, or with
    `monitor` (an index from monitors()) that monitor's secondary taskbar.  Auto-hide: where the bar sits when shown, and
    whether it is shown right now."""
    from minis_core import config as cfgmod
    mons = monitors()
    primary = next((m for m in mons if m['primary']), mons[0] if mons else None)
    hwnd, note = None, None
    rect = edge = None
    target = next((m for m in mons if m['index'] == monitor), None) if monitor else None
    if target is not None and not target['primary']:
        for h, r in _secondary_taskbars():
            if _contains(target['rect'], r):
                hwnd, rect, edge = h, r, cfgmod.edge_of(r, target['rect'])
                break
        if hwnd is None:
            note = f'monitor {monitor} has no taskbar: using the primary'
    if hwnd is None:
        hwnd = user32.FindWindowW('Shell_TrayWnd', None)
        l, t, r, b, edge = taskbar_rect()
        rect = (l, t, r, b)
    mon = next((m for m in mons if _contains(m['rect'], rect)), primary)
    mrect = mon['rect'] if mon else rect
    autohide = taskbar_autohide()
    revealed = True
    if autohide:
        cur = _rect_of(hwnd) or rect
        th = (rect[3] - rect[1]) if edge in (1, 3) else (rect[2] - rect[0])
        rect, revealed = cfgmod.autohide_shown(cur, mrect, edge, thickness=th)
    parts, src = taskbar_parts(hwnd) if hwnd else (None, None)
    return dict(rect=tuple(rect), edge=int(edge), autohide=autohide, revealed=revealed, monitor=tuple(mrect),
                work=tuple(mon['work']) if mon else tuple(mrect), dpi=monitor_dpi(rect), parts=parts, parts_src=src,
                monitor_index=mon['index'] if mon else None, note=note)


def fullscreen_busy():
    """True while a fullscreen app / game / presentation is up (QUNS_BUSY, D3D fullscreen, presentation)."""
    st = ctypes.c_int()
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0:
            return st.value in (2, 3, 4)
    except Exception:
        pass
    return False


def raise_taskbar():
    """What a click on the taskbar does: it re-asserts itself as topmost (used by the self-test)."""
    tray = user32.FindWindowW('Shell_TrayWnd', None)
    if tray:
        user32.SetWindowPos(tray, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    return bool(tray)


def cursor_pos():
    pt = wt.POINT()
    return (pt.x, pt.y) if user32.GetCursorPos(ctypes.byref(pt)) else None


def shift_down():
    return bool(user32.GetKeyState(0x10) & 0x8000)            # VK_SHIFT


def make_mutex(name):
    h = kernel32.CreateMutexW(None, False, name)
    return h, ctypes.get_last_error() == 183              # (handle, already_running)


# ---------------------------------------------------------------- monitors + window rectangles (arena stage)
class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT), ('dwFlags', wt.DWORD)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM]
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.GetDesktopWindow.restype = wt.HWND
user32.GetShellWindow.restype = wt.HWND
try:
    dwmapi = ctypes.WinDLL('dwmapi')
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
except OSError:
    dwmapi = None
GWL_EXSTYLE, DWMWA_CLOAKED = -20, 14


def monitors():
    """-> [{'index': 1-based, 'rect': (l, t, r, b), 'work': (l, t, r, b), 'primary': bool, 'scale': DPI scale}] in
    enumeration order (physical px: the process is per-monitor DPI aware)."""
    out = []

    def cb(hmon, hdc, prc, lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r, w = mi.rcMonitor, mi.rcWork
            scale = 1.0
            try:
                x, y = wt.UINT(), wt.UINT()
                if shcore is not None and shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
                    scale = x.value / 96.0
            except (AttributeError, OSError):
                pass
            out.append(dict(index=len(out) + 1, rect=(r.left, r.top, r.right, r.bottom), work=(w.left, w.top, w.right, w.bottom),
                            primary=bool(mi.dwFlags & 1), scale=scale))
        return True
    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return out


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def _cloaked(hwnd):
    if dwmapi is None:
        return False
    v = wt.DWORD(0)
    try:
        return dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4) == 0 and v.value != 0
    except Exception:
        return False


OWN_CLASSES = (CLASS_NAME, 'MinisArena')
SKIP_CLASSES = ('Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Progman', 'WorkerW', 'Windows.UI.Core.CoreWindow')


def window_rects(exclude=()):
    """Rectangles of visible top-level windows, top of the z-order first: [(hwnd, l, t, r, b)].  Rectangles only -
    no titles are read, ever.  Our own windows, the shell/taskbar and cloaked (hidden UWP) windows are left out."""
    out = []
    excl = set(int(h) for h in exclude if h)
    shell_win = user32.GetShellWindow()

    def cb(hwnd, lp):
        if int(hwnd) in excl or hwnd == shell_win or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetAncestor(hwnd, 2) != hwnd:                     # GA_ROOT: only top-level windows
            return True
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        cls = _class_name(hwnd)
        if cls in OWN_CLASSES or cls in SKIP_CLASSES or _cloaked(hwnd):
            return True
        r = wt.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)) and r.right > r.left and r.bottom > r.top:
            out.append((int(hwnd), r.left, r.top, r.right, r.bottom))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def find_own_window(class_name='MinisArena'):
    """hwnd of one of OUR windows by its class name (never by title), or 0."""
    return user32.FindWindowW(class_name, None) or 0


def capture_window(hwnd):
    """PrintWindow(PW_RENDERFULLCONTENT) of ONE window into a PIL image: the window's own pixels, never the desktop."""
    r = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    sdc = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(sdc)
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    im = None
    try:
        old = gdi32.SelectObject(dc, bmp)
        ok = user32.PrintWindow(hwnd, dc, 2)
        if ok:
            raw = ctypes.string_at(bits, w * h * 4)
            im = Image.frombuffer('RGBA', (w, h), raw, 'raw', 'BGRA', 0, 1).copy()
        gdi32.SelectObject(dc, old)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, sdc)
    return im
