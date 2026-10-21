"""UI Automation, rects only: the bounding rectangles of the elements inside one window (the taskbar).

Raw COM through ctypes (no comtypes / pywin32).  Exactly two properties are ever read per element: BoundingRectangle and
IsOffscreen.  Never a name, value, class or anything a user typed.  Each probe runs on its own short-lived thread with its own
COM apartment and a deadline, so a hung Explorer can never freeze a fighter loop: a probe that misses the deadline returns
None (the caller falls back to window rects) and UIA is not tried again until that thread has finished.
"""
from __future__ import annotations
import ctypes
import threading
import uuid
from ctypes import wintypes as wt

CLSID_CUIAutomation = 'ff48dba4-60ef-4201-aa87-54103eef594e'
IID_IUIAutomation = '30cbe57d-d9d0-452a-ab13-7ac5ac4825ee'
TreeScope_Descendants = 4
# vtable slots (IUnknown 0-2 first)
AUTO_ELEMENT_FROM_HANDLE, AUTO_CREATE_TRUE_CONDITION = 6, 21
EL_FIND_ALL, EL_IS_OFFSCREEN, EL_BOUNDING_RECT = 6, 38, 43
ARR_LENGTH, ARR_ELEMENT = 3, 4
RELEASE = 2
MAX_ELEMENTS = 400
DEADLINE_S = 1.5

_busy = threading.Event()                                  # a probe thread is still running (maybe stuck in Explorer)


class GUID(ctypes.Structure):
    _fields_ = [('d1', ctypes.c_ulong), ('d2', ctypes.c_ushort), ('d3', ctypes.c_ushort), ('d4', ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s):
        g = cls()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
        return g


def _call(obj, slot, argtypes, *args, restype=ctypes.c_long):      # c_long: a failed HRESULT is a value, not an exception
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[slot])(obj, *args)


def _release(p):
    if p:
        try:
            _call(p, RELEASE, (), restype=ctypes.c_ulong)
        except OSError:
            pass


def _probe(hwnd):
    """[(l, t, r, b)] of the on-screen descendants of `hwnd` (runs on the calling thread; COM initialised here)."""
    ole = ctypes.WinDLL('ole32')
    ole.CoInitializeEx(None, 0)                            # COINIT_MULTITHREADED, this thread only
    auto = el = cond = arr = None
    try:
        p = ctypes.c_void_p()
        if ole.CoCreateInstance(ctypes.byref(GUID.of(CLSID_CUIAutomation)), None, 1,         # CLSCTX_INPROC_SERVER
                                ctypes.byref(GUID.of(IID_IUIAutomation)), ctypes.byref(p)) != 0 or not p.value:
            return None
        auto = p.value
        out = ctypes.c_void_p()
        PP = ctypes.POINTER(ctypes.c_void_p)
        _call(auto, AUTO_ELEMENT_FROM_HANDLE, (wt.HWND, PP), wt.HWND(hwnd), ctypes.byref(out))
        el, out = out.value, ctypes.c_void_p()
        if not el:
            return None
        _call(auto, AUTO_CREATE_TRUE_CONDITION, (PP,), ctypes.byref(out))
        cond, out = out.value, ctypes.c_void_p()
        _call(el, EL_FIND_ALL, (ctypes.c_int, ctypes.c_void_p, PP), TreeScope_Descendants, cond, ctypes.byref(out))
        arr = out.value
        if not arr:
            return None
        n = ctypes.c_int()
        _call(arr, ARR_LENGTH, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(n))
        rects = []
        for i in range(min(n.value, MAX_ELEMENTS)):
            e = ctypes.c_void_p()
            if _call(arr, ARR_ELEMENT, (ctypes.c_int, PP), i, ctypes.byref(e)) != 0 or not e.value:
                continue
            try:
                off, r = wt.BOOL(), wt.RECT()
                if _call(e.value, EL_IS_OFFSCREEN, (ctypes.POINTER(wt.BOOL),), ctypes.byref(off)) == 0 and off.value:
                    continue
                if _call(e.value, EL_BOUNDING_RECT, (ctypes.POINTER(wt.RECT),), ctypes.byref(r)) == 0 and r.right > r.left and r.bottom > r.top:
                    rects.append((r.left, r.top, r.right, r.bottom))
            finally:
                _release(e.value)
        return rects
    except OSError:
        return None
    finally:
        for x in (arr, cond, el, auto):
            _release(x)
        ole.CoUninitialize()


def descendant_rects(hwnd, deadline_s=DEADLINE_S):
    """_probe on a worker thread with a deadline.  None when UIA is unavailable, failed, or is still stuck in a previous probe."""
    if not hwnd or _busy.is_set():
        return None
    box = {}

    def run():
        try:
            box['rects'] = _probe(int(hwnd))
        except Exception:
            box['rects'] = None
        finally:
            _busy.clear()
    _busy.set()
    t = threading.Thread(target=run, name='minis-uia', daemon=True)
    t.start()
    t.join(deadline_s)
    return box.get('rects') if not t.is_alive() else None
