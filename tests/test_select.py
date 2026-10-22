"""V6 fighter select, scoreboard UX and reliability: lineup + skins (control, director, CLI, menu, select screen),
records per program (with the V5 migration), the result line, hide/show, flash effects, arena capture guards, the
non-blocking arena stop, the director watchdog, argv identity and the config guards.  Hermetic: helpers.Isolated gives
every test its own data dir, MINIS_TESTING refuses every real launch, and windows are FakeOverlay objects."""
import io, json, sys, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG, ROOT, Isolated  # noqa: E402
import minis  # noqa: E402
from minis_core import control, director as D, lineup as L, records, scoreboard as SB, select as S, sources  # noqa: E402
from minis_core.sources import Activity  # noqa: E402
from minis_platform.menus import menu_entries  # noqa: E402  (the same normalisation as minis_win.shell's)
from test_minis import FakeOverlay, FakeShell, FakeDetector  # noqa: E402

HOUR = 3600.0
PY = r'C:\Python314\pythonw.exe'
SCRIPT = str(ROOT / 'minis.py')


def act(sid, state='idle', last=0.0, ch=None):
    return Activity(sid, sid.title(), ch or sid, state, last_active=last)


def make(**over):
    return D.Director(dict(CFG, **over), resolve=lambda c: c)


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = minis.main(argv)
    return rc, out.getvalue()


# ================================================================== control.json lineup
class Lineup(Isolated):
    def test_defaults_and_garbage_read_as_auto(self):
        self.assertEqual(control.lineup(), {'a': 'auto', 'b': 'auto', 'skins': {}})
        (self.data / 'control.json').write_text(json.dumps({'lineup': {'a': 5, 'b': 'codex', 'skins': ['x']}}))
        self.assertEqual(control.lineup(), {'a': 'auto', 'b': 'codex', 'skins': {}})

    def test_pick_moves_a_program_and_never_doubles_it(self):
        control.set_pick('a', 'codex')
        control.set_pick('b', 'codex')                         # taking the other side's program moves it here
        self.assertEqual((control.lineup()['a'], control.lineup()['b']), ('auto', 'codex'))
        (self.data / 'control.json').write_text(json.dumps({'lineup': {'a': 'grok', 'b': 'grok'}}))
        self.assertEqual(control.lineup()['b'], 'auto')        # a hand-edited duplicate: b falls back

    def test_skins_default_auto_and_reset(self):
        control.set_skin('grok', 'claude')
        control.set_pick('a', 'grok')
        self.assertEqual(control.lineup()['skins'], {'grok': 'claude'})
        control.reset_lineup(skins=False)                      # `fighters auto` keeps looks
        self.assertEqual(control.lineup(), {'a': 'auto', 'b': 'auto', 'skins': {'grok': 'claude'}})
        control.set_skin('grok', 'default')
        self.assertEqual(control.lineup()['skins'], {})
        control.set_skin('aider', 'codex')
        control.reset_lineup(skins=True)                       # `fighters reset` forgets them
        self.assertEqual(control.lineup()['skins'], {})

    def test_hide_show_and_timed_hide(self):
        self.assertIsNone(control.hidden_left('a'))
        control.hide('a', None, now=100.0)
        self.assertEqual(control.hidden_left('a', now=1e12), float('inf'))
        control.hide('b', 3600, now=100.0)
        self.assertAlmostEqual(control.hidden_left('b', now=200.0), 3500.0)
        self.assertIsNone(control.hidden_left('b', now=3800.0))           # expired
        control.show('a')
        self.assertIsNone(control.hidden_left('a', now=200.0))
        control.show()
        self.assertIsNone(control.hidden_left('b', now=200.0))

    def test_picker_request_carries_slots(self):
        control.request_picker(('b',), now=50.0)
        self.assertEqual(control.picker_request(now=51.0)['slots'], ['b'])
        self.assertIsNone(control.picker_request(now=60.0))


# ================================================================== director honours the lineup
class DirectorLineup(unittest.TestCase):
    def test_picked_program_keeps_its_slot_asleep_when_not_detected_even_past_dormant_hours(self):
        d = make(sparring_bot=False)
        now = 10 * 24 * HOUR
        got = d.step([act('claude', 'working', now)], now, {'a': 'auto', 'b': 'codex'})
        self.assertEqual(got, {'a': 'claude', 'b': 'codex'})
        a = d.assignment(now)
        self.assertTrue(a['b']['dormant'] and a['b']['picked'])
        self.assertEqual((a['b']['program'], a['b']['character']), ('Codex', 'codex'))      # from the static table
        got = d.step([act('claude', 'working', now + 1), act('codex', 'working', now + 1)], now + 1, {'a': 'auto', 'b': 'codex'})
        self.assertNotIn('dormant', d.assignment(now + 1)['b'])                              # detected: awake

    def test_auto_slot_never_takes_a_picked_program_and_an_idle_pick_is_never_displaced(self):
        d = make()
        lu = {'a': 'cursor', 'b': 'auto'}
        got = d.step([act('claude', 'working', 1000), act('cursor', 'idle', 10)], 1000, lu)
        self.assertEqual(got, {'a': 'cursor', 'b': 'claude'})
        got = d.step([act('claude', 'idle', 1000), act('cursor', 'idle', 10), act('gemini', 'working', 5000)], 5000, lu)
        self.assertEqual(got['a'], 'cursor')                    # the rules would have replaced the idle cursor

    def test_pinning_the_other_sides_program_moves_it(self):
        d = make()
        d.step([act('claude', 'working', 100), act('codex', 'working', 100)], 100)
        self.assertEqual(d.slots, {'a': 'claude', 'b': 'codex'})
        got = d.step([act('claude', 'working', 101), act('codex', 'working', 101)], 101, {'a': 'codex', 'b': 'auto'})
        self.assertEqual(got, {'a': 'codex', 'b': 'claude'})

    def test_bot_can_be_picked_and_auto_back_restores_the_rules(self):
        d = make()
        got = d.step([act('claude', 'working', 100), act('codex', 'working', 100)], 100, {'a': 'auto', 'b': 'sparring'})
        self.assertEqual(got['b'], 'sparring')
        self.assertTrue(d.assignment(100)['b']['bot'])
        got = d.step([act('claude', 'working', 101), act('codex', 'working', 101)], 101, {'a': 'auto', 'b': 'auto'})
        self.assertEqual(set(got.values()), {'claude', 'codex'})

    def test_skins_change_the_character_and_flag_it(self):
        d = make()
        d.step([act('grok', 'working', 100, ch='generic'), act('claude', 'idle', 90)], 100, {'a': 'grok', 'b': 'auto', 'skins': {'grok': 'gemini'}})
        a = d.assignment(100)
        self.assertEqual((a['a']['source'], a['a']['character'], a['a'].get('skin')), ('grok', 'gemini', True))
        self.assertNotIn('skin', a['b'])
        d.step([act('grok', 'working', 101, ch='generic')], 101, {'a': 'grok', 'skins': {'grok': 'generic'}})
        self.assertNotIn('skin', d.assignment(101)['a'])       # a skin equal to the own character is no skin

    def test_programs_list_states(self):
        d = make()
        d.step([act('claude', 'working', 1000), act('codex', 'idle', 500)], 1000)
        d.step([act('claude', 'working', 2000)], 2000)                                    # codex vanished: remembered
        rows = {r['source']: r for r in d.assignment(2000)['programs']}
        self.assertEqual(rows['claude']['state'], 'working')
        self.assertEqual(rows['codex']['state'], 'asleep')
        self.assertEqual(rows['grok']['state'], 'not seen')
        self.assertEqual((rows['sparring']['state'], rows['sparring']['label']), ('bot', 'Bot'))
        self.assertEqual(rows['claude']['label'], 'Claude')


class RunnerReadsLineup(Isolated):
    def test_runner_applies_control_lineup(self):
        class Src:
            def poll(self, now):
                return [Activity('claude', 'Claude Code', 'claude', 'working', last_active=now)]
        control.set_pick('b', 'grok')
        control.set_skin('grok', 'codex')
        r = D.Runner(dict(CFG), Src())
        data, _ = r.step(1000.0)
        self.assertEqual((data['b']['source'], data['b']['character'], data['b'].get('dormant')), ('grok', 'codex', True))
        self.assertTrue(json.loads((self.data / 'assign.json').read_text())['programs'])


# ================================================================== CLI
class Cli(Isolated):
    def test_fighters_lists_programs_characters_and_lineup(self):
        rc, out = run(['fighters'])
        self.assertEqual(rc, 0)
        for w in ('claude', 'grok', 'characters:', 'lineup: a = auto, b = auto', 'Agent'):
            self.assertIn(w, out)

    def test_set_pin_auto_reset_and_aliases(self):
        self.assertEqual(run(['fighters', 'pin', 'a', 'Claude Code'])[0], 0)
        self.assertEqual(control.lineup()['a'], 'claude')
        self.assertEqual(run(['fighters', 'set', 'b', 'grok'])[0], 0)                  # a program: pinned
        self.assertEqual(control.lineup()['b'], 'grok')
        rc, out = run(['fighters', 'set', 'b', 'agent'])                                # a character: that side's look
        self.assertEqual(rc, 0, out)
        self.assertEqual(control.lineup()['skins'], {'grok': 'generic'})
        self.assertEqual(run(['skin', 'grok', 'LM Studio'])[0], 0)
        self.assertEqual(control.lineup()['skins'], {'grok': 'lmstudio'})
        self.assertEqual(run(['pick', 'a', 'auto'])[0], 0)
        self.assertEqual(control.lineup()['a'], 'auto')
        self.assertEqual(run(['fighters', 'auto'])[0], 0)
        self.assertEqual(control.lineup(), {'a': 'auto', 'b': 'auto', 'skins': {'grok': 'lmstudio'}})
        self.assertEqual(run(['fighters', 'reset'])[0], 0)
        self.assertEqual(control.lineup()['skins'], {})

    def test_unknown_names_are_refused_with_the_valid_ones(self):
        rc, out = run(['pick', 'a', 'notepad'])
        self.assertEqual(rc, 2)
        self.assertIn('known:', out)
        rc, out = run(['skin', 'grok', 'batman'])
        self.assertEqual(rc, 2)
        self.assertIn('have:', out)
        rc, out = run(['fighters', 'set', 'a', 'agent'])                                # nothing on a to dress up
        self.assertEqual(rc, 2)
        self.assertEqual(run(['fighters', 'set', 'c', 'grok'])[0], 2)

    def test_show_and_flash(self):
        control.hide('b', None)
        self.assertEqual(run(['show', 'b'])[0], 0)
        self.assertIsNone(control.hidden_left('b'))
        self.assertEqual(run(['flash', 'off'])[0], 0)
        self.assertFalse(control.flashes_on())
        self.assertEqual(run(['flash', 'on'])[0], 0)
        self.assertTrue(control.flashes_on())

    def test_start_waits_and_says_what_is_on_screen(self):
        launched, slept = [], []
        state = {'director': 'stopped', 'a': 'stopped', 'b': 'stopped'}

        def fake_launch(role):
            launched.append(role)
            state[role] = 'running'
            return True
        D.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                        'b': dict(D.SPARRING_ASSIGN), 'ts': 1.0})
        with mock.patch.object(minis, 'launch_role', fake_launch), mock.patch.object(minis, 'proc_state', lambda r: (state.get(r, 'stopped'), None)), \
                mock.patch.object(minis.plat.shell(), 'taskbar_rect', lambda: (0, 1392, 2560, 1440, 3)), mock.patch.object(minis.plat.shell(), 'taskbar_autohide', lambda: False), \
                redirect_stdout(io.StringIO()) as out:
            rc = minis.cmd_start(wait_s=3.0, sleep=slept.append)
        self.assertEqual((rc, launched, slept), (0, ['director', 'a', 'b'], [3.0]))
        self.assertIn('on screen: a: Claude Code, b: Sparring bot asleep', out.getvalue())

    def test_on_screen_explains_why_nothing_shows(self):
        with mock.patch.object(minis, 'proc_state', lambda r: ('stopped', None)):
            line, ok = minis.on_screen(taskbar=((0, 0, 100, 48, 1), False))
        self.assertFalse(ok)
        self.assertIn('the director is not running', line)
        self.assertIn('taskbar is not at the bottom', line)
        self.assertIn('a: (not running)', line)

    def test_launch_role_is_refused_under_tests(self):
        with mock.patch.object(minis.subprocess, 'Popen', lambda *a, **k: self.fail('launched a real process')):
            self.assertFalse(minis.launch_role('a'))
            self.assertFalse(minis.quit_all())

    def test_status_first_line_is_plain_english_with_rival_mode(self):
        with mock.patch.object(minis, 'proc_state', lambda r: ('stopped', None)):
            self.assertEqual(minis.status_line(), 'minis is not running (start it with `python minis.py start`). Rival mode on.')
        D.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                        'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex', 'dormant': True, 'picked': True}, 'ts': 1.0})
        control.set_rival(False)
        with mock.patch.object(minis, 'proc_state', lambda r: ('running', 1)):
            line = minis.status_line()
        self.assertEqual(line, 'minis is running: Claude Code on the left vs Codex on the right (asleep, picked). Rival mode off.')


# ================================================================== records per program
class Records(Isolated):
    def test_v5_file_migrates_unique_characters_and_keeps_generic_apart(self):
        (self.data / 'record.json').write_text(json.dumps({'characters': {'claude': {'w': 32, 'l': 39}, 'generic': {'w': 5, 'l': 1}}, 'matches': 77}))
        rec = records.read()
        self.assertEqual(records.for_program(rec, 'claude'), (32, 39))
        self.assertEqual(records.for_program(rec, 'grok'), (0, 0))              # the shared line is nobody's
        records.record('grok', 'claude', now=1000.0, score=(2, 1))
        raw = json.loads((self.data / 'record.json').read_text())
        self.assertEqual(raw['programs'], {'claude': {'w': 32, 'l': 40}, 'grok': {'w': 1, 'l': 0}})
        self.assertEqual(raw['characters']['generic'], {'w': 5, 'l': 1})        # old data kept, untouched
        self.assertEqual((raw['matches'], raw['last']['score']), (78, [2, 1]))
        self.assertNotIn('migrated', raw)

    def test_last_result_is_fresh_only(self):
        records.record('codex', 'claude', now=1000.0, score=(2, 0))
        rec = records.read()
        self.assertEqual(records.last_result(rec, 1004.0)['winner'], 'codex')
        self.assertIsNone(records.last_result(rec, 1020.0))


# ================================================================== scoreboard UX
class Board(unittest.TestCase):
    base = dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (3, 1), 'b': (1, 3)}, mode='taskbar', arena=False, paused=False,
                hp=None, wins={})

    def test_result_line_after_a_match_then_plain(self):
        assign = {'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': {'source': 'grok', 'character': 'generic', 'program': 'Grok'}}
        rec = {'programs': {'claude': {'w': 4, 'l': 1}, 'grok': {'w': 1, 'l': 4}}, 'last': {'winner': 'claude', 'loser': 'grok', 'score': [2, 1], 'ts': 1000.0}}
        st = SB.Model.state(assign, {}, rec, False, False, 'decided', now=1003.0)
        self.assertEqual(st['result'], 'CLAUDE WINS 2-1')
        self.assertEqual((st['names'], st['records']), ({'a': 'Claude', 'b': 'Grok'}, {'a': (4, 1), 'b': (1, 4)}))
        self.assertIsNone(SB.Model.state(assign, {}, rec, False, False, 'decided', now=1030.0)['result'])
        busy = SB.Model.state(assign, {'a': {'hp': 50}}, rec, False, False, 'decided', now=1003.0)
        self.assertIsNone(busy['result'])                                       # HP bars win while a bout plays
        plain, res = SB.render(self.base), SB.render(dict(self.base, result='CLAUDE WINS 2-1'))
        self.assertNotEqual(plain.tobytes(), res.tobytes())
        self.assertTrue(any(res.getpixel((x, 17))[:3] == SB.GOLD for x in range(SB.W)))

    def test_readable_hp_bars_and_hidden_text(self):
        bout = SB.render(dict(self.base, hp={'a': 64, 'b': 20}, wins={'a': 1, 'b': 0}))
        tall = sum(1 for y in range(SB.H) if bout.getpixel((20, y))[:3] == SB.GREEN)
        self.assertGreaterEqual(tall, 6)                                        # not a sliver: >= 6 px tall
        self.assertEqual(bout.getpixel((SB.W - 8, 18))[:3], SB.RED)
        self.assertEqual(SB.hidden_text({'b': 3120.0}), 'B hidden 52m')
        self.assertEqual(SB.hidden_text({'a': float('inf')}), 'A hidden')
        self.assertEqual(SB.hidden_text({'a': 10.0, 'b': 4000.0}), 'both hidden 1m')
        self.assertNotEqual(SB.render(dict(self.base, hidden={'b': 3120.0})).tobytes(), SB.render(self.base).tobytes())

    def test_short_labels(self):
        self.assertEqual([sources.short_label(s) for s in ('claude', 'codex', 'sparring', 'grok', 'lmstudio')],
                         ['Claude', 'Codex', 'Bot', 'Grok', 'LM Studio'])


class BoardHosted(Isolated):
    def setUp(self):
        super().setUp()
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.shell = FakeShell()
        self.board = minis.Scoreboard(dict(CFG), self.shell, wall=lambda: self.t['wall'], mono=lambda: self.t['mono'])
        self.board.setup()

    def go(self, secs, dt=0.05):
        for _ in range(int(secs / dt)):
            self.t['mono'] += dt
            self.t['wall'] += dt
            self.board.step()

    def test_name_click_opens_select_and_confirming_writes_the_lineup(self):
        D.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': None, 'ts': self.t['wall'],
                        'programs': [dict(source='claude', program='Claude Code', label='Claude', character='claude', state='working'),
                                     dict(source='grok', program='Grok', label='Grok', character='generic', state='idle'),
                                     dict(source='sparring', program='Sparring bot', label='Bot', character='generic', state='bot')]})
        self.go(0.3)
        b = self.board
        b.on_event('down', 180, 5)
        b.on_event('up', 180, 5)                                                # name_b
        self.assertIsNotNone(b.select)
        ov = b.select.ov
        self.assertTrue(ov.activatable and ov.focused)                          # the popup, and only it, takes focus
        self.assertLess(ov.y + ov.h * ov.scale, 1392)                           # above the taskbar
        m = b.select.model
        self.assertEqual(m.players, ['b'])
        grok = next(i for i, r in enumerate(m.rows) if r['source'] == 'grok')
        m.cur['b'] = grok
        ov.on_key(S.VK['enter'])
        ov.on_key(S.VK['enter'])                                                # keep its look
        self.go(0.1)
        self.assertEqual(control.lineup()['b'], 'grok')                         # written at the VS card
        self.go(1.2)
        self.assertIsNone(b.select)
        self.assertTrue(ov.closed)

    def test_menu_request_opens_select_and_blur_cancels(self):
        control.request_picker(('a', 'b'), now=self.t['wall'] + 0.1)
        self.go(0.4)
        self.assertIsNotNone(self.board.select)
        self.assertEqual(self.board.select.model.players, ['a', 'b'])
        self.board.select.ov.on_blur()
        self.go(0.1)
        self.assertIsNone(self.board.select)
        self.assertEqual(control.lineup(), {'a': 'auto', 'b': 'auto', 'skins': {}})

    def test_show_link_brings_a_hidden_fighter_back(self):
        control.hide('b', 3600, now=self.t['wall'])
        self.go(0.4)
        self.assertEqual(self.board.state['hidden'].keys(), {'b'})
        self.board.on_event('down', 165, 17)
        self.board.on_event('up', 165, 17)
        self.assertIsNone(control.hidden_left('b', now=self.t['wall']))

    def test_arena_button_stop_never_blocks(self):
        control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2}, now=self.t['wall'])
        stopped = []
        with mock.patch.object(control, 'arena_active', lambda *a, **k: True), \
                mock.patch.object(minis, 'proc_state', lambda r: ('running', 7)), \
                mock.patch.object(minis, 'cmd_stop', lambda roles=None: stopped.append(roles) or 0), \
                mock.patch.object(minis.time, 'sleep', lambda s: self.fail('the UI loop slept')):
            self.board.act('arena')
            self.assertEqual(stopped, [])
            self.assertTrue(control.arena_stop_requested(0))
            self.go(2.0)
            self.assertEqual(stopped, [])
            self.go(2.5)
        self.assertEqual(stopped, [(minis.ARENA,)])                             # force-stopped from the loop after 4 s


# ================================================================== the select screen model
def chars(n=7):
    base = L.characters()
    return [dict(id=f'c{i}', display=f'C{i}') for i in range(n)] if n > len(base) else base


ROWS = [dict(source='claude', program='Claude Code', label='Claude', character='claude', state='working'),
        dict(source='codex', program='Codex', label='Codex', character='codex', state='asleep'),
        dict(source='sparring', program='Sparring bot', label='Bot', character='generic', state='bot')]


class SelectModel(unittest.TestCase):
    def model(self, slots=('a', 'b'), lu=None, ch=None):
        return S.Model(slots, ROWS, lu or {'a': 'auto', 'b': 'auto', 'skins': {}}, ch or L.characters(), portrait=lambda c, t, w, h: None)

    def test_keyboard_flow_p1_then_p2_with_a_look(self):
        m = self.model()
        self.assertEqual((m.cur['a'], m.slot, m.stage), (0, 'a', 'who'))         # starts on AUTO (lineup auto)
        m.key(S.VK['right'], 0)
        m.key(S.VK['enter'], 0)                                                 # Claude -> look stage, own look highlighted
        self.assertEqual((m.stage, m.chars[m.look]['id']), ('look', 'claude'))
        codex = next(i for i, c in enumerate(m.chars) if c['id'] == 'codex')
        m.look = codex
        m.key(S.VK['enter'], 0)
        self.assertEqual((m.slot, m.stage), ('b', 'who'))
        m.key(S.VK['enter'], 0)                                                 # P2 takes AUTO: no look stage
        self.assertEqual(m.phase, 'vs')
        self.assertEqual(m.result(), ({'a': 'claude', 'b': 'auto'}, {'claude': 'codex'}))
        m.tick(m.vs_until + 0.01)
        self.assertEqual(m.phase, 'done')

    def test_the_same_program_twice_is_refused(self):
        m = self.model()
        m.cur['a'] = 1
        m.key(S.VK['enter'], 0)
        m.key(S.VK['enter'], 0)
        m.cur['b'] = 1
        m.key(S.VK['enter'], 0)
        self.assertEqual((m.stage, m.phase), ('who', 'select'))
        self.assertIn("1P's fighter", m.msg)

    def test_choosing_the_own_look_clears_a_skin_and_back_and_cancel(self):
        m = self.model(lu={'a': 'codex', 'b': 'auto', 'skins': {'codex': 'claude'}})
        self.assertEqual(m.rows[m.cur['a']]['source'], 'codex')                 # starts on the current pick
        m.key(S.VK['enter'], 0)
        self.assertEqual(m.chars[m.look]['id'], 'claude')                       # its current look
        m.key(S.VK['back'], 0)
        self.assertEqual(m.stage, 'who')
        m.key(S.VK['enter'], 0)
        m.look = next(i for i, c in enumerate(m.chars) if c['id'] == 'codex')
        m.key(S.VK['enter'], 0)
        self.assertEqual(m.skins, {})
        m.key(S.VK['esc'], 0)
        self.assertEqual(m.phase, 'cancel')

    def test_mouse_click_and_wheel(self):
        m = self.model(slots=('b',))
        x, y = m.who_rects[1]
        m.click(x + 3, y + 3, 0)                                                # Claude
        self.assertEqual(m.stage, 'look')
        before = m.look
        m.wheel(-120, 0)
        self.assertEqual(m.look, (before + 1) % len(m.chars))
        lx, ly = m.look_rects[0]
        m.click(lx + 2, ly + 2, 0)
        self.assertEqual(m.phase, 'vs')
        self.assertEqual(m.result()[0], {'b': 'claude'})

    def test_thirteen_plus_characters_grid_and_render_size(self):
        ch = [dict(id=f'c{i}', display=f'Char {i}') for i in range(14)]
        m = self.model(ch=ch)
        self.assertEqual(len(m.look_rects), 14)
        rows = {y for _, y in m.look_rects}
        self.assertEqual(len(rows), 2)                                          # 7 columns, two rows
        self.assertTrue(all(m.hit(x + 1, y + 1) == ('look', i) for i, (x, y) in enumerate(m.look_rects)))
        im = m.render(0.0)
        self.assertEqual(im.size, (m.W, m.H))
        m.stage = 'look'
        m.key(S.VK['down'], 0)
        self.assertEqual(m.look, 7)
        m.key(S.VK['up'], 0)
        m.key(S.VK['up'], 0)
        self.assertEqual(m.stage, 'who')                                        # up out of the grid

    def test_offer_hides_never_seen_programs_unless_picked(self):
        rows = ROWS + [dict(source='grok', program='Grok', label='Grok', character='generic', state='not seen')]
        self.assertNotIn('grok', [r['source'] for r in S.offer(rows, {'a': 'auto', 'b': 'auto'})])
        self.assertIn('grok', [r['source'] for r in S.offer(rows, {'a': 'grok', 'b': 'auto'})])
        self.assertEqual(S.offer(rows, {})[0]['source'], 'claude')              # working first

    def test_portraits_come_from_the_sheets(self):
        from minis_core.atlas import Library
        p = S.Portraits(Library())
        im = p('claude', 0.0, 46, 44)
        self.assertEqual(im.size, (46, 44))
        self.assertIsNotNone(im.getchannel('A').getbbox())
        self.assertEqual(p('claude', 0.0, 46, 96).size, (46, 96))


# ================================================================== the right-click menu
class Menu(Isolated):
    def setUp(self):
        super().setUp()
        self.t = {'mono': 100.0, 'wall': 1_800_000_000.0}
        self.f = minis.Fighter('a', dict(CFG), FakeShell(), mono=lambda: self.t['mono'], wall=lambda: self.t['wall'],
                               detector_for=lambda src, cfg: FakeDetector(src))

    def go(self, secs, dt=0.05):
        for _ in range(int(secs / dt)):
            self.t['mono'] += dt
            self.t['wall'] += dt
            if self.f.step() is None:
                return None
        return 0

    def choose(self, label):
        items, _ = self.items()
        it = L.find_item(items, label)
        self.assertIsNotNone(it, (label, L.labels_of(items)))
        self.f.ov.menu_choice = it[0]
        self.f.st['menu'] = True
        self.go(0.1)
        return it

    def items(self):
        self.f.ov.menu_choice = 0
        self.f.st['menu'] = True
        self.go(0.1)
        return self.f.ov.items, None

    def test_menu_structure_has_submenus_checks_and_greyed_programs(self):
        D.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': None, 'ts': 1.0,
                        'programs': [dict(source='claude', state='working'), dict(source='grok', state='not seen')]})
        self.f.setup()
        self.go(0.3)
        items, _ = self.items()
        entries = {e[1]: e for e in menu_entries(items) if e[0] == 'sub'}
        self.assertIn('Fighter (left side)', entries)
        self.assertIn('Look (Claude)', entries)
        auto = L.find_item(items, 'Auto')
        self.assertTrue(auto[2]['checked'] and auto[2]['radio'])
        self.assertTrue(L.find_item(items, 'Grok')[2]['disabled'])
        self.assertTrue(L.find_item(items, 'HUD plates')[2]['checked'])
        self.assertIn(None, items)                                               # separators
        for gone in ('Quit this mini', 'Winners:', 'Arena mode...'):
            self.assertFalse(any(str(x).startswith(gone) for x in L.labels_of(items)))
        looks = [it for it in entries['Look (Claude)'][2] if it]
        self.assertEqual(len(looks) - 1, len(L.characters()))                   # Default + every character on disk

    def test_pick_skin_hide_show_flash_and_select_from_the_menu(self):
        D.write_assign({'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'}, 'b': None, 'ts': 1.0})
        self.f.setup()
        self.go(0.3)
        self.choose('Codex')
        self.assertEqual(control.lineup()['a'], 'codex')
        items, _ = self.items()
        look = next(sub for sub in items if sub and isinstance(sub[1], list) and str(sub[0]).startswith('Look'))[1]
        self.f.ov.menu_choice = next(it[0] for it in look if it and it[1] == 'Gemini')      # Look > Gemini
        self.f.st['menu'] = True
        self.go(0.1)
        self.assertEqual(control.lineup()['skins'], {'claude': 'gemini'})
        self.choose('Hide this fighter')
        self.go(0.6)
        self.assertFalse(self.f.ov.visible)
        control.show('a')
        self.go(2.5)
        self.assertTrue(self.f.ov.visible)
        self.choose('Hide for 1 hour')
        self.assertAlmostEqual(control.hidden_left('a', now=self.t['wall']), 3600, delta=1)
        self.choose('Flash effects')
        self.assertFalse(control.flashes_on())
        self.go(0.6)
        if hasattr(self.f.brain, 'flashes'):
            self.assertIs(self.f.brain.flashes, False)
        self.choose('Select fighters...')
        self.assertEqual(control.picker_request(now=self.t['wall'])['slots'], ['a', 'b'])

    def test_a_skinned_plate_names_the_program(self):
        D.write_assign({'a': {'source': 'grok', 'character': 'claude', 'program': 'Grok', 'skin': True}, 'b': None, 'ts': 1.0})
        self.f.setup()
        self.go(0.3)
        self.assertEqual(self.f.display_name(), 'Grok')

    def test_brain_results_are_recorded_per_program_even_for_the_same_character(self):
        D.write_assign({'a': {'source': 'aider', 'character': 'generic', 'program': 'aider'},
                        'b': {'source': 'grok', 'character': 'generic', 'program': 'Grok'}, 'ts': 1.0})
        self.f.setup()
        self.go(0.3)
        self.f.brain.round = {'n': 3, 'wins': {'a': 1, 'b': 2}}
        self.f._record('generic', 'generic')
        rec = records.read()
        self.assertEqual((records.for_program(rec, 'grok'), records.for_program(rec, 'aider')), ((1, 0), (0, 1)))
        self.assertEqual(rec['last']['score'], [2, 1])


class FlashSwitch(unittest.TestCase):
    def test_shadowing_the_effect_player_removes_every_flash_and_restores(self):
        from minis_core import effects, fx as fxmod
        p = effects.EffectPlayer(fxmod.default())
        p.flash_at(1.0, 0.8, 0.5)
        self.assertGreater(p.flash(1.1), 0)
        minis.set_flash_effects(p, False)
        self.assertEqual(p.flash(1.1), 0.0)
        minis.set_flash_effects(p, True)
        self.assertGreater(p.flash(1.1), 0)


# ================================================================== reliability
class Reliability(Isolated):
    def test_argv_must_be_absolute(self):
        self.assertTrue(minis.argv_is_ours([PY, SCRIPT, 'run', 'a'], 'a'))
        self.assertFalse(minis.argv_is_ours([PY, 'minis.py', 'run', 'a'], 'a', root=Path('.').resolve()))
        self.assertFalse(minis.argv_is_ours([PY, r'.\minis.py', 'director'], 'director'))

    def test_capture_refused_during_freeze_and_outside_qa_or_data(self):
        control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2, 'freeze': True})
        if minis.plat.is_mac():                                         # macOS never captures a window (no Screen Recording)
            with mock.patch.object(minis.plat.shell(), 'find_own_window', lambda *a: self.fail('looked for a window')):
                rc, out = run(['arena', 'capture', str(ROOT / 'qa' / 'x.png')])
            self.assertEqual(rc, 2)
            self.assertIn('Windows only', out)
            return
        with mock.patch.object(minis.plat.shell(), 'find_own_window', lambda *a: self.fail('looked for a window')):
            rc, out = run(['arena', 'capture', str(ROOT / 'qa' / 'x.png')])
        self.assertEqual(rc, 2)
        self.assertIn('freeze', out)
        control.write_arena_state({'active': True, 'pid': 1, 'monitor': 2, 'freeze': False})
        with mock.patch.object(minis.plat.shell(), 'find_own_window', lambda *a: self.fail('looked for a window')):
            rc, out = run(['arena', 'capture', r'C:\Windows\Temp\x.png'])
        self.assertEqual(rc, 2)
        self.assertIn('refused', out)
        self.assertTrue(minis.capture_allowed(self.data / 'cap.png'))
        self.assertTrue(minis.capture_allowed(ROOT / 'qa' / 'a' / 'b.png'))
        self.assertFalse(minis.capture_allowed(ROOT / 'qa' / '..' / 'evil.png'))

    def test_watchdog_restarts_only_a_dead_slot_it_saw_running_rate_limited(self):
        st = {'a': 'running', 'b': 'stopped'}
        launched = []
        dog = minis.Watchdog(state=lambda r: st[r], launch=lambda r: launched.append(r) or True, every_s=1, min_gap_s=30, max_restarts=2,
                             window_s=600)
        dog.check(0)
        self.assertEqual(launched, [])                                          # b never ran under us: left alone
        st['a'] = 'stopped'
        dog.check(2)
        self.assertEqual(launched, ['a'])
        dog.check(4)
        self.assertEqual(launched, ['a'])                                       # min gap
        dog.check(40)
        dog.check(80)
        self.assertEqual(launched, ['a', 'a'])                                  # at most 2 in the window
        st['a'] = 'foreign'
        dog2 = minis.Watchdog(state=lambda r: 'running' if r == 'a' else 'stopped', launch=lambda r: launched.append(r))
        dog2.check(0)
        dog2.state = lambda r: 'foreign'
        dog2.check(10)
        self.assertEqual(launched, ['a', 'a'])                                  # a reused pid is never "restarted"

    def test_broken_minis_json_is_logged_and_fps_clamped(self):
        bad = self.data / 'minis.json'
        bad.write_text('{"fps_idle": 0,,}')
        log = mock.Mock()
        cfg = minis.load_config(bad, log=log)
        self.assertIn('could not be read', cfg['_config_problem'])
        log.warning.assert_called_once()
        good = self.data / 'ok.json'
        good.write_text(json.dumps({'fps_idle': 0, 'fps_active': 500, 'arena_fps': 'x'}))
        cfg = minis.load_config(good, log=log)
        self.assertEqual((cfg['fps_idle'], cfg['fps_active'], cfg['arena_fps']), (1, 60, 60))     # V9: arena default 60
        self.assertNotIn('_config_problem', cfg)


class ShellMenuSpec(unittest.TestCase):
    def test_menu_entries_normalises_items_separators_and_submenus(self):
        got = menu_entries([(1, 'a'), None, '-', ('Sub', [(2, 'b', {'checked': True})]), (3, 'c', {'disabled': True})])
        self.assertEqual(got, [('item', 1, 'a', {}), ('sep',), ('sep',), ('sub', 'Sub', [(2, 'b', {'checked': True})]),
                               ('item', 3, 'c', {'disabled': True})])


if __name__ == '__main__':
    unittest.main()
