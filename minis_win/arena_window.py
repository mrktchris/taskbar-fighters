"""The arena overlay: one full-monitor layered, topmost window that is click-through everywhere except the EXIT button.

Drawing is incremental.  The window keeps a persistent premultiplied-BGRA DIB the size of the monitor; the arena
compositor writes only the rectangles that changed (`write`), and `flush` hands exactly those to
UpdateLayeredWindowIndirect with `prcDirty`, so a frame costs the dirty pixels, never the whole 2560x1440 surface.
Screen shake moves THIS window (`offset`) - never any other window.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
from PIL import Image, ImageChops

from . import shell
from .shell import user32, gdi32, kernel32, BLENDFUNCTION, BITMAPINFOHEADER, WS_POPUP, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_LAYERED, \
    HWND_TOPMOST, SWP_NOSIZE, SWP_NOACTIVATE, SWP_NOMOVE, ULW_ALPHA, WNDCLASSEXW, WNDPROC, CS_DBLCLKS

ARENA_CLASS = 'MinisArena'
VK_ESCAPE = 0x1B


class UPDATELAYEREDWINDOWINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('hdcDst', wt.HDC), ('pptDst', ctypes.POINTER(wt.POINT)), ('psize', ctypes.POINTER(wt.SIZE)),
                ('hdcSrc', wt.HDC), ('pptSrc', ctypes.POINTER(wt.POINT)), ('crKey', wt.COLORREF), ('pblend', ctypes.POINTER(BLENDFUNCTION)),
                ('dwFlags', wt.DWORD), ('prcDirty', ctypes.POINTER(wt.RECT))]


user32.UpdateLayeredWindowIndirect.argtypes = [wt.HWND, ctypes.POINTER(UPDATELAYEREDWINDOWINFO)]
user32.UpdateLayeredWindowIndirect.restype = wt.BOOL

_registered = False
_proc_ref = None


def _register():
    global _registered, _proc_ref
    if _registered:
        return
    _proc_ref = WNDPROC(shell._wndproc)                   # same message handling as the fighters (hit-test, keys, mouse)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = CS_DBLCLKS
    wc.lpfnWndProc = _proc_ref
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = ARENA_CLASS
    wc.hIcon, wc.hIconSm = shell.class_icons()
    user32.RegisterClassExW(ctypes.byref(wc))
    _registered = True


def premultiplied_bgra(img):
    r, g, b, a = img.split()
    return Image.merge('RGBA', (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a)).tobytes()


class ArenaWindow:
    """rect = (l, t, r, b) of the monitor in screen px.  on_hittest(x, y) says where the window is solid (the EXIT
    button); on_click(x, y) fires on a left click there; on_key(vk) gets key presses while the window has focus."""

    def __init__(self, rect, on_hittest=None, on_click=None, on_key=None, title='minis-arena'):
        _register()
        l, t, r, b = rect
        self.x, self.y, self.w, self.h = int(l), int(t), int(r - l), int(b - t)
        self.scale = 1
        self.activatable = True
        self.on_hittest, self.on_key, self.on_timer = on_hittest, on_key, None
        self.on_click = on_click
        self._dragging = False
        self.on_event = self._mouse
        ex = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED
        self.hwnd = user32.CreateWindowExW(ex, ARENA_CLASS, title, WS_POPUP, self.x, self.y, self.w, self.h, None, None,
                                           kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            raise OSError('CreateWindowExW failed: %d' % ctypes.get_last_error())
        shell._instances[self.hwnd] = self
        self.visible = False
        self._dirty = []
        self._offset = (0, 0)
        sdc = user32.GetDC(None)
        try:
            self._dc = gdi32.CreateCompatibleDC(sdc)
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), self.w, -self.h, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            self._bmp = gdi32.CreateDIBSection(self._dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not self._dc or not self._bmp or not bits.value:
                raise OSError('arena DIB failed: %d' % ctypes.get_last_error())
            self._bits = bits
            self._old = gdi32.SelectObject(self._dc, self._bmp)
        finally:
            user32.ReleaseDC(None, sdc)
        ctypes.memset(self._bits, 0, self.w * self.h * 4)
        self.flush(full=True)
        user32.ShowWindow(self.hwnd, 4)                       # SW_SHOWNOACTIVATE
        self.visible = True

    # ---- mouse / keys (shell._wndproc calls on_event with client coords)
    def _mouse(self, kind, x, y):
        if kind == 'down' and self.on_click:
            try:
                self.on_click(x, y)
            except Exception:
                pass

    # ---- drawing
    def write(self, img, x, y):
        """Replace the rect at (x, y) with `img` (RGBA, straight alpha); clipped to the window."""
        x, y = int(x), int(y)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + img.width), min(self.h, y + img.height)
        if x1 <= x0 or y1 <= y0:
            return
        if (x0, y0, x1, y1) != (x, y, x + img.width, y + img.height):
            img = img.crop((x0 - x, y0 - y, x1 - x, y1 - y))
        data = premultiplied_bgra(img)
        row = img.width * 4
        base = self._bits.value + (y0 * self.w + x0) * 4
        stride = self.w * 4
        if img.width == self.w and x0 == 0:
            ctypes.memmove(base, data, len(data))
        else:
            for j in range(img.height):
                ctypes.memmove(base + j * stride, data[j * row:(j + 1) * row], row)
        self._dirty.append((x0, y0, x1, y1))

    def fill(self, rgba):
        """V9: the whole window one colour (straight alpha) - a colour / white flash's empty screen, or clearing it - as
        one premultiplied row repeated into the DIB: a few ms instead of premultiplying a monitor-sized image (~30 ms at
        1920x1080).  The arena compositor then writes only the drawables' rects on top."""
        px = premultiplied_bgra(Image.new('RGBA', (1, 1), tuple(int(v) for v in rgba)))
        ctypes.memmove(self._bits.value, px * (self.w * self.h), self.w * self.h * 4)
        self._dirty.append((0, 0, self.w, self.h))

    def flush(self, full=False):
        """Push the dirty rectangles to the screen (one UpdateLayeredWindowIndirect per merged rect)."""
        rects = [(0, 0, self.w, self.h)] if full else merge_rects(self._dirty)
        self._dirty = []
        if not rects:
            return True
        sdc = user32.GetDC(None)
        ok = True
        try:
            blend = BLENDFUNCTION(0, 0, 255, 1)
            pos = wt.POINT(self.x + self._offset[0], self.y + self._offset[1])
            size = wt.SIZE(self.w, self.h)
            src = wt.POINT(0, 0)
            for (x0, y0, x1, y1) in rects:
                rc = wt.RECT(x0, y0, x1, y1)
                info = UPDATELAYEREDWINDOWINFO(ctypes.sizeof(UPDATELAYEREDWINDOWINFO), sdc, ctypes.pointer(pos), ctypes.pointer(size), self._dc,
                                               ctypes.pointer(src), 0, ctypes.pointer(blend), ULW_ALPHA, ctypes.pointer(rc))
                if not user32.UpdateLayeredWindowIndirect(self.hwnd, ctypes.byref(info)):
                    ok = False
        finally:
            user32.ReleaseDC(None, sdc)
        return ok

    def offset(self, dx, dy):
        """Screen shake: move this window by (dx, dy) from its home position."""
        if (dx, dy) != self._offset:
            self._offset = (int(dx), int(dy))
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, self.x + self._offset[0], self.y + self._offset[1], 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)

    def reassert_topmost(self):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def pump(self):
        msg = wt.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == shell.WM_QUIT:
                return False
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True

    def show(self, visible):
        if visible != self.visible:
            user32.ShowWindow(self.hwnd, 4 if visible else 0)
            self.visible = visible

    def close(self):
        if self.hwnd:
            shell._instances.pop(self.hwnd, None)
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if getattr(self, '_dc', None):
            gdi32.SelectObject(self._dc, self._old)
            gdi32.DeleteObject(self._bmp)
            gdi32.DeleteDC(self._dc)
            self._dc = None


from minis_platform.rects import merge_rects  # noqa: E402,F401  (moved: pure, so the tests run on every OS)
