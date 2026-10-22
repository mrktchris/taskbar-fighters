"""V9 spacing: two fighters on the ground never stand trunk inside trunk, and never idle inside each other.

Weapons and striking limbs may reach into the opponent at a contact (that is the hit); bodies may not.  Measured on whole
seeded demo matches between many pairings, every 1/30 s, from the real timelines both slots replay."""
import os, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ.setdefault('MINIS_TESTING', '1')
from helpers import CFG  # noqa: E402,F401
from minis_core import config as cfgmod, rounds, sim  # noqa: E402
from minis_core.brain import LEFT, RIGHT  # noqa: E402

PAIRS = [('claude', 'codex'), ('cursor', 'oni'), ('gemini', 'knight'), ('barbarian', 'kunoichi'), ('monk', 'nomad'),
         ('ollama', 'lmstudio'), ('oni', 'barbarian')]
# rows where touching is the point (a grab), the body is horizontal on the floor, or the fighter passes the other on purpose
EXEMPT = set(rounds.LYING) | {'throw', 'thrown', 'ko', 'getup', 'launched', 'jump', 'clash'}


def frames(chars, secs=150, fps=30):
    cfg = dict(cfgmod.DEFAULTS, bout_min_s=999, bout_max_s=999, clash_min_s=999, clash_max_s=999, scoreboard=False)
    _, atl, br = sim.make(1, cfg, 1000.0, chars={LEFT: chars[0], RIGHT: chars[1]})
    tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
    bus = {}
    br[LEFT].request_demo('match', 1000.0, wait_s=30)
    for i in range(int(secs * fps)):
        now = 1000.0 + i / fps
        sim.step(br, tele, now, bus)
        if br[LEFT].mode == 'script' and br[RIGHT].mode == 'script':
            yield now, br, br[LEFT].view(now), br[RIGHT].view(now)


def passing(atlas, anim):
    a = atlas.anim.get(anim) or {}
    return a.get('type') in ('through', 'throw') or bool(a.get('air'))


class Spacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bad_core, cls.bad_idle, cls.n = [], [], 0
        for chars in PAIRS:
            for now, br, v1, v2 in frames(chars):
                A1, A2 = br[LEFT].atlas, br[RIGHT].atlas
                if v1['lift'] > 0 or v2['lift'] > 0 or v1['anim'] in EXEMPT or v2['anim'] in EXEMPT:
                    continue
                if passing(A1, v1['anim']) or passing(A2, v2['anim']):
                    continue
                cls.n += 1
                d = abs(v1['x'] - v2['x'])
                if d < rounds.core_room(A1, A2) - 1.0:
                    cls.bad_core.append((chars, round(now - 1000, 2), round(d, 1), v1['anim'], v2['anim']))
                ending = now > float(br[LEFT].script.get('t_end', now + 1)) - 0.25     # the hand-off to the walk home
                if v1['anim'] == v2['anim'] == 'idle' and d < rounds.idle_room(A1, A2) - 1.0 and not ending:
                    cls.bad_idle.append((chars, round(now - 1000, 2), round(d, 1)))

    def test_enough_frames_were_checked(self):
        self.assertGreater(self.n, 4000)

    def test_trunks_never_overlap_on_the_ground(self):
        self.assertEqual(self.bad_core, [], self.bad_core[:10])

    def test_idle_bodies_never_overlap(self):
        # a single 1/30 s idle frame between two rows (a dash landing straight into the next strike) is not a stance
        runs, prev = [], None
        for chars, t, d in self.bad_idle:
            if prev and prev[0] == chars and abs(t - prev[1]) < 0.04:
                runs[-1].append(t)
            else:
                runs.append([t])
            prev = (chars, t)
        long_runs = [r for r in runs if len(r) > 2]
        self.assertEqual(long_runs, [], self.bad_idle[:10])

    def test_the_rooms_come_from_the_art(self):
        from minis_core.atlas import Library
        lib = Library()
        for a, b in PAIRS:
            A, B = lib[a], lib[b]
            self.assertGreaterEqual(rounds.idle_room(A, B), rounds.core_room(A, B))
            self.assertGreaterEqual(rounds.core_room(A, B), rounds.MIN_APART)


if __name__ == '__main__':
    unittest.main()
