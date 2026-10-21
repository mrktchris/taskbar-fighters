"""Windows taskbar geometry on strangers' PCs (config.stage and the loops that use it), headless and on every OS.

Synthetic RECT sets stand in for what minis_win.shell.taskbar_info reads from a real taskbar (UI Automation bounding rects
of the start button, each app button, the tray; the taskbar rect, edge, auto-hide state, monitor, work area and DPI).  Every
DPI step 100-200%, every taskbar edge, auto-hide, centred vs left-aligned icons, Windows 10 vs 11 sets, a growing icon
cluster, a second monitor, and the live re-layout on a display / DPI change or an Explorer restart."""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
import minis  # noqa: E402
from minis_core import config as cfgmod, director, scoreboard as SB  # noqa: E402
from minis_win import select_window  # noqa: E402  (pure placement: no window is made)
from test_minis import FakeDetector, FakeOverlay  # noqa: E402

DPIS = (1.0, 1.25, 1.5, 1.75, 2.0)


def win11_bar(sw, sh, dpi=1.0, icons=10, centred=True, widgets=False, edge=3):
    """(rect, parts) of a Windows 11 taskbar at `dpi`, laid out like the real UIA tree: the whole bar and the icon list as
    containers, a start button, `icons` app buttons (the first with an icon image inside), tray icons, the clock."""
    band = int(round(48 * dpi))
    t, b = sh - band, sh
    btn = int(round(44 * dpi))
    n = icons + 1                                          # start + apps
    x0 = (sw - n * btn) // 2 if centred else int(round(12 * dpi))
    parts = [(0, t, sw, b)]                                # the whole bar (container)
    for i in range(n):
        parts.append((x0 + i * btn, t, x0 + (i + 1) * btn, b))
    parts.append((x0 + btn + 10, t + 12, x0 + 2 * btn - 10, b - 12))   # an icon image inside the first app button
    parts.append((x0 + btn, t, x0 + n * btn, b))           # the icon list (container)
    tray0 = sw - int(round(310 * dpi))
    for i in range(5):
        w = int(round(32 * dpi))
        parts.append((tray0 + i * w, t, tray0 + (i + 1) * w, b))
    parts.append((sw - int(round(86 * dpi)), t, sw - int(round(16 * dpi)), b))      # the clock
    parts.append((tray0, t, sw, b))                        # the tray (container)
    if widgets:
        parts.append((0, t, int(round(160 * dpi)), b))     # weather / widgets button at the far left
    return (0, t, sw, b), parts, (x0, x0 + n * btn), tray0


def info_for(sw, sh, dpi=1.0, edge=3, autohide=False, revealed=True, **bar):
    rect, parts, cluster, tray0 = win11_bar(sw, sh, dpi, **bar)
    band = rect[3] - rect[1]
    mon = (0, 0, sw, sh)
    if edge == 3:
        work = (0, 0, sw, sh) if autohide else (0, 0, sw, sh - band)
    elif edge == 1:
        rect, work, parts = (0, 0, sw, band), (0, 0 if autohide else band, sw, sh), None
    elif edge == 0:
        w = int(round(62 * dpi))
        rect, work, parts = (0, 0, w, sh), (0 if autohide else w, 0, sw, sh), None
    else:
        w = int(round(62 * dpi))
        rect, work, parts = (sw - w, 0, sw, sh), (0, 0, sw if autohide else sw - w, sh), None
    return dict(rect=rect, edge=edge, autohide=autohide, revealed=revealed, monitor=mon, work=work, dpi=dpi, parts=parts,
                parts_src='uia' if parts else None), cluster, tray0


class StagePure(unittest.TestCase):
    def test_every_dpi_step_gives_an_integer_scale_a_fitting_hud_and_a_zone_clear_of_the_icons(self):
        for sw, sh in ((2560, 1440), (1920, 1080), (3840, 2160)):
            for dpi in DPIS:
                with self.subTest(screen=(sw, sh), dpi=dpi):
                    info, (c0, c1), tray0 = info_for(sw, sh, dpi)
                    st = cfgmod.stage(info, CFG)
                    sc = st['scale']
                    band = st['band'][1] - st['band'][0]
                    self.assertIsInstance(sc, int)
                    self.assertEqual(sc, 2 if dpi >= 2 else 1)             # crisp: 125-175% draw at 1x, 200% at 2x
                    self.assertEqual(st['floor'], sh)                      # feet on the screen's bottom edge
                    self.assertLessEqual(SB.H * sc, band)                  # the scoreboard and the plates fit the band
                    self.assertLessEqual(cfgmod.PLATE_H * sc, band)
                    self.assertTrue(st['usable'])
                    if sw / sc < 1280:                                     # 1920x1080 at 200%: no room (next test)
                        continue
                    self.assertEqual(st['zone_src'], 'auto')
                    z0, z1 = st['zone']
                    self.assertGreaterEqual(z0 * sc, 40)
                    self.assertLessEqual((z1 + cfgmod.SCOREBOARD_TAIL + cfgmod.ZONE_MARGIN) * sc, c0)   # scoreboard left of the icons
                    self.assertGreater(z1 - z0, 2 * cfgmod.PLATE_W)

    def test_author_pc_matches_the_measured_default(self):
        info, cluster, _ = info_for(2560, 1440, 1.0, icons=13)
        st = cfgmod.stage(info, CFG)
        self.assertEqual(cluster[0], 972)                          # the real UIA start button on the author's PC
        self.assertEqual(st['zone'], (40, 912))                    # the hand-measured default was [40, 900]

    def test_left_aligned_icons_use_the_stretch_between_icons_and_tray(self):
        info, (c0, c1), tray0 = info_for(1920, 1080, 1.0, icons=8, centred=False)
        z0, z1 = cfgmod.stage(info, CFG)['zone']
        self.assertGreaterEqual(z0, c1 + cfgmod.ZONE_MARGIN)
        self.assertLessEqual(z1 + 36, tray0)

    def test_widgets_at_the_far_left_are_kept_clear(self):
        info, (c0, c1), _ = info_for(2560, 1440, 1.0, widgets=True)
        z0, z1 = cfgmod.stage(info, CFG)['zone']
        self.assertGreaterEqual(z0, 160 + cfgmod.ZONE_MARGIN)
        self.assertLessEqual(z1 + 36, c0)

    def test_windows10_set_wide_task_list_container_is_not_occupied(self):
        """Windows 10: start, a wide search box, task view, left-aligned buttons inside a task-list window that spans the whole
        free stretch, the tray.  The spanning list is a container (it holds the buttons), so the free stretch survives."""
        t, b = 1040, 1080
        parts = [(0, t, 1920, b), (0, t, 48, b), (48, t, 392, b), (392, t, 440, b),
                 (440, t, 1650, b)] + [(440 + i * 54, t, 494 + i * 54, b) for i in range(6)] + [(1650, t, 1920, b), (1660, t, 1690, b), (1700, t, 1740, b),
                                                                        (1750, t, 1790, b), (1800, t, 1840, b), (1910, t, 1920, b)]
        info = dict(rect=(0, t, 1920, b), edge=3, monitor=(0, 0, 1920, 1080), work=(0, 0, 1920, t), dpi=1.0, parts=parts)
        z0, z1 = cfgmod.stage(info, CFG)['zone']
        self.assertGreaterEqual(z0, 440 + 6 * 54)
        self.assertLessEqual(z1 + 36, 1650)

    def test_no_parts_keeps_the_default_zone(self):
        info, _, _ = info_for(2560, 1440)
        info['parts'] = None
        st = cfgmod.stage(info, CFG)
        self.assertEqual((st['zone'], st['zone_src']), ((40, 900), 'default'))
        cfg = dict(CFG)
        self.assertFalse(cfgmod.apply_stage(cfg, st))
        self.assertEqual(cfg['zone'], [40, 900])

    def test_no_room_gives_a_cramped_zone_that_still_keeps_off_the_icons(self):
        """1920x1080 at 200% is 960 logical px, and a 1024 px taskbar (the GitHub Windows runner: occupied 287-732 and
        790-1024, read from its real doctor output) leaves 287 px: no gap holds plates + scoreboard.  A narrow zone in the gap
        is used (the HUD is crowded) instead of the default zone, which would walk over the icons."""
        info, (c0, _), _ = info_for(1920, 1080, 2.0)
        st = cfgmod.stage(info, CFG)
        self.assertEqual(st['zone_src'], 'auto (cramped)')
        self.assertLessEqual((st['zone'][1] + 36 + cfgmod.ZONE_MARGIN) * 2, c0)
        t, b = 720, 768
        runner = dict(rect=(0, t, 1024, b), edge=3, monitor=(0, 0, 1024, 768), work=(0, 0, 1024, t), dpi=1.0,
                      parts=[(0, t, 1024, b), (287, t, 732, b), (790, t, 1024, b)])
        st = cfgmod.stage(runner, CFG)
        self.assertEqual((st['zone'], st['zone_src']), ((40, 240), 'auto (cramped)'))
        z0, z1 = cfgmod.fight_zone(dict(CFG, zone=list(st['zone'])))
        self.assertLess(z0, z1)
        self.assertLessEqual(z1 + cfgmod.SPRITE_REACH, 287)                     # no sprite reaches the first icon
        info['parts'] = None
        info['rect'] = (2560, 1032, 4480, 1080)              # a taskbar on a second monitor: measured from its own left end
        st = cfgmod.stage(info, CFG)
        self.assertEqual(st["zone"][0], 2560 + 40)          # (a 48 px band: scale 1)

    def test_a_zone_in_minis_json_always_wins(self):
        info, _, _ = info_for(1920, 1080)
        cfg = dict(CFG, zone=[100, 700], zone_auto=False)
        st = cfgmod.stage(info, cfg)
        self.assertEqual(st['zone_src'], 'config')
        self.assertFalse(cfgmod.apply_stage(cfg, st))
        self.assertEqual(cfg['zone'], [100, 700])

    def test_load_turns_zone_auto_off_when_the_owner_sets_a_zone(self):
        import tempfile, os
        d = tempfile.mkdtemp()
        p = Path(d) / 'minis.json'
        p.write_text(json.dumps({'zone': [10, 600]}), encoding='utf-8')
        self.assertEqual((cfgmod.load(p)['zone'], cfgmod.load(p)['zone_auto']), ([10, 600], False))
        p.write_text(json.dumps({'monitor': 2}), encoding='utf-8')
        self.assertEqual((cfgmod.load(p)['zone_auto'], cfgmod.load(p)['monitor']), (True, 2))
        os.remove(p)
        os.rmdir(d)

    def test_a_growing_cluster_moves_the_zone_end_in_grid_steps_and_never_onto_an_icon(self):
        ends = []
        for n in range(4, 24):
            info, (c0, _), _ = info_for(2560, 1440, 1.0, icons=n)
            z1 = cfgmod.stage(info, CFG)['zone'][1]
            self.assertLessEqual(z1 + 36 + cfgmod.ZONE_MARGIN, c0)
            self.assertEqual(z1 % cfgmod.ZONE_GRID, 0)
            ends.append(z1)
        self.assertEqual(ends, sorted(ends, reverse=True))
        self.assertLess(len(set(ends)), len(ends))                 # several icon counts share a zone: no re-layout per icon

    def test_vertical_and_top_taskbars_get_a_strip_at_the_bottom_of_the_work_area(self):
        for edge in (0, 1, 2):
            for dpi in DPIS:
                with self.subTest(edge=edge, dpi=dpi):
                    info, _, _ = info_for(1920, 1080, dpi, edge=edge)
                    st = cfgmod.stage(info, CFG)
                    work = info['work']
                    self.assertEqual((st['layout'], st['usable'], st['edge']), ('strip', True, cfgmod.EDGES[edge]))
                    self.assertEqual(st['floor'], work[3])
                    self.assertEqual(st['band'][1] - st['band'][0], cfgmod.band_for_dpi(dpi))
                    z0, z1 = st['zone']
                    sc = st['scale']
                    self.assertGreaterEqual(z0 * sc, work[0] + 40)        # beside a left taskbar, never under it
                    self.assertLessEqual((z1 + 36) * sc, work[2])           # never under a right taskbar
                    self.assertLessEqual(z1 - z0, cfgmod.STRIP_ZONE_MAX)

    def test_bottom_autohide_shows_only_while_revealed(self):
        info, _, _ = info_for(1920, 1080, 1.0, autohide=True, revealed=True)
        self.assertTrue(cfgmod.stage(info, CFG)['usable'])
        info['revealed'] = False
        st = cfgmod.stage(info, CFG)
        self.assertFalse(st['usable'])
        self.assertIn('auto-hides', st['why'])

    def test_autohide_shown_rect_and_revealed_flag(self):
        mon = (0, 0, 1920, 1080)
        self.assertEqual(cfgmod.autohide_shown((0, 1032, 1920, 1080), mon, 3), ((0, 1032, 1920, 1080), True))
        self.assertEqual(cfgmod.autohide_shown((0, 1078, 1920, 1126), mon, 3), ((0, 1032, 1920, 1080), False))   # 2 px left
        self.assertEqual(cfgmod.autohide_shown((0, -46, 1920, 2), mon, 1), ((0, 0, 1920, 48), False))
        self.assertEqual(cfgmod.autohide_shown((-60, 0, 2, 1080), mon, 0), ((0, 0, 62, 1080), False))
        self.assertEqual(cfgmod.autohide_shown((1858, 0, 1920, 1080), mon, 2), ((1858, 0, 1920, 1080), True))

    def test_edge_of_a_secondary_taskbar(self):
        mon = (2560, 0, 4480, 1080)
        self.assertEqual(cfgmod.edge_of((2560, 1032, 4480, 1080), mon), 3)
        self.assertEqual(cfgmod.edge_of((2560, 0, 4480, 48), mon), 1)
        self.assertEqual(cfgmod.edge_of((2560, 0, 2622, 1080), mon), 0)
        self.assertEqual(cfgmod.edge_of((4418, 0, 4480, 1080), mon), 2)

    def test_secondary_monitor_at_a_negative_x(self):
        """A taskbar on a monitor LEFT of the primary (negative screen x) still gives a zone inside that monitor."""
        rect, parts, (c0, _), _ = win11_bar(1920, 1080, 1.0)
        dx = -1920
        sh = lambda r: (r[0] + dx, r[1], r[2] + dx, r[3])
        info = dict(rect=sh(rect), edge=3, monitor=(-1920, 0, 0, 1080), work=(-1920, 0, 0, 1032), dpi=1.0, parts=[sh(p) for p in parts])
        z0, z1 = cfgmod.stage(info, CFG)['zone']
        self.assertEqual(z0, -1920 + 40)
        self.assertLessEqual(z1 + 36, c0 + dx)

    def test_legacy_shells_are_laid_out_exactly_as_before(self):
        st = cfgmod.stage(dict(legacy=True, rect=(0, 1392, 2560, 1440), edge=3, autohide=False), CFG)
        self.assertEqual((st['usable'], st['band'], st['scale'], st['zone']), (True, (1392, 1440), 1, None))
        st = cfgmod.stage(dict(legacy=True, rect=(0, 0, 2560, 48), edge=1, autohide=False, screen=(2560, 1440)), CFG)
        self.assertEqual((st['usable'], st['band']), (False, (1392, 1440)))

    def test_select_popup_is_placed_above_the_band_on_its_monitor(self):
        x, y = select_window.placement(None, 300, 200, 2, centre_x=-1000, area=(-1920, 0, 1032))
        self.assertEqual((x, y), (-1000 - 300, 1032 - 400 - select_window.MARGIN))
        x, _ = select_window.placement(None, 300, 200, 2, centre_x=-1900, area=(-1920, 0, 1032))
        self.assertEqual(x, -1920 + select_window.MARGIN)              # kept on that monitor

    def test_review8_select_popup_stays_on_a_monitor_above_the_primary(self):
        """Codex review #8: max(MARGIN, ...) forced y >= 8, so on a monitor ABOVE the primary (negative screen y) the popup
        landed on the primary.  It is clamped to the target monitor's own top instead."""
        mon = (0, -1080, 1920, 0)
        info = dict(rect=(0, -48, 1920, 0), edge=3, monitor=mon, work=(0, -1080, 1920, -48), dpi=1.0, parts=None)
        st = cfgmod.stage(info, CFG)
        self.assertEqual(st['monitor'], mon)
        area = minis.select_area(st)
        x, y = select_window.placement(None, 300, 200, 2, centre_x=960, area=area)
        self.assertEqual(y, -48 - 400 - select_window.MARGIN)                    # just above that bar, negative y kept
        self.assertTrue(mon[1] <= y and y + 400 <= mon[3])
        _, y = select_window.placement(None, 300, 600, 2, centre_x=960, area=area)     # taller than the room above the bar
        self.assertEqual(y, mon[1] + select_window.MARGIN)                         # clamped to THAT monitor's top, not 8

    def test_review7_known_full_taskbar_hides_instead_of_using_the_default_zone(self):
        """Codex review #7: element rects known, no gap left (a bar full of buttons): the default zone would put fighters on
        the buttons.  Hide and say why; the default zone stays only for when no element rects could be read."""
        t, b = 1392, 1440
        parts = [(0, t, 2560, b)] + [(i * 44, t, i * 44 + 44, b) for i in range(52)] + [(2290, t, 2560, b)]
        info = dict(rect=(0, t, 2560, b), edge=3, monitor=(0, 0, 2560, 1440), work=(0, 0, 2560, t), dpi=1.0, parts=parts,
                    parts_src='uia')
        st = cfgmod.stage(info, CFG)
        self.assertFalse(st['usable'])
        self.assertIsNone(st['zone'])
        self.assertEqual(st['zone_src'], 'none')
        self.assertIn('no free taskbar space', st['why'])
        cfg = dict(CFG)
        self.assertFalse(cfgmod.apply_stage(cfg, st))
        info['parts'] = None                                                        # nothing readable: default, shown
        st = cfgmod.stage(info, CFG)
        self.assertEqual((st['usable'], st['zone_src'], st['zone']), (True, 'default', (40, 900)))
        info['parts'] = parts                                                       # the owner's own zone always shows
        st = cfgmod.stage(info, dict(CFG, zone=[40, 400], zone_auto=False))
        self.assertTrue(st['usable'])


# ------------------------------------------------------------------------------------------------ the loops, headless
class InfoShell:
    """A fake Windows shell with taskbar_info (rects only) and a layout epoch, like minis_win.shell."""

    def __init__(self, info):
        self.info = info
        self.epoch = 0
        self.calls = 0
        self.Overlay = FakeOverlay

    def taskbar_info(self, monitor=None):
        self.calls += 1
        return dict(self.info)

    def layout_epoch(self):
        return self.epoch

    def taskbar_rect(self):                                # still there (status, selftest); the loops do not use it
        return tuple(self.info['rect']) + (self.info['edge'],)

    def taskbar_autohide(self):
        return self.info.get('autohide', False)

    def screen_size(self):
        return self.info['monitor'][2], self.info['monitor'][3]

    def fullscreen_busy(self):
        return False

    def monitors(self):
        return [{'index': 1, 'rect': self.info['monitor'], 'work': self.info['work'], 'primary': True, 'scale': self.info['dpi']}]


class Loops(Isolated):
    def setUp(self):
        super().setUp()
        from unittest import mock
        p = mock.patch.object(minis.plat, 'is_mac', return_value=False)      # these shells stand in for Windows: on the
        p.start()                                                            # macOS CI runner the Mac-only placements
        self.addCleanup(p.stop)                                              # (scoreboard at the screen's right) stay off
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                               'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex'}, 'ts': self.t['wall']})

    def fighter(self, shell, slot='a', size=64):
        f = minis.Fighter(slot, dict(CFG, fighter_size=size), shell, mono=lambda: self.t['mono'], wall=lambda: self.t['wall'],
                          detector_for=lambda src, cfg: FakeDetector(src))
        f.setup()
        return f

    def go(self, objs, secs, dt=0.05):
        for _ in range(int(round(secs / dt))):
            self.t['mono'] += dt
            self.t['wall'] += dt
            for o in objs:
                o.step()

    def test_fighter_geometry_at_every_dpi_and_size(self):
        for dpi in DPIS:
            for size in (64, 128):
                with self.subTest(dpi=dpi, size=size):
                    info, (c0, _), _ = info_for(2560, 1440, dpi)
                    f = self.fighter(InfoShell(info), size=size)
                    self.go([f], 0.3)
                    sc = f.g['scale']
                    top = f.cell - cfgmod.feet_drop(size) + cfgmod.headroom_px(size)
                    self.assertEqual(f.ov.y, 1440 - top * sc)                         # feet on the floor
                    band_t = 1440 - int(round(48 * dpi))
                    self.assertGreaterEqual(f.g['plate_y'], band_t)                     # plate inside the taskbar band
                    self.assertLessEqual(f.g["plate_y"] + cfgmod.PLATE_H * sc, 1440)
                    self.assertTrue(f.ov.visible)
                    self.assertEqual(f.ov.presented[-1][1] % sc, 0)                     # window x in whole scaled px
                    self.assertEqual(list(f.cfg['zone']), list(cfgmod.stage(info, CFG)['zone']))
                    self.assertLessEqual(f.brain.band[1] * f.k * sc, c0)                # nothing drawn onto the icons

    def test_vertical_taskbar_shows_the_fighters_on_the_work_area_strip(self):
        info, _, _ = info_for(1920, 1080, 1.0, edge=0)
        f = self.fighter(InfoShell(info))
        self.go([f], 0.3)
        self.assertTrue(f.ov.visible)
        self.assertEqual(f.g['bottom'], 1080)
        self.assertGreaterEqual(f.cfg['zone'][0], 62 + 40)

    def test_autohide_follows_the_reveal_within_a_quarter_second(self):
        info, _, _ = info_for(1920, 1080, 1.0, autohide=True, revealed=True)
        sh = InfoShell(info)
        f = self.fighter(sh)
        board = minis.Scoreboard(dict(CFG), sh, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        board.setup()
        self.go([f, board], 0.3)
        self.assertTrue(f.ov.visible and f.pov.visible and board.ov.visible)
        sh.info['revealed'] = False                       # the bar slid away: nothing may cover its 2 px reveal strip
        self.go([f, board], 0.3)
        self.assertFalse(f.ov.visible or f.pov.visible or board.ov.visible)
        sh.info['revealed'] = True
        self.go([f, board], 0.3)
        self.assertTrue(f.ov.visible and board.ov.visible)

    def test_a_growing_icon_cluster_re_zones_brain_plates_and_scoreboard_live(self):
        info, _, _ = info_for(2560, 1440, 1.0, icons=6)
        sh = InfoShell(info)
        fa, fb = self.fighter(sh, 'a'), self.fighter(sh, 'b')
        board = minis.Scoreboard(dict(CFG), sh, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        board.setup()
        self.go([fa, fb, board], 0.5)
        z_before = tuple(fa.cfg['zone'])
        sb_x = board.ov.x
        info2, (c0, _), _ = info_for(2560, 1440, 1.0, icons=20)
        sh.info = info2
        self.go([fa, fb, board], 2.2)
        z_after = tuple(fa.cfg['zone'])
        self.assertLess(z_after[1], z_before[1])
        self.assertEqual(tuple(fb.cfg['zone']), z_after)                       # both processes detect the same zone
        self.assertEqual(fa.brain.zone, cfgmod.fight_zone(fa.cfg))
        self.assertLessEqual(fa.brain.home[1], fa.brain.zone[1])
        self.assertLessEqual(fb.brain.home[1], fb.brain.zone[1])
        self.assertLessEqual(fb.brain.x, fb.brain.zone[1])
        self.assertEqual(fb.pov.x, cfgmod.plate_left(fb.cfg, 'b'))
        self.assertLess(board.ov.x, sb_x)
        self.assertLessEqual(board.ov.x + SB.W, c0)                              # the widget stays left of the icons

    def test_a_layout_change_is_picked_up_at_once_not_after_two_seconds(self):
        info, _, _ = info_for(1920, 1080, 1.0)
        sh = InfoShell(info)
        f = self.fighter(sh)
        self.go([f], 0.3)
        n = sh.calls
        self.go([f], 0.3)
        self.assertEqual(sh.calls, n)                       # nothing changed: the 2 s cadence
        sh.info = info_for(1920, 1080, 2.0)[0]              # the owner switched the display to 200%, then the
        sh.epoch += 1                                       # backend saw WM_DPICHANGED / WM_DISPLAYCHANGE
        self.go([f], 0.1)
        self.assertEqual(f.g['scale'], 2)
        self.assertEqual(f.ov.scale, 2)
        self.assertEqual(f.pov.scale, 2)

    def test_explorer_restart_moves_the_taskbar_to_the_top_live(self):
        info, _, _ = info_for(1920, 1080, 1.0)
        sh = InfoShell(info)
        f = self.fighter(sh)
        self.go([f], 0.3)
        sh.info = info_for(1920, 1080, 1.0, edge=1)[0]
        sh.epoch += 1                                       # TaskbarCreated
        self.go([f], 0.1)
        self.assertTrue(f.ov.visible)
        self.assertEqual(f.g['stage']['layout'], 'strip')
        self.assertEqual(f.g['bottom'], 1080)

    def test_a_cramped_taskbar_runs_both_fighters_and_the_scoreboard(self):
        t, b = 720, 768
        sh = InfoShell(dict(rect=(0, t, 1024, b), edge=3, monitor=(0, 0, 1024, 768), work=(0, 0, 1024, t), dpi=1.0,
                            parts=[(0, t, 1024, b), (287, t, 732, b), (790, t, 1024, b)], autohide=False, revealed=True))
        fa, fb = self.fighter(sh, 'a'), self.fighter(sh, 'b')
        board = minis.Scoreboard(dict(CFG), sh, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        board.setup()
        self.go([fa, fb, board], 3.0)
        for f in (fa, fb):
            self.assertTrue(f.ov.visible)
            self.assertLessEqual(f.brain.x + cfgmod.SPRITE_REACH, 287)

    def test_review7_a_full_taskbar_hides_fighters_plates_and_scoreboard_and_status_says_why(self):
        from unittest import mock
        t, b = 1392, 1440
        parts = [(0, t, 2560, b)] + [(i * 44, t, i * 44 + 44, b) for i in range(52)] + [(2290, t, 2560, b)]
        info = dict(rect=(0, t, 2560, b), edge=3, monitor=(0, 0, 2560, 1440), work=(0, 0, 2560, t), dpi=1.0, parts=parts,
                    parts_src='uia', autohide=False, revealed=True)
        sh = InfoShell(info)
        f = self.fighter(sh)
        board = minis.Scoreboard(dict(CFG), sh, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        board.setup()
        self.go([f, board], 0.5)
        self.assertFalse(f.ov.visible or f.pov.visible or board.ov.visible)
        with mock.patch.object(minis.plat, 'shell', return_value=sh):
            line, _ok = minis.on_screen(now=self.t['wall'])
        self.assertIn('no free taskbar space', line)

    def test_status_reports_a_hidden_autohide_taskbar(self):
        from unittest import mock
        info, _, _ = info_for(1920, 1080, 1.0, autohide=True, revealed=False)
        with mock.patch.object(minis.plat, 'shell', return_value=InfoShell(info)):
            line, _ok = minis.on_screen(now=self.t['wall'])
        self.assertIn('auto-hides and is hidden right now (fighters hide)', line)
        info, _, _ = info_for(1920, 1080, 1.0, edge=0)
        with mock.patch.object(minis.plat, 'shell', return_value=InfoShell(info)):
            line, _ok = minis.on_screen(now=self.t['wall'])
        self.assertNotIn('taskbar', line)                  # a left taskbar no longer hides the fighters


if __name__ == '__main__':
    unittest.main()
