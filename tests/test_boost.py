"""V9: the task-finished boost reaches the arena process.  The slot whose agent went working -> done publishes a short-lived
marker on its bus file; the arena reads both bus files and opens its next exchange with that fighter's signature super.
Real bus files in a temp data dir, real Brains, a real headless Arena; no window, no screen."""
import sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
from minis_core import arena as AR, brain as BR, bus  # noqa: E402
from test_arena import FX, LIB, MON, FLOOR, WINS, run  # noqa: E402
from test_core import pair, snap  # noqa: E402


def finished_brain(now=1000.0):
    a, b = pair()
    a.tick(now, snap(), None)
    a.tick(now + 0.1, snap('done', 40.0, ['finished']), None)       # working -> done: the telemetry's 'finished' event
    return a


def real_arena(seed=3):
    st = AR.Stage(MON, WINS, floor_y=FLOOR)
    ar = AR.Arena(st, {'a': LIB['claude'], 'b': LIB['codex']}, FX, seed=seed, now=0.0, record=lambda *a, **k: None,
                  cfg=dict(CFG), forge=False)                           # a cfg: the real-process path (reads the bus)
    ar.flashes = True
    return ar


def first_attack(ar):
    return [bt for bt in ar.exchange['beats'] if bt['kind'] in ('strike', 'super', 'special', 'ultimate', 'counter')][0]


class BoostMarker(unittest.TestCase):
    def test_a_finished_task_publishes_a_marker_that_expires(self):
        a = finished_brain()
        m = a.publish()['boost']
        self.assertIsInstance(m, dict)
        self.assertTrue(m['id'])
        self.assertAlmostEqual(m['left'], BR.ARENA_BOOST_S, delta=0.2)
        self.assertEqual(set(m), {'id', 'left'})                         # an opaque id and a number: no content
        a.tick(1000.1 + BR.ARENA_BOOST_S + 0.5, snap('done', 40.0), None)
        self.assertIsNone(a.publish()['boost'])

    def test_no_marker_without_a_finish(self):
        a, _ = pair()
        a.tick(1000.0, snap('working', 40.0), None)
        self.assertIsNone(a.publish()['boost'])


class ArenaReadsTheBus(Isolated):
    def test_marker_on_the_bus_opens_the_next_exchange_with_the_signature_super(self):
        wall = time.time()
        b = finished_brain()
        b.slot = 'b'
        self.assertTrue(bus.write('b', b.publish(), now=wall))          # what slot b's process writes
        ar = real_arena()
        run(ar, until_phase='fight')
        ar.k_round = 3                                                   # mid-round: the taskbar's k < 2 rule does not apply
        ar._boost_read = -1e9
        ar._boost_poll(ar.last_now)
        self.assertEqual(ar.boost, ['b'])
        self.assertTrue(any(e[0] == 'boost' for e in ar.events))
        ar._new_exchange(ar.last_now)
        first = first_attack(ar)
        self.assertEqual((ar.exchange['att'], first['kind'], first['outcome']), ('b', 'super', 'hit'))
        self.assertEqual(ar.boost, [])

    def test_each_marker_boosts_once(self):
        wall = time.time()
        a = finished_brain()
        bus.write('a', a.publish(), now=wall)
        ar = real_arena()
        run(ar, until_phase='fight')
        for _ in range(3):
            ar._boost_read = -1e9
            ar._boost_poll(ar.last_now)
        self.assertEqual(ar.boost, ['a'])
        ar._new_exchange(ar.last_now)
        ar._boost_read = -1e9
        ar._boost_poll(ar.last_now)
        self.assertEqual(ar.boost, [])                                   # the same finish is never a second super

    def test_an_expired_marker_is_ignored(self):
        a = finished_brain()
        p = a.publish()
        bus.write('a', p, now=time.time() - p['boost']['left'] - 1.0)    # written long enough ago that it has run out
        ar = real_arena()
        run(ar, until_phase='fight')
        ar._boost_poll(ar.last_now, buses={'a': bus.read('a', stale_s=1e9, now=time.time()), 'b': None})
        self.assertEqual(ar.boost, [])

    def test_the_live_arena_loop_polls_the_bus(self):
        a = finished_brain()
        bus.write('a', a.publish(), now=time.time())
        ar = real_arena()
        run(ar, until_phase='fight')
        self.assertIn('a', {s for s, _ in ar.boost_seen})                # tick() itself read it, no manual poll


class BareArenaNeverReadsTheBus(Isolated):
    def test_without_a_cfg_no_bus_file_is_read(self):
        a = finished_brain()
        bus.write('a', a.publish(), now=time.time())
        st = AR.Stage(MON, WINS, floor_y=FLOOR)
        ar = AR.Arena(st, {'a': LIB['claude'], 'b': LIB['codex']}, FX, seed=3, now=0.0, record=lambda *a, **k: None)
        ar.flashes = True
        run(ar, until_phase='fight')
        self.assertEqual(ar.boost, [])
        self.assertEqual(ar.boost_seen, set())


if __name__ == '__main__':
    unittest.main()
