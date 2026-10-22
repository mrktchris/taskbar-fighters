"""V9 platform-fighter frame data (minis_core/framedata.py, docs/ANIMATION-NOTES.md section 12): the formulas, and that the
taskbar timeline and the arena really use them - hitlag freezes both fighters for the same time, hitstun grows with
knockback, later hits in a round launch further, big hits tumble along a real arc and end in a tech or a missed tech."""
import random, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG  # noqa: E402,F401
from minis_core import framedata as F, fx, rounds  # noqa: E402
from minis_core.atlas import Library  # noqa: E402

LIB = Library()
FX = fx.default()


def plan(seed, c1='claude', c2='knight'):
    return dict(kind='match', left='a', right='b', pos={'a': 380, 'b': 412}, t0=1000.0, seed=seed, chars={'a': c1, 'b': c2},
                mode='decided', scores={'a': 100, 'b': 100}, span=75)


def bout_of(seed, c1='claude', c2='knight'):
    """make_match, keeping the Bout (its fd_log) for inspection."""
    made = []
    real = rounds.Bout

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)
    rounds.Bout = Spy
    try:
        tl, t_end, s = rounds.make_match(plan(seed, c1, c2), {c1: LIB[c1], c2: LIB[c2]}, FX)
    finally:
        rounds.Bout = real
    return tl, s, made[0]


class Formulas(unittest.TestCase):
    def test_hitlag(self):
        self.assertEqual(F.hitlag_frames(15), 8)                  # floor(15 / 3 + 3)
        self.assertEqual(F.hitlag_frames(0), 0)                   # no damage, no freeze
        self.assertEqual(F.hitlag_frames(500), F.HITLAG_CAP)
        self.assertAlmostEqual(F.hitlag_ms(15), 8 * 1000 / 60)
        prev = 0
        for d in range(0, 80):
            f = F.hitlag_frames(d)
            self.assertGreaterEqual(f, prev)
            prev = f

    def test_knockback_grows_with_percent_and_damage_and_falls_with_weight(self):
        for d in (4, 9, 18):
            kbs = [F.knockback(p, d) for p in range(0, 150, 5)]
            self.assertEqual(kbs, sorted(kbs))
            self.assertLess(kbs[0], kbs[-1])
        self.assertLess(F.knockback(50, 9), F.knockback(50, 18))
        self.assertGreater(F.knockback(50, 9, weight=80), F.knockback(50, 9, weight=120))

    def test_hitstun_is_proportional_to_knockback(self):
        for kb in (10, 25, 50, 100, 200):
            self.assertEqual(F.hitstun_frames(kb), int(kb * 0.4))
        self.assertEqual(F.hitstun_frames(100), 40)

    def test_launch_decays_and_tumbles_above_the_line(self):
        self.assertAlmostEqual(F.launch_speed(100), 3.0)
        self.assertGreater(F.launch_distance(120), F.launch_distance(60))
        self.assertFalse(F.tumbles(79.9))
        self.assertTrue(F.tumbles(80))
        keys, air, px = F.tumble_arc(140, 45)
        self.assertEqual(keys[0], [0, 0])
        self.assertLessEqual(max(k[1] for k in keys), F.TASKBAR_LIFT_MAX)
        self.assertGreater(air, 100)
        self.assertLessEqual(px, F.TASKBAR_KNOCK_MAX)

    def test_taskbar_knockback_is_monotonic_and_bounded(self):
        px = [F.taskbar_knock_px(kb) for kb in range(0, 600, 10)]
        self.assertEqual(px, sorted(px))
        self.assertLessEqual(px[-1], F.TASKBAR_KNOCK_MAX)

    def test_shieldstun_and_pushback(self):
        self.assertEqual(F.shieldstun_frames(13), 7)              # 13 * 0.45 + 1.99
        self.assertGreater(F.shield_push_px(18), F.shield_push_px(6))

    def test_di_leans_at_most_18_degrees(self):
        r = random.Random(3)
        for _ in range(500):
            self.assertLessEqual(abs(F.di(45.0, r) - 45.0), F.DI_MAX_DEG)

    def test_move_frames_come_from_the_art(self):
        a = LIB['claude']
        for move in ('jab', 'cross', 'roundhouse', 'iai_slash'):
            st, act, rec, iasa = F.move_frames(a, move)
            fr = a.anim[move]['frames']
            hf = a.anim[move]['hit_frame']
            self.assertEqual(st, F.frames_of_ms(sum(f['ms'] for f in fr[:hf])))
            self.assertGreaterEqual(act, 1)
            self.assertEqual(st + act + rec, F.frames_of_ms(sum(f['ms'] for f in fr)))
            self.assertLessEqual(iasa, st + act + rec)


class Timeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = [bout_of(seed) for seed in range(8)] + [bout_of(seed, 'cursor', 'oni') for seed in range(8, 14)]

    def test_hitlag_freezes_both_fighters_for_the_same_time(self):
        n = 0
        for tl, s, bout in self.runs:
            for w in 'ab':
                o_tl = tl['b' if w == 'a' else 'a']
                for t, name, o in tl[w]:
                    if 'contact' not in o or o.get('outcome') not in ('hit', 'block', 'crouch_block') or o.get('kind') == 'counter':
                        continue
                    tc = o['contact']
                    react = [ro for t2, n2, ro in o_tl if ro.get('react_to') == name and abs(t2 - tc) < 1e-6]
                    if react and 'stop_at' not in react[0] and not o.get('slow'):
                        self.assertEqual(react[0]['hitstop'], o['hitstop'], (name, tc))
                        n += 1
        self.assertGreater(n, 50)

    def test_hitstun_grows_with_knockback(self):
        log = [e for tl, s, bout in self.runs for e in bout.fd_log]
        self.assertGreater(len(log), 60)
        for e in log:
            self.assertAlmostEqual(e['stun'], min(rounds.HITSTUN_CAP_S, F.hitstun_ms(e['kb']) / 1000.0), places=3)
        pairs = sorted((e['kb'], e['stun']) for e in log)
        self.assertEqual([p[1] for p in pairs], sorted(p[1] for p in pairs))

    def test_later_hits_in_a_round_launch_further(self):
        """Within a round, the same move landing on the same fighter at a higher percentage knocks it back further."""
        checked = 0
        for tl, s, bout in self.runs:
            seen = {}
            for e in bout.fd_log:
                key = (e['tgt'], e['move'], e['dmg'])
                if key in seen and e['pct'] > seen[key]['pct']:
                    self.assertGreater(e['kb'], seen[key]['kb'])
                    self.assertGreaterEqual(e['knock'], seen[key]['knock'] - 1e-6)
                    checked += 1
                seen[key] = e
        self.assertGreater(checked, 5)

    def test_big_hits_tumble_along_an_arc_and_tech_or_lie_down(self):
        arcs = techs = 0
        for tl, s, bout in self.runs:
            for w in 'ab':
                rows = [(t, n, o) for t, n, o in tl[w] if not n.startswith('@')]
                for i, (t, n, o) in enumerate(rows):
                    if n == 'knockdown' and o.get('air'):
                        arcs += 1
                        hs = [k[1] for k in o['air']]
                        self.assertGreater(max(hs), 1.0)
                        self.assertEqual(o['air'][2][1], 0)          # lands on the row's flat frame
                        self.assertIn('slow', o)                      # the flight is stretched over the real airtime
                        nxt = rows[i + 1] if i + 1 < len(rows) else None
                        if nxt and nxt[1] == 'getup':
                            techs += 1
        self.assertGreater(arcs, 3)
        self.assertGreater(techs, 2)

    def test_percent_resets_every_round_and_rides_on_the_hp_directive(self):
        for tl, s, bout in self.runs[:3]:
            hps = [o for t, n, o in tl['a'] if n == '@hp' and 'pct' in o]
            self.assertTrue(hps)
            self.assertTrue(all(v == 0.0 for o in hps for v in o['pct'].values()))


class Arena(unittest.TestCase):
    def test_arena_hits_use_the_same_model(self):
        from minis_core import arena as AR
        hd = Library(hd=True)
        st = AR.Stage((0, 0, 1280, 720), [(1, 90, 200, 580, 600)], floor_y=672)
        ar = AR.Arena(st, {'a': hd['claude'], 'b': hd['knight']}, FX, seed=2, now=0.0, record=lambda *a, **k: None)
        ar.flashes = True
        now, symmetric = 0.0, 0
        while ar.phase != 'done' and now < 120:
            now += 1 / 30.0
            n, ne = len(ar.fd_log), ar.counts.get('wall_bounce', 0) + ar.counts.get('skid', 0)
            ar.tick(now)
            bounced = ar.counts.get('wall_bounce', 0) + ar.counts.get('skid', 0) > ne     # a bounce adds its own short stop
            if len(ar.fd_log) > n and ar.f['a'].stop is not None and not bounced:
                self.assertEqual(ar.f['a'].stop, ar.f['b'].stop)        # both fighters freeze for the same hitlag
                symmetric += 1
        self.assertGreater(len(ar.fd_log), 10)
        self.assertGreater(symmetric, 5)
        for e in ar.fd_log:
            self.assertAlmostEqual(e['stun'], F.hitstun_ms(e['kb']) / 1000.0, places=3)
        for s in 'ab':                                                    # within a round the % only grows
            pcts = [e['pct'] for e in ar.fd_log if e['tgt'] == s]
            self.assertTrue(pcts)


if __name__ == '__main__':
    unittest.main()
