"""Two REAL slot processes talking over the real bus files (slow: ~40 s, so it is opt-in).

    PowerShell:  $env:MINIS_INTEGRATION=1; python -m unittest tests.test_integration_processes -v
    bash:        MINIS_INTEGRATION=1 python -m unittest tests.test_integration_processes -v

Each process is `tests/two_process_harness.py <slot>`: the real minis.run_slot / Fighter / Brain against a temp data dir
(its own LOCALAPPDATA), with fake sources and a headless shell (no windows on the desktop).  The test only reads what the
processes wrote: bus files (sampled every 0.1 s), the present logs and the slot logs.

Scenario: The author's case - slot a "working" (Claude), slot b "idle" (Gemini).  A clash must start from usage on its own;
at ~20 s a demo spar is requested through control.json (what `minis.py demo` / the menu do).
"""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from minis_core import config as cfgmod, control  # noqa: E402

RUN_S = 40.0
DEMO_AT = 20.0
LINE = re.compile(r' INFO (bout|contact|hit) (\S+) ([0-9.]+) (\S+)$')


def _cannot_run():
    """Why this machine cannot run the process-level suite, or None.  The harness processes drive the Windows backend
    (minis_win: named mutexes, the headless overlay stands in for the layered windows), so it is Windows-only; a runner
    where that backend cannot even load says so instead of failing with a stack trace from a child process."""
    if not os.environ.get('MINIS_INTEGRATION'):
        return 'slow process-level test: set MINIS_INTEGRATION=1'
    if sys.platform != 'win32':
        return f'process-level suite is Windows-only (the harness drives minis_win); this is {sys.platform}'
    try:
        from minis_win import shell as real_shell
        h, _ = real_shell.make_mutex(f'minis-integration-probe-{os.getpid()}')
        if not h:
            return 'the Windows backend loaded but could not create a named mutex'
    except Exception as e:                                       # noqa: BLE001 - any failure here means "cannot run", said loudly
        return f'the Windows backend cannot load here: {type(e).__name__}: {e}'
    return None


SKIP = _cannot_run()
if SKIP and os.environ.get('MINIS_INTEGRATION'):
    print(f'\n*** MINIS_INTEGRATION=1 but the process-level suite is SKIPPED: {SKIP} ***\n', file=sys.stderr, flush=True)


def _env(tmp):
    """The child processes' environment: every data path (LOCALAPPDATA on Windows, MINIS_DATA_BASE anywhere, which wins over
    it) points into the temp dir, so nothing reads or writes the real data folder."""
    return dict(os.environ, LOCALAPPDATA=str(tmp), MINIS_DATA_BASE=str(tmp), PYTHONDONTWRITEBYTECODE='1')


def _bus(data, slot):
    try:
        return json.loads((data / 'bus' / f'{slot}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _present_counts(data):
    """How many frames each slot has presented so far (lines in its headless present log), or None before both exist."""
    out = {}
    for s in 'ab':
        try:
            with open(data / f'present-{s}.log', encoding='ascii') as f:
                out[s] = sum(1 for _ in f)
        except OSError:
            return None
    return out


def _wait_for(cond, timeout, what, procs=()):
    """Poll `cond` until it is true (a condition, not a fixed sleep); fail loudly on timeout or when a process died."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return time.monotonic() - t0
        dead = [p.args for p in procs if p.poll() is not None]
        if dead:
            raise AssertionError(f'waiting for {what}: a process exited early: {dead}')
        time.sleep(0.05)
    raise AssertionError(f'timed out after {timeout} s waiting for {what}')


@unittest.skipIf(SKIP, SKIP or '')
class TwoRealProcesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='minis-2proc-'))
        data = cls.data = cls.tmp / 'minis'
        (data / 'fake').mkdir(parents=True)
        (data / 'fake' / 'srcA.json').write_text(json.dumps({'state': 'working', 'ctx': 41.0}))
        (data / 'fake' / 'srcB.json').write_text(json.dumps({'state': 'idle', 'ctx': None}))
        (data / 'harness.json').write_text(json.dumps({'cfg': {'clash_min_s': 6, 'clash_max_s': 9}}))
        (data / 'assign.json').write_text(json.dumps({'a': {'source': 'srcA', 'character': 'claude', 'program': 'Claude Code'},
                                                      'b': {'source': 'srcB', 'character': 'gemini', 'program': 'Gemini'},
                                                      'ts': time.time()}))
        env = _env(cls.tmp)
        cls.procs = [subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'two_process_harness.py'), s], env=env, cwd=str(ROOT),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000) for s in 'ab']
        cls.samples = []
        t0 = time.monotonic()
        demo_sent = False
        try:
            while time.monotonic() - t0 < RUN_S:
                el = time.monotonic() - t0
                if not demo_sent and el >= DEMO_AT:
                    control.request_demo('spar', path=data / 'control.json')
                    demo_sent = el
                row = {'t': el}
                for s in 'ab':
                    try:
                        row[s] = json.loads((data / 'bus' / f'{s}.json').read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        row[s] = None
                cls.samples.append(row)
                time.sleep(0.1)
        finally:
            cls.alive_at_end = [p.poll() is None for p in cls.procs]
            for p in cls.procs:
                p.terminate()
            cls.errs = [p.communicate(timeout=10)[1].decode('utf-8', 'replace') for p in cls.procs]
        cls.demo_sent = demo_sent
        cls.notes = {s: cls._notes(data / f'{s}.log') for s in 'ab'}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    @staticmethod
    def _notes(path):
        out = []
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                m = LINE.search(line)
                if m:
                    out.append((m.group(1), m.group(2), float(m.group(3)), m.group(4)))
        except OSError:
            pass
        return out

    def both(self):
        return [r for r in self.samples if r['a'] and r['b'] and r['a'].get('state') != 'gone' and r['b'].get('state') != 'gone']

    # ------------------------------------------------------------------ the assertions asked for
    def test_0_processes_ran_without_crashing(self):
        self.assertEqual(self.alive_at_end, [True, True], self.errs)
        self.assertGreater(len(self.both()), RUN_S * 5)
        for s in 'ab':
            text = (self.data / f'{s}.log').read_text(encoding='utf-8')
            self.assertNotIn('ERROR', text, text[-2000:])

    def test_a_positions_stay_apart_outside_bouts_and_off_the_plates(self):
        # The bus x is the brain's hip in RES 1 px; at fighter size N the window shows that world k = N/64 times larger, and
        # the sprite reaches clearance_px(N) - HUD_GAP screen px behind the hip (V7.1).  The harness keeps the default size and
        # the legacy (rect-only) taskbar, so the zone is DEFAULTS['zone'].
        size = cfgmod.DEFAULTS['fighter_size']
        k, reach = size / 64.0, cfgmod.clearance_px(size) - cfgmod.HUD_GAP
        plates_end = cfgmod.plate_left(cfgmod.DEFAULTS, 'b') + cfgmod.PLATE_W
        outside = 0
        for r in self.both():
            a, b = r['a'], r['b']
            for p in (a, b):
                left = float(p['x']) * k - reach                   # screen x of the sprite's furthest-back pixel
                self.assertGreaterEqual(left, plates_end, f"t={r['t']:.1f} {p['who']} over the plates: hip x={p['x']} (RES 1), "
                                                          f"sprite from {left:.0f} px, plates end at {plates_end} px")
            if a.get('bout') or b.get('bout') or 'script' in (a['mode'], b['mode']):
                continue
            outside += 1
            self.assertGreaterEqual(abs(float(a['x']) - float(b['x'])), 20, f"t={r['t']:.1f}: a {a['x']} b {b['x']}")
            self.assertLess(float(a['x']), float(b['x']))
        self.assertGreater(outside, 50)

    def test_b_animation_frames_change_over_time(self):
        for s in 'ab':
            rows = [ln.split() for ln in (self.data / f'present-{s}.log').read_text(encoding='ascii').splitlines()]
            crcs = {r[2] for r in rows}
            span = float(rows[-1][0]) - float(rows[0][0])
            self.assertGreaterEqual(len(crcs), 8, f'{s}: only {len(crcs)} distinct frames')
            self.assertGreater(span, RUN_S * 0.8)
            # no long freeze: some new frame at least every 1.5 s while visible
            gaps = [float(b[0]) - float(a[0]) for a, b in zip(rows, rows[1:])]
            self.assertLess(max(gaps), 1.5, f'{s}: a {max(gaps):.1f} s gap between frames')
            plate = [ln.split() for ln in (self.data / f'present-{s}-plate.log').read_text(encoding='ascii').splitlines()]
            self.assertEqual({p[1] for p in plate}, {str(cfgmod.plate_left(cfgmod.DEFAULTS, s))})      # the plate never moves

    def test_c_a_bout_happens_and_both_sides_agree_on_contact_times(self):
        scripted = [(r['t'], r['a']['bout']) for r in self.both() if r['a']['mode'] == 'script' and r['b']['mode'] == 'script'
                    and r['a'].get('bout') and r['a'].get('bout') == r['b'].get('bout')]
        self.assertTrue(scripted, 'never saw both fighters in script mode on the same bout')
        bouts = {s: {n[1]: n[3] for n in self.notes[s] if n[0] == 'bout'} for s in 'ab'}
        common = set(bouts['a']) & set(bouts['b'])
        kinds = {bouts['a'][i] for i in common}
        self.assertIn('clash', kinds, f'no clash from usage (a working, b idle): {kinds}')
        self.assertIn('spar-demo', kinds, f'the demo spar did not happen: {kinds}')
        matched = 0
        for bid in common:
            for att, dfn in (('a', 'b'), ('b', 'a')):
                hits = {round(t, 2) for w, i, t, m in self.notes[dfn] if i == bid and w == 'hit'}
                for w, i, t, m in self.notes[att]:
                    if i != bid or w != 'contact':
                        continue
                    if m in ('fistbump', 'highfive'):                          # both play it: same instant on both sides
                        other = {round(t2, 2) for w2, i2, t2, m2 in self.notes[dfn] if i2 == bid and w2 == 'contact' and m2 == m}
                        self.assertIn(round(t, 2), other, f'{bid} {m}')
                    else:
                        self.assertIn(round(t, 2), hits, f'{bid}: {att} {m} lands at {t} but {dfn} reacts at {sorted(hits)}')
                    matched += 1
        self.assertGreaterEqual(matched, 6)
        apart = [abs(float(r['a']['x']) - float(r['b']['x'])) for r in self.both()
                 if not (r['a'].get('bout') or r['b'].get('bout') or 'script' in (r['a']['mode'], r['b']['mode']))]
        print(f'\n  [2proc] bouts on both sides: {sorted(bouts["a"][i] for i in common)}; contact/reaction pairs matched: {matched}; '
              f'both scripted in {len(scripted)} samples; closest outside bouts: {min(apart):.1f} px', file=sys.stderr)


@unittest.skipIf(SKIP, SKIP or '')
class RivalWithASleepingPartner(unittest.TestCase):
    """V5.1 rival mode with two REAL slot processes: slot a idle (Claude), slot b the sparring bot (its detector sees nothing, so
    it is `sleeping` with no numbers).  With the rival timers at 6 s the awake side must wake the sleeper for a best-of-3, both
    sides must play it, the record must be written once, and the sleeper's bus state must say `sleeping` the whole time."""
    RUN_S = 130.0                        # cap; the sampling stops as soon as the match is recorded and the sleeper is back asleep

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='minis-rival-'))
        data = cls.data = cls.tmp / 'minis'
        (data / 'fake').mkdir(parents=True)
        (data / 'fake' / 'srcA.json').write_text(json.dumps({'state': 'idle', 'ctx': 41.0}))
        (data / 'harness.json').write_text(json.dumps({'cfg': {'rival_min': 0.1, 'rival_max': 0.1, 'rival_spar_min': 0.1, 'rival_spar_max': 0.1,
                                                              'bout_min_s': 999, 'bout_max_s': 999}}))
        (data / 'assign.json').write_text(json.dumps({'a': {'source': 'srcA', 'character': 'claude', 'program': 'Claude Code'},
                                                      'b': {'source': 'sparring', 'character': 'generic', 'program': 'Sparring bot', 'bot': True},
                                                      'ts': time.time()}))
        env = _env(cls.tmp)
        cls.procs = [subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'two_process_harness.py'), s], env=env, cwd=str(ROOT),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000) for s in 'ab']
        cls.samples = []
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < cls.RUN_S:
                row = {'t': time.monotonic() - t0}
                for s in 'ab':
                    try:
                        row[s] = json.loads((data / 'bus' / f'{s}.json').read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        row[s] = None
                cls.samples.append(row)
                b = row['b'] or {}
                if row['t'] > 20 and (data / 'record.json').exists() and b.get('mode') == 'home' and b.get('anim') == 'sleep':
                    time.sleep(0.5)                                     # one more beat asleep, then stop before the next rival bout
                    break
                time.sleep(0.1)
        finally:
            cls.alive_at_end = [p.poll() is None for p in cls.procs]
            for p in cls.procs:
                p.terminate()
            cls.errs = [p.communicate(timeout=10)[1].decode('utf-8', 'replace') for p in cls.procs]
        cls.notes = {s: TwoRealProcesses._notes(data / f'{s}.log') for s in 'ab'}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def both(self):
        return [r for r in self.samples if r['a'] and r['b'] and r['a'].get('state') != 'gone' and r['b'].get('state') != 'gone']

    def test_0_processes_ran_without_crashing(self):
        self.assertEqual(self.alive_at_end, [True, True], self.errs)
        self.assertGreater(len(self.both()), 200)                                           # 20 s at least, both alive
        for s in 'ab':
            self.assertNotIn('ERROR', (self.data / f'{s}.log').read_text(encoding='utf-8'))

    def test_a_the_sleeper_is_woken_for_a_rival_match_and_the_plate_keeps_saying_sleeping(self):
        bouts = {s: {n[1]: n[3] for n in self.notes[s] if n[0] == 'bout'} for s in 'ab'}
        common = set(bouts['a']) & set(bouts['b'])
        self.assertIn('match-rival', {bouts['a'][i] for i in common}, f'no rival match on both sides: {bouts}')
        rows = self.both()
        self.assertEqual({r['b']['state'] for r in rows}, {'sleeping'})                    # the truth, before, during and after
        self.assertEqual({r['b']['ctx'] for r in rows}, {None})
        anims = [r['b']['anim'] for r in rows]
        self.assertIn('wake', anims)
        self.assertLess(anims.index('wake'), anims.index('walk'), 'it must stretch and yawn before walking out')
        self.assertTrue(any(r['b']['mode'] == 'script' and r['a']['mode'] == 'script' for r in rows), 'both never in the bout together')
        hits = [n for n in self.notes['a'] + self.notes['b'] if n[0] in ('hit', 'contact')]
        self.assertGreaterEqual(len(hits), 4)

    def test_b_the_result_is_recorded_once_and_the_sleeper_goes_back_to_sleep(self):
        rec = json.loads((self.data / 'record.json').read_text(encoding='utf-8'))
        self.assertEqual(rec.get('matches'), 1, rec)
        self.assertEqual({rec['last']['winner'], rec['last']['loser']}, {'srcA', 'sparring'})       # V6: keyed by program (source id)
        self.assertEqual(set(rec['programs']), {'srcA', 'sparring'}, rec)
        self.assertEqual(rec['last']['where'], 'taskbar')
        last = self.both()[-1]
        self.assertEqual((last['b']['mode'], last['b']['anim']), ('home', 'sleep'), last['b'])
        print(f"\n  [rival] bouts: {sorted(set(n[3] for n in self.notes['a'] if n[0] == 'bout'))}; hits/contacts: "
              f"{len([n for n in self.notes['a'] + self.notes['b'] if n[0] in ('hit', 'contact')])}; record {rec['last']['winner']} > {rec['last']['loser']}",
              file=sys.stderr)


@unittest.skipIf(SKIP, SKIP or '')
class ArenaWithTwoSlots(unittest.TestCase):
    """Two real slot processes + one real arena process (headless surface, synthetic monitor + windows, synthetic backdrop)
    for ~30 s: the slots hide while the arena heartbeat is fresh, rounds progress, a winner is recorded, nothing is written
    outside the temp data dir, and the slots come back when the arena leaves."""
    ARENA_S = 120.0                      # a best-of-3 takes ~60 s, up to ~95 s when every round goes the full 25 s (physics timing is
                                         # real time, so it varies run to run); the arena leaves on its own at ARENA_S at the latest

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='minis-arena-'))
        data = cls.data = cls.tmp / 'minis'
        (data / 'fake').mkdir(parents=True)
        (data / 'fake' / 'srcA.json').write_text(json.dumps({'state': 'idle', 'ctx': 30.0}))
        (data / 'fake' / 'srcB.json').write_text(json.dumps({'state': 'working', 'ctx': 55.0}))
        rect = [2560, 76, 4480, 1156]
        wins = [[11, 2560 + 300, 76 + 200, 2560 + 1200, 76 + 800], [12, 2560 + 1300, 76 + 300, 2560 + 1800, 76 + 900]]
        (data / 'harness.json').write_text(json.dumps({'cfg': {'bout_min_s': 999, 'bout_max_s': 999, 'clash_min_s': 999, 'clash_max_s': 999},
                                                       'arena': {'rect': rect, 'windows': wins, 'seconds': cls.ARENA_S, 'freeze': True, 'seed': 3, 'monitor': 2}}))
        (data / 'assign.json').write_text(json.dumps({'a': {'source': 'srcA', 'character': 'claude', 'program': 'Claude Code'},
                                                      'b': {'source': 'srcB', 'character': 'codex', 'program': 'Codex'}, 'ts': time.time()}))
        env = _env(cls.tmp)
        cls.procs = [subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'two_process_harness.py'), s], env=env, cwd=str(ROOT),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000) for s in 'ab']
        _wait_for(lambda: all(_bus(data, s) for s in 'ab'), 30, 'both slots on the bus before the arena starts', cls.procs)
        cls.arena = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'arena_harness.py')], env=env, cwd=str(ROOT),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000)
        cls.samples = []
        t0 = time.monotonic()
        exited = None
        try:
            while time.monotonic() - t0 < cls.ARENA_S + 20:
                row = {'t': time.monotonic() - t0}
                for name in ('a', 'b'):
                    try:
                        row[name] = json.loads((data / 'bus' / f'{name}.json').read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        row[name] = None
                try:
                    row['arena'] = json.loads((data / 'arena.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    row['arena'] = None
                row['present'] = _present_counts(data)
                cls.samples.append(row)
                if cls.arena.poll() is not None:
                    exited = exited if exited is not None else row['t']
                    if row['t'] > exited + 6:
                        break                                 # a few seconds of samples after the arena left
                time.sleep(0.2)
        finally:
            cls.arena_rc = cls.arena.poll()
            cls.slots_alive = [p.poll() is None for p in cls.procs]
            for p in cls.procs + [cls.arena]:
                if p.poll() is None:
                    p.terminate()
            cls.errs = [p.communicate(timeout=10)[1].decode('utf-8', 'replace') for p in cls.procs + [cls.arena]]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def arena_rows(self):
        return [r for r in self.samples if r['arena'] and r['arena'].get('active')]

    def test_0_all_three_processes_ran_and_the_arena_left_on_its_own(self):
        self.assertEqual(self.slots_alive, [True, True], self.errs)
        self.assertEqual(self.arena_rc, 0, self.errs[2])
        for name in ('a', 'b', 'arena'):
            text = (self.data / f'{name}.log').read_text(encoding='utf-8')
            self.assertNotIn('ERROR', text, text[-2000:])

    def test_a_rounds_progress_and_a_winner_is_recorded(self):
        states = [r['arena'] for r in self.arena_rows()]
        self.assertTrue(states, 'no arena heartbeat seen')
        phases = []
        for s in states:
            if not phases or phases[-1] != s['phase']:
                phases.append(s['phase'])
        self.assertIn('fight', phases, phases)
        self.assertGreaterEqual(max(s['round'] for s in states), 1)
        hps = [tuple(s['hp'].values()) for s in states]
        self.assertTrue(any(min(h) < 100 for h in hps), hps[:10])
        rec = json.loads((self.data / 'record.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['matches'], 1)
        self.assertEqual(rec['last']['where'], 'arena')
        self.assertEqual(set(rec['programs']), {'srcA', 'srcB'}, rec)                # V6: keyed by program (source id)
        self.assertEqual({rec['last']['winner'], rec['last']['loser']}, {'srcA', 'srcB'}, rec)
        last = states[-1]
        self.assertTrue(last['phase'] in ('winner', 'exit', 'done') or last['winner'] in ('a', 'b'), last)
        print(f"\n  [arena] phases {phases}; rounds {max(s['round'] for s in states)}; winner {last.get('winner')}; "
              f"cracks {last.get('cracks')} shattered {last.get('shattered')}; freeze {last.get('freeze')}; cpu {last.get('cpu_pct')}%", file=sys.stderr)

    def test_b_taskbar_fighters_hide_during_the_arena_and_return(self):
        rows = self.arena_rows()
        self.assertTrue(rows)
        t_in, t_out = rows[0]['t'], rows[-1]['t']
        # The slots may legitimately come back if the heartbeat goes stale (a crashed arena); make that case say so instead of
        # looking like a hide bug.  (A heartbeat newer than a slot's clock is fresh: control.arena_state.)
        beats = sorted({r['arena']['ts'] for r in rows})
        worst = max((b - a for a, b in zip(beats, beats[1:])), default=0.0)
        self.assertLess(worst, control.ARENA_FRESH_S, f'the arena heartbeat stalled {worst:.1f} s (machine overloaded?)')
        during = [r for r in self.samples if t_in + 4 < r['t'] < t_out - 1 and r['present']]
        self.assertGreater(len(during), 10)
        for s in 'ab':
            counts = [r['present'][s] for r in during]
            self.assertEqual(counts[0], counts[-1], f'{s} kept drawing while the arena was up')     # hidden: no present() calls
        after = [r for r in self.samples if r['t'] > t_out + 3 and r['present']]
        self.assertTrue(after, 'no samples after the arena left')
        for s in 'ab':
            self.assertGreater(after[-1]['present'][s], during[-1]['present'][s], f'{s} did not come back')
        self.assertFalse(json.loads((self.data / 'arena.json').read_text(encoding='utf-8')).get('active'))

    def test_c_the_freeze_backdrop_left_no_file_behind(self):
        names = {p.name for p in self.data.rglob('*') if p.is_file()}
        self.assertFalse(any(n.lower().endswith(('.png', '.bmp', '.jpg', '.jpeg', '.raw')) for n in names), names)


if __name__ == '__main__':
    unittest.main()
