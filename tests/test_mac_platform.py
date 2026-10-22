"""macOS backend, tested on any OS with fakes: backend selection, Dock geometry, click-through, keys, the Quartz window list
(bounds only), the data dir, the LaunchAgent plist and the per-OS sources table.  No AppKit import here; the real-AppKit
checks at the bottom run only on a Mac."""
import os, plistlib, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, ROOT, Isolated  # noqa: E402
import minis_platform as plat  # noqa: E402
from minis_core import config as cfgmod, sources as S  # noqa: E402
from minis_mac import geometry as G, launchd  # noqa: E402
from PIL import Image  # noqa: E402


class Selection(unittest.TestCase):
    def test_platform_names(self):
        self.assertEqual(plat.current('win32'), 'win')
        self.assertEqual(plat.current('darwin'), 'mac')
        self.assertEqual(plat.current('linux'), 'other')
        self.assertEqual(plat.package('win32'), 'minis_win')
        self.assertEqual(plat.package('darwin'), 'minis_mac')

    def test_unsupported_os_is_a_clear_error(self):
        with self.assertRaises(plat.UnsupportedPlatform) as cm:
            plat.package('linux')
        self.assertIn('Windows', str(cm.exception))
        with self.assertRaises(ValueError):
            plat.module('nope', 'win32')

    def test_mac_pure_modules_import_without_appkit(self):
        import importlib
        for name in ('minis_mac', 'minis_mac.geometry', 'minis_mac.procs', 'minis_mac.launchd', 'minis_platform.menus'):
            importlib.import_module(name)
        self.assertEqual(plat.module('procs', 'darwin').__name__, 'minis_mac.procs')
        self.assertNotIn('AppKit', sys.modules if sys.platform != 'darwin' else {})

    @unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
    def test_windows_gets_the_unchanged_win_modules(self):
        import minis_win.procs
        self.assertIs(plat.procs(), minis_win.procs)
        self.assertIs(plat.module('tray'), sys.modules['minis_win.tray'])

    @unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
    def test_neutral_menu_entries_match_the_windows_ones(self):
        from minis_win import shell
        from minis_platform.menus import menu_entries
        spec = [(1, 'A'), None, (2, 'B', {'checked': True}), ('Sub', [(3, 'C', {'radio': True, 'checked': True}), '-']),
                (4, 'D', {'disabled': True})]
        self.assertEqual(menu_entries(spec), shell.menu_entries(spec))


class DockGeometry(unittest.TestCase):
    # a 1512x982 MacBook screen, menu bar 33 pt (visible frame top), Dock 70 pt
    F = (0.0, 0.0, 1512.0, 982.0)

    def test_bottom_dock_strip_sits_on_the_dock(self):
        d = G.dock_strip(self.F, (0.0, 70.0, 1512.0, 879.0))
        self.assertEqual(d['dock'], 'bottom')
        self.assertEqual(d['rect'], (0, 982 - 70 - 48, 1512, 982 - 70))
        self.assertEqual(d['edge'], 3)
        self.assertEqual(d['dock_top'], 912)

    def test_left_and_right_dock_fall_back_to_the_visible_bottom(self):
        left = G.dock_strip(self.F, (80.0, 0.0, 1432.0, 949.0))
        self.assertEqual(left['dock'], 'left')
        self.assertEqual(left['rect'], (80, 982 - 48, 1512, 982))
        right = G.dock_strip(self.F, (0.0, 0.0, 1432.0, 949.0))
        self.assertEqual(right['dock'], 'right')
        self.assertEqual(right['rect'], (0, 934, 1432, 982))

    def test_autohidden_dock_sliver_counts_as_hidden(self):
        d = G.dock_strip(self.F, (0.0, 4.0, 1512.0, 945.0))
        self.assertEqual(d['dock'], 'hidden')
        self.assertEqual(d['rect'][3], 978)                     # bottom of the visible frame, above the 4 pt sliver
        self.assertEqual(d['edge'], 3)                          # always usable: the fighters never hide on a Mac

    def test_cocoa_and_app_coordinates_round_trip(self):
        self.assertEqual(G.to_app_rect((100, 70, 64, 64), 982), (100, 848, 164, 912))
        self.assertEqual(G.to_cocoa_origin(100, 848, 64, 982), (100.0, 70.0))
        self.assertEqual(G.point_to_app(10.4, 900.0, 982), (10, 82))

    def test_monitors_retina_and_a_second_screen_above(self):
        mons = G.monitors_from_frames([((0, 0, 1512, 982), (0, 70, 1512, 879), 2.0),
                                       ((-200, 982, 2560, 1440), (-200, 982, 2560, 1415), 1.0)])
        self.assertEqual(mons[0], dict(index=1, rect=(0, 0, 1512, 982), work=(0, 33, 1512, 912), primary=True, scale=2.0))
        self.assertEqual(mons[1]['rect'], (-200, -1440, 2360, 0))           # above the primary: negative y, like Windows
        self.assertFalse(mons[1]['primary'])
        self.assertEqual(G.monitors_from_frames([]), [])


class ClickThrough(unittest.TestCase):
    def setUp(self):
        self.alpha = Image.new('L', (10, 10), 0)
        self.alpha.putpixel((5, 5), 255)

    def test_opaque_pixels_take_the_mouse_transparent_ones_do_not(self):
        rect = (100, 200, 120, 220)                              # 10x10 logical at scale 2
        self.assertTrue(G.window_solid_at((110, 210), rect, 2, self.alpha))
        self.assertFalse(G.window_solid_at((101, 201), rect, 2, self.alpha))
        self.assertFalse(G.window_solid_at((500, 500), rect, 2, self.alpha))
        self.assertFalse(G.window_solid_at(None, rect, 2, self.alpha))

    def test_hittest_wins_over_pixels(self):
        rect = (0, 0, 100, 100)
        self.assertTrue(G.window_solid_at((1, 1), rect, 1, None, on_hittest=lambda x, y: x < 10))
        self.assertFalse(G.window_solid_at((50, 50), rect, 1, self.alpha, on_hittest=lambda x, y: False))
        self.assertFalse(G.window_solid_at((1, 1), rect, 1, None, on_hittest=lambda x, y: 1 / 0))

    def test_mac_keys_map_to_the_select_screens_vk_codes(self):
        from minis_core.select import VK
        self.assertEqual(G.vk_from_mac(123), VK['left'])
        self.assertEqual(G.vk_from_mac(124), VK['right'])
        self.assertEqual(G.vk_from_mac(126), VK['up'])
        self.assertEqual(G.vk_from_mac(125), VK['down'])
        self.assertEqual(G.vk_from_mac(36), VK['enter'])
        self.assertEqual(G.vk_from_mac(53), VK['esc'])
        self.assertEqual(G.vk_from_mac(51), VK['back'])
        self.assertIsNone(G.vk_from_mac(0))


class NoNames(dict):
    """A CGWindowList entry that fails the test if anyone reads a title or an owner name."""

    def __getitem__(self, k):
        if k in ('kCGWindowName', 'kCGWindowOwnerName'):
            raise AssertionError(f'read {k}')
        return super().__getitem__(k)

    def get(self, k, d=None):
        if k in ('kCGWindowName', 'kCGWindowOwnerName'):
            raise AssertionError(f'read {k}')
        return super().get(k, d)


def cg(num, pid, x, y, w, h, layer=0, alpha=1.0):
    return NoNames(kCGWindowNumber=num, kCGWindowOwnerPID=pid, kCGWindowLayer=layer, kCGWindowAlpha=alpha,
                   kCGWindowBounds={'X': x, 'Y': y, 'Width': w, 'Height': h},
                   kCGWindowName='SECRET TITLE', kCGWindowOwnerName='SecretApp')


class QuartzWindowList(unittest.TestCase):
    def test_platforms_are_bounds_of_other_apps_normal_windows(self):
        infos = [cg(1, 50, 10, 40, 800, 600), cg(2, 99, 0, 0, 100, 100),          # 2: our own process
                 cg(3, 50, 0, 0, 1512, 25, layer=25), cg(4, 51, 5, 5, 0, 10),      # 3: menu-bar layer, 4: empty
                 cg(5, 52, 1, 2, 3, 4, alpha=0.0), cg(6, 53, 100, 100, 400, 300)]   # 5: invisible
        self.assertEqual(G.platforms_from_cg(infos, own_pid=99), [(1, 10, 40, 810, 640), (6, 100, 100, 500, 400)])
        self.assertEqual(G.platforms_from_cg(infos, own_pid=99, exclude=(6,)), [(1, 10, 40, 810, 640)])
        self.assertEqual(set(G.CG_KEYS) & {'kCGWindowName', 'kCGWindowOwnerName'}, set())

    def test_fullscreen_needs_a_window_over_the_whole_screen(self):
        zoomed = [cg(1, 50, 0, 25, 1512, 957)]                                      # menu bar still showing
        full = [cg(1, 50, 0, 0, 1512, 982)]
        self.assertFalse(G.fullscreen_from_cg(zoomed, 99, (0, 0, 1512, 982)))
        self.assertTrue(G.fullscreen_from_cg(full, 99, (0, 0, 1512, 982)))
        self.assertFalse(G.fullscreen_from_cg([cg(1, 99, 0, 0, 1512, 982)], 99, (0, 0, 1512, 982)))

    def test_malformed_entries_are_skipped(self):
        self.assertEqual(G.platforms_from_cg([NoNames(kCGWindowLayer=0), {'kCGWindowLayer': 'x'}], 1), [])

    def test_menu_bar_icon_shown_hidden_or_unknown(self):
        def item(pid, onscreen):
            d = cg(9, pid, 741, 0, 38, 38, layer=25)
            if onscreen:
                d['kCGWindowIsOnscreen'] = True
            return d
        panels = [cg(1, 7, 746, 965, 190, 44, layer=25), cg(2, 7, 40, 974, 128, 26, layer=25)]   # scoreboard, plate: not it
        self.assertTrue(G.status_item_shown(panels + [item(7, True)], 7))
        self.assertFalse(G.status_item_shown(panels + [item(7, False)], 7))                    # behind the notch / no room
        self.assertIsNone(G.status_item_shown(panels + [item(8, True)], 7))                    # someone else's icon
        self.assertIsNone(G.status_item_shown([{'kCGWindowLayer': 'x'}], 7))


class DataDir(unittest.TestCase):
    def test_per_os_base(self):
        home = Path('/Users/someone')
        self.assertEqual(cfgmod.data_base('darwin', {}, home), home / 'Library' / 'Application Support')
        self.assertEqual(cfgmod.data_base('win32', {'LOCALAPPDATA': r'C:\L'}, home), Path(r'C:\L'))
        self.assertEqual(cfgmod.data_base('win32', {}, home), home / 'AppData' / 'Local')
        self.assertEqual(cfgmod.data_base('darwin', {'MINIS_DATA_BASE': '/tmp/x'}, home), Path('/tmp/x'))

    @unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
    def test_windows_data_dir_is_unchanged(self):
        self.assertEqual(cfgmod.data_base(), Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local'))


class LaunchAgent(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix='minis-home-'))
        self.addCleanup(__import__('shutil').rmtree, self.home, True)
        self.root = Path('/Users/someone/taskbar fighters')

    def test_plist_runs_start_once_at_login(self):
        d = plistlib.loads(launchd.plist_bytes('/usr/bin/python3', self.root))
        self.assertEqual(d['Label'], launchd.LABEL)
        self.assertEqual(d['ProgramArguments'], ['/usr/bin/python3', str(self.root / 'minis.py'), 'start'])
        self.assertTrue(d['RunAtLoad'])
        self.assertFalse(d['KeepAlive'])
        self.assertTrue(d['AbandonProcessGroup'])                 # `start` exits; its children must survive it
        self.assertEqual(d['WorkingDirectory'], str(self.root))
        self.assertTrue(launchd.is_ours(launchd.plist_bytes('/x/python', self.root), self.root))
        self.assertFalse(launchd.is_ours(launchd.plist_bytes('/x/python', Path('/elsewhere')), self.root))
        self.assertFalse(launchd.is_ours(b'not a plist', self.root))

    def test_install_and_uninstall_only_touch_our_file(self):
        p = launchd.plist_path(self.home)
        self.assertEqual(p, self.home / 'Library' / 'LaunchAgents' / f'{launchd.LABEL}.plist')
        ok, msg = launchd.install('/usr/bin/python3', self.root, self.home)
        self.assertTrue(ok and p.exists(), msg)
        self.assertTrue(launchd.uninstall(self.root, self.home)[0])
        self.assertFalse(p.exists())
        p.write_bytes(plistlib.dumps({'Label': launchd.LABEL, 'ProgramArguments': ['/bin/sh', '-c', 'other']}))
        self.assertFalse(launchd.install('/usr/bin/python3', self.root, self.home)[0])
        self.assertFalse(launchd.uninstall(self.root, self.home)[0])
        self.assertTrue(p.exists())                                # someone else's file: left alone


class FakeMacInfo:
    """ps-shaped process facts: (pid, ppid, name, path, argv, cpu)."""

    def __init__(self, procs):
        self.p = {r[0]: r for r in procs}

    def list(self):
        return [(pid, r[1], r[2]) for pid, r in self.p.items()]

    def path(self, pid):
        return self.p[pid][3] if pid in self.p else None

    def times(self, pid):
        return ('start', self.p[pid][5]) if pid in self.p else None

    def argv(self, pid):
        return self.p[pid][4] if pid in self.p else None


class MacSourcesTable(unittest.TestCase):
    def test_windows_table_is_the_original_object(self):
        self.assertIs(S.rules_for('win32'), S.RULES)

    def test_mac_table_has_mac_names_and_no_windows_exes(self):
        t = S.rules_for('darwin')
        exes = {e for r in t for e in r.get('exe', ())}
        self.assertFalse(any(e.endswith('.exe') for e in exes))
        self.assertFalse(any('path_has' in r for r in t))
        for want in ('cursor', 'ollama', 'lm studio', 'codex', 'claude', 'gemini'):
            self.assertIn(want, exes)
        self.assertEqual({r['source'] for r in t}, {r['source'] for r in S.RULES})        # every program has a mac rule

    def test_bundle_main_executable_only(self):
        self.assertTrue(S.bundle_hit('/Applications/Cursor.app/Contents/MacOS/Cursor', ('cursor.app',)))
        self.assertFalse(S.bundle_hit('/Applications/Cursor.app/Contents/Frameworks/Cursor Helper (Renderer).app/Contents/MacOS/'
                                      'Cursor Helper (Renderer)', ('cursor.app',)))
        self.assertTrue(S.bundle_hit('/Applications/LM Studio.app/Contents/MacOS/LM Studio', ('lm studio.app',)))
        self.assertFalse(S.bundle_hit(None, ('cursor.app',)))

    def test_interpreters(self):
        for n in ('node', 'python3', 'python3.12', 'Python', 'bun'):
            self.assertTrue(S.is_mac_interpreter(n), n)
        for n in ('python3.x', 'nodejs-helper', 'cursor'):
            self.assertFalse(S.is_mac_interpreter(n), n)

    def test_scanner_on_mac_detects_apps_clis_and_claims(self):
        info = FakeMacInfo([
            (10, 1, 'cursor', '/Applications/Cursor.app/Contents/MacOS/Cursor', None, 1.0),
            (11, 10, 'cursor helper (renderer)', '/Applications/Cursor.app/Contents/Frameworks/Cursor Helper (Renderer).app/'
             'Contents/MacOS/Cursor Helper (Renderer)', None, 5.0),
            (20, 1, 'node', '/opt/homebrew/bin/node', ['node', '/opt/homebrew/bin/gemini'], 0.5),
            (30, 1, 'node', '/opt/homebrew/bin/node', ['node', '/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js'], 0.1),
            (40, 1, 'python3.12', '/opt/homebrew/bin/python3.12', ['/opt/homebrew/bin/python3.12', '/opt/homebrew/bin/aider'], 0.2),
            (50, 1, 'lm studio', '/Applications/LM Studio.app/Contents/MacOS/LM Studio', None, 0.0),
            (60, 1, 'windsurf-main', '/Applications/Windsurf.app/Contents/MacOS/Electron', None, 0.0),   # by bundle only
            (70, 1, 'chatgpt', '/Applications/ChatGPT.app/Contents/MacOS/ChatGPT', None, 0.0),            # growth: ChatGPT desktop
        ])
        sc = S.ProcessScanner(dict(CFG), info, platform='darwin')
        out = sc.scan(100.0)
        self.assertEqual(set(out), {'cursor', 'gemini', 'aider', 'lmstudio', 'windsurf', 'chatgpt'})
        self.assertEqual(sc.claimed, {'claude': 1})
        self.assertEqual(sc.matched['cursor'], ['cursor'])               # the helper is in the tree, not a root

    @unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
    def test_windows_scanner_is_configured_exactly_as_before(self):
        sc = S.ProcessScanner(dict(CFG), FakeMacInfo([]))
        self.assertIs(sc.rules, S.RULES)
        self.assertFalse(sc._bundles)
        self.assertTrue(sc._is_interp('node.exe'))
        self.assertFalse(sc._is_interp('node'))


@unittest.skipUnless(sys.platform == 'darwin', 'needs a real Mac with PyObjC')
class RealAppKit(unittest.TestCase):
    """Run on a Mac: `python -m unittest tests.test_mac_platform` (opens one tiny transparent window for a second)."""

    def test_backend_loads_and_reports_a_dock_strip(self):
        sh = plat.shell()
        l, t, r, b, edge = sh.taskbar_rect()
        self.assertEqual(edge, 3)
        self.assertGreater(r, l)
        self.assertGreater(b, t)
        self.assertTrue(sh.monitors())

    def test_overlay_probe(self):
        ok, detail = plat.shell().probe_overlay(0.5)
        self.assertTrue(ok, detail)

    def test_a_2x_hud_image_shows_at_logical_size_and_plates_fade_under_the_mouse(self):
        from minis_core import render
        from minis_core.atlas import Atlas
        from minis_core.telemetry import Snapshot
        sh = plat.shell()
        im = render.plate(Atlas('claude'), Snapshot('claude', 'working', 40.0), 0.0, k=2)
        ov = sh.Overlay('minis-test-plate', 300, 300, cfgmod.PLATE_W, cfgmod.PLATE_H, on_hittest=lambda x, y: False)
        try:
            ov.fade_on_hover = True
            ov.present(im)
            self.assertEqual((ov.w, ov.h), (cfgmod.PLATE_W, cfgmod.PLATE_H))                 # points, not image pixels
            self.assertEqual(ov._alpha.size, (cfgmod.PLATE_W, cfgmod.PLATE_H))
            ov.update_ignore((310, 310))                                                     # over the plate
            self.assertTrue(ov.panel.ignoresMouseEvents())
            self.assertLess(ov.panel.alphaValue(), 0.5)
            ov.update_ignore((10, 10))                                                       # elsewhere
            self.assertEqual(ov.panel.alphaValue(), 1.0)
        finally:
            ov.close()


if __name__ == '__main__':
    unittest.main()


class MenuBarPlates(unittest.TestCase):
    """`plates menubar`: geometry (pure), the control.json setting and the fighter-menu submenu (macOS only)."""

    def test_pair_sits_left_of_the_notch_or_centred(self):
        frame, visible = (0, 0, 1710, 1107), (0, 63, 1710, 1005)                    # 39 pt menu bar, Dock below
        a, b = (G.menubar_plate_origin(s, frame, visible, 763, 128, 26, 4) for s in 'ab')
        self.assertEqual((a, b), ((495, 6), (627, 6)))
        self.assertLessEqual(b[0] + 128, 763 - 8)                                     # never under the notch
        a, b = (G.menubar_plate_origin(s, (0, 0, 1440, 900), (0, 0, 1440, 876), None, 128, 26, 4) for s in 'ab')
        self.assertEqual(a[0] + 260 // 2, 720)                                        # no notch: centred
        self.assertEqual(a[1], 0)                                                     # 24 pt bar: top-aligned
        self.assertEqual(G.menubar_plate_origin('a', (0, 0, 800, 600), (0, 0, 800, 600), 100, 128, 26, 4)[0], 8)

    def test_setting_and_menu(self):
        from minis_core import control, lineup as L
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'control.json'
            self.assertEqual(control.hud_position(p), 'dock')
            control.set_hud_position('menubar', p)
            self.assertEqual(control.hud_position(p), 'menubar')
            control.set_hud_position('nonsense', p)
            self.assertEqual(control.hud_position(p), 'dock')
        flags = dict(paused=False, plates=True, rival=True, flash=True, arena=False, winners='decided', size=128)
        win, _ = L.fighter_menu('a', {}, control.lineup(Path('/nonexistent/control.json')), flags, L.characters())
        mac, _ = L.fighter_menu('a', {}, control.lineup(Path('/nonexistent/control.json')), dict(flags, hud_pos='menubar'), L.characters())
        self.assertNotIn('Plates position', L.labels_of(win))                         # Windows menu unchanged
        sub = dict((it[0], it[1]) for it in mac if it and isinstance(it[1], list))['Plates position']
        self.assertEqual([(i, l, o['checked']) for i, l, o in sub], [(L.HUD_DOCK, 'Above the Dock', False), (L.HUD_MENUBAR, 'In the menu bar', True)])
        labels = L.labels_of(mac)
        self.assertEqual(labels.index('Plates position'), labels.index('HUD plates') + 1)
