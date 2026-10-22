"""V7.1 lock-on: fighters face each other, attacks target the opponent's real position, projectiles never fly into empty
space, and nothing a fight draws reaches a plate or the scoreboard.

Property tests over many seeded matches between two Brains wired like the two real slot processes: each reads the other's
bus copy every 0.2 s and publishes at most every 0.25 s (unless an event goes out), redraws at 30 fps.  The facing check
runs on every rendered frame (the view a window would draw) against the OTHER brain's actual position.

The owner's live screenshot (2026-10-15): the left fighter faced away with its bow aimed at empty space while the right one
was mid-jump - the vault back after a dash-through.  Root causes these tests pin down:
  1. inside a bout facing followed the partner's bus copy (0.2-0.45 s old), so after every crossover a fighter faced the
     old side and its next attack went off backwards;
  2. the shared timeline let a bout spread 110 px either side of its centre while the brain clamped every slide to its own
     zone (only ~75 px either side at 128 px fighters), so the two fighters stopped being where the plan said: crossed
     over, overlapping, striking from the wrong distance;
  3. facing was set before the slide of the same redraw (one stale frame) and never at all at home while asleep / KO'd
     after a walk home that faces the way it walks.
`python tests/test_lockon.py` prints the audit numbers.
"""
import collections, random, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from minis_core import choreo, config as cfgmod, rounds, sim  # noqa: E402
from minis_core.brain import LEFT, RIGHT, Brain, proj_x  # noqa: E402

LIB = sim._LIB
ROSTER = ['generic', 'claude', 'codex', 'cursor', 'gemini', 'knight', 'kunoichi', 'nomad', 'ollama', 'monk', 'oni',
          'lmstudio', 'barbarian']
FPS = 30


def whitelisted(b, o, now):
    """The explicit, intended moments of not facing the opponent (independent of the brain's own rule)."""
    if b.mode == 'walk' and b.walk_then == 'home':
        return True
    for who, frame in ((b, b.frame(now)[0]), (o, o.frame(now)[0])):
        a = who.atlas.anim.get(who.anim) or {}
        if a.get('type') == 'through' and frame <= a.get('hit_frame', 99):
            return True                                       # a dash-through pass until its cut lands (attacker and defender)
    return b.anim == 'hit_back'                               # struck from behind


def play(seed, ca, cb, size=128, secs=70.0, kinds=('match',)):
    """One run: demo bouts back to back.  -> dict of counters and samples."""
    cfg = dict(cfgmod.DEFAULTS, bout_min_s=999, bout_max_s=999, clash_min_s=999, clash_max_s=999, match_min_s=9999,
               match_max_s=9999)
    k = size / 64.0
    try:
        z0, z1 = cfgmod.fight_zone(cfg, size)
    except TypeError:                                         # (the pre-V7.1 engine, for the before/after numbers)
        z0, z1 = cfgmod.fight_zone(cfg)
    zone = (z0 / k, z1 / k)
    br = {w: Brain(w, LIB[c], LIB, cfg, random.Random(seed * 7 + i), 1000.0, run=f'r{w}{seed}', zone=zone, record=sim.no_record)
          for i, (w, c) in enumerate(((LEFT, ca), (RIGHT, cb)))}
    for b in br.values():
        b.flashes = True
    tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
    bus, seen, lastpub, lastkey, lastread = {}, {}, {w: -1e9 for w in br}, {}, {w: -1e9 for w in br}
    out = collections.Counter()
    bad = []
    projs_seen = set()
    contacts = []
    n = 0
    for i in range(int(secs * FPS)):
        now = 1000.0 + i / FPS
        for w, b in br.items():
            o = RIGHT if w == LEFT else LEFT
            if now - lastread[w] >= 0.2:
                lastread[w] = now
                seen[w] = dict(bus[o]) if o in bus else None
            b.tick(now, tele[w].poll(now), seen.get(w))
        for w, b in br.items():
            pub = b.publish()
            ev = pub['event'] or {}
            evk = (ev.get('run'), ev.get('seq'))
            key = (pub['state'], pub['mode'], int(pub['x']), pub['facing'], pub['anim'], evk)
            if evk != (lastkey.get(w) or (None,) * 6)[5] or (now - lastpub[w] >= 0.25 and key != lastkey.get(w)) or now - lastpub[w] >= 1.0:
                bus[w], lastpub[w], lastkey[w] = pub, now, key
        a = br[LEFT]
        if a.mode == 'home' and br[RIGHT].mode == 'home' and a.script is None and not a.demo and not a.pending:
            a.request_demo(kinds[n % len(kinds)], now, wait_s=20)
            n += 1
        for w, b in br.items():
            o = br[RIGHT if w == LEFT else LEFT]
            v = b.view(now)                                   # what the window draws this frame
            if b.mode != 'script':
                continue
            out['frames'] += 1
            g = getattr(b, 'ghost', None)
            if g is not None and o.mode == 'script' and abs(g.x - o.x) > 0.5:
                out['ghost_off'] += 1                         # the replayed opponent is where the real one is
            d = o.x - b.x
            if abs(d) < 0.5:
                continue
            want = 1 if d > 0 else -1
            if v['facing'] != want and not whitelisted(b, o, now):
                out['facing'] += 1
                bad.append((seed, round(now, 2), w, b.character, b.anim, round(b.x, 1), o.character, o.anim, round(o.x, 1)))
            # a projectile leaves toward the opponent and arrives on it
            for p in (b.script or {}).get('projs') or ():
                key = (b.script['plan']['id'], p['owner'], p['spawn'], p['move'])
                if p['owner'] != w or key in projs_seen or now < p['spawn']:
                    continue
                projs_seen.add(key)
                out['projectiles'] += 1
                ahead = (o.x - p['x0']) * p['dir']
                if ahead <= 0:
                    out['proj_behind'] += 1
                contacts.append(('proj', p, w))
            # close-range contacts: remember them, checked at their contact time below
            for t_c, name in list(b.contact_log):
                ck = (w, round(t_c, 4), name)
                if ck in projs_seen or t_c < now - 0.5:
                    continue
                projs_seen.add(ck)
                contacts.append(('close', (t_c, name), w))
        # resolve contacts whose time has come
        keep = []
        for c in contacts:
            kind, data, w = c
            b, o = br[w], br[RIGHT if w == LEFT else LEFT]
            t_due = data['arrive'] if kind == 'proj' else data[0]
            if now < t_due:
                keep.append(c)
                continue
            if b.mode != 'script' or o.mode != 'script':
                continue
            if kind == 'proj':
                px = proj_x(data, data['arrive'])
                miss = abs(px - o.x)
                out['proj_checked'] += 1
                if miss > 24:
                    out['proj_empty'] += 1
                    bad.append(('proj', seed, data['move'], round(px, 1), round(o.x, 1)))
            else:
                name = data[1]
                meta = b.atlas.anim.get(name) or {}
                whiff = o.anim in ('backdash', 'clash')         # a deliberate whiff (the defender is gone) / two blades locked
                if meta.get('cat') == 'strike' and meta.get('type') not in ('through', 'pull', 'gust') and 'proj_frame' not in meta and not whiff:
                    out['close'] += 1
                    dist = abs(o.x - b.x)
                    reach = choreo.reach_of(b.atlas, name) + max(12, rounds.core_front(o.atlas))   # reach + the defender's trunk (V9)
                    if dist > reach + 3:
                        out['close_far'] += 1
                        bad.append(('far', seed, b.character, name, round(dist, 1), round(reach, 1), o.anim, b.anim,
                                    getattr(getattr(o, 'track', None), 'slide', None), getattr(getattr(b, 'track', None), 'slide', None), round(now - t_due, 3)))
                    if (o.x - b.x) * b.facing <= 0:
                        out['close_backwards'] += 1
        contacts = keep
        for w, b in br.items():                                  # the timeline never asks for a place the brain cannot go
            lo, hi = b.zone
            if not (lo - 1e-6 <= b.x <= hi + 1e-6):
                out['outside_zone'] += 1
    return out, bad


def audit(n=26, size=128, secs=70.0):
    tot, bad = collections.Counter(), []
    for s in range(n):
        ca = ROSTER[s % len(ROSTER)]
        cb = ROSTER[(s * 5 + 3) % len(ROSTER)]
        if ca == cb:
            cb = 'generic' if ca != 'generic' else 'claude'
        o, b = play(s, ca, cb, size=size, secs=secs, kinds=('match', 'spar', 'match', 'clash'))
        tot.update(o)
        bad += b
    return tot, bad


class LockOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tot, cls.bad = audit(n=13, secs=60.0)

    def test_enough_was_played(self):
        self.assertGreater(self.tot['frames'], 13 * 30 * 25, self.tot)
        self.assertGreater(self.tot['projectiles'] + self.tot['close'], 100, self.tot)

    def test_fighters_face_each_other_on_every_frame_outside_the_whitelist(self):
        self.assertEqual(self.tot['facing'], 0, [b for b in self.bad if len(b) == 9][:10])

    def test_projectiles_leave_toward_the_opponent_and_arrive_on_it(self):
        self.assertEqual(self.tot['proj_behind'], 0, self.tot)
        self.assertEqual(self.tot['proj_empty'], 0, [b for b in self.bad if b[0] == 'proj'][:10])

    def test_close_strikes_land_from_inside_their_reach_and_forward(self):
        self.assertEqual(self.tot['close_backwards'], 0, self.tot)
        self.assertEqual(self.tot['close_far'], 0, [b for b in self.bad if b[0] == 'far'][:10])

    def test_the_replayed_opponent_is_exactly_where_the_real_one_is(self):
        self.assertEqual(self.tot['ghost_off'], 0, self.tot)

    def test_nobody_is_planned_outside_the_zone(self):
        self.assertEqual(self.tot['outside_zone'], 0, self.tot)


class Units(unittest.TestCase):
    def brains(self, chars=('claude', 'codex')):
        cfg = dict(cfgmod.DEFAULTS)
        return {w: Brain(w, LIB[c], LIB, cfg, random.Random(i), 1000.0, run=w, record=sim.no_record)
                for i, (w, c) in enumerate(zip((LEFT, RIGHT), chars))}

    def test_a_crossover_on_the_ground_plays_the_turn_pivot_not_a_snap(self):
        b = self.brains()[LEFT]
        b.partner = dict(x=b.x - 30, mode='home', state='idle')   # the opponent is now behind it
        b.play('idle', 1000.0)
        b.lock_on(1000.0)
        self.assertEqual(b.facing, -1)
        self.assertEqual(b.anim, 'turn')

    def test_airborne_or_mid_move_the_flip_is_immediate(self):
        b = self.brains()[LEFT]
        b.partner = dict(x=b.x - 30, mode='home', state='idle')
        b.play('uppercut', 1000.0)
        b.lock_on(1000.0)
        self.assertEqual((b.facing, b.anim), (-1, 'uppercut'))

    def test_a_sleeping_fighter_turns_back_after_walking_home(self):
        br = self.brains()
        a = br[LEFT]
        tele = sim.FakeTelemetry(LEFT, [(0, 'sleeping', 30)])
        a.partner = dict(x=a.zone[1], mode='home', state='idle', character='codex')
        a.x = a.home[1] + 30                                       # outside its half: it walks home facing left
        now = 1000.0
        faced_away = False
        for i in range(200):
            now += 0.05
            a.tick(now, tele.poll(now), a.partner)
            faced_away |= a.mode == 'walk' and a.facing == -1
        self.assertTrue(faced_away)
        self.assertEqual((a.mode, a.facing), ('home', 1))         # V7.1: before, a sleeper stayed turned away

    def test_a_shot_at_an_airborne_opponent_climbs_to_it(self):
        from minis_core.brain import Track
        b = self.brains()[LEFT]
        b.mode = 'script'
        b.script = dict(projs=[], tl=[], t_end=2000.0, plan={})
        b.ghost = Track([(1000.0, 'launched', {})], b.x + 60, b.zone, LIB['codex'])
        b.ghost.advance(1001.0)
        up = b.ghost.lift(1001.0)
        p = dict(spawn=1000.0, arrive=1002.0, x0=b.x, dir=1, speed=30.0, move='x')
        self.assertAlmostEqual(b.proj_lift(p, 1000.0), b.lift(1000.0))
        self.assertAlmostEqual(b.proj_lift(p, 1002.0), b.ghost.lift(1002.0))
        if up > 0:                                                 # (once the art gives `launched` its air curve)
            self.assertGreater(b.proj_lift(p, 1001.5), 0.0)


class LockOn64(unittest.TestCase):
    def test_same_rules_at_64_px(self):
        tot, bad = collections.Counter(), []
        for s in range(4):
            o, b = play(100 + s, ROSTER[s], ROSTER[s + 5], size=64, secs=50.0, kinds=('match', 'spar'))
            tot.update(o)
            bad += b
        self.assertEqual((tot['facing'], tot['proj_behind'], tot['proj_empty'], tot['close_backwards']), (0, 0, 0, 0), bad[:10])


class HudClear(unittest.TestCase):
    """No fighter frame or effect ever reaches a plate or the scoreboard, at 64 / 96 / 128 px: every frame of seeded
    matches is composed the way minis.Fighter.compose draws the window (HD atlas above 64 px, shrunk at 96) and its
    screen extent must stay inside config.fight_band (plate strip end .. scoreboard left edge)."""

    def overlaps(self, size, seeds=3, secs=45.0):
        import minis
        from minis_core import render
        from minis_core.atlas import Library
        cfg = dict(cfgmod.DEFAULTS)
        plates_end = cfgmod.plate_left(cfg, 'b') + cfgmod.PLATE_W
        from minis_core import scoreboard
        sb = scoreboard.left_x(cfg)
        k = size / 64.0
        hd = Library(hd=True) if size > 64 else None
        try:
            z0, z1 = cfgmod.fight_zone(cfg, size)
        except TypeError:                                         # (the pre-V7.1 engine, for the before/after numbers)
            z0, z1 = cfgmod.fight_zone(cfg)
        zone = (z0 / k, z1 / k)
        n = bad = 0
        for s in range(seeds):
            ca, cb = ROSTER[(s * 3) % 13], ROSTER[(s * 3 + 7) % 13]
            br = {w: Brain(w, LIB[c], LIB, cfg, random.Random(s + i), 1000.0, run=f'h{w}', zone=zone, record=sim.no_record)
                  for i, (w, c) in enumerate(((LEFT, ca), (RIGHT, cb)))}
            for b in br.values():
                b.flashes = True
            tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
            bus = {}
            br[LEFT].request_demo('match', 1000.0, wait_s=30)
            for i in range(int(secs * 15)):
                now = 1000.0 + i / 15.0
                sim.step(br, tele, now, bus)
                for w, b in br.items():
                    v = b.view(now)
                    if size == 64:
                        im, x0 = render.compose(b.atlas, b.atlas, v, b.snap, now, cfg, show_plate=False)
                        sx0, sx1 = x0, x0 + im.width
                    else:
                        h = hd[b.character]
                        im, x0 = render.compose(h, h, minis.hd_view(v, h, b.atlas), b.snap, now, cfg, show_plate=False)
                        f = k / 2.0                                           # HD px -> screen px (96: the 3/4 shrink)
                        sx0, sx1 = x0 * f, (x0 + im.width) * f
                    bb = im.getbbox()
                    if not bb:
                        continue
                    n += 1
                    f = 1.0 if size == 64 else k / 2.0
                    lo, hi = sx0 + bb[0] * f, sx0 + bb[2] * f
                    if lo < plates_end or hi > sb:
                        bad += 1
        return n, bad

    def test_nothing_reaches_a_plate_or_the_scoreboard_at_any_size(self):
        for size in (64, 96, 128):
            n, bad = self.overlaps(size)
            self.assertGreater(n, 500, size)
            self.assertEqual(bad, 0, (size, n))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'audit':
        t, b = audit(int(sys.argv[2]) if len(sys.argv) > 2 else 26)
        print(dict(t))
        for x in b[:40]:
            print(x)
    else:
        unittest.main()


class SpriteNeverClipped(unittest.TestCase):
    """The HUD clip (render.compose `clip`) may only ever trim effects, never a fighter: the sprite composed with the clip
    must equal the sprite composed without it, on every frame of seeded matches at 64 / 96 / 128 px.  Two paths: the live
    one (minis.Fighter passes the zone to the Brain) and the doc render (tools/doc_images.taskbar_strip_frames sets
    brain.zone afterwards).  Found 2026-10-16 in the launch demo: Brain.band was computed once from the constructor's zone,
    so the 128 px doc render kept the 64 px band and sliced the left fighter at strip x ~355."""

    def run_size(self, size, doc, seeds=2, secs=40.0):
        import minis
        from minis_core import render
        from minis_core.atlas import Library
        cfg = dict(cfgmod.DEFAULTS)
        k = size / 64.0
        hd = Library(hd=True) if size > 64 else None
        z0, z1 = cfgmod.fight_zone(cfg, size)
        zone = (z0 / k, z1 / k)
        n = cut = 0
        for s in range(seeds):
            ca, cb = ROSTER[(s * 5 + 1) % 13], ROSTER[(s * 5 + 8) % 13]
            br = {}
            for i, (w, c) in enumerate(((LEFT, ca), (RIGHT, cb))):
                if doc:                                          # as doc_images: default zone first, the real one after
                    b = Brain(w, LIB[c], LIB, cfg, random.Random(s + i), 1000.0, run=f'd{w}', record=sim.no_record)
                    b.zone = zone
                    x = (420 if w == LEFT else 610) / k
                    b.x = b.home_x = x
                    b.home = (x - 40 / k, x + 40 / k)
                else:
                    b = Brain(w, LIB[c], LIB, cfg, random.Random(s + i), 1000.0, run=f'l{w}', zone=zone, record=sim.no_record)
                b.flashes = True
                br[w] = b
            tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
            bus = {}
            br[LEFT].request_demo('match', 1000.0, wait_s=30)
            for i in range(int(secs * 10)):
                now = 1000.0 + i / 10.0
                sim.step(br, tele, now, bus)
                for w, b in br.items():
                    v = dict(b.view(now), fx=[], banner=None, proj=None, flash=0.0)     # the sprite alone
                    atlas = b.atlas if size == 64 else hd[b.character]
                    vv = v if size == 64 else minis.hd_view(v, atlas, b.atlas)
                    a_im, a_x = render.compose(atlas, atlas, vv, b.snap, now, cfg, show_plate=False)
                    b_im, b_x = render.compose(atlas, atlas, dict(vv, clip=None), b.snap, now, cfg, show_plate=False)
                    n += 1
                    if a_im.getbbox() is None or b_im.getbbox() is None:
                        continue
                    aa = (a_im.getbbox()[0] + a_x, a_im.getbbox()[2] + a_x)
                    bb = (b_im.getbbox()[0] + b_x, b_im.getbbox()[2] + b_x)
                    if aa != bb:
                        cut += 1
        return n, cut

    def test_no_fighter_pixel_is_ever_clipped(self):
        for size in (64, 96, 128):
            for doc in (False, True):
                n, cut = self.run_size(size, doc)
                self.assertGreater(n, 1000, (size, doc))
                self.assertEqual(cut, 0, (size, 'doc render' if doc else 'live', n))
