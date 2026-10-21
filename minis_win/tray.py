"""The notification-area (tray) icon, hosted by the director process.

- Tooltip: "Taskbar Fighters - <a> vs <b>" from assign.json display names only (program names / short labels); never a window title,
  a prompt or a path.
- Left click: the fighter-select screen.  Right click: a real Win32 popup menu (tray_menu below).
- Explorer restarts broadcast the registered "TaskbarCreated" message: the icon is added again.
- remove() (NIM_DELETE) is idempotent; the director calls it in a finally and through atexit.

Split for tests: `Tray` is the logic and talks to Windows only through `api` (Win32Api here; tests pass a fake), so no
test ever creates a real window or icon.  The director gets a real tray only through minis_win.shell.make_tray.
"""
from __future__ import annotations
import logging

# menu ids (never 0: TrackPopupMenu returns 0 for "nothing chosen")
SELECT, PAUSE, FLASH, PLATES, RIVAL, ARENA, BOUT, RESTART, QUIT = range(1, 10)
FORGE = 10                                       # V8: Desktop weapons (the arena's RAM-only screen grab)
CARD, STREAM = 11, 12                            # growth: Share my stats card..., Streamer mode
PRODUCT = 'Taskbar Fighters'                    # the user-visible name; internal names (minis.py, data dir) stay
TIP_MAX = 127                                         # NOTIFYICONDATAW.szTip is WCHAR[128]
WM_TRAY = 0x8000 + 0x4D                               # WM_APP + 'M': the icon's callback message
TRAY_UID = 1
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x202, 0x205, 0x7B


def tray_menu(flags):
    """-> items for minis_win.shell.Overlay.build_menu.  flags: paused, flash, forge, plates, rival, arena, stream (bools);
    select_ok / arena_ok (False greys the item out: no scoreboard host in this director)."""
    f = flags or {}
    return [(SELECT, 'Select fighters…', {'disabled': not f.get('select_ok', True)}),
            None,
            (PAUSE, 'Pause animations', {'checked': bool(f.get('paused'))}),
            (FLASH, 'Flash effects', {'checked': bool(f.get('flash', True))}),
            (FORGE, 'Desktop weapons', {'checked': bool(f.get('forge', True))}),
            (PLATES, 'Plates', {'checked': bool(f.get('plates', True))}),
            (RIVAL, 'Rival mode', {'checked': bool(f.get('rival', True))}),
            (ARENA, 'Exit arena' if f.get('arena') else 'Start arena', {'disabled': not f.get('arena_ok', True)}),
            (BOUT, 'Bout now'),
            None,
            (CARD, 'Share my stats card…'),
            (STREAM, 'Streamer mode (OBS window)', {'checked': bool(f.get('stream'))}),
            None,
            (RESTART, 'Restart Taskbar Fighters'),
            (QUIT, 'Quit Taskbar Fighters')]


def tooltip(assign, paused=False):
    """'Taskbar Fighters — Claude vs Codex' from an assign.json dict: display names only (short labels of the program ids)."""
    from minis_core import director, sources
    names = []
    for s in ('a', 'b'):
        a = director.slot_assignment(assign, s) if isinstance(assign, dict) else None
        if a:
            names.append(sources.short_label(a.get('source'), a.get('program')))
    tip = PRODUCT + (' — ' + ' vs '.join(names) if names else '') + (' (paused)' if paused else '')
    return tip[:TIP_MAX]


class Tray:
    """on_left() opens the select screen; on_choice(id, flags) runs a menu choice; flags() -> the menu's tick state;
    tip() -> the tooltip text (polled by step())."""

    def __init__(self, api, icon_path, tip, flags, on_choice, on_left, log=None):
        self.api, self.icon_path = api, icon_path
        self.tip_fn, self.flags_fn, self.on_choice, self.on_left = tip, flags, on_choice, on_left
        self.log = log or logging.getLogger('minis.null')
        self.hwnd = None
        self.hicon = None
        self.added = False
        self.tip = None
        self.taskbar_created = 0
        self.adds = 0                                 # how many times the icon was added (tests, the log)

    def create(self):
        self.taskbar_created = self.api.register_message('TaskbarCreated')
        self.hwnd = self.api.create_window(self.handle)
        return self.add()

    def _load_icon(self):
        if self.hicon:
            self.api.destroy_icon(self.hicon)
        self.hicon = self.api.load_icon(self.icon_path, self.api.small_icon_size(self.hwnd))

    def add(self):
        """NIM_ADD with the icon at the current small-icon size (it changes with DPI, so it is reloaded every add)."""
        self._load_icon()
        try:
            self.tip = self.tip_fn()
        except Exception:
            self.tip = PRODUCT
        self.added = bool(self.api.notify('add', self.hwnd, TRAY_UID, WM_TRAY, self.hicon, self.tip))
        if not self.added:                            # it is still there (TaskbarCreated without a real Explorer restart)
            self.added = bool(self.api.notify('modify', self.hwnd, TRAY_UID, WM_TRAY, self.hicon, self.tip))
        self.adds += 1
        return self.added

    def handle(self, msg, wparam, lparam):
        """The tray window's messages.  -> True when handled."""
        if self.taskbar_created and msg == self.taskbar_created:
            self.log.info('tray: taskbar restarted, icon added again')
            self.added = False
            self.add()
            return True
        if msg != WM_TRAY:
            return False
        ev = lparam & 0xFFFF
        if ev == WM_LBUTTONUP:
            self.on_left()
        elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
            self.open_menu()
        return True

    def open_menu(self):
        f = self.flags_fn()
        choice = self.api.menu(self.hwnd, tray_menu(f))
        if choice:
            self.on_choice(choice, f)
        return choice

    def step(self):
        """Refresh the tooltip when it changed (cheap: NIM_MODIFY only on a change); retry a failed add."""
        if self.hwnd is None:
            return
        if not self.added:
            self.add()
            return
        try:
            tip = self.tip_fn()
        except Exception:
            return
        if tip != self.tip:
            self.tip = tip
            self.api.notify('modify', self.hwnd, TRAY_UID, WM_TRAY, self.hicon, tip)

    def pump(self):
        return self.api.pump()

    def remove(self):
        """NIM_DELETE + free the icon and window.  Safe to call twice (finally + atexit)."""
        if self.hwnd is None:
            return
        try:
            if self.added:
                self.api.notify('delete', self.hwnd, TRAY_UID, WM_TRAY, None, None)
            if self.hicon:
                self.api.destroy_icon(self.hicon)
            self.api.destroy_window(self.hwnd)
        finally:
            self.added, self.hicon, self.hwnd = False, None, None


# ---------------------------------------------------------------- the real Windows side
class Win32Api:
    """Shell_NotifyIconW, a hidden top-level window (not message-only: those never get the TaskbarCreated broadcast),
    LoadImageW from the .ico and a TrackPopupMenu menu.  Used only through shell.make_tray."""

    CLASS = 'MinisTray'

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt
        from minis_win import shell
        self.ct, self.wt, self.shell = ctypes, wt, shell
        u, s32 = shell.user32, shell.shell32

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT), ('uFlags', wt.UINT),
                        ('uCallbackMessage', wt.UINT), ('hIcon', wt.HICON), ('szTip', wt.WCHAR * 128), ('dwState', wt.DWORD),
                        ('dwStateMask', wt.DWORD), ('szInfo', wt.WCHAR * 256), ('uVersion', wt.UINT),
                        ('szInfoTitle', wt.WCHAR * 64), ('dwInfoFlags', wt.DWORD), ('guidItem', ctypes.c_byte * 16),
                        ('hBalloonIcon', wt.HICON)]
        self.NID = NOTIFYICONDATAW
        s32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        s32.Shell_NotifyIconW.restype = wt.BOOL
        u.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
        u.RegisterWindowMessageW.restype = wt.UINT
        u.DestroyIcon.argtypes = [wt.HICON]
        u.GetDpiForWindow.argtypes = [wt.HWND]
        u.GetDpiForWindow.restype = wt.UINT
        u.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wt.UINT]
        self._proc = None
        self._handler = None
        self._registered = False

    def register_message(self, name):
        return int(self.shell.user32.RegisterWindowMessageW(name))

    def create_window(self, handler):
        ct, wt, sh = self.ct, self.wt, self.shell
        self._handler = handler

        def proc(hwnd, msg, wparam, lparam):
            try:
                if self._handler(msg, wparam, lparam):
                    return 0
            except Exception:
                logging.getLogger('director').exception('tray message failed')
            return sh.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if not self._registered:
            self._proc = sh.WNDPROC(proc)
            wc = sh.WNDCLASSEXW()
            wc.cbSize = ct.sizeof(sh.WNDCLASSEXW)
            wc.lpfnWndProc = self._proc
            wc.hInstance = sh.kernel32.GetModuleHandleW(None)
            wc.lpszClassName = self.CLASS
            wc.hIcon, wc.hIconSm = sh.class_icons()
            sh.user32.RegisterClassExW(ct.byref(wc))
            self._registered = True
        hwnd = sh.user32.CreateWindowExW(sh.WS_EX_TOOLWINDOW, self.CLASS, 'minis-tray', sh.WS_POPUP, 0, 0, 0, 0, None, None,
                                         sh.kernel32.GetModuleHandleW(None), None)          # never shown
        if not hwnd:
            raise OSError('tray window: CreateWindowExW failed: %d' % ct.get_last_error())
        return hwnd

    def small_icon_size(self, hwnd):
        u = self.shell.user32
        try:
            dpi = u.GetDpiForWindow(hwnd) or 96
            return int(u.GetSystemMetricsForDpi(49, dpi)) or 16              # SM_CXSMICON at the window's DPI
        except Exception:
            return int(u.GetSystemMetrics(49)) or 16

    def load_icon(self, path, size):
        return self.shell.load_icon(path, size)

    def destroy_icon(self, hicon):
        if hicon:
            self.shell.user32.DestroyIcon(hicon)

    def notify(self, action, hwnd, uid, cbmsg, hicon, tip):
        NIM = {'add': 0, 'modify': 1, 'delete': 2}[action]
        nid = self.NID()
        nid.cbSize = self.ct.sizeof(self.NID)
        nid.hWnd, nid.uID = hwnd, uid
        if action != 'delete':
            nid.uFlags = 0x1 | 0x2 | 0x4 | 0x80                            # NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
            nid.uCallbackMessage = cbmsg
            nid.hIcon = hicon
            nid.szTip = (tip or PRODUCT)[:TIP_MAX]
        return bool(self.shell.shell32.Shell_NotifyIconW(NIM, self.ct.byref(nid)))

    def menu(self, hwnd, items):
        """The popup at the cursor.  SetForegroundWindow first (or the menu never closes on an outside click), WM_NULL
        after (KB Q135788)."""
        ct, wt, sh = self.ct, self.wt, self.shell
        pt = wt.POINT()
        sh.user32.GetCursorPos(ct.byref(pt))
        hm = sh.Overlay.build_menu(items)
        sh.user32.SetForegroundWindow(hwnd)
        try:
            # TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN (the tray sits at the bottom)
            return int(sh.user32.TrackPopupMenu(hm, 0x0100 | 0x0080 | 0x0002 | 0x0020, pt.x, pt.y, 0, hwnd, None))
        finally:
            sh.user32.PostMessageW(hwnd, sh.WM_NULL, 0, 0)
            sh.user32.DestroyMenu(hm)

    def pump(self):
        ct, wt, u = self.ct, self.wt, self.shell.user32
        msg = wt.MSG()
        while u.PeekMessageW(ct.byref(msg), None, 0, 0, 1):
            if msg.message == self.shell.WM_QUIT:
                return False
            u.TranslateMessage(ct.byref(msg))
            u.DispatchMessageW(ct.byref(msg))
        return True

    def destroy_window(self, hwnd):
        if hwnd:
            self.shell.user32.DestroyWindow(hwnd)
