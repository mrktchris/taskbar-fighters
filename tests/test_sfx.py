"""V9 optional sound effects: the generated .wav files, the player's rules (off by default, rate-limited, quiet, async),
who plays (slot a hears the whole shared fight once; slot b never plays) and the arena's own sounds.  No audio device is
touched: every backend here is a recorder."""
import os, random, struct, sys, tempfile, threading, unittest, wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
from minis_core import control, sfx, sim  # noqa: E402
from minis_core.atlas import Library  # noqa: E402
from minis_core.brain import LEFT, RIGHT, Brain  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'art'))
import build_sfx  # noqa: E402

LIB = Library()


def samples(path):
    with wave.open(str(path), 'rb') as w:
        meta = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        n = w.getnframes()
        return meta, struct.unpack('<%dh' % n, w.readframes(n))


class Rec:
    """A backend that records what it would have played."""

    def __init__(self, sync=True):
        self.paths = []
        self.ev = threading.Event()
        if sync:
            self.sync = True

    def __call__(self, path):
        self.paths.append(Path(path).stem)
        self.ev.set()


class Files(unittest.TestCase):
    def test_every_sound_is_built_short_quiet_mono_16bit(self):
        for name in sfx.NAMES:
            p = ROOT / 'assets' / 'sfx' / f'{name}.wav'
            self.assertTrue(p.is_file(), name)
            meta, s = samples(p)
            self.assertEqual(meta, (1, 2, build_sfx.RATE), name)
            self.assertLessEqual(len(s) / build_sfx.RATE, 1.0, name)
            peak = max(abs(v) for v in s) / 32767.0
            self.assertLessEqual(peak, 0.26, name)                   # about -12 dBFS: quiet
            self.assertGreater(peak, 0.1, name)
            self.assertLess(p.stat().st_size, 48_000, name)

    def test_build_is_deterministic_and_matches_the_committed_files(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            build_sfx.build(d1)
            build_sfx.build(d2)
            for name in sfx.NAMES:
                a = (Path(d1) / f'{name}.wav').read_bytes()
                self.assertEqual(a, (Path(d2) / f'{name}.wav').read_bytes(), name)
                _, new = samples(Path(d1) / f'{name}.wav')
                _, old = samples(ROOT / 'assets' / 'sfx' / f'{name}.wav')
                self.assertEqual(len(new), len(old), name)
                self.assertLessEqual(max(abs(x - y) for x, y in zip(new, old)), 2, name)   # a libm ULP may differ by OS

    def test_the_wheel_ships_the_sounds(self):
        # The packaging rules name the files; the CI job "package smoke test" builds the real wheel, asserts every
        # assets/sfx/*.wav is inside it and reads them back from an installed copy (.github/workflows/ci.yml).
        txt = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('**/*.wav', txt)
        self.assertIn('*.wav', (ROOT / 'MANIFEST.in').read_text(encoding='utf-8'))


class Switch(Isolated):
    def test_off_by_default_and_toggled_by_control_json(self):
        self.assertFalse(control.sound_on())
        self.assertTrue(control.set_sound(True))
        self.assertTrue(control.sound_on())
        control.set_sound(False)
        self.assertFalse(control.sound_on())

    def test_a_player_on_the_control_switch_stays_silent_until_turned_on(self):
        rec = Rec()
        p = sfx.Player(enabled=sfx.control_enabled(), backend=rec, clock=lambda: 10.0)
        self.assertFalse(p.play('hit_light'))
        control.set_sound(True)
        self.assertTrue(p.play('hit_light'))
        self.assertEqual(rec.paths, ['hit_light'])

    def test_the_cli_writes_the_switch(self):
        import minis
        self.assertEqual(minis.main(['sound', 'on']), 0)
        self.assertTrue(control.sound_on())
        self.assertEqual(minis.main(['sound', 'off']), 0)
        self.assertFalse(control.sound_on())

    def test_menus_carry_a_sound_checkmark(self):
        from minis_core import lineup
        from minis_win import tray
        items = tray.tray_menu({'sound': True})
        self.assertIn((tray.SOUND, 'Sound effects', {'checked': True}), items)
        items, _ = lineup.fighter_menu('a', {}, {}, {'sound': False}, [])
        self.assertIn((lineup.SOUND, 'Sound effects', {'checked': False}), items)
        import minis
        flags = minis.tray_flags(dict(CFG), None)
        self.assertFalse(flags['sound'])
        minis.tray_choice(tray.SOUND, flags, None)
        self.assertTrue(control.sound_on())


class PlayerRules(unittest.TestCase):
    def setUp(self):
        self.t = [100.0]
        self.rec = Rec()
        self.p = sfx.Player(enabled=lambda: True, backend=self.rec, clock=lambda: self.t[0])

    def test_rate_limited_per_kind_and_per_second(self):
        self.assertTrue(self.p.play('hit_light'))
        self.assertFalse(self.p.play('hit_light'))                  # same kind inside its gap
        self.t[0] += 0.1
        self.assertTrue(self.p.play('hit_light'))
        n = 0
        for i in range(40):
            self.t[0] += 0.02
            n += self.p.play(sfx.NAMES[i % len(sfx.NAMES)])
        self.assertLessEqual(n, sfx.MAX_PER_S + 1)

    def test_quiet_stale_and_unknown_are_silent(self):
        self.p.quiet = True
        self.assertFalse(self.p.play('bell'))
        self.p.quiet = False
        self.assertFalse(self.p.play('bell', t=self.t[0] - 1.0))     # a late event is dropped, never replayed
        self.assertFalse(self.p.play('meow'))
        self.assertTrue(self.p.play('bell', t=self.t[0] - 0.05))

    def test_async_backend_never_blocks_the_caller(self):
        gate = threading.Event()
        done = []

        def slow(path):
            gate.wait(2.0)
            done.append(Path(path).stem)
        p = sfx.Player(enabled=lambda: True, backend=slow, clock=lambda: 5.0)
        import time
        t0 = time.perf_counter()
        self.assertTrue(p.play('clash'))
        self.assertEqual(done, [])                                    # returned while the backend is still held: async
        self.assertLess(time.perf_counter() - t0, 1.0)                # far under the 2 s hold; a busy CI box took 83 ms to start the thread
        gate.set()
        for _ in range(200):
            if done:
                break
            time.sleep(0.01)
        self.assertEqual(done, ['clash'])

    def test_no_backend_under_tests(self):
        self.assertIsNone(sfx.default_backend())                    # MINIS_TESTING: never a real audio device


def bout(seed=2, with_b=False, secs=70.0):
    cfg = dict(CFG)
    br = {w: Brain(w, LIB[c], LIB, cfg, random.Random(seed + i), 1000.0, run=f's{w}', record=sim.no_record)
          for i, (w, c) in enumerate(((LEFT, 'claude'), (RIGHT, 'knight')))}
    clock = [1000.0]
    recs = {}
    for w, b in br.items():
        b.flashes = True
        if w == LEFT or with_b:
            recs[w] = Rec()
            b.sfx = sfx.Player(enabled=lambda: True, backend=recs[w], clock=lambda: clock[0])
    tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
    bus = {}
    br[LEFT].request_demo('match', 1000.0, wait_s=30)
    hits = []
    for i in range(int(secs * 15)):
        clock[0] = now = 1000.0 + i / 15.0
        sim.step(br, tele, now, bus)
    for w in br:
        hits += list(br[w].hit_log)
    return br, recs, hits


class WhoPlays(unittest.TestCase):
    def test_slot_a_hears_both_fighters_hits_and_the_rounds(self):
        br, recs, hits = bout()
        heard = recs[LEFT].paths
        self.assertTrue(any(br[w].hit_log for w in br))
        self.assertIn('whoosh', heard)
        self.assertTrue({'hit_light', 'hit_heavy', 'clash'} & set(heard))
        self.assertIn('bell', heard)
        # reactions on BOTH rows reach slot a's player: its own row (it was struck) and the ghost row (it struck)
        own = [n for t, n in br[LEFT].hit_log if n in sfx.ROW_SOUNDS]
        opp = [n for t, n in br[RIGHT].hit_log if n in sfx.ROW_SOUNDS]
        self.assertTrue(own and opp)
        self.assertGreaterEqual(len(heard), 0.5 * min(len(own) + len(opp), 40))

    def test_only_one_process_plays(self):
        br, recs, _ = bout()
        self.assertIsNone(br[RIGHT].sfx)                            # slot b never gets a player (minis.Fighter: slot a only)
        self.assertTrue(recs[LEFT].paths)


class ArenaSounds(Isolated):
    def test_the_arena_plays_its_own_events(self):
        from test_arena import FX, FLOOR, MON, WINS
        from minis_core import arena as AR
        hd = Library(hd=True)
        st = AR.Stage(MON, WINS, floor_y=FLOOR)
        ar = AR.Arena(st, {'a': hd['claude'], 'b': hd['codex']}, FX, seed=4, now=0.0, record=lambda *a, **k: None,
                      cfg=dict(CFG), forge=False)
        self.assertIsNotNone(ar.sfx)
        self.assertIsNone(ar.sfx.backend)                            # under tests: no audio device
        rec = Rec()
        ar.sfx.backend = rec
        control.set_sound(True)
        ar.flashes = True
        now = 0.0
        while ar.phase != 'done' and now < 120:
            now += 1 / 30.0
            ar.tick(now)
        self.assertIn('bell', rec.paths)
        self.assertTrue({'hit_light', 'hit_heavy'} & set(rec.paths))
        self.assertIn('ko', rec.paths)

    def test_paused_arena_is_silent(self):
        from test_arena import FX, FLOOR, MON, WINS
        from minis_core import arena as AR
        hd = Library(hd=True)
        st = AR.Stage(MON, WINS, floor_y=FLOOR)
        ar = AR.Arena(st, {'a': hd['claude'], 'b': hd['codex']}, FX, seed=4, now=0.0, record=lambda *a, **k: None,
                      cfg=dict(CFG), forge=False)
        rec = Rec()
        ar.sfx.backend = rec
        control.set_sound(True)
        ar.paused = True
        ar.tick(0.1)
        self.assertTrue(ar.sfx.quiet)
        self.assertFalse(ar.sfx.play('bell', 0.1, 0.1))


if __name__ == '__main__':
    unittest.main()
