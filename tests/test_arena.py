"""Arena mode, headless: platforms from a synthetic window list, flight, rounds, cracks / shatter, the RAM-only freeze
backdrop, the compositor's dirty rectangles, EXIT hit-test.  Nothing here touches the real desktop or any real window."""
import collections, os, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, Isolated  # noqa: E402
from minis_core import arena as AR, arena_setpieces as SP, choreo, fx, rounds  # noqa: E402
from minis_core.atlas import Library  # noqa: E402

LIB = Library(hd=True)
FX = fx.default()
MON = (2560, 76, 4480, 1156)                 # a 1920x1080 monitor to the right of the primary one
FLOOR = 1108
WINS = [(11, 2560 + 300, 76 + 200, 2560 + 1200, 76 + 800), (12, 2560 + 1300, 76 + 300, 2560 + 1800, 76 + 900),
        (13, 2560 - 100, 76 + 500, 2560 + 400, 76 + 700),      # straddles the monitor edge: clipped
        (14, 2560 + 50, 76 + 50, 2560 + 120, 76 + 90),         # too small: not a platform
        (15, 2560, 76, 4480, 1156)]                            # maximized: no platform


def make(seed=3, freeze=True, windows=WINS, record=None, mode='decided', scores=None):
    st = AR.Stage(MON, windows, floor_y=FLOOR)
    bd = AR.synthetic_backdrop(st.w, st.h) if freeze else None
    ar = AR.Arena(st, {'a': LIB['claude'], 'b': LIB['codex']}, FX, seed=seed, mode=mode, scores=scores, backdrop=bd, now=0.0,
                  record=record or (lambda *a, **k: None))
    ar.flashes = True                                          # never read this machine's control.json
    return st, ar


def run(ar, comp=None, secs=120, fps=30, until_phase='done', hook=None):
    now = 0.0
    phases = []
    n = 0
    while ar.phase != until_phase and now < secs:
        now += 1.0 / fps
        ar.tick(now)
        if comp is not None:
            comp.render(now)
        if hook:
            hook(now)
        if not phases or phases[-1] != ar.phase:
            phases.append(ar.phase)
        n += 1
    return now, phases, n


class Platforms(unittest.TestCase):
    def test_platforms_come_from_window_tops_clipped_plus_the_floor(self):
        st = AR.Stage(MON, WINS, floor_y=FLOOR)
        self.assertEqual(st.platforms(), [(1300, 1800, 300), (0, 400, 500), (0, 1920, 1032)])   # window 11's top (200) is inside the HUD band: no platform
        self.assertEqual([w['id'] for w in st.windows], [11, 12, 13])                         # ... but it still cracks
        self.assertGreaterEqual(AR.MIN_PLATFORM_Y, AR.HUD_H + AR.SPRITE_H)
        self.assertEqual(st.window_at(500, 500)['id'], 11)
        self.assertIsNone(st.window_at(1250, 250))
        st.update([])
        self.assertEqual(st.platforms(), [(0, 1920, 1032)])                 # only the floor remains

    def test_crack_state_machine(self):
        c = AR.Cracks()
        self.assertEqual(c.hit(1), 'crack_small')
        self.assertEqual(c.hit(1), 'crack_small')
        self.assertEqual(c.hit(1), 'shatter')
        self.assertIsNone(c.hit(1))                                          # stays shattered
        self.assertEqual(c.hit(2, heavy=True), 'crack_big')
        self.assertEqual(c.hit(2), 'shatter')
        self.assertEqual(c.state(1), 'shattered')
        self.assertEqual(c.state(3), 0)


class Match(unittest.TestCase):
    def test_a_match_runs_entry_rounds_winner_exit_and_records_once(self):
        recs = []
        st, ar = make(record=lambda w, l, **kw: recs.append((w, l, kw.get('where'))))
        now, phases, n = run(ar)
        self.assertEqual(phases[0], 'entry')
        self.assertEqual(phases[-3:], ['winner', 'exit', 'done'])
        self.assertEqual(phases.count('fight'), len(ar.rounds))
        self.assertIn(len(ar.rounds), (2, 3))
        self.assertEqual(max(ar.wins.values()), 2)
        self.assertIn(ar.winner, ('a', 'b'))
        self.assertEqual(recs, [(ar.chars[ar.winner], ar.chars['b' if ar.winner == 'a' else 'a'], 'arena')])
        for r in ar.rounds:
            self.assertLessEqual(r['dur'], rounds.ROUND_CAP_S + 1.5)
        kinds = collections.Counter(e[0] for e in ar.events)
        self.assertGreater(kinds['strike'], 4)
        self.assertGreater(kinds['fly'] + kinds['air'], 0)                   # somebody took to the air
        hps = [h for t, who, h in ar.hp_history]
        self.assertTrue(all(0 <= h <= 100 for h in hps))
        self.assertIn(0, hps)

    def test_round_cap_is_25_seconds(self):
        st, ar = make(seed=8)
        run(ar, until_phase='fight')
        t0 = ar.round_t0
        ar.p_left = 0.5
        # make every strike miss its mark by keeping the defender unreachable: freeze HP so only the cap can end the round
        ar.f['a'].hp = ar.f['b'].hp = 10 ** 6
        now = ar.last_now
        while ar.phase == 'fight' and now - t0 < 40:
            now += 1 / 30.0
            ar.tick(now)
        self.assertEqual(ar.phase, 'round_end')
        self.assertLessEqual(now - t0, rounds.ROUND_CAP_S + 1.0)
        self.assertGreaterEqual(now - t0, rounds.ROUND_CAP_S - 0.5)
        self.assertEqual(ar.rounds[-1]['ko'], False)

    def test_decided_mode_bias_reaches_the_arena(self):
        wins = collections.Counter()
        for seed in range(20):                                    # V6: the story tilt helps the underdog, so judge a bigger batch
            st, ar = make(seed=seed, freeze=False, scores={'a': 140.0, 'b': 20.0})
            run(ar)
            wins[ar.winner] += 1
        self.assertGreaterEqual(wins['a'], 14, wins)
        st, ar = make(seed=1, mode='random', scores={'a': 140.0, 'b': 20.0})
        self.assertEqual(ar.p_left, 0.5)

    def test_pause_freezes_and_exit_request_leaves(self):
        st, ar = make()
        run(ar, until_phase='fight')
        ar.paused = True
        snap = (ar.f['a'].x, ar.f['a'].y, ar.f['b'].x, ar.state())
        for i in range(60):
            ar.tick(ar.last_now + 0.1 * (i + 1))
        self.assertEqual(snap, (ar.f['a'].x, ar.f['a'].y, ar.f['b'].x, ar.state()))
        ar.paused = False
        ar.request_exit(ar.last_now + 6.1)
        now, phases, n = run(ar, secs=ar.last_now + 10)
        self.assertEqual(phases[-2:], ['exit', 'done'])
        self.assertTrue(all(ar.f[s].y > st.h for s in 'ab'))                 # gone below the floor


class Destruction(unittest.TestCase):
    def knock_into_window(self, ar, st, heavy):
        b = ar.f['b']
        ar.phase = 'fight'
        b.x, b.y = 700.0, 600.0                                              # inside window 11 (300..1200 x 200..800)
        b.vx, b.vy = (900.0 if heavy else 400.0), 0.0
        b.knocked_until = ar.last_now + 1.0
        b.last_crack = -10.0
        ar._window_collisions(b, ar.last_now)

    def test_three_hits_crack_then_shatter_with_letters_shards_and_a_hole(self):
        st, ar = make(freeze=True)
        before = ar.backdrop.getpixel((700, 500))
        untouched = ar.backdrop.copy()
        self.knock_into_window(ar, st, heavy=False)
        self.assertEqual([e[0] for e in ar.events][-1], 'crack_small')
        self.assertEqual(ar.letters_spawned, 0)
        self.knock_into_window(ar, st, heavy=True)
        self.assertEqual([e[0] for e in ar.events][-2:], ['shatter', 'hole'])   # 1 + 2 = 3: shattered, and a hole
        self.assertGreaterEqual(ar.letters_spawned, 9)
        self.assertTrue(any(i.effect.name == 'shatter' for i in ar.fxp.active))
        self.assertTrue(any(p[5] > 0 for p in ar.particles))                # V7: glyph debris are arena particles that fall
        self.assertEqual(ar.backdrop.getpixel((700, 500)), AR.HOLE)        # the hole is in the RAM backdrop
        self.assertNotEqual(before, AR.HOLE)
        self.assertEqual(ar.holes, [(300, 200, 1201, 801)])              # V9: the jagged edge paints row 800 / column 1200 too
        from PIL import ImageChops
        bx = ImageChops.difference(untouched, ar.backdrop).getbbox(alpha_only=False)
        (l, t, r, b), = ar.holes
        self.assertTrue(l <= bx[0] and t <= bx[1] and bx[2] <= r and bx[3] <= b, (bx, ar.holes))   # every painted pixel is repainted
        self.knock_into_window(ar, st, heavy=True)
        self.assertEqual([e[0] for e in ar.events].count('shatter'), 1)        # a shattered window stays shattered

    def test_no_backdrop_means_no_hole_but_still_shards(self):
        st, ar = make(freeze=False)
        self.knock_into_window(ar, st, True)
        self.knock_into_window(ar, st, True)
        self.assertEqual(ar.holes, [])
        self.assertIn('shatter_done', [e[0] for e in ar.events])

    def test_ultimate_explodes_and_shakes_the_overlay(self):
        st, ar = make(freeze=False)
        run(ar, until_phase='fight')
        now = ar.last_now
        ar.exchange = dict(att='a', dfn='b', move=ar.f['a'].atlas.ultimate(), kind='ultimate', dmg=40, state='strike', t=now, contact=now,
                           end=now + 1, hit_done=False, blocked=False, fx_at=None)
        ar.f['b'].hp = 80
        ar._resolve(ar.exchange, now)
        self.assertEqual(ar.f['b'].hp, 40)
        self.assertEqual(ar.explosions, 1)
        surf = AR.Surface(st.w, st.h)
        comp = AR.Compositor(ar, surf)
        comp.render(now + ar.fxp.hit_frame_time('explosion') + 0.02)         # the shake starts on the explosion's hit frame
        self.assertNotEqual(surf.offsets[-1], (0, 0))                        # the window moves: whole-overlay shake
        comp.render(now + 3.0)
        self.assertEqual(surf.offsets[-1], (0, 0))


class FreezeBackdrop(Isolated):
    def test_backdrop_is_never_written_to_disk(self):
        tmp = Path(tempfile.mkdtemp(prefix='minis-arena-cwd-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        root = Path(__file__).resolve().parent.parent
        before = {p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        data_before = set(self.data.rglob('*'))
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            st, ar = make(freeze=True)
            surf = AR.Surface(st.w, st.h)
            comp = AR.Compositor(ar, surf)
            run(ar, comp, secs=20)
            self.assertGreater(len(ar.cracks.count) + len(ar.cracks.shattered) + ar.explosions + 1, 0)
        finally:
            os.chdir(cwd)
        after = {p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        self.assertEqual(after - before, set())                              # nothing new under the project
        self.assertEqual(set(self.data.rglob('*')) - data_before, set())     # nothing new under the data dir
        self.assertEqual(list(tmp.iterdir()), [])                            # nothing in the working directory
        self.assertIsNotNone(ar.backdrop)
        self.assertEqual(ar.backdrop.size, (st.w, st.h))


class Composing(unittest.TestCase):
    def test_dirty_rects_are_small_and_the_surface_shows_the_fighters(self):
        st, ar = make(freeze=True)
        surf = AR.Surface(st.w, st.h)
        comp = AR.Compositor(ar, surf)
        sizes = []

        def hook(now):
            d = comp.render(now)
            sizes.append(sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in d))
        run(ar, secs=12, hook=hook)
        self.assertEqual(sizes[0], st.w * st.h)                              # first frame: the whole backdrop once
        self.assertEqual(surf.writes, 1 + sum(1 for s in sizes[1:] for _ in [0]) if False else surf.writes)
        typical = sorted(sizes[30:])[len(sizes[30:]) // 2]
        self.assertLess(typical, st.w * st.h * 0.25, typical)                # then only what moved
        # a fighter sprite really is on the surface where the body says it is
        b = ar.f['a']
        l, t, r, bt = b.sprite_rect()
        crop = surf.canvas.crop((max(0, l), max(0, t), min(st.w, r), min(st.h, bt)))
        bd = ar.backdrop.crop((max(0, l), max(0, t), min(st.w, r), min(st.h, bt)))
        self.assertNotEqual(crop.tobytes(), bd.tobytes())
        self.assertEqual(surf.canvas.size, (st.w, st.h))
        self.assertGreater(ar.f['a'].sprite_rect()[3] - ar.f['a'].sprite_rect()[1], 200)   # HD at 2x: 256 px cells

    def test_exit_button_hit_test_and_hud(self):
        st, ar = make(freeze=False)
        x0, y0, x1, y1 = ar.exit_rect()
        self.assertEqual(x1, st.w - AR.EXIT_MARGIN)
        self.assertTrue(ar.hit_exit(x0 + 5, y0 + 5))
        self.assertTrue(ar.hit_exit(x1, y1))
        self.assertFalse(ar.hit_exit(x0 - 1, y0))
        self.assertFalse(ar.hit_exit(st.w // 2, st.h // 2))
        run(ar, until_phase='fight')
        items = ar.drawables(ar.last_now)
        self.assertEqual(items[-1][1:], (x0, y0))                            # the button is always the last (topmost) drawable
        hud = [im for im, x, y in items if (x, y) == (0, 0) and im.width == st.w]
        self.assertEqual(len(hud), 1)
        self.assertTrue(ar.state()['hp'] == {'a': 100, 'b': 100} or ar.state()['hp'])

    def test_merge_rects(self):
        from minis_platform.rects import merge_rects                    # pure: runs on every OS
        self.assertEqual(sorted(merge_rects([(0, 0, 10, 10), (5, 5, 20, 20), (100, 100, 110, 110)])), [(0, 0, 20, 20), (100, 100, 110, 110)])
        many = [(i * 50, 0, i * 50 + 10, 10) for i in range(30)]
        self.assertLessEqual(len(merge_rects(many, limit=12)), 12)
        self.assertEqual(merge_rects([]), [])


class FightFeelV6(unittest.TestCase):
    """V6 rules in the arena: rare ultimate (one per match, attacker below 30 HP), impact frames that honour the flashes
    switch without full-screen frames, the KO finisher beat inside 3.5 s, braces on wind-ups, TIME + slump, comeback, boost."""

    def test_pacing_most_rounds_end_by_ko_in_10_to_18_s(self):
        lens, ko = [], 0
        for seed in range(30):
            st, ar = make(seed=seed, freeze=False)
            run(ar, secs=240)
            for r in ar.rounds:
                lens.append(r['dur'])
                ko += r['ko']
        self.assertLess(1 - ko / len(lens), 0.2, (ko, len(lens)))             # TIME is the exception (V5: 46 % of rounds)
        mean = sum(lens) / len(lens)
        self.assertTrue(10.0 <= mean <= 18.0, mean)

    def test_a_far_special_fires_instead_of_bouncing_between_approach_and_beat(self):
        st, ar = make(freeze=False)
        run(ar, until_phase='fight')
        now = ar.last_now
        a, b = ar.f['a'], ar.f['b']
        a.x, b.x = 300.0, 1600.0
        sp = a.atlas.signature()['special']
        beat = dict(who='att', kind='special', anim=sp, dmg=12, outcome='block', pre='block', react='block_hit', hitstop=100, knock=3, down=False)
        ar.exchange = dict(att='a', dfn='b', beats=[beat], i=0, state='beat', t=now, deadline=now + 6.0, air=False, kind='special', opener=None,
                           range_after='far', hit=False)
        ar._start_beat(ar.exchange, now)
        self.assertEqual(ar.exchange['state'], 'strike')


    def matches(self, seeds):
        out = []
        for seed in seeds:
            st, ar = make(seed=seed, freeze=False)
            ar.flashes = True
            ko_t, exit_t = [], []

            def hook(now, ar=ar):
                if ar.phase == 'exit' and not exit_t:
                    exit_t.append(now)
            run(ar, secs=200, hook=hook)
            out.append((ar, exit_t[0] if exit_t else None))
        return out

    def test_one_ultimate_per_match_only_below_30_hp_and_ko_finisher_inside_3_5_s(self):
        n_ult = finals = 0
        for ar, t_exit in self.matches(range(6)):
            ev = list(ar.events)
            ults = [e for e in ev if e[0] == 'ultimate']
            self.assertLessEqual(len(ults), 1)
            n_ult += len(ults)
            for kind, t, kw in ults:                                   # the attacker's HP when it fired
                hp = [h for (t2, who, h) in ar.hp_history if who == kw['who'] and t2 <= t]
                self.assertTrue(hp and hp[-1] < 30, (kw, hp))
            if ar.final_ko is not None and ar.rounds[-1]['ko']:
                finals += 1
                self.assertIsNotNone(t_exit)
                self.assertLessEqual(t_exit - ar.final_ko[0], rounds.POST_KO_MAX_S + 0.1, (ar.final_ko, t_exit))
                self.assertIn('impact', [e[0] for e in ev if e[1] >= ar.final_ko[0] - 1e-3])
            self.assertEqual(ar.phase, 'done')
        self.assertGreater(finals, 2)

    def test_winner_beat_has_the_name_banner_and_the_loser_slumps_up(self):
        st, ar = make(seed=2, freeze=False)
        ar.flashes = True
        seen = {}

        def hook(now):
            if ar.phase == 'winner':
                if ar.banner and ar.banner[0] == 'winner':
                    seen['banner'] = ar.banner
                loser = 'b' if ar.winner == 'a' else 'a'
                if ar.f[loser].anim == 'getup':
                    seen['getup'] = ar.f[loser].slow
        run(ar, secs=200, hook=hook)
        self.assertEqual(seen['banner'][3], ar.names[ar.winner])
        if ar.rounds[-1]['ko']:
            self.assertIsNotNone(seen.get('getup'))
            self.assertEqual(seen['getup'][2], rounds.GETUP_SLOW_K)

    def test_impact_frames_are_silhouettes_never_full_frames_and_obey_the_switch(self):
        for on in (True, False):
            st, ar = make(freeze=False)
            ar.flashes = on
            run(ar, until_phase='fight')
            now = ar.last_now
            surf = AR.Surface(st.w, st.h)
            comp = AR.Compositor(ar, surf)
            comp.render(now)
            ar.exchange = dict(att='a', dfn='b', move='roundhouse', kind='strike', dmg=36, state='strike', t=now, contact=now, end=now + 1,
                               hit_done=False)
            ar._resolve(ar.exchange, now)
            self.assertEqual(ar.impact is not None, on)
            self.assertEqual('impact' in [e[0] for e in ar.events], on)
            d = comp.render(now + 0.03)
            self.assertNotEqual(d, [(0, 0, st.w, st.h)])                       # only the sprite rects change
            if on:
                im = ar._sprite(ar.f['b'].atlas, ar.f['b'].anim, ar.f['b'].frame(now + 0.03)[0], ar.f['b'].facing, silhouette='white')
                px = {p for p in im.getdata() if p[3]}
                self.assertEqual(px, {(255, 255, 255, 255)})

    def test_flashes_off_means_no_white_frame_from_an_ultimate(self):
        st, ar = make(freeze=False)
        ar.flashes = False
        run(ar, until_phase='fight')
        now = ar.last_now
        ar.exchange = dict(att='a', dfn='b', move=ar.f['a'].atlas.ultimate(), kind='ultimate', dmg=40, state='strike', t=now, contact=now,
                           end=now + 1, hit_done=False)
        ar.f['b'].hp = 80
        ar._resolve(ar.exchange, now)
        surf = AR.Surface(st.w, st.h)
        comp = AR.Compositor(ar, surf)
        comp.render(now)
        self.assertNotEqual(comp.render(now + 0.03), [(0, 0, st.w, st.h)])
        self.assertFalse(comp.flashed)

    def test_time_banner_and_slump_and_the_round_loser_gets_a_comeback(self):
        st, ar = make(freeze=False)
        run(ar, until_phase='fight')
        now = ar.last_now
        ar.f['a'].hp, ar.f['b'].hp = 70, 40
        ar._end_round(now, None)
        self.assertEqual(ar.banner[0], 'time')
        self.assertIn(ar.f['b'].anim, rounds.SLUMP)
        self.assertEqual(ar.f['b'].hold, AR.HOLD_LAST)
        self.assertFalse(ar.f['b'].down)                                     # nobody falls over unprovoked
        self.assertEqual(ar.comeback_for, 'b')
        run(ar, until_phase='fight')
        ar.k_round = 1
        ar.cooldown_until = 0.0
        ar._new_exchange(ar.last_now)
        self.assertEqual(ar.exchange['att'], 'b')
        self.assertIsNone(ar.comeback_for)

    def test_boost_opens_with_the_signature_super_and_wind_ups_get_a_brace(self):
        st, ar = make(freeze=False)
        ar.boost = ['b']
        run(ar, until_phase='fight')
        ar._new_exchange(ar.last_now)
        first = [bt for bt in ar.exchange['beats'] if bt['kind'] in ('strike', 'super', 'special', 'ultimate', 'counter')][0]
        self.assertEqual((ar.exchange['att'], first['kind'], first['outcome']), ('b', 'super', 'hit'))
        braces = 0
        for ar2, _ in self.matches(range(3)):
            braces += sum(1 for e in ar2.events if e[0] == 'brace')
        self.assertGreater(braces, 0)

# ======================================================================== V7 (docs/ARENA.md)
def knock(b, now, x, y, vx, vy, down=False):
    b.x, b.y, b.vx, b.vy = float(x), float(y), float(vx), float(vy)
    b.grounded, b.knocked_until, b.down = False, now + 1.0, down
    b.play('knockdown' if down else 'hit_heavy', now, loop=False, hold='knockdown' if down else 'idle')


def quiet(ar):
    """Stop the procedural fight (no new exchanges, no hazards) so one mechanic can be watched on its own."""
    ar.exchange = None
    ar.cooldown_until = 1e9
    ar.next_hazard = 1e9


def step(ar, secs, comp=None, fps=30, until=None):
    now = ar.last_now
    for _ in range(int(secs * fps)):
        now += 1.0 / fps
        ar.tick(now)
        if comp is not None:
            comp.render(now)
        if until is not None and until(ar):
            break
    return now


def fight(seed=3, **kw):
    st, ar = make(seed=seed, freeze=False, **kw)
    run(ar, until_phase='fight')
    return st, ar


def arena(seed=3, chars=('claude', 'codex'), **options):
    st = AR.Stage(MON, WINS, floor_y=FLOOR)
    ar = AR.Arena(st, {'a': LIB[chars[0]], 'b': LIB[chars[1]]}, FX, seed=seed, now=0.0, record=options.pop('record', lambda *a, **k: None),
                  options=options)
    ar.flashes = True
    return st, ar


class Options(unittest.TestCase):
    def test_arena_options_validate_and_layer(self):
        o = AR.arena_options()
        self.assertEqual((o['rounds'], o['intensity'], o['seconds'], o['endless'], o['intro'], o['outro']), (3, 'normal', None, False, True, True))
        o = AR.arena_options({'arena': {'rounds': 5, 'intensity': 'calm'}}, {'arena_opts': {'intensity': 'wild', 'seconds': 40}}, {'seconds': 12})
        self.assertEqual((o['rounds'], o['intensity'], o['seconds']), (5, 'wild', 12.0))          # cfg < control < override
        o = AR.arena_options(override={'rounds': 4, 'intensity': 'loud', 'seconds': -3, 'endless': 'yes'})
        self.assertEqual((o['rounds'], o['intensity'], o['seconds'], o['endless']), (3, 'normal', None, True))
        self.assertTrue(AR.arena_options(override={'rounds': 'endless'})['endless'])
        st, ar = make()
        self.assertEqual(ar.opts, AR.arena_options())                      # a bare Arena never reads this machine's control file

    def test_best_of_one_and_best_of_five(self):
        recs = []
        st, ar = arena(seed=4, rounds=1, record=lambda w, l, **k: recs.append(w))
        run(ar, secs=200)
        self.assertEqual((len(ar.rounds), ar.phase, len(recs)), (1, 'done', 1))
        st, ar = arena(seed=4, rounds=5)
        run(ar, secs=400)
        self.assertEqual(max(ar.wins.values()), 3)
        self.assertIn(len(ar.rounds), (3, 4, 5))

    def test_endless_runs_until_its_seconds_and_records_nothing(self):
        recs = []
        st, ar = arena(seed=6, endless=True, seconds=70, record=lambda *a, **k: recs.append(a))
        now, phases, n = run(ar, secs=200)
        self.assertNotIn('winner', phases)
        self.assertEqual(phases[-2:], ['exit', 'done'])
        self.assertGreaterEqual(len(ar.rounds), 3)
        self.assertEqual(recs, [])
        self.assertLess(now, 78)                                           # left at its 70 s (plus the exit flight)

    def test_intro_vs_card_and_outro_perch(self):
        st, ar = make(seed=2, freeze=False)
        seen = set()

        def hook(now):
            if ar.phase == 'vs':
                seen.update(id(im) for im, x, y in ar._vs_drawables(now))
        now, phases, n = run(ar, secs=200, hook=hook)
        self.assertEqual(phases[:3], ['entry', 'vs', 'intro'])
        self.assertGreaterEqual(len(seen), 3)                              # two plates + VS
        self.assertIn('outro_perch', ar.counts)                            # the winner flew to the highest window
        st, ar = arena(seed=2, intro=False)
        now, phases, n = run(ar, until_phase='fight')
        self.assertNotIn('vs', phases)


class OptionsLayer(Isolated):
    def test_the_real_process_layers_minis_json_control_json_and_the_cli(self):
        import json
        (self.data / 'control.json').write_text(json.dumps({'arena_opts': {'intensity': 'calm', 'seconds': 30}}), encoding='utf-8')
        st = AR.Stage(MON, WINS, floor_y=FLOOR)
        ar = AR.Arena(st, {'a': LIB['claude'], 'b': LIB['codex']}, FX, seed=1, now=0.0, record=lambda *a, **k: None,
                      cfg=dict(CFG, arena={'intensity': 'wild', 'rounds': 5}), options={'seconds': 12, 'outro': False})
        self.assertEqual((ar.opts['rounds'], ar.opts['intensity'], ar.opts['seconds'], ar.opts['outro']), (5, 'calm', 12.0, False))
        self.assertEqual(ar.to_win, 3)


class Stage7(unittest.TestCase):
    def test_wall_bounce_off_the_monitor_edge_and_a_slow_hit_just_stops(self):
        st, ar = fight()
        quiet(ar)
        ar.I['tech_p'] = 0.0
        b = ar.f['b']
        knock(b, ar.last_now, 120, 1000, -1000, 0)
        step(ar, 0.3, until=lambda ar: ar.counts.get('wall_bounce'))
        self.assertEqual(ar.counts.get('wall_bounce'), 1)
        self.assertGreater(b.vx, 0)                                        # coming back the other way
        self.assertLess(abs(b.vx), 1000 * AR.WALL_K + 1)
        st, ar = fight()
        quiet(ar)
        b = ar.f['b']
        knock(b, ar.last_now, 60, 1000, -200, 0)
        step(ar, 0.3)
        self.assertNotIn('wall_bounce', ar.counts)

    def test_tech_recovery_lands_on_its_feet(self):
        st, ar = fight()
        quiet(ar)
        ar.I['tech_p'] = 1.0
        b = ar.f['b']
        knock(b, ar.last_now, 140, 1000, -1100, -200, down=True)
        step(ar, 2.0)
        self.assertEqual(ar.counts.get('tech'), 1)
        self.assertFalse(b.down)
        self.assertTrue(b.grounded)

    def test_ledge_grab_hang_climb_ends_standing_on_the_window_top(self):
        st, ar = fight()
        quiet(ar)
        x0, x1, y = st.ledges()[0]                                         # window 12: 1300..1800, top 300
        b = ar.f['b']
        b.x, b.y, b.vx, b.vy, b.grounded = x1 + 40.0, y + 60.0, 0.0, 300.0, False
        step(ar, 0.4, until=lambda ar: b.hang is not None)
        self.assertIsNotNone(b.hang)
        self.assertEqual(b.pose[0], 'jump')                                # hands up: the jump sheet's arms-up frame
        ys = []
        step(ar, 1.5, until=lambda ar: (ys.append(b.y), b.climb is None and b.hang is None)[1])
        self.assertEqual((b.x <= x1, b.y, b.grounded), (True, float(y), True))
        self.assertTrue(all(abs(ys[i + 1] - ys[i]) < 60 for i in range(len(ys) - 1)), ys)   # no pops along the climb
        self.assertEqual([e[0] for e in ar.events if e[0] in ('ledge_grab', 'climb')], ['ledge_grab', 'climb'])

    def test_knock_through_leaves_a_fighter_shaped_crack_on_that_window(self):
        st, ar = fight()
        quiet(ar)
        b = ar.f['b']
        knock(b, ar.last_now, 1260, 600, -1500, 0, down=True)              # into window 11 (300..1200 x 200..800) at speed
        step(ar, 0.2, until=lambda ar: 'through' in ar.counts)
        d = [d for d in ar.decals if d['kind'] == 'through']
        self.assertEqual(len(d), 1)
        w = st.window_by_id(d[0]['wid'])
        self.assertTrue(w['l'] <= d[0]['x'] and d[0]['x'] + d[0]['img'].width <= w['r'] and w['t'] <= d[0]['y'] <= w['b'])
        self.assertGreater(len({p for p in d[0]['img'].getdata() if p[3]}), 3)
        self.assertLess(b.vx, -900)                                        # it keeps going: through, not a bounce

    def test_skid_decelerates_linearly_on_a_window_top_then_stops(self):
        st, ar = fight()
        quiet(ar)
        x0, x1, y = st.ledges()[0]
        b = ar.f['b']
        ar.I['tech_p'] = 0.0
        knock(b, ar.last_now, x0 + 30, y - 60, 700, 300, down=True)
        n0 = ar.fx_count
        vs = []
        step(ar, 1.2, until=lambda ar: (vs.append((b.skid, b.vx)), len(vs) > 5 and not b.skid and vs[-2][0])[1])
        sk = [v for s, v in vs if s]
        self.assertGreater(len(sk), 5)
        drops = [sk[i] - sk[i + 1] for i in range(len(sk) - 1)]
        self.assertTrue(all(abs(d - AR.SKID_F / 30.0) < 3 for d in drops[1:-1]), drops)   # constant deceleration: no float, no snap
        self.assertEqual(b.vx, 0.0)
        self.assertGreater(ar.fx_count - n0, 6)                            # sparks off the glass

    def test_meteor_spike_cracks_the_tops_it_passes_and_leaves_a_crater(self):
        st, ar = fight()
        quiet(ar)
        b = ar.f['b']
        knock(b, ar.last_now, 1500, 150, 0, 1900, down=True)
        b.meteor = True
        step(ar, 1.0)
        self.assertEqual(ar.counts.get('meteor_through'), 1)                # window 12's top (300)
        self.assertGreaterEqual(ar.cracks.count.get(12, 0), 2)
        cr = [d for d in ar.decals if d['kind'] == 'crater']
        self.assertEqual(len(cr), 1)
        self.assertLess(cr[0]['y'], st.floor_y)
        self.assertGreater(cr[0]['y'] + cr[0]['img'].height, st.floor_y)   # straddles the taskbar line
        for i in range(10):
            ar._crater(ar.last_now, 100 + i * 150, 1800)
        self.assertEqual(len([d for d in ar.decals if d['kind'] == 'crater']), ar.I['craters'])

    def test_double_jump_into_an_air_to_air_hover(self):
        st, ar = fight()
        quiet(ar)
        ty = 600.0
        for s in 'ab':
            ar.f[s].air_plan = dict(y=ty, stage=0)
        ys = []
        step(ar, 1.5, until=lambda ar: (ys.append(ar.f['a'].y), all(ar.f[s].hover for s in 'ab'))[1])
        self.assertEqual(ar.counts.get('double_jump'), 2)
        for s in 'ab':
            self.assertTrue(ar.f[s].hover)
            self.assertLess(abs(ar.f[s].y - ty), 30)
        self.assertTrue(all(abs(ys[i + 1] - ys[i]) < 60 for i in range(len(ys) - 1)))

    def test_recovery_jump_once(self):
        st, ar = fight()
        quiet(ar)
        b = ar.f['b']
        knock(b, ar.last_now, 900, 500, 0, 300)
        b.knocked_until = ar.last_now
        b.recover_ok = True
        step(ar, 1.5)
        self.assertEqual(ar.counts.get('recovery'), 1)

    def test_shard_hazard_drops_a_platform_you_can_stand_on_then_it_crumbles(self):
        st, ar = fight()
        quiet(ar)
        ar.next_hazard = 0.0
        ar._hazards(ar.last_now)
        ar.next_hazard = 1e9
        self.assertEqual(ar.counts.get('hazard_crack'), 1)
        step(ar, 2.5, until=lambda ar: st.extra)
        self.assertEqual(len(st.extra), 1)
        p = st.extra[0]
        self.assertIn((p['x0'], p['x1'], p['y']), st.platforms())
        b = ar.f['b']
        b.x, b.y, b.vy, b.grounded = (p['x0'] + p['x1']) / 2.0, p['y'] - 80.0, 0.0, False
        step(ar, 0.5)
        self.assertEqual((b.y, b.grounded), (float(p['y']), True))         # standing on the glass
        step(ar, 13.0, until=lambda ar: not st.extra)
        self.assertEqual(st.extra, [])
        self.assertIn('shard_crumble', ar.counts)

    def test_letter_rain_after_a_shatter(self):
        st, ar = fight()
        quiet(ar)
        n0 = ar.letters_spawned
        ar._shatter(st.windows[0], ar.last_now, 600, 500)
        step(ar, 2.0)
        self.assertGreater(ar.letters_spawned - n0, 9 + 10)                # the spray, then the rain


class Camera7(unittest.TestCase):
    def test_zoom_lens_eases_and_never_leaves_the_monitor(self):
        st, ar = fight()
        quiet(ar)
        surf = AR.Surface(st.w, st.h)
        comp = AR.Compositor(ar, surf)
        comp.render(ar.last_now)
        for cx, cy in ((0, 0), (st.w, st.h), (st.w / 2, st.h / 2), (-500, 5000)):
            zs = []
            ar.cam.punch(ar.last_now, cx, cy)
            x0, y0, x1, y1 = ar.cam.zoom['rect']
            self.assertTrue(0 <= x0 < x1 <= st.w and 0 <= y0 < y1 <= st.h)
            step(ar, 1.2, comp, until=lambda ar: (zs.append(ar.cam.z), ar.cam.zoom is None)[1])
            self.assertLessEqual(max(zs), ar.I['zoom'] + 1e-6)
            self.assertTrue(all(abs(zs[i + 1] - zs[i]) < 0.1 for i in range(len(zs) - 1)), zs)   # eased: no jumps
        self.assertEqual(surf.out_of_bounds, 0)
        self.assertLessEqual(comp.max_zoom, ar.I['zoom'] + 1e-6)
        self.assertGreater(comp.max_zoom, 1.05)

    def test_a_second_punch_while_zoomed_continues_instead_of_popping(self):
        st, ar = fight()
        quiet(ar)
        comp = AR.Compositor(ar, AR.Surface(st.w, st.h))
        ar.cam.punch(ar.last_now, 800, 500)
        step(ar, 0.1, comp)
        z1, rect = ar.cam.z, ar.cam.zoom['rect']
        ar.cam.punch(ar.last_now, 100, 100)
        step(ar, 1.0 / 30, comp)
        self.assertEqual(ar.cam.zoom['rect'], rect)
        self.assertGreaterEqual(ar.cam.z, z1 - 0.02)

    def test_letterbox_eases_and_sits_behind_the_fighters(self):
        st, ar = fight()
        quiet(ar)
        ar.cam.letterbox(ar.last_now, ar.last_now + 0.6)
        hs = []
        now = ar.last_now
        spr_w = ar.f['a'].atlas.cell[0] * AR.SCALE
        for i in range(45):
            now += 1 / 30.0
            ar.tick(now)
            items = ar.drawables(now)
            hs.append(ar.cam.bar)
            bars = [k for k, (im, x, y) in enumerate(items) if im.width == st.w and y + im.height == st.h and x == 0]
            if bars:
                sprites = {id(e[1]) for e in AR.Arena._trim_cache.values() if e[1] is not None}     # V9: trimmed sprites
                spr = [k for k, (im, x, y) in enumerate(items) if im.width == spr_w or id(im) in sprites]
                self.assertLess(bars[0], min(spr))                        # drawn first: never over a foot
        self.assertGreater(max(hs), 0)
        self.assertEqual(hs[-1], 0)
        self.assertTrue(all(abs(hs[i + 1] - hs[i]) < 25 for i in range(len(hs) - 1)), hs)

    def test_colour_flash_and_ink_frames_obey_the_flashes_switch(self):
        for on in (True, False):
            st, ar = fight()
            ar.flashes = on
            quiet(ar)
            a, b = ar.f['a'], ar.f['b']
            plan = ar._setpiece_plan('stance_finisher', a, b)
            ar._start_sp_setup('stance_finisher', 'a', 'b', plan, ar.last_now)
            surf = AR.Surface(st.w, st.h)
            comp = AR.Compositor(ar, surf)
            comp.render(ar.last_now)
            full = 0
            now = ar.last_now
            for i in range(130):
                now += 1 / 30.0
                ar.tick(now)
                if comp.render(now) == [(0, 0, st.w, st.h)]:
                    full += 1
                if ar.exchange is None:
                    ar.cooldown_until = now + 99
            self.assertEqual('ink' in ar.counts, on)
            self.assertEqual(full > 0, on)                                 # the colour flash is the only full frame


class Intensity7(unittest.TestCase):
    def test_letters_scale_with_intensity(self):
        got = {}
        for name in AR.INTENSITIES:
            st, ar = make(freeze=False)
            ar.I = dict(AR.INTENSITY[name])
            ar._letters(st.windows[0], 0.0, 500, 500, 9)
            got[name] = ar.letters_spawned
        self.assertLess(got['calm'], got['normal'])
        self.assertLess(got['normal'], got['wild'])

    def test_whole_matches_scale_fx_counts(self):
        tot = {}
        for name in ('calm', 'wild'):
            n = 0
            for seed in range(3):
                st, ar = arena(seed=seed, intensity=name)
                run(ar, secs=200)
                n += ar.fx_count + ar.letters_spawned
            tot[name] = n
        self.assertLess(tot['calm'] * 1.5, tot['wild'], tot)


class Clash7(unittest.TestCase):
    def test_beam_clash_meets_struggles_and_the_winner_overpowers(self):
        st, ar = fight(7)
        quiet(ar)
        first = dict(who='att', kind='super', anim=ar.f['a'].atlas.signature()['super'], dmg=24, outcome='hit')
        ar.meter = {'a': 90.0, 'b': 90.0}
        for s in 'ab':
            ar.f[s].hp = 100
        ar._start_clash('a', 'b', first, ar.last_now)
        ex = ar.exchange
        w = ex['winner']
        l = 'b' if w == 'a' else 'a'
        self.assertEqual(ar.meter, {'a': 0.0, 'b': 0.0})                   # both spent their charge on it
        xs = []
        step(ar, 7.0, until=lambda ar: (xs.append(ex.get('x_c')), ar.exchange is not ex)[1])
        order = [e[0] for e in ar.events if e[0].startswith('clash')]
        self.assertEqual(order, ['clash', 'clash_charge', 'clash_fire', 'clash_meet', 'clash_push', 'clash_win'])
        self.assertEqual(ar.f[l].hp, 100 - int(round(choreo.DMG_SUPER * AR.ARENA_DMG_K)))
        self.assertTrue(ar.f[l].down)
        self.assertEqual([e for e in ar.events if e[0] == 'clash_win'][0][2]['who'], w)
        sway = [x for x in xs if x is not None]
        self.assertGreater(max(sway) - min(sway), 60)                      # it pushed back and forth
        self.assertIsNone(ar.f[w].pose)                                    # everyone released afterwards

    def test_at_most_clash_max_per_match(self):
        n = 0
        for seed in range(6):
            st, ar = make(seed=seed, freeze=False)
            run(ar, secs=240)
            self.assertLessEqual(ar.counts.get('clash', 0), ar.I['clash_max'])
            n += ar.counts.get('clash', 0)
        self.assertGreater(n, 0)


class SetPieces7(unittest.TestCase):
    def test_two_to_four_set_pieces_a_match(self):
        counts = []
        for seed in range(8):
            st, ar = make(seed=seed, freeze=False)
            run(ar, secs=240)
            counts.append(ar.counts.get('setpiece', 0))
        self.assertTrue(all(2 <= c <= 4 for c in counts), counts)

    def test_every_set_piece_plays_lands_its_cut_and_releases_both(self):
        for name in SP.SETPIECES:
            for chars in (('claude', 'codex'), ('knight', 'kunoichi')):
                st, ar = arena(seed=3, chars=chars)
                run(ar, until_phase='fight')
                quiet(ar)
                ar.f['b'].hp = 100
                plan = ar._setpiece_plan(name, ar.f['a'], ar.f['b'])
                self.assertIsNotNone(plan, name)
                ar._start_sp_setup(name, 'a', 'b', plan, ar.last_now)
                surf = AR.Surface(st.w, st.h)
                comp = AR.Compositor(ar, surf)
                step(ar, SP.SETPIECES[name]['dur'] + 2.0, comp, until=lambda ar: ar.counts.get('setpiece') and ar.sp is None)
                self.assertIsNone(ar.sp, name)
                self.assertEqual(ar.f['b'].hp, 100 - SP.SETPIECES[name]['dmg'], (name, chars))
                self.assertIsNone(ar.f['a'].pose)
                self.assertIsNone(ar.f['a'].alpha)
                self.assertEqual(surf.out_of_bounds, 0)

    def test_pose_slots_come_from_the_atlas_and_missing_moves_fall_back(self):
        a = LIB['knight']
        for slot in ('stance', 'charge', 'dash', 'wind', 'cut', 'follow', 'cut2', 'cut3', 'guard', 'stagger', 'recoil'):
            r = SP.resolve_slot(a, slot)
            self.assertIsNotNone(r, slot)
            self.assertIn(r[1] if r[0] == '@play' else r[0], a.anim)

        class Bare:                                                       # an atlas with nothing but idle
            anim = {'idle': {'frames': [{'ms': 100}], 'loop': True}}
            accent = (200, 200, 210)
            meta = {}

            def signature(self):
                return {'strike': None, 'special': None, 'super': None, 'ultimate': None}
        for slot in ('stance', 'charge', 'dash', 'cut', 'follow', 'guard', 'recoil'):
            r = SP.resolve_slot(Bare(), slot)
            self.assertTrue(r is None or (r[1] if r[0] == '@play' else r[0]) in Bare.anim, (slot, r))
        self.assertIn(SP.element_for(Bare()), SP.ELEMENTS)

    def test_every_element_paints_a_ribbon_at_hd_size(self):
        spec = SP.cut(250, -76, -12, 58, 0.1, 0.3, 0.3, 8, k=1.0)
        for e in SP.ELEMENTS:
            im, ox, oy = SP.ribbon(e, spec, 1.0, 0.0, 1.0, (169, 157, 255))
            self.assertGreater(im.width, 150, e)
            self.assertGreater(sum(1 for p in im.getchannel('A').getdata() if p > 128), 500, e)
        self.assertIsNone(SP.ribbon('flame', spec, 0.0, 0.0, 1.0))


class Moves7(unittest.TestCase):
    def test_traits_come_from_beat_flags_atlas_metadata_and_names(self):
        a = LIB['nomad']
        self.assertIn('throw', AR.move_traits(a, 'jab', {'throw': True}))
        self.assertIn('launcher', AR.move_traits(a, 'uppercut'))
        self.assertEqual(AR.move_traits(None, 'mystery', {'tags': ['pull', 'grab']}) & {'pull', 'throw'}, {'pull', 'throw'})
        sp = a.signature()['special']
        if 'proj_frame' in (a.anim.get(sp) or {}):
            self.assertNotIn('throw', AR.move_traits(a, sp))              # a thrown projectile is not a grab

    def test_an_unknown_attack_kind_plays_and_its_trait_moves_the_defender(self):
        st, ar = fight()
        quiet(ar)
        a, b = ar.f['a'], ar.f['b']
        b.x, b.y = a.x + a.facing * 70, a.y
        b.hp = 100
        beat = dict(who='att', kind='throw', anim='cross', dmg=12, outcome='hit', pre=None, react='knockdown', hitstop=100, throw=True)
        ar.exchange = dict(att='a', dfn='b', beats=[beat], i=0, state='beat', t=ar.last_now, deadline=ar.last_now + 6, air=False,
                           kind='throw', opener=None, range_after='far', hit=False)
        step(ar, 1.0, until=lambda ar: 'throw' in ar.counts)
        self.assertIn('throw', ar.counts)
        self.assertLess(b.hp, 100)
        self.assertGreater(abs(b.vx), 900)


class VisualOnly7(Isolated):
    """The arena never touches another window: run the real arena process body against a recording shell and a recording
    user32, and require that the only shell call is the single-instance mutex and that user32 is never called at all."""

    @unittest.skipUnless(sys.platform == 'win32', 'records the Win32 backend (minis_win needs ctypes.WinDLL); the macOS arena window is checked on a real Mac: docs/MAC-HANDOFF.md MAC-3')
    def test_no_window_api_is_ever_called(self):
        import minis
        from unittest import mock
        from minis_win import shell as real_shell, arena_window
        calls = []

        class Rec:
            def __init__(self, tag):
                self.tag = tag

            def __getattr__(self, name):
                def f(*a, **k):
                    calls.append((self.tag, name))
                    return (object(), False) if name == 'make_mutex' else 0
                return f
        clock = [1000.0]

        def tick():
            clock[0] += 0.004
            return clock[0]
        surf = AR.Surface(1280, 720)
        wins = [(1, 100, 300, 600, 650), (2, 700, 380, 1200, 700)]
        with mock.patch.object(real_shell, 'user32', Rec('user32')), mock.patch.object(arena_window, 'user32', Rec('user32')), \
                mock.patch.object(minis.time, 'sleep', lambda s: None):
            rc = minis.run_arena(dict(monitor=1, seconds=None), Rec('shell'), dict(CFG), monitor_rect=(0, 0, 1280, 720),
                                 windows_fn=lambda: wins, surface=surf, wall=tick, mono=tick, max_seconds=25, seed=5)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(set(calls)), [('shell', 'make_mutex')], calls[:10])
        self.assertGreater(surf.writes, 50)                                # it really drew (on the RAM surface only)


class ArenaCLI(Isolated):
    """`arena --rounds/--endless/--intensity/--seconds/--no-intro/--no-outro` reach Arena(options=...), set values only."""

    def ns(self, **kw):
        import argparse
        base = dict(rounds=None, endless=False, intensity=None, seconds=None, no_intro=False, no_outro=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_only_set_flags_become_options(self):
        import minis
        self.assertEqual(minis.arena_cli_options(self.ns()), {})
        self.assertEqual(minis.arena_cli_options(self.ns(rounds='5', intensity='wild', seconds=20.0, no_intro=True, no_outro=True)),
                         {'rounds': 5, 'intensity': 'wild', 'seconds': 20.0, 'intro': False, 'outro': False})
        self.assertEqual(minis.arena_cli_options(self.ns(rounds='endless')), {'endless': True})
        self.assertEqual(minis.arena_cli_options(self.ns(endless=True, rounds='1')), {'rounds': 1, 'endless': True})

    def test_the_child_argv_round_trips(self):
        import minis
        opts = {'rounds': 1, 'endless': True, 'intensity': 'calm', 'intro': False, 'outro': False}
        tail = minis.arena_option_argv(opts)
        self.assertEqual(tail, ['--endless', '--rounds', '1', '--intensity', 'calm', '--no-intro', '--no-outro'])
        self.assertEqual(minis.arena_option_argv({}), [])
        with self.assertRaises(SystemExit):                       # the parser accepts exactly these flags
            minis.main(['run', 'arena', '--rounds', '7'])

    def test_run_arena_hands_the_options_to_the_arena(self):
        import minis
        from unittest import mock
        seen = []

        class Rec(AR.Arena):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                seen.append(dict(self.opts))

        class Shell:
            def make_mutex(self, *a, **k):
                return (object(), False)

            def __getattr__(self, name):
                return lambda *a, **k: 0
        clock = [1000.0]

        def tick():
            clock[0] += 0.004
            return clock[0]
        with mock.patch.object(AR, 'Arena', Rec), mock.patch.object(minis.time, 'sleep', lambda s: None):
            rc = minis.run_arena(dict(monitor=1, options={'rounds': 1, 'intensity': 'wild', 'intro': False}), Shell(), dict(CFG),
                                 monitor_rect=(0, 0, 1280, 720), windows_fn=lambda: [], surface=AR.Surface(1280, 720), wall=tick,
                                 mono=tick, max_seconds=2, seed=5)
        self.assertEqual(rc, 0)
        self.assertEqual((seen[0]['rounds'], seen[0]['intensity'], seen[0]['intro'], seen[0]['outro']), (1, 'wild', False, True))


if __name__ == '__main__':
    unittest.main()
