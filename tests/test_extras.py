"""docs/COMPARISON.md items 1-4: reset countdown on the plate, loud `waiting?`, the 7-day sparkline, micro-interactions."""
import json, sys, unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
import minis  # noqa: E402
from minis_core import eyes, fx, history, render, scoreboard as SB, sim  # noqa: E402
from minis_core.atlas import Atlas, available  # noqa: E402
from minis_core.brain import LEFT, RIGHT  # noqa: E402
from minis_core.sources import Activity  # noqa: E402
from minis_core.telemetry import Snapshot  # noqa: E402
from test_minis import FakeShell, FakeDetector  # noqa: E402


class Plate(unittest.TestCase):
    def test_reset_countdown_sits_next_to_the_plan_figure(self):
        a = Atlas('codex')
        with_reset = Snapshot('codex', 'idle', 40.0, 12.0, 'wk', resets_in='2d 4h')
        without = Snapshot('codex', 'idle', 40.0, 12.0, 'wk')
        p1, p0 = render.plate(a, with_reset, 0.0), render.plate(a, without, 0.0)
        self.assertNotEqual(p1.tobytes(), p0.tobytes())
        self.assertEqual(p1.size, (render.PLATE_W, render.PLATE_H))
        # the label the plate chose contains the countdown (rendered through the same candidate list)
        from PIL import ImageDraw
        d = ImageDraw.Draw(Image.new('RGBA', (4, 4)))
        if sys.platform == 'win32':                     # Segoe UI metrics; other systems draw the plate with another font
            self.assertLessEqual(d.textlength('40% wk 12% · 2d 4h', font=render.font(9, False)), render.PLATE_W - 5 - (5 + 10 * 4 + 3) - 3 + 40)
        self.assertEqual(render.plate(a, Snapshot('codex', 'idle', 40.0, None, '', resets_in='2d 4h'), 0.0).tobytes(),
                         render.plate(a, Snapshot('codex', 'idle', 40.0), 0.0).tobytes())          # no plan figure: no countdown

    def test_retina_plate_and_scoreboard_are_2x_images_tagged_with_their_density(self):
        a = Atlas('claude')
        s = Snapshot('claude', 'working', 40.0, 12.0, 'wk', resets_in='2d 4h')
        p1, p2 = render.plate(a, s, 0.0), render.plate(a, s, 0.0, k=2)
        self.assertEqual(p2.size, (2 * render.PLATE_W, 2 * render.PLATE_H))
        self.assertEqual((p1.info.get('density'), p2.info.get('density')), (None, 2))
        self.assertGreater(p2.getpixel((render.PLATE_W, render.PLATE_H))[3], p1.getpixel((render.PLATE_W // 2, render.PLATE_H // 2))[3])
        st = {'names': {'a': 'Claude', 'b': 'Codex'}, 'records': {'a': (1, 0), 'b': (0, 1)}}
        b2 = SB.render(st, k=2)
        self.assertEqual((b2.size, b2.info.get('density')), ((2 * SB.W, 2 * SB.H), 2))
        self.assertIsNot(SB.render(st), b2)                                         # separate cache entries per density

    def test_waiting_is_loud_amber_border_and_word(self):
        a = Atlas('claude')
        w, i = render.plate(a, Snapshot('claude', 'waiting', 40.0), 0.0), render.plate(a, Snapshot('claude', 'idle', 40.0), 0.0)
        self.assertNotEqual(w.tobytes(), i.tobytes())
        self.assertEqual(w.getpixel((render.PLATE_W // 2, 0))[:3], render.AMBER)      # amber border
        self.assertNotEqual(i.getpixel((render.PLATE_W // 2, 0))[:3], render.AMBER)
        amber = sum(1 for x in range(render.PLATE_W) for y in range(2, 12) if w.getpixel((x, y))[:3] == render.AMBER)
        self.assertGreater(amber, 10)                                                  # the state word is amber too


class Waiting(unittest.TestCase):
    def test_waiting_fighter_wears_an_alert_effect_until_the_state_changes(self):
        cfg = dict(CFG, scoreboard=False, bout_min_s=999, bout_max_s=999, clash_min_s=999, clash_max_s=999)
        _, atl, brains = sim.make(1, cfg, 1000.0)
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'waiting', 30.0), (6, 'working', 30.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 20.0)])}
        bus = {}
        tags = []
        for i in range(120):
            now = 1000 + i / 10.0
            sim.step(brains, tele, now, bus)
            brains[LEFT].view(now)
            tags.append(sorted({x.tag for x in brains[LEFT].fxp.active}))
        self.assertEqual(tags[5], ['alert'])
        self.assertEqual(brains[LEFT].anim, 'work')
        self.assertEqual(tags[-1], [])
        self.assertTrue(fx.default().get('alert').loop)


class Spark(Isolated):
    def test_history_keeps_numbers_and_dates_only_and_feeds_the_sparkline(self):
        r = history.Recorder(every_s=60)
        day = 86400
        t0 = 1_800_000_000.0
        acts = [Activity('claude', 'Claude Code', 'claude', 'working', 41.0, 12.0, 'wk'), Activity('cursor', 'Cursor', 'cursor', 'idle', None)]
        self.assertTrue(r.record(acts, t0))
        self.assertFalse(r.record([Activity('claude', 'Claude Code', 'claude', 'working', 90.0)], t0 + 10))   # once a minute
        self.assertTrue(r.record([Activity('claude', 'Claude Code', 'claude', 'working', 90.0)], t0 + 70))
        self.assertTrue(r.record([Activity('claude', 'Claude Code', 'claude', 'idle', 10.0)], t0 + 3 * day))
        d = json.loads((self.data / 'history.json').read_text(encoding='utf-8'))
        row = d['days'][history.day_key(t0)]
        self.assertEqual((row['ctx_max'], row['plan_max'], row['samples']), (90.0, 12.0, 2))
        self.assertEqual(set(d), {'days'})
        text = json.dumps(d)
        for word in ('Claude', 'claude', 'cursor', 'Cursor', 'program', 'source'):
            self.assertNotIn(word, text)                                               # numbers and dates, nothing else
        self.assertEqual(history.last_days(7, t0 + 3 * day), [None, None, None, 90.0, None, None, 10.0])
        for i in range(20):
            r.record([Activity('claude', 'Claude Code', 'claude', 'idle', 5.0)], t0 + (4 + i) * day)
        self.assertLessEqual(len(history.read()['days']), history.KEEP_DAYS)
        base = dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (0, 0), 'b': (0, 0)}, mode='taskbar', arena=False, paused=False, hp=None,
                    wins={}, winners='decided')
        plain, spark = SB.render(base), SB.render(dict(base, spark=[None, 10, 50, 95, 70, None, 30]))
        self.assertNotEqual(plain.tobytes(), spark.tobytes())
        self.assertEqual(spark.getpixel((SB.SPARK_X + 3 * SB.SPARK_PITCH + 1, 20))[:3], render.RED)        # 95 % day is red
        self.assertEqual(spark.getpixel((SB.SPARK_X + 2 * SB.SPARK_PITCH + 1, 20))[:3], (150, 220, 150))     # 50 % day is green
        self.assertNotEqual(SB.signature(base), SB.signature(dict(base, spark=[1])))


class Micro(Isolated):
    def setUp(self):
        super().setUp()
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.shell = FakeShell()
        self.cursor = (2000, 1200)
        self.shift = False
        self.shell.cursor_pos = lambda: self.cursor
        self.shell.shift_down = lambda: self.shift
        self.f = minis.Fighter('a', dict(CFG, fighter_size=64), self.shell, mono=lambda: self.t['mono'], wall=lambda: self.t['wall'],
                               detector_for=lambda src, cfg: FakeDetector(src))      # 64 px geometry (test_fighter_size covers 96 / 128)
        self.f.setup()
        self.go(0.5)

    def go(self, secs, dt=0.05):
        for _ in range(int(secs / dt)):
            self.t['mono'] += dt
            self.t['wall'] += dt
            self.f.step()

    def test_pupils_follow_the_cursor_only_while_idle(self):
        b = self.f.brain
        self.go(0.3)
        self.assertEqual(b.eye, (1, -1))                                                # cursor far right, above
        self.cursor = (0, 0)
        self.go(0.3)
        self.assertEqual(b.eye, (-1, -1))
        self.cursor = (int(b.x), 1412)
        self.go(0.3)
        self.assertEqual(b.eye, (0, 0))                                                 # dead zone: straight ahead
        self.cursor = (0, 0)
        b.play('jab', self.t['mono'], loop=False)
        self.go(0.25)
        self.assertEqual(b.eye, (0, 0))                                                 # not while a move plays
        found = 0
        found_moving = False
        for ch in available():
            a = Atlas(ch)
            pts = eyes.eye_pixels(a, 'idle', 0, 1)
            self.assertLessEqual(len(pts), 6, (ch, pts))
            fr = a.frame_image('idle', 0, 1)
            if not pts:                                                                 # a dark outfit hides the eye: left alone
                self.assertIs(eyes.shift_eyes(fr, pts, 1, 0), fr)
                continue
            found += 1
            bb = fr.getbbox()
            self.assertTrue(all(bb[1] <= y < bb[1] + (bb[3] - bb[1]) * 0.3 for x, y in pts), ch)
            moved = eyes.shift_eyes(fr, pts, 1, 0)
            diff = sum(1 for x in range(fr.width) for y in range(fr.height) if moved.getpixel((x, y)) != fr.getpixel((x, y)))
            self.assertLessEqual(diff, 2 * len(pts), (ch, diff))                       # a uniform visor band (Cursor, V5 art) shifts invisibly: 0 is fine
            if diff:
                found_moving = True
            self.assertIs(eyes.shift_eyes(fr, pts, 0, 0), fr)
        self.assertGreaterEqual(found, 4, 'eyes found for too few characters')
        self.assertTrue(found_moving, 'no character has pupils that visibly move')

    def test_a_new_atlas_never_reads_a_freed_atlas_s_cached_eyes(self):
        """The eye cache was keyed by id(atlas) alone; a freed atlas's id is reused by the next one, which then got the
        old character's eye pixels (the macOS py3.12 flake above: 'oni' with another fighter's eyes).  Simulate the reuse
        exactly: an entry under the new atlas's id that was made for a different atlas must not be returned."""
        old, new = Atlas('claude'), Atlas('oni')
        want = eyes.find_eye(new.frame_image('idle', 0, 1), 1, new.res)
        stale = eyes.find_eye(old.frame_image('idle', 0, 1), 1, old.res)
        self.assertNotEqual(want, stale)                                                # (otherwise the check proves nothing)
        eyes._cache[(id(new), 'idle', 0, True)] = (old, stale)                           # what id reuse leaves behind
        self.assertEqual(eyes.eye_pixels(new, 'idle', 0, 1), want)
        self.assertEqual(eyes.eye_pixels(new, 'idle', 0, 1), want)                      # and the corrected entry is kept

    def test_fast_drag_makes_it_dizzy_and_shift_drag_throws(self):
        b, ov = self.f.brain, self.f.ov
        mx = int(b.x - ov.x / ov.scale)
        self.f.on_event('down', mx, 30)
        for k in range(1, 6):
            self.t['mono'] += 0.02
            self.f.on_event('move', mx + 20 * k, 30)                                    # 1000 px/s
        self.f.on_event('up', -1, -1)
        self.assertEqual(b.anim, 'dizzy')
        self.go(2.0)
        self.assertNotEqual(b.anim, 'dizzy')
        x0 = b.x
        self.shift = True
        mx = int(b.x - ov.x / ov.scale)
        self.f.on_event('down', mx, 30)
        for k in range(1, 4):
            self.t['mono'] += 0.05
            self.f.on_event('move', mx - 15 * k, 30)                                    # -300 px/s, to the left
        self.f.on_event('up', -1, -1)
        self.assertIsNotNone(b.throw_state)
        self.assertEqual(b.anim, 'jump')
        self.go(0.7)
        self.assertIsNone(b.throw_state)
        self.assertLess(b.x, x0)                                                        # flew left ...
        self.assertGreaterEqual(b.x, b.home[0])                                         # ... but stayed in its own half
        self.assertEqual(b.anim, 'dizzy')
        self.go(1.5)
        self.assertNotEqual(b.anim, 'dizzy')
        slow = b.x
        self.shift = False
        self.f.on_event('down', int(b.x - ov.x / ov.scale), 30)
        self.t['mono'] += 0.5
        self.f.on_event('move', int(b.x - ov.x / ov.scale) + 10, 30)                   # a slow drag: no dizzy, no throw
        self.f.on_event('up', -1, -1)
        self.assertNotEqual(b.anim, 'dizzy')
        self.assertIsNone(b.throw_state)


if __name__ == '__main__':
    unittest.main()
