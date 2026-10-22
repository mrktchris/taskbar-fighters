"""Sources: everything that can put a fighter on the taskbar.  Each detector yields Activity records.

  claude, codex      transcript-based (telemetry.Tracker): real state, context %, plan %.
  process detectors  a table of known AI programs, matched by executable name or command line (ctypes only, no file
                     reading).  State comes from the CPU use of the program's process tree over the last few seconds;
                     context and plan are unknown (None -> the plate shows '-').  Anything not in the table never shows.

A program is never counted twice: rules that point at `claude` or `codex` only *claim* processes for those transcript
sources (the Codex desktop app is ChatGPT.exe under an OpenAI.Codex_* package folder: it is Codex, not ChatGPT), and a
claimed process - with its children - is left out of every other program's CPU tree.
"""
from __future__ import annotations
import os, time
from collections import deque
from dataclasses import dataclass, field

from .telemetry import Snapshot, Tracker, Transitions

TRANSCRIPT_SOURCES = ('claude', 'codex')
LAUNCHERS = {'npx', 'npx-cli', 'npm-cli', 'npm', 'bunx', 'uvx', 'pipx', 'pnpm', 'dlx'}
INTERPRETERS = {'node.exe', 'bun.exe', 'deno.exe', 'python.exe', 'pythonw.exe', 'python3.exe', 'py.exe', 'uv.exe', 'uvx.exe'}

# First match wins, so claims come first.  exe: lower-case image names.  path_has: required substring of the image path.
# cmd: names matched against the first few argv tokens of an interpreter (basename without .js/.cmd/.exe/.mjs/.py),
# or a package path fragment.
# macOS names (experimental, untested on a real Mac): mac_exe = lower-case executable basenames as `ps -o comm` shows them;
# mac_bundle = app bundles whose MAIN executable (<Name>.app/Contents/MacOS/...) counts, never their helper processes.
# `cmd` is shared: npm / pip CLIs have the same names on both systems.  rules_for() picks the fields for this OS.
RULES = [
    dict(source='codex', exe=('chatgpt.exe',), path_has='openai.codex_', mac_bundle=('codex.app',)),
    dict(source='codex', exe=('codex.exe',), mac_exe=('codex',)),
    dict(source='codex', cmd=('codex', '@openai/codex')),
    # The Claude DESKTOP app (claude.exe in %LOCALAPPDATA%\AnthropicClaude or the MSIX Claude_* package; Claude.app) is
    # its own program, matched by its install path before the bare claude.exe rule claims the Claude Code CLI.
    dict(source='claudeapp', program='Claude desktop', character='claude', exe=('claude.exe',), path_has='anthropicclaude',
         mac_bundle=('claude.app',)),
    dict(source='claudeapp', program='Claude desktop', character='claude', exe=('claude.exe',), path_has='windowsapps\\claude_'),
    dict(source='claude', exe=('claude.exe',), mac_exe=('claude',)),
    dict(source='claude', cmd=('claude', '@anthropic-ai/claude-code')),
    dict(source='cursor', program='Cursor', character='cursor', exe=('cursor.exe',), mac_exe=('cursor',), mac_bundle=('cursor.app',)),
    dict(source='windsurf', program='Windsurf', character='generic', exe=('windsurf.exe',), mac_exe=('windsurf',), mac_bundle=('windsurf.app',)),
    dict(source='ollama', program='Ollama', character='ollama', exe=('ollama.exe', 'ollama app.exe'), mac_exe=('ollama',),
         mac_bundle=('ollama.app',)),
    dict(source='lmstudio', program='LM Studio', character='lmstudio', exe=('lm studio.exe',), mac_exe=('lm studio',),
         mac_bundle=('lm studio.app',)),
    dict(source='gemini', program='Gemini', character='gemini', exe=('gemini.exe',), cmd=('gemini', '@google/gemini-cli'), mac_exe=('gemini',)),
    dict(source='aider', program='aider', character='generic', exe=('aider.exe',), cmd=('aider',), mac_exe=('aider',)),
    dict(source='opencode', program='opencode', character='generic', exe=('opencode.exe',), cmd=('opencode', 'opencode-ai'), mac_exe=('opencode',)),
    # V5.1: found installed on the author's PC and missed before (npm shims run under node.exe: matched by package path)
    dict(source='copilot', program='Copilot CLI', character='generic', cmd=('copilot', '@github/copilot')),
    dict(source='qwen', program='Qwen Code', character='generic', cmd=('qwen', '@qwen-code/qwen-code')),
    dict(source='perplexity', program='Perplexity', character='generic', exe=('perplexity.exe',), mac_exe=('perplexity',),
         mac_bundle=('perplexity.app',)),
    dict(source='grok', program='Grok', character='generic', exe=('grok bot.exe',), mac_exe=('grok',), mac_bundle=('grok.app',)),
    # Growth (2026-10-21).  Names from each vendor's install docs; none seen on a real machine yet (README "Detected programs").
    # Plain ChatGPT.exe comes AFTER the Codex rule above: under an OpenAI.Codex_* folder the same image name is Codex.
    dict(source='chatgpt', program='ChatGPT', character='generic', exe=('chatgpt.exe',), mac_bundle=('chatgpt.app',)),
    dict(source='zed', program='Zed', character='knight', exe=('zed.exe',), mac_exe=('zed',), mac_bundle=('zed.app',)),
    dict(source='junie', program='Junie', character='kunoichi', exe=('junie.exe',), cmd=('junie', '@jetbrains/junie'), mac_exe=('junie',)),
    dict(source='continue', program='Continue CLI', character='monk', cmd=('@continuedev/cli',)),
    dict(source='cline', program='Cline CLI', character='barbarian', cmd=('cline',)),
    dict(source='amazonq', program='Amazon Q', character='generic', mac_exe=('q', 'qchat'), mac_bundle=('amazon q.app',)),
    dict(source='crush', program='Crush', character='oni', exe=('crush.exe',), cmd=('crush', '@charmland/crush'), mac_exe=('crush',)),
    dict(source='goose', program='Goose', character='nomad', exe=('goose.exe',), mac_exe=('goose',), mac_bundle=('goose.app',)),
    dict(source='jan', program='Jan', character='lmstudio', exe=('jan.exe',), mac_bundle=('jan.app',)),
]
MAC_INTERPRETERS = {'node', 'bun', 'deno', 'python', 'python3', 'uv', 'uvx'}
_MAC_RULES = None


def is_mac_interpreter(name) -> bool:
    """node, bun, deno, uv, python, python3 and python3.N (Homebrew / python.org names)."""
    n = str(name).lower()
    return n in MAC_INTERPRETERS or (n.startswith('python3.') and n[8:].isdigit())


def rules_for(platform=None):
    """The detection table for one OS.  Windows gets RULES itself (unchanged); macOS a view with exe / bundle taken from
    the mac_* fields (path_has is a Windows package path and is dropped)."""
    global _MAC_RULES
    import sys
    if (platform or sys.platform) != 'darwin':
        return RULES
    if _MAC_RULES is None:
        out = []
        for r in RULES:
            m = {k: v for k, v in r.items() if k in ('source', 'program', 'character', 'cmd')}
            if r.get('mac_exe'):
                m['exe'] = tuple(r['mac_exe'])
            if r.get('mac_bundle'):
                m['bundle'] = tuple(r['mac_bundle'])
            if m.get('exe') or m.get('bundle') or m.get('cmd'):
                out.append(m)
        _MAC_RULES = out
    return _MAC_RULES


def bundle_hit(path, bundles) -> bool:
    """True when `path` is the main executable of one of `bundles` (.../Name.app/Contents/MacOS/<exe>), not a helper."""
    p = (path or '').replace(chr(92), '/').lower()
    for b in bundles or ():
        key = '/' + b.lower() + '/contents/macos/'
        i = p.find(key)
        if i >= 0 and '/' not in p[i + len(key):]:
            return True
    return False


SPARRING = 'sparring'                                 # the director's stand-in partner: no detector ever reports it
PROGRAM = {'claude': 'Claude Code', 'codex': 'Codex', SPARRING: 'Sparring bot'}
for _r in RULES:
    PROGRAM.setdefault(_r['source'], _r.get('program', _r['source']))
CHARACTER = {r['source']: r.get('character', r['source']) for r in RULES}
CHARACTER[SPARRING] = 'generic'
# V6: the short name the scoreboard, the select screen and a skinned plate use ("Claude Code" -> "Claude"); never truncated
LABEL = {'claude': 'Claude', 'codex': 'Codex', SPARRING: 'Bot', 'lmstudio': 'LM Studio', 'copilot': 'Copilot', 'qwen': 'Qwen',
         'claudeapp': 'Claude app', 'continue': 'Continue', 'cline': 'Cline', 'amazonq': 'Amazon Q'}


def short_label(source_id, program=None) -> str:
    """Short display label of a program: the LABEL table, else the program's name, else the id."""
    if source_id in LABEL:
        return LABEL[source_id]
    return str(PROGRAM.get(source_id) or program or source_id or '-')


def known_programs() -> list:
    """Every source id a fighter can be picked for, in table order: the two transcript programs, the process table, the bot."""
    out = list(TRANSCRIPT_SOURCES)
    for r in RULES:
        if r['source'] not in out:
            out.append(r['source'])
    return out + [SPARRING]


@dataclass
class Activity:
    source_id: str
    program: str
    character: str
    state: str = 'idle'
    ctx_pct: float | None = None
    plan_pct: float | None = None
    plan_label: str = ''
    resets_in: str = ''
    last_active: float = 0.0
    events: list = field(default_factory=list)

    def snapshot(self) -> Snapshot:
        return Snapshot(self.character, self.state, self.ctx_pct, self.plan_pct, self.plan_label, self.resets_in, events=list(self.events))


def _stem(tok):
    b = tok.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1].lower()
    for ext in ('.js', '.mjs', '.cjs', '.cmd', '.exe', '.py', '.ps1'):
        if b.endswith(ext):
            return b[:-len(ext)]
    return b


def cmd_matches(argv, names):
    """True if one of the first few non-option arguments after the interpreter is one of `names` (or contains a package
    path like @google/gemini-cli).  Only names and package paths are compared; nothing is kept."""
    argv = argv or []
    if any(a in ('-c', '-e', '--eval', '-p', '--print') for a in argv[1:2]):
        return False                                              # inline code: its text is not a program name
    rest = [t for t in argv[1:] if t and not t.startswith('-')]
    if len(argv) > 2 and argv[1] == '-m':                         # python -m aider
        rest = [argv[2]] + rest
    toks = rest[:1]                                               # the script or module, never a later argument
    if rest and _stem(rest[0]) in LAUNCHERS:                      # npx @google/gemini-cli, uvx aider-chat, ...
        toks = rest[:2]
    toks = [t for t in toks if not any(c.isspace() for c in t)]
    for t in toks:
        low = t.replace('\\', '/').lower()
        for n in names:
            if '/' in n or n.startswith('@'):
                if n in low or n.split('/')[-1] in low.split('/'):
                    return True
            elif _stem(t) == n:
                return True
    return False


# ------------------------------------------------------------------ transcript sources
class TranscriptSource:
    def __init__(self, who, cfg, clock=time.time, feed_path=None):
        self.source_id = who
        self.tracker = Tracker(who, cfg, clock=clock, feed_path=feed_path)
        self.cfg = cfg

    def poll(self, now):
        snap = self.tracker.poll(now)
        m = self.tracker.mtime
        if not self.tracker.path or m is None or now - m > self.cfg['stale_session_hours'] * 3600:
            return []                                              # no session at all: this program is not around
        return [Activity(self.source_id, PROGRAM[self.source_id], self.source_id, snap.state, snap.ctx_pct, snap.plan_pct,
                         snap.plan_label, snap.resets_in, last_active=m, events=list(snap.events))]


# ------------------------------------------------------------------ process sources
class ProcessScanner:
    """One pass over the process list classifies every process by RULES, builds each program's tree (children included,
    claimed and other programs' processes excluded) and measures its CPU over a sliding window."""

    def __init__(self, cfg, info=None, rules=None, platform=None):
        import sys
        mac = (platform or sys.platform) == 'darwin'
        if info is None:
            import minis_platform
            info = minis_platform.module('procs', platform).Info
        self.cfg, self.info, self.rules = cfg, info, rules or rules_for(platform)
        self._is_interp = is_mac_interpreter if mac else INTERPRETERS.__contains__
        self._bundles = any(r.get('bundle') for r in self.rules)          # mac only: Windows rules have none
        self._cls = {}           # (pid, create) -> source or None   (command lines are read once per process)
        self._cpu = {}           # (pid, create) -> last cpu seconds
        self.groups = {}         # source -> dict(samples=deque[(t, cum)], cum, last_active, first_seen, tr)
        self.claimed = {}        # source -> pid count (diagnostics)
        self.matched = {}        # source -> sorted image names of its root processes (diagnostics: `minis.py detect`)

    def _classify(self, pid, name, create):
        key = (pid, create)
        if key in self._cls:
            return self._cls[key]
        src = None
        argv = None
        for r in self.rules:
            if name in r.get('exe', ()):
                ph = r.get('path_has')
                if ph:
                    p = self.info.path(pid)
                    if not p or ph not in p.lower():
                        continue
                src = r['source']
                break
            if r.get('bundle') and bundle_hit(self.info.path(pid), r['bundle']):
                src = r['source']
                break
            if r.get('cmd') and self._is_interp(name):
                if argv is None:
                    argv = self.info.argv(pid) or []
                if cmd_matches(argv, r['cmd']):
                    src = r['source']
                    break
        self._cls[key] = src
        return src

    def scan(self, now):
        """-> {source: (state, last_active, events)} for every program from the table that is running."""
        plist = self.info.list()
        kids, times = {}, {}
        for pid, ppid, name in plist:
            kids.setdefault(ppid, []).append(pid)
        names = {pid: name for pid, _, name in plist}
        owner = {}
        for pid, ppid, name in plist:
            if not self._is_interp(name) and not any(name in r.get('exe', ()) for r in self.rules) and not (
                    self._bundles and bundle_hit(self.info.path(pid), [b for r in self.rules for b in r.get('bundle', ())])):
                continue
            t = self.info.times(pid)
            if not t:
                continue
            times[pid] = t
            src = self._classify(pid, name, t[0])
            if src:
                owner[pid] = src
        roots = {}
        for pid, src in owner.items():
            roots.setdefault(src, []).append(pid)
        self.claimed = {s: len(v) for s, v in roots.items() if s in TRANSCRIPT_SOURCES}
        self.matched = {s: sorted({names[p] for p in v}) for s, v in roots.items()}      # source -> image names only (diagnostics)
        seen_keys = set()
        out = {}
        for src, rs in roots.items():
            if src in TRANSCRIPT_SOURCES:
                continue
            tree, stack = set(), list(rs)
            while stack:                                           # children, but never another program's or a claimed one
                p = stack.pop()
                if p in tree or (p in owner and owner[p] != src):
                    continue
                tree.add(p)
                stack.extend(kids.get(p, []))
            delta = 0.0
            for p in tree:
                t = times.get(p) or self.info.times(p)
                if not t:
                    continue
                key = (p, t[0])
                seen_keys.add(key)
                if key in self._cpu:
                    delta += max(0.0, t[1] - self._cpu[key])        # a process first seen now counts from now on
                self._cpu[key] = t[1]
            g = self.groups.get(src)
            if g is None:
                g = self.groups[src] = dict(samples=deque(), cum=0.0, last_active=0.0, tr=Transitions(self.cfg))   # never active yet
            g['cum'] += delta
            g['samples'].append((now, g['cum']))
            win = self.cfg['proc_window_s']
            while len(g['samples']) > 2 and g['samples'][1][0] <= now - win:
                g['samples'].popleft()
            t0, c0 = g['samples'][0]
            rate = (g['cum'] - c0) / (now - t0) * 100.0 if now - t0 >= 1.0 else 0.0
            g['rate'] = rate
            state = 'working' if rate >= self.cfg['proc_working_cpu_pct'] else 'idle'
            if state == 'working':
                g['last_active'] = now
            snap = g['tr'].apply(Snapshot(src, state), now)
            out[src] = (snap.state, g['last_active'], snap.events)
        for k in list(self._cpu):
            if k not in seen_keys:
                del self._cpu[k]
        live = {(pid, times[pid][0]) for pid in times}
        for k in list(self._cls):
            if k not in live:
                del self._cls[k]
        for src in list(self.groups):
            if src not in out:
                del self.groups[src]                               # program closed: start fresh if it comes back
        return out


class ProcessSource:
    """All process programs (or just `only`), as Activities."""

    def __init__(self, cfg, scanner=None, only=None):
        self.scanner = scanner or ProcessScanner(cfg)
        self.only = only

    def poll(self, now):
        acts = []
        for src, (state, last, events) in sorted(self.scanner.scan(now).items()):
            if self.only and src != self.only:
                continue
            acts.append(Activity(src, PROGRAM.get(src, src), CHARACTER.get(src, 'generic'), state, last_active=last, events=list(events)))
        return acts


# ------------------------------------------------------------------ registry
class Sources:
    """Every detector.  poll(now) -> [Activity] for whatever is around right now."""

    def __init__(self, cfg, detectors=None, clock=time.time):
        self.cfg = cfg
        self.detectors = detectors if detectors is not None else [
            TranscriptSource('claude', cfg, clock), TranscriptSource('codex', cfg, clock), ProcessSource(cfg)]

    def poll(self, now):
        out, ids = [], set(self.cfg.get('ignore_sources') or ())          # ignored programs are never reported at all
        for d in self.detectors:
            try:
                acts = d.poll(now)
            except Exception:                                      # one broken detector must not hide the others
                acts = []
            for a in acts:
                if a.source_id not in ids:
                    ids.add(a.source_id)
                    out.append(a)
        return out


class NullDetector:
    """Never sees anything: the sparring bot's slot shows `sleeping` with no numbers, and nothing is scanned for it."""

    def poll(self, now):
        return []


def detector_for(source_id, cfg, clock=time.time):
    """The single detector a fighter slot runs for its assigned source."""
    if source_id == SPARRING:
        return NullDetector()
    if source_id in TRANSCRIPT_SOURCES:
        return TranscriptSource(source_id, cfg, clock)
    return ProcessSource(cfg, only=source_id)


# ------------------------------------------------------------------ diagnostics (`minis.py detect`)
def _age(seconds):
    if seconds is None:
        return '-'
    s = int(seconds)
    if s < 90:
        return f'{s} s'
    if s < 5400:
        return f'{s // 60} min'
    return f'{s / 3600:.1f} h'


def describe(cfg, now=None, srcs=None):
    """-> [dict(source, program, character, state, how)] for every program in the table: what the detectors see right now
    and how (a transcript's age and context, or the matched image names and CPU rate).  Names and numbers only: no window
    title, no path, nothing beyond the executable's file name."""
    now = time.time() if now is None else now
    srcs = srcs or Sources(cfg)
    acts = {a.source_id: a for a in srcs.poll(now)}
    rows = []
    scanner = None
    for d in srcs.detectors:
        if isinstance(d, ProcessSource):
            scanner = d.scanner
    for sid in TRANSCRIPT_SOURCES:
        tr = next((d.tracker for d in srcs.detectors if isinstance(d, TranscriptSource) and d.source_id == sid), None)
        a = acts.get(sid)
        if a is not None:
            how = f'transcript, newest session file {_age(now - (a.last_active or now))} old'
            if a.ctx_pct is not None:
                how += f', ctx {int(round(a.ctx_pct))}%'
        elif tr is not None and tr.path is None:
            how = f"no session file within {cfg['stale_session_hours']} h"
        else:
            how = 'transcript sources not polled'
        rows.append(dict(source=sid, program=PROGRAM[sid], character=CHARACTER.get(sid, sid), state=a.state if a else '-', how=how))
    seen_rules = set()
    table = rules_for()
    for r in table:
        sid = r['source']
        if sid in TRANSCRIPT_SOURCES or sid in seen_rules:
            continue
        seen_rules.add(sid)
        a = acts.get(sid)
        if a is not None and scanner is not None:
            names = ', '.join(scanner.matched.get(sid, [])) or 'process tree'
            rate = (scanner.groups.get(sid) or {}).get('rate', 0.0)
            how = f'process: {names}, cpu {rate:.0f}% of one core'
            if a.last_active:
                how += f', last working {_age(now - a.last_active)} ago'
        else:
            by = [f"exe {' / '.join(r2['exe'])}" for r2 in table if r2['source'] == sid and r2.get('exe')]
            by += [f"app {' / '.join(r2['bundle'])}" for r2 in table if r2['source'] == sid and r2.get('bundle')]
            by += [f"command {' / '.join(r2['cmd'])}" for r2 in table if r2['source'] == sid and r2.get('cmd')]
            how = ('not running (would match ' + '; '.join(by) + ')') if by else 'not detected on this OS (no known process name here)'
        rows.append(dict(source=sid, program=PROGRAM.get(sid, sid), character=CHARACTER.get(sid, 'generic'), state=a.state if a else '-', how=how))
    return rows
