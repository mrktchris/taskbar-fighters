"""Real Win32 windows (empty and transparent, so nothing visible is drawn).  Regression guard: a popup window is created HIDDEN,
and an optimisation once removed the only call that showed it, so the fighters ran invisibly."""
import sys, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
class Overlay(unittest.TestCase):
    def setUp(self):
        from minis_win import shell
        self.shell = shell
        self.ov = shell.Overlay('minis-test', 0, 0, 64, 64)

    def tearDown(self):
        self.ov.close()

    def visible(self):
        return bool(self.shell.user32.IsWindowVisible(self.ov.hwnd))

    def test_closing_one_window_does_not_quit_the_others(self):
        """The director hosts the scoreboard AND the fighter-select popup: every WM_DESTROY used to post WM_QUIT, so
        confirming a pick closed the popup and the scoreboard's pump returned False - the director exited silently."""
        while not self.ov.pump():   # an earlier test closing its LAST window leaves a real WM_QUIT queued: drain it
            pass
        popup = self.shell.Overlay('minis-test-popup', 100, 100, 64, 64)
        popup.close()
        self.assertTrue(self.ov.pump(), 'closing another window ended this message loop')

    def test_window_is_visible_right_after_creation(self):
        self.assertTrue(self.visible())

    def test_show_and_hide_really_change_visibility(self):
        self.ov.show(False)
        self.assertFalse(self.visible())
        self.ov.show(True)
        self.assertTrue(self.visible())

    def test_keep_on_top_tick_does_not_change_visibility(self):
        self.ov.reassert_topmost()
        self.assertTrue(self.visible())
        self.ov.show(False)
        self.ov.reassert_topmost()
        self.assertFalse(self.visible())

    def test_present_resizes_and_moves_the_window_with_the_content(self):
        from PIL import Image
        import ctypes
        from ctypes import wintypes as wt
        self.assertTrue(self.ov.present(Image.new('RGBA', (180, 64), (255, 0, 0, 80)), x=100))
        r = wt.RECT()
        self.shell.user32.GetWindowRect(self.ov.hwnd, ctypes.byref(r))
        self.assertEqual((r.left, r.right - r.left, r.bottom - r.top), (100, 180, 64))

    def test_present_writes_premultiplied_bgra(self):
        from PIL import Image
        import ctypes
        self.assertTrue(self.ov.present(Image.new('RGBA', (1, 1), (255, 0, 0, 80))))
        self.assertEqual(tuple(ctypes.string_at(self.ov._bits, 4)), (0, 0, 80, 80))

    def test_present_at_scale_2_doubles_the_window(self):
        from PIL import Image
        import ctypes
        from ctypes import wintypes as wt
        self.ov.set_scale(2)
        self.assertTrue(self.ov.present(Image.new('RGBA', (30, 64), (0, 0, 0, 0)), x=10))
        r = wt.RECT()
        self.shell.user32.GetWindowRect(self.ov.hwnd, ctypes.byref(r))
        self.assertEqual((r.right - r.left, r.bottom - r.top), (60, 128))

    def test_timer_tick_reaches_on_timer(self):
        import time
        hits = []
        self.ov.on_timer = lambda: hits.append(1)
        self.assertTrue(self.ov.start_timer(20))
        end = time.time() + 1.0
        while not hits and time.time() < end:
            self.ov.pump()
            time.sleep(0.01)
        self.ov.stop_timer()
        self.assertTrue(hits, 'WM_TIMER never reached on_timer (the menu heartbeat depends on it)')

    def test_losing_mouse_capture_ends_a_drag(self):
        events = []
        self.ov.on_event = lambda kind, x, y: events.append(kind)
        u = self.shell.user32
        u.SendMessageW.argtypes = [self.shell.wt.HWND, self.shell.wt.UINT, self.shell.wt.WPARAM, self.shell.wt.LPARAM]
        u.SendMessageW(self.ov.hwnd, self.shell.WM_LBUTTONDOWN, 0, (10 << 16) | 10)
        self.assertTrue(self.ov._dragging)
        u.SendMessageW(self.ov.hwnd, self.shell.WM_CAPTURECHANGED, 0, 0)       # e.g. alt-tab steals capture mid-drag
        self.assertFalse(self.ov._dragging)
        self.assertEqual(events, ['down', 'up'])
        u.ReleaseCapture()

    def test_hittest_callback_makes_the_window_click_through_except_where_solid(self):
        import ctypes
        from ctypes import wintypes as wt
        from PIL import Image
        ov = self.shell.Overlay('minis-test-hit', 300, 300, 100, 40, on_hittest=lambda x, y: 10 <= x <= 50 and y >= 20)
        try:
            ov.present(Image.new('RGBA', (100, 40), (0, 0, 0, 0)), x=300)
            u = self.shell.user32
            u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.SendMessageW.restype = ctypes.c_ssize_t
            hit = lambda sx, sy: u.SendMessageW(ov.hwnd, self.shell.WM_NCHITTEST, 0, ((sy & 0xFFFF) << 16) | (sx & 0xFFFF))
            self.assertEqual(hit(320, 330), self.shell.HTCLIENT)                # on the "button"
            self.assertEqual(hit(320, 305), self.shell.HTTRANSPARENT)           # above it: falls through to the taskbar
            self.assertEqual(hit(390, 330), self.shell.HTTRANSPARENT)
            self.assertFalse(ov.activatable)
            self.assertEqual(u.SendMessageW(ov.hwnd, self.shell.WM_MOUSEACTIVATE, 0, 0), self.shell.MA_NOACTIVATE)
        finally:
            ov.close()

    def test_arena_window_is_full_monitor_layered_click_through_except_exit_and_takes_esc(self):
        import ctypes
        from ctypes import wintypes as wt
        from PIL import Image
        from minis_win.arena_window import ArenaWindow, VK_ESCAPE, ARENA_CLASS
        keys, clicks = [], []
        rect = (100, 100, 740, 460)                                                  # a synthetic "monitor" rect on the primary screen
        exit_rect = (640 - 120, 10, 640 - 10, 50)
        w = ArenaWindow(rect, on_hittest=lambda x, y: exit_rect[0] <= x <= exit_rect[2] and exit_rect[1] <= y <= exit_rect[3],
                        on_click=lambda x, y: clicks.append((x, y)), on_key=lambda vk: keys.append(vk))
        try:
            u = self.shell.user32
            self.assertTrue(u.IsWindowVisible(w.hwnd))
            r = wt.RECT()
            u.GetWindowRect(w.hwnd, ctypes.byref(r))
            self.assertEqual((r.left, r.top, r.right, r.bottom), rect)
            self.assertEqual(self.shell.find_own_window(ARENA_CLASS), w.hwnd)
            ex = u.GetWindowLongW(w.hwnd, -20)
            self.assertTrue(ex & self.shell.WS_EX_LAYERED and ex & self.shell.WS_EX_TOPMOST)
            u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.SendMessageW.restype = ctypes.c_ssize_t
            hit = lambda sx, sy: u.SendMessageW(w.hwnd, self.shell.WM_NCHITTEST, 0, ((sy & 0xFFFF) << 16) | (sx & 0xFFFF))
            self.assertEqual(hit(100 + 600, 100 + 30), self.shell.HTCLIENT)         # EXIT button
            self.assertEqual(hit(100 + 300, 100 + 200), self.shell.HTTRANSPARENT)   # the stage: click-through
            u.SendMessageW(w.hwnd, self.shell.WM_KEYDOWN, VK_ESCAPE, 0)
            self.assertEqual(keys, [VK_ESCAPE])
            u.SendMessageW(w.hwnd, self.shell.WM_LBUTTONDOWN, 0, ((30 & 0xFFFF) << 16) | (600 & 0xFFFF))
            u.ReleaseCapture()
            self.assertEqual(clicks, [(600, 30)])
            # incremental drawing: a write lands in the DIB as premultiplied BGRA, flush pushes only the dirty rect
            w.write(Image.new('RGBA', (4, 4), (255, 0, 0, 80)), 10, 10)
            self.assertEqual(w._dirty, [(10, 10, 14, 14)])
            off = (10 * w.w + 10) * 4
            self.assertEqual(tuple(ctypes.string_at(w._bits.value + off, 4)), (0, 0, 80, 80))
            self.assertTrue(w.flush())
            self.assertEqual(w._dirty, [])
            w.offset(5, -3)
            u.GetWindowRect(w.hwnd, ctypes.byref(r))
            self.assertEqual((r.left, r.top), (105, 97))
            w.offset(0, 0)
            cap = self.shell.capture_window(w.hwnd)                                   # PrintWindow of OUR window only
            self.assertEqual(cap.size, (640, 360))
        finally:
            w.close()
        self.assertIsNone(w.hwnd)                                                     # closed (a foreign leftover window may still exist)

    def test_monitors_and_window_rects_are_rectangles_only(self):
        mons = self.shell.monitors()
        self.assertTrue(mons and any(m['primary'] for m in mons))
        for m in mons:
            self.assertEqual(len(m['rect']), 4)
        rects = self.shell.window_rects()
        for hwnd, l, t, r, b in rects:
            self.assertTrue(r > l and b > t)
            self.assertIsInstance(hwnd, int)
        import inspect
        src = inspect.getsource(self.shell)
        self.assertNotIn('GetWindowText', src)                                       # titles are never read

    def test_taskbar_helpers_answer(self):
        l, t, r, b, edge = self.shell.taskbar_rect()
        self.assertIn(edge, (0, 1, 2, 3))
        self.assertIsInstance(self.shell.taskbar_autohide(), bool)
        self.assertTrue(self.shell.kernel32.GetModuleHandleW(None))


@unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
class StrangersPCs(unittest.TestCase):
    """The real Win32 side of the stage: DPI awareness, live re-layout messages, the taskbar's rects."""

    def setUp(self):
        from minis_win import shell
        self.shell = shell

    def test_process_is_per_monitor_dpi_aware(self):
        """Every coordinate must be a physical pixel, or sprites blur and land in the wrong place at 125-200%."""
        self.assertEqual(self.shell.dpi_awareness(), 'per-monitor v2')
        for m in self.shell.monitors():
            self.assertGreaterEqual(m['scale'], 1.0)

    def test_layout_messages_bump_the_epoch(self):
        """WM_DISPLAYCHANGE, WM_DPICHANGED, a work-area WM_SETTINGCHANGE and TaskbarCreated (posted to OUR window only; a real
        broadcast would reach every program) each bump layout_epoch; an unrelated setting change does not."""
        import ctypes
        from ctypes import wintypes as wt
        sh = self.shell
        sh.user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        sh.user32.SendMessageW.restype = ctypes.c_ssize_t
        ov = sh.Overlay('minis-test-layout', 0, 0, 8, 8)
        try:
            while not ov.pump():
                pass
            for msg, wp in ((sh.WM_DISPLAYCHANGE, 32), (sh.WM_DPICHANGED, 0x00900090), (sh.WM_SETTINGCHANGE, sh.SPI_SETWORKAREA),
                            (sh.WM_TASKBARCREATED, 0)):
                before = sh.layout_epoch()
                rc = wt.RECT(0, 0, 8, 8)                                                  # WM_DPICHANGED carries a suggested rect
                sh.user32.SendMessageW(ov.hwnd, msg, wp, ctypes.addressof(rc))
                self.assertEqual(sh.layout_epoch(), before + 1, hex(msg))
            before = sh.layout_epoch()
            sh.user32.SendMessageW(ov.hwnd, sh.WM_SETTINGCHANGE, 0x2A, 0)                # SPI_SETFONTSMOOTHING: not layout
            self.assertEqual(sh.layout_epoch(), before)
            self.assertTrue(sh.user32.IsWindowVisible(ov.hwnd))                         # a DPI message did not hide / resize it
        finally:
            ov.close()

    def test_taskbar_info_is_rects_only_and_stage_lays_it_out(self):
        sh = self.shell
        if not sh.user32.FindWindowW('Shell_TrayWnd', None):
            self.skipTest('no taskbar in this session (a service desktop)')
        from minis_core import config as cfgmod
        info = sh.taskbar_info()
        self.assertIn(info['edge'], (0, 1, 2, 3))
        self.assertGreater(info['dpi'], 0)
        for r in [info['rect'], info['monitor'], info['work']] + list(info['parts'] or ()):
            self.assertEqual(len(r), 4)
            self.assertTrue(all(isinstance(v, int) for v in r))
        st = cfgmod.stage(info, dict(cfgmod.DEFAULTS))
        self.assertIsInstance(st['scale'], int)
        self.assertGreater(st['band'][1], st['band'][0])
        if st['zone']:
            self.assertLess(st['zone'][0], st['zone'][1])
        import inspect
        from minis_win import uia
        src = inspect.getsource(uia)
        for word in ('CurrentName', 'GetWindowText', 'ValuePattern'):                     # only rects are ever read
            self.assertNotIn(word, src)

    def test_uia_probe_has_a_deadline(self):
        from minis_win import uia
        h = self.shell.user32.FindWindowW('Shell_TrayWnd', None)
        got = uia.descendant_rects(h) if h else None
        self.assertTrue(got is None or all(len(r) == 4 for r in got))
        self.assertIsNone(uia.descendant_rects(0))
        end = time.monotonic() + 15.0                   # past the deadline the call returns None with the worker still
        while uia._busy.is_set() and time.monotonic() < end:   # running (a loaded CI runner): it must still finish
            time.sleep(0.05)
        self.assertFalse(uia._busy.is_set())                                             # the worker thread finished


if __name__ == '__main__':
    unittest.main()
