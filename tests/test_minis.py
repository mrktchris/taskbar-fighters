import io, json, ntpath, os, sys, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, CFG, Isolated  # noqa: E402
import minis  # noqa: E402
from minis_core import bus, config as cfgmod, control, director, lineup as L  # noqa: E402
from minis_core.sources import Activity  # noqa: E402

PY = r'C:\Python314\pythonw.exe'
SCRIPT = str(ROOT / 'minis.py')


class Identity(unittest.TestCase):
    def test_exact_argv_only(self):
        ok = minis.argv_is_ours
        self.assertTrue(ok([PY, SCRIPT, 'run', 'a'], 'a'))
        if sys.platform == 'win32':                                                       # Windows paths ignore case; macOS paths do not
            self.assertTrue(ok([r'C:\Python314\python.exe', SCRIPT.upper(), 'director'], 'director'))
        self.assertTrue(ok([PY, SCRIPT, 'run', 'claude'], 'claude'))                     # v2 fighters
        self.assertFalse(ok([PY, SCRIPT, 'run', 'b'], 'a'))
        self.assertFalse(ok([PY, SCRIPT, 'run', 'a', '--x'], 'a'))
        self.assertFalse(ok([PY, r'C:\elsewhere\minis.py', 'run', 'a'], 'a'))
        self.assertFalse(ok([PY, SCRIPT + '.bak', 'run', 'a'], 'a'))
        self.assertFalse(ok([r'C:\x\notpython.exe', SCRIPT, 'run', 'a'], 'a'))
        self.assertFalse(ok([PY, '-c', f'"{SCRIPT} run a"'], 'a'))                       # mentions everything, is none of it
        self.assertFalse(ok([], 'a'))
        self.assertFalse(ok(None, 'a'))
        self.assertTrue(ok([PY, SCRIPT, 'run', 'arena', '--monitor', '2', '--freeze'], 'arena'))     # the arena carries options
        self.assertTrue(ok([PY, SCRIPT, 'run', 'arena'], 'arena'))
        self.assertFalse(ok([PY, SCRIPT, 'run', 'a', '--monitor', '2'], 'arena'))
        self.assertFalse(ok([PY, SCRIPT, 'run', 'arena', '--monitor', '2'], 'a'))


class Stop(Isolated):
    def setUp(self):
        super().setUp()
        for role, pid in (('a', 111), ('b', 222), ('director', 333)):
            (self.data / f'{role}.pid').write_text(str(pid))
        self.killed = []

    def run_stop(self, argvs, alive=lambda pid: True):
        def fake_run(cmd, **kw):
            self.killed.append(cmd)
            return mock.Mock(returncode=0)
        out = io.StringIO()
        with mock.patch.object(minis, 'pid_alive', alive), mock.patch.object(minis, 'proc_argv', lambda pid: argvs.get(pid)), \
                mock.patch.object(minis.subprocess, 'run', fake_run), redirect_stdout(out), \
                mock.patch('minis_platform.current', lambda platform=None: 'win'):        # the Windows (taskkill) path, on any OS
            rc = minis.cmd_stop()
        return rc, out.getvalue()

    def test_foreign_and_unreadable_command_lines_are_never_killed(self):
        rc, out = self.run_stop({111: [r'C:\Windows\notepad.exe', 'x.txt'], 222: [], 333: None})
        self.assertEqual(self.killed, [])
        self.assertIn('a: pid 111 is not a minis process', out)
        self.assertIn('b: could not verify pid 222', out)
        self.assertIn('director: could not verify pid 333', out)
        for role in ('a', 'b', 'director'):
            self.assertTrue((self.data / f'{role}.pid').exists(), role)       # evidence kept

    def test_ours_are_killed_by_full_path_and_pid_files_removed(self):
        argvs = {111: [PY, SCRIPT, 'run', 'a'], 222: [PY, SCRIPT, 'run', 'b'], 333: [PY, SCRIPT, 'director']}
        rc, out = self.run_stop(argvs)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(c[2] for c in self.killed), ['111', '222', '333'])
        for c in self.killed:
            self.assertEqual(c[0], minis.TASKKILL)
            self.assertTrue(ntpath.isabs(c[0]) and ntpath.normcase(c[0]).endswith(r'system32\taskkill.exe'))   # a Windows path on any OS
        for role in ('a', 'b', 'director'):
            self.assertFalse((self.data / f'{role}.pid').exists())
        self.assertIsNone(bus.read('a', now=__import__('time').time()))          # a killed fighter reads as gone
        self.assertEqual(bus.read('a', raw=True)['state'], 'gone')

    def test_slot_pid_running_another_slot_is_left_alone(self):
        rc, out = self.run_stop({111: [PY, SCRIPT, 'run', 'b'], 222: [PY, SCRIPT, 'run', 'b'], 333: [PY, SCRIPT, 'director']})
        self.assertNotIn('111', [c[2] for c in self.killed])

    def test_dead_pid_is_just_a_stale_file(self):
        rc, out = self.run_stop({}, alive=lambda pid: False)
        self.assertEqual(self.killed, [])
        self.assertFalse((self.data / 'a.pid').exists())
        self.assertIn('a: not running', out)

    def test_running_needs_the_command_line_not_just_a_live_pid(self):
        with mock.patch.object(minis, 'pid_alive', lambda pid: True), mock.patch.object(minis, 'proc_argv', lambda pid: [r'C:\x\game.exe']):
            self.assertIsNone(minis.running('a'))                          # a pid reused after a reboot
        with mock.patch.object(minis, 'pid_alive', lambda pid: True), mock.patch.object(minis, 'proc_argv', lambda pid: [PY, SCRIPT, 'run', 'a']):
            self.assertEqual(minis.running('a'), 111)


class Commands(Isolated):
    def test_pause_and_resume_write_control_json(self):
        with redirect_stdout(io.StringIO()):
            minis.cmd_pause()
        self.assertTrue(json.loads((self.data / 'control.json').read_text())['paused'])
        self.assertTrue(control.paused())
        with redirect_stdout(io.StringIO()):
            minis.cmd_resume()
        self.assertFalse(control.paused())

    def test_status_runs_without_any_processes(self):
        out = io.StringIO()
        with mock.patch.object(minis, 'pid_alive', lambda pid: False), redirect_stdout(out):
            minis.cmd_status()
        self.assertIn('assign.json: missing', out.getvalue())
        self.assertIn('animations: running', out.getvalue())

    def test_status_names_a_dormant_partner_and_the_sparring_bot(self):
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                               'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex', 'dormant': True}, 'ts': 1.0})
        out = io.StringIO()
        with mock.patch.object(minis, 'pid_alive', lambda pid: False), redirect_stdout(out):
            minis.cmd_status()
        self.assertIn('-> Codex as codex  (dormant partner', out.getvalue())
        director.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': dict(director.SPARRING_ASSIGN), 'ts': 2.0})
        out = io.StringIO()
        with mock.patch.object(minis, 'pid_alive', lambda pid: False), redirect_stdout(out):
            minis.cmd_status()
        self.assertIn('-> Sparring bot as generic  (sparring bot', out.getvalue())

    def test_rival_cli_writes_control_and_the_config_default_applies_until_then(self):
        self.assertTrue(control.rival_on(default=True))
        self.assertFalse(control.rival_on(default=False))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(minis.main(['rival', 'off']), 0)
        self.assertFalse(control.rival_on(default=True))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(minis.main(['rival', 'on']), 0)
        self.assertTrue(control.rival_on(default=False))
        with self.assertRaises(SystemExit):
            minis.main(['rival', 'maybe'])

    def test_detect_prints_names_states_and_how_never_paths(self):
        from minis_core import sources
        rows = [dict(source='claude', program='Claude Code', character='claude', state='idle', how='transcript, newest session file 4 min old, ctx 77%'),
                dict(source='cursor', program='Cursor', character='cursor', state='-', how='not running (would match exe cursor.exe)')]
        out = io.StringIO()
        with mock.patch.object(sources, 'describe', lambda cfg, now, srcs: rows), mock.patch.object(sources.Sources, 'poll', lambda self, now: []), \
                mock.patch('time.sleep', lambda s: None), redirect_stdout(out):
            self.assertEqual(minis.main(['detect']), 0)
        text = out.getvalue()
        self.assertIn('claude      Claude Code  claude    idle      transcript, newest session file 4 min old, ctx 77%', text)
        self.assertIn('1 of 2 known programs seen: Claude Code', text)

    def test_log_is_rotating_and_never_carries_a_file_name(self):
        log = minis.get_logger('t-slot')
        try:
            open(str(self.data / 'secret-project-name' / 'session.jsonl'))
        except OSError as e:
            log.error(minis.safe_traceback(e))
        for h in log.handlers:
            h.flush()
        text = (self.data / 't-slot.log').read_text(encoding='utf-8')
        self.assertIn('FileNotFoundError errno=2', text)
        self.assertNotIn('secret-project-name', text)
        h = log.handlers[0]
        self.assertEqual((h.maxBytes, h.backupCount), (CFG['log_max_bytes'], 1))
        for h in list(log.handlers):
            h.close()
            log.removeHandler(h)


# ---------------------------------------------------------------------------------------- the fighter loop, headless
class FakeOverlay:
    def __init__(self, title, x, y, w, h, scale=1, on_event=None, on_timer=None, on_hittest=None, on_key=None, activatable=False,
                 on_blur=None):
        self.title, self.x, self.y, self.w, self.h, self.scale, self.on_event, self.on_timer = title, x, y, w, h, scale, on_event, on_timer
        self.on_hittest, self.on_key, self.activatable, self.on_blur = on_hittest, on_key, activatable, on_blur
        self.visible = True
        self.presented, self.menu_choice, self.tops, self.items, self.focused, self.closed = [], 0, 0, [], False, False
        FakeOverlay.made.append(self)

    made = []

    def focus(self):
        self.focused = True

    def pump(self):
        return True

    def present(self, im, x=None):
        self.presented.append((im.size, x))
        return True

    def show(self, v):
        self.visible = v

    def reassert_topmost(self):
        self.tops += 1

    def move(self, x, y):
        self.x, self.y = x, y

    def set_scale(self, s):
        self.scale = s

    def menu(self, items):
        self.items = items
        if self.on_timer:
            self.on_timer()
        return self.menu_choice

    def close(self):
        self.closed = True


class FakeShell:
    def __init__(self):
        self.rect = (0, 1392, 2560, 1440, 3)
        self.autohide = False
        self.Overlay = FakeOverlay

    def taskbar_rect(self):
        return self.rect

    def taskbar_autohide(self):
        return self.autohide

    def screen_size(self):
        return 2560, 1440

    def fullscreen_busy(self):
        return False


class FakeDetector:
    def __init__(self, source, state='idle', ctx=30.0):
        self.source, self.state, self.ctx, self.events = source, state, ctx, []

    def poll(self, now):
        ev, self.events = self.events, []
        return [Activity(self.source, self.source, self.source, self.state, self.ctx, events=ev)]


class FighterLoop(Isolated):
    def setUp(self):
        super().setUp()
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.dets = {}

        def det(src, cfg):
            self.dets[src] = FakeDetector(src)
            return self.dets[src]
        self.shell = FakeShell()
        self.f = minis.Fighter('a', dict(CFG, fighter_size=64), self.shell, mono=lambda: self.t['mono'], wall=lambda: self.t['wall'],
                               detector_for=det)                  # 64 px geometry (test_fighter_size covers 96 / 128)

    def assign(self, a=None, b=None):
        director.write_assign({'a': a, 'b': b, 'ts': self.t['wall']})

    def go(self, secs, dt=0.05):
        n = int(secs / dt)
        for _ in range(n):
            self.t['mono'] += dt
            self.t['wall'] += dt
            r = self.f.step()
            if r is None:
                return None
        return r

    def test_without_a_director_it_falls_back_to_claude(self):
        self.f.setup()
        self.go(0.5)
        self.assertEqual(self.f.assigned['source'], 'claude')
        self.assertTrue(self.f.ov.visible)
        self.assertTrue(self.f.ov.presented)

    def test_unassigned_slot_hides_and_reads_as_gone(self):
        self.assign(a=None)
        self.f.setup()
        self.go(0.5)
        self.assertFalse(self.f.ov.visible)
        self.assertEqual(self.f.ov.presented, [])
        self.assertIsNone(bus.read('a', now=self.t['wall']))
        self.assertEqual(bus.read('a', raw=True)['state'], 'gone')

    def test_a_new_assignment_switches_character_and_detector(self):
        self.assign(a={'source': 'claude', 'character': 'claude', 'program': 'Claude Code'})
        self.f.setup()
        self.go(1.2)
        self.assertEqual(self.f.brain.character, 'claude')
        self.assign(a={'source': 'cursor', 'character': 'cursor', 'program': 'Cursor'})
        self.go(1.2)
        self.assertEqual(self.f.brain.character, 'cursor')
        self.assertIn('cursor', self.dets)
        self.assertEqual(bus.read('a', now=self.t['wall'])['character'], 'cursor')

    def test_paused_draws_one_static_frame_and_sleeps_longer(self):
        self.assign(a={'source': 'claude', 'character': 'claude', 'program': 'Claude Code'})
        self.f.setup()
        self.go(1.0)
        control.set_paused(True)
        r = self.go(1.0)
        self.assertEqual(r, 0.25)
        n, pn = len(self.f.ov.presented), len(self.f.pov.presented)
        self.dets['claude'].state = 'working'                     # state changes still reach the plate ...
        self.go(3.0, dt=0.25)
        self.assertEqual(len(self.f.pov.presented), pn + 1)       # ... as exactly one plate redraw
        self.assertEqual(len(self.f.ov.presented), n)             # and the frozen fighter is not redrawn at all
        self.assertEqual(self.f.brain.view(self.t['mono'])['anim'], 'idle')
        self.assertTrue(bus.read('a', now=self.t['wall'])['paused'])

    def test_events_are_published_immediately(self):
        self.assign(a={'source': 'claude', 'character': 'claude', 'program': 'Claude Code'})
        self.f.setup()
        self.go(1.5)
        self.dets['claude'].events = ['limit']
        self.dets['claude'].ctx = 95.0
        self.t['mono'] += 1.0
        self.t['wall'] += 1.0
        self.f.step()
        self.assertEqual(bus.read('a', now=self.t['wall'])['event']['type'], 'limit')

    def test_taskbar_not_at_the_bottom_or_autohide_hides(self):
        self.f.setup()
        self.go(0.5)
        self.assertTrue(self.f.ov.visible)
        self.shell.autohide = True
        self.go(2.1)
        self.assertFalse(self.f.ov.visible)
        self.shell.autohide = False
        self.shell.rect = (0, 0, 2560, 48, 1)                     # taskbar moved to the top
        self.go(2.1)
        self.assertFalse(self.f.ov.visible)

    def test_a_bigger_taskbar_applies_the_new_scale(self):
        self.f.setup()
        self.go(0.5)
        self.shell.rect = (0, 1344, 2560, 1440, 3)                # 96 px band -> scale 2
        self.go(2.1)
        self.assertEqual(self.f.ov.scale, 2)
        self.assertEqual(self.f.g['scale'], 2)
        self.assertEqual(self.f.ov.y, 1440 - (64 + cfgmod.headroom_px(64)) * 2)   # the cell + the jump headroom, scaled
        self.assertEqual(self.f.ov.presented[-1][1] % 2, 0)       # window x is in scaled pixels

    def test_menu_keeps_the_heartbeat_and_can_pause_everyone(self):
        self.f.setup()
        self.go(0.5)
        self.f.ov.menu_choice = 4
        self.f.st['menu'] = True
        tops = self.f.ov.tops
        self.go(0.1)
        self.assertTrue(control.paused())
        self.assertGreater(self.f.ov.tops, tops)
        self.assertIn('Pause all animations', L.labels_of(self.f.ov.items))
        quits = []
        with mock.patch.object(minis, 'quit_all', lambda: quits.append(1) or True):
            self.f.ov.menu_choice = L.QUIT_ALL                   # "Quit minis" stops everything (a detached `stop`)
            self.f.st['menu'] = True
            self.go(0.1)
        self.assertEqual(quits, [1])
        self.assertIn('Quit Taskbar Fighters (stops everything)', L.labels_of(self.f.ov.items))

    def test_plate_is_a_fixed_window_at_the_left_named_after_the_program(self):
        from minis_core import config as cfgmod
        self.assign(a={'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                    b={'source': 'gemini', 'character': 'gemini', 'program': 'Gemini'})
        self.f.setup()
        self.go(1.0)
        pov = self.f.pov
        self.assertTrue(pov.visible)
        self.assertEqual(self.f.display_name(), 'Claude')
        xs = {x for _, x in pov.presented}
        self.assertEqual(xs, {cfgmod.plate_left(CFG, 'a')})
        self.assertEqual(pov.presented[-1][0], (cfgmod.PLATE_W, cfgmod.PLATE_H))
        self.assertTrue(1392 <= pov.y and pov.y + cfgmod.PLATE_H <= 1440)          # inside the taskbar band
        self.f.brain.x = self.f.brain.home[1]
        self.go(1.0)
        self.assertEqual({x for _, x in pov.presented}, xs)                         # never moves with the fighter
        for size, x in self.f.ov.presented:                                          # the fighter window never reaches it
            self.assertGreater(x, cfgmod.plate_left(CFG, 'b') + cfgmod.PLATE_W)

    def test_generic_skin_is_named_after_the_program(self):
        self.assign(a={'source': 'aider', 'character': 'generic', 'program': 'aider'})
        self.f.setup()
        self.go(0.5)
        self.assertEqual(self.f.display_name(), 'aider')

    def test_plates_off_hides_the_plate_window_and_on_brings_it_back(self):
        self.f.setup()
        self.go(0.6)
        self.assertTrue(self.f.pov.visible)
        with redirect_stdout(io.StringIO()):
            minis.main(['plates', 'off'])
        self.assertFalse(control.plates_on())
        self.go(0.6)
        self.assertFalse(self.f.pov.visible)
        self.assertTrue(self.f.ov.visible)                         # the fighter stays
        self.f.ov.menu_choice = 3                                  # the menu toggles it back, for both fighters
        self.f.st['menu'] = True
        self.go(0.6)
        self.assertTrue(control.plates_on())
        self.assertTrue(self.f.pov.visible)

    def test_demo_request_reaches_slot_a_once(self):
        self.f.setup()
        self.go(0.6)
        self.f.ov.menu_choice = 5                                  # "Start a bout now"
        self.f.st['menu'] = True
        self.go(0.6)
        self.assertIn('Start a bout now', L.labels_of(self.f.ov.items))
        self.assertIsNotNone(control.demo(now=self.t['wall']))
        self.assertEqual(self.f.brain.demo['kind'], 'spar')
        self.f.brain.demo = None
        self.go(1.0)
        self.assertIsNone(self.f.brain.demo)                       # the same request is not taken twice

    def test_demo_cli_validates_and_writes_control(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
            minis.main(['demo', 'handoff'])
        with mock.patch.object(minis, 'running', lambda role: None), redirect_stdout(io.StringIO()) as out:
            rc = minis.main(['demo', 'ranged'])
        self.assertEqual(rc, 1)                                    # written, but says the fighters are not running
        self.assertIn('must be running', out.getvalue())
        self.assertEqual(control.demo()['kind'], 'ranged')

    def test_fighters_hide_while_the_arena_is_up_and_come_back_after(self):
        self.f.setup()
        self.go(0.6)
        self.assertTrue(self.f.ov.visible)
        control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2, 'phase': 'fight'}, now=self.t['wall'])
        self.go(0.6)
        self.assertFalse(self.f.ov.visible)
        self.assertFalse(self.f.pov.visible)
        self.assertTrue(self.f.arena)
        self.t['wall'] += 10                                       # the heartbeat went stale (arena crashed): fighters return
        self.go(0.6)
        self.assertTrue(self.f.ov.visible)
        control.write_arena_state({'active': True, 'pid': 1}, now=self.t['wall'])
        self.go(0.6)
        self.assertFalse(self.f.ov.visible)
        control.clear_arena_state()
        self.go(0.6)
        self.assertTrue(self.f.ov.visible)

    def test_a_heartbeat_written_after_the_slot_read_its_clock_still_hides_the_fighters(self):
        """The slot takes its wall clock at the top of a step and reads arena.json later; under load the arena writes a
        heartbeat in between, stamped a little AFTER that clock.  That is the freshest heartbeat there is - it must not
        read as 'no arena' (the process-level suite caught the fighters flashing back mid-arena on a busy machine)."""
        self.f.setup()
        self.go(0.6)
        self.assertTrue(self.f.ov.visible)
        control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2, 'phase': 'fight'}, now=self.t['wall'])
        self.go(0.6)
        self.assertFalse(self.f.ov.visible)
        for _ in range(4):
            control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2, 'phase': 'fight'}, now=self.t['wall'] + 0.3)
            self.go(0.6)
            self.assertFalse(self.f.ov.visible)
        t = self.t['wall'] + 0.3
        self.assertTrue(control.arena_active(now=t - 0.5))                     # read a moment before the write: fresh
        self.assertFalse(control.arena_active(now=t + control.ARENA_FRESH_S + 1))   # stale: the arena stopped beating
        self.assertFalse(control.arena_active(now=t - 60))                    # far in the future: a bad clock, not trusted

    def test_menu_has_match_winners_and_arena_entries(self):
        self.f.setup()
        self.go(0.5)
        self.f.ov.menu_choice = L.WIN_RANDOM                       # "Who wins" > "Coin flip"
        self.f.st['menu'] = True
        self.go(0.2)
        labels = L.labels_of(self.f.ov.items)
        self.assertIn('Who wins', labels)
        self.assertTrue(L.find_item(self.f.ov.items, 'Healthier program usually wins')[2]['checked'])
        self.assertIn('Arena mode', labels)                         # no "..." on a toggle
        self.assertIn('Start a match now (best of 3)', labels)
        self.assertEqual(control.winners(), 'random')
        self.go(0.6)
        self.assertEqual(self.f.brain.winners, 'random')
        self.f.ov.menu_choice = 6
        self.f.st['menu'] = True
        self.go(0.6)
        self.assertEqual(self.f.brain.demo['kind'], 'match')
        started = []
        self.shell.monitors = lambda: [{'index': 1, 'rect': (0, 0, 1, 1), 'work': (0, 0, 1, 1), 'primary': True},
                                       {'index': 2, 'rect': (0, 0, 1, 1), 'work': (0, 0, 1, 1), 'primary': False}]
        with mock.patch.object(minis, 'start_arena', lambda mon, freeze=False, seconds=None: started.append(mon) or ('ok', 0)):
            self.f.ov.menu_choice = 8
            self.f.st['menu'] = True
            self.go(0.2)
        self.assertEqual(started, [2])

    def test_menu_toggles_rival_mode_and_the_brain_follows(self):
        self.f.setup()
        self.go(0.6)
        self.assertTrue(self.f.brain.rival)                                        # config default: on
        self.f.ov.menu_choice = 9
        self.f.st['menu'] = True
        self.go(0.2)
        self.assertTrue(L.find_item(self.f.ov.items, 'Rival mode')[2]['checked'])
        self.assertFalse(control.rival_on(default=True))
        self.go(0.6)
        self.assertFalse(self.f.brain.rival)
        self.f.ov.menu_choice = 9
        self.f.st['menu'] = True
        self.go(0.2)
        self.assertFalse(L.find_item(self.f.ov.items, 'Rival mode')[2]['checked'])
        self.go(0.6)
        self.assertTrue(self.f.brain.rival)

    def test_sparring_bot_slot_shows_asleep_with_no_numbers(self):
        self.f.detector_for = None                                                 # the real detector_for: a NullDetector for the bot
        from minis_core import sources
        self.f.detector_for = sources.detector_for
        self.assign(a=dict(director.SPARRING_ASSIGN))
        self.f.setup()
        self.go(2.5)
        self.assertEqual(self.f.display_name(), 'Sparring bot')
        self.assertEqual((self.f.snap.state, self.f.snap.ctx_pct, self.f.snap.plan_pct), ('sleeping', None, None))
        self.assertTrue(self.f.ov.visible and self.f.pov.visible)
        self.assertTrue(self.f.brain.view(self.t['mono'])['dim'])

    def test_arena_cli_requires_a_monitor_and_stop_asks_first(self):
        shell = minis.plat.shell()                                           # the backend minis.main uses on this OS
        one = [{'index': 1, 'rect': (0, 0, 1, 1), 'work': (0, 0, 1, 1), 'primary': True}]
        two = one + [{'index': 2, 'rect': (1, 0, 2, 1), 'work': (1, 0, 2, 1), 'primary': False}]
        if minis.plat.is_mac():                                              # macOS: a single display hosts the arena
            picked = []
            with mock.patch.object(shell, 'monitors', lambda: one), \
                    mock.patch.object(minis, 'start_arena', lambda mon, *a, **k: picked.append(mon) or ('ok', 0)), redirect_stdout(io.StringIO()):
                self.assertEqual(minis.main(['arena']), 0)
            self.assertEqual(picked, [1])
        else:
            with mock.patch.object(shell, 'monitors', lambda: one), redirect_stdout(io.StringIO()) as out:
                rc = minis.main(['arena'])
            self.assertEqual(rc, 2)
            self.assertIn('no default monitor', out.getvalue())
        started = []
        with mock.patch.object(shell, 'monitors', lambda: two), \
                mock.patch.object(minis, 'start_arena', lambda mon, *a, **k: started.append(mon) or ('ok', 0)), redirect_stdout(io.StringIO()):
            self.assertEqual(minis.main(['arena']), 0)
        self.assertEqual(started, [2])                                       # the same pick as the Arena button
        with mock.patch.object(shell, 'monitors', lambda: [{'index': 1, 'rect': (0, 0, 1, 1), 'work': (0, 0, 1, 1), 'primary': True}]), \
                redirect_stdout(io.StringIO()) as out:
            rc = minis.main(['arena', '--monitor', '7'])
        self.assertEqual(rc, 2)
        self.assertIn('does not exist', out.getvalue())
        with mock.patch.object(minis, 'proc_state', lambda role: ('stopped', None)):
            msg, rc = minis.stop_arena()
        self.assertEqual((msg, rc), ('arena: not running', 0))
        self.assertFalse(control.arena_active())
        with mock.patch.object(minis, 'proc_state', lambda role: ('running', 4242)), mock.patch.object(minis, 'cmd_stop', lambda roles=None: 0):
            msg, rc = minis.stop_arena(wait_s=0.3)
        self.assertEqual(msg, 'arena: force-stopped')
        self.assertTrue(control.arena_stop_requested(0))

    def test_drag_with_capture_loss_ends_the_drag(self):
        self.f.setup()
        self.go(0.5)
        b, ov = self.f.brain, self.f.ov
        mx = int(b.x - ov.x / ov.scale)
        self.f.on_event('down', mx, 30)
        self.assertTrue(self.f.st['drag'])
        self.f.on_event('move', mx + 40, 30)
        self.assertAlmostEqual(b.x, mx + 40 + ov.x / ov.scale, delta=1)
        self.f.on_event('up', -1, -1)
        self.assertFalse(self.f.st['drag'])


if __name__ == '__main__':
    unittest.main()
