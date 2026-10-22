"""The UX layer: Settings + zone editor, first-run guide + legend, hover cards, event signals, the results moment, the rival
countdown, instant replay + fight codes + GIF export, and the move book.  Pure models are driven directly; the window
drivers and the director / fighter hooks run against fake shells (no real window, no screen capture, no PowerShell)."""
import io, json, os, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
import minis  # noqa: E402
from PIL import Image  # noqa: E402
from minis_core import (bus, collection, control, director, guide as G, hovercard as HC, records, render, replay, results as R,  # noqa: E402
                        settings_ui as S, signals as SG, ux, ux_runtime)
from minis_core.sources import Activity  # noqa: E402
from minis_core.telemetry import Snapshot  # noqa: E402

PLAN = dict(kind='match', left='a', right='b', pos={'a': 300.0, 'b': 332.0}, t0=5000.0, seed=42, chars={'a': 'claude', 'b': 'codex'},
            mode='decided', scores={'a': 70.0, 'b': 90.0}, span=110.0, rival=True, deadline=9.0, id='run:3')


class Ov:
    """A fake window that keeps the last picture."""
    made = []

    def __init__(self, title, x, y, w, h, scale=1, on_event=None, on_timer=None, on_hittest=None, on_key=None, activatable=False,
                 on_blur=None):
        self.title, self.x, self.y, self.w, self.h, self.scale = title, x, y, w, h, scale
        self.on_event, self.on_hittest, self.on_key, self.activatable, self.on_blur = on_event, on_hittest, on_key, activatable, on_blur
        self.visible, self.closed, self.focused, self.img, self.n = True, False, False, None, 0
        Ov.made.append(self)

    def present(self, im, x=None):
        self.img, self.n = im, self.n + 1
        if x is not None:
            self.x = x
        return True

    def show(self, v):
        self.visible = v

    def move(self, x, y):
        self.x, self.y = x, y

    def reassert_topmost(self):
        pass

    def focus(self):
        self.focused = True

    def pump(self):
        return True

    def set_scale(self, s):
        self.scale = s

    def menu(self, items):
        return 0

    def close(self):
        self.closed = True


class Shell:
    def __init__(self):
        self.Overlay = Ov
        self.cursor = None

    def taskbar_rect(self):
        return 0, 1392, 2560, 1440, 3

    def taskbar_autohide(self):
        return False

    def screen_size(self):
        return 2560, 1440

    def fullscreen_busy(self):
        return False

    def cursor_pos(self):
        return self.cursor

    def monitors(self):
        return [{'index': 1, 'rect': (0, 0, 2560, 1440), 'work': (0, 0, 2560, 1392), 'primary': True}]


def titles(prefix):
    return [o for o in Ov.made if o.title.startswith(prefix) and not o.closed]


# ======================================================================== state file
class UxState(Isolated):
    def test_switches_default_on_and_persist(self):
        for name in ('results', 'cards', 'signals'):
            self.assertTrue(ux.switch(name))
            ux.set_switch(name, False)
            self.assertFalse(ux.switch(name))
        with self.assertRaises(ValueError):
            ux.set_switch('paused', True)                                # control.json keys are not ours

    def test_requests_expire_and_carry_a_short_arg(self):
        ux.request('replay', 'TF2-x' * 60, now=1000.0)
        r = ux.pending(now=1001.0)
        self.assertEqual(r['kind'], 'replay')
        self.assertLessEqual(len(r['arg']), 120)
        self.assertIsNone(ux.pending(now=1000.0 + ux.REQUEST_MAX_AGE_S + 1))
        with self.assertRaises(ValueError):
            ux.request('format-disk')

    def test_first_run_flag(self):
        self.assertFalse(ux.first_run_done())
        ux.set_first_run_done()
        self.assertTrue(ux.first_run_done())

    def test_write_setting_keeps_other_keys_and_refuses_a_broken_file(self):
        p = self.data / 'minis.json'
        p.write_text(json.dumps({'ignore_sources': ['grok'], 'zone': [1, 2]}))
        self.assertTrue(ux.write_setting('zone', [100, 900], p))
        self.assertEqual(json.loads(p.read_text()), {'ignore_sources': ['grok'], 'zone': [100, 900]})
        self.assertTrue(ux.write_setting('zone', None, p))
        self.assertEqual(json.loads(p.read_text()), {'ignore_sources': ['grok']})
        p.write_text('{not json')
        self.assertFalse(ux.write_setting('zone', [0, 700], p))
        self.assertEqual(p.read_text(), '{not json')                       # someone's file is never overwritten

    def test_quiet_reads_calm_or_quiet(self):
        self.assertFalse(ux.quiet(lambda: {}))
        self.assertTrue(ux.quiet(lambda: {'calm': True}))
        self.assertTrue(ux.quiet(lambda: {'quiet': 1}))


# ======================================================================== replay, fight codes, GIF
class Replay(Isolated):
    def test_stats_from_the_planners_own_summary(self):
        _, s = replay.summarize(PLAN)
        st = replay.stats_of(s)
        self.assertGreater(st['hits'], 5)
        self.assertGreaterEqual(st['best_combo'], 2)
        self.assertEqual(st['rounds'], len(s['rounds']))
        line = replay.result_line(dict(stats=st, winner=s['winner'], wins=s['wins'], labels={'a': 'Claude', 'b': 'Codex'}))
        self.assertTrue(line.startswith(('CLAUDE WINS', 'CODEX WINS')))
        self.assertIn(f"{st['hits']} hits", line)

    def test_store_keeps_numbers_and_ids_only_and_counts_head_to_head(self):
        _, s = replay.summarize(PLAN)
        e = replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, {'a': 'Claude', 'b': 'Codex'}, now=1000.0)
        self.assertNotIn('rival', e['plan'])                                # only what the planner reads
        self.assertNotIn('deadline', e['plan'])
        self.assertNotIn('id', e['plan'])
        self.assertTrue(e['code'].startswith('TF2-claude-codex-'))
        w = 'claude' if s['winner'] == 'a' else 'codex'
        l = 'codex' if w == 'claude' else 'claude'
        self.assertEqual(replay.h2h(w, l), (1, 0))
        self.assertEqual(replay.h2h(l, w), (0, 1))
        for i in range(replay.KEEP + 3):
            replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, now=2000.0 + i)
        self.assertEqual(len(replay.read()['matches']), replay.KEEP)
        self.assertEqual(sum(replay.h2h('claude', 'codex')), replay.KEEP + 4)
        self.assertIsNone(replay.store(dict(PLAN, kind='spar'), s, {}))       # only matches

    def test_a_fight_code_reproduces_the_match(self):
        for seed, mode, boost in ((42, 'decided', []), (7, 'random', ['b']), (913, 'decided', ['a'])):
            plan = dict(PLAN, seed=seed, mode=mode, boost=boost, pos={'a': 268.4375, 'b': 301.5}, span=97.125)
            _, s = replay.summarize(plan)
            code = replay.encode(replay.clean_plan(plan), s)
            self.assertLess(len(code), 60)
            p2, expect, ver = replay.decode(code)
            self.assertEqual(ver, replay.ENGINE)
            _, s2 = replay.summarize(p2)
            self.assertEqual((s2['winner'], s2['wins']), (s['winner'], s['wins']))
            self.assertEqual(replay.stats_of(s2), replay.stats_of(s))
            self.assertEqual(expect, {'winner': s['winner'], 'wins': s['wins']})

    def test_a_code_carries_no_context_numbers(self):
        a = replay.encode(replay.clean_plan(dict(PLAN, scores={'a': 70.0, 'b': 90.0})))
        b = replay.encode(replay.clean_plan(dict(PLAN, scores={'a': 7.0, 'b': 9.0})))
        self.assertEqual(a, b)                                              # only the odds (a ratio), not the weights

    def test_damaged_and_foreign_codes_say_so(self):
        code = replay.encode(replay.clean_plan(PLAN))
        bad = code[:-3] + ('a' if code[-3] != 'a' else 'b') + code[-2:]
        with self.assertRaises(replay.CodeError):
            replay.decode(bad)
        with self.assertRaises(replay.CodeError):
            replay.decode('hello')
        old = bytearray(replay._unb32(code.split('-')[3]))
        old[0] = 99
        old[-1] = sum(old[:-1]) & 0xFF
        plan, _, _, _, warn = replay.resolve('TF2-claude-codex-' + replay._b32(bytes(old)))
        self.assertIn('different engine version', warn)

    def test_frames_are_offline_renders_on_the_plain_backdrop(self):
        fr = list(replay.frames(PLAN, 'final', fps=10, limit=4))
        self.assertEqual(len(fr), 4)
        im, ms = fr[0]
        self.assertEqual(im.size, (replay.W, replay.H))
        self.assertEqual(ms, 100)
        self.assertEqual(im.getpixel((replay.W - 3, replay.H - 3))[:3], replay.BAND[:3])   # the backdrop's taskbar band
        start, end = replay.window_of(PLAN, replay.summarize(PLAN)[1], 'final')
        self.assertLess(end - start, 12.0)
        sched = replay.schedule(0.0, 2.0, 10, slow_from=1.0)
        self.assertGreater(len(sched), 25)                                  # the K.O. runs at half speed
        self.assertTrue(sched[-1][1])

    def test_gif_goes_to_the_exports_folder_in_the_data_dir(self):
        out = replay.exports_dir()
        self.assertEqual(out, self.data / 'exports')                        # under the data folder, nowhere else
        self.assertFalse(replay.reveal(out / 'x.gif'))                      # no Explorer / Finder under tests
        with mock.patch.dict(os.environ, {'MINIS_TESTING': '1'}):
            p, n = replay.save_gif(replay.frames(PLAN, 'final', fps=8, limit=6), out / replay.gif_name(PLAN, now=0))
        self.assertTrue(p.exists())
        self.assertEqual(n, 6)
        with Image.open(p) as g:
            self.assertEqual(g.format, 'GIF')
            self.assertEqual(g.size, (replay.W, replay.H))
        self.assertTrue(p.name.startswith('taskbar-fighters-claude-vs-codex-'))


# ======================================================================== the move book
class Book(Isolated):
    def setUp(self):
        super().setUp()
        from minis_core.atlas import Library
        from minis_core import lineup
        self.lib = Library()
        self.chars = lineup.characters()

    def test_catalogue_has_every_move_set_piece_and_finisher(self):
        a = self.lib['claude']
        e = collection.entries(a)
        moves = sum(len(e[s]) for s in ('attacks', 'defense', 'everyday'))
        self.assertEqual(moves, len(a.anim))                                # every move, once
        self.assertEqual(len(e['pieces']), 8)
        self.assertEqual([x['type'] for x in e['finishers']], ['ultimate', 'super', 'finisher'])
        got, tot = collection.counts(a, set())
        self.assertEqual(got, 0)
        self.assertGreater(tot, 70)

    def test_tracker_merges_and_heals(self):
        t1, t2 = collection.Tracker(), collection.Tracker()
        t1.note_move('claude', 'jab', 10.0)
        t1.note_move('claude', 'jab', 11.0)                                 # the same anim again: nothing new
        t2.note_move('codex', 'spiral_orb', 12.0)
        t2.note_match(['claude', 'codex'], ['blade_lock'], 'codex', 13.0)
        self.assertTrue(t1.flush(100.0))
        self.assertTrue(t2.flush(100.0))
        seen = collection.read()
        self.assertEqual(set(seen['claude']), {'m:jab', 'p:blade_lock'})
        self.assertEqual(set(seen['codex']), {'m:spiral_orb', 'p:blade_lock', 'f:ko'})
        self.assertEqual(seen['claude']['m:jab'], 10.0)
        (self.data / 'collection.json').write_text('{"seen": {}}')          # lost to a race: the next flush puts it back
        t1.dirty = True
        t1.flush(1000.0)
        self.assertIn('m:jab', collection.read()['claude'])

    def test_book_navigation_and_silhouettes(self):
        b = collection.Book(self.chars, {'claude': {'m:jab': 1.0}}, self.lib, start='claude')
        self.assertEqual(b.char, 'claude')
        im = b.render(0.5)
        self.assertEqual(im.size, (b.W, b.H))
        vis = b.visible()
        jab = next(i for i, e in enumerate(vis) if e['key'] == 'm:jab')
        other = next(i for i, e in enumerate(vis) if e['key'] != 'm:jab' and not e['absent'])
        seen_p = b.portrait('claude', 'jab', 0.0, True)
        unseen_p = b.portrait('claude', vis[other]['anim'], 0.0, False)
        cols = {c[:3] for _, c in unseen_p.getcolors(1 << 16) if c[3]}
        self.assertEqual(cols, {(58, 58, 74)})                              # a silhouette: one flat colour
        self.assertGreater(len({c[:3] for _, c in seen_p.getcolors(1 << 16) if c[3]}), 4)
        b.key(collection.VK['tab'])
        self.assertEqual(b.si, 1)
        b.key(collection.VK['down'])
        b.key(collection.VK['down'])
        b.key(collection.VK['down'])                                        # past the grid: the next fighter
        self.assertNotEqual(b.char, 'claude')
        x0, y0, x1, y1 = b.tab_rects()[3]
        b.click((x0 + x1) // 2, (y0 + y1) // 2)
        self.assertEqual(collection.SECTIONS[b.si][0], 'pieces')
        b.key(collection.VK['esc'])
        self.assertEqual(b.phase, 'closed')
        self.assertIsNotNone(jab)


# ======================================================================== event signals
def snap(state='idle', ctx=30.0, events=(), sid='s1'):
    s = Snapshot('claude', state, ctx, events=list(events))
    s.sid = sid
    return s


class Signals(unittest.TestCase):
    def setUp(self):
        from minis_core.atlas import Library
        self.atlas = Library()['claude']
        self.view = dict(anim='idle', frame=0, x=500.0, facing=1, lift=0.0)

    def test_task_done_raises_a_flag_until_hovered(self):
        s = SG.Signals()
        s.on_snapshot(snap('idle', events=['finished']), 10.0)
        ov, _ = s.overlays(self.view, self.atlas, 10.1)
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0][0].size, SG.flag_image().size)
        self.assertLess(ov[0][2], SG.head_top(self.atlas, self.view))      # above the head
        s.on_snapshot(snap('working'), 40.0)
        self.assertTrue(s.flag)                                             # stays until the mouse passes over it
        self.assertTrue(s.hovered(41.0))
        self.assertEqual(s.overlays(self.view, self.atlas, 42.0)[0], [])

    def test_needs_you_halo_pulses_and_waves_but_holds_still_when_paused(self):
        s = SG.Signals()
        s.on_snapshot(snap('waiting'), 10.0)
        self.assertEqual(s.take_moves(), ['wave'])
        ov, anim = s.overlays(self.view, self.atlas, 10.3)
        self.assertTrue(anim)
        self.assertEqual(ov[0][3], 'back')                                  # round the feet, behind the sprite
        k1 = s.key(10.3)
        self.assertNotEqual(k1, s.key(10.9))                                # it moves ...
        ov2, anim2 = s.overlays(self.view, self.atlas, 10.9, paused=True)
        self.assertFalse(anim2)                                             # ... except when paused
        self.assertEqual(s.key(10.3, paused=True), s.key(10.9, paused=True))
        self.assertFalse(s.overlays(self.view, self.atlas, 10.9, flashes=False)[1])    # Flash effects off: no pulse
        s.on_snapshot(snap('waiting'), 10.0 + SG.WAVE_EVERY_S + 1, paused=True)
        self.assertEqual(s.take_moves(), [])                                # paused: nothing new starts

    def test_compaction_is_a_second_wind_and_the_plate_refills(self):
        s = SG.Signals()
        s.on_snapshot(snap('working', 92.0), 10.0)
        s.on_snapshot(snap('working', 31.0), 12.0)
        self.assertIn((12.0, 'second_wind'), s.events)
        self.assertIn('powerup', s.take_moves())
        p = s.plate_snap(snap('working', 31.0), 12.4)
        self.assertTrue(31.0 < p.ctx_pct < 92.0)                            # sweeping down: the refill
        self.assertEqual(s.plate_snap(snap('working', 31.0), 20.0).ctx_pct, 31.0)
        ov, _ = s.overlays(self.view, self.atlas, 12.5)
        self.assertTrue(any(o[0] is SG.text_mark('second') for o in ov))
        s2 = SG.Signals()
        s2.on_snapshot(snap('working', 92.0, sid='one'), 10.0)
        s2.on_snapshot(snap('working', 31.0, sid='two'), 12.0)              # a NEW session is not a compaction
        self.assertNotIn('second_wind', [e[1] for e in s2.events])

    def test_danger_once_near_the_limit_then_finish_on_the_ko(self):
        s = SG.Signals()
        s.on_snapshot(snap('working', 86.0), 10.0)
        s.on_snapshot(snap('working', 87.0), 11.0)
        self.assertEqual([e[1] for e in s.events], ['danger'])              # once per approach
        s.on_snapshot(snap('limit', 93.0, events=['limit']), 15.0)
        ov, _ = s.overlays(self.view, self.atlas, 15.2)
        self.assertTrue(any(o[0] is SG.text_mark('finish') for o in ov))
        self.assertFalse(any(o[0] is SG.text_mark('danger') for o in ov))
        s.on_snapshot(snap('idle', 20.0), 30.0)
        s.on_snapshot(snap('idle', 88.0), 31.0)
        self.assertEqual([e[1] for e in s.events].count('danger'), 2)       # re-armed below 80 %

    def test_quiet_keeps_only_the_static_marks(self):
        s = SG.Signals()
        s.on_snapshot(snap('working', 92.0, events=['finished']), 10.0)
        s.on_snapshot(snap('waiting', 31.0), 11.0)
        ov, anim = s.overlays(self.view, self.atlas, 11.2, quiet=True)
        self.assertFalse(anim)
        self.assertEqual(len(ov), 2)                                        # the flag and a still halo; no texts
        self.assertFalse(any(o[0] is SG.text_mark('second') for o in ov))


# ======================================================================== hover card
class Card(unittest.TestCase):
    def test_plain_words_for_each_state(self):
        txt = lambda info: ' / '.join(t for t, _, _ in HC.lines(info))
        self.assertIn('working · 3 min', txt(dict(name='Claude Code', state='working', since_s=190, ctx=77)))
        self.assertIn('waiting for you · 1 min 37 s', txt(dict(name='Codex', state='waiting', since_s=52, waiting_s=45)))
        self.assertIn('context 77%', txt(dict(name='x', state='working', ctx=77.2)))
        self.assertIn('usage limit, resets in 1h', txt(dict(name='x', state='limit', resets_in='1h', ctx=96)))
        self.assertIn('rival match in ~6 min', txt(dict(name='x', state='sleeping', rival_in=372)))
        self.assertIn('record 12-7 · vs Codex 5-3', txt(dict(name='x', state='idle', record=(12, 7), opponent='Codex', h2h=(5, 3))))
        self.assertIn('no numbers for this program', txt(dict(name='Grok', state='idle', ctx=None, process=True)))
        self.assertEqual(HC.dur(52), '52 s')
        self.assertEqual(HC.dur(7300), '2 h 1 min')

    def test_render_fits_and_never_needs_content(self):
        im = HC.render(dict(name='Claude Code', state='waiting', since_s=10, ctx=50, record=(1, 2), opponent='Codex', h2h=(0, 1)))
        self.assertEqual(im.width, HC.W)
        self.assertGreater(im.height, 40)
        self.assertEqual(set(HC.lines.__code__.co_varnames) & {'prompt', 'title', 'path', 'cwd'}, set())

    def test_dwell_and_leave(self):
        d = HC.Dwell()
        self.assertFalse(d.update('fighter', 0.0))
        self.assertFalse(d.update('fighter', 0.5))
        self.assertTrue(d.update('fighter', 0.65))
        self.assertTrue(d.update(None, 0.7))                                # a short slip off it keeps the card
        self.assertFalse(d.update(None, 1.0))
        self.assertFalse(d.update('plate', 1.1))

    def test_place_keeps_it_on_screen(self):
        self.assertEqual(HC.place((0, 100, 20, 140), 180, 60, 2560), (4, 36))
        self.assertEqual(HC.place((2550, 100, 2560, 140), 180, 60, 2560)[0], 2560 - 180 - 4)
        self.assertEqual(HC.place((100, 2, 228, 28), 180, 60, 2560, below=True)[1], 32)


# ======================================================================== guide + legend
class Guide(unittest.TestCase):
    targets = {'fighter': 520, 'plates': (40, 300), 'board': (746, 936)}

    def test_three_cards_next_skip_and_auto_advance(self):
        g = G.Guide('guide', (40, 940), self.targets, names={'a': 'Claude Code'}, now=0.0)
        self.assertIn('Claude Code', ' '.join(g.steps[0][2]))
        nx = g.buttons()['next']
        self.assertEqual(g.click((nx[0] + nx[2]) // 2, (nx[1] + nx[3]) // 2, 1.0), 'next')
        self.assertEqual(g.i, 1)
        g.tick(1.0 + G.STEP_S + 0.1)
        self.assertEqual(g.i, 2)
        sk = g.buttons()['skip']
        g.click(sk[0] + 2, sk[1] + 2, 20.0)
        self.assertEqual(g.phase, 'done')

    def test_only_the_card_takes_the_mouse_and_the_arrow_points_at_the_target(self):
        g = G.Guide('guide', (40, 940), self.targets, now=0.0)
        self.assertIsNone(g.hit(5, G.GH - 2))                               # the strip under the card clicks through
        r = g.card_rect()
        self.assertEqual(g.hit(r[0] + 5, r[1] + 5), 'card')
        im = g.render(0.5)
        tx = int(g.target_x('fighter'))
        self.assertGreater(im.getpixel((tx, G.GH - 6))[3], 0)               # the arrow reaches down at the fighter

    def test_legend_lasts_ten_seconds_or_one_click(self):
        g = G.Guide('legend', (40, 940), self.targets, now=0.0)
        g.tick(5.0)
        self.assertEqual(g.phase, 'open')
        g.tick(G.LEGEND_S + 0.1)
        self.assertEqual(g.phase, 'closed')
        g2 = G.Guide('legend', (40, 940), self.targets, now=0.0)
        k = g2._legend_boxes()['key']
        g2.click(k[0] + 4, k[1] + 4, 1.0)
        self.assertEqual(g2.phase, 'closed')
        self.assertEqual(g2.render(1.0).getbbox(), None)


# ======================================================================== settings + zone editor
class FakeStartup:
    def __init__(self, state='off'):
        self.state, self.calls = state, []

    def status(self):
        return self.state, Path('x.lnk')

    def enable(self):
        self.calls.append('on')
        self.state = 'on'
        return True, 'on'

    def disable(self):
        self.calls.append('off')
        self.state = 'off'
        return True, 'off'


class Settings(Isolated):
    def model(self, startup=None, restart=None):
        be = S.Backend(dict(CFG), startup=startup, restart=restart, edit_zone=lambda: self.zone_opened.append(1))
        self.zone_opened = []
        if startup is not None:
            be.startup_state = startup.status()[0]
        return S.Model(be, now=0.0, is_mac=False)

    def row(self, m, rid):
        return next(i for i, r in enumerate(m.rows) if r['id'] == rid)

    def click_control(self, m, rid, val=None):
        i = self.row(m, rid)
        for name, v, (a, b, c, d) in m.controls(i):
            if val is None or v == val:
                return m.click((a + c) // 2, (b + d) // 2, 1.0)

    def test_toggles_write_the_same_switches_as_the_cli(self):
        m = self.model()
        self.click_control(m, 'flash')
        self.assertFalse(control.flashes_on())
        self.click_control(m, 'forge')
        self.assertFalse(control.forge_on())
        self.click_control(m, 'results')
        self.assertFalse(ux.switch('results'))
        self.click_control(m, 'winners', 'random')
        self.assertEqual(control.winners(), 'random')
        m.cur = self.row(m, 'plates')
        m.key(S.VK['left'], 2.0)
        self.assertFalse(control.plates_on())
        m.key(S.VK['right'], 2.0)
        self.assertTrue(control.plates_on())

    def test_forge_default_stays_on_and_its_help_is_always_visible(self):
        m = self.model()
        self.assertTrue(m.values['forge'])                                  # the owner's choice: real pixels by default
        self.assertIn('never saved', next(r for r in m.rows if r['id'] == 'forge')['help'])

    def test_size_asks_for_a_restart(self):
        calls = []
        m = self.model(restart=lambda: calls.append(1) or True)
        self.click_control(m, 'size', 64)
        self.assertEqual(control.fighter_size(), 64)
        self.assertEqual(calls, [1])
        self.assertIn('restarting', m.msg)

    def test_startup_runs_off_the_window_thread(self):
        st = FakeStartup('off')
        m = self.model(startup=st)
        self.click_control(m, 'startup')
        for _ in range(200):
            if not m.backend.pending:
                break
            import time
            time.sleep(0.01)
        self.assertEqual(st.calls, ['on'])
        m.tick(5.0)
        self.assertEqual(m.values['startup'], 'on')

    def test_zone_row_opens_the_editor_and_rows_have_commands(self):
        m = self.model()
        self.click_control(m, 'zone', 'edit')
        self.assertEqual(self.zone_opened, [1])
        self.assertTrue(all(r['cli'] for r in m.rows))
        self.assertEqual(m.render(0.0).size, (m.W, m.H))
        m.key(S.VK['esc'], 1.0)
        self.assertEqual(m.phase, 'closed')

    def test_mac_says_open_at_login(self):
        self.assertEqual(S.rows(is_mac=True)[-2]['label'], 'Open at login')
        self.assertEqual(S.rows(is_mac=False)[-2]['label'], 'Start with Windows')


class Zone(unittest.TestCase):
    def test_drag_the_ends_and_the_bar_within_limits(self):
        z = S.ZoneEdit(1920, 48, (40, 900))
        y = S.BAR_H + 10
        z.on_event('down', 900, y)
        z.on_event('move', 1100, y)
        z.on_event('up', 1100, y)
        self.assertEqual((z.z0, z.z1), (40, 1100))
        z.on_event('down', 40, y)
        z.on_event('move', 800, y)                                          # never narrower than MIN_ZONE_W
        z.on_event('up', 800, y)
        self.assertEqual(z.z1 - z.z0, S.MIN_ZONE_W)
        z.on_event('down', z.z0 + 50, y)
        z.on_event('move', 5000, y)
        z.on_event('up', 5000, y)
        self.assertEqual(z.z1, 1920 - 4)
        self.assertTrue(z.solid(10, y))                                     # the band takes the mouse while editing
        self.assertFalse(z.solid(5, 2))                                     # the desktop above it does not

    def test_buttons(self):
        for b in ('save', 'auto', 'cancel'):
            z = S.ZoneEdit(1920, 48, (40, 900))
            r = z.buttons()[b]
            z.on_event('up', (r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
            self.assertEqual(z.phase, b)
        z = S.ZoneEdit(1920, 48, (40, 900))
        z.key(S.VK['right'])
        self.assertEqual(z.result(), [50, 910])
        z.key(S.VK['enter'])
        self.assertEqual(z.phase, 'save')


# ======================================================================== start at sign-in
class StartupWin(unittest.TestCase):
    def setUp(self):
        from minis_win import startup
        self.dir = Path(tempfile.mkdtemp())
        self.files = {}
        self.writes = []

        def reader(p):
            return self.files.get(str(p))

        def writer(p, spec):
            self.writes.append(str(p))
            self.files[str(p)] = (spec['target'], spec['arguments'])
            Path(p).write_text('lnk')
            return True
        self.st = startup.Startup(reader, writer, lambda t, a: a == '"C:\\me\\minis.py" start',
                                  lambda: {'target': 'pythonw.exe', 'arguments': '"C:\\me\\minis.py" start'}, folder=self.dir)

    def test_on_reuses_our_shortcut_and_never_duplicates(self):
        self.assertEqual(self.st.status()[0], 'off')
        self.assertTrue(self.st.enable()[0])
        self.assertTrue(self.st.enable()[0])
        self.assertEqual(len(self.writes), 1)                               # the second "on" reused it
        self.assertEqual([p.name for p in self.dir.iterdir()], ['Taskbar Fighters.lnk'])
        self.assertTrue(self.st.disable()[0])
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_another_copys_shortcut_is_left_alone(self):
        p = self.dir / 'Taskbar Fighters.lnk'
        p.write_text('lnk')
        self.files[str(p)] = ('pythonw.exe', '"D:\\other\\minis.py" start')
        self.assertEqual(self.st.status()[0], 'other')
        self.assertFalse(self.st.enable()[0])
        self.assertFalse(self.st.disable()[0])
        self.assertTrue(p.exists())
        self.assertEqual(self.writes, [])


class StartupMac(unittest.TestCase):
    def test_launch_agent_behind_the_same_interface(self):
        from minis_mac.startup import Startup
        home = Path(tempfile.mkdtemp())
        st = Startup('/usr/bin/python3', '/Users/me/tf', home=home)
        self.assertEqual(st.status()[0], 'off')
        self.assertTrue(st.enable()[0])
        self.assertEqual(st.status()[0], 'on')
        self.assertTrue(st.enable()[0])
        other = Startup('/usr/bin/python3', '/Users/me/other', home=home)
        self.assertEqual(other.status()[0], 'other')
        self.assertFalse(other.disable()[0])
        self.assertTrue(st.disable()[0])
        self.assertEqual(st.status()[0], 'off')


# ======================================================================== results
class Results(unittest.TestCase):
    def entry(self):
        return dict(id='m1', ts=100.0, plan=dict(PLAN), programs={'a': 'claude', 'b': 'codex'}, labels={'a': 'Claude', 'b': 'Codex'},
                    winner='b', loser='a', wins={'a': 1, 'b': 2}, stats=dict(hits=23, best_combo=5, ultimate=True))

    def test_headline_and_freshness(self):
        e = self.entry()
        self.assertEqual(R.headline(e), ('CODEX WINS 2-1', '23 hits · best combo 5 · ultimate landed'))
        self.assertTrue(R.fresh(e, 103.0))
        self.assertFalse(R.fresh(e, 103.0, shown_id='m1'))
        self.assertFalse(R.fresh(e, 100.0 + R.FRESH_S + 1))

    def test_beats_and_the_strip(self):
        e = self.entry()
        self.assertEqual(R.taskbar_beat(e, 'codex', 'b'), 'victory')
        self.assertEqual(R.taskbar_beat(e, 'claude', 'a'), 'bow')
        self.assertIsNone(R.taskbar_beat(e, 'grok', 'a'))
        from minis_core.atlas import Library
        im = R.render(e, 1.0, Library())
        self.assertEqual(im.size, (R.width(e), R.H))
        self.assertGreaterEqual(im.width, R.W)
        self.assertLess(R.render(e, R.SHOW_S - 0.05, Library()).getchannel('A').getextrema()[1], 60)    # fading out


# ======================================================================== the director host
class Host(Isolated):
    def setUp(self):
        super().setUp()
        Ov.made = []
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.shell = Shell()
        self.restarts = []
        self.board = minis.Scoreboard(dict(CFG), self.shell, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        with mock.patch.object(minis, 'ux_actions', lambda: dict(restart=lambda: self.restarts.append(1) or True,
                                                                  startup=lambda: FakeStartup('off'))):
            self.board.setup()

    def go(self, secs, dt=0.05):
        for _ in range(int(secs / dt)):
            self.t['mono'] += dt
            self.t['wall'] += dt
            self.board.step()

    def test_tray_items_reach_the_host_and_open_windows(self):
        from minis_win import tray as T
        minis.tray_choice(T.SETTINGS, {}, self.board, wall=lambda: self.t['wall'])
        self.go(0.4)
        w = titles('minis-settings')
        self.assertEqual(len(w), 1)
        self.assertTrue(w[0].activatable and w[0].focused)
        minis.tray_choice(T.BOOK, {}, self.board, wall=lambda: self.t['wall'])
        self.go(0.4)
        self.assertEqual(len(titles('minis-book')), 1)
        minis.tray_choice(T.LEGEND, {}, self.board, wall=lambda: self.t['wall'])
        self.go(0.4)
        lg = titles('minis-guide')
        self.assertEqual(len(lg), 1)
        self.assertFalse(lg[0].activatable)                                # the legend never takes the focus
        self.go(G.LEGEND_S + 0.5)
        self.assertEqual(titles('minis-guide'), [])

    def test_first_run_guide_once(self):
        with mock.patch.object(ux, 'testing', lambda: False):
            self.board.ux.setup()
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': None, 'ts': self.t['wall']})
        self.go(ux_runtime.FIRST_RUN_DELAY_S + 1.0)
        g = titles('minis-guide')
        self.assertEqual(len(g), 1)
        model = self.board.ux.win['guide'].model
        self.assertEqual(model.kind, 'guide')
        sk = model.buttons()['skip']
        g[0].on_event('up', sk[0] + 2, sk[1] + 2)
        self.go(0.2)
        self.assertTrue(ux.first_run_done())
        with mock.patch.object(ux, 'testing', lambda: False):
            self.board.ux.setup()
        self.assertIsNone(self.board.ux.first_run_at)                       # never again on its own

    def test_results_strip_after_a_match_then_gone(self):
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': None, 'ts': self.t['wall']})
        self.go(0.5)
        _, s = replay.summarize(PLAN)
        replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, {'a': 'Claude', 'b': 'Codex'}, now=self.t['wall'])
        self.go(1.0)
        strip = titles('minis-results')
        self.assertEqual(len(strip), 1)
        self.assertTrue(strip[0].visible)
        self.assertEqual(strip[0].on_hittest(5, 5), False)                  # click-through
        self.go(R.SHOW_S + 0.5)
        self.assertFalse(strip[0].visible)
        ux.set_switch('results', False)
        replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, now=self.t['wall'])
        self.go(1.0)
        self.assertFalse(strip[0].visible)                                  # switched off: nothing

    def test_replay_window_plays_frames_and_gif_lands_in_pictures(self):
        _, s = replay.summarize(PLAN)
        replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, now=self.t['wall'] - 60)
        ux.request('replay', now=self.t['wall'])
        self.go(0.3)
        w = self.board.ux.win['replay']
        w.thread.join(30)
        self.go(1.0)
        self.assertGreater(w.shown, 5)
        with mock.patch.object(replay, 'frames', _few), mock.patch.object(replay, 'reveal', lambda p: self.revealed.append(p)):
            self.revealed = []
            ux.request('gif', now=self.t['wall'])
            self.go(0.6)
            self.board.ux.gif.join(60)
        gifs = list((self.data / 'exports').glob('*.gif'))
        self.assertEqual(len(gifs), 1)
        self.assertEqual(self.revealed, gifs)                               # its folder opens with the file selected

    def test_zone_editor_saves_to_minis_json_and_restarts(self):
        p = self.data / 'minis.json'
        with mock.patch.object(ux, 'settings_path', lambda: p):
            ux.request('zone', now=self.t['wall'])
            self.go(0.3)
            zw = self.board.ux.win['zone']
            z = zw.model
            y = S.BAR_H + 5
            zw.on_event('down', z.z1, y)
            zw.on_event('move', z.z1 + 200, y)
            zw.on_event('up', z.z1 + 200, y)
            r = z.buttons()['save']
            zw.on_event('up', r[0] + 3, r[1] + 3)
            self.go(0.2)
        self.assertEqual(json.loads(p.read_text())['zone'], [40, 1100])
        self.assertEqual(self.restarts, [1])


_REAL_FRAMES = replay.frames


def _few(*a, **k):
    return _REAL_FRAMES(*a, **dict(k, limit=5))


# ======================================================================== the fighter hooks
class FakeDetector:
    def __init__(self, source):
        self.source, self.state, self.ctx, self.events = source, 'idle', 30.0, []

    def poll(self, now):
        ev, self.events = self.events, []
        return [Activity(self.source, self.source, self.source, self.state, self.ctx, events=ev)]


class Slot(Isolated):
    def setUp(self):
        super().setUp()
        Ov.made = []
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.dets = {}

        def det(src, cfg):
            self.dets[src] = FakeDetector(src)
            return self.dets[src]
        self.shell = Shell()
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                               'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex'}, 'ts': self.t['wall']})
        self.f = minis.Fighter('a', dict(CFG, fighter_size=64), self.shell, mono=lambda: self.t['mono'], wall=lambda: self.t['wall'],
                               detector_for=det)
        self.f.setup()

    def go(self, secs, dt=0.05):
        for _ in range(int(secs / dt)):
            self.t['mono'] += dt
            self.t['wall'] += dt
            self.f.step()

    def test_task_done_flag_drawn_then_cleared_by_hovering(self):
        self.go(1.5)
        self.dets['claude'].events = ['finished']
        self.go(1.5)
        self.assertTrue(self.f.ux.sig.flag)
        v = self.f.ux.decorate(self.f.brain.view(self.t['mono']), self.t['mono'])
        self.assertTrue(any(o[0] is SG.flag_image(0) or o[0] is SG.flag_image(1) for o in v['fx']))
        r = self.f.ux.fighter_rect()
        self.shell.cursor = (int((r[0] + r[2]) / 2), int((r[1] + r[3]) / 2))
        self.go(1.0)
        self.assertFalse(self.f.ux.sig.flag)
        cards = titles('minis-a-card')
        self.assertEqual(len(cards), 1)                                     # and the hover card came up
        self.assertTrue(cards[0].visible)
        self.assertFalse(cards[0].on_hittest(3, 3))                         # never in the way of a click
        self.shell.cursor = (5, 5)
        self.go(0.6)
        self.assertFalse(cards[0].visible)

    def test_card_info_is_numbers_and_names(self):
        self.go(1.5)
        info = self.f.ux.card_info(self.t['wall'])
        self.assertEqual(info['name'], 'Claude')
        self.assertEqual(info['opponent'], 'Codex')
        self.assertEqual(info['record'], (0, 0))
        allowed = {'name', 'accent', 'state', 'since_s', 'ctx', 'plan_pct', 'plan_label', 'resets_in', 'waiting_s', 'dormant', 'bot',
                   'process', 'flag', 'record', 'opponent', 'h2h', 'rival_in', 'rival_kind'}
        self.assertLessEqual(set(info), allowed)

    def test_rival_countdown_goes_on_the_bus_and_on_the_sleeping_plate(self):
        self.go(1.5)
        b = self.f.brain
        self.f.partner = {'state': 'sleeping', 'x': 600, 'mode': 'home', 'ts': self.t['wall']}
        b.next_rival = self.t['mono'] + 360
        pub = self.f.ux.publish_extra({'state': 'idle'}, self.t['wall'])
        self.assertEqual((pub['rival_in'], pub['rival_kind']), (360, 'match'))
        self.f.ux.state = 'sleeping'
        self.f.partner = {'state': 'idle', 'rival_in': 360, 'rival_kind': 'match', 'ts': self.t['wall'] - 10}
        left, kind = self.f.ux.rival_left(self.t['wall'])
        self.assertAlmostEqual(left, 350, delta=1)
        from minis_core import render
        base = render.plate(b.atlas, Snapshot('claude', 'sleeping'), 0.0, name='Claude')
        im = self.f.ux.plate_image(base, self.t['wall'])
        self.assertNotEqual(im.tobytes(), base.tobytes())                   # the second line now reads the countdown
        self.assertEqual(self.f.ux.plate_key(self.t['mono'], self.t['wall'])[0], '6 min')

    def test_a_finished_match_is_kept_for_replays_and_the_book(self):
        self.go(1.0)
        b = self.f.brain
        from minis_core import brain as B
        tl, t_end, _ = B.make_timeline('match', PLAN, b.atlases, b.fx)
        b.script = dict(kind='match', plan=PLAN, tl=[], t_end=t_end, projs=[])
        b.last_match = B.make_timeline.last_summary
        self.f._record('claude', 'codex')
        e = replay.last()
        self.assertEqual(e['programs'], {'a': 'claude', 'b': 'codex'})
        self.assertEqual(e['labels'], {'a': 'Claude', 'b': 'Codex'})
        seen = collection.read()
        for pc in e['stats']['pieces']:
            self.assertIn('p:' + pc, seen.get('claude', {}))
        self.assertEqual(sum(records.for_program(records.read(), 'claude')) + sum(records.for_program(records.read(), 'codex')), 2)

    def test_signals_switch_off(self):
        ux.set_switch('signals', False)
        self.go(2.5)
        self.dets['claude'].events = ['finished']
        self.go(1.0)
        self.assertFalse(self.f.ux.sig.flag)


# ======================================================================== commands
class Commands(Isolated):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(minis, 'running', lambda role: False):
            rc = minis.main(list(argv))
        return rc, out.getvalue()

    def test_settings_list_names_every_row_and_its_command(self):
        with mock.patch.object(minis, 'ux_actions', lambda: dict(restart=None, startup=lambda: FakeStartup('on'))):
            rc, out = self.run_cli('settings', 'list')
        self.assertEqual(rc, 0)
        for r in S.rows():
            self.assertIn(r['label'], out)
            self.assertIn(r['cli'], out)
        self.assertIn('Desktop weapons', out)

    def test_settings_set_and_switches(self):
        with mock.patch.object(minis, 'ux_actions', lambda: dict(restart=None, startup=lambda: FakeStartup('off'))):
            rc, out = self.run_cli('settings', 'set', 'winners', 'random')
        self.assertEqual((rc, control.winners()), (0, 'random'))
        self.run_cli('results', 'off')
        self.assertFalse(ux.switch('results'))
        self.run_cli('cards', 'off')
        self.assertFalse(ux.switch('cards'))

    def test_zone_and_guide_commands(self):
        p = self.data / 'minis.json'
        with mock.patch.object(ux, 'settings_path', lambda: p), mock.patch.object(minis, 'load_config', lambda: dict(CFG)):
            rc, out = self.run_cli('zone', '100', '200')
            self.assertEqual(rc, 2)                                         # too narrow
            rc, out = self.run_cli('zone', '100', '1000')
            self.assertEqual(json.loads(p.read_text())['zone'], [100, 1000])
            rc, out = self.run_cli('zone', 'auto')
            self.assertEqual(json.loads(p.read_text())['zone'], 'auto')
        ux.set_first_run_done(True)
        self.run_cli('guide', '--reset')
        self.assertFalse(ux.first_run_done())
        rc, out = self.run_cli('guide')
        self.assertEqual(rc, 1)
        self.assertIn('not running', out)

    def test_replay_code_and_gif_offline(self):
        rc, out = self.run_cli('replay', 'code')
        self.assertEqual(rc, 1)
        _, s = replay.summarize(PLAN)
        e = replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'}, {'a': 'Claude', 'b': 'Codex'})
        rc, out = self.run_cli('replay', 'code')
        self.assertIn(e['code'], out)
        dst = Path(tempfile.mkdtemp()) / 'fight.gif'
        with mock.patch.object(replay, 'frames', _few):
            rc, out = self.run_cli('replay', e['code'], '--gif', str(dst), '--final')
        self.assertEqual(rc, 0)
        self.assertTrue(dst.exists())
        rc, out = self.run_cli('replay', 'TF2-claude-codex-zzzz')
        self.assertEqual(rc, 2)

    def test_book_list(self):
        collection.merge({'claude': {'m:jab': 1.0}})
        rc, out = self.run_cli('book', 'list', '--fighter', 'claude')
        self.assertEqual(rc, 0)
        self.assertIn('Claude', out)
        self.assertIn('  1 /', out)

    def test_startup_status(self):
        with mock.patch.object(minis, 'ux_actions', lambda: dict(restart=None, startup=lambda: FakeStartup('other'))):
            rc, out = self.run_cli('startup', 'status')
        self.assertIn('another copy', out)


# ======================================================================== text quality (regressions)
def max_gap_inside(im, ink_min=60):
    """The widest run of empty columns between a word's first and last inked column (RGBA on a dark ground)."""
    w, h = im.size
    px = im.load()
    cols = [any(px[x, y][0] > ink_min for y in range(h)) for x in range(w)]
    xs = [x for x, c in enumerate(cols) if c]
    run = best = 0
    for x in range(xs[0], xs[-1] + 1):
        run = 0 if cols[x] else run + 1
        best = max(best, run)
    return best


class TextQuality(unittest.TestCase):
    WORDS = ('mouse', 'minis', 'Claude', 'arena', 'settings', 'waiting', 'Codex', 'fighter', 'context', 'restart', 'weapons',
             'Healthier', 'Settings', 'rival', 'match')

    def word(self, w, size, bold, k=1):
        from minis_core import render
        im, d = render.canvas(160, 24, k)
        d.rectangle([0, 0, 159, 23], fill=(18, 18, 22, 255))
        render.text(d, (4, 4), w, (230, 230, 240), size, bold)
        if k > 1:
            im = im.resize((160, 24), Image.BOX)
        return im

    def test_no_holes_inside_words(self):
        """FreeType's monochrome hinting left 2-4 px holes inside 9-10 px words ("m inis", "C laude"); no gap over 1 px now."""
        for size in (8, 9, 10):
            for bold in (False, True):
                for w in self.WORDS:
                    self.assertLessEqual(max_gap_inside(self.word(w, size, bold)), 1, f'{w!r} {size}px bold={bold}')
        for w in self.WORDS:                                                 # titles / names at 11 px bold
            self.assertLessEqual(max_gap_inside(self.word(w, 11, True)), 1, w)

    def test_two_x_and_the_old_mono_path_for_contrast(self):
        from minis_core import render
        from PIL import ImageDraw
        for w in self.WORDS:
            self.assertLessEqual(max_gap_inside(self.word(w, 9, False, k=2)), 1, w)
        im = Image.new('RGBA', (160, 24), (18, 18, 22, 255))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        d.text((4, 4), 'minis', fill=(230, 230, 240), font=render.os_font(9, False))
        if sys.platform == 'win32':                                         # Segoe UI, monochrome-hinted: what the fix is about
            self.assertGreaterEqual(max_gap_inside(im), 2)

    def test_the_pixel_font_needs_no_os_font(self):
        """The UI text is the shipped pixel font: with every OS font refusing to load, a word renders pixel for pixel the same."""
        from PIL import ImageFont
        from minis_core import pixelfont
        before = self.word('Claude Code', 10, True).tobytes()
        render._font_cache.clear()
        pixelfont.PixelFont._mask_cache.clear()
        pixelfont.PixelFont._glyph_cache.clear()
        with mock.patch.object(ImageFont, 'truetype', side_effect=OSError('no fonts here')):
            render._font_cache.clear()
            self.assertEqual(self.word('Claude Code', 10, True).tobytes(), before)
            self.assertEqual(self.word('Claude Code', 10, True, k=2).tobytes(), self.word('Claude Code', 10, True, k=2).tobytes())
            f = render.font(9, False)
            self.assertTrue(render.is_pixel(f))
            self.assertEqual(f.getlength('minis'), pixelfont.for_size(9, False).getlength('minis'))
        render._font_cache.clear()
        self.assertEqual(self.word('Claude Code', 10, True).tobytes(), before)

    def test_every_glyph_is_drawn_and_unknown_characters_fall_back(self):
        from minis_core import pixelfont
        f = pixelfont.for_size(9, False)
        for code in range(33, 127):
            self.assertGreater(f.mask(chr(code)).getbbox()[2], 0, chr(code))
        self.assertEqual(pixelfont.normalize('a…b — c×d · 中'), 'a...b - cxd · ?')
        self.assertEqual(f.getlength('ab'), f.getlength('a') + f.getlength('b') + pixelfont.SPACING)
        bold = pixelfont.for_size(9, True)
        self.assertGreater(bold.getlength('Claude'), f.getlength('Claude'))
        self.assertEqual(pixelfont.for_size(8, True).getlength('Barbarian'), f.getlength('Barbarian'))   # 8 px: never emboldened
        self.assertEqual(pixelfont.for_size(11, True).height, f.height + 1)                              # tall: one row more

    def test_text_is_crisp_not_washed_out(self):
        im = self.word('mouse', 9, False)
        reds = sorted(px[0] for px in (im.getpixel((x, y)) for x in range(160) for y in range(24)) if px[0] > 60)
        self.assertGreaterEqual(reds[-1], 225)                               # stems reach full ink


class NoTruncation(Isolated):
    def test_settings_help_lines_wrap_whole(self):
        from minis_core.render import font, wrap
        be = S.Backend(dict(CFG))
        for is_mac in (False, True):
            m = S.Model(be, now=0.0, is_mac=is_mac)
            for i, r in enumerate(m.rows):
                y0, y1 = m.ys[i]
                for h in m.help_variants(r):
                    lines = wrap(h, m.help_w)
                    self.assertEqual(' '.join(lines), h)                       # every word kept
                    self.assertTrue(all(font(9, False).getlength(ln) <= m.help_w for ln in lines), h)
                    self.assertLessEqual(S.LINE1_H + 11 * len(lines), y1 - y0)  # and room for every line
            self.assertGreater(m.close_rect()[1], m.foot_y + 22)              # the footer's two lines clear the Close button

    def test_book_captions_and_descriptions_fit(self):
        from minis_core.render import font, wrap
        from minis_core.atlas import Library
        from minis_core import lineup
        lib = Library()
        b = collection.Book(lineup.characters(), {}, lib)
        for c in lineup.characters():
            for lst in collection.entries(lib[c['id']]).values():
                for e in lst:
                    names = wrap(e['name'], collection.CW - 4, 8, True)
                    self.assertLessEqual(len(names), 2, e['name'])
                    self.assertTrue(all(font(8, True).getlength(n) <= collection.CW - 4 for n in names), e['name'])
                    self.assertLessEqual(font(9, False).getlength(e['type']), collection.CW - 2, e['type'])
                    self.assertLessEqual(len(wrap(f"{e['name']}: {e['desc']}", b.W - 2 * collection.PAD - 4)), 3, e['name'])

    def test_results_strip_toast_and_cards_grow_instead_of_cutting(self):
        from minis_core.render import font
        e = dict(id='m', ts=0, plan=dict(PLAN), labels={'a': 'LM Studio', 'b': 'Perplexity'}, winner='b', loser='a',
                 wins={'a': 1, 'b': 2}, stats=dict(hits=123, best_combo=12, ultimate=True))
        head, rest = R.headline(e)
        self.assertGreaterEqual(R.width(e), font(9, False).getlength(rest) + 2 * R.PORTRAIT)
        t = ux_runtime.toast_image('saved taskbar-fighters-claude-vs-codex-20261021-131347.gif (its folder opens) ' * 3)
        self.assertGreater(t.height, 20)                                     # wrapped onto more lines
        info = dict(name='Claude Code', state='waiting', since_s=5, waiting_s=45, ctx=50, record=(1, 2), opponent='Perplexity',
                    h2h=(3, 4), plan_pct=12.0, plan_label='wk', resets_in='2d 4h')
        self.assertEqual(HC.render(info).width, HC.W)
        g = G.Guide('guide', (40, 940), {'fighter': 520, 'plates': (40, 300), 'board': (746, 936)},
                    names={'a': 'A very long program name indeed'}, now=0.0)
        self.assertIn('A very long program name indeed.', ' '.join(g.body_lines()))


class CodexReview(Isolated):
    """The second Codex review of this branch: a crafted fight code must not escape the exports folder, two writers of one
    JSON file must not lose each other's entries, and pack ids with hyphens round-trip through a fight code."""

    def test_a_crafted_code_cannot_name_a_path_and_the_default_gif_stays_in_exports(self):
        payload = replay.encode(replay.clean_plan(PLAN)).split('-')[3]
        for bad in ('..', 'a/b', 'a\\b', '..\\..\\x', 'A', 'x' * 41, '', 'c.d.e!'):
            with self.assertRaises(replay.CodeError, msg=bad):
                replay.decode(f'TF2-{bad}-codex-{payload}')
        with mock.patch.object(replay, 'ID_RE', mock.Mock(match=lambda s: True)):   # even if the allowlist were bypassed ...
            plan, _, _ = replay.decode(f'TF2-..\\..\\evil-codex-{payload}')
        name = replay.gif_name(plan)
        self.assertNotIn('\\', name)
        self.assertNotIn('/', name)
        self.assertNotIn('..', name)
        self.assertTrue(replay.inside_exports(replay.exports_dir() / name))        # ... the file name is sanitized ...
        self.assertFalse(replay.inside_exports(replay.exports_dir() / '..' / 'x.gif'))
        self.assertFalse(replay.inside_exports(Path(tempfile.gettempdir()) / 'x.gif'))
        out = io.StringIO()
        with mock.patch.object(replay, 'gif_name', lambda *a, **k: '..\\..\\escape.gif'), redirect_stdout(out), \
                mock.patch.object(minis, 'running', lambda role: False):
            _, s = replay.summarize(PLAN)
            replay.store(PLAN, s, {'a': 'claude', 'b': 'codex'})
            rc = minis.main(['replay', '--gif'])                                    # ... and the CLI checks containment
        self.assertEqual(rc, 1)
        self.assertIn('refused', out.getvalue())
        self.assertFalse((self.data / 'escape.gif').exists())

    def test_pack_ids_with_hyphens_round_trip(self):
        plan = dict(PLAN, chars={'a': 'pack-shadow-ronin', 'b': 'codex'})
        code = replay.encode(replay.clean_plan(plan))
        self.assertTrue(code.startswith('TF2-pack.shadow.ronin-codex-'))
        self.assertEqual(code.count('-'), 3)
        p2, _, _ = replay.decode(code)
        self.assertEqual(p2['chars'], {'a': 'pack-shadow-ronin', 'b': 'codex'})
        with self.assertRaises(ValueError):
            replay.encode(replay.clean_plan(dict(PLAN, chars={'a': 'Bad Id', 'b': 'codex'})))
        with self.assertRaises(replay.CodeError):
            replay.decode('TF1-claude-codex-' + code.split('-')[3])              # an earlier format says so, never guesses

    def test_two_processes_merging_the_move_book_lose_nothing(self):
        import threading
        p = self.data / 'collection.json'
        collection.merge({'claude': {'m:jab': 1.0}}, p)
        started, go = threading.Event(), threading.Event()

        def slow_writer():                                                       # reads the file, then waits inside the lock
            collection.merge({'claude': {'m:cross': 2.0}}, p, _after_read=lambda: (started.set(), go.wait(5)))
        t = threading.Thread(target=slow_writer)
        t.start()
        started.wait(5)
        other = threading.Thread(target=lambda: collection.merge({'codex': {'m:spiral_orb': 3.0}}, p))
        other.start()                                                            # the second writer must wait for the lock
        other.join(0.3)
        self.assertTrue(other.is_alive())
        go.set()
        t.join(5)
        other.join(5)
        seen = collection.read(p)
        self.assertEqual(set(seen['claude']), {'m:jab', 'm:cross'})
        self.assertEqual(set(seen['codex']), {'m:spiral_orb'})                     # nothing lost, no manual retry
        self.assertFalse(p.with_name('collection.json.lock').exists())

    def test_two_processes_updating_ux_json_keep_both_changes(self):
        import threading
        p = self.data / 'ux.json'
        started, go = threading.Event(), threading.Event()
        t = threading.Thread(target=lambda: ux.update(p, _after_read=lambda: (started.set(), go.wait(5)), first_run_done=True))
        t.start()
        started.wait(5)
        other = threading.Thread(target=lambda: ux.set_switch('results', False, p))
        other.start()
        other.join(0.3)
        self.assertTrue(other.is_alive())
        go.set()
        t.join(5)
        other.join(5)
        self.assertTrue(ux.first_run_done(p))
        self.assertFalse(ux.switch('results', p))
        self.assertFalse(p.with_name('ux.json.lock').exists())

    def test_a_stale_lock_is_reclaimed_and_a_held_one_times_out(self):
        from minis_core import filelock
        p = self.data / 'x.json'
        lock = p.with_name('x.json.lock')
        lock.write_text('')
        old = time.time() - filelock.STALE_S - 1
        os.utime(lock, (old, old))
        with filelock.locked(p, timeout=0.2) as ok:
            self.assertTrue(ok)                                                   # a dead holder's lock is taken over
        lock.write_text('')
        with filelock.locked(p, timeout=0.2) as ok:
            self.assertFalse(ok)                                                  # a live one is not
        lock.unlink()
        self.assertFalse(collection.Tracker().flush(0))                           # nothing to write: no lock is needed


class Overlay(Isolated):
    def test_the_data_folder_minis_json_overrides_the_zone(self):
        cfg = dict(CFG, zone=[10, 700])
        self.assertEqual(ux.apply_overlay(dict(cfg))['zone'], [10, 700])
        ux.write_setting('zone', [100, 1000])
        self.assertEqual(ux.settings_path(), self.data / 'minis.json')
        self.assertEqual(ux.apply_overlay(dict(cfg))['zone'], [100, 1000])
        ux.write_setting('zone', 'auto')
        self.assertEqual(ux.apply_overlay(dict(cfg))['zone'], list(CFG['zone']))
        ux.write_setting('zone', [5, 1])                                     # nonsense is ignored
        self.assertEqual(ux.apply_overlay(dict(cfg))['zone'], [10, 700])


if __name__ == '__main__':
    unittest.main()
