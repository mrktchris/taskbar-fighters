"""Growth: more AI programs in the detection table (minis_core/sources.py RULES), on synthetic process tables only.
Command lines are compared and discarded; nothing here touches a real process."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG  # noqa: E402
from test_sources import FakeInfo, scan_ids, CPU  # noqa: E402
from test_mac_platform import FakeMacInfo  # noqa: E402
from minis_core import sources as S  # noqa: E402

NPM = r'C:\Users\u\AppData\Roaming\npm\node_modules'


class WindowsTable(unittest.TestCase):
    def test_new_desktop_apps_and_clis_by_image_name(self):
        i = FakeInfo()
        i.add(10, 1, 'zed.exe')
        i.add(11, 1, 'junie.exe')
        i.add(12, 1, 'crush.exe')
        i.add(13, 1, 'goose.exe')
        i.add(14, 1, 'jan.exe')
        i.add(15, 1, 'windsurf.exe')
        got = {a.source_id: (a.program, a.character) for a in scan_ids(i)}
        self.assertEqual(got, {'zed': ('Zed', 'knight'), 'junie': ('Junie', 'kunoichi'), 'crush': ('Crush', 'oni'),
                               'goose': ('Goose', 'nomad'), 'jan': ('Jan', 'lmstudio'), 'windsurf': ('Windsurf', 'generic')})

    def test_npm_clis_by_package_path_or_script_name(self):
        i = FakeInfo()
        i.add(10, 1, 'node.exe', argv=['node.exe', NPM + r'\@continuedev\cli\dist\cn.js'])
        i.add(11, 1, 'node.exe', argv=['node.exe', NPM + r'\cline\bin\cline.js', 'task'])
        i.add(12, 1, 'node.exe', argv=['node.exe', NPM + r'\@charmland\crush\bin\crush.js'])
        i.add(13, 1, 'node.exe', argv=['node.exe', NPM + r'\@jetbrains\junie\bin\index.js'])
        i.add(14, 1, 'node.exe', argv=['node.exe', NPM + r'\@github\copilot\index.js'])            # existing rule, verified
        i.add(15, 1, 'node.exe', argv=['node.exe', NPM + r'\@google\gemini-cli\dist\index.js'])    # existing rule, verified
        self.assertEqual([a.source_id for a in scan_ids(i)], ['cline', 'continue', 'copilot', 'crush', 'gemini', 'junie'])

    def test_plain_chatgpt_is_chatgpt_but_the_codex_app_stays_codex(self):
        i = FakeInfo()
        i.add(10, 1, 'chatgpt.exe', path=r'C:\Program Files\WindowsApps\OpenAI.ChatGPT-Desktop_1.0_x64__abc\app\ChatGPT.exe')
        i.add(20, 1, 'chatgpt.exe', path=r'C:\Program Files\WindowsApps\OpenAI.Codex_1.2.3_x64__abc\app\ChatGPT.exe')
        sc = S.ProcessScanner(CPU, i, platform='win32')
        got = [a.source_id for a in S.ProcessSource(CPU, sc).poll(1.0)]
        self.assertEqual(got, ['chatgpt'])
        self.assertEqual(sc.claimed, {'codex': 1})

    def test_claude_desktop_app_is_its_own_program_and_the_cli_stays_claimed(self):
        i = FakeInfo()
        i.add(10, 1, 'claude.exe', path=r'C:\Users\u\AppData\Local\AnthropicClaude\app-1.2.3\claude.exe')
        i.add(11, 10, 'claude.exe', path=r'C:\Users\u\AppData\Local\AnthropicClaude\app-1.2.3\claude.exe')
        i.add(20, 1, 'claude.exe', path=r'C:\Users\u\.local\bin\claude.exe')                     # Claude Code (transcripts)
        sc = S.ProcessScanner(CPU, i, platform='win32')
        acts = S.ProcessSource(CPU, sc).poll(1.0)
        self.assertEqual([(a.source_id, a.program, a.character) for a in acts], [('claudeapp', 'Claude desktop', 'claude')])
        self.assertEqual(sc.claimed, {'claude': 1})
        j = FakeInfo()
        j.add(30, 1, 'claude.exe', path=r'C:\Program Files\WindowsApps\Claude_1.0.0.0_x64__pzs8sxrjxfjjc\app\claude.exe')
        self.assertEqual([a.source_id for a in scan_ids(j)], ['claudeapp'])

    def test_plain_vs_code_and_its_extension_host_are_never_cline_or_continue(self):
        i = FakeInfo()
        i.add(10, 1, 'code.exe', argv=['code.exe'])
        i.add(11, 10, 'code.exe', argv=['code.exe', '--type=extensionHost', '--inspect-port=0'])
        i.add(12, 10, 'node.exe', argv=['node.exe', r'C:\Users\u\.vscode\extensions\saoudrizwan.claude-dev-3.0.0\dist\extension.js'])
        i.add(13, 10, 'node.exe', argv=['node.exe', r'C:\Users\u\.vscode\extensions\continue.continue-1.0.0\out\index.js'])
        i.add(14, 1, 'node.exe', argv=['node.exe', r'C:\work\scripts\cline-notes.js'])
        i.add(15, 1, 'idea64.exe')                                       # JetBrains IDE: its AI Assistant is not separable
        self.assertEqual(scan_ids(i), [])

    def test_option_or_later_argument_never_matches(self):
        self.assertFalse(S.cmd_matches(['node.exe', r'C:\x\server.js', 'cline'], ('cline',)))
        self.assertFalse(S.cmd_matches(['node.exe', '-e', 'require("@charmland/crush")'], ('crush', '@charmland/crush')))
        self.assertTrue(S.cmd_matches(['node.exe', r'C:\npm\node_modules\npm\bin\npx-cli.js', '@jetbrains/junie'],
                                      ('junie', '@jetbrains/junie')))


class MacTable(unittest.TestCase):
    def test_mac_names_for_the_new_programs(self):
        info = FakeMacInfo([
            (10, 1, 'zed', '/Applications/Zed.app/Contents/MacOS/zed', None, 0.0),
            (11, 1, 'goose', '/Applications/Goose.app/Contents/MacOS/Goose', None, 0.0),
            (12, 1, 'jan', '/Applications/Jan.app/Contents/MacOS/Jan', None, 0.0),
            (13, 1, 'q', '/Applications/Amazon Q.app/Contents/MacOS/q', None, 0.0),
            (14, 1, 'crush', '/opt/homebrew/bin/crush', None, 0.0),
            (15, 1, 'junie', '/Users/u/.local/bin/junie', None, 0.0),
            (16, 1, 'node', '/opt/homebrew/bin/node', ['node', '/opt/homebrew/bin/cline'], 0.0),
            (17, 1, 'claude', '/Applications/Claude.app/Contents/MacOS/Claude', None, 0.0),        # the desktop app
            (18, 1, 'claude', '/Users/u/.local/bin/claude', None, 0.0),                             # Claude Code: claimed
            (19, 1, 'chatgpt', '/Applications/ChatGPT.app/Contents/MacOS/ChatGPT', None, 0.0),
            (20, 1, 'code helper (plugin)', '/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/'
             'Contents/MacOS/Code Helper (Plugin)', None, 0.0),
        ])
        sc = S.ProcessScanner(dict(CFG), info, platform='darwin')
        out = sc.scan(100.0)
        self.assertEqual(set(out), {'zed', 'goose', 'jan', 'amazonq', 'crush', 'junie', 'cline', 'claudeapp', 'chatgpt'})
        self.assertEqual(sc.claimed, {'claude': 1})

    def test_windows_only_path_rules_are_dropped_on_mac(self):
        t = S.rules_for('darwin')
        self.assertFalse(any('path_has' in r for r in t))
        self.assertTrue(any(r['source'] == 'claudeapp' and 'claude.app' in r.get('bundle', ()) for r in t))


class Describe(unittest.TestCase):
    def test_detect_lists_every_new_program_with_names_only(self):
        sc = S.ProcessScanner(CPU, FakeInfo(), platform='win32')
        srcs = S.Sources(CPU, detectors=[S.ProcessSource(CPU, sc)])
        rows = {r['source']: r for r in S.describe(CPU, 100.0, srcs)}
        for sid in ('chatgpt', 'zed', 'junie', 'continue', 'cline', 'crush', 'goose', 'jan', 'claudeapp', 'windsurf',
                    'aider', 'opencode', 'qwen', 'copilot', 'gemini', 'ollama', 'lmstudio'):
            self.assertIn(sid, rows)
        self.assertIn('would match command @continuedev/cli', rows['continue']['how'])
        self.assertNotIn('anthropicclaude', rows['claudeapp']['how'])                  # path markers are never printed
        if sys.platform != 'darwin':                                                    # Amazon Q has macOS names only
            self.assertEqual(rows['amazonq']['how'], 'not detected on this OS (no known process name here)')

    def test_every_rule_names_an_existing_character(self):
        from minis_core import atlas
        have = set(atlas.available())
        for r in S.RULES:
            self.assertIn(S.CHARACTER[r['source']], have | {'claude', 'codex'}, r['source'])


if __name__ == '__main__':
    unittest.main()
