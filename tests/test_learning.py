"""Fighters teach themselves new moves (docs/LEARNING.md): the learning loop, procedural move synthesis and its QA gate,
determinism across two processes, the kit cap and decay, privacy of learning.json, and the brain / choreo hooks."""
import hashlib, json, os, random, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, ROOT, Isolated  # noqa: E402
from minis_core import choreo, config as cfgmod, fx as fxmod, learning as L, rounds, sim  # noqa: E402
from minis_core.atlas import Library  # noqa: E402
from minis_core.brain import LEFT, RIGHT, Brain  # noqa: E402
from minis_core.telemetry import Snapshot  # noqa: E402

EV = L.evolve()
LIB = Library()
FX = fxmod.default()


def plan(seed=7, a='claude', b='codex'):
    return dict(kind='match', left='a', right='b', pos={'a': 500.0, 'b': 532.0}, t0=1000.0, seed=seed, chars={'a': a, 'b': b},
                mode='decided', scores={'a': 100.0, 'b': 100.0}, id='t:1', deadline=1003.0, span=60.0)


def tl_hash(tl):
    return hashlib.sha256(json.dumps({s: [[round(t, 4), n, sorted((k, str(v)) for k, v in o.items())] for t, n, o in v]
                                      for s, v in sorted(tl.items())}, sort_keys=True).encode()).hexdigest()


def grant(e, spec, how, **kw):
    """Seed a learned move directly (tests): the pacing gap is for real fights, not for setting up a fixture."""
    e.pop('last_learn', None)
    return L._unlock(e, spec, how, **kw)


class Base(Isolated):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {'MINIS_LEARN_NO_RENDER': '1'})      # nothing spawns a render build in the tests
        p.start()
        self.addCleanup(p.stop)
        self.f = self.data / L.FILE


# ---------------------------------------------------------------- synthesis + QA
class Synthesis(unittest.TestCase):
    def test_the_synthesis_module_loads(self):
        self.assertIsNotNone(EV)
        self.assertTrue(L.enabled())

    def test_remap_variants_are_deterministic_and_pass_the_timing_rules(self):
        a = LIB['claude']
        for base in ('iai_slash', 'cross', 'roundhouse', 'spin_kick'):
            for op in EV.eligible_remap_ops(a.anim[base]):
                v1 = EV.remap(dict(a.anim[base], name=base), op, 123)
                v2 = EV.remap(dict(a.anim[base], name=base), op, 123)
                self.assertEqual(v1, v2)
                if v1 is None:
                    continue
                ms = [f['ms'] for f in v1['frames']]
                self.assertEqual(EV.timing_qa(ms, v1['hit_frame'], v1['smear_frames'], v1['hitstop_ms']), [], (base, op))
                self.assertTrue(all(0 <= f['src'] < len(a.anim[base]['frames']) for f in v1['frames']))
                self.assertEqual(v1['type'], 'learned')

    def test_retime_makes_the_startup_faster_and_twin_adds_a_hit(self):
        a = LIB['claude']
        e = dict(a.anim['iai_slash'], name='iai_slash')
        r = EV.remap(e, 'retime', 1)
        start = lambda m: sum(f['ms'] for f in m['frames'][:m['hit_frame']])
        self.assertLess(start(r), start(e) * 0.85)
        t = EV.remap(e, 'twin', 1)
        self.assertEqual(len(t['smear_frames']), len(e['smear_frames']) + 1)
        self.assertGreater(len(t['frames']), len(e['frames']))

    def test_moves_with_engine_flags_never_grow_variants(self):
        a = LIB['claude']
        for n, e in a.anim.items():
            if e.get('type') in ('through', 'throw', 'pull', 'air', 'spike', 'guard_break'):
                self.assertFalse(EV.eligible_base(e), n)
                self.assertEqual(EV.eligible_remap_ops(e), (), n)

    def test_timing_qa_rejects_even_timing_a_late_smear_and_no_hitstop(self):
        self.assertTrue(EV.timing_qa([100, 100, 40, 150], 3, [2], 150))
        self.assertTrue(EV.timing_qa([100, 60, 150, 40], 2, [3], 150))
        self.assertTrue(EV.timing_qa([100, 60, 40, 150], 3, [2], 90))
        self.assertEqual(EV.timing_qa([100, 60, 40, 150], 3, [2], 150), [])

    def test_a_feint_that_reads_like_a_stall_is_rejected(self):
        """Review finding: the knight's ground slam stutters between two wind-up keys 1-2 px apart; at 4x it is a pause,
        not a fake.  The silhouette gate rejects it at both resolutions; a kick's chamber feint passes."""
        for hd in (False, True):
            kn = Library(hd=hd)['knight']
            self.assertTrue(EV.remap_qa(kn, 'ground_slam', 'feint'), hd)
            self.assertTrue(EV.remap_qa(kn, 'jab', 'feint'), hd)
            cu = Library(hd=hd)['cursor']
            self.assertEqual(EV.remap_qa(cu, 'roundhouse', 'feint'), [], hd)
        self.assertEqual(EV.remap_qa(LIB['claude'], 'iai_slash', 'retime'), [])

    def test_load_row_refuses_a_variant_that_fails_qa(self):
        at = L.LearnedAtlas(LIB['knight'])
        self.assertFalse(L.load_row(at, ['knight', 'ground_slam', 'feint', 5, None, 'mastery']))
        self.assertNotIn('ground_slam_feint', at.anim)
        self.assertTrue(L.load_row(at, ['knight', 'ground_slam', 'retime', 5, None, 'mastery']))
        self.assertIn('ground_slam_ii', at.anim)

    @unittest.skipUnless(EV is not None and EV.available(), 'the rig (art/) is not here')
    def test_render_variants_pass_qa_and_a_broken_one_is_rejected(self):
        mv, info = EV._pose_variant('claude', 'iai_slash', 'spin', 3)
        for res in (1, 2):
            fr = EV.render_frames('claude', mv, res)
            pal, idle = EV._sheet_palette('claude', res)
            bad, reach = EV.qa('claude', mv, fr, res, pal, idle, base_frames=EV._base_frames('claude', 'iai_slash', res),
                               base_frames_l=EV._base_frames('claude', 'iai_slash', res, -1))
            self.assertEqual(bad, [], res)
            self.assertGreater(reach, 10 * res)
        # a colour the character's sheet does not have, a frame that floats, even timing: all caught
        fr = EV.render_frames('claude', mv, 1)
        pal, idle = EV._sheet_palette('claude', 1)
        fr[2] = dict(fr[2], r=fr[2]['r'].copy())
        fr[2]['r'].putpixel((40, 30), (1, 255, 2, 255))
        bad, _ = EV.qa('claude', mv, fr, 1, pal, idle)
        self.assertTrue(any('not in the sheet' in b for b in bad), bad)
        bad2, _ = EV.qa('claude', dict(mv, frames=[(p, 100) for p, _ in mv['frames']]), [dict(f, ms=100) for f in EV.render_frames('claude', mv, 1)], 1, pal, idle)
        self.assertTrue(any('even timing' in b for b in bad2), bad2)
        moved = [dict(f) for f in EV.render_frames('claude', mv, 1)]
        from PIL import Image
        im = Image.new('RGBA', moved[0]['r'].size, (0, 0, 0, 0))
        im.paste(moved[0]['r'], (0, -4))
        moved[0]['r'] = im
        bad3, _ = EV.qa('claude', mv, moved, 1, pal, idle)
        self.assertTrue(any('jitter' in b or 'mirror' in b for b in bad3), bad3)

    @unittest.skipUnless(EV is not None and EV.available(), 'the rig (art/) is not here')
    def test_a_variant_the_fit_passes_undid_is_rejected_as_not_new(self):
        """Review finding: the knight's amplified cleave rendered as the base cleave (the greatsword's hands are pulled back in
        by fit_weapons).  The novelty rule rejects it; Claude's amplified cross (a visibly bigger arc) passes."""
        meta, bad = EV.build(str(Path(tempfile.mkdtemp())), 'knight', 'cleave', 'amplify', 1)
        self.assertIsNone(meta)
        self.assertTrue(any('no new shape' in b for b in bad), bad)
        d = Path(tempfile.mkdtemp())
        meta, bad = EV.build(str(d), 'claude', 'cross', 'amplify', 1)
        self.assertEqual(bad, [])
        self.assertTrue(EV.cached(str(d), 'claude', 'cross_grand'))
        at = L.LearnedAtlas(LIB['claude'])
        self.assertTrue(L.load_row(at, ['claude', 'cross', 'amplify', 1, None, 'mastery'], data_dir=d))
        self.assertEqual(at.frame_image('cross_grand', 2, -1).size, tuple(at.cell))
        self.assertTrue(at.anim['cross_grand']['reach'] >= LIB['claude'].anim['cross']['reach'])
        hd = L.LearnedAtlas(Library(hd=True)['claude'])
        self.assertTrue(L.load_row(hd, ['claude', 'cross', 'amplify', 1, None, 'mastery'], data_dir=d))
        self.assertEqual(hd.frame_image('cross_grand', 2, 1).size, tuple(hd.cell))

    @unittest.skipUnless(EV is not None and EV.available(), 'the rig (art/) is not here')
    def test_a_spin_must_turn_the_body(self):
        """Review finding: the first spin was a side-on coil that read as the base move.  A spin now carries a back-turned
        frame (drawn from the other facing) and must match the base's other facing there; one that never turns is rejected."""
        mv, _ = EV._pose_variant('claude', 'iai_slash', 'spin', 1)
        fr = EV.render_frames('claude', mv, 1)
        self.assertEqual(mv['flip_frames'], [3])
        self.assertTrue(fr[3].get('flipped'))
        R, Lf = EV._base_frames('claude', 'iai_slash', 1), EV._base_frames('claude', 'iai_slash', 1, -1)
        m = EV._mask(fr[3]['r'])
        self.assertGreater(max(EV._iou(m, EV._mask(b)) for b in Lf), max(EV._iou(m, EV._mask(b)) for b in R) + 0.2)
        meta, bad = EV.build(str(Path(tempfile.mkdtemp())), 'claude', 'jab', 'spin', 1)        # a near-symmetric coil
        self.assertIsNone(meta)
        self.assertTrue(any('never turns' in b for b in bad), bad)

    @unittest.skipUnless(EV is not None and EV.available(), 'the rig (art/) is not here')
    def test_an_afterimage_smudge_outside_a_smear_is_caught(self):
        """The ghost-pixel budget: a faded copy of the body left behind on a recovery frame fails QA; the real frames have
        none (every redrawn variant passes it)."""
        mv, _ = EV._pose_variant('claude', 'cross', 'amplify', 1)
        fr = EV.render_frames('claude', mv, 1)
        for i, f in enumerate(fr):
            if i not in mv['smear_frames']:
                self.assertEqual(EV.ghost_pixels(f['r'], f['buf']), 0, i)
        i = len(fr) - 2
        im = fr[i]['r'].copy()
        smudge = fr[i]['r'].copy()
        smudge.putalpha(smudge.getchannel('A').point(lambda v: 90 if v else 0))
        im.alpha_composite(smudge, (-12, 0))                      # a translucent copy 12 px behind the body
        fr[i] = dict(fr[i], r=im)
        pal, idle = EV._sheet_palette('claude', 1)
        bad, _ = EV.qa('claude', mv, fr, 1, pal, idle)
        self.assertTrue(any('stray pixels' in b for b in bad), bad)

    def test_names_are_original_and_generic(self):
        self.assertEqual(EV.display_name('iai_slash_ii', 'iai_slash', 'retime'), 'Iai Slash II')
        self.assertEqual(EV.display_name('cross_twin', 'cross', 'twin'), 'Twin Cross')
        self.assertTrue(EV.display_name('jab_x01f', 'jab', 'retime', 'invention', 31).startswith('Jab '))


class Cache(Base):
    def test_lru_eviction_keeps_the_cache_under_its_cap(self):
        root = EV.cache_root(self.data) / 'claude'
        root.mkdir(parents=True)
        for i in range(6):
            (root / f'm{i}.json').write_text('{}')
            (root / f'm{i}.r1.png').write_bytes(b'x' * 1000)
            EV.touch(self.data, 'claude', f'm{i}', now=100 + i)
        EV.touch(self.data, 'claude', 'm0', now=500)                       # m0 used most recently
        gone = EV.evict(self.data, cap=3500)
        self.assertEqual(gone[0], 'claude/m1')
        self.assertLessEqual(EV.cache_size(self.data), 3500)
        self.assertTrue((root / 'm0.json').exists())

    def test_the_cache_lives_under_the_data_folder_never_the_repo(self):
        self.assertTrue(str(EV.cache_root(self.data)).startswith(str(self.data)))
        self.assertFalse(str(EV.cache_root(cfgmod.data_dir())).startswith(str(ROOT)))


# ---------------------------------------------------------------- the learning loop
def fake_summary(slot, mine, theirs, winner=None):
    other = 'b' if slot == 'a' else 'a'
    b = lambda m, o='hit': dict(kind='strike', anim=m, outcome=o)
    return dict(beats={slot: [b(m) for m in mine], other: [b(m) for m in theirs]}, winner=winner or slot,
                loser=other if (winner or slot) == slot else slot, story={'pieces': ['blade_lock']})


class Loop(Base):
    def test_mastery_unlocks_an_evolved_variant(self):
        lib = L.LearnedLibrary(LIB)
        got = None
        for i in range(L.MASTERY_N):
            got = L.observe('claude', 'claude', 'codex', 'codex', fake_summary('a', ['iai_slash'], []), 'a', 'match', lib, p=self.f) or got
        self.assertIsNotNone(got)
        self.assertEqual(got['how'], 'mastery')
        self.assertTrue(got['id'].startswith('iai_slash_'))
        doc = L.read(self.f)
        self.assertIn(got['id'], doc['programs']['claude']['learned'])

    def test_counter_learning_from_being_hit(self):
        lib = L.LearnedLibrary(LIB)
        got = []
        for i in range(L.COUNTER_K + 2):
            g = L.observe('claude', 'claude', 'cursor', 'cursor', fake_summary('a', [], ['long_thrust']), 'a', 'match', lib, p=self.f)
            if g:
                got.append(g)
        c = [g for g in got if g['how'] == 'counter']
        self.assertTrue(c, got)
        self.assertEqual(c[0]['vs'], LIB['cursor'].anim['long_thrust']['hit'])
        kit = L.kit_for('claude', 'claude', L.read(self.f))
        self.assertEqual(kit[c[0]['id']]['kind'], 'counter')

    def test_mimicry_needs_the_render_tier_and_queues_a_build(self):
        lib = L.LearnedLibrary(LIB)
        with mock.patch.dict(os.environ, {'MINIS_LEARN_NO_RENDER': ''}), mock.patch.object(L, 'spawn_build', return_value=True) as sp, \
                mock.patch.object(L, '_step_mastery', return_value=None), mock.patch.object(L, '_step_counter', return_value=None):
            for i in range(L.MIMIC_M + 1):
                L.observe('codex', 'codex', 'claude', 'claude', fake_summary('a', [], ['iai_slash']), 'a', 'match', lib, p=self.f)
        if not EV.available():
            self.skipTest('no rig')
        self.assertTrue(sp.called)
        spec = sp.call_args[0][0]
        self.assertEqual(spec[:3], ['codex', 'iai_slash', 'mimic'])
        self.assertEqual(spec[4], 'claude')
        self.assertTrue(L.read(self.f)['programs']['codex']['pending'])

    def test_invention_through_practice(self):
        lib = L.LearnedLibrary(LIB)
        at = lib['claude']
        unlocked = None
        for i in range(800):
            play, got = L.practice('claude', 'claude', 'jab', at, p=self.f)
            self.assertIn(play, at.anim)
            unlocked = unlocked or got
        self.assertIsNotNone(unlocked)
        self.assertEqual(unlocked['how'], 'invention')
        self.assertIn(unlocked['id'], at.anim)

    def test_the_kit_never_exceeds_its_cap_and_unused_moves_decay_then_go(self):
        doc = {'version': 1, 'v': 0, 'programs': {}}
        e = L._entry(doc, 'claude', 'claude')
        e['bouts'] = 10
        for i in range(L.KIT_MAX + 3):
            grant(e, ['claude', 'jab', 'retime', i, None, 'invention'], 'invention')
        self.assertEqual(len(e['learned']), L.KIT_MAX)                      # a full kit of live moves learns nothing more
        rec = next(iter(e['learned'].values()))
        self.assertEqual(L._weight(rec, 10), L.W_BASE)
        self.assertLess(L._weight(rec, 10 + L.DECAY_BOUTS + 20), L.W_BASE * 0.3)
        self.assertTrue(L.has_room(dict(e, bouts=10 + L.EVICT_BOUTS)))     # a stale move makes room
        e['bouts'] = 10 + L.FORGET_BOUTS
        L._decay(e)
        self.assertEqual(e['learned'], {})
        self.assertEqual(e['forgotten'], L.KIT_MAX)

    def test_new_moves_are_paced(self):
        doc = {'version': 1, 'v': 0, 'programs': {}}
        e = L._entry(doc, 'claude', 'claude')
        self.assertIsNotNone(L._unlock(e, ['claude', 'jab', 'retime', 1, None, 'invention'], 'invention'))
        self.assertIsNone(L._unlock(e, ['claude', 'jab', 'retime', 2, None, 'invention'], 'invention'))
        e['bouts'] = L.LEARN_GAP_BOUTS
        self.assertIsNotNone(L._unlock(e, ['claude', 'jab', 'retime', 2, None, 'invention'], 'invention'))

    def test_weights_grow_with_mastery(self):
        self.assertLess(L._weight({'level': 0, 'last': 5}, 5), L._weight({'level': 3, 'last': 5}, 5))
        self.assertLessEqual(L._weight({'level': 99, 'last': 5}, 5), L.W_MAX)

    def test_learning_follows_the_skin(self):
        doc = {'version': 1, 'v': 0, 'programs': {}}
        e = L._entry(doc, 'grok', 'knight')
        grant(e, ['knight', 'cleave', 'retime', 1, None, 'mastery'], 'mastery')
        self.assertTrue(L.kit_for('grok', 'knight', doc))
        self.assertEqual(L.kit_for('grok', 'claude', doc), {})


class Sim(Base):
    def test_300_match_balance(self):
        """Learning changes fights over time without running away: every program learns, kits stay under the cap, no move
        takes more than 25 % of a fighter's attacks, unused moves get forgotten, learning.json stays numbers and ids."""
        out = L.simulate(300, p=self.f)
        self.assertTrue(all(n > 0 for n in out['kit_sizes'].values()), out['kit_sizes'])
        self.assertTrue(all(n <= L.KIT_MAX for n in out['kit_sizes'].values()))
        self.assertLessEqual(out['max_share'], 0.25, out['top'])
        for ch, t in out['top'].items():
            self.assertGreater(t['learned_share'], 0.03, (ch, t))         # learned moves really appear in fights
            self.assertLess(t['learned_share'], 0.35, (ch, t))            # ... without taking over
        self.assertGreaterEqual(len(out['by_how']), 2, out['by_how'])
        self.assertEqual(out['privacy'], [])

    def test_learning_changes_the_fight(self):
        p0 = plan(11)
        tl0, _, _ = rounds.make_match(p0, {'claude': LIB['claude'], 'codex': LIB['codex']}, FX)
        lib = L.LearnedLibrary(Library())
        doc = {'version': 1, 'v': 3, 'programs': {}}
        e = L._entry(doc, 'claude', 'claude')
        for base, op in (('iai_slash', 'retime'), ('cross', 'twin'), ('low_kick', 'feint')):
            grant(e, ['claude', base, op, 9, None, 'mastery'], 'mastery')
        p1 = L.attach(plan(11), {'a': 'claude', 'b': None}, doc)
        self.assertTrue(L.prepare(p1, lib))
        tl1, _, s1 = rounds.make_match(p1, {'claude': lib['claude'], 'codex': lib['codex']}, FX)
        self.assertNotEqual(tl_hash(tl0), tl_hash(tl1))
        used = {b['anim'] for b in s1['beats']['a']}
        self.assertTrue(used & set(p1['learn']['kit']['a']), used)


# ---------------------------------------------------------------- determinism across processes
CHILD = r'''
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from minis_core import learning as L, rounds, fx as fxmod
from minis_core.atlas import Library
plan = json.loads(sys.argv[2])
lib = L.LearnedLibrary(Library())
ok = L.prepare(plan, lib)
chars = plan['chars']
tl, t_end, s = rounds.make_match(plan, {c: lib[c] for c in set(chars.values())}, fxmod.default())
rows = {m: [lib[chars[s_]].anim[m]['frames'], lib[chars[s_]].anim[m]['hit_frame']] for s_, k in plan['learn']['kit'].items() for m in k}
h = hashlib.sha256(json.dumps({x: [[round(t, 4), n, sorted((k, str(v)) for k, v in o.items())] for t, n, o in v] for x, v in sorted(tl.items())}, sort_keys=True).encode()).hexdigest()
print(json.dumps(dict(ok=ok, tl=h, rows=rows, winner=s['winner'])))
'''


class TwoProcesses(Base):
    def test_both_slot_processes_build_the_same_kit_and_the_same_fight(self):
        doc = {'version': 1, 'v': 0, 'programs': {}}
        for prog, ch, moves in (('claude', 'claude', (('iai_slash', 'retime'), ('cross', 'twin'))),
                                ('codex', 'codex', (('roundhouse', 'feint'), ('kunai_toss', 'retime')))):
            e = L._entry(doc, prog, ch)
            for base, op in moves:
                grant(e, [ch, base, op, 4, None, 'mastery'], 'mastery')
        e['taken'] = {'slash': 50}
        L._step_counter(e, LIB['codex'], None, None, None, 'codex', {}, set(), None)
        p = L.attach(plan(23), {'a': 'claude', 'b': 'codex'}, doc)
        self.assertEqual(sorted(p['learn']['kit']), ['a', 'b'])
        outs = []
        for _ in range(2):
            env = dict(os.environ, MINIS_DATA_BASE=str(self.data), PYTHONHASHSEED=str(random.randrange(1, 9999)))
            r = subprocess.run([sys.executable, '-c', CHILD, str(ROOT), json.dumps(p)], capture_output=True, text=True, env=env, timeout=240)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            outs.append(json.loads(r.stdout.strip().splitlines()[-1]))
        self.assertTrue(outs[0]['ok'])
        self.assertEqual(outs[0], outs[1])                                  # two processes: the same rows, the same timeline
        lib = L.LearnedLibrary(Library())
        self.assertTrue(L.prepare(p, lib))
        tl, _, _ = rounds.make_match(p, {'claude': lib['claude'], 'codex': lib['codex']}, FX)
        self.assertEqual(tl_hash(tl), outs[0]['tl'])                        # ... and this one too

    def test_a_plan_whose_rows_cannot_be_built_is_declined(self):
        p = plan(5)
        p['learn'] = dict(v=1, kit={'a': {'nope_ii': dict(w=1.0, kind='strike', spec=['claude', 'nope', 'retime', 1, None, 'mastery'])}})
        self.assertFalse(L.prepare(p, L.LearnedLibrary(Library())))
        p['learn']['kit']['a'] = {'jab_x001': dict(w=1.0, kind='strike', spec=['claude', 'jab', 'retime', 1, None, 'mastery'])}
        self.assertFalse(L.prepare(p, L.LearnedLibrary(Library())))         # id and spec disagree


# ---------------------------------------------------------------- privacy
class Privacy(Base):
    def test_learning_json_holds_only_ids_counters_and_seeds(self):
        L.simulate(40, p=self.f)
        doc = json.loads(self.f.read_text(encoding='utf-8'))
        self.assertEqual(L.audit_privacy(doc), [])
        self.assertGreater(len(doc['programs']), 0)
        for prog, e in doc['programs'].items():
            for k in e:
                self.assertIn(k, ('character', 'seed', 'bouts', 'matches', 'wins', 'losses', 'practice', 'trials', 'forgotten', 'used',
                                  'taken', 'seen', 'pieces', 'learned', 'pending', 'trial', 'last_invention', 'trials_failed', 'last_learn'), k)

    def test_the_audit_catches_text(self):
        self.assertTrue(L.audit_privacy({'programs': {'claude': {'note': 'fix the login bug'}}}))
        self.assertTrue(L.audit_privacy({'programs': {'C:\\Users\\x': {}}}))
        self.assertEqual(L.audit_privacy({'programs': {'claude': {'used': {'iai_slash': {'n': 3}}}}}), [])


# ---------------------------------------------------------------- hooks
class Hooks(Base):
    def brain(self, slot=LEFT, char='claude'):
        return Brain(slot, LIB[char], LIB, dict(CFG), random.Random(3), 1000.0, run='t' + slot, record=sim.no_record)

    def test_the_learner_is_off_by_default_and_never_writes(self):
        b = self.brain()
        self.assertFalse(b.learner.on)
        sc = dict(kind='match', plan=plan(), summary=fake_summary('a', ['jab'] * 30, []))
        b.snap = Snapshot('claude', 'idle', 10.0)
        self.assertIsNone(b.learner.after_bout(sc, 1000.0))
        self.assertEqual(b.learner.practice('jab', 1000.0), 'jab')
        self.assertFalse(self.f.exists())

    def test_an_enabled_learner_learns_after_a_bout_and_shows_the_moment(self):
        b = self.brain()
        b.learner.on = True
        b.snap = Snapshot('claude', 'idle', 10.0)
        b.partner = dict(who='codex', character='codex', x=540.0, mode='home')
        got = None
        for i in range(L.MASTERY_N):
            got = b.learner.after_bout(dict(kind='match', plan=plan(), summary=fake_summary('a', ['iai_slash'], [])), 1000.0) or got
        self.assertIsNotNone(got)
        self.assertIn(got['id'], b.atlas.anim)                               # the brain's own atlas already carries the row
        b.mode, b.anim = 'home', 'idle'
        self.assertTrue(b.learner.home(1001.0))
        self.assertEqual(b.anim, got['id'])
        self.assertEqual(b.banner['kind'], 'learned')
        v = b.view(1001.1)
        self.assertIsNotNone(v['banner'])                                    # 'LEARNED: <MOVE>' is drawn

    def test_the_plan_carries_the_kits_and_the_partner_accepts_it(self):
        doc_e = None

        def seed(doc):
            e = L._entry(doc, 'claude', 'claude')
            grant(e, ['claude', 'iai_slash', 'retime', 2, None, 'mastery'], 'mastery')
        L.update(seed, self.f)
        with mock.patch.object(L, 'path', lambda p=None: Path(p) if p else self.f):
            a = self.brain(LEFT, 'claude')
            a.learner.on = True
            a.snap = Snapshot('claude', 'idle', 10.0)
            a.partner = dict(who='codex', character='codex', x=560.0, mode='home', state='idle')
            p = a._plan('match', 1000.0)
        self.assertIn('iai_slash_ii', p['learn']['kit']['a'])
        b = self.brain(RIGHT, 'codex')                                       # the accepting side builds the same row
        self.assertTrue(b._possible('match', p))
        self.assertIn('iai_slash_ii', b.atlases['claude'].anim)

    def test_publish_carries_the_program_id(self):
        b = self.brain()
        b.snap = Snapshot('claude', 'idle', 10.0)
        self.assertEqual(b.publish()['who'], 'claude')

    def test_picker_weights_learned_moves_and_a_counter_widens_the_parry(self):
        at = L.LearnedAtlas(LIB['claude'])
        L.load_row(at, ['claude', 'iai_slash', 'retime', 1, None, 'mastery'])
        L.load_row(at, ['claude', 'riposte', 'retime', 7, None, 'counter'])
        kit = {'iai_slash_ii': dict(w=1.1, kind='strike'), 'riposte_vs007': dict(w=0.8, kind='counter', vs='pierce')}
        pk = choreo.Picker(random.Random(1), at, kit)
        self.assertIn(('iai_slash_ii', 1.1), pk.strikes())
        self.assertNotIn('riposte_vs007', [m for m, _ in pk.strikes()])
        self.assertEqual(pk.counter_for({'hit': 'pierce'}), 'riposte_vs007')
        self.assertIsNone(pk.counter_for({'hit': 'slash'}))
        self.assertGreater(pk.parry_k({'hit': 'pierce'}), 1.0)
        self.assertEqual(choreo.Picker(random.Random(1), at).parry_k({'hit': 'pierce'}), 1.0)

    def test_a_picker_without_a_kit_is_unchanged(self):
        """No learned moves: the V9 picker draws exactly as before (the same moves from the same seed)."""
        a, b = choreo.Picker(random.Random(5), LIB['claude']), choreo.Picker(random.Random(5), LIB['claude'], {})
        self.assertEqual([a.pick(a.strikes()) for _ in range(30)], [b.pick(b.strikes()) for _ in range(30)])
        tl1, _, _ = rounds.make_match(plan(3), {'claude': LIB['claude'], 'codex': LIB['codex']}, FX)
        lib = L.LearnedLibrary(Library())
        tl2, _, _ = rounds.make_match(plan(3), {'claude': lib['claude'], 'codex': lib['codex']}, FX)
        self.assertEqual(tl_hash(tl1), tl_hash(tl2))

    def test_learned_rows_draw_at_both_sizes(self):
        for hd in (False, True):
            at = L.LearnedLibrary(Library(hd=hd))['claude']
            self.assertTrue(L.load_row(at, ['claude', 'cross', 'twin', 1, None, 'mastery']))
            n = len(at.anim['cross_twin']['frames'])
            for i in range(n):
                im = at.frame_image('cross_twin', i, -1)
                self.assertEqual(im.size, tuple(at.cell))
            self.assertEqual(at.total_ms('cross_twin'), sum(f['ms'] for f in at.anim['cross_twin']['frames']))


# ---------------------------------------------------------------- views
class Views(Base):
    def seed(self):
        def f(doc):
            e = L._entry(doc, 'claude', 'claude')
            e['used'] = {'iai_slash': {'n': 20, 'hit': 9, 'whiff': 2, 'block': 9, 'prac': 0}}
            grant(e, ['claude', 'iai_slash', 'retime', 2, None, 'mastery'], 'mastery', now=50.0)
            e['taken'] = {'pierce': 21}
            grant(e, ['claude', 'riposte', 'retime', 9, None, 'counter'], 'counter', kind='counter', vs='pierce', now=60.0)
        L.update(f, self.f)

    def test_cli_lists_learned_moves_and_how(self):
        self.seed()
        out = L.lines(L.read(self.f))
        txt = '\n'.join(out)
        self.assertIn('Iai Slash II', txt)
        self.assertIn('mastered iai slash (20 thrown in fights)', txt)
        self.assertIn('hit by pierce attacks 21 times', txt)
        self.assertIn('nothing learned yet', L.lines(L.read(self.f), program='gemini')[0])

    def test_minis_learned_command(self):
        self.seed()
        env = dict(os.environ, MINIS_DATA_BASE=str(self.data.parent), PYTHONIOENCODING='utf-8')
        (self.data.parent / 'minis').mkdir(exist_ok=True)
        (self.data.parent / 'minis' / L.FILE).write_text(self.f.read_text(encoding='utf-8'), encoding='utf-8')
        r = subprocess.run([sys.executable, str(ROOT / 'minis.py'), 'learned', 'claude'], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertIn('Iai Slash II', r.stdout)

    def test_book_entries_hover_line_stats_and_toast(self):
        self.seed()
        doc = L.read(self.f)
        ent = L.book_entries('claude', doc)
        self.assertEqual(len(ent), 2)
        self.assertIn('l:iai_slash_ii', {e['key'] for e in ent})
        self.assertEqual({e['how'] for e in ent}, {'mastery', 'counter'})
        self.assertTrue(all(e['key'] == 'l:' + e['anim'] and e['desc'] for e in ent))
        self.assertEqual(L.book_entries('knight', doc), [])
        self.assertEqual(L.summary_line('claude', doc), 'learned 2 moves')
        self.assertIsNone(L.summary_line('codex', doc))
        st = L.stats(doc)
        self.assertEqual(st['learned'], 2)
        self.assertEqual(st['by_how'], {'mastery': 1, 'counter': 1})
        t = L.Toaster(self.f, every_s=0.0)
        self.assertIsNone(t.poll(0.0))                                       # the first look seeds silently
        L.update(lambda d: grant(L._entry(d, 'codex', 'codex'), ['codex', 'cross', 'retime', 1, None, 'mastery'], 'mastery'), self.f)
        self.assertEqual(t.poll(1.0), 'codex: Cross II')
        self.assertIsNone(t.poll(1.0 + L.TOAST_S + 0.1))


# ---------------------------------------------------------------- packaged installs (pip / the Windows zip: no art/)
class Packaged(Base):
    """A pip or zip install has minis_core but no art/: learning falls back to minis_core.movegen and still learns the
    remap operators (retime / twin / feint); nothing is ever redrawn or spawned."""

    def setUp(self):
        super().setUp()
        from minis_core import paths, movegen
        self.movegen = movegen
        p1 = mock.patch.object(paths, 'checkout', lambda: False)
        p2 = mock.patch.object(L, '_EVOLVE', None)
        p3 = mock.patch.dict(os.environ, {'MINIS_LEARN_NO_RENDER': ''})       # it must hold without the test switch
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_the_packaged_generator_is_used_and_cannot_redraw(self):
        ev = L.evolve()
        self.assertIs(ev, self.movegen)
        self.assertTrue(L.enabled())
        self.assertFalse(L.redraws())
        self.assertEqual(ev.eligible_render_ops(LIB['claude'].anim['cross']), ())
        self.assertNotIn('art', Path(ev.__file__).parts[-2:])

    def test_a_packaged_install_learns_remap_moves_and_spawns_nothing(self):
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('nothing may be spawned')) as po:
            out = L.simulate(150, p=self.f)
        self.assertFalse(po.called)
        self.assertTrue(all(n > 0 for n in out['kit_sizes'].values()), out['kit_sizes'])
        doc = L.read(self.f)
        for prog, e in doc['programs'].items():
            for mid, rec in e['learned'].items():
                self.assertIn(rec['spec'][2], self.movegen.REMAP_OPS, (prog, mid))
            self.assertEqual(e.get('pending') or [], [])
        self.assertLessEqual(out['max_share'], 0.25)

    def test_the_remap_rows_match_the_checkout_ones(self):
        """The same spec builds the same row whether the generator came from art/ or from the package."""
        spec = ['claude', 'iai_slash', 'twin', 77, None, 'mastery']
        a = L.LearnedAtlas(LIB['claude'])
        self.assertTrue(L.load_row(a, spec))
        packaged = a.anim['iai_slash_twin']
        with mock.patch.object(L, '_EVOLVE', EV):
            b = L.LearnedAtlas(Library()['claude'])
            self.assertTrue(L.load_row(b, spec))
        self.assertEqual(packaged, b.anim['iai_slash_twin'])


# ---------------------------------------------------------------- the ux / growth surfaces (move book, hover card, badges, toasts)
class Surfaces(Base):
    def seed(self):
        def f(doc):
            e = L._entry(doc, 'claude', 'claude')
            e['used'] = {'iai_slash': {'n': 31, 'hit': 9, 'whiff': 2, 'block': 9, 'prac': 0}}
            grant(e, ['claude', 'iai_slash', 'retime', 2, None, 'mastery'], 'mastery', now=50.0)
            e['taken'] = {'pierce': 46}
            grant(e, ['claude', 'riposte', 'retime', 9, None, 'counter'], 'counter', kind='counter', vs='pierce', now=60.0)
            g = L._entry(doc, 'codex', 'claude')                 # codex wearing the claude skin learned the same move
            grant(g, ['claude', 'iai_slash', 'retime', 2, None, 'mastery'], 'mastery', now=70.0)
        L.update(f, self.f)

    def test_the_move_book_has_a_learned_tab_drawn_animated(self):
        from minis_core import collection, lineup
        self.seed()
        self.assertEqual(collection.SECTIONS[-1][0], 'learned')
        b = collection.Book(lineup.characters(), {}, Library(), start='claude')
        b.set_section(len(collection.SECTIONS) - 1)
        vis = b.visible()
        self.assertEqual(len(vis), 2)                                    # one entry per move, though two programs learned one
        iai = next(e for e in vis if e['key'] == 'l:iai_slash_ii')
        self.assertEqual(iai['type'], 'mastered')
        self.assertIn('Claude mastered iai slash (31 thrown in fights)', iai['desc'])
        self.assertIn('Codex', iai['desc'])
        self.assertTrue(b.is_seen(iai))
        frames = {b.portrait('claude', iai['anim'], t, True).tobytes() for t in (0.0, 0.2, 0.4, 0.6)}
        self.assertGreater(len(frames), 1)                               # it animates
        b.render(0.3)
        got, tot = collection.counts(b.atlas('claude'), set())
        got2, tot2 = collection.counts(Library()['claude'], set())
        self.assertEqual(tot, tot2)                                      # the Learned tab never changes "N of M seen"
        normal = collection.entries(b.atlas('claude'))
        self.assertFalse(any(e['anim'] == 'iai_slash_ii' for sec in ('attacks', 'defense', 'everyday') for e in normal[sec]))

    def test_the_hover_card_says_how_many_moves_were_learned(self):
        from minis_core import hovercard
        self.seed()
        info = dict(name='Claude', state='idle', record=(3, 2), learned=L.summary_line('claude'))
        texts = [t for t, _, _ in hovercard.lines(info)]
        self.assertIn('learned 2 moves', texts)
        self.assertNotIn('learned', ' '.join(t for t, _, _ in hovercard.lines(dict(name='Codex', state='idle', learned=None))))

    def test_two_learning_badges_with_open_criteria(self):
        from minis_core import achievements as ACH, records
        self.assertIn('self_taught', ACH.IDS)
        self.assertIn('student', ACH.IDS)
        for aid in ('self_taught', 'student'):
            a = ACH.BY_ID[aid]
            self.assertTrue(a.desc)
            for word in ('token', 'hour', 'usage', 'context'):
                self.assertNotIn(word, (a.name + a.desc).lower())
        rec = records.read()
        self.assertNotIn('self_taught', ACH.evaluate(rec))
        self.assertEqual(ACH.progress(rec)['self_taught'], (0, 1))
        self.seed()
        met = ACH.evaluate(rec)
        self.assertEqual(met.get('self_taught'), 'claude')
        self.assertEqual(met.get('student'), 'claude')

    def test_learned_and_unlocked_toasts_share_one_row_without_overlapping(self):
        from minis_core import achievements as ACH, records, scoreboard
        records.record('claude', 'codex', now=1.0, score=(2, 1))
        slot = L.toast_slot(wall=lambda: 0.0, label=lambda s: s.title())
        slot.every_s = 0.0
        self.assertIsNone(slot.poll(0.0))                                # the first look seeds both sources silently
        self.seed()                                                       # two learned moves (+ two badges they earn)
        shown = []
        t = 1.0
        while t < 40.0:
            cur = slot.poll(t)
            if cur and (not shown or shown[-1][1] != cur):
                shown.append((t, cur))
            t += 0.25
        kinds = [c[0] for _, c in shown]
        self.assertEqual(kinds.count('unlocked'), 2)
        self.assertEqual(kinds.count('learned'), 3)                       # claude x2 + codex (wearing claude)
        self.assertEqual(kinds[:2], ['unlocked', 'unlocked'])              # in arrival order, one source after the other
        gaps = [b - a for (a, _), (b, _) in zip(shown, shown[1:])]
        self.assertTrue(all(g >= L.TOAST_S - 0.01 for g in gaps), gaps)   # each holds its full 3 s: nothing overlaps
        for kind, txt in [c for _, c in shown]:
            im = scoreboard.render(dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (1, 0), 'b': (0, 1)}, mode='taskbar',
                                        toast=(kind, txt)))
            self.assertGreater(im.width, 0)
        self.assertIn(('learned', 'Claude: Iai Slash II'), [c for _, c in shown])


# ---------------------------------------------------------------- Codex review 3 (do-not-merge findings), each a regression test
class ReviewHardening(Base):
    """P1 cache path traversal; P2 unbounded render workers; P2 failed cache writes leaving orphans; P2 a stale lock owner
    deleting a newer owner's lock; P2 invalid kit weights passing validation and failing after the accept."""

    # ---- P1: no identifier from learning.json or a bus plan can reach outside the cache
    def test_crafted_identifiers_never_leave_the_cache(self):
        outside = self.data.parent / ('outside-' + self.data.name)
        outside.mkdir()
        self.addCleanup(__import__('shutil').rmtree, outside, True)
        (outside / 'x_grand.json').write_text('{"code_v": 2}')
        for ch in ('../' + outside.name, '..', 'a/b', 'C:\\x', 'Claude', 'claude ', ''):
            with self.assertRaises(ValueError, msg=ch):
                EV.cache_paths(self.data, ch, 'x_grand')
            self.assertIsNone(EV.cached(self.data, ch, 'x_grand'), ch)
            self.assertIsNone(EV.load_sheet(self.data, ch, 'x_grand', 1), ch)
        for mid in ('../x', 'x/../../y', 'X', 'x.json', ''):
            with self.assertRaises(ValueError, msg=mid):
                EV.cache_paths(self.data, 'claude', mid)
        d, mp, pngs = EV.cache_paths(self.data, 'claude', 'cross_grand')
        root = EV.cache_root(self.data).resolve()
        for q in [mp] + list(pngs.values()):
            self.assertTrue(str(q.resolve()).startswith(str(root)), q)

    def test_prepare_refuses_a_spec_that_does_not_belong_to_the_plans_fighter(self):
        lib = L.LearnedLibrary(Library())
        p = plan(5)
        good = ['claude', 'cross', 'retime', 1, None, 'mastery']
        p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w=0.8, kind='strike', spec=good)}})
        self.assertTrue(L.prepare(p, lib))
        for bad_spec in (['codex', 'cross', 'retime', 1, None, 'mastery'],          # not slot a's character
                         ['../../outside', 'cross', 'retime', 1, None, 'mastery'],
                         ['claude', '../x', 'retime', 1, None, 'mastery'],
                         ['claude', 'cross', 'retime', 1, '../src', 'mimic'],
                         ['claude', 'cross', 'nope', 1, None, 'mastery'],
                         ['claude', 'cross', 'retime', -1, None, 'mastery'],
                         ['claude', 'cross', 'retime', 'x', None, 'mastery'],
                         ['claude', 'cross', 'retime', 1, None, 'gossip'],
                         ['claude', 'cross', 'retime', 1, None]):
            p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w=0.8, kind='strike', spec=bad_spec)}})
            self.assertFalse(L.prepare(p, L.LearnedLibrary(Library())), bad_spec)
        self.assertFalse(L.valid_spec(['../../outside', 'x', 'amplify', 1, None, 'mastery']))
        self.assertFalse(L.load_row(L.LearnedAtlas(LIB['claude']), ['claude', 'cross', 'amplify', 1, None, 'mastery'],
                                    data_dir=self.data / '..' / 'elsewhere'))

    def test_a_crafted_learning_json_entry_never_reaches_a_kit(self):
        def f(doc):
            e = L._entry(doc, 'claude', 'claude')
            e['learned']['x_grand'] = dict(how='mastery', spec=['claude', '../../x', 'amplify', 1, None, 'mastery'], kind='strike')
            e['learned']['y'] = dict(how='mastery', spec=['claude', 'cross', 'retime', 1, None, 'mastery'], kind='strike', level='lots')
        L.update(f, self.f)
        kit = L.kit_for('claude', 'claude', L.read(self.f))
        self.assertNotIn('x_grand', kit)
        self.assertTrue(all(isinstance(v['w'], float) for v in kit.values()))

    # ---- P2: kit weights are validated before the accept is emitted
    def test_invalid_kit_weights_are_refused_before_the_accept(self):
        lib = L.LearnedLibrary(Library())
        spec = ['claude', 'cross', 'retime', 1, None, 'mastery']
        for w in ('bad', float('nan'), float('inf'), -1.0, 99.0, None, True):
            p = plan(5)
            p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w=w, kind='strike', spec=spec)}})
            self.assertFalse(L.prepare(p, lib), w)
        p = plan(5)
        p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w=0.7, kind='punch', spec=spec)}})
        self.assertFalse(L.prepare(p, lib))
        p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w=0.7, kind='counter', vs='spite', spec=spec)}})
        self.assertFalse(L.prepare(p, lib))
        p['learn'] = dict(v=1, kit={'a': {f'jab_x{i:03x}': dict(w=0.5, kind='strike', spec=['claude', 'jab', 'retime', i, None, 'invention'])
                                         for i in range(L.KIT_MAX + 1)}})
        self.assertFalse(L.prepare(p, lib))                                 # more moves than any kit can hold
        # the accepting brain never acknowledges such a plan
        b = Brain(RIGHT, LIB['codex'], LIB, dict(CFG), random.Random(1), 1000.0, run='acc', record=sim.no_record)
        b.snap = Snapshot('codex', 'idle', 10.0)
        p = plan(5)
        p['learn'] = dict(v=1, kit={'a': {'cross_ii': dict(w='bad', kind='strike', spec=spec)}})
        b._accept(dict(seq=1, run='inv', type='invite', plan=p), 1000.0)
        self.assertIsNone(b.event)
        self.assertIsNone(b.script)
        # and a picker handed a bad weight anyway skips it instead of raising
        pk = choreo.Picker(random.Random(1), L.LearnedAtlas(LIB['claude']), {'jab': dict(w='bad', kind='strike')})
        self.assertNotIn('bad', [w for _, w in pk.strikes()])

    # ---- P2: render workers are tracked, deduplicated, capped, timed out and reaped
    def test_render_builds_are_deduplicated_capped_timed_out_and_reaped(self):
        made = []

        class FakeProc:
            def __init__(self, cmd, **kw):
                self.cmd, self.rc, self.killed = cmd, None, False
                made.append(self)

            def poll(self):
                return self.rc

            def kill(self):
                self.killed, self.rc = True, -9

            def wait(self, timeout=None):
                return self.rc
        clock = [1000.0]
        with mock.patch.object(L, 'redraws', return_value=True), mock.patch.object(EV, 'available', return_value=True), \
                mock.patch.dict(os.environ, {'MINIS_LEARN_NO_RENDER': ''}), mock.patch.object(subprocess, 'Popen', FakeProc), \
                mock.patch.object(L, '_mono', lambda: clock[0]):
            L.reset_builds()
            a = ['claude', 'cross', 'amplify', 1, None, 'mastery']
            b = ['claude', 'jab', 'spin', 2, None, 'invention']
            c = ['claude', 'roundhouse', 'amplify', 3, None, 'mastery']
            self.assertTrue(L.spawn_build(a))
            self.assertTrue(L.spawn_build(a))                               # the same build again: deduplicated
            self.assertEqual(len(made), 1)
            self.assertTrue(L.spawn_build(b))
            self.assertFalse(L.spawn_build(c))                              # the cap (MAX_BUILDS) is full: refused, retried later
            self.assertEqual(len(made), L.MAX_BUILDS)
            made[0].rc = 0                                                  # the first one finishes...
            L.reap_builds()
            self.assertTrue(L.spawn_build(c))                               # ...and frees a place
            clock[0] += L.BUILD_TIMEOUT_S + 1                               # the others stall past the timeout
            L.reap_builds()
            self.assertTrue(made[1].killed and made[2].killed)
            self.assertEqual(L.active_builds(), [])
            L.reset_builds()

    def test_a_pending_build_is_respawned_when_its_worker_is_gone(self):
        with mock.patch.object(L, 'spawn_build', return_value=True) as sp:
            e = {'bouts': 3, 'pending': [dict(spec=['claude', 'cross', 'amplify', 1, None, 'mastery'], how='mastery', kind='strike',
                                              vs=None, fallback=None, since=2)], 'learned': {}}
            self.assertIsNone(L._pending_ready(e, self.data))
            self.assertTrue(sp.called)                                      # not cached, not rejected, no worker: asked again

    # ---- P2: a build that fails part way leaves nothing behind, and eviction counts everything
    @unittest.skipUnless(EV is not None and EV.available(), 'the rig (art/) is not here')
    def test_a_failed_cache_write_leaves_no_files(self):
        from PIL import Image
        real = Image.Image.save
        calls = [0]

        def flaky(im, fp, *a, **k):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError('disk full')
            return real(im, fp, *a, **k)
        with mock.patch.object(Image.Image, 'save', flaky):
            meta, bad = EV.build(str(self.data), 'claude', 'cross', 'amplify', 1)
        self.assertIsNone(meta)
        self.assertTrue(any('cache write failed' in b for b in bad), bad)
        left = list((EV.cache_root(self.data) / 'claude').glob('*')) if (EV.cache_root(self.data) / 'claude').exists() else []
        self.assertEqual(left, [], left)

    def test_eviction_counts_and_removes_orphans_and_sidecars(self):
        root = EV.cache_root(self.data) / 'claude'
        root.mkdir(parents=True)
        (root / 'ghost_grand.r1.png').write_bytes(b'x' * 4000)                # an orphan: no metadata...
        (root / 'ghost_grand.rejected.json').write_bytes(b'{}' * 10)
        os.utime(root / 'ghost_grand.r1.png', (1, 1))                        # ...left behind long ago (a young one is spared)
        (root / 'old.r2.png.123.tmp').write_bytes(b'x' * 3000)              # a temp left by a crash
        os.utime(root / 'old.r2.png.123.tmp', (1, 1))
        for i in range(2):
            (root / f'm{i}.json').write_text('{}')
            (root / f'm{i}.r1.png').write_bytes(b'x' * 1000)
            EV.touch(self.data, 'claude', f'm{i}', now=100 + i)
        self.assertGreater(EV.cache_size(self.data), 9000)                  # orphans count toward the total
        gone = EV.evict(self.data, cap=10 ** 9)                             # under any cap: orphans and stale temps still go
        self.assertFalse((root / 'ghost_grand.r1.png').exists())
        self.assertFalse((root / 'old.r2.png.123.tmp').exists())
        self.assertTrue((root / 'm0.json').exists() and (root / 'm1.r1.png').exists())
        self.assertIn('claude/ghost_grand', gone)
        EV.evict(self.data, cap=1500)
        self.assertFalse((root / 'm0.json').exists())                       # then LRU, a whole group at a time
        self.assertFalse((root / 'm0.r1.png').exists())
        self.assertLessEqual(EV.cache_size(self.data), 1500)


class LockOwnership(Isolated):
    """P2: a lock taken over as stale is never deleted by the old owner when it finally finishes."""

    def test_a_stale_owner_cannot_delete_the_new_owners_lock(self):
        """Owner 1 stalls past STALE_S (its lock file still names it), owner 2 reclaims, then owner 1 resumes and runs its
        release: owner 2's lock must survive, so a third writer still cannot get in."""
        from minis_core import filelock
        target = self.data / 'learning.json'
        lock = target.with_name(target.name + '.lock')
        tok1 = b'111:owner-one'
        lock.write_bytes(tok1)
        os.utime(lock, (1, 1))
        cm2 = filelock.locked(target, timeout=1.0)
        self.assertTrue(cm2.__enter__())                                   # owner 2 reclaims the stale lock
        tok2 = lock.read_bytes()
        self.assertNotEqual(tok2, tok1)
        filelock._release(lock, tok1)                                       # owner 1 resumes and leaves its block
        self.assertTrue(lock.exists(), 'the stale owner deleted a lock it no longer owned')
        cm3 = filelock.locked(target, timeout=0.2)
        self.assertFalse(cm3.__enter__())                                   # so a third writer still cannot enter
        cm3.__exit__(None, None, None)
        cm2.__exit__(None, None, None)
        self.assertFalse(lock.exists())                                     # the real owner removes its own lock

    @unittest.skipIf(sys.platform == 'win32', 'Windows cannot delete an open lock file, so a held lock is never reclaimed there')
    def test_the_real_lock_api_keeps_a_reclaimed_lock(self):
        """The race end to end through filelock.locked(): owner 1 holds the lock and stalls, owner 2 reclaims it as stale,
        owner 1 leaves its block - before the fix its unconditional unlink deleted owner 2's lock."""
        from minis_core import filelock
        target = self.data / 'learning.json'
        lock = target.with_name(target.name + '.lock')
        cm1 = filelock.locked(target)
        self.assertTrue(cm1.__enter__())
        os.utime(lock, (1, 1))
        cm2 = filelock.locked(target, timeout=1.0)
        self.assertTrue(cm2.__enter__())
        cm1.__exit__(None, None, None)
        self.assertTrue(lock.exists(), 'the stale owner deleted a lock it no longer owned')
        cm3 = filelock.locked(target, timeout=0.2)
        self.assertFalse(cm3.__enter__())
        cm3.__exit__(None, None, None)
        cm2.__exit__(None, None, None)
        self.assertFalse(lock.exists())

    def test_learning_updates_go_through_the_shared_lock(self):
        from minis_core import filelock
        seen = []
        real = filelock.locked

        def spy(path, *a, **k):
            seen.append(Path(path).name)
            return real(path, *a, **k)
        with mock.patch.object(filelock, 'locked', spy):
            self.assertTrue(L.update(lambda d: d.setdefault('programs', {}), self.data / 'learning.json'))
        self.assertEqual(seen, ['learning.json'])


if __name__ == '__main__':
    unittest.main()
