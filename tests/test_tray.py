"""Tray icon, app icon and Start-menu shortcut.  Hermetic: a fake api stands in for Windows (no window, no icon, no
PowerShell), data_dir() is a temp dir, and the shortcut writer / reader are mocks."""
import io, os, struct, sys, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, ROOT, Isolated  # noqa: E402
import minis  # noqa: E402
from minis_core import config as cfgmod, control  # noqa: E402
from minis_win import tray as T  # noqa: E402

ICO = ROOT / 'assets' / 'icon' / 'minis.ico'
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


class FakeApi:
    def __init__(self, choice=0):
        self.calls, self.choice, self.menus = [], choice, []
        self.handler = None
        self.icons = 0

    def register_message(self, name):
        self.calls.append(('register', name))
        return 0xC0DE

    def create_window(self, handler):
        self.handler = handler
        return 0x1234

    def small_icon_size(self, hwnd):
        return 24

    def load_icon(self, path, size):
        self.icons += 1
        self.calls.append(('load', Path(path).name, size))
        return 100 + self.icons

    def destroy_icon(self, h):
        self.calls.append(('destroy_icon', h))

    def notify(self, action, hwnd, uid, cbmsg, hicon, tip):
        self.calls.append(('notify', action, hicon, tip))
        return True

    def menu(self, hwnd, items):
        self.menus.append(items)
        return self.choice

    def pump(self):
        return True

    def destroy_window(self, hwnd):
        self.calls.append(('destroy_window', hwnd))

    def notifies(self, action=None):
        return [c for c in self.calls if c[0] == 'notify' and (action is None or c[1] == action)]


def make_tray(api, tip='Taskbar Fighters', flags=None, chosen=None, left=None):
    chosen = chosen if chosen is not None else []
    return T.Tray(api, str(ICO), lambda: tip if not callable(tip) else tip(), lambda: dict(flags or {}),
                  lambda c, f: chosen.append((c, f)), left or (lambda: chosen.append(('left',))))


# ---------------------------------------------------------------------------------------------- the .ico
class IconFile(unittest.TestCase):
    def entries(self, data):
        _, kind, n = struct.unpack_from('<HHH', data, 0)
        self.assertEqual(kind, 1)
        out = []
        for i in range(n):
            w, h, _, _, planes, bpp, size, off = struct.unpack_from('<BBBBHHII', data, 6 + 16 * i)
            out.append(((w or 256), (h or 256), bpp, data[off:off + size]))
        return out

    def test_the_ico_holds_every_size_at_32_bit(self):
        got = self.entries(ICO.read_bytes())
        self.assertEqual(sorted(w for w, h, _, _ in got), sorted(SIZES))
        for w, h, bpp, blob in got:
            self.assertEqual((w, h, bpp), (w, w, 32))
            if w == 256:
                self.assertTrue(blob.startswith(b'\x89PNG'))
            else:
                self.assertEqual(struct.unpack_from('<Iii', blob, 0), (40, w, 2 * w))     # BMP entry, height x2 (mask)

    def test_pillow_reads_every_size_back(self):
        from PIL import Image
        with Image.open(ICO) as im:
            self.assertEqual({s[0] for s in im.info['sizes']}, set(SIZES))

    def test_the_build_is_deterministic_and_matches_the_committed_files(self):
        sys.path.insert(0, str(ROOT / 'art'))
        import build_icon
        imgs = build_icon.icon_images()
        self.assertEqual(build_icon.ico_bytes(imgs), ICO.read_bytes())
        self.assertEqual(build_icon._png_bytes(imgs[256]), (ROOT / 'assets' / 'icon' / 'minis-256.png').read_bytes())

    def test_small_sizes_are_drawn_not_downscaled(self):
        sys.path.insert(0, str(ROOT / 'art'))
        import build_icon
        from PIL import Image
        imgs = build_icon.icon_images()
        for s in (16, 20, 24):
            shrunk = imgs[256].resize((s, s), Image.LANCZOS)
            self.assertNotEqual(imgs[s].tobytes(), shrunk.tobytes())
            self.assertEqual(imgs[s].getpixel((0, 0))[3], 0)                 # transparent corners
            colours = {imgs[s].getpixel((x, y)) for x in range(s) for y in range(s)} - {build_icon.CLEAR}
            self.assertIn(build_icon.DARK, colours)                           # the 1 px outline
            self.assertIn(build_icon.CREAM, colours)


# ---------------------------------------------------------------------------------------------- the tray logic
class TrayLogic(unittest.TestCase):
    def test_create_adds_the_icon_with_the_tooltip(self):
        api = FakeApi()
        t = make_tray(api, tip='Taskbar Fighters \u2014 Claude vs Codex')
        self.assertTrue(t.create())
        self.assertIn(('register', 'TaskbarCreated'), api.calls)
        self.assertEqual(api.notifies('add'), [('notify', 'add', 101, 'Taskbar Fighters \u2014 Claude vs Codex')])
        self.assertIn(('load', 'minis.ico', 24), api.calls)                   # the DPI's small-icon size

    def test_taskbar_created_adds_the_icon_again(self):
        api = FakeApi()
        t = make_tray(api)
        t.create()
        self.assertTrue(api.handler(0xC0DE, 0, 0))                           # Explorer restarted
        self.assertEqual(len(api.notifies('add')), 2)
        self.assertEqual(t.adds, 2)
        self.assertIn(('destroy_icon', 101), api.calls)                       # the old HICON is freed, a fresh one loaded
        self.assertEqual(api.notifies('add')[-1][2], 102)

    def test_a_refused_add_falls_back_to_modify(self):
        api = FakeApi()
        real = api.notify
        api.notify = lambda action, *a: False if action == 'add' else real(action, *a)
        t = make_tray(api)
        self.assertTrue(t.create())                                            # the icon already existed: it is updated
        self.assertEqual(len(api.notifies('modify')), 1)

    def test_left_click_opens_select_right_click_the_menu(self):
        api = FakeApi(choice=T.PAUSE)
        got = []
        t = make_tray(api, flags=dict(paused=True), chosen=got)
        t.create()
        api.handler(T.WM_TRAY, T.TRAY_UID, T.WM_LBUTTONUP)
        self.assertEqual(got, [('left',)])
        api.handler(T.WM_TRAY, T.TRAY_UID, T.WM_RBUTTONUP)
        self.assertEqual(got[-1], (T.PAUSE, dict(paused=True)))
        self.assertEqual(len(api.menus), 1)
        self.assertFalse(api.handler(0x0200, 0, 0))                          # not ours: DefWindowProc

    def test_step_modifies_only_when_the_tooltip_changed(self):
        api = FakeApi()
        tips = ['Taskbar Fighters \u2014 Claude']
        t = make_tray(api, tip=lambda: tips[0])
        t.create()
        t.step()
        self.assertEqual(api.notifies('modify'), [])
        tips[0] = 'Taskbar Fighters \u2014 Claude vs Grok'
        t.step()
        self.assertEqual(api.notifies('modify'), [('notify', 'modify', 101, 'Taskbar Fighters \u2014 Claude vs Grok')])

    def test_remove_deletes_once(self):
        api = FakeApi()
        t = make_tray(api)
        t.create()
        t.remove()
        t.remove()                                                             # finally + atexit
        self.assertEqual(len(api.notifies('delete')), 1)
        self.assertEqual([c for c in api.calls if c[0] == 'destroy_window'], [('destroy_window', 0x1234)])

    def test_menu_spec(self):
        from minis_core import lineup as L
        items = T.tray_menu(dict(paused=True, flash=False, plates=True, rival=False, arena=True))
        labels = L.labels_of(items)
        self.assertEqual(labels, ['Select fighters\u2026', 'Pause animations', 'Flash effects', 'Desktop weapons', 'Sound effects', 'Plates', 'Rival mode',
                                  'Exit arena', 'Bout now', 'Restart Taskbar Fighters', 'Quit Taskbar Fighters'])
        opts = {it[0]: (it[2] if len(it) > 2 else {}) for it in items if it}
        self.assertTrue(opts[T.PAUSE]['checked'])
        self.assertFalse(opts[T.FLASH]['checked'])
        self.assertTrue(opts[T.PLATES]['checked'])
        self.assertFalse(opts[T.RIVAL]['checked'])
        self.assertEqual(L.find_item(T.tray_menu({}), 'Start arena')[0], T.ARENA)
        self.assertTrue(T.tray_menu(dict(select_ok=False, arena_ok=False))[0][2]['disabled'])
        from minis_platform.menus import menu_entries                          # the spec is what the real menu builder takes
        self.assertEqual(sum(1 for e in menu_entries(items) if e[0] == 'sep'), 2)


class Tooltip(unittest.TestCase):
    def test_display_names_only(self):
        a = {'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
             'b': {'source': 'grok', 'character': 'oni', 'program': 'Grok', 'dormant': True}, 'programs': [], 'ts': 1}
        tip = T.tooltip(a)
        self.assertTrue(tip.startswith('Taskbar Fighters \u2014 '))
        self.assertIn(' vs ', tip)
        self.assertEqual(T.tooltip(a, paused=True)[-9:], ' (paused)')
        self.assertEqual(T.tooltip({}), 'Taskbar Fighters')
        self.assertEqual(T.tooltip({'a': None, 'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex'}}), 'Taskbar Fighters \u2014 Codex')

    def test_a_long_or_odd_name_is_capped(self):
        a = {'a': {'source': 'x' * 300, 'character': 'generic', 'program': 'y' * 300}}
        self.assertLessEqual(len(T.tooltip(a)), T.TIP_MAX)


# ---------------------------------------------------------------------------------------------- menu -> control calls
class TrayActions(Isolated):
    FLAGS = dict(paused=False, flash=True, plates=True, rival=True, arena=False)

    def run_choice(self, choice, board=None, flags=None):
        quits, restarts = [], []
        minis.tray_choice(choice, dict(self.FLAGS, **(flags or {})), board, wall=lambda: 1000.0,
                          quit_fn=lambda: quits.append(1) or True, restart_fn=lambda: restarts.append(1) or True)
        return quits, restarts

    def test_toggles_flip_the_control_flags(self):
        self.run_choice(T.PAUSE)
        self.assertTrue(control.paused())
        self.run_choice(T.PAUSE, flags=dict(paused=True))
        self.assertFalse(control.paused())
        self.run_choice(T.FLASH)
        self.assertFalse(control.flashes_on())
        self.assertTrue(control.forge_on())                                    # desktop weapons: on by default
        self.run_choice(T.FORGE)
        self.assertFalse(control.forge_on())
        self.run_choice(T.PLATES)
        self.assertFalse(control.plates_on())
        self.run_choice(T.RIVAL)
        self.assertFalse(control.rival_on())

    def test_select_and_left_click_use_the_picker_request(self):
        self.run_choice(T.SELECT)
        req = control.picker_request(now=1000.0)
        self.assertEqual(req['slots'], ['a', 'b'])

    def test_bout_asks_for_a_match(self):
        self.run_choice(T.BOUT)
        self.assertEqual(control.demo(now=1000.0)['kind'], 'match')

    def test_arena_goes_through_the_scoreboard_button(self):
        board = mock.Mock()
        self.run_choice(T.ARENA, board=board)
        board.act.assert_called_once_with('arena')
        self.run_choice(T.ARENA, board=None)                                  # no host: nothing happens (greyed out)

    def test_restart_and_quit(self):
        self.assertEqual(self.run_choice(T.QUIT), ([1], []))
        self.assertEqual(self.run_choice(T.RESTART), ([], [1]))

    def test_the_real_quit_and_restart_are_refused_under_tests(self):
        with mock.patch.object(minis.subprocess, 'Popen') as po:
            self.assertFalse(minis.quit_all())
            self.assertFalse(minis.restart_all())
            po.assert_not_called()

    def test_flags_read_control(self):
        control.set_paused(True)
        control.set_rival(False)
        f = minis.tray_flags(dict(CFG), board=None)
        self.assertTrue(f['paused'])
        self.assertFalse(f['rival'])
        self.assertFalse(f['select_ok'])

    def test_director_builds_the_tray_through_the_shell_and_removes_it(self):
        made = []

        class Tray:
            def __init__(self, **kw):
                self.kw, self.removed, self.steps = kw, 0, 0
                made.append(self)

            def step(self):
                self.steps += 1

            def pump(self):
                return True

            def remove(self):
                self.removed += 1

        shell = types.SimpleNamespace(make_mutex=lambda name: (1, False), make_tray=lambda **kw: Tray(**kw))
        src = types.SimpleNamespace(poll=lambda now: [])
        cfg = dict(CFG, scoreboard=False)
        with mock.patch.object(minis.time, 'sleep', lambda s: None), mock.patch.object(minis.atexit, 'register') as reg:
            minis.run_director(shell, cfg, detector_sources=src, max_iterations=3)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].removed, 1)
        self.assertGreaterEqual(made[0].steps, 1)
        self.assertIn(mock.call(made[0].remove), reg.call_args_list)
        made[0].kw['on_left']()
        self.assertIsNotNone(control.picker_request())
        self.assertEqual(made[0].kw['tip'](), 'Taskbar Fighters')                        # no assign.json yet

    def test_tray_icon_off(self):
        calls = []
        shell = types.SimpleNamespace(make_mutex=lambda name: (1, False), make_tray=lambda **kw: calls.append(kw))
        src = types.SimpleNamespace(poll=lambda now: [])
        with mock.patch.object(minis.time, 'sleep', lambda s: None):
            minis.run_director(shell, dict(CFG, scoreboard=False, tray_icon=False), detector_sources=src, max_iterations=2)
        self.assertEqual(calls, [])

    def test_config_default(self):
        self.assertIs(cfgmod.DEFAULTS['tray_icon'], True)


# ---------------------------------------------------------------------------------------------- shortcut
class Shortcut(Isolated):
    def args(self, action='create', desktop=False):
        return types.SimpleNamespace(action=action, desktop=desktop)

    def test_spec_targets_pythonw_on_this_minis_py(self):
        sp = minis.shortcut_spec()
        self.assertIn(os.path.basename(sp['target']).lower(), minis.PYTHONS)
        self.assertEqual(sp['arguments'], f'"{ROOT / "minis.py"}" start')
        self.assertEqual(sp['workdir'], str(ROOT))
        self.assertEqual(sp['icon'], f'{ROOT / "assets" / "icon" / "minis.ico"},0')

    def test_create_writes_start_menu_and_desktop(self):
        written = []
        sm, dt = self.data / 'Programs', self.data / 'Desktop'
        with mock.patch('builtins.print') as pr:
            rc = minis.cmd_shortcut(self.args(desktop=True), writer=lambda p, sp: written.append((p, sp)) or True,
                                    reader=lambda p: None, dirs=[sm, dt])
        self.assertEqual(rc, 0)
        self.assertEqual([p for p, _ in written], [sm / 'Taskbar Fighters.lnk', dt / 'Taskbar Fighters.lnk'])
        self.assertEqual(written[0][1], minis.shortcut_spec())
        self.assertTrue(any(minis.PIN_HINT in str(c) for c in pr.call_args_list))

    @unittest.skipUnless(sys.platform == 'win32', 'Start menu: Windows only (macOS uses `autostart`)')
    def test_default_dirs(self):
        with mock.patch.dict(os.environ, {'APPDATA': r'C:\Users\x\AppData\Roaming'}):
            self.assertEqual(minis.start_menu_dir(), Path(r'C:\Users\x\AppData\Roaming\Microsoft\Windows\Start Menu\Programs'))
        got = []
        with mock.patch.object(minis, 'start_menu_dir', lambda: self.data / 'sm'), \
                mock.patch.object(minis, 'desktop_dir', lambda: self.data / 'dt'), mock.patch('builtins.print'):
            minis.cmd_shortcut(self.args(), writer=lambda p, sp: got.append(p) or True, reader=lambda p: None)
        self.assertEqual(got, [self.data / 'sm' / 'Taskbar Fighters.lnk'])                # no --desktop: Start menu only

    def test_create_never_overwrites_a_foreign_lnk(self):
        lnk = self.data / 'Taskbar Fighters.lnk'
        lnk.write_bytes(b'x')
        written = []
        with mock.patch('builtins.print'):
            rc = minis.cmd_shortcut(self.args(), writer=lambda p, sp: written.append(p) or True,
                                    reader=lambda p: (r'C:\Program Files\Other\other.exe', ''), dirs=[self.data])
        self.assertEqual((rc, written), (1, []))

    def test_remove_refuses_a_lnk_that_is_not_ours(self):
        lnk = self.data / 'Minis.lnk'
        lnk.write_bytes(b'x')
        for target, arguments in ((r'C:\evil\cmd.exe', f'"{ROOT / "minis.py"}" start'),
                                  (r'C:\Python\pythonw.exe', r'"C:\elsewhere\minis.py" start'),
                                  (r'C:\Python\pythonw.exe', f'"{ROOT / "minis.py"}" stop')):
            with mock.patch('builtins.print'):
                rc = minis.cmd_shortcut(self.args('remove'), reader=lambda p: (target, arguments), dirs=[self.data])
            self.assertEqual(rc, 1)
            self.assertTrue(lnk.exists())
        with mock.patch('builtins.print'):
            self.assertEqual(minis.cmd_shortcut(self.args('remove'), reader=lambda p: None, dirs=[self.data]), 1)
        self.assertTrue(lnk.exists())                                          # unreadable: left alone too

    def test_remove_deletes_ours_including_an_old_minis_lnk(self):
        new, old = self.data / 'Taskbar Fighters.lnk', self.data / 'Minis.lnk'
        new.write_bytes(b'x')
        old.write_bytes(b'x')
        sp = minis.shortcut_spec()
        with mock.patch('builtins.print'):
            rc = minis.cmd_shortcut(self.args('remove'), reader=lambda p: (sp['target'], sp['arguments']), dirs=[self.data, self.data / 'none'])
        self.assertEqual(rc, 0)
        self.assertFalse(new.exists())
        self.assertFalse(old.exists())

    def test_remove_refuses_an_old_minis_lnk_that_is_not_ours(self):
        old = self.data / 'Minis.lnk'
        old.write_bytes(b'x')
        with mock.patch('builtins.print'):
            rc = minis.cmd_shortcut(self.args('remove'), reader=lambda p: (r'C:\Other\minis.exe', 'start'), dirs=[self.data])
        self.assertEqual(rc, 1)
        self.assertTrue(old.exists())

    def test_the_name_is_the_product_name(self):
        self.assertEqual(minis.SHORTCUT_NAME, 'Taskbar Fighters.lnk')
        self.assertIn('Taskbar Fighters', minis.PIN_HINT)
        self.assertTrue(minis.shortcut_spec()['description'].startswith('Taskbar Fighters'))

    def test_powershell_is_refused_under_tests(self):
        with mock.patch.object(minis.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                minis.write_shortcut(self.data / 'Minis.lnk', minis.shortcut_spec())
            run.assert_not_called()

    def test_parser(self):
        with mock.patch.object(minis, 'cmd_shortcut', return_value=0) as cs:
            minis.main(['shortcut', '--desktop'])
        a = cs.call_args[0][0]
        self.assertEqual((a.action, a.desktop), ('create', True))


if __name__ == '__main__':
    unittest.main()
