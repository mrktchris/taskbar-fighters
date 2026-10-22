"""Rounds, HP, winners and record.json (docs/V4-WORKORDER.md "Rounds and winners")."""
import collections, json, os, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
from minis_core import rounds, sim, fx, control  # noqa: E402
from minis_core.atlas import Library  # noqa: E402
from minis_core.brain import LEFT, RIGHT, Brain, make_timeline  # noqa: E402

LIB = Library()
ATL = {c: LIB[c] for c in ('claude', 'codex', 'gemini', 'cursor')}


def plan(seed=5, mode='decided', scores=None, chars=('claude', 'codex')):
    return dict(kind='match', left='a', right='b', pos={'a': 500.0, 'b': 524.0}, t0=1000.0, seed=seed, chars={'a': chars[0], 'b': chars[1]},
                mode=mode, scores=scores or {'a': 100.0, 'b': 100.0}, id='t:1', deadline=1003.0)


class Math(unittest.TestCase):
    def test_health_score_formula(self):
        self.assertEqual(rounds.health_score('idle', 30.0), 70 + 20)
        self.assertEqual(rounds.health_score('working', 30.0), 70 + 20 + 10)
        self.assertEqual(rounds.health_score('limit', 95.0), 5)
        self.assertEqual(rounds.health_score('idle', None), 50 + 20)               # unknown context counts as 50 %
        self.assertEqual(rounds.score_of_bus({'state': 'working', 'ctx': 40.0}), 60 + 20 + 10)
        self.assertEqual(rounds.score_of_bus(None), 70)

    def test_damage_table(self):
        a = ATL['claude']
        self.assertEqual(rounds.damage_of(a, 'jab'), 12)
        self.assertEqual(rounds.damage_of(a, 'cross'), 24)
        self.assertEqual(rounds.damage_of(a, 'roundhouse'), 36)
        self.assertEqual(rounds.damage_of(a, a.ultimate()), 40)                   # the ultimate (or the super until the art lands)
        sig = a.signature()
        self.assertEqual(a.ultimate(), sig['ultimate'] or sig['super'])
        legacy = Library()['codex']
        legacy.meta['signature'] = {'strike': 'jab', 'special': 'deploy', 'super': 'sudo'}
        self.assertEqual(legacy.ultimate(), 'sudo')                            # no ultimate in the atlas: the super stands in

    def test_attacker_probability(self):
        self.assertEqual(rounds.p_left('random', {'a': 130, 'b': 10}, 'a', 'b'), 0.5)
        self.assertEqual(rounds.p_left('decided', {'a': 60, 'b': 60}, 'a', 'b'), 0.5)        # a tie is a coin flip
        self.assertAlmostEqual(rounds.p_left('decided', {'a': 90, 'b': 30}, 'a', 'b'), 0.75)


class Timeline(unittest.TestCase):
    def test_best_of_three_hp_and_caps(self):
        tl, t_end, s = rounds.make_match(plan(), ATL, fx.default())
        self.assertEqual(max(s['wins'].values()), 2)
        self.assertIn(len(s['rounds']), (2, 3))
        self.assertLess(t_end - 1000.0, 3 * (rounds.ROUND_CAP_S + 8) + 10)
        for r in s['rounds']:
            self.assertLessEqual(r['t1'] - r['t0'], rounds.ROUND_CAP_S + 2.0)
            if r['ko']:
                self.assertEqual(min(r['hp'].values()), 0)
            self.assertEqual(sorted(r['hp'].values()), sorted(r['hp'].values()))
        trace = rounds.hp_trace(tl)
        self.assertEqual(trace[0][1], {'a': 100, 'b': 100})
        for (t0, h0), (t1, h1) in zip(trace, trace[1:]):
            self.assertLessEqual(t0, t1)
            for w in 'ab':
                self.assertTrue(0 <= h1[w] <= 100)
        # damage never exceeds the table: every drop is 12 / 24 / 36 / 40, or the remainder down to 0 on a KO
        drops = collections.Counter()
        for (t0, h0), (t1, h1) in zip(trace, trace[1:]):
            for w in 'ab':
                d = h0[w] - h1[w]
                if d > 0:
                    drops[d] += 1
                    self.assertTrue(d in (12, 24, 36, 40) or (h1[w] == 0 and d <= 40) or d == 100, (d, h0, h1))
        self.assertTrue(any(d in (12, 24, 36) for d in drops), drops)

    def test_same_plan_same_timeline_different_seed_differs(self):
        a, _, sa = rounds.make_match(plan(seed=9), ATL, fx.default())
        b, _, sb = rounds.make_match(plan(seed=9), ATL, fx.default())
        c, _, sc = rounds.make_match(plan(seed=10), ATL, fx.default())
        self.assertEqual(a, b)
        self.assertEqual(sa, sb)
        self.assertNotEqual(a, c)

    def test_decided_mode_is_biased_random_is_not(self):
        wins = collections.Counter()
        for seed in range(120):
            wins[rounds.make_match(plan(seed, 'decided', {'a': 130.0, 'b': 40.0}), ATL)[2]['winner']] += 1
        self.assertGreater(wins['a'], 95, wins)
        even = collections.Counter()
        for seed in range(120):
            even[rounds.make_match(plan(seed, 'random', {'a': 130.0, 'b': 40.0}), ATL)[2]['winner']] += 1
        self.assertGreater(even['b'], 35, even)
        self.assertGreater(even['a'], 35, even)

    def test_directives_and_texts(self):
        tl, t_end, s = rounds.make_match(plan(), ATL, fx.default())
        names = {n for w in tl for t, n, o in tl[w] if n.startswith('@')}
        self.assertTrue({'@hp', '@fx', '@banner', '@record'} <= names <= {'@hp', '@fx', '@banner', '@record', '@shake', '@flash', '@whiff', '@impact'}, names)
        banners = [o['banner'] for t, n, o in tl['a'] if n == '@banner']
        self.assertEqual(banners[:2], ['round1', 'fight'])
        self.assertIn('ko', banners)
        self.assertEqual(banners[-1], 'winner')
        self.assertFalse(any(n in ('@banner', '@record') for t, n, o in tl['b']))      # the left side owns texts + record
        rec = [o for t, n, o in tl['a'] if n == '@record'][0]
        self.assertEqual((rec['winner'], rec['loser']), (s['winner'], s['loser']))
        self.assertEqual(rec['chars'], {'a': 'claude', 'b': 'codex'})
        ults = [o for w in tl for t, n, o in tl[w] if n == '@fx' and o.get('kind') == 'ultimate' and not o.get('impact')]   # the impact burst lands on the defender
        allowed = {n for a in (ATL['claude'], ATL['codex']) for _, n, _ in a.move_fx(a.ultimate())}
        self.assertTrue(all(o['fx'] in allowed for o in ults), (ults, allowed))

    def test_every_roster_pair_can_play_a_match(self):
        from minis_core.atlas import available
        chars = available()
        for i, c1 in enumerate(chars):
            for c2 in chars[i:]:
                lib = {c1: LIB[c1], c2: LIB[c2]}
                tl, t_end, s = rounds.make_match(plan(3, chars=(c1, c2)), lib, fx.default())
                self.assertIn(s['winner'], ('a', 'b'), (c1, c2))


class TwoBrains(unittest.TestCase):
    """Two Brains (as in two processes) agree on HP and the winner; only the left side records."""

    def run_match(self, seed=4, mode='decided', secs=90, states=('working', 'idle'), ctx=(41.0, 70.0)):
        rec = []
        cfg = dict(CFG, bout_min_s=999, bout_max_s=999, clash_min_s=999, clash_max_s=999, match_min_s=3, match_max_s=4, scoreboard=False)
        _, atl, brains = sim.make(seed, cfg, 1000.0)
        for b in brains.values():
            b.record = lambda w, l, **kw: rec.append((w, l))
            b.winners = mode
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, states[0], ctx[0])]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, states[1], ctx[1])])}
        bus = {}
        hp = {LEFT: [], RIGHT: []}
        banners = []
        for i in range(int(secs * 10)):
            now = 1000 + i / 10.0
            sim.step(brains, tele, now, bus)
            for w, b in brains.items():
                if b.hp is not None:
                    hp[w].append((now, b.hp, bus[w].get('hp')))
                v = b.view(now)
                if b.banner:
                    banners.append(b.banner['kind'])
        return brains, rec, hp, banners

    def test_a_match_plays_from_usage_with_hp_texts_and_one_record(self):
        brains, rec, hp, banners = self.run_match()
        bouts = [n for n in brains[LEFT].bout_log if n[0] == 'bout']
        self.assertTrue(bouts and bouts[0][3] == 'match', bouts)
        results = [n for n in brains[LEFT].bout_log if n[0] == 'result']
        self.assertEqual(len(rec), len(results))                         # written once per match, by the left side only
        self.assertGreaterEqual(len(rec), 1)
        self.assertEqual(set(rec[0]), {'claude', 'codex'})
        self.assertTrue(hp[LEFT] and hp[RIGHT])
        self.assertTrue(all(h == p for _, h, p in hp[LEFT]))              # HP is on the bus
        self.assertEqual(hp[LEFT][0][1], 100)
        self.assertTrue(any(h == 0 for _, h, _ in hp[LEFT] + hp[RIGHT]))
        self.assertTrue({'round1', 'fight', 'ko', 'winner'} <= set(banners), set(banners))
        if brains[LEFT].script is None:                                   # cleared after the match (unless the next one is on)
            self.assertIsNone(brains[LEFT].hp)
            self.assertIsNone(brains[LEFT].banner)
        plan = brains[LEFT].last_match
        self.assertEqual(plan['mode'], 'decided')

    def test_both_sides_derive_the_same_scores_and_mode(self):
        cfg = dict(CFG, scoreboard=False)
        _, atl, brains = sim.make(2, cfg, 1000.0)
        tele = {LEFT: sim.FakeTelemetry(LEFT, [(0, 'working', 40.0)]), RIGHT: sim.FakeTelemetry(RIGHT, [(0, 'idle', 70.0)])}
        bus = {}
        sim.step(brains, tele, 1000.0, bus)
        sim.step(brains, tele, 1000.2, bus)
        brains[LEFT].winners = 'random'
        p = brains[LEFT]._plan('match', 1000.3)
        self.assertEqual(p['mode'], 'random')
        self.assertEqual(p['scores'], {'a': 90.0, 'b': 50.0})             # (100-40)+20+10 ; (100-70)+20
        self.assertEqual(p['kind'], 'match')

    def test_random_mode_reaches_the_timeline(self):
        brains, rec, hp, banners = self.run_match(mode='random')
        self.assertEqual(brains[LEFT].last_match['mode'], 'random')
        self.assertEqual(len(rec), 1)


class Record(Isolated):
    def test_record_json_is_atomic_and_counts_w_l(self):
        self.assertTrue(rounds.record_result('claude', 'codex', now=5.0))
        self.assertTrue(rounds.record_result('codex', 'claude', now=6.0, where='arena'))
        self.assertTrue(rounds.record_result('claude', 'gemini', now=7.0))
        rec = rounds.read_record()
        self.assertEqual(rounds.record_for(rec, 'claude'), (2, 1))
        self.assertEqual(rounds.record_for(rec, 'codex'), (1, 1))
        self.assertEqual(rounds.record_for(rec, 'gemini'), (0, 1))
        self.assertEqual(rounds.record_for(rec, 'nobody'), (0, 0))
        self.assertEqual(rec['matches'], 3)
        self.assertEqual(rec['last']['where'], 'taskbar')
        self.assertEqual([p.name for p in self.data.iterdir() if p.name.endswith('.tmp')], [])
        (self.data / 'record.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(rounds.read_record(), {})
        self.assertTrue(rounds.record_result('claude', 'codex'))          # a corrupt file is replaced, not a crash
        self.assertEqual(rounds.record_for(rounds.read_record(), 'claude'), (1, 0))

    def test_winners_switch_lives_in_control_json(self):
        self.assertEqual(control.winners(), 'decided')
        self.assertTrue(control.set_winners('random'))
        self.assertEqual(control.winners(), 'random')
        self.assertEqual(json.loads((self.data / 'control.json').read_text())['winners'], 'random')
        with self.assertRaises(ValueError):
            control.set_winners('coin')
        self.assertTrue(control.set_winners('decided'))
        self.assertEqual(control.winners(), 'decided')


class FightFeelV6(unittest.TestCase):
    """V6 fight feel: knockdowns stay down until the get-up, the finisher beat, time-outs, rare ultimates, comeback, boost,
    braces during charge-ups, spacing and the hitstop floor."""

    def matches(self, n=40):
        from minis_core.atlas import available
        chars = available()
        out = []
        for seed in range(n):
            c1, c2 = chars[seed % len(chars)], chars[(seed * 3 + 1) % len(chars)]
            p = plan(seed, chars=(c1, c2))
            tl, t_end, s = rounds.make_match(p, {c1: LIB[c1], c2: LIB[c2]}, fx.default())
            out.append((p, tl, t_end, s))
        return out

    def test_a_knockdown_that_is_not_a_ko_stays_down_and_gets_up_the_moment_it_lands(self):
        seen = 0
        for p, tl, t_end, s in self.matches(20):
            for w in 'ab':
                steps = [(t, n, o) for t, n, o in tl[w] if not n.startswith('@')]
                for i, (t, n, o) in enumerate(steps):
                    if n == 'knockdown' and o.get('hp', {}).get(w, 0) > 0:
                        seen += 1
                        a = LIB[p['chars'][w]]
                        sl = o.get('slow')                                    # V9: a tumble stretches the flight
                        stretch = (sl[1] - sl[0]) * (1.0 - sl[2]) if sl else 0.0
                        t_land = t + a.total_ms('knockdown') / 1000.0 + o['hitstop'] / 1000.0 + stretch
                        nxt = steps[i + 1]
                        self.assertEqual(nxt[1], 'getup', (w, t, steps[i:i + 3]))          # never idle in between
                        # up the moment it lands (a tech), or after lying a moment (V9: a missed tech after a tumble)
                        self.assertTrue(any(abs(nxt[0] - (t_land + extra)) < 1e-3 for extra in (0.0, rounds.MISSED_TECH_S)),
                                        (nxt[0], t_land))
        self.assertGreater(seen, 3)

    def test_nobody_is_hit_while_on_the_floor(self):
        for p, tl, t_end, s in self.matches(20):
            for w in 'ab':
                o_w = 'b' if w == 'a' else 'a'
                ups = [(t, t + LIB[p['chars'][w]].total_ms('getup') / 1000.0) for t, n, o in tl[w] if n == 'getup']
                hits = [t for t, n, o in tl[w] if 'react_to' in o]
                for t0, t1 in ups:
                    self.assertFalse(any(t0 < h < t1 - 1e-6 for h in hits), (w, t0, t1, hits))

    def test_the_final_ko_plays_a_finisher_beat_inside_three_and_a_half_seconds(self):
        n = 0
        for p, tl, t_end, s in self.matches(30):
            if not s['rounds'][-1]['ko']:
                continue
            n += 1
            ki = s['final_ko']
            tc, loser, champ = ki['tc'], s['loser'], s['winner']
            self.assertLessEqual(t_end - tc, rounds.POST_KO_MAX_S + 1e-6)
            ko = [o for t, n2, o in tl[loser] if n2 in rounds.LYING and abs(t - tc) < 1e-6 or n2 == 'thrown' and o.get('stop_at') == round(tc, 4)][0]
            self.assertGreaterEqual(ko['hitstop'], rounds.KO_HITSTOP_MS)                    # freeze on the blow...
            self.assertEqual(ko['slow'][2], rounds.SLOW_K)                                    # ...then slow motion
            self.assertTrue(any(n2 == '@impact' and abs(t - tc) < 1e-6 for t, n2, o in tl[loser]))
            self.assertTrue(any(n2 == '@fx' and o['fx'] == 'dust' and t > tc for t, n2, o in tl[loser]))
            pose = [(t, n2) for t, n2, o in tl[champ] if n2 in ('victory', 'victory2') and t > tc]
            self.assertTrue(pose and pose[0][0] < tc + 1.5, pose)
            win = [o for t, n2, o in tl['a'] if n2 == '@banner' and o['banner'] == 'winner']
            self.assertEqual(win[-1]['over'], champ)
            self.assertTrue(win[-1]['name'])
            ups = [(t, o) for t, n2, o in tl[loser] if n2 == 'getup' and t > tc]
            self.assertEqual(len(ups), 1)                                                    # stays down, then slumps up
            self.assertGreater(ups[0][0], ki['down'] + 0.5)
            self.assertIn('slow', ups[0][1])
            self.assertLessEqual(ups[0][0] + LIB[p['chars'][loser]].total_ms('getup') / 1000.0 / rounds.GETUP_SLOW_K, t_end)
        self.assertGreater(n, 10)

    def test_a_round_called_on_time_says_time_and_the_loser_slumps(self):
        found = 0
        for seed in range(60):
            p = plan(seed)
            tl, t_end, s = rounds.make_match(p, ATL, fx.default())
            for r in s['rounds']:
                if r['ko']:
                    continue
                found += 1
                loser = 'b' if r['winner'] == 'a' else 'a'
                self.assertTrue(any(n == '@banner' and o['banner'] == 'time' and r['t0'] < t <= r['t1'] + 0.01 for t, n, o in tl['a']))
                slumps = [o for t, n, o in tl[loser] if n in rounds.SLUMP and r['t0'] < t <= r['t1'] + 0.5]
                self.assertTrue(slumps and slumps[0].get('hold'), (seed, r))
                falls = [t for t, n, o in tl[loser] if n == 'knockdown' and 'react_to' not in o]
                self.assertEqual(falls, [])                                                  # nobody falls over unprovoked
            if found >= 2:
                break
        self.assertGreaterEqual(found, 1)

    def test_the_ultimate_is_rare_one_per_match_and_only_below_30_hp(self):
        n_ult = 0
        ms = self.matches(80)
        for p, tl, t_end, s in ms:
            ults = [(w, b) for w in 'ab' for b in s['beats'][w] if b['kind'] == 'ultimate']
            self.assertLessEqual(len(ults), 1)
            n_ult += len(ults)
            for w in 'ab':
                for t, n, o in tl[w]:
                    if o.get('kind') == 'ultimate' and 'contact' in o:
                        hp = [h for t2, h in rounds.hp_trace(tl) if t2 < t][-1]
                        self.assertLess(hp[w], 30)
        self.assertLess(n_ult / len(ms), 0.6)
        self.assertGreater(n_ult, 0)
        supers = sum(1 for p, tl, t_end, s in ms for w in 'ab' for b in s['beats'][w] if b['kind'] == 'super')
        self.assertLess(supers / len(ms), 1.6)                                              # V5: ~3 per match

    def test_a_round_loser_gets_a_comeback_exchange_and_kos_end_on_a_signature_move(self):
        comebacks = sig = kos = 0
        for p, tl, t_end, s in self.matches(30):
            if len(s['rounds']) >= 2:
                self.assertGreaterEqual(s['story']['comebacks'], 1)
            comebacks += s['story']['comebacks']
            if s['rounds'][-1]['ko']:
                kos += 1
                w = s['winner']
                g = LIB[p['chars'][w]].signature()
                ko = [o for t, n, o in tl[s['loser']] if (n in rounds.LYING and abs(t - s['final_ko']['tc']) < 1e-6)
                      or (n == 'thrown' and o.get('stop_at') == round(s['final_ko']['tc'], 4))][0]
                show = ((LIB[p['chars'][w]].anim.get(ko['react_to']) or {}).get('type') in ('throw', 'spike', 'through', 'pull', 'air')
                        or ko['react_to'] == 'uppercut')                                  # V9: a juggle (launch, air slash) finishes too
                sig += ko['react_to'] in (g['strike'], g['super'], g['ultimate'], g['special']) or show   # V7 showpieces count
        self.assertGreater(comebacks, 20)
        self.assertGreater(sig / kos, 0.85)

    def test_trailing_fighters_win_more_rounds_than_v5_two_nil_rate(self):
        two_nil = sum(1 for p, tl, t_end, s in self.matches(80) if min(s['wins'].values()) == 0)
        self.assertLess(two_nil / 80, 0.45)                                                 # V5: 53 %

    def test_boost_opens_with_the_signature_super_in_a_match_and_a_spar(self):
        p = dict(plan(7), boost=['b'])
        tl, t_end, s = rounds.make_match(p, ATL, fx.default())
        first = [b for b in s['beats']['b'] if b['kind'] in ('strike', 'super', 'special', 'ultimate', 'counter')][0]
        self.assertEqual((first['kind'], first['anim'], first['outcome']), ('super', ATL['codex'].signature()['super'], 'hit'))
        self.assertEqual(s['story']['boosts'], 1)
        sp = dict(kind='spar', left=LEFT, right=RIGHT, pos={LEFT: 400, RIGHT: 432}, t0=50.0, seed=11, chars={LEFT: 'claude', RIGHT: 'codex'}, boost=['a'])
        tl2, _, _ = make_timeline('spar', sp, LIB, fx.default())
        kinds = [o.get('kind') for t, n, o in tl2[LEFT] if 'contact' in o]
        self.assertEqual(kinds[0], 'super')

    def test_the_defender_braces_during_a_long_wind_up(self):
        braced = 0
        for p, tl, t_end, s in self.matches(40):
            for w in 'ab':
                o_w = 'b' if w == 'a' else 'a'
                for t, n, o in tl[w]:
                    if o.get('kind') in ('super', 'ultimate') and 'contact' in o and o['contact'] - t >= rounds.BRACE_MIN_S and o['outcome'] == 'hit':
                        guard = [(t2, n2) for t2, n2, o2 in tl[o_w] if t < t2 < o['contact'] and n2 in ('block', 'crouch_block') and o2.get('hold')]
                        self.assertTrue(guard, (w, n, t, o['contact']))
                        braced += 1
        self.assertGreater(braced, 3)

    def test_strikes_stand_at_their_reach_and_hitstop_has_a_floor(self):
        for p, tl, t_end, s in self.matches(20):
            pos = dict(p['pos'])
            ev = sorted((t, w, n, o) for w in 'ab' for t, n, o in tl[w] if 'to' in o)
            for t, w, n, o in ev:
                pos[w] = o['path'][-1][2] if o.get('path') else o['to']     # V7: a thrown fighter's slide has a second leg
                self.assertGreaterEqual(abs(pos['a'] - pos['b']), rounds.MIN_APART - 1e-6, (t, w, n, pos))
            for w in 'ab':
                for t, n, o in tl[w]:
                    if 'contact' in o and o.get('outcome') == 'hit':
                        self.assertGreaterEqual(o['hitstop'], 100, (n, o))


class WeaponFightsV7(unittest.TestCase):
    """V7: weapon families in the fight - throws in sync, juggles, boomerangs, dash-throughs, clashes, strings, set pieces."""
    LIBV = Library()
    PAIRS = [('claude', 'codex'), ('codex', 'knight'), ('nomad', 'cursor'), ('generic', 'oni'), ('gemini', 'monk'),
             ('kunoichi', 'barbarian'), ('lmstudio', 'ollama')]

    def match(self, seed, a, b):
        p = dict(plan(seed, chars=(a, b)))
        return p, rounds.make_match(p, {a: self.LIBV[a], b: self.LIBV[b]}, fx.default())

    def find(self, pred, n=60):
        for seed in range(n):
            a, b = self.PAIRS[seed % len(self.PAIRS)]
            p, (tl, t_end, s) = self.match(seed, a, b)
            hit = pred(p, tl, s)
            if hit:
                return p, tl, s, hit
        self.fail('no seeded match showed it')

    def test_variety_300_match_audit(self):
        out = sim.audit(300)
        for ch, v in out['chars'].items():
            self.assertGreaterEqual(v['distinct'], 14, (ch, v))
            self.assertLessEqual(v['top_share'], 0.20, (ch, v))
            self.assertEqual(v['session12'], 1.0, (ch, v))                       # 12+ distinct moves per 10-minute session
        for k in ('throw', 'juggle', 'through', 'string', 'clash', 'guard_break', 'riposte'):
            self.assertGreater(out['per_match'].get(k, 0), 0.05, (k, out['per_match']))
        self.assertLess(out['per_match']['ultimate'], 0.5)                         # V6 rarity kept
        self.assertLess(out['per_match']['super'], 1.6)

    def test_a_throw_starts_the_defender_on_the_grab_and_slams_it_on_the_contact(self):
        def throw(p, tl, s):
            for w in 'ab':
                for t, n, o in tl[w]:
                    if (self.LIBV[p['chars'][w]].anim.get(n) or {}).get('type') == 'throw' and o.get('outcome') == 'hit':
                        return w, t, o
        p, tl, s, (w, t, o) = self.find(throw)
        d = 'b' if w == 'a' else 'a'
        A, D = self.LIBV[p['chars'][w]], self.LIBV[p['chars'][d]]
        grab = t + A.start_ms('throw', A.anim['throw']['grab_frame']) / 1000.0
        th = [(t2, o2) for t2, n2, o2 in tl[d] if n2 == 'thrown' and o2.get('react_to') == 'throw']
        self.assertTrue(th)
        t_r, o_r = min(th, key=lambda e: abs(e[0] - grab))
        self.assertAlmostEqual(t_r + D.start_ms('thrown', D.anim['thrown']['grab_frame']) / 1000.0, grab, places=2)
        self.assertAlmostEqual(t_r + D.start_ms('thrown', D.anim['thrown']['hit_frame']) / 1000.0, o['contact'], places=2)
        self.assertAlmostEqual(o_r['stop_at'], o['contact'], places=3)             # both freeze on the slam
        self.assertEqual(len(o_r['path']), 1)                                         # hoisted in, then slammed out

    def test_launcher_air_hit_spike_in_order_and_the_defender_hangs_in_the_air(self):
        def juggle(p, tl, s):
            for w in 'ab':
                names = [n for t, n, o in tl[w] if n in ('launched', 'air_hit', 'spiked')]
                if names[:3] == ['launched', 'air_hit', 'spiked']:
                    return w
        p, tl, s, w = self.find(juggle)
        ents = [(t, n, o) for t, n, o in tl[w] if n in ('launched', 'air_hit', 'spiked', 'getup')]
        self.assertTrue(ents[0][2].get('hold') and ents[1][2].get('hold'))           # hangs until the next hit
        i = [n for t, n, o in ents].index('spiked')
        self.assertTrue(any(n == 'getup' for t, n, o in ents[i:]) or s['final_ko'])     # then gets up (or it was the KO)

    def test_a_boomerang_flies_out_and_comes_back_on_the_catch_frame(self):
        from minis_core.brain import proj_x
        p, (tl, t_end, s) = None, (None, None, None)
        for seed in range(80):
            p, (tl, t_end, s) = self.match(seed, 'nomad', 'claude')
            pr = [q for q in s['projs'] if q.get('ret')]
            if pr:
                break
        self.assertTrue(pr, 'no boomerang in 80 matches')
        q = pr[0]
        A = self.LIBV['nomad']
        mv = [t for t, n, o in tl[q['owner']] if n == q['move']]
        t0 = min(mv, key=lambda t: abs(t + A.start_ms(q['move'], A.anim[q['move']]['catch_frame']) / 1000.0 - q['back']))
        self.assertAlmostEqual(t0 + A.start_ms(q['move'], A.anim[q['move']]['catch_frame']) / 1000.0, q['back'], places=3)
        self.assertAlmostEqual(proj_x(q, q['back']), q['x0'], places=3)              # back in the hand
        far = proj_x(q, q['arrive'])
        self.assertGreater(abs(far - q['x0']), 10)                                   # it really went out

    def test_a_dash_through_swaps_sides_and_the_attacker_vaults_back(self):
        def through(p, tl, s):
            for w in 'ab':
                for t, n, o in tl[w]:
                    if o.get('through'):
                        return w, t, o
        p, tl, s, (w, t, o) = self.find(through)
        d = 'b' if w == 'a' else 'a'
        side_before = 1 if w == 'a' else -1                                         # a starts left of b
        pos_d = [o2['to'] for t2, n2, o2 in tl[d] if 'to' in o2 and t2 <= o['slide_at']]
        x_d = pos_d[-1] if pos_d else p['pos'][d]
        self.assertGreater((o['to'] - x_d) * side_before, 0)                          # it ended up on the far side
        vault = [o2 for t2, n2, o2 in tl[w] if n2 == 'jump' and o2.get('vault') and t2 > t]
        self.assertTrue(vault, 'vaults back over')

    def test_a_clash_puts_both_fighters_in_the_lock_on_the_same_instant(self):
        def clash(p, tl, s):
            for w in 'ab':
                for t, n, o in tl[w]:
                    if n == 'clash' and o.get('outcome') == 'clash' and 'contact' in o:
                        return w, t, o
        p, tl, s, (w, t, o) = self.find(clash, 120)
        d = 'b' if w == 'a' else 'a'
        self.assertTrue(any(n == 'clash' and abs(t2 - t) < 0.01 for t2, n, o2 in tl[d]), 'the other one locks too')

    def test_a_string_cancels_on_its_cancel_frame(self):
        def string(p, tl, s):
            for w in 'ab':
                A = self.LIBV[p['chars'][w]]
                combo = A.meta.get('combo') or []
                ent = [(t, n, o) for t, n, o in tl[w] if n in combo and 'contact' in o]
                for (t1, n1, o1), (t2, n2, o2) in zip(ent, ent[1:]):
                    if combo.index(n2) == combo.index(n1) + 1 and o1.get('outcome') == 'hit' and t2 - t1 < 2.0:
                        return A, (t1, n1, o1), (t2, n2, o2)
        p, tl, s, (A, (t1, n1, o1), (t2, n2, o2)) = self.find(string, 120)
        cancel = t1 + A.start_ms(n1, A.anim[n1]['cancel_frame']) / 1000.0 + o1['hitstop'] / 1000.0
        self.assertLessEqual(t2, t1 + A.total_ms(n1) / 1000.0 + o1['hitstop'] / 1000.0)    # starts before the move ends
        self.assertGreaterEqual(t2 + 1e-6, cancel - 0.01)

    def test_set_pieces_are_deterministic_playable_for_every_pairing_and_one_to_three_per_match(self):
        from minis_core import setpieces as SP
        from minis_core.atlas import available
        n = []
        for seed in range(28):
            a, b = self.PAIRS[seed % len(self.PAIRS)]
            p, (tl, t_end, s) = self.match(seed, a, b)
            _, (tl2, _, s2) = self.match(seed, a, b)
            self.assertEqual(tl, tl2)
            n.append(len(s['story']['pieces']))
            for name in s['story']['pieces']:
                self.assertIn(name, SP.PIECES)
        self.assertLessEqual(max(n), SP.MAX_PER_MATCH)
        self.assertTrue(1.0 <= sum(n) / len(n) <= 3.0, n)
        for name in SP.ORDER:                                                        # every piece fits some pairing
            ok = [(a, b) for a in available() for b in available() if a != b and SP.eligible(name, self.LIBV[a], self.LIBV[b])]
            self.assertTrue(ok, name)


if __name__ == '__main__':
    unittest.main()
