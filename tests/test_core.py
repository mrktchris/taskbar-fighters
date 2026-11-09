import json, os, random, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, CFG, Isolated  # noqa: E402
from minis_core import bus, render, sim  # noqa: E402
from minis_core.atlas import Atlas, AtlasError, Library, resolve, validate  # noqa: E402
from minis_core.brain import LEFT, RIGHT, Brain, make_timeline  # noqa: E402
from minis_core.telemetry import Snapshot  # noqa: E402


# ====================================================================== bus
class Bus(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_roundtrip_and_no_temp_files_left(self):
        self.assertTrue(bus.write('a', {'x': 5, 'event': {'seq': 1}}, root=self.d, now=100.0))
        got = bus.read('a', root=self.d, now=101.0)
        self.assertEqual(got['x'], 5)
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith('.tmp')], [])

    def test_stale_missing_and_corrupt_partner_mean_solo(self):
        self.assertIsNone(bus.read('b', root=self.d, now=1.0))                           # missing
        bus.write('b', {'x': 1}, root=self.d, now=100.0)
        self.assertIsNone(bus.read('b', root=self.d, now=106.0))                         # stale (>5 s)
        Path(self.d, 'b.json').write_text('{not json', encoding='utf-8')
        self.assertIsNone(bus.read('b', root=self.d, now=100.5))                         # corrupt

    def test_read_cache_sees_a_rewrite(self):
        bus.write('a', {'x': 1}, root=self.d, now=100.0)
        self.assertEqual(bus.read('a', root=self.d, now=100.1)['x'], 1)
        bus.write('a', {'x': 2}, root=self.d, now=100.2)
        self.assertEqual(bus.read('a', root=self.d, now=100.3)['x'], 2)

    def test_gone_has_a_real_timestamp_and_reads_as_absent(self):
        self.assertTrue(bus.write_gone('a', root=self.d, now=500.0))
        self.assertIsNone(bus.read('a', root=self.d, now=500.5))                         # fresh, but gone = solo
        raw = bus.read('a', root=self.d, now=500.5, raw=True)
        self.assertEqual((raw['state'], raw['ts']), ('gone', 500.0))

    def test_replace_retries_while_a_reader_holds_the_file(self):
        real = os.replace
        calls = {'n': 0}

        def flaky(a, b):
            calls['n'] += 1
            if calls['n'] < 3:
                raise PermissionError('held open')
            return real(a, b)
        with mock.patch.object(bus.os, 'replace', flaky):
            self.assertTrue(bus.write('a', {'x': 9}, root=self.d, now=10.0))
        self.assertEqual(calls['n'], 3)
        self.assertEqual(bus.read('a', root=self.d, now=10.1)['x'], 9)

    def test_replace_that_never_succeeds_returns_false_and_cleans_up(self):
        with mock.patch.object(bus.os, 'replace', side_effect=PermissionError('held')), mock.patch.object(bus.time, 'sleep'):
            self.assertFalse(bus.write('a', {'x': 9}, root=self.d, now=10.0))
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith('.tmp')], [])

    def test_write_oserror_never_raises(self):
        with mock.patch.object(Path, 'write_text', side_effect=OSError(28, 'disk full')):
            self.assertFalse(bus.write('a', {'x': 1}, root=self.d, now=1.0))


# ====================================================================== planner
def idle_tele():
    return {LEFT: sim.FakeTelemetry(LEFT, [(0, 'idle', 22.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 31.0)], plan=(1.0, 'wk'))}


PLACE = {LEFT: 380, RIGHT: 560}
QUIET = {'bout_min_s': 999, 'bout_max_s': 999, 'clash_min_s': 999, 'clash_max_s': 999}


def placed(seed, chars=None, **over):
    cfg, atl, brains = sim.make(seed, dict(CFG, **over), 1000.0, chars=chars)
    for w, x in PLACE.items():
        brains[w].x = brains[w].home_x = x
        brains[w].home = (x - 40, x + 40)
    return cfg, atl, brains


def drive(brains, tele, secs, t0=1000.0, fps=10, each=None):
    bus_ = {}
    for i in range(int(secs * fps)):
        now = t0 + i / fps
        sim.step(brains, tele, now, bus_)
        if each:
            each(now, bus_)
    return bus_


class Planner(unittest.TestCase):
    def test_spar_contact_and_reaction_start_on_the_same_instant(self):
        brains, _, _ = sim.run(60, idle_tele(), seed=3, cfg_over={'bout_min_s': 5, 'bout_max_s': 6}, place=PLACE)
        c, k = brains[LEFT], brains[RIGHT]
        hits = {LEFT: dict((round(t, 2), n) for t, n in c.hit_log), RIGHT: dict((round(t, 2), n) for t, n in k.hit_log)}
        pairs = 0
        for att, dfn in ((c, RIGHT), (k, LEFT)):
            for tc, move in att.contact_log:
                if move in ('fistbump', 'highfive'):
                    continue
                self.assertIn(round(tc, 2), hits[dfn], f'{move} contact at {tc} has no matching reaction')
                self.assertIn(hits[dfn][round(tc, 2)], ('block_hit', 'hit', 'hit_heavy', 'parry', 'whiff', 'knockdown',     # V5: every answer is
                                                        'pulled', 'guard_crush', 'launched', 'air_hit', 'spiked',     # logged at the
                                                        'hit_high', 'hit_low', 'hit_back', 'clash'))                 # contact instant
                pairs += 1
        self.assertGreaterEqual(pairs, 4, 'a spar has at least four exchanges')

    def test_fistbump_or_highfive_is_simultaneous(self):
        brains, _, _ = sim.run(60, idle_tele(), seed=3, cfg_over={'bout_min_s': 5, 'bout_max_s': 6}, place=PLACE)
        end = ('fistbump', 'highfive')
        a = [(round(t, 2), n) for t, n in brains[LEFT].contact_log if n in end]
        b = [(round(t, 2), n) for t, n in brains[RIGHT].contact_log if n in end]
        self.assertTrue(a and a == b)

    def test_everyone_ends_up_home_and_out_of_script(self):
        brains, _, _ = sim.run(60, idle_tele(), seed=3, cfg_over={'bout_min_s': 5, 'bout_max_s': 6, 'scoreboard': False}, place=PLACE)
        for b in brains.values():
            self.assertIn(b.mode, ('home', 'walk'))
            self.assertGreaterEqual(b.x, b.zone[0])
            self.assertLessEqual(b.x, b.zone[1])

    def test_fighters_never_overlap_more_than_20px(self):
        cfg, atl, brains = placed(3, bout_min_s=5, bout_max_s=6)
        closest = [999]
        passing = lambda: any((brains[w].atlas.anim.get(brains[w].anim) or {}).get('type') == 'through' or brains[w].anim == 'jump'
                              for w in (LEFT, RIGHT))

        def note(now, b):
            if not passing():                                   # V7: a dash-through runs THROUGH the opponent (and vaults back) on purpose
                closest[0] = min(closest[0], abs(brains[LEFT].x - brains[RIGHT].x))
        drive(brains, idle_tele(), 60, each=note)
        self.assertGreaterEqual(closest[0], 20)

    def test_handoff_after_b_finishes_the_finisher_gives(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'idle', 22.0)]),
                RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 30.0), (2, 'working', 34.0), (22, 'idle', 36.0)])}
        cfg, atl, brains = placed(5, **QUIET)
        seen = {LEFT: set(), RIGHT: set()}
        drive(brains, tele, 60, each=lambda now, b: [seen[w].add(brains[w].anim) for w in (LEFT, RIGHT)])
        self.assertIn('review', seen[LEFT])                     # the other one reviews
        self.assertIn('handoff_take', seen[LEFT])
        self.assertIn('handoff_give', seen[RIGHT])              # the finished fighter gives
        self.assertIn('victory', seen[RIGHT])
        self.assertIn('fistbump', seen[LEFT] & seen[RIGHT])
        self.assertIn('thumbs_up', seen[LEFT])
        self.assertIn(brains[LEFT].mode, ('home', 'walk'))

    def test_limit_means_ko_then_dizzy_and_partner_consoles(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'idle', 50.0), (3, 'idle', 92.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 30.0)])}
        cfg, atl, brains = placed(5, **QUIET)
        seen = {LEFT: [], RIGHT: []}

        def rec(now, b):
            for w in (LEFT, RIGHT):
                if not seen[w] or seen[w][-1] != brains[w].anim:
                    seen[w].append(brains[w].anim)
        drive(brains, tele, 30, each=rec)
        self.assertEqual([a for a in seen[LEFT] if a in ('ko', 'getup', 'dizzy')][:3], ['ko', 'getup', 'dizzy'])
        self.assertIn('console', seen[RIGHT])

    def test_waking_up_and_powering_up_use_their_moves(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'sleeping', None), (5, 'working', 75.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 20.0)])}
        cfg, atl, brains = placed(2, **QUIET)
        seen = []
        drive(brains, tele, 20, each=lambda now, b: (not seen or seen[-1] != brains[LEFT].anim) and seen.append(brains[LEFT].anim))
        self.assertEqual(seen[0], 'sleep')
        self.assertIn('wake', seen)
        self.assertEqual(seen[-1], 'powerup')                    # working past 70% context

    def test_partner_absent_means_solo_and_never_raises(self):
        cfg, atl, brains = sim.make(2, dict(CFG, bout_min_s=1, bout_max_s=2), 1000.0)
        b = brains[LEFT]
        tele = sim.FakeTelemetry(LEFT, [(0, 'idle', 20.0)])
        for i in range(0, 900):
            b.tick(1000.0 + i / 10, tele.poll(1000.0 + i / 10), None)
        self.assertNotEqual(b.mode, 'script')
        self.assertEqual(list(b.contact_log), [])

    def test_shared_timeline_is_deterministic(self):
        lib = Library()
        plan = dict(kind='spar', left=LEFT, right=RIGHT, pos={LEFT: 400, RIGHT: 424}, t0=50.0, seed=7, chars={LEFT: 'claude', RIGHT: 'codex'})
        a = make_timeline('spar', plan, lib)
        b = make_timeline('spar', plan, lib)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])

    def test_same_character_in_both_slots_still_spars(self):
        brains, _, _ = sim.run(60, idle_tele(), seed=3, cfg_over={'bout_min_s': 5, 'bout_max_s': 6}, place=PLACE, chars={LEFT: 'codex', RIGHT: 'codex'})
        self.assertGreaterEqual(len(brains[LEFT].contact_log) + len(brains[RIGHT].contact_log), 3)     # either side's strikes count


# ====================================================================== brain regressions (audit findings)
def snap(state='idle', ctx=20.0, events=()):
    s = Snapshot('x', state, ctx)
    s.events = list(events)
    return s


def pair(seed=1, **over):
    cfg, atl, brains = placed(seed, **dict(QUIET, **over))
    return brains[LEFT], brains[RIGHT]


def invite_from(a, b, kind, now):
    """a invites b, as it would on the bus."""
    a.partner = b.publish()
    a.snap = a.snap or snap()
    assert a._send_invite(kind, now)
    return a.publish()


class BrainEvents(unittest.TestCase):
    def setUp(self):
        self.a, self.b = pair()
        for br in (self.a, self.b):
            br.tick(1000.0, snap(), None)

    def test_invite_is_only_accepted_before_its_deadline(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1003.5, snap(), pa)                          # deadline is 3 s after the invite
        self.assertIsNone(self.b.script)
        b2 = pair()[1]
        b2.tick(1000.0, snap(), None)
        b2.tick(1000.4, snap(), pa)
        self.assertIsNotNone(b2.script)
        self.assertEqual(b2.event['type'], 'accept')

    def test_old_events_are_ignored_and_runs_dedupe(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1004.0, snap(), pa)                          # 4 s old: a replay after a restart, ignored
        self.assertIsNone(self.b.script)
        fresh = dict(pa, event=dict(pa['event'], mt=1004.0))
        fresh['event']['plan'] = dict(pa['event']['plan'], deadline=1007.0)
        self.b.tick(1004.1, snap(), fresh)                       # same run + seq as the ignored one: still seen
        self.assertIsNone(self.b.script)
        other_run = dict(fresh, event=dict(fresh['event'], run='restarted'))
        self.b.tick(1004.2, snap(), other_run)                   # a restarted partner reuses seq 1 with a new run id
        self.assertIsNotNone(self.b.script)

    def test_an_old_finished_event_starts_no_handoff(self):
        p = dict(self.a.publish(), event=dict(seq=7, type='finished', run='r1', mt=996.0))
        self.b.tick(1000.0, snap(), p)                           # 4 s old (e.g. replayed after a restart)
        self.assertIsNone(self.b.pending)
        self.assertIsNone(self.b.bout)
        p = dict(p, event=dict(seq=8, type='finished', run='r1', mt=999.9))
        self.b.tick(1000.1, snap(), p)                           # fresh: the other fighter goes to take the diff
        self.assertIsNotNone(self.b.bout)
        self.assertEqual(self.b.event['plan']['giver'], LEFT)

    def test_accept_only_when_actually_free(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b._goto(self.b.x + 30, 1000.0, then='home')         # walking (a wander): not free
        self.b.tick(1000.2, snap(), pa)
        self.assertIsNone(self.b.script)
        b2 = pair()[1]
        b2.tick(1000.0, snap('working'), None)                   # working: a spar is not accepted
        b2.tick(1000.2, snap('working'), pa)
        self.assertIsNone(b2.script)
        b3 = pair()[1]
        b3.tick(1000.0, snap('sleeping'), None)                  # asleep: no bouts
        b3.tick(1000.2, snap('sleeping'), dict(pa, event=dict(pa['event'], plan=dict(pa['event']['plan'], kind='clash'))))
        self.assertIsNone(b3.script)

    def test_drag_mid_bout_cancels_and_the_partner_aborts(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1000.2, snap(), pa)
        self.a.tick(1000.3, snap(), self.b.publish())            # a receives accept -> both scripted
        self.assertIsNotNone(self.a.script)
        self.a.drag_to(200, 1000.5)
        self.assertEqual(self.a.event['type'], 'cancel')
        self.assertEqual(self.a.mode, 'home')
        self.b.tick(1000.6, snap(), self.a.publish())
        self.assertIsNone(self.b.script)
        self.assertIsNone(self.b.bout)
        self.assertEqual(self.b.walk_then, 'home')

    def test_partner_gone_mid_bout_aborts(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1000.2, snap(), pa)
        self.assertIsNotNone(self.b.script)
        self.b.tick(1000.4, snap(), None)
        self.assertIsNone(self.b.script)
        self.assertEqual(self.b.walk_then, 'home')

    def test_own_limit_stops_walking_and_cancels(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1000.2, snap(), pa)
        x = self.b.x
        self.b.tick(1000.5, snap('limit', 95.0, ['limit']), self.a.publish())
        self.assertEqual(self.b.mode, 'home')
        self.assertIsNone(self.b.script)
        self.assertEqual(self.b.event['type'], 'limit')          # one event slot: the limit carries the cancel
        self.assertEqual(self.b.event['cancels'], pa['event']['plan']['id'])
        self.b.tick(1001.5, snap('limit', 95.0), self.a.publish())
        self.assertAlmostEqual(self.b.x, x, delta=0.5)           # it does not keep walking to the bout spot
        self.a.tick(1000.6, snap(), self.b.publish())            # ... and the partner aborts its side of the bout
        self.assertIsNone(self.a.script)
        self.assertIsNone(self.a.bout)

    def test_console_only_when_the_knocked_out_partner_is_home(self):
        self.a.tick(1000.1, snap('limit', 95.0, ['limit']), None)
        p = dict(self.a.publish(), mode='walk')
        self.b.tick(1000.2, snap(), p)
        self.assertIsNone(self.b.script)                         # partner was not at home: no visit
        a2, b2 = pair()
        a2.tick(1000.0, snap(), None)
        b2.tick(1000.0, snap(), None)
        a2.tick(1000.1, snap('limit', 95.0, ['limit']), None)
        b2.tick(1000.2, snap(), a2.publish())
        self.assertEqual(b2.script['kind'], 'console')

    def test_logs_are_bounded(self):
        for i in range(500):
            self.a.contact_log.append((i, 'jab'))
            self.a.hit_log.append((i, 'hit'))
        self.assertLessEqual(len(self.a.contact_log), 64)
        self.assertLessEqual(len(self.a.hit_log), 64)

    def test_reassigned_slot_drops_its_bout(self):
        pa = invite_from(self.a, self.b, 'spar', 1000.0)
        self.b.tick(1000.2, snap(), pa)
        self.b.set_atlas(Library()['claude'], 1000.3)
        self.assertIsNone(self.b.script)
        self.assertEqual(self.b.character, 'claude')
        self.assertEqual(self.b.event['type'], 'cancel')


class UsageBouts(unittest.TestCase):
    def test_both_working_means_clashes(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'working', 30.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'working', 40.0)])}
        cfg, atl, brains = placed(4, bout_min_s=999, bout_max_s=999, clash_min_s=3, clash_max_s=4)
        kinds = []
        drive(brains, tele, 60, each=lambda now, b: brains[LEFT].script and (not kinds or kinds[-1] is not brains[LEFT].script) and kinds.append(brains[LEFT].script))
        self.assertTrue(kinds and all(s['kind'] == 'clash' for s in kinds))
        self.assertGreaterEqual(len(brains[LEFT].contact_log), 2)

    def test_one_asleep_means_no_bouts(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'idle', 30.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'sleeping', None)])}
        cfg, atl, brains = placed(4, bout_min_s=2, bout_max_s=3, clash_min_s=2, clash_max_s=3)
        drive(brains, tele, 60)
        self.assertEqual(list(brains[LEFT].contact_log) + list(brains[RIGHT].contact_log), [])

    def test_both_idle_means_an_occasional_bout(self):
        cfg, atl, brains = placed(3, bout_min_s=5, bout_max_s=6)
        drive(brains, idle_tele(), 40)
        self.assertGreater(len(brains[LEFT].contact_log), 0)

    def test_specials_and_supers_come_from_the_atlas_signature(self):
        lib = Library()
        sig = lib['claude'].signature()
        self.assertEqual({k: sig[k] for k in ('strike', 'special', 'super')}, {'strike': 'spin_kick', 'special': 'slash_wave', 'super': 'reverse'})
        self.assertIn(sig['ultimate'], (None, 'radiant_beam'))               # None until the V4 art build lands
        self.assertEqual(lib['codex'].signature()['special'], 'deploy')
        brains, _, _ = sim.run(40, idle_tele(), seed=4, cfg_over={'bout_min_s': 5, 'bout_max_s': 6, 'bout_kinds': ['ranged']}, place=PLACE)
        fired = {p['move'] for b in brains.values() if b.script for p in b.script['projs']} | {n for b in brains.values() for _, n in b.hit_log}
        self.assertTrue(fired)

    def test_every_roster_pair_can_play_every_bout(self):
        from minis_core.atlas import available
        from minis_core.brain import kind_possible
        lib = Library()
        chars = available()
        self.assertIn('claude', chars)
        for c1 in chars:
            self.assertEqual(lib[c1].character, c1)
            for c2 in chars:
                by_slot = {LEFT: lib[c1], RIGHT: lib[c2]}
                for kind, extra in (('spar', {}), ('clash', {}), ('ranged', {}), ('handoff', {'giver': RIGHT, 'taker': LEFT}),
                                    ('console', {'visitor': LEFT})):
                    plan = dict(kind=kind, left=LEFT, right=RIGHT, pos={LEFT: 300, RIGHT: 450}, t0=10.0, seed=3,
                                chars={LEFT: c1, RIGHT: c2}, **extra)
                    self.assertTrue(kind_possible(kind, by_slot, plan), (c1, c2, kind))
                    tl, t_end, _ = make_timeline(kind, plan, lib)
                    self.assertGreater(t_end, 10.0)

    def test_a_character_without_a_super_never_plays_one(self):
        cfg, atl, brains = placed(1, **QUIET)
        b = brains[LEFT]
        b.sig = dict(b.sig, super=None)
        seen = set()
        for i in range(600):
            b.tick(1000 + i / 10, snap('idle', 20.0), None)
            seen.add(b.anim)
        self.assertNotIn('reverse', seen)
        self.assertIn('idle_flourish', seen)


RIVAL_FAST = dict(QUIET, rival_min=0.05, rival_max=0.05, rival_spar_min=0.05, rival_spar_max=0.05)   # 3 s, in minutes


def rival_pair(seed=4, left_state='idle', right_slot_sleeps=True, **over):
    """LEFT awake (idle by default), RIGHT asleep - or the other way round - with the rival timers at 3 s."""
    sleeper, awake = (RIGHT, LEFT) if right_slot_sleeps else (LEFT, RIGHT)
    tele = {awake: sim.FakeTelemetry(awake, [(0, left_state, 30.0)]), sleeper: sim.FakeTelemetry(sleeper, [(0, 'sleeping', None)])}
    cfg, atl, brains = placed(seed, **dict(RIVAL_FAST, **over))
    recs = []
    for b in brains.values():
        b.record = lambda w, l, **kw: recs.append((w, l))
    return brains, tele, recs, sleeper, awake


def trace(brains, tele, secs, until=None, t0=1000.0, fps=10):
    """-> (anims per slot as [(t, anim)], distinct bout plans seen - sent or playing).  Stops early when `until(now)` holds."""
    anims = {LEFT: [], RIGHT: []}
    plans = []
    bus_ = {}
    for i in range(int(secs * fps)):
        now = t0 + i / fps
        sim.step(brains, tele, now, bus_)
        for w, b in brains.items():
            if not anims[w] or anims[w][-1][1] != b.anim:
                anims[w].append((now, b.anim))
            sc = b.script or b.pending
            if sc and (not plans or plans[-1] is not sc['plan']):
                plans.append(sc['plan'])
        if until and until(now):
            break
    return anims, plans


class Rival(unittest.TestCase):
    """V5.1 rival mode: a sleeping partner is woken for a best-of-3 now and then, fights, and goes back to sleep."""

    def test_sleeper_is_woken_for_a_match_fights_and_sleeps_again(self):
        brains, tele, recs, sleeper, awake = rival_pair()
        b = brains[sleeper]
        anims, plans = trace(brains, tele, 300, until=lambda now: recs and b.mode == 'home' and b.anim == 'sleep')
        self.assertTrue(plans and plans[0]['kind'] == 'match' and plans[0].get('rival') and plans[0]['wake'] == sleeper, plans[:1])
        names = [a for _, a in anims[sleeper]]
        self.assertIn('wake', names)
        self.assertLess(names.index('wake'), names.index('walk'), names)              # stretch and yawn, then walk out
        self.assertGreaterEqual(len(brains[sleeper].hit_log) + len(brains[awake].hit_log), 2)
        self.assertEqual(len(recs), 1)                                                   # W/L recorded as usual, once
        self.assertEqual(set(recs[0]), {'claude', 'codex'})
        self.assertEqual((b.mode, b.anim, b.script, b.bout), ('home', 'sleep', None, None))   # back home, asleep
        self.assertTrue(b.view(b.last_now)['dim'])
        self.assertEqual(b.state(), 'sleeping')                                          # the plate kept telling the truth

    def test_the_plan_leaves_time_for_the_wake(self):
        brains, tele, recs, sleeper, awake = rival_pair()
        plans = trace(brains, tele, 20)[1]
        self.assertTrue(plans)
        p = plans[0]
        sent = p['deadline'] - CFG['invite_window_s']
        wake = brains[awake].wake_s('codex')
        self.assertGreater(wake, 0.5)
        walk_max = (brains[awake].zone[1] - brains[awake].zone[0]) / CFG['walk_px_s']
        self.assertGreaterEqual(p['t0'] - sent, 1.0 + wake)                             # the normal lead plus the wake
        self.assertLessEqual(p['t0'] - sent, 1.0 + wake + walk_max)
        self.assertGreater(brains[sleeper].hold_until, sent)                             # it stood still for the wake

    def test_sleeper_is_lit_while_it_fights_and_dim_at_home(self):
        brains, tele, recs, sleeper, awake = rival_pair()
        dims = []
        drive(brains, tele, 60, each=lambda now, bus_: dims.append((brains[sleeper].mode, brains[sleeper].view(now)['dim'])))
        self.assertIn(('home', True), dims)
        self.assertIn(('script', False), dims)
        self.assertNotIn(('script', True), dims)

    def test_a_working_fighter_gets_short_exchanges_not_matches(self):
        brains, tele, recs, sleeper, awake = rival_pair(left_state='working')
        plans = trace(brains, tele, 90)[1]
        self.assertTrue(plans)
        self.assertEqual({p['kind'] for p in plans}, {'clash'})
        self.assertTrue(all(p.get('rival') for p in plans))
        self.assertEqual(recs, [])

    def test_the_awake_fighter_in_slot_b_starts_the_rival_bout(self):
        brains, tele, recs, sleeper, awake = rival_pair(right_slot_sleeps=False)
        self.assertEqual((sleeper, awake), (LEFT, RIGHT))
        plans = trace(brains, tele, 90)[1]
        self.assertTrue(plans and plans[0]['kind'] == 'match' and plans[0]['wake'] == LEFT)
        self.assertEqual(plans[0]['id'].split(':')[0], brains[RIGHT].run)               # invited by the right side
        self.assertGreaterEqual(len(recs), 1)

    def test_rival_off_means_the_sleeper_is_left_alone(self):
        brains, tele, recs, sleeper, awake = rival_pair()
        for b in brains.values():
            b.rival = False
        anims, plans = trace(brains, tele, 90)
        self.assertEqual(plans, [])
        self.assertEqual([a for _, a in anims[sleeper]], ['sleep'])

    def test_sleeper_does_not_accept_when_the_toggle_is_off_on_its_side(self):
        brains, tele, recs, sleeper, awake = rival_pair()
        brains[sleeper].rival = False                                                     # e.g. control.json read a beat later
        plans = trace(brains, tele, 30)[1]
        self.assertTrue(plans)                                                            # the invite went out ...
        self.assertEqual(len(recs), 0)                                                    # ... and nobody came
        self.assertEqual(brains[sleeper].anim, 'sleep')

    def test_default_timers_are_minutes_so_a_sleeper_stays_asleep_for_a_while(self):
        brains, tele, recs, sleeper, awake = rival_pair(rival_min=8, rival_max=15, rival_spar_min=3, rival_spar_max=6)
        anims, plans = trace(brains, tele, 120)
        self.assertEqual(plans, [])
        self.assertGreaterEqual(brains[awake].next_rival - 1000.0, 8 * 60)
        self.assertLessEqual(brains[awake].next_rival - 1000.0, 15 * 60)


class Placement(unittest.TestCase):
    """Bug report, 2026-10-13: the two fighters stood on top of each other.  Root cause: a fighter knocked out (limit) mid-bout
    stayed where it fell, a limit fighter was forbidden from walking at all, and nothing ever sent a working fighter back
    to its own half; the partner's wander range covered that spot."""

    def fresh(self, seed=1, **over):
        cfg, atl, brains = sim.make(seed, dict(CFG, **dict(QUIET, **over)), 1000.0)
        return brains[LEFT], brains[RIGHT]

    def test_homes_are_disjoint_halves_of_the_fighting_zone(self):
        a, b = self.fresh()
        self.assertGreaterEqual(b.home[0] - a.home[1], 40)
        self.assertGreater(a.home[0], a.zone[0])
        self.assertLess(b.home[1], b.zone[1])
        self.assertTrue(a.home[0] <= a.x <= a.home[1] and b.home[0] <= b.x <= b.home[1])

    def test_knocked_out_mid_bout_walks_back_to_its_own_half(self):
        a, b = self.fresh()
        a.tick(1000.0, snap('working'), b.publish())
        b.tick(1000.0, snap('idle'), a.publish())
        a.x = b.x - 10                                          # where a bout or an old drag left it, in b's half
        a.tick(1000.1, snap('limit', 95.0, ['limit']), b.publish())
        self.assertEqual(a.anim, 'ko')
        for i in range(2, 400):                                 # KO, get up, then stagger home
            now = 1000 + i / 10
            a.tick(now, snap('limit', 95.0), b.publish())
            b.tick(now, snap('idle'), a.publish())
        self.assertTrue(a.home[0] - 2 <= a.x <= a.home[1] + 2, a.x)
        self.assertEqual(a.mode, 'home')

    def test_a_limit_fighter_walking_home_keeps_walking(self):
        a, b = self.fresh()
        a.tick(1000.0, snap('limit', 95.0), None)
        a.x = a.home[1] + 100
        for i in range(1, 300):
            a.tick(1000 + i / 10, snap('limit', 95.0), None)
        self.assertLessEqual(a.x, a.home[1] + 2)

    def test_working_fighter_far_from_home_returns(self):
        a, b = self.fresh()
        a.x = b.home[0] + 30
        for i in range(0, 400):
            a.tick(1000 + i / 10, snap('working', 40.0), None)
        self.assertTrue(a.home[0] - 2 <= a.x <= a.home[1] + 2, a.x)

    def test_drag_stays_in_its_own_half_and_pause_does_not_move_home(self):
        a, b = self.fresh()
        a.tick(1000.0, snap(), None)
        a.drag_to(b.home[1], 1000.1)
        self.assertEqual(a.x, a.home[1])
        hx = a.home_x
        a.x = a.home[1] + 50
        a.set_paused(True, 1000.2)
        self.assertEqual(a.home_x, hx)

    def test_bouts_happen_in_the_middle_of_the_fighting_zone(self):
        a, b = self.fresh()
        a.tick(1000.0, snap(), b.publish())
        b.tick(1000.0, snap(), a.publish())
        pa = invite_from(a, b, 'spar', 1000.0)
        mid = (a.zone[0] + a.zone[1]) / 2.0
        pos = pa['event']['plan']['pos']
        self.assertAlmostEqual((pos[LEFT] + pos[RIGHT]) / 2.0, mid, delta=0.01)
        self.assertLess(pos[LEFT], pos[RIGHT])

    def test_fighters_stay_apart_through_a_long_mixed_run(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'working', 40.0), (40, 'idle', 92.0), (80, 'working', 50.0)]),
                RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', None), (60, 'working', None)])}
        cfg, atl, brains = sim.make(6, dict(CFG, clash_min_s=8, clash_max_s=12, bout_min_s=10, bout_max_s=15), 1000.0)
        closest, bouts = [999.0], set()

        def each(now, bus_):
            if not any(br.bout or br.mode == 'script' for br in brains.values()):
                closest[0] = min(closest[0], abs(brains[LEFT].x - brains[RIGHT].x))
            for br in brains.values():
                if br.script:
                    bouts.add(br.script['kind'])
        drive(brains, tele, 150, each=each)
        self.assertGreaterEqual(closest[0], 20)
        self.assertIn('clash', bouts)
        self.assertIn('console', bouts)


class Liveliness(unittest.TestCase):
    def test_one_working_one_idle_still_clash(self):
        """The author's usual case (Claude working, Gemini idle) used to start no bout at all."""
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'working', 40.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', None)])}
        cfg, atl, brains = sim.make(4, dict(CFG, clash_min_s=5, clash_max_s=8), 1000.0)
        kinds = []
        drive(brains, tele, 60, each=lambda now, b: brains[LEFT].script and brains[LEFT].script['kind'] not in kinds
              and kinds.append(brains[LEFT].script['kind']))
        self.assertEqual(kinds, ['clash'])
        self.assertTrue(any(n in ('fistbump',) for _, n in brains[RIGHT].contact_log))

    def test_working_fighter_shadowboxes(self):
        cfg, atl, brains = sim.make(2, dict(CFG, **QUIET), 1000.0)
        a = brains[LEFT]
        seen = set()
        for i in range(0, 300):
            a.tick(1000 + i / 10, snap('working', 40.0), None)
            seen.add(a.anim)
        self.assertTrue(seen & set(('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse', 'spin_kick')), seen)
        self.assertTrue(seen & {'work', 'type'})

    def test_knocked_out_partner_gets_visited_again(self):
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'idle', 95.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 30.0)])}
        cfg, atl, brains = sim.make(3, dict(CFG, console_min_s=10, console_max_s=12, **QUIET), 1000.0)
        n = [0]
        prev = [None]

        def each(now, bus_):
            s = brains[RIGHT].script
            if s and s is not prev[0] and s['kind'] == 'console':
                n[0] += 1
            prev[0] = s
        drive(brains, tele, 60, each=each)
        self.assertGreaterEqual(n[0], 2)

    def test_demo_bout_starts_whatever_the_states(self):
        a, b = pair()
        a.tick(1000.0, snap('limit', 95.0), b.publish())          # knocked out ...
        b.tick(1000.0, snap('working', 40.0), a.publish())        # ... and busy: no timed bout would ever start
        a.request_demo('spar', 1000.0)
        t = 1000.0
        kinds = set()
        for i in range(1, 200):
            t = 1000 + i / 10
            a.tick(t, snap('limit', 95.0), b.publish())
            b.tick(t, snap('working', 40.0), a.publish())
            for br in (a, b):
                if br.script:
                    kinds.add((br.slot, br.script['kind'], br.script['plan'].get('demo')))
        self.assertEqual(kinds, {(LEFT, 'spar', True), (RIGHT, 'spar', True)})
        self.assertIsNone(a.demo)
        self.assertEqual(a.snap.state, 'limit')                    # the plate still shows the real state

    def test_demo_expires_when_the_partner_never_comes(self):
        a, b = pair()
        a.tick(1000.0, snap(), None)
        a.request_demo('ranged', 1000.0, wait_s=5.0)
        for i in range(1, 100):
            a.tick(1000 + i / 10, snap(), None)
        self.assertIsNone(a.demo)
        self.assertIsNone(a.script)


class Away(unittest.TestCase):
    """A fighter the user hid (`minis.py hide`, the scoreboard) is away: no bout starts with it, demo or timed, and a bout
    already running stops.  Seen live 2026-10-22: the visible fighter fought, and was K.O.'d by, an invisible opponent."""

    def run_pair(self, a, b, t0, secs):
        bouts = set()
        for i in range(int(secs * 10)):
            t = t0 + i / 10
            a.tick(t, snap('idle', 30.0), b.publish())
            b.tick(t, snap('idle', 30.0), a.publish())
            for br in (a, b):
                if br.script:
                    bouts.add(br.slot)
        return bouts

    def test_no_demo_bout_against_a_hidden_fighter(self):
        a, b = pair()
        b.away = True
        a.request_demo('match', 1000.0)
        self.assertEqual(self.run_pair(a, b, 1000.0, 20), set())
        self.assertIsNone(a.demo)                                       # the request expired; nothing queued for later

    def test_no_timed_bout_while_away_and_bouts_resume_after_show(self):
        a, b = pair(2, bout_min_s=1, bout_max_s=2)
        b.away = True
        self.assertEqual(self.run_pair(a, b, 1000.0, 60), set())
        b.away = False
        self.assertTrue(self.run_pair(a, b, 1060.0, 90))

    def test_hiding_mid_bout_stops_it_on_both_sides(self):
        a, b = pair()
        a.request_demo('spar', 1000.0)
        t = 1000.0
        for i in range(1, 200):
            t = 1000 + i / 10
            a.tick(t, snap(), b.publish())
            b.tick(t, snap(), a.publish())
            if a.script and b.script:
                break
        self.assertTrue(a.script and b.script, 'the demo bout never started')
        b.away = True
        for i in range(1, 30):
            a.tick(t + i / 10, snap(), b.publish())
            b.tick(t + i / 10, snap(), a.publish())
        self.assertIsNone(a.script)
        self.assertIsNone(b.script)
        self.assertFalse(a.bout or b.bout)


class Pause(unittest.TestCase):
    def test_paused_fighter_is_one_static_frame_and_never_moves(self):
        a, b = pair(2, bout_min_s=1, bout_max_s=2)
        a.set_paused(True, 1000.0)
        b.set_paused(True, 1000.0)
        frames, xs = set(), set()
        for i in range(300):
            now = 1000 + i / 10
            a.tick(now, snap('working', 50.0, ['finished'] if i == 5 else []), b.publish())
            b.tick(now, snap('idle', 30.0), a.publish())
            v = a.view(now)
            frames.add((v['anim'], v['frame']))
            xs.add(round(a.x, 2))
        self.assertEqual(frames, {('idle', 0)})
        self.assertEqual(len(xs), 1)
        self.assertIsNone(a.script)
        self.assertTrue(a.publish()['paused'])

    def test_pausing_mid_bout_cancels_it_and_resume_animates_again(self):
        a, b = pair()
        a.tick(1000.0, snap(), None)
        b.tick(1000.0, snap(), None)
        pa = invite_from(a, b, 'spar', 1000.0)
        b.tick(1000.2, snap(), pa)
        b.set_paused(True, 1000.3)
        self.assertEqual(b.event['type'], 'cancel')
        self.assertIsNone(b.script)
        b.set_paused(False, 1001.0)
        b.tick(1001.1, snap('working', 40.0), None)
        self.assertIn(b.anim, ('work', 'type'))


# ====================================================================== atlas
class Atlases(unittest.TestCase):
    def test_every_move_has_frames_and_timing(self):
        for ch in ('claude', 'codex'):
            a = Atlas(ch)
            self.assertGreaterEqual(len(a.anim), 45)
            for name, m in a.anim.items():
                self.assertTrue(m['frames'], name)
                self.assertTrue(all(f['ms'] >= 40 for f in m['frames']), name)

    def test_loop_range_plays_intro_once_then_loops(self):
        a = Atlas('claude')
        idx = lambda ms: a.locate('block', ms, True)[0]
        self.assertEqual(idx(10), 0)
        self.assertIn(idx(60 + 120 + 5000), (1, 2))

    def test_projectile_specials_have_spawn_data(self):
        self.assertIn('proj_frame', Atlas('claude').anim['slash_wave'])
        self.assertIn('proj_frame', Atlas('codex').anim['deploy'])

    def test_attacks_have_reach_and_hit_frames(self):
        for ch in ('claude', 'codex'):
            a = Atlas(ch)
            for n in ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse'):
                self.assertIn('hit_frame', a.anim[n])
                self.assertGreater(a.anim[n]['reach'], 8, n)

    def test_bad_frame_index_and_unknown_anim_draw_a_real_frame(self):
        a = Atlas('claude')
        n = len(a.anim['jab']['frames'])
        self.assertEqual(a.frame_image('jab', 99, 1).tobytes(), a.frame_image('jab', n - 1, 1).tobytes())
        self.assertEqual(a.frame_image('jab', -3, 1).tobytes(), a.frame_image('jab', 0, 1).tobytes())
        self.assertEqual(a.frame_image('no_such_move', 2, -1).size, a.cell)
        self.assertEqual(a.locate('no_such_move', 100, True), (0, True))

    def test_projectile_frame_count_comes_from_metadata(self):
        a = Atlas('claude')
        a.proj_frames = 2
        a._pcrop.clear()
        self.assertEqual(a.proj_image(2, 1).tobytes(), a.proj_image(0, 1).tobytes())
        self.assertIs(a.proj_image(1, -1), a.proj_image(3, -1))           # cached

    def test_validation_rejects_zero_totals_and_bad_loop_ranges(self):
        good = json.loads((ROOT / 'assets' / 'claude' / 'anim.json').read_text(encoding='utf-8'))
        validate(good)
        for mutate in (lambda m: m['anims']['idle'].update(frames=[]),
                       lambda m: m['anims']['jab']['frames'][0].update(ms=0),
                       lambda m: m['anims']['block'].update(loop_range=[2, 99]),
                       lambda m: m['anims']['block'].update(loop_range=[3, 1]),
                       lambda m: m['anims'].pop('idle')):
            m = json.loads(json.dumps(good))
            mutate(m)
            with self.assertRaises(AtlasError):
                validate(m)

    def test_unknown_and_broken_characters_fall_back(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(ROOT / 'assets' / 'claude', tmp / 'claude')
        shutil.copytree(ROOT / 'assets' / 'codex', tmp / 'broken')
        m = json.loads((tmp / 'broken' / 'anim.json').read_text(encoding='utf-8'))
        m['anims']['idle']['frames'] = []
        (tmp / 'broken' / 'anim.json').write_text(json.dumps(m), encoding='utf-8')
        lib = Library(tmp)
        self.assertEqual(lib['nobody'].character, 'claude')               # no generic here: claude
        self.assertEqual(lib['broken'].character, 'claude')
        self.assertIn('broken', lib.errors)
        self.assertEqual(resolve('nobody', tmp), 'claude')
        self.assertEqual(resolve('claude', tmp), 'claude')
        shutil.copytree(ROOT / 'assets' / 'codex', tmp / 'generic')
        self.assertEqual(resolve('nobody', tmp), 'generic')

    def test_signature_metadata_wins_and_unknown_atlases_get_a_safe_fallback(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(ROOT / 'assets' / 'codex', tmp / 'zed')
        m = json.loads((tmp / 'zed' / 'anim.json').read_text(encoding='utf-8'))
        m.update(character='zed', tag='zed!', accent='#10ff20')
        m.pop('signature', None)
        (tmp / 'zed' / 'anim.json').write_text(json.dumps(m), encoding='utf-8')
        a = Atlas('zed', tmp / 'zed')
        self.assertEqual(a.signature(), {'strike': None, 'special': 'deploy', 'super': None, 'ultimate': None})   # first move with proj_frame, no super
        self.assertEqual((a.tag, a.accent), ('zed!', (16, 255, 32)))
        m['signature'] = {'strike': 'jab', 'special': 'deploy', 'super': 'sudo'}
        (tmp / 'zed' / 'anim.json').write_text(json.dumps(m), encoding='utf-8')
        self.assertEqual(Atlas('zed', tmp / 'zed').signature(), {'strike': 'jab', 'special': 'deploy', 'super': 'sudo', 'ultimate': None})


# ====================================================================== render
class Render(unittest.TestCase):
    BOUNDS = (4, 936)

    def view(self, x, facing):
        return dict(anim='idle', frame=0, x=x, facing=facing, dim=False, proj=None)

    def test_plate_stays_inside_bounds_and_off_the_sprite_at_both_edges(self):
        a = Atlas('claude')
        s = Snapshot('claude', 'idle', 40.0)
        for x in (self.BOUNDS[0] + 8, self.BOUNDS[1] - 8, 470):
            for facing in (1, -1):
                pw = render.PLATE_W
                px = render.plate_x(x, facing, pw, self.BOUNDS)
                self.assertGreaterEqual(px, self.BOUNDS[0], (x, facing))
                self.assertLessEqual(px + pw, self.BOUNDS[1], (x, facing))
                self.assertTrue(px + pw <= x - 18 or px >= x + 18, f'plate over the sprite at x={x} facing={facing}')
                canvas, x0 = render.compose(a, a, self.view(x, facing), s, 0.0, CFG, bounds=self.BOUNDS)
                sprite_l = x - a.anchor(facing)
                self.assertEqual(x0, min(sprite_l, px))
                self.assertEqual(canvas.width, max(sprite_l + 64, px + pw) - x0)

    def test_plate_prefers_behind_the_fighter(self):
        self.assertEqual(render.plate_x(470, 1, 128, self.BOUNDS), 470 - 18 - 128)
        self.assertEqual(render.plate_x(470, -1, 128, self.BOUNDS), 470 + 18)

    def test_bar_segments_follow_the_rounded_label(self):
        self.assertEqual(render.filled_segments(55.0), 6)          # half-up, like the label's 55%
        self.assertEqual([render.filled_segments(v) for v in (45.0, 65.0, 64.0, 5.0)], [5, 7, 6, 1])   # never banker's rounding
        self.assertEqual(render.filled_segments(None), 0)
        self.assertEqual(render.filled_segments(64.6), render.filled_segments(65.4))     # both label "65%"
        self.assertEqual(render.filled_segments(100.0), 10)
        a = Atlas('claude')

        def lit(ctx):
            im = render.plate(a, Snapshot('claude', 'idle', ctx), 0.0)
            return sum(1 for i in range(10) if im.getpixel((5 + i * 4 + 1, 18))[:3] != render.TRACK)
        self.assertEqual(lit(55.0), 6)
        self.assertEqual(lit(None), 0)

    def test_red_blink_runs_at_90_percent_whatever_the_state(self):
        s = Snapshot('claude', 'working', 93.0)
        self.assertNotEqual(render.blink_phase(s, 0.0), render.blink_phase(s, 0.5))
        a = Atlas('claude')
        p0, p1 = render.plate(a, s, 0.0), render.plate(a, s, 0.5)
        self.assertNotEqual(p0.tobytes(), p1.tobytes())
        self.assertEqual(render.blink_phase(Snapshot('claude', 'working', 50.0), 0.5), 0)

    def test_long_tags_and_labels_fit_the_plate(self):
        from PIL import ImageDraw
        a = Atlas('claude')
        a2 = type('A', (), {'tag': 'lmstudio-super-long-tag', 'accent': (1, 2, 3)})()
        im = render.plate(a2, Snapshot('x', 'waiting', 100.0, 100.0, 'wk'), 0.0)
        self.assertEqual(im.size, (render.PLATE_W, render.PLATE_H))
        d = ImageDraw.Draw(im)
        self.assertLessEqual(d.textlength(render._fit(d, 'lmstudio-super-long-tag', 60, 10, True), font=render.font(10, True)), 60)
        self.assertEqual(render.style_of(a), ('Claude', a.accent))                    # the plate names the program
        self.assertEqual(render.style_of(a2), ('lmstudio-super-long-tag', (1, 2, 3)))  # no display: the tag is the fallback

    def test_plate_shows_the_name_not_the_sigil(self):
        a = Atlas('claude')
        s = Snapshot('claude', 'idle', 40.0)
        by_name = render.plate(a, s, 0.0)
        self.assertEqual(by_name.tobytes(), render.plate(a, s, 0.0, name='Claude').tobytes())
        self.assertNotEqual(by_name.tobytes(), render.plate(a, s, 0.0, name='/reverse').tobytes())

    def test_plate_strip_and_fighting_zone_never_meet(self):
        from minis_core import config as cfgmod
        a_l, b_l = cfgmod.plate_left(CFG, 'a'), cfgmod.plate_left(CFG, 'b')
        self.assertEqual(a_l, CFG['zone'][0])
        self.assertGreaterEqual(b_l, a_l + render.PLATE_W)                  # side by side, not overlapping
        from minis_core import scoreboard
        for size in (64, 96, 128):                                          # V7.1: the clearance scales with the fighter size
            z0, z1 = cfgmod.fight_zone(CFG, size)
            reach = cfgmod.SPRITE_REACH * size / 64.0                       # widest sprite pixel from the hip, any character
            self.assertGreater(z0 - reach, b_l + render.PLATE_W, size)
            self.assertLess(z1 + reach, scoreboard.left_x(CFG), size)      # the scoreboard sits at the right end
            self.assertEqual(round(z1 + reach + cfgmod.HUD_GAP), scoreboard.left_x(CFG), size)
        self.assertEqual(cfgmod.fight_zone(dict(CFG, scoreboard=False))[1], CFG['zone'][1] - cfgmod.clearance_px(64))
        self.assertEqual(scoreboard.left_x(CFG) + scoreboard.W, CFG['zone'][1] + 36)   # just left of the icon cluster


if __name__ == '__main__':
    unittest.main()
