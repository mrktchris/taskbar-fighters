"""The streamer-mode window on Windows (growth): an ordinary app window OBS can capture.

Default: WS_OVERLAPPEDWINDOW - title bar, resizable border, a taskbar button, alt-tab; NOT layered, NOT topmost, NOT
click-through.  Frames are painted with SetDIBitsToDevice from the composited image minis_core/stream.py hands over
(already scaled to the client size and filled with the key colour).

--transparent (experimental): a layered popup (UpdateLayeredWindow, per-pixel alpha) that is still an app window with a
taskbar button and not topmost.  Drag anywhere to move it, drag the bottom-right corner to resize it, Esc or a right
click closes it.  Whether a capture tool keeps its alpha depends on the tool: see docs/STREAMING.md.

Nothing here reads the screen or another window.
"""
from __future__ import annotations
import ctypes, time
from ctypes import wintypes as wt
from PIL import Image, ImageChops

from minis_win import shell as sh

u, g = sh.user32, sh.gdi32
CLASS = 'MinisStream'
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_APPWINDOW = 0x00040000
CW_USEDEFAULT = -0x80000000                       # 0x80000000 as the signed int CreateWindowExW takes
WM_PAINT, WM_ERASEBKGND, WM_SIZE, WM_CLOSE, WM_GETMINMAXINFO, WM_RBUTTONUP = 0x0F, 0x14, 0x05, 0x10, 0x24, 0x205
HTCAPTION, HTBOTTOMRIGHT = 2, 17
VK_ESCAPE = 0x1B
GRIP = 16
MIN_W, MIN_H = 160, 60


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [('hdc', wt.HDC), ('fErase', wt.BOOL), ('rcPaint', wt.RECT), ('fRestore', wt.BOOL), ('fIncUpdate', wt.BOOL),
                ('rgbReserved', ctypes.c_byte * 32)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [('ptReserved', wt.POINT), ('ptMaxSize', wt.POINT), ('ptMaxPosition', wt.POINT), ('ptMinTrackSize', wt.POINT),
                ('ptMaxTrackSize', wt.POINT)]


u.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
u.BeginPaint.restype = wt.HDC
u.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
u.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
u.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
g.SetDIBitsToDevice.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD, wt.DWORD, ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT,
                                ctypes.c_void_p, ctypes.POINTER(sh.BITMAPINFOHEADER), wt.UINT]

_windows = {}
_proc_ref = None
_registered = False


def _proc(hwnd, msg, wparam, lparam):
    w = _windows.get(hwnd)
    if w is not None:
        try:
            r = w.handle(msg, wparam, lparam)
            if r is not None:
                return r
        except Exception:
            pass
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register():
    global _proc_ref, _registered
    if _registered:
        return
    _proc_ref = sh.WNDPROC(_proc)
    wc = sh.WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(sh.WNDCLASSEXW)
    wc.lpfnWndProc = _proc_ref
    wc.hInstance = sh.kernel32.GetModuleHandleW(None)
    wc.lpszClassName = CLASS
    wc.hIcon, wc.hIconSm = sh.class_icons()
    wc.hCursor = u.LoadCursorW(None, ctypes.c_void_p(32512))       # IDC_ARROW
    u.RegisterClassExW(ctypes.byref(wc))
    _registered = True


u.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
u.LoadCursorW.restype = wt.HANDLE


class StreamWindow:
    def __init__(self, title, w, h, transparent=False, bg=(0, 255, 0), show_cmd=5):
        """show_cmd: ShowWindow's nCmdShow (5 SW_SHOW; tools/stream_preview.py passes 4, SW_SHOWNOACTIVATE)."""
        _register()
        self.transparent, self.bg = bool(transparent), tuple(bg)
        self.closed = False
        self.frame = None
        self._dc = self._bmp = self._old = None
        self._bits = ctypes.c_void_p()
        self._dib = (0, 0)
        hinst = sh.kernel32.GetModuleHandleW(None)
        if self.transparent:
            style, ex = sh.WS_POPUP, sh.WS_EX_LAYERED | WS_EX_APPWINDOW
            x, y, ww, hh = 120, 120, int(w), int(h)
        else:
            style, ex = WS_OVERLAPPEDWINDOW, WS_EX_APPWINDOW
            rc = wt.RECT(0, 0, int(w), int(h))
            u.AdjustWindowRectEx(ctypes.byref(rc), style, False, ex)     # w x h is the CLIENT size
            x, y, ww, hh = CW_USEDEFAULT, CW_USEDEFAULT, rc.right - rc.left, rc.bottom - rc.top
        self.hwnd = u.CreateWindowExW(ex, CLASS, title, style, x, y, ww, hh, None, None, hinst, None)
        if not self.hwnd:
            raise OSError('stream window: CreateWindowExW failed: %d' % ctypes.get_last_error())
        _windows[self.hwnd] = self
        self.x, self.y = (x, y) if self.transparent else (0, 0)
        self._size = (int(w), int(h)) if self.transparent else None
        u.ShowWindow(self.hwnd, int(show_cmd))                           # SW_SHOW: a normal app window, it may take the focus

    # -------------------------------------------------------------- messages
    def handle(self, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1                                                     # the frame covers the whole client: no flicker
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = u.BeginPaint(self.hwnd, ctypes.byref(ps))
            try:
                if self.frame is not None and not self.transparent:
                    self._blit(hdc, self.frame)
            finally:
                u.EndPaint(self.hwnd, ctypes.byref(ps))
            return 0
        if msg == WM_GETMINMAXINFO:
            mm = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            mm.ptMinTrackSize.x, mm.ptMinTrackSize.y = MIN_W, MIN_H
            return 0
        if msg == WM_SIZE and self.transparent:
            self._size = (max(MIN_W, lparam & 0xFFFF), max(MIN_H, (lparam >> 16) & 0xFFFF))
            return 0
        if self.transparent and msg == sh.WM_NCHITTEST:
            sx = ctypes.c_short(lparam & 0xFFFF).value
            sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            r = wt.RECT()
            u.GetWindowRect(self.hwnd, ctypes.byref(r))
            if sx >= r.right - GRIP and sy >= r.bottom - GRIP:
                return HTBOTTOMRIGHT
            return HTCAPTION                                             # drag anywhere to move
        if self.transparent and (msg == WM_RBUTTONUP or msg == 0xA5 or (msg == sh.WM_KEYDOWN and wparam == VK_ESCAPE)):
            u.DestroyWindow(self.hwnd)                                   # 0xA5 = WM_NCRBUTTONUP (the body is a caption)
            return 0
        if msg == WM_CLOSE:
            u.DestroyWindow(self.hwnd)
            return 0
        if msg == sh.WM_DESTROY:
            self.closed = True
            _windows.pop(self.hwnd, None)
            return 0
        return None

    # -------------------------------------------------------------- drawing
    def client_size(self):
        if self.transparent:
            return self._size
        r = wt.RECT()
        u.GetClientRect(self.hwnd, ctypes.byref(r))
        return max(1, r.right - r.left), max(1, r.bottom - r.top)

    def _blit(self, hdc, img):
        w, h = img.size
        bmi = sh.BITMAPINFOHEADER(ctypes.sizeof(sh.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        data = img.convert('RGB').tobytes('raw', 'BGRX')
        g.SetDIBitsToDevice(hdc, 0, 0, w, h, 0, 0, 0, h, data, ctypes.byref(bmi), 0)

    def present(self, img: Image.Image):
        if self.closed:
            return False
        self.frame = img
        if self.transparent:
            return self._layered(img)
        hdc = u.GetDC(self.hwnd)
        try:
            self._blit(hdc, img)
        finally:
            u.ReleaseDC(self.hwnd, hdc)
        return True

    def _layered(self, img):
        w, h = img.size
        r, gg, b, a = img.split()
        pm = Image.merge('RGBA', (ImageChops.multiply(b, a), ImageChops.multiply(gg, a), ImageChops.multiply(r, a), a)).tobytes()
        if self._dib != (w, h):
            self._free()
            sdc = u.GetDC(None)
            try:
                self._dc = g.CreateCompatibleDC(sdc)
                bmi = sh.BITMAPINFOHEADER(ctypes.sizeof(sh.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
                self._bmp = g.CreateDIBSection(self._dc, ctypes.byref(bmi), 0, ctypes.byref(self._bits), None, 0)
                self._old = g.SelectObject(self._dc, self._bmp)
            finally:
                u.ReleaseDC(None, sdc)
            self._dib = (w, h)
        ctypes.memmove(self._bits, pm, len(pm))
        wr = wt.RECT()
        u.GetWindowRect(self.hwnd, ctypes.byref(wr))
        sdc = u.GetDC(None)
        try:
            return bool(u.UpdateLayeredWindow(self.hwnd, sdc, ctypes.byref(wt.POINT(wr.left, wr.top)), ctypes.byref(wt.SIZE(w, h)),
                                              self._dc, ctypes.byref(wt.POINT(0, 0)), 0, ctypes.byref(sh.BLENDFUNCTION(0, 0, 255, 1)),
                                              sh.ULW_ALPHA))
        finally:
            u.ReleaseDC(None, sdc)

    def _free(self):
        if self._dc:
            g.SelectObject(self._dc, self._old)
            g.DeleteObject(self._bmp)
            g.DeleteDC(self._dc)
            self._dc = None
            self._dib = (0, 0)

    # -------------------------------------------------------------- loop
    def pump(self):
        msg = wt.MSG()
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == sh.WM_QUIT:
                return False
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        return not self.closed

    def wait(self, seconds):
        time.sleep(max(0.0, min(0.5, seconds)))

    def close(self):
        if not self.closed and self.hwnd:
            u.DestroyWindow(self.hwnd)
        self.closed = True
        self._free()
