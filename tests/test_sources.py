import json, os, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, CFG, Isolated  # noqa: E402
from minis_core import sources as S  # noqa: E402

CPU = dict(CFG, proc_working_cpu_pct=15, proc_window_s=6)
WIN = 'win32'                                       # FakeInfo tables are Windows process lists (claude.exe ...)


class FakeInfo:
    """A synthetic process table: pid -> dict(ppid, name, path, argv, cpu, create)."""

    def __init__(self):
        self.p = {}
        self.argv_reads = 0

    def add(self, pid, ppid, name, path=None, argv=None, cpu=0.0, create=1):
        self.p[pid] = dict(ppid=ppid, name=name, path=path or ('C:\\x\\' + name), argv=argv or [name], cpu=cpu, create=create)

    def list(self):
        return [(pid, d['ppid'], d['name']) for pid, d in self.p.items()]

    def path(self, pid):
        return self.p[pid]['path'] if pid in self.p else None

    def times(self, pid):
        d = self.p.get(pid)
        return (d['create'], d['cpu']) if d else None

    def argv(self, pid):
        self.argv_reads += 1
        return self.p[pid]['argv'] if pid in self.p else None

    def burn(self, pid, seconds):
        self.p[pid]['cpu'] += seconds


def scan_ids(info, now=100.0):
    return sorted(S.ProcessSource(CPU, S.ProcessScanner(CPU, info, platform=WIN)).poll(now), key=lambda a: a.source_id)


class Matching(unittest.TestCase):
    def test_codex_desktop_app_is_codex_not_chatgpt(self):
        i = FakeInfo()
        i.add(10, 1, 'chatgpt.exe', path=r'C:\Program Files\WindowsApps\OpenAI.Codex_1.2.3_x64__abc\app\ChatGPT.exe')
        i.add(11, 10, 'chatgpt.exe', path=r'C:\Program Files\WindowsApps\OpenAI.Codex_1.2.3_x64__abc\app\ChatGPT.exe')
        sc = S.ProcessScanner(CPU, i, platform=WIN)
        self.assertEqual(S.ProcessSource(CPU, sc).poll(1.0), [])            # no 'chatgpt' fighter, no second codex
        self.assertEqual(sc.claimed, {'codex': 2})

    def test_unknown_programs_never_show(self):
        i = FakeInfo()
        i.add(10, 1, 'chatgpt-helper.exe')                                # not in the table (plain ChatGPT.exe is: growth)
        i.add(11, 1, 'code.exe')                                          # VS Code / Copilot: too ambiguous, skipped
        i.add(12, 1, 'notepad.exe')
        i.add(13, 1, 'node.exe', argv=['node.exe', r'C:\srv\server.js'])
        self.assertEqual(scan_ids(i), [])

    def test_known_programs_by_exe_and_by_command_line(self):
        i = FakeInfo()
        i.add(10, 1, 'cursor.exe')
        i.add(11, 1, 'ollama app.exe')
        i.add(12, 1, 'lm studio.exe')
        i.add(13, 1, 'node.exe', argv=['node.exe', r'C:\Users\u\AppData\Roaming\npm\node_modules\@google\gemini-cli\dist\index.js'])
        i.add(14, 1, 'python.exe', argv=['python.exe', '-m', 'aider', '--model', 'x'])
        i.add(15, 1, 'opencode.exe')
        i.add(16, 1, 'windsurf.exe')
        got = {a.source_id: a.character for a in scan_ids(i)}
        self.assertEqual(got, {'cursor': 'cursor', 'ollama': 'ollama', 'lmstudio': 'lmstudio', 'gemini': 'gemini',
                               'aider': 'generic', 'opencode': 'generic', 'windsurf': 'generic'})
        for a in scan_ids(i):
            self.assertIsNone(a.ctx_pct)
            self.assertIsNone(a.plan_pct)

    def test_command_line_arguments_and_inline_code_do_not_match(self):
        self.assertFalse(S.cmd_matches(['pythonw.exe', r'C:\Users\u\minis\minis.py', 'run', 'claude'], ('claude',)))
        self.assertFalse(S.cmd_matches(['python.exe', '-c', 'import x; "@google/gemini-cli"'], ('gemini', '@google/gemini-cli')))
        self.assertFalse(S.cmd_matches(['node.exe', '-e', 'require("gemini")'], ('gemini',)))
        self.assertFalse(S.cmd_matches(['node.exe', r'C:\notes\gemini.md'], ('gemini',)))
        self.assertTrue(S.cmd_matches(['node.exe', r'C:\npm\node_modules\npm\bin\npx-cli.js', '@google/gemini-cli'], ('gemini', '@google/gemini-cli')))
        self.assertTrue(S.cmd_matches(['node.exe', r'C:\npm\gemini.js', 'chat'], ('gemini',)))

    def test_command_lines_are_read_once_per_process(self):
        i = FakeInfo()
        i.add(13, 1, 'node.exe', argv=['node.exe', r'C:\x\gemini.js'])
        sc = S.ProcessScanner(CPU, i, platform=WIN)
        for t in range(5):
            sc.scan(100.0 + t)
        self.assertEqual(i.argv_reads, 1)


class Cpu(unittest.TestCase):
    def test_cpu_above_threshold_is_working_then_idle_with_finished(self):
        i = FakeInfo()
        i.add(10, 1, 'ollama.exe')
        i.add(11, 10, 'ollama_llama_server.exe')                         # child process: part of the tree
        src = S.ProcessSource(CPU, S.ProcessScanner(CPU, i, platform=WIN))
        states, evs = {}, []
        for t in range(0, 60, 2):
            if 4 <= t < 30:
                i.burn(11, 1.6)                                          # 80% of a core in the child
            acts = src.poll(1000.0 + t)
            states[t] = acts[0].state
            evs += acts[0].events
        self.assertEqual(states[0], 'idle')
        self.assertEqual(states[20], 'working')
        self.assertEqual(states[50], 'idle')
        self.assertEqual(evs, ['finished'])

    def test_claimed_children_are_not_counted_for_their_host(self):
        i = FakeInfo()
        i.add(10, 1, 'cursor.exe')
        i.add(11, 10, 'claude.exe')                                      # Claude Code running inside Cursor's terminal
        i.add(12, 11, 'node.exe', argv=['node.exe', r'C:\x\tool.js'])     # ... and its child
        src = S.ProcessSource(CPU, S.ProcessScanner(CPU, i, platform=WIN))
        for t in range(0, 20, 2):
            i.burn(11, 1.8)
            i.burn(12, 1.8)
            acts = src.poll(1000.0 + t)
        self.assertEqual([(a.source_id, a.state) for a in acts], [('cursor', 'idle')])

    def test_a_new_process_does_not_count_its_past_cpu(self):
        i = FakeInfo()
        i.add(10, 1, 'cursor.exe', cpu=5000.0)                           # long-running: lifetime CPU is not "now"
        src = S.ProcessSource(CPU, S.ProcessScanner(CPU, i, platform=WIN))
        for t in range(0, 10, 2):
            acts = src.poll(1000.0 + t)
        self.assertEqual(acts[0].state, 'idle')
        self.assertEqual(acts[0].last_active, 0.0)                        # never active: does not look recent to the director

    def test_program_closing_removes_the_source(self):
        i = FakeInfo()
        i.add(10, 1, 'cursor.exe')
        src = S.ProcessSource(CPU, S.ProcessScanner(CPU, i, platform=WIN))
        self.assertEqual(len(src.poll(1.0)), 1)
        del i.p[10]
        self.assertEqual(src.poll(3.0), [])


class Registry(Isolated):
    def test_transcript_source_absent_without_a_session_and_present_with_one(self):
        root = self.data / 'claude'
        (root / 'p').mkdir(parents=True)
        cfg = dict(CFG, claude_dirs=[str(root)])
        now = time.time()
        src = S.TranscriptSource('claude', cfg)
        self.assertEqual(src.poll(now), [])
        p = root / 'p' / 's.jsonl'
        p.write_text(json.dumps({'type': 'assistant', 'timestamp': '2030-01-01T00:00:00Z', 'message': {'stop_reason': 'end_turn', 'usage': {'input_tokens': 100000}}}) + '\n', encoding='utf-8')
        os.utime(p, (now - 10, now - 10))
        src = S.TranscriptSource('claude', cfg)
        (a,) = src.poll(now)
        self.assertEqual((a.source_id, a.character, a.program, a.ctx_pct), ('claude', 'claude', 'Claude Code', 10.0))
        self.assertAlmostEqual(a.last_active, now - 10, places=3)

    def test_a_broken_detector_does_not_hide_the_others_and_ids_are_unique(self):
        class Boom:
            def poll(self, now):
                raise RuntimeError('x')

        class Two:
            def poll(self, now):
                return [S.Activity('cursor', 'Cursor', 'cursor'), S.Activity('cursor', 'Cursor', 'cursor')]
        reg = S.Sources(CFG, detectors=[Boom(), Two()])
        self.assertEqual([a.source_id for a in reg.poll(1.0)], ['cursor'])

    def test_detector_for_picks_the_right_kind(self):
        self.assertIsInstance(S.detector_for('codex', CFG), S.TranscriptSource)
        d = S.detector_for('cursor', CFG, )
        self.assertIsInstance(d, S.ProcessSource)
        self.assertEqual(d.only, 'cursor')

    def test_ignored_sources_are_never_reported(self):
        class Two:
            def poll(self, now):
                return [S.Activity('grok', 'Grok', 'generic'), S.Activity('claude', 'Claude Code', 'claude')]
        reg = S.Sources(dict(CFG, ignore_sources=['grok']), detectors=[Two()])
        self.assertEqual([a.source_id for a in reg.poll(1.0)], ['claude'])
        self.assertEqual([a.source_id for a in S.Sources(CFG, detectors=[Two()]).poll(1.0)], ['grok', 'claude'])

    def test_sparring_bot_has_a_null_detector_and_a_name(self):
        d = S.detector_for(S.SPARRING, CFG)
        self.assertIsInstance(d, S.NullDetector)
        self.assertEqual(d.poll(1.0), [])
        self.assertEqual((S.PROGRAM[S.SPARRING], S.CHARACTER[S.SPARRING]), ('Sparring bot', 'generic'))
        self.assertFalse(any(r['source'] == S.SPARRING for r in S.RULES))              # no process can ever claim it


class NewPrograms(unittest.TestCase):
    """V5.1: programs found installed on the author's PC that the table missed (`minis.py detect`)."""

    def test_npm_clis_are_matched_by_package_path_under_node(self):
        i = FakeInfo()
        i.add(10, 1, 'node.exe', argv=['node.exe', r'C:\Users\u\AppData\Roaming\npm\node_modules\@github\copilot\index.js'])
        i.add(11, 1, 'node.exe', argv=['node.exe', r'C:\Users\u\AppData\Roaming\npm\node_modules\@qwen-code\qwen-code\cli.js'])
        i.add(12, 1, 'node.exe', argv=['node.exe', 'copilot'])
        i.add(13, 1, 'node.exe', argv=['node.exe', r'C:\x\pi.js'])                        # not in the table: never shows
        self.assertEqual([a.source_id for a in scan_ids(i)], ['copilot', 'qwen'])
        by = {a.source_id: a for a in scan_ids(i)}
        self.assertEqual((by['copilot'].program, by['copilot'].character), ('Copilot CLI', 'generic'))
        self.assertEqual(by['qwen'].program, 'Qwen Code')

    def test_desktop_apps_by_image_name(self):
        i = FakeInfo()
        i.add(10, 1, 'perplexity.exe')
        i.add(11, 1, 'grok bot.exe')
        i.add(12, 1, 'lm studio.exe')
        i.add(13, 1, 'cursor.exe')
        i.add(14, 1, 'opencode.exe')
        i.add(15, 1, 'claude-devtools.exe')                                                # a viewer, not an agent
        i.add(16, 1, 'emdash.exe')                                                         # hosts Claude + Codex: never a third fighter
        self.assertEqual([a.source_id for a in scan_ids(i)], ['cursor', 'grok', 'lmstudio', 'opencode', 'perplexity'])

    def test_describe_names_programs_and_numbers_only(self):
        i = FakeInfo()
        i.add(10, 1, 'cursor.exe', path=r'C:\Users\secret-project\cursor\cursor.exe')
        i.add(11, 10, 'cursor.exe', path=r'C:\Users\secret-project\cursor\cursor.exe', argv=['cursor.exe', r'C:\secret-project\notes.md'])
        sc = S.ProcessScanner(CPU, i, platform=WIN)
        srcs = S.Sources(CPU, detectors=[S.ProcessSource(CPU, sc)])
        srcs.poll(100.0)
        i.burn(11, 1.5)
        rows = S.describe(CPU, 103.0, srcs)
        by = {r['source']: r for r in rows}
        self.assertEqual({r['source'] for r in S.RULES} | set(S.TRANSCRIPT_SOURCES), set(by))
        self.assertEqual(by['cursor']['state'], 'working')
        self.assertIn('process: cursor.exe, cpu 50% of one core', by['cursor']['how'])
        self.assertEqual(by['copilot']['state'], '-')
        self.assertIn('would match command copilot / @github/copilot', by['copilot']['how'])
        self.assertEqual(by['claude']['how'], 'transcript sources not polled')
        text = ' '.join(f"{r['program']} {r['character']} {r['state']} {r['how']}" for r in rows)
        self.assertNotIn('secret-project', text)
        self.assertNotIn('notes.md', text)
        self.assertNotIn('\\', text)
        self.assertNotIn(':', text.replace(': ', ''))                                      # no drive letters, no paths

    def test_activity_snapshot_carries_numbers_and_events(self):
        s = S.Activity('codex', 'Codex', 'codex', 'working', 12.0, 3.0, 'wk', '1d 2h', 5.0, ['finished']).snapshot()
        self.assertEqual((s.state, s.ctx_pct, s.plan_pct, s.plan_label, s.events), ('working', 12.0, 3.0, 'wk', ['finished']))


@unittest.skipUnless(sys.platform == 'win32', 'Win32 only')
class RealProcesses(unittest.TestCase):
    """The real ctypes layer, checked against this test process only (nothing else is printed or kept)."""

    def test_own_process_is_listed_and_its_argv_reads_back(self):
        from minis_win import procs
        me = os.getpid()
        rows = [r for r in procs.list_processes() if r[0] == me]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][2].startswith('python'))
        self.assertEqual(procs.argv(me), list(sys.orig_argv))
        self.assertTrue(procs.alive(me))
        self.assertIsNotNone(procs.times(me))

    def test_real_scan_only_reports_programs_from_the_table(self):
        sc = S.ProcessScanner(CPU)
        out = sc.scan(time.time())
        known = {r['source'] for r in S.RULES} - set(S.TRANSCRIPT_SOURCES)
        self.assertLessEqual(set(out), known)


if __name__ == '__main__':
    unittest.main()
