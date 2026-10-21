#!/usr/bin/env python3
"""Pixel fighters on the Windows taskbar for whatever AI program is in use (at most two at a time).

  python minis.py start          launch the director + both fighter slots (three processes, no console windows)
  python minis.py stop           stop them: only PIDs it recorded itself, after proving each one's exact command line
  python minis.py status         processes, slot assignments, pause state, bus freshness
  python minis.py pause          freeze every fighter on a static frame (plates keep updating)
  python minis.py resume         animate again
  python minis.py plates on|off  show / hide both HUD plates (fixed at the left end of the zone)
  python minis.py demo [kind]    start one bout now (spar | clash | ranged | match); plates keep the real numbers
  python minis.py winners random|decided   how match winners are drawn (decided = biased by the health score)
  python minis.py rival on|off   rival mode: a sleeping partner (or the sparring bot) is woken for a match now and then
  python minis.py flash on|off   white flashes on big hits (off: never a flash, for anyone who dislikes strobing)
  python minis.py forge on|off   desktop weapons in the arena (default on): it grabs its monitor ONCE into RAM to forge weapons
                                 from real screen pixels and never saves it; turn it off before screen-sharing client work
  python minis.py fighters       programs seen + their state, the characters, the current lineup
  python minis.py fighters set a|b <program|character>   pin a program to a side, or give that side's program a look
  python minis.py fighters pin a|b <program>   keep this program on that side (asleep when it is not detected)
  python minis.py fighters auto | reset        both sides back to auto (reset also forgets every look)
  python minis.py pick a|b <program>|auto      alias of `fighters pin` / back to auto for one side
  python minis.py skin <program> <character>|default   draw a program as another character
  python minis.py show [a|b]     bring back a hidden fighter
  python minis.py detect         which known AI programs the sources see right now, and how (names and numbers only)
  python minis.py monitors       list monitors (index, rect, primary) for `arena --monitor N`
  python minis.py arena [--monitor N] [--freeze] [--seconds S] [--seed K]   arena mode (default monitor: the Arena button's)
      [--rounds 1|3|5|endless] [--endless] [--intensity calm|normal|wild] [--no-intro] [--no-outro]   match options (docs/ARENA.md)
  python minis.py arena stop     ask the arena to leave (then force-stop it if it will not)
  python minis.py arena capture <png>   PrintWindow of the arena's OWN window only; refused while --freeze is on or the arena
                                        holds a screen grab for desktop weapons (`forge off` first), and only under qa/ or
                                        the data folder
  python minis.py director       run the director + scoreboard widget in the foreground
  python minis.py run <slot>     run one fighter slot in the foreground (a = left, b = right)
  python minis.py run arena ...  the arena process body (what `arena` launches)
  python minis.py selftest-gui   real-desktop check: draws over the taskbar, survives a taskbar raise   [--keep]
  python minis.py print-startup  print (never run) the commands to start at logon
  python minis.py restart        stop everything, then start again (what the tray's "Restart Taskbar Fighters" runs)
  python minis.py shortcut [--desktop]   Start-menu shortcut "Taskbar Fighters" (then: right-click it in Start > Pin to taskbar)
  python minis.py shortcut remove        delete the shortcut(s) it made (also an old Minis.lnk), only if they run this minis.py
"""
from __future__ import annotations
import argparse, atexit, logging, logging.handlers, os, random, subprocess, sys, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from minis_core import config as cfgmod  # noqa: E402
import minis_platform as plat  # noqa: E402  (backend selection; imports no desktop library)
from minis_core import paths  # noqa: E402  (checkout / PyInstaller / py2app / wheel locations)

logging.getLogger('minis.null').addHandler(logging.NullHandler())       # the default log of injectable parts: silent
SLOTS = ('a', 'b')
LEGACY = ('claude', 'codex')                      # v2 fighters (`run claude|codex`): stop/status still recognise them
ROLES = ('director',) + SLOTS
ARENA = 'arena'                                    # its own process: `run arena --monitor N ...` (argv prefix match)
PYTHONS = {'python.exe', 'pythonw.exe', 'python3.exe', 'python', 'pythonw', 'python3'}


def is_python_name(base):
    """An interpreter's file name: the Windows / generic names above, or python3.N (macOS Homebrew / python.org; the
    python.org framework build shows up as .../Python.app/Contents/MacOS/Python, i.e. 'python')."""
    b = ntpath.basename(str(base)).lower()             # splits on / and \ alike: a Windows path reads right on a Mac too
    return b in PYTHONS or (b.startswith('python3.') and b[8:].isdigit())
DEFAULT_ASSIGN = {'a': {'source': 'claude', 'character': 'claude', 'program': 'Claude Code'},
                  'b': {'source': 'codex', 'character': 'codex', 'program': 'Codex'}}
SYSROOT = os.environ.get('SystemRoot', r'C:\Windows')
import ntpath  # noqa: E402  (Windows paths built the same way on every OS, so the tests read the same everywhere)
TASKKILL = ntpath.join(SYSROOT, 'System32', 'taskkill.exe')


def other(slot):
    return 'b' if slot == 'a' else 'a'


FPS_KEYS = (('fps_active', 1, 60), ('fps_idle', 1, 60), ('arena_fps', 5, 60))


def load_config(path=None, log=None):
    """cfgmod.load() plus two guards: a minis.json that does not parse is logged (it used to be ignored silently), and the
    fps values are clamped (fps 0 divided by zero in the loops)."""
    p = Path(path) if path else cfgmod.ROOT / 'minis.json'
    cfg = cfgmod.load(p)
    problem = None
    if p.exists():
        import json
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                problem = 'minis.json is not a JSON object: ignored, defaults used'
                cfg = dict(cfgmod.DEFAULTS)
        except (OSError, ValueError) as e:
            problem = f'minis.json could not be read ({type(e).__name__}): ignored, defaults used'
    for k, lo, hi in FPS_KEYS:
        try:
            v = float(cfg.get(k, cfgmod.DEFAULTS.get(k, lo)))
        except (TypeError, ValueError):
            v = float(cfgmod.DEFAULTS.get(k, lo))
        cfg[k] = max(lo, min(hi, v))
    if problem:
        (log or get_logger('config')).warning(problem)
        cfg['_config_problem'] = problem
    return cfg


# ------------------------------------------------------------------ logging (small, rotating, never content)
def get_logger(name):
    log = logging.getLogger(f'minis.{name}')
    if not log.handlers:
        try:
            h = logging.handlers.RotatingFileHandler(cfgmod.data_dir() / f'{name}.log', maxBytes=cfgmod.DEFAULTS['log_max_bytes'],
                                                     backupCount=1, encoding='utf-8')
            h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            log.addHandler(h)
        except OSError:
            log.addHandler(logging.NullHandler())
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


def safe_traceback(e):
    """Frames as file:line:function only (no source text), and an OSError's message (which names the file - possibly a
    transcript) reduced to its errno, so a log line can never carry a project or session name."""
    frames = ''.join(f'  {os.path.basename(fr.filename)}:{fr.lineno} in {fr.name}\n' for fr in traceback.extract_tb(e.__traceback__))
    if isinstance(e, OSError):
        msg = f'{type(e).__name__} errno={e.errno} winerror={getattr(e, "winerror", None)}'
    else:
        msg = f'{type(e).__name__}: {str(e)[:200]}'
    return frames + msg


# ------------------------------------------------------------------ process identity
def pid_file(role):
    return cfgmod.data_dir() / f'{role}.pid'


def expected_tail(role):
    return ['director'] if role == 'director' else ['run', role]


def self_argv(*tail):
    """The command that runs this program with `tail`: <python> <ROOT>/minis.py ... from a checkout, or the executable
    itself when frozen (PyInstaller / py2app: there is no minis.py to hand a python)."""
    if paths.frozen():
        return [str(sys.executable)] + list(tail)
    return [str(python_exe()), str(ROOT / 'minis.py')] + list(tail)


BUNDLE_EXES = ('taskbarfighters.exe', 'taskbarfighters-cli.exe')   # the windowed and console launchers of one bundle


def _frozen_argv_is_ours(argv, tail, role, exe=None):
    """A frozen build's child: <this executable, or its sibling launcher in the same bundle folder> then exactly the tail
    (the arena: the tail as a prefix).  A double-click starts TaskbarFighters.exe; `TaskbarFighters-cli.exe stop` must
    still recognise those processes, so both launchers count - only from this very folder."""
    exe = exe or sys.executable
    try:
        mine = os.path.normcase(os.path.normpath(str(exe)))
        theirs = os.path.normcase(os.path.normpath(str(argv[0])))
        same = theirs == mine or (os.path.dirname(theirs) == os.path.dirname(mine)
                                  and os.path.basename(theirs).lower() in BUNDLE_EXES     # normcase only folds case
                                  and os.path.basename(mine).lower() in BUNDLE_EXES)      # on Windows
    except (TypeError, ValueError):
        return False
    rest = list(argv[1:])
    return same and (rest[:len(tail)] == tail if role == ARENA else rest == tail)


def argv_is_ours(argv, role, root=ROOT, frozen=None):
    """Exact argv: <python>, <ROOT>\\minis.py, then `run <slot>` or `director`.  Substrings never count.
    The arena is `run arena` followed by its own options (--monitor N ...), so that role matches on the prefix.
    A frozen build (PyInstaller / py2app) runs <its executable> <tail> instead, and only that form counts there."""
    if not argv:
        return False
    tail = expected_tail(role)
    if paths.frozen() if frozen is None else frozen:
        return _frozen_argv_is_ours(argv, tail, role)
    if role == ARENA:
        if len(argv) < 2 + len(tail) or list(argv[2:4]) != tail:
            return False
    elif len(argv) != 2 + len(tail):
        return False
    if not is_python_name(argv[0]):
        return False
    try:
        if not os.path.isabs(argv[1]):                   # relative paths would resolve against OUR cwd, not the process's
            return False
        script_ok = os.path.normcase(os.path.normpath(argv[1])) == os.path.normcase(str(Path(root) / 'minis.py'))
    except (TypeError, ValueError):
        return False
    return script_ok and (list(argv[2:4]) == tail if role == ARENA else list(argv[2:]) == tail)


def read_pid(role):
    try:
        return int(pid_file(role).read_text().strip())
    except (OSError, ValueError):
        return None


def pid_alive(pid):
    return plat.procs().alive(pid)


def proc_argv(pid):
    """argv of a live process, or None when it cannot be read.  On macOS `ps -o args=` joins argv with spaces, so the
    split is anchored on ROOT/minis.py (a clone path with spaces still compares exactly)."""
    procs = plat.procs()
    try:
        if plat.is_mac():
            return procs.argv(pid, str(ROOT / 'minis.py'))
        return procs.argv(pid)
    except OSError:
        return None


def proc_state(role):
    """-> (status, pid) with status in running | stopped | unverified | foreign."""
    pid = read_pid(role)
    if not pid:
        return 'stopped', None
    if not pid_alive(pid):
        return 'stopped', pid
    argv = proc_argv(pid)
    if not argv:
        return 'unverified', pid
    return ('running' if argv_is_ours(argv, role) else 'foreign'), pid


def running(role):
    st, pid = proc_state(role)
    return pid if st == 'running' else None


def python_exe(windowless=True):
    exe = Path(sys.executable)
    pyw = exe.with_name('pythonw.exe')
    return pyw if windowless and pyw.exists() else exe


DETACHED = 0x00000008 | 0x00000200 | 0x08000000           # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW


def spawn_detached(argv):
    """Start a background process with no console: Windows creation flags (unchanged), or on macOS its own session with
    stdio on /dev/null (it outlives the shell that ran `start`)."""
    if plat.is_windows():
        return subprocess.Popen(argv, creationflags=DETACHED, close_fds=True, cwd=str(ROOT))
    return subprocess.Popen(argv, start_new_session=True, close_fds=True, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def role_argv(role):
    return self_argv(*expected_tail(role))


def launch_role(role):
    """Start one role as a detached, windowless process.  Refused under tests; the argv is proven ours before it runs."""
    if os.environ.get('MINIS_TESTING'):
        return False
    argv = role_argv(role)
    if not argv_is_ours(argv, role):
        return False
    spawn_detached(argv)
    return True


def on_screen(now=None, taskbar=None):
    """-> (line, ok): what the fighters show right now in plain words ('a: Claude Code, b: Sparring bot'), or why nothing
    shows.  Reads pid files, assign.json and control.json; `taskbar` (rect tuple, autohide) is injectable."""
    from minis_core import control, director
    now = time.time() if now is None else now
    why = []
    states = {r: proc_state(r)[0] for r in ROLES}
    if states['director'] != 'running':
        why.append('the director is not running')
    data = director.read_assign()
    parts = []
    for s in SLOTS:
        a = DEFAULT_ASSIGN[s] if data is None else director.slot_assignment(data, s)
        if states[s] != 'running':
            parts.append(f'{s}: (not running)')
            continue
        if a is None:
            parts.append(f'{s}: (nothing to show)')
            continue
        tail = ' asleep' if a.get('dormant') or a.get('bot') else ''
        left = control.hidden_left(s, now=now)
        if left is not None:
            tail += ' (hidden)' if left == float('inf') else f' (hidden {int(left // 60) + 1}m)'
        parts.append(f"{s}: {a.get('program') or a.get('source')}{tail}")
    st = None
    if taskbar is None:
        try:
            shell = plat.shell()
            if getattr(shell, 'taskbar_info', None) is not None:
                st = taskbar_stage(shell, load_config())        # Windows: every edge and auto-hide is laid out (config.stage)
            else:
                taskbar = (shell.taskbar_rect(), shell.taskbar_autohide())
        except Exception:
            taskbar = None
    if st is not None:
        if not st['usable']:
            why.append(f"{st['why']} (fighters hide)")
    elif taskbar is not None:
        rect, autohide = taskbar
        if rect[4] != 3:
            why.append('the taskbar is not at the bottom (fighters hide)')
        elif autohide:
            why.append('the taskbar auto-hides (fighters hide)')
    if control.arena_active(now=now):
        why.append('the arena is up (taskbar fighters wait)')
    if control.paused():
        why.append('animations are paused')
    ok = all(states[r] == 'running' for r in ROLES)
    return ', '.join(parts) + (('  -  ' + '; '.join(why)) if why else ''), ok


def cmd_start(args=None, wait_s=3.0, sleep=time.sleep):
    legacy = [r for r in LEGACY if running(r)]
    if legacy:
        print(f'v2 fighters still running ({", ".join(legacy)}): run `python minis.py stop` first')
        return 1
    started = []
    for role in ROLES:
        st, pid = proc_state(role)
        if st == 'running':
            print(f'{role}: already running (pid {pid})')
            continue
        if launch_role(role):
            started.append(role)
        else:
            print(f'{role}: could not be launched' + (' (refused under tests)' if os.environ.get('MINIS_TESTING') else ''))
    if started:
        sleep(wait_s)                                      # give the windows a moment, then say what is really there
    line, ok = on_screen()
    print(('on screen: ' if ok else 'not everything started: ') + line)
    return 0 if ok else 1


def cmd_stop(args=None, roles=None):
    """Stops only a process whose pid it recorded AND whose exact command line is ours.  Anything else is left alone and
    reported; a command line that cannot be read is reported as 'could not verify', separately."""
    from minis_core import bus, control
    rc = 0
    for role in (roles if roles is not None else ROLES + LEGACY + (ARENA,)):
        st, pid = proc_state(role)
        if st == 'stopped':
            if pid is not None:
                pid_file(role).unlink(missing_ok=True)       # stale file from a dead process
            if role in ROLES:
                print(f'{role}: not running')
            if role == ARENA and pid is not None:
                control.clear_arena_state()
            continue
        if st == 'unverified':
            print(f'{role}: could not verify pid {pid} (command line unreadable) - left alone')
            rc = 1
            continue
        if st == 'foreign':
            print(f'{role}: pid {pid} is not a minis process (pid reused?) - left alone')
            continue
        if not argv_is_ours(proc_argv(pid), role):            # re-check right before killing
            print(f'{role}: pid {pid} changed under us - left alone')
            continue
        r = kill_own(pid, role)
        if r.returncode == 0:
            pid_file(role).unlink(missing_ok=True)
            if role in SLOTS + LEGACY:
                bus.write_gone(role)
            if role == ARENA:
                control.clear_arena_state()
            print(f'{role}: stopped (pid {pid})')
        else:
            print(f'{role}: {"taskkill" if plat.is_windows() else "kill"} failed for pid {pid} (exit {r.returncode})')
            rc = 1
    return rc


def kill_own(pid, role):
    """Kill one process already proven ours.  Windows: taskkill /F (unchanged).  macOS: SIGTERM, then SIGKILL only if the
    pid still runs exactly our argv after the grace period.  -> an object with .returncode (0 = gone)."""
    if plat.is_windows():
        return subprocess.run([TASKKILL, '/PID', str(pid), '/F'], capture_output=True)
    gone = plat.procs().terminate(pid, still_ours=lambda: argv_is_ours(proc_argv(pid), role))
    return subprocess.CompletedProcess([], 0 if gone else 1)


def status_line(now=None):
    """The one-line summary `status` starts with: running or not, who is on which side, and rival mode."""
    from minis_core import control, director
    now = time.time() if now is None else now
    states = {r: proc_state(r)[0] for r in ROLES}
    rival = 'on' if control.rival_on(default=load_config().get('rival', True)) else 'off'
    if not any(v == 'running' for v in states.values()):
        return f'minis is not running (start it with `{prog_name()} start`). Rival mode {rival}.'
    data = director.read_assign()
    sides = []
    for s, side in (('a', 'left'), ('b', 'right')):
        a = DEFAULT_ASSIGN[s] if data is None else director.slot_assignment(data, s)
        if states[s] != 'running':
            sides.append(f'nothing on the {side} (slot {s} is not running)')
        elif a is None:
            sides.append(f'nothing on the {side}')
        else:
            extra = []
            if a.get('bot'):
                extra.append('stand-in')
            elif a.get('dormant'):
                extra.append('asleep')
            if a.get('picked'):
                extra.append('picked')
            if control.hidden_left(s, now=now) is not None:
                extra.append('hidden')
            sides.append(f"{a.get('program') or a.get('source')} on the {side}" + (f" ({', '.join(extra)})" if extra else ''))
    run = 'minis is running' if all(v == 'running' for v in states.values()) else 'minis is partly running'
    return f"{run}: {sides[0]} vs {sides[1]}. Rival mode {rival}" + ('; paused.' if control.paused() else '.')


def cmd_status(args=None):
    from minis_core import bus, control, director
    print(status_line())
    data = director.read_assign()
    now = time.time()
    for role in ROLES + LEGACY:
        st, pid = proc_state(role)
        if role in LEGACY and st == 'stopped':
            continue
        line = f'{role:8s} {st}{" pid %s" % pid if pid else ""}'
        if role in SLOTS + LEGACY:
            b = bus.read(role, raw=True)
            age = None if not b else round(now - float(b.get('ts', 0)), 1)
            line += f'  bus age {age}s state={b and b.get("state")} mode={b and b.get("mode")} anim={b and b.get("anim")}'
        if role in SLOTS:
            a = DEFAULT_ASSIGN[role] if data is None else director.slot_assignment(data, role)
            line += f'  -> {a["program"]} as {a["character"]}' if a else '  -> (no assignment: hidden)'
            if a and a.get('bot'):
                line += '  (sparring bot: stand-in, shown asleep)'
            elif a and a.get('dormant'):
                line += '  (dormant partner: not detected right now, shown asleep)'
        print(line)
    if plat.is_mac():
        st, pid = proc_state('director')
        shown = plat.shell().menubar_icon_shown(pid) if st == 'running' and pid else None
        if shown is False:
            print('menu-bar icon: hidden by macOS (the menu bar is full, or the icon sits behind the notch); right-click a '
                  'fighter for the same controls, or remove a few menu-bar icons (Cmd-drag them out)')
        elif shown:
            print('menu-bar icon: shown')
    if data is None:
        print('assign.json: missing (fighters fall back to a=claude, b=codex)')
    else:
        print(f'assign.json: written {round(now - float(data.get("ts", 0)), 1)}s ago')
    print('animations:', 'PAUSED' if control.paused() else 'running', '| HUD plates:',
          ('on' if control.plates_on() else 'off') + (' (menu bar)' if plat.is_mac() and control.hud_position() == 'menubar' else ''),
          '| winners:', control.winners(), '| flash effects:', 'on' if control.flashes_on() else 'off',
          '| desktop weapons:', 'on' if control.forge_on(default=load_config().get('forge', True)) else 'off')
    lu = control.lineup()
    print(f"lineup: a={lu['a']} b={lu['b']}" + (' | looks: ' + ', '.join(f'{k}->{v}' for k, v in sorted(lu['skins'].items())) if lu['skins'] else ''))
    st, pid = proc_state(ARENA)
    ar = control.arena_state()
    print(f'arena: {st}{" pid %s" % pid if pid else ""}' + (f'  monitor {ar.get("monitor")} phase={ar.get("phase")} round={ar.get("round")} hp={ar.get("hp")}' if ar else ''))
    from minis_core import records
    rec = records.read()
    if rec.get('programs'):
        print('record:', ', '.join(f'{c} {v.get("w", 0)}-{v.get("l", 0)}' for c, v in sorted(rec['programs'].items())))
    return 0


def cmd_pause(args=None):
    from minis_core import control
    ok = control.set_paused(True)
    print('paused' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_resume(args=None):
    from minis_core import control
    ok = control.set_paused(False)
    print('resumed' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_plates(args):
    from minis_core import control
    if args.state in control.HUD_POSITIONS:
        if not plat.is_mac():
            print('plates menubar|dock: macOS only (on Windows the plates live in the taskbar)')
            return 2
        ok = control.set_hud_position(args.state)
        where = 'in the menu bar' if args.state == 'menubar' else 'above the Dock'
        print(f'HUD plates: {where}' if ok else 'could not write control.json')
        return 0 if ok else 1
    ok = control.set_plates(args.state == 'on')
    print(f'HUD plates {args.state}' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_demo(args):
    """One bout right now, for a look.  Only the choreography is forced; the plates keep showing the real state."""
    from minis_core import control
    ok = control.request_demo(args.kind)
    if not ok:
        print('could not write control.json')
        return 1
    if not running('a') or not running('b'):
        print(f'{args.kind} requested, but both fighter slots must be running (`python minis.py start`)')
        return 1
    print(f'{args.kind} requested: the two fighters meet in the middle within a few seconds (if neither is paused)')
    return 0


def cmd_winners(args):
    from minis_core import control
    ok = control.set_winners(args.mode)
    print(f'winners: {args.mode}' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_rival(args):
    from minis_core import control
    ok = control.set_rival(args.state == 'on')
    print(f'rival mode {args.state}' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_flash(args):
    from minis_core import control
    ok = control.set_flashes(args.state == 'on')
    print(f'flash effects {args.state}' if ok else 'could not write control.json')
    return 0 if ok else 1


def cmd_forge(args):
    from minis_core import control
    ok = control.set_forge(args.state == 'on')
    if not ok:
        print('could not write control.json')
        return 1
    print(f'desktop weapons {args.state}' + (' (the arena grabs its monitor into RAM once to forge weapons; it is never saved)'
                                             if args.state == 'on' else ' (no screen grab; a running arena drops its grab within ~2 s)'))
    return 0


def cmd_show(args):
    from minis_core import control
    ok = control.show(getattr(args, 'slot', None))
    print(('shown: ' + (args.slot or 'both')) if ok else 'could not write control.json')
    return 0 if ok else 1


def _fighters_table():
    from minis_core import control, director, lineup
    data = director.read_assign() or {}
    lu = control.lineup()
    chars = lineup.characters()
    print('programs (source id, name, state, look):')
    for r in lineup.programs(data):
        look = lineup.look_of(r['source'], lu, data)
        mark = [f'slot {s}' for s in SLOTS if lu[s] == r['source']]
        on = [f'on {s}' for s in SLOTS if (director.slot_assignment(data, s) or {}).get('source') == r['source']]
        print(f"  {r['source']:11s} {r['label']:11s} {lineup.state_word(r['state']):9s} {lineup.display_of(look, chars):10s}"
              + (f"  [{', '.join(mark + on)}]" if mark or on else ''))
    print('characters: ' + ', '.join(f"{c['id']} ({c['display']})" if c['display'].lower() != c['id'] else c['id'] for c in chars))
    print(f"lineup: a = {lu['a']}, b = {lu['b']}" + ('; looks: ' + ', '.join(f'{k} as {v}' for k, v in sorted(lu['skins'].items())) if lu['skins'] else ''))
    if not data.get('programs'):
        print('(the director has not written a program list yet: states are unknown until `python minis.py start`)')
    return 0


def _pick(slot, name):
    from minis_core import control, director, lineup
    kind, val = lineup.resolve_name(name, director.read_assign())
    if kind == 'auto':
        control.set_pick(slot, 'auto')
        print(f'{slot}: auto')
        return 0
    if kind != 'program':
        print(f'{name!r} is not a program; known: ' + ', '.join(lineup.known_ids(director.read_assign())))
        return 2
    control.set_pick(slot, val)
    print(f'{slot}: {val} (stays on this side; asleep when it is not detected)')
    return 0


def _skin(program, character):
    from minis_core import control, director, lineup
    kind, val = lineup.resolve_name(program, director.read_assign())
    if kind != 'program':
        print(f'{program!r} is not a program; known: ' + ', '.join(lineup.known_ids(director.read_assign())))
        return 2
    if str(character).lower() in ('default', 'auto', 'none'):
        control.set_skin(val, None)
        print(f'{val}: its own character again')
        return 0
    cid = lineup.resolve_character(character)
    if cid is None:
        print(f'{character!r} is not a character; have: ' + ', '.join(lineup.character_ids()))
        return 2
    control.set_skin(val, cid)
    print(f'{val}: drawn as {cid}')
    return 0


def cmd_fighters(args):
    """`fighters` (list), `fighters set a|b <program|character>`, `fighters pin a|b <program>`, `fighters auto|reset`."""
    from minis_core import control, director, lineup
    act = args.action or 'list'
    rest = list(args.rest or [])
    if act == 'list':
        return _fighters_table()
    if act in ('auto', 'reset'):
        control.reset_lineup(skins=act == 'reset')
        print('both sides: auto' + (' (looks forgotten)' if act == 'reset' else ' (looks kept)'))
        return 0
    if act in ('set', 'pin'):
        if len(rest) != 2 or rest[0] not in SLOTS:
            print(f'usage: fighters {act} a|b <{"program|character" if act == "set" else "program"}>')
            return 2
        slot, name = rest
        if act == 'pin':
            return _pick(slot, name)
        data = director.read_assign()
        kind, val = lineup.resolve_name(name, data)
        if kind in ('program', 'auto'):
            return _pick(slot, name)
        if kind == 'character':
            lu = control.lineup()
            src = lu[slot] if lu[slot] != 'auto' else (director.slot_assignment(data, slot) or {}).get('source')
            if not src:
                print(f'slot {slot} shows nothing right now: pin a program first (fighters pin {slot} <program>)')
                return 2
            return _skin(src, val)
        print(f'{name!r} is neither a program nor a character; see `python minis.py fighters`')
        return 2
    print('fighters: list | set a|b <program|character> | pin a|b <program> | auto | reset')
    return 2


def cmd_pick(args):
    return _pick(args.slot, args.program)


def cmd_skin(args):
    return _skin(args.program, args.character)


def cmd_detect(args=None):
    """What the sources layer sees right now, program by program.  Names, states and numbers only: never a window title,
    never a path beyond the executable's file name."""
    from minis_core import sources
    cfg = load_config()
    srcs = sources.Sources(cfg)
    now = time.time()
    srcs.poll(now)                                      # process sources need two polls a second apart for a CPU rate
    time.sleep(1.1)
    rows = sources.describe(cfg, time.time(), srcs)
    w = max(len(r['program']) for r in rows)
    for r in rows:
        print(f"{r['source']:11s} {r['program']:{w}s}  {r['character']:9s} {r['state']:9s} {r['how']}")
    seen = [r for r in rows if r['state'] != '-']
    print(f'{len(seen)} of {len(rows)} known programs seen' + (': ' + ', '.join(r['program'] for r in seen) if seen else ''))
    return 0


def cmd_monitors(args=None):
    shell = plat.shell()
    for m in shell.monitors():
        l, t, r, b = m['rect']
        extra = f"  scale {m['scale']:g}" if m.get('scale') and m['scale'] != 1 else ''
        print(f"{m['index']}: {r - l}x{b - t} at ({l},{t}){'  primary' if m['primary'] else ''}{extra}")
    return 0


def pick_arena_monitor(cfg, mons):
    """The monitor the Arena button / menu item uses: cfg `arena_monitor`, else the one non-primary monitor, else None.
    macOS: with a single display the arena opens on it (click-through except EXIT; Esc leaves)."""
    if cfg.get('arena_monitor'):
        return int(cfg['arena_monitor'])
    if plat.is_mac() and len(mons) == 1:
        return mons[0]['index']
    others = [m['index'] for m in mons if not m['primary']]
    return others[0] if len(others) == 1 else None


def arena_cli_options(args):
    """The arena options the user actually set on the command line (rounds, endless, intensity, seconds, intro, outro),
    for Arena(options=...).  Unset flags are left out, so minis.json "arena" and control.json "arena_opts" still apply."""
    out = {}
    rounds = getattr(args, 'rounds', None)
    if rounds is not None:
        if str(rounds) == 'endless':
            out['endless'] = True
        else:
            out['rounds'] = int(rounds)
    if getattr(args, 'endless', False):
        out['endless'] = True
    if getattr(args, 'intensity', None):
        out['intensity'] = args.intensity
    if getattr(args, 'seconds', None):
        out['seconds'] = float(args.seconds)
    if getattr(args, 'no_intro', False):
        out['intro'] = False
    if getattr(args, 'no_outro', False):
        out['outro'] = False
    return out


def arena_option_argv(options):
    """Arena options back to the child's flags (`run arena ...`); the inverse of arena_cli_options (seconds travels
    separately as --seconds)."""
    options = options or {}
    argv = []
    if options.get('endless'):
        argv.append('--endless')
    if options.get('rounds') is not None:
        argv += ['--rounds', str(int(options['rounds']))]
    if options.get('intensity'):
        argv += ['--intensity', str(options['intensity'])]
    if options.get('intro') is False:
        argv.append('--no-intro')
    if options.get('outro') is False:
        argv.append('--no-outro')
    return argv


def start_arena(monitor, freeze=False, seconds=None, seed=None, options=None):
    """Launch the arena as its own detached process (a crash never takes the taskbar fighters down).
    `seed` fixes the choreography (previews, captures); without it the wall clock seeds the match.
    `options` (arena_cli_options) become the child's --rounds / --endless / --intensity / --no-intro / --no-outro."""
    if os.environ.get('MINIS_TESTING'):                                    # a test run must never put a real arena on the screen
        return 'arena: refused under tests (MINIS_TESTING)', 1
    st, pid = proc_state(ARENA)
    if st == 'running':
        return f'arena: already running (pid {pid})', 1
    argv = self_argv('run', 'arena', '--monitor', str(int(monitor)))
    if freeze:
        argv.append('--freeze')
    if seconds:
        argv += ['--seconds', str(float(seconds))]
    if seed is not None:
        argv += ['--seed', str(int(seed))]
    argv += arena_option_argv(options)
    spawn_detached(argv)
    return f'arena: started on monitor {monitor}' + (' (freeze)' if freeze else ''), 0


class ArenaStopper:
    """Non-blocking `arena stop` for the UI loops (menu, scoreboard): request() asks the arena to leave and returns at
    once; poll(now), called every loop iteration, force-stops it (command line verified) once `grace_s` has passed."""

    def __init__(self, grace_s=4.0):
        self.grace_s = grace_s
        self.deadline = None

    def request(self, now):
        from minis_core import control
        st, pid = proc_state(ARENA)
        if st != 'running':
            control.clear_arena_state()
            return 'arena: not running'
        control.request_arena_stop()
        self.deadline = now + self.grace_s
        return 'arena: asked to leave'

    def poll(self, now):
        if self.deadline is None:
            return None
        if proc_state(ARENA)[0] != 'running':
            from minis_core import control
            control.clear_arena_state()
            self.deadline = None
            return 'arena: stopped'
        if now >= self.deadline:
            self.deadline = None
            rc = cmd_stop(roles=(ARENA,))
            return 'arena: force-stopped' if rc == 0 else 'arena: could not stop'
        return None


def capture_allowed(path):
    """`arena capture` writes only under ROOT/qa or the data folder (never anywhere a typo or a relative path lands)."""
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for base in [b for b in (paths.qa_dir(), cfgmod.data_dir()) if b is not None]:      # never inside an installed bundle
        try:
            if target.is_relative_to(base.resolve()):
                return True
        except (OSError, ValueError):
            pass
    return False


def stop_arena(wait_s=4.0):
    """Ask the arena to play its exit and leave; after `wait_s` force-stop it (only if its command line is ours)."""
    from minis_core import control
    st, pid = proc_state(ARENA)
    if st != 'running':
        control.clear_arena_state()
        return 'arena: not running', 0
    control.request_arena_stop()
    end = time.time() + wait_s
    while time.time() < end:
        if proc_state(ARENA)[0] != 'running':
            control.clear_arena_state()
            return 'arena: stopped', 0
        time.sleep(0.2)
    rc = cmd_stop(roles=(ARENA,))
    return 'arena: force-stopped' if rc == 0 else 'arena: could not stop', rc


MAC_NO_FREEZE = ('arena --freeze is not available on macOS: it would need a screen capture, which needs the Screen Recording '
                 'permission, and Taskbar Fighters never asks for it. Run the arena without --freeze.')


def cmd_arena(args):
    shell = plat.shell()
    if args.action == 'stop':
        msg, rc = stop_arena()
        print(msg)
        return rc
    if args.action == 'capture':
        from minis_core import control
        if not args.path:
            print('arena capture <png>: a path is needed')
            return 2
        if plat.is_mac():
            print('arena capture: Windows only (on macOS reading another process\'s window needs Screen Recording, never requested)')
            return 2
        st = control.arena_state()
        if st and st.get('freeze'):
            print('arena capture: refused while the freeze backdrop is on (it holds a full-monitor grab)')
            return 2
        if st and st.get('screen_pixels', True):
            # desktop weapons are textured with real screen pixels: a capture of the overlay would carry them out of RAM.
            # (An old heartbeat without the key counts as holding pixels: refuse rather than guess.)
            print('arena capture: refused while the arena holds a screen grab for desktop weapons '
                  f'(run `{prog_name()} forge off`, wait 2 s, then capture)')
            return 2
        if not capture_allowed(args.path):
            print(f'arena capture: refused - write under {ROOT / "qa"} or {cfgmod.data_dir()}')
            return 2
        hwnd = shell.find_own_window('MinisArena')
        if not hwnd:
            print('arena capture: no arena window')
            return 1
        im = shell.capture_window(hwnd)
        if im is None:
            print('arena capture: PrintWindow failed')
            return 1
        Path(args.path).parent.mkdir(parents=True, exist_ok=True)
        im.save(args.path)
        print(f'arena capture: {im.size[0]}x{im.size[1]} -> {args.path}')
        return 0
    if args.freeze and plat.is_mac():
        print(MAC_NO_FREEZE)
        return 2
    if args.monitor is None:
        try:
            args.monitor = pick_arena_monitor(load_config(), shell.monitors())       # the same pick as the Arena button
        except Exception:
            args.monitor = None
        if args.monitor is None:
            print('arena: no default monitor (set arena_monitor in minis.json, or pass --monitor N; see `python minis.py monitors`)')
            return 2
    mons = {m['index'] for m in shell.monitors()}
    if args.monitor not in mons:
        print(f'arena: monitor {args.monitor} does not exist; have {sorted(mons)}')
        return 2
    msg, rc = start_arena(args.monitor, args.freeze, args.seconds, getattr(args, 'seed', None), options=arena_cli_options(args))
    print(msg)
    return rc


def quit_all():
    """Right-click "Quit minis": a detached `minis.py stop` (stops the director first, so nothing restarts a slot).  It runs
    in its own process because a slot cannot stop the others and then itself from inside its own loop.  Refused under tests."""
    if os.environ.get('MINIS_TESTING'):
        return False
    spawn_detached(self_argv('stop'))
    return True


def restart_all():
    """Tray "Restart Taskbar Fighters": a detached `minis.py restart` (stop proves every pid ours, then start).  Its own process,
    because it stops the director that asked for it.  Refused under tests."""
    if os.environ.get('MINIS_TESTING'):
        return False
    spawn_detached(self_argv('restart'))
    return True


def cmd_restart(args=None, sleep=time.sleep):
    cmd_stop()
    sleep(1.0)                                             # let the single-instance mutexes go with the processes
    return cmd_start()


# ------------------------------------------------------------------ Start-menu shortcut (a pinnable launcher)
SHORTCUT_NAME = 'Taskbar Fighters.lnk'
OLD_SHORTCUT_NAMES = ('Minis.lnk',)                   # made before the rename: `shortcut remove` still cleans them up
POWERSHELL = os.path.join(SYSROOT, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
PIN_HINT = 'Right-click Taskbar Fighters in Start > Pin to taskbar'


def start_menu_dir():
    base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    return Path(base) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


def desktop_dir():
    """The real Desktop folder (it may be redirected, e.g. into OneDrive)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:      # CSIDL_DESKTOPDIRECTORY
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / 'Desktop'


def shortcut_spec(root=ROOT):
    """What the shortcut holds: pythonw.exe running `"<root>/minis.py" start`, in the repo, with the minis icon."""
    root = Path(root)
    desc = 'Taskbar Fighters - pixel fighters on the taskbar'
    if paths.frozen():                                     # the executable itself, with its own icon
        exe = Path(sys.executable)
        return dict(target=str(exe), arguments='start', workdir=str(exe.parent), icon=f'{paths.icon_path()},0', description=desc)
    return dict(target=str(python_exe(windowless=True)), arguments=f'"{root / "minis.py"}" start', workdir=str(root),
                icon=f'{paths.icon_path()},0', description=desc)          # the checkout's assets/, or the wheel's package


def shortcut_is_ours(target, arguments, root=ROOT):
    """A .lnk is ours only when it runs a python(w).exe on exactly `"<root>/minis.py" start` (frozen: this executable
    with exactly `start`)."""
    if paths.frozen():
        try:
            same = os.path.normcase(os.path.normpath(str(target or ''))) == os.path.normcase(os.path.normpath(sys.executable))
        except (TypeError, ValueError):
            return False
        return same and (arguments or '').strip() == 'start'
    if not target or os.path.basename(str(target)).lower() not in PYTHONS:
        return False
    return os.path.normcase((arguments or '').strip()) == os.path.normcase(shortcut_spec(root)['arguments'])


# values reach PowerShell in environment variables, never spliced into the script text
_PS_WRITE = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:MINIS_LNK);'
             '$s.TargetPath=$env:MINIS_TARGET;$s.Arguments=$env:MINIS_ARGS;$s.WorkingDirectory=$env:MINIS_WORKDIR;'
             '$s.IconLocation=$env:MINIS_ICON;$s.Description=$env:MINIS_DESC;$s.Save()')
_PS_READ = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:MINIS_LNK);'
            '[Console]::Out.Write($s.TargetPath + [char]10 + $s.Arguments)')


def _ps(script, env):
    if os.environ.get('MINIS_TESTING'):
        raise RuntimeError('powershell refused under tests')
    return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True,
                          env=dict(os.environ, **env), creationflags=0x08000000, timeout=30)


def write_shortcut(path, spec):
    r = _ps(_PS_WRITE, dict(MINIS_LNK=str(path), MINIS_TARGET=spec['target'], MINIS_ARGS=spec['arguments'],
                            MINIS_WORKDIR=spec['workdir'], MINIS_ICON=spec['icon'], MINIS_DESC=spec['description']))
    return r.returncode == 0 and Path(path).exists()


def read_shortcut(path):
    """-> (target, arguments) of a .lnk, or None."""
    r = _ps(_PS_READ, dict(MINIS_LNK=str(path)))
    if r.returncode != 0:
        return None
    target, _, args = r.stdout.partition('\n')
    return target.strip(), args.strip()


def cmd_shortcut(args, writer=None, reader=None, dirs=None):
    """`shortcut [--desktop]` writes "Taskbar Fighters.lnk"; `shortcut remove` deletes it (and an old Minis.lnk) while it still runs this minis.py.
    writer(path, spec) -> bool, reader(path) -> (target, arguments) | None and dirs (folders) are injectable for tests."""
    if plat.is_mac() and writer is None and reader is None and dirs is None:
        print(MAC_SHORTCUT_NOTE)
        return 0
    writer, reader = writer or write_shortcut, reader or read_shortcut
    if dirs is None:
        dirs = [start_menu_dir()] + ([desktop_dir()] if args.desktop or args.action == 'remove' else [])
    if args.action == 'remove':
        rc = 0
        for d, name in ((d, n) for d in dirs for n in (SHORTCUT_NAME,) + OLD_SHORTCUT_NAMES):
            p = Path(d) / name
            if not p.exists():
                continue
            got = reader(p)
            if not got or not shortcut_is_ours(*got):
                print(f'{p}: left alone (it does not run {ROOT / "minis.py"} start)')
                rc = 1
                continue
            p.unlink()
            print(f'removed {p}')
        return rc
    spec = shortcut_spec()
    if not paths.icon_path().exists():
        print('note: assets/icon/minis.ico is missing (`python art/build_icon.py` makes it)')
    rc = 0
    for d in dirs:
        p = Path(d) / SHORTCUT_NAME
        if p.exists():
            got = reader(p)
            if not got or not shortcut_is_ours(*got):
                print(f'{p}: exists and is not ours - left alone')
                rc = 1
                continue
        Path(d).mkdir(parents=True, exist_ok=True)
        if writer(p, spec):
            print(f'wrote {p}  ->  {spec["target"]} {spec["arguments"]}')
        else:
            print(f'{p}: could not be written')
            rc = 1
    if rc == 0:
        print(PIN_HINT + '  (Windows lets only you pin a program; minis never pins itself.)')
    return rc


MAC_SHORTCUT_NOTE = ('macOS has no Start menu, so `shortcut` makes nothing here.\n'
                     '  start it:          python minis.py start   (from this folder, inside .venv if you used scripts/setup_mac.sh)\n'
                     '  start at login:    python minis.py autostart on    (writes one LaunchAgent plist; `autostart off` removes it)\n'
                     '  while it runs, its icon sits in the menu bar (left click: fighter select, right click: the menu).')


def cmd_print_startup(args=None):
    if plat.is_mac():
        from minis_mac import launchd
        print('# Not installed for you. `python minis.py autostart on` writes this file; `autostart off` removes it.\n')
        print(f'# {launchd.plist_path()}')
        print(launchd.plist_bytes(sys.executable, ROOT, argv=self_argv('start')).decode('utf-8'))
        print(f'# it takes effect at your next login; to start it now as well:  launchctl load -w "{launchd.plist_path()}"')
        print('# remove later:  python minis.py autostart off   (or delete the file above)')
        return 0
    if paths.frozen():
        exe = Path(sys.executable)
        cmd_q, cmd = f'\\"{exe}\\" start', f'"{exe}" start'
    else:
        exe = Path(sys.executable).with_name('pythonw.exe')
        cmd_q, cmd = f'\\"{exe}\\" \\"{ROOT / "minis.py"}\\" start', f'"{exe}" "{ROOT / "minis.py"}" start'
    print('# Not run for you. Either of these starts the director and both fighter slots at logon:\n')
    print(f'schtasks /Create /SC ONLOGON /TN "MinisFighters" /TR "{cmd_q}" /RL LIMITED /F')
    print('\n# or drop a shortcut to this into  shell:startup :')
    print(cmd)
    print('\n# remove later:  schtasks /Delete /TN "MinisFighters" /F')
    return 0


def cmd_autostart(args, home=None):
    """macOS only: `autostart on|off|status` - the LaunchAgent that runs `minis.py start` at login.  Only on request."""
    if not plat.is_mac():
        print('autostart is the macOS LaunchAgent. On Windows use `python minis.py print-startup` (schtasks) or '
              '`python minis.py shortcut`.')
        return 2
    from minis_mac import launchd
    p = launchd.plist_path(home)
    if args.state == 'status':
        on = p.exists() and launchd.is_ours(p.read_bytes(), ROOT, argv=self_argv('start'))
        print(f'autostart: {"on" if on else "off"} ({p})')
        return 0
    if args.state == 'on':
        ok, msg = launchd.install(sys.executable, ROOT, home, argv=self_argv('start'))
    else:
        ok, msg = launchd.uninstall(ROOT, home, argv=self_argv('start'))
    print(msg)
    return 0 if ok else 1


def _own_process(role):
    """Single instance per role (named mutex / lock file) + pid file removed on exit."""
    return _own_process_with(plat.shell(), role)


def mutex_name(role):
    """One instance per role *per data dir*: the two-process test (its own temp data dir) can run beside live fighters."""
    import zlib
    return f'Local\\minis-{role}-{zlib.crc32(str(cfgmod.data_dir()).lower().encode()):08x}'


def _own_process_with(shell, role):
    mutex, already = shell.make_mutex(mutex_name(role))
    if already:
        return None
    pf = pid_file(role)
    pf.write_text(str(os.getpid()))
    atexit.register(lambda: pf.unlink(missing_ok=True))
    return mutex


# ------------------------------------------------------------------ director process
def arm_fault_log(role):
    """A native crash (ctypes / AppKit) kills a pythonw process without a Python traceback; faulthandler writes the stack
    of every thread to <data>/<role>.fault so the next silent death has a cause."""
    if os.environ.get('MINIS_TESTING'):
        return None
    try:
        import faulthandler
        f = open(cfgmod.data_dir() / f'{role}.fault', 'a', encoding='utf-8')
        f.write(f'--- {time.strftime("%Y-%m-%d %H:%M:%S")} {role} pid {os.getpid()} started\n')
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        return f
    except Exception:
        return None


def cmd_director(args):
    _fault = arm_fault_log('director')  # noqa: F841  (kept open for the life of the process)
    return run_director(plat.shell(), load_config(log=get_logger('director')))


def drive(shell, step, sleep=None):
    """Run a loop body until it returns None.  `step()` -> seconds to wait.  A backend with run_loop (macOS: AppKit must own
    the main thread, so an NSTimer inside NSApplication.run calls the step) drives it; otherwise - Windows and the test
    shells - the plain sleep loop the program has always used."""
    runner = getattr(shell, 'run_loop', None)
    if runner is not None:
        return runner(step)
    while True:
        dt = step()
        if dt is None:
            return 0
        (sleep or time.sleep)(dt)


def run_director(shell, cfg, detector_sources=None, wall=time.time, mono=time.monotonic, max_iterations=None):
    """The director process body: source polling every `director_poll_s` + the scoreboard widget (pumped every 50 ms)."""
    from minis_core import director, sources
    log = get_logger('director')
    mutex = _own_process_with(shell, 'director')
    if mutex is None:
        print('director is already running')
        return 0
    from minis_core import history
    runner = director.Runner(cfg, detector_sources or sources.Sources(cfg))
    hist = history.Recorder()
    board = None
    try:
        if cfg.get('scoreboard', True):
            board = Scoreboard(cfg, shell, wall=wall, mono=mono, log=log)
            board.setup()
    except Exception as e:
        log.error('scoreboard setup failed\n' + safe_traceback(e))
        board = None
    tray = None
    if cfg.get('tray_icon', True) and hasattr(shell, 'make_tray'):        # fake shells (tests) have none: no real icon
        try:
            tray = director_tray(shell, cfg, board, log, wall)
            atexit.register(tray.remove)                   # the finally below covers a normal exit; atexit anything else
        except Exception as e:
            log.error('tray icon setup failed\n' + safe_traceback(e))
            tray = None
    log.info('director started')
    dog = Watchdog(log=log, mono=mono)
    st = dict(errors=0, next_poll=-1e9, next_tip=-1e9, n=0)

    def step():
        """One director iteration -> seconds to wait, or None to stop."""
        now = mono()
        try:
            if now >= st['next_poll']:
                st['next_poll'] = now + cfg['director_poll_s'] + (2.0 if st['errors'] > 20 else 0.0)
                data, acts = runner.step(wall())
                hist.record(acts, wall())
                dog.check(now)
                st['errors'] = 0
            if board is not None and board.step() is None:
                return None
            if tray is not None:
                if board is None and not tray.pump():      # otherwise the board's pump serves the tray window too
                    return None
                if now >= st['next_tip']:
                    st['next_tip'] = now + 1.0
                    tray.step()
        except Exception as e:                        # never die silently: log and keep going
            st['errors'] += 1
            log.error(safe_traceback(e))
        st['n'] += 1
        if max_iterations is not None and st['n'] >= max_iterations:
            return None
        return 0.05 if board is not None or tray is not None else max(0.2, st['next_poll'] - mono())
    try:
        drive(shell, step)
    finally:
        if tray is not None:
            tray.remove()
        if board is not None:
            board.close()
    return 0


def tray_flags(cfg, board):
    """The tray menu's tick state, read fresh each time the menu opens."""
    from minis_core import control
    return dict(paused=control.paused(), plates=control.plates_on(), arena=control.arena_active(),
                rival=control.rival_on(default=cfg.get('rival', True)), flash=control.flashes_on(default=cfg.get('flashes', True)),
                forge=control.forge_on(default=cfg.get('forge', True)), select_ok=board is not None, arena_ok=board is not None)


def tray_choice(choice, flags, board, wall=time.time, log=None, quit_fn=None, restart_fn=None):
    """Run one tray-menu choice through the same calls the scoreboard and the fighters' menu use."""
    from minis_core import control
    from minis_win import tray as T
    log = log or logging.getLogger('minis.null')
    if choice == T.SELECT:
        control.request_picker(SLOTS, now=wall())          # the scoreboard hosts the select screen (one at a time)
    elif choice == T.PAUSE:
        control.set_paused(not flags['paused'])
    elif choice == T.FLASH:
        control.set_flashes(not flags['flash'])
    elif choice == T.FORGE:
        control.set_forge(not flags.get('forge', True))
    elif choice == T.PLATES:
        control.set_plates(not flags['plates'])
    elif choice == T.RIVAL:
        control.set_rival(not flags['rival'])
    elif choice == T.ARENA:
        if board is not None:
            board.act('arena')                             # the scoreboard's Arena button: start it, or ask it to leave
    elif choice == T.BOUT:
        control.request_demo('match', now=wall())          # what the scoreboard's bout button asks for
    elif choice == T.RESTART:
        if not (restart_fn or restart_all)():
            log.info('restart: refused (tests)')
    elif choice == T.QUIT:
        if not (quit_fn or quit_all)():
            log.info('quit: refused (tests)')


def director_tray(shell, cfg, board, log, wall=time.time):
    from minis_core import control, director
    from minis_win import tray as T
    return shell.make_tray(tip=lambda: T.tooltip(director.read_assign() or {}, control.paused()),
                           flags=lambda: tray_flags(cfg, board),
                           on_choice=lambda c, f: tray_choice(c, f, board, wall, log),
                           on_left=lambda: control.request_picker(SLOTS, now=wall()), log=log)


class Watchdog:
    """The director restarts a fighter slot that died.  Only a slot it has itself seen running (so `stop` and a slot
    that never started are left alone); only when the slot's state is 'stopped' (a recorded pid that is alive with a
    foreign or unreadable command line is never touched); the relaunch argv is proven ours first (launch_role); at most
    `max_restarts` per slot in `window_s`, never more often than every `min_gap_s`."""

    def __init__(self, log=None, mono=time.monotonic, every_s=5.0, min_gap_s=30.0, max_restarts=3, window_s=600.0,
                 state=None, launch=None):
        self.log = log or logging.getLogger('minis.null')
        self.mono, self.every_s, self.min_gap_s = mono, every_s, min_gap_s
        self.max_restarts, self.window_s = max_restarts, window_s
        self.state = state or (lambda role: proc_state(role)[0])
        self.launch = launch or launch_role
        self.seen = {s: False for s in SLOTS}
        self.restarts = {s: [] for s in SLOTS}
        self.next = -1e18

    def check(self, now=None):
        now = self.mono() if now is None else now
        if now < self.next:
            return []
        self.next = now + self.every_s
        done = []
        for s in SLOTS:
            st = self.state(s)
            if st == 'running':
                self.seen[s] = True
                continue
            if st != 'stopped' or not self.seen[s]:
                continue
            hist = [t for t in self.restarts[s] if now - t < self.window_s]
            self.restarts[s] = hist
            if len(hist) >= self.max_restarts or (hist and now - hist[-1] < self.min_gap_s):
                continue
            ok = self.launch(s)
            hist.append(now)
            self.log.warning('watchdog: slot %s was not running; restart %s', s, 'launched' if ok else 'refused')
            done.append((s, ok))
        return done


def taskbar_stage(shell, cfg):
    """config.stage() for this shell: the Windows backend describes the taskbar with rects (taskbar_info: edge, auto-hide,
    DPI, monitor, the elements that mark the empty stretch); a shell without it (macOS, the tests' fakes) gives the old
    rect + edge + autohide and is laid out exactly as before."""
    fn = getattr(shell, 'taskbar_info', None)
    if fn is not None:
        return cfgmod.stage(fn(cfg.get('monitor')), cfg)
    l, t, r, b, edge = shell.taskbar_rect()
    info = dict(legacy=True, rect=(l, t, r, b), edge=edge, autohide=shell.taskbar_autohide())
    if edge != 3:
        info['screen'] = shell.screen_size()
    return cfgmod.stage(info, cfg)


def layout_epoch(shell):
    """The backend's layout-change counter (display / DPI / work-area change, Explorer restart), or None without one."""
    fn = getattr(shell, 'layout_epoch', None)
    try:
        return fn() if fn else None
    except Exception:
        return None


def hud_density(shell):
    """How many times finer the HUD (plates, scoreboard) is drawn: macOS draws it at the screen's backing scale (2 on
    Retina, so the text is sharp); Windows and anything without the call: 1, i.e. unchanged."""
    fn = getattr(shell, 'hud_density', None) if plat.is_mac() else None
    try:
        return max(1, min(3, int(fn()))) if fn else 1
    except Exception:
        return 1


class Scoreboard:
    """The right-side widget (minis_core.scoreboard draws it): names + records per program, HP bars / result line /
    status, three buttons.  Lives in the director process; solid to the mouse only on its names, buttons and a visible
    "show" (WM_NCHITTEST), so clicks elsewhere fall through to the taskbar.  It also hosts the fighter-select screen
    (a click on a name, or a "Select fighters..." request a slot's menu writes to control.json)."""

    def __init__(self, cfg, shell, wall=time.time, mono=time.monotonic, log=None, lib=None):
        from minis_core import scoreboard as SB
        self.cfg, self.shell, self.wall, self.mono = cfg, shell, wall, mono
        self.SB = SB
        self.log = log or logging.getLogger('minis.null')
        self.lib = lib
        self.ov = None
        self.g = None
        self.pressed = None
        self.press_t = 0.0
        self.last = dict(draw=-1e9, sig=None, tb=-1e9, top=-1e9, read=-1e9, picker=None)
        self.state = None
        self.clicks = []                                  # (button, mono) for tests
        self.hidden = True
        self.quit = False
        self.select = None                                # the open SelectWindow, or None
        self.stopper = ArenaStopper()
        self.hud_k = 1                                    # HUD pixel density (2 on a Retina Mac)

    def left(self):
        """Logical x of the widget.  Windows: left of the icon cluster (SB.left_x).  macOS, unless scoreboard_x is set: the
        right end of the strip, over the Dock's trash end, instead of the middle of the screen (the roam zone was
        measured on a 2560 px Windows taskbar)."""
        x = self.SB.left_x(self.cfg)
        if plat.is_mac() and self.cfg.get('scoreboard_x') is None:
            try:
                sw = int(self.shell.screen_size()[0]) // max(1, self.g['scale'] if self.g else 1)
                x = max(x, sw - self.SB.W - 12)
            except Exception:
                pass
        return x

    def geometry(self):
        st = taskbar_stage(self.shell, self.cfg)
        cfgmod.apply_stage(self.cfg, st)                  # a detected zone moves the widget with it (left_x reads cfg['zone'])
        top, b = st['band']
        band = b - top
        sc = st['scale']
        y = b - band + max(0, (band - self.SB.H * sc) // 2)
        return dict(scale=sc, y=y, usable=st['usable'], zone=tuple(self.cfg['zone']), autohide=st['autohide'], stage=st)

    def setup(self):
        from minis_core import control
        self.g = self.geometry()
        self.last['epoch'] = layout_epoch(self.shell)
        self.hud_k = hud_density(self.shell)
        self.ov = self.shell.Overlay('minis-scoreboard', self.left() * self.g['scale'], self.g['y'], self.SB.W, self.SB.H,
                                     scale=self.g['scale'], on_event=self.on_event,
                                     on_hittest=lambda x, y: self.SB.hit(x, y, self.state) is not None)
        from minis_core import dump; dump.watch(self.ov, 'scoreboard')   # docs: tools/own_capture.py
        self.ov.show(False)
        req = control.picker_request(now=self.wall())
        self.last['picker'] = req and req.get('id')       # a request from before this process started is not replayed

    def on_event(self, kind, mx, my):
        name = self.SB.hit(mx, my, self.state)
        if kind == 'down' and name:
            self.pressed, self.press_t = name, self.mono()
            self.last['sig'] = None
        elif kind == 'up':
            if self.pressed and self.SB.hit(mx, my, self.state) == self.pressed:
                self.act(self.pressed)
            self.pressed = None
            self.last['sig'] = None

    def act(self, name):
        from minis_core import control
        self.clicks.append((name, self.mono()))
        if name == 'pause':
            control.set_paused(not control.paused())
        elif name == 'bout':
            control.request_demo('match', now=self.wall())
        elif name in ('name_a', 'name_b'):
            self.open_select((name[-1],))
        elif name == 'show':
            control.show()
        elif name == 'arena':
            if control.arena_active():
                self.log.info('%s', self.stopper.request(self.mono()))      # never blocks the loop: poll() finishes it
            else:
                try:
                    mon = pick_arena_monitor(self.cfg, self.shell.monitors())
                except Exception:
                    mon = None
                if mon is None:
                    self.log.info('arena: no monitor chosen (set arena_monitor in minis.json or use `minis.py arena --monitor N`)')
                else:
                    self.log.info('arena: %s', start_arena(mon)[0])
        self.last['read'] = -1e9

    # -------------------------------------------------- the select screen
    def open_select(self, slots):
        """Open (or re-open for other slots) the fighter-select popup above the taskbar."""
        from minis_core import control, director, lineup, select
        from minis_win.select_window import SelectWindow
        if self.select is not None:
            self.select.close()
            self.select = None
        if self.lib is None:
            from minis_core.atlas import Library
            self.lib = Library()
        lu = control.lineup()
        data = director.read_assign() or {}
        rows = select.offer(lineup.programs(data), lu)
        model = select.Model(slots, rows, lu, lineup.characters(), select.Portraits(self.lib), now=self.mono())
        sc = max(2, self.g['scale'] * 2 if self.g else 2)
        centre = (self.cfg['zone'][0] + self.cfg['zone'][1]) // 2 * (self.g['scale'] if self.g else 1)
        if plat.is_mac():                                  # the zone is a Windows-taskbar measurement: centre on the screen
            try:
                centre = int(self.shell.screen_size()[0]) // 2
            except Exception:
                pass
        st = (self.g or {}).get('stage')
        area = None
        if st and getattr(self.shell, 'taskbar_info', None) is not None:     # Windows: above the fighters' band, on its monitor
            area = (st['span'][0], st['span'][1], st['band'][0])
        self.select = SelectWindow(self.shell, model, self.mono, self.select_done, scale=sc, centre_x=centre, area=area)

    def select_done(self, model):
        from minis_core import control
        picks, skins = model.result()
        lu = control.lineup()
        for prog in set(lu['skins']) | set(skins):
            if lu['skins'].get(prog) != skins.get(prog):
                control.set_skin(prog, skins.get(prog))
        for slot in ('a', 'b'):
            if slot in picks:
                control.set_pick(slot, picks[slot])
        self.log.info('select: %s', ', '.join(f'{k}={v}' for k, v in sorted(picks.items())))

    def read_state(self):
        from minis_core import bus, control, director, records
        wall = self.wall()
        assign = director.read_assign()
        if assign is None:
            assign = DEFAULT_ASSIGN
        from minis_core import history
        buses = {s: bus.read(s, now=wall) for s in SLOTS}
        hidden = {s: v for s in SLOTS for v in [control.hidden_left(s, now=wall)] if v is not None}
        return self.SB.Model.state(assign, buses, records.read(), control.paused(), control.arena_active(now=wall), control.winners(),
                                   pressed=self.pressed, spark=history.last_days(7, wall), now=wall, hidden=hidden)

    def step(self):
        """One iteration; None when the window is gone."""
        from minis_core import control
        if not self.ov.pump() or self.quit:
            return None
        now = self.mono()
        if self.select is not None and not self.select.step():
            self.select = None
        msg = self.stopper.poll(now)
        if msg:
            self.log.info('%s', msg)
        if self.pressed and now - self.press_t > 1.5:
            self.pressed = None
        ep = layout_epoch(self.shell)
        if ep != self.last.get('epoch'):                  # display / DPI / taskbar change, Explorer restart: re-lay out now
            self.last['epoch'], self.last['tb'] = ep, -1e9
        if now - self.last['tb'] >= (0.25 if self.g.get('autohide') else 2.0):    # an auto-hide bar is followed closely
            self.last['tb'] = now
            g2 = self.geometry()
            if g2['scale'] != self.g['scale'] or g2['y'] != self.g['y'] or g2.get('zone') != self.g.get('zone'):
                self.ov.set_scale(g2['scale'])
                self.ov.move(self.left() * g2['scale'], g2['y'])
                self.last['sig'] = None
            self.g = g2
            hidden = not g2['usable'] or self.shell.fullscreen_busy() or not self.cfg.get('scoreboard', True)
            if not hidden and not self.ov.visible:
                self.last['sig'] = None
            self.ov.show(not hidden)
            self.hidden = hidden
        if self.ov.visible and now - self.last['top'] >= self.cfg['topmost_tick_ms'] / 1000.0:
            self.ov.reassert_topmost()
            self.last['top'] = now
        if now - self.last['read'] >= 0.25:
            req = control.picker_request(now=self.wall())
            if req and req.get('id') != self.last['picker']:
                self.last['picker'] = req.get('id')
                try:
                    self.open_select(tuple(req.get('slots') or SLOTS))
                except Exception as e:
                    self.log.error('select screen failed\n' + safe_traceback(e))
        if self.ov.visible and now - self.last['read'] >= 0.25:
            self.last['read'] = now
            self.state = self.read_state()
            sig = self.SB.signature(self.state)
            if sig != self.last['sig']:
                self.ov.present(self.SB.render(self.state, k=self.hud_k), x=self.left() * self.g['scale'])
                self.last['sig'] = sig
        elif not self.ov.visible and now - self.last['read'] >= 0.25:
            self.last['read'] = now
        return 0.05

    def close(self):
        try:
            if self.select:
                self.select.close()
            if self.ov:
                self.ov.close()
        except Exception:
            pass


# ------------------------------------------------------------------ fighter slot
class Fighter:
    """One slot's loop.  `step()` is one iteration (testable without a desktop: inject a fake shell / overlay)."""

    def __init__(self, slot, cfg, shell, lib=None, rng=None, wall=time.time, mono=time.monotonic, assign_path=None,
                 control_path=None, bus_root=None, detector_for=None, log=None):
        from minis_core.atlas import Library
        from minis_core import sources
        self.slot, self.cfg, self.shell = slot, cfg, shell
        self.lib = lib or Library()
        self.rng = rng or random.Random()
        self.wall, self.mono = wall, mono
        self.assign_path, self.control_path, self.bus_root = assign_path, control_path, bus_root
        self.detector_for = detector_for or sources.detector_for
        self.log = log or logging.getLogger('minis.null')
        self.size = 64                # fighter_size (64 | 96 | 128), resolved in setup(); the logic always runs in RES 1 px
        self.k = 1.0                  # size / 64: the window shows the RES 1 world k times larger (HD art above 64)
        self.cell = 64
        self.hd = None                # Library(hd=True) for sizes above 64
        z0, z1 = cfg['zone']
        self.win_x = int(z0 - 36)
        self.zone_w = int(z1 + 36 - self.win_x)
        self.st = dict(drag=False, dx=0.0, quit=False, menu=False, drag_t=0.0, drag_x=0.0, drag_v=0.0, drag_vmax=0.0)
        self.arena = False            # the arena process is up: the taskbar fighters hide while it plays
        self.assigned = None          # {'source','character','program'} or None
        self.detector = None
        self.snap = None
        self.partner = None
        self.paused = False
        self.plates = cfg.get('plate', True)                # HUD plates on/off: control.json `plates` (all fighters)
        self.hidden = True
        self.brain = None
        self.ov = None                # the fighter window (sprite + projectile), moves with the fighter
        self.pov = None               # the HUD plate window, fixed at the left end of the zone
        self.hud_k = 1                # HUD pixel density (2 on a Retina Mac)
        self.hud_pos = 'dock'         # macOS: 'dock' or 'menubar' (control.json hud_position); Windows: always the taskbar
        self.g = None
        self.last = dict(tele=-1e9, bus=-1e9, top=-1e9, tb=-1e9, draw=-1e9, sig=None, pbus=-1e9, assign=-1e9, ctl=-1e9, pubkey=None, evkey=None,
                         psig=None, demo=None, notes=0)
        self.gone_written = False
        self.flash = True             # control.json `flashes`: off = no white flash frames on this fighter
        self.ctl_hidden = None        # control.hidden_left() for this slot (hide / hide 1 h, undone by `show`)
        self.stopper = ArenaStopper()

    # -------------------------------------------------- setup
    def geometry(self):
        """Where this side is drawn (config.stage via taskbar_stage): the integer sprite scale, the window's y, the plate's y,
        whether it may show, and the zone (a detected one is put into cfg, so plates, fight zone and brain follow)."""
        st = taskbar_stage(self.shell, self.cfg)
        cfgmod.apply_stage(self.cfg, st)
        t, b = st['band']
        band = b - t
        sc = st['scale']
        py = b - band + max(0, (band - cfgmod.PLATE_H * sc) // 2)          # plate: vertically centred in the taskbar band
        # the window's bottom stays at the taskbar bottom (feet on the same line at every size); a bigger fighter reaches higher.
        # V7.1: the window also reaches headroom_px above the cell, where an airborne fighter (the `air` lift) is drawn
        top = self.cell - cfgmod.feet_drop(self.size) + cfgmod.headroom_px(self.size)
        return dict(scale=sc, y=b - top * sc, bottom=b, usable=st['usable'], plate_y=py, zone=tuple(self.cfg['zone']),
                    autohide=st['autohide'], stage=st)

    def rezone(self, now):
        """The zone moved (the icon cluster grew or shrank, the taskbar moved, another DPI): the brain gets the new fight zone
        and homes - the same split Brain.__init__ makes - a bout in progress is called off (its plan was laid out in the old
        zone), and a fighter now outside its home walks back.  The plates follow on their own (plate_xy reads cfg['zone'])."""
        b = self.brain
        if b is None:
            return
        z0, z1 = self.logic_zone() or cfgmod.fight_zone(self.cfg)
        b.zone = (z0, z1)
        mid, gap = (z0 + z1) / 2.0, self.cfg['gap_px']
        b.home = (z0 + 12, mid - gap) if self.slot == 'a' else (mid + gap, z1 - 12)
        b.home_x = max(b.home[0], min(b.home[1], b.home_x))
        b.abort(now)                                       # (walks back to the new home_x)
        if b.mode == 'home':
            b.x = max(b.home[0], min(b.home[1], b.x))
        self.log.info('layout: zone %s (%s)', list(self.cfg['zone']), self.g['stage'].get('zone_src') if self.g.get('stage') else '-')

    def plate_x(self):
        return cfgmod.plate_left(self.cfg, self.slot) * self.g['scale']

    def plate_xy(self):
        """(x, y) of this side's plate window: the taskbar / Dock strip, or (macOS, `plates menubar`) the menu bar."""
        if self.hud_pos == 'menubar':
            try:
                return self.shell.menubar_plate_origin(self.slot, cfgmod.PLATE_W, cfgmod.PLATE_H, cfgmod.PLATE_SPACING)
            except Exception:
                pass
        return self.plate_x(), self.g['plate_y']

    def resolve_size(self):
        """fighter_size from control.json (`minis.py size N`, the menu) or the config.  Applied at setup; a change restarts."""
        from minis_core import control
        self.size = control.fighter_size(self.control_path, default=self.cfg.get('fighter_size', 128))
        self.k = self.size / 64.0
        self.cell = self.size
        if self.size > 64 and self.hd is None:
            from minis_core.atlas import Library
            self.hd = Library(hd=True)

    def logic_zone(self):
        """Where the brain may stand, in RES 1 px: the fight zone at this fighter size divided by k, so spacing, reach and
        walking keep the art's real proportions at every size and the whole sprite stays clear of the plates and the
        scoreboard (config.fight_zone scales its clearance with the size).  None at 64 px (the brain's own default)."""
        if self.k == 1:
            return None
        z0, z1 = cfgmod.fight_zone(self.cfg, self.size)
        return (z0 / self.k, z1 / self.k)

    def compose(self, v, now):
        """-> (image, x0): one fighter frame in screen-logical px.  64: the RES 1 art as always.  128: the HD atlas (real
        128 px art) with the view mapped to its pixels.  96: the 128 render reduced 3/4 with a box filter - nearest
        neighbour at 3/4 drops every fourth row and with it the HD art's 1 px outline; a box filter keeps every line
        (slightly soft) and the silhouette stays whole."""
        from minis_core import render
        b = self.brain
        hd = self.hd[b.character] if self.hd is not None else None
        if self.k == 1 or hd is None or v['anim'] not in hd.anim:
            return render.compose(b.atlas, b.atlas, v, self.snap, now, self.cfg, show_plate=False)
        im, x0 = render.compose(hd, hd, hd_view(v, hd, b.atlas), self.snap, now, self.cfg, show_plate=False)
        if self.size != 128:
            im, x0 = shrink(im, self.k / 2.0), int(round(x0 * self.k / 2.0))
        return im, x0

    def setup(self):
        from minis_core import control
        from minis_core.brain import Brain
        from minis_core.telemetry import Snapshot
        self.resolve_size()
        self.g = self.geometry()                           # before the brain: a detected zone is its zone from the start
        self.last['epoch'] = layout_epoch(self.shell)
        now = self.mono()
        self._apply_assignment(self._read_assignment(), now, force=True)
        atlas = self.lib[self.assigned['character'] if self.assigned else 'claude']
        self.brain = Brain(self.slot, atlas, self.lib, self.cfg, self.rng, now, zone=self.logic_zone(), record=self._record)
        self.snap = Snapshot(atlas.character, 'sleeping')
        self.ov = self.shell.Overlay(f'minis-{self.slot}', int(self.cfg['zone'][0]), self.g['y'], 64, self.cell, scale=self.g['scale'],
                                     on_event=self.on_event, on_timer=self.menu_tick)
        from minis_core import dump; dump.watch(self.ov, self.slot)   # docs: tools/own_capture.py
        self.ov.show(False)
        if plat.is_mac():
            self.hud_pos = control.hud_position(self.control_path)
        self.pov = self.shell.Overlay(f'minis-{self.slot}-plate', *self.plate_xy(), cfgmod.PLATE_W, cfgmod.PLATE_H,
                                      scale=self.g['scale'], on_event=self.on_plate_event, on_timer=self.menu_tick)
        dump.watch(self.pov, f'{self.slot}-plate')
        self.pov.show(False)
        self.hud_k = hud_density(self.shell)
        if plat.is_mac():                                  # over app windows, not a taskbar: see-through + click-through on hover
            self.pov.fade_on_hover = True                  # (the fighter's own right-click menu stays)
            self.pov.on_hittest = lambda x, y: False
        d = control.demo(self.control_path, now=self.wall())
        self.last['demo'] = d and d.get('id')                # a demo asked for before this process started is not replayed

    def display_name(self):
        """What the plate calls this fighter: the program's name (Claude, Codex, Gemini ...).  A character drawn with the
        generic skin (aider, opencode, a missing atlas) or a look the owner picked (V6 skins) is named after the program it
        stands for, never after the costume."""
        from minis_core import sources
        a = self.assigned or {}
        atlas = self.brain.atlas
        if a.get('skin') and a.get('source'):
            return sources.short_label(a['source'], a.get('program'))
        if atlas.character == 'generic' or (a.get('character') and a['character'] != atlas.character):
            return a.get('program') or atlas.display
        return atlas.display

    def _record(self, winner_char, loser_char, **kw):
        """The brain's match result (it only knows characters), keyed by PROGRAM (V6): the round score says which side
        won; the characters are the fallback.  Written by the left side only (the brain's own rule)."""
        from minis_core import director, records, rounds
        mine = (self.assigned or {}).get('source')
        theirs = (director.slot_assignment(director.read_assign(self.assign_path), other(self.slot)) or {}).get('source')
        wins = ((self.brain.round or {}).get('wins') or {}) if self.brain is not None else {}
        me, op = wins.get(self.slot), wins.get(other(self.slot))
        if mine and theirs:
            if me is not None and op is not None and me != op:
                won = me > op
            elif winner_char != loser_char:
                won = winner_char == self.brain.character
            else:
                return rounds.record_result(winner_char, loser_char)      # cannot tell: the old per-character line
            score = (max(me, op), min(me, op)) if me is not None and op is not None else None
            return records.record(mine if won else theirs, theirs if won else mine, score=score)
        return rounds.record_result(winner_char, loser_char)

    # -------------------------------------------------- assignment + controls
    def _read_assignment(self):
        from minis_core import director
        data = director.read_assign(self.assign_path)
        if data is None:                                  # no director has ever run: the two transcript fighters
            return DEFAULT_ASSIGN[self.slot]
        return director.slot_assignment(data, self.slot)

    def _apply_assignment(self, a, now, force=False):
        if not force and a == self.assigned:
            return
        prev = self.assigned
        self.assigned = a
        self.last['tb'] = -1e9                             # show / hide on the next iteration, not up to 2 s later
        if a is None:
            self.detector = None
            return
        if force or prev is None or prev.get('source') != a['source']:
            self.detector = self.detector_for(a['source'], self.cfg)
            self.last['tele'] = -1e9
        self._swap_skin(now)

    def _swap_skin(self, now):
        """Wear the assigned character.  A change (the director moved on, or the owner picked a fighter) waits until the fighter
        is home and free: swapping the atlas under a bout in progress would cancel it mid-exchange."""
        a, b = self.assigned, self.brain
        if a is None or b is None or b.character == self.lib[a['character']].character:
            return
        if b.bout is not None or b.script is not None or b.pending is not None or b.mode != 'home':
            return
        b.set_atlas(self.lib[a['character']], now)
        self.last['sig'] = self.last['psig'] = None

    # -------------------------------------------------- mouse + menu
    def on_event(self, kind, mx, my):
        now = self.mono()
        b, ov = self.brain, self.ov
        if kind == 'up':
            if self.st['drag']:
                self.st['drag'] = False
                v, vmax = self.st['drag_v'], self.st['drag_vmax']
                shift = False
                try:
                    shift = bool(self.shell.shift_down())
                except Exception:
                    pass
                if shift and abs(v) > 150:
                    b.throw(max(-900.0, min(900.0, v)), now)      # Shift-drag: a short throw
                elif vmax > 600:
                    b.stun(now)                                   # a fast drag leaves it dizzy
            return
        sx = (ov.x / ov.scale + mx) / self.k               # window-relative -> screen x (logical px) -> brain px (RES 1)
        if kind == 'down' and abs(sx - b.x) <= 24 and my / self.k >= 8:
            self.st['drag'], self.st['dx'] = True, sx - b.x
            self.st.update(drag_t=now, drag_x=sx, drag_v=0.0, drag_vmax=0.0)
        elif kind == 'move' and self.st['drag']:
            dt = now - self.st['drag_t']
            if dt > 0.0:
                v = (sx - self.st['drag_x']) / dt
                self.st['drag_v'] = 0.6 * self.st['drag_v'] + 0.4 * v if dt < 0.2 else v
                self.st['drag_vmax'] = max(self.st['drag_vmax'], abs(v))
            self.st['drag_t'], self.st['drag_x'] = now, sx
            b.drag_to(sx - self.st['dx'], now)
        elif kind == 'dbl' and not self.paused:
            b.play('victory', now, loop=False)
        elif kind == 'rclick':
            self.st['menu'] = True                         # opened from the loop, not from inside the window procedure

    def on_plate_event(self, kind, mx, my):
        if kind == 'rclick':                               # the plate only opens the menu; it cannot be dragged
            self.st['menu'] = True

    def menu_tick(self):
        """Runs on a timer while the (modal) menu is open: keeps the bus heartbeat and keep-on-top alive."""
        self._publish(self.wall(), force=True)
        self.ov.reassert_topmost()
        if self.pov is not None and self.pov.visible:
            self.pov.reassert_topmost()

    def open_menu(self):
        from minis_core import control, director, lineup as L
        cp = self.control_path
        flags = dict(paused=control.paused(cp), plates=control.plates_on(cp), winners=control.winners(cp), arena=control.arena_active(),
                     rival=control.rival_on(cp, default=self.cfg.get('rival', True)), flash=control.flashes_on(cp, default=self.cfg.get('flashes', True)),
                     forge=control.forge_on(cp, default=self.cfg.get('forge', True)))
        lu = control.lineup(cp)
        data = director.read_assign(self.assign_path) or {}
        if self.assigned and not director.slot_assignment(data, self.slot):
            data = dict(data, **{self.slot: self.assigned})
        flags['size'] = self.size
        if plat.is_mac():
            flags['hud_pos'] = self.hud_pos                # adds the Plates position submenu
        items, actions = L.fighter_menu(self.slot, data, lu, flags, L.characters())
        choice = self.ov.menu(items)
        self.last['ctl'] = -1e9
        if choice in actions:
            kind, val = actions[choice]
            if kind == 'size':
                if val != self.size and control.set_fighter_size(val, cp):
                    self.log.info('fighter size %s: restarting', val)
                    if not restart_all():                 # every window is rebuilt at the new size
                        self.log.info('restart: refused (tests)')
            elif kind == 'pick':
                control.set_pick(self.slot, val, cp)
            elif kind == 'skin' and (self.assigned or {}).get('source'):
                control.set_skin(self.assigned['source'], val, cp)
        elif choice == L.QUIT_ALL:
            if not quit_all():
                self.log.info('quit: refused (tests)')
        elif choice == L.HIDE:
            control.hide(self.slot, None, cp, now=self.wall())
        elif choice == L.HIDE_1H:
            control.hide(self.slot, 3600, cp, now=self.wall())
        elif choice == L.PLATES:
            control.set_plates(not flags['plates'], cp)
        elif choice in (L.HUD_DOCK, L.HUD_MENUBAR):
            control.set_hud_position('dock' if choice == L.HUD_DOCK else 'menubar', cp)
        elif choice == L.PAUSE:
            control.set_paused(not flags['paused'], cp)
        elif choice == L.FLASH:
            control.set_flashes(not flags['flash'], cp)
        elif choice == L.FORGE:
            control.set_forge(not flags['forge'], cp)
        elif choice == L.BOUT:
            control.request_demo('spar', cp, now=self.wall())
        elif choice == L.MATCH:
            control.request_demo('match', cp, now=self.wall())
        elif choice in (L.WIN_DECIDED, L.WIN_RANDOM):
            control.set_winners('decided' if choice == L.WIN_DECIDED else 'random', cp)
        elif choice == L.ARENA:
            self.toggle_arena()
        elif choice == L.RIVAL:
            control.set_rival(not flags['rival'], cp)
        elif choice == L.SELECT:
            control.request_picker(SLOTS, cp, now=self.wall())       # the director hosts the select screen

    def toggle_arena(self):
        """Menu / scoreboard: start the arena on the configured (or the only other) monitor, or ask it to leave (without
        blocking this loop: the stopper finishes the job from step())."""
        from minis_core import control
        if control.arena_active():
            self.log.info('%s', self.stopper.request(self.mono()))
            return
        try:
            mon = pick_arena_monitor(self.cfg, self.shell.monitors())
        except Exception:
            mon = None
        if mon is None:
            self.log.info('arena: no monitor chosen (set arena_monitor in minis.json or use `minis.py arena --monitor N`)')
            return
        self.log.info('arena: %s', start_arena(mon)[0])

    # -------------------------------------------------- bus
    def _publish(self, wall, force=False):
        from minis_core import bus
        if self.assigned is None:
            if not self.gone_written:
                self.gone_written = bus.write_gone(self.slot, root=self.bus_root, now=wall)
            return
        self.gone_written = False
        pub = self.brain.publish()
        ev = pub['event'] or {}
        evkey = (ev.get('run'), ev.get('seq'))
        key = (pub['state'], pub['mode'], int(pub['x']), pub['facing'], pub['anim'], pub['ctx'], evkey, pub['paused'], pub['character'])
        mono = self.mono()
        if force or evkey != self.last['evkey'] or (mono - self.last['bus'] >= 0.25 and key != self.last['pubkey']) or mono - self.last['bus'] >= 1.0:
            bus.write(self.slot, pub, root=self.bus_root, now=wall)        # event changes go out immediately
            self.last['bus'], self.last['pubkey'], self.last['evkey'] = mono, key, evkey

    # -------------------------------------------------- one iteration
    def step(self):
        """-> seconds to sleep before the next iteration, or None to quit."""
        from minis_core import bus, control, render
        from minis_core.telemetry import Snapshot
        ov, b = self.ov, self.brain
        if not ov.pump() or self.st['quit']:
            return None
        if self.st['menu']:
            self.st['menu'] = False
            self.open_menu()
            if self.st['quit']:
                return None
        now, wall = self.mono(), self.wall()
        msg = self.stopper.poll(now)
        if msg:
            self.log.info('%s', msg)
        if now - self.last['assign'] >= 1.0:
            self.last['assign'] = now
            self._apply_assignment(self._read_assignment(), now)
        self._swap_skin(now)                              # cheap: a pending skin change lands at the next return home
        if now - self.last['ctl'] >= 0.5:
            self.last['ctl'] = now
            p = control.paused(self.control_path)
            if p != self.paused:
                self.paused = p
                b.set_paused(p, now)
                self.last['sig'] = None
            pl = control.plates_on(self.control_path)
            if pl != self.plates:
                self.plates = pl
                self.last['psig'] = None
                self._show_plate()
            if plat.is_mac():
                hp = control.hud_position(self.control_path)
                if hp != self.hud_pos:                    # the menu or `plates menubar|dock`: move the plate right away
                    self.hud_pos = hp
                    self.pov.move(*self.plate_xy())
                    self.last['psig'] = None
            b.winners = control.winners(self.control_path)
            self.flash = control.flashes_on(self.control_path, default=self.cfg.get('flashes', True))
            if hasattr(b, 'flashes'):
                b.flashes = self.flash                     # the engine's own switch (impact frames + white flashes)
            else:
                set_flash_effects(b.fxp, self.flash)
            hl = control.hidden_left(self.slot, self.control_path, now=wall)
            if (hl is None) != (self.ctl_hidden is None):
                self.last['tb'] = -1e9                              # hide / come back on this iteration
            self.ctl_hidden = hl
            b.rival = control.rival_on(self.control_path, default=self.cfg.get('rival', True))
            ar = control.arena_active(now=wall)
            if ar != self.arena:
                self.arena = ar
                self.last['tb'] = -1e9                             # hide / reappear on this very iteration
                if ar and (b.bout or b.script or b.pending):
                    b.abort(now)
            d = control.demo(self.control_path, now=wall)
            if d and d.get('id') != self.last['demo']:
                self.last['demo'] = d.get('id')
                if self.slot == 'a':                       # one side starts it (like every timed bout); the other accepts
                    b.request_demo(d['kind'], now)
        tele_every = 1.0 if (self.assigned or {}).get('source') in ('claude', 'codex') else 2.0
        if self.detector is not None and now - self.last['tele'] >= tele_every:
            self.last['tele'] = now
            acts = self.detector.poll(wall)
            self.snap = acts[0].snapshot() if acts else Snapshot(b.character, 'sleeping')
        if now - self.last['pbus'] >= 0.2:
            self.last['pbus'] = now
            self.partner = bus.read(other(self.slot), root=self.bus_root, now=wall)
            if b.mode == 'home' and b.anim == 'idle' and not self.paused:        # pupils follow the cursor (one GetCursorPos per 0.2 s)
                from minis_core import eyes
                try:
                    cur = self.shell.cursor_pos()
                except Exception:
                    cur = None
                b.eye = eyes.look_at(b.x * self.k * self.g['scale'], self.g['y'] + 20 * self.k * self.g['scale'], cur) if cur else (0, 0)
            elif b.eye != (0, 0):
                b.eye = (0, 0)
        if self.assigned is not None:
            b.tick(now, self.snap, self.partner)
            self.snap.events = []                          # events are consumed by the first tick that sees them
            self._log_bout_notes()
        self._publish(wall)
        ep = layout_epoch(self.shell)
        if ep != self.last.get('epoch'):                   # display / DPI / taskbar change, Explorer restart: re-lay out now
            self.last['epoch'], self.last['tb'] = ep, -1e9
        if now - self.last['tb'] >= (0.25 if self.g.get('autohide') else 2.0):   # an auto-hide bar is followed closely
            self.last['tb'] = now
            g2 = self.geometry()
            rezoned = g2.get('zone') != self.g.get('zone')
            if g2['scale'] != self.g['scale'] or g2['y'] != self.g['y'] or g2['plate_y'] != self.g['plate_y'] or rezoned:
                ov.set_scale(g2['scale'])
                ov.move(ov.x, g2['y'])
                self.g = g2
                if rezoned:
                    self.rezone(now)
                self.pov.set_scale(g2['scale'])
                self.pov.move(*self.plate_xy())
                self.last['sig'] = self.last['psig'] = None
            self.g = g2
            if self.hud_pos == 'menubar':                  # the menu bar moves with the screen (resolution, display change)
                xy = self.plate_xy()
                if xy != (self.pov.x, self.pov.y):
                    self.pov.move(*xy)
            hidden = (self.assigned is None or self.ctl_hidden is not None or not g2['usable'] or self.shell.fullscreen_busy() or self.arena)
            if not hidden and not ov.visible:
                self.last['sig'] = None
            ov.show(not hidden)
            self.hidden = hidden
            self._show_plate()
        if ov.visible and now - self.last['top'] >= self.cfg['topmost_tick_ms'] / 1000.0:
            ov.reassert_topmost()
            if self.pov.visible:
                self.pov.reassert_topmost()
            self.last['top'] = now
        fps = self.cfg.get('fps_fight', 30) if b.mode == 'script' else self.cfg['fps_active']    # V6: 30 fps while a fight script runs
        if ov.visible:
            v = b.view(now)
            sig = (v['anim'], v['frame'], int(v['x']), v['facing'], v['dim'], (v['proj'] or {}).get('x', 0) // 2, b.character,
                   int(now * fps) if v.get('busy') else 0, v.get('eye'))       # effects / banners: redraw at the active rate
            quiet = self.paused or (v['anim'] in ('idle', 'sleep', 'wait', 'dizzy', 'rage', 'type', 'work') and b.mode == 'home' and not v.get('busy'))
            min_dt = 1.0 / (self.cfg['fps_idle'] if quiet else fps)
            stale = (not self.paused) and now - self.last['draw'] > 1.0
            if (sig != self.last['sig'] and now - self.last['draw'] >= min_dt) or stale:
                im, x0 = self.compose(v, now)
                ov.present(im, x=x0 * self.g['scale'])
                self.last['sig'], self.last['draw'] = sig, now
        if self.pov.visible:
            self._draw_plate(now)
        return 0.25 if (self.paused or not ov.visible) else min(0.05, 1.0 / fps)

    def _show_plate(self):
        vis = self.plates and not self.hidden
        if vis and not self.pov.visible:
            self.last['psig'] = None
        self.pov.show(vis)

    def _draw_plate(self, now):
        """The plate window only redraws when what it shows changes (state, the rounded numbers, the blink phase)."""
        from minis_core import render
        snap, name = self.snap, self.display_name()
        psig = (name, self.brain.character, snap.state, render.shown_pct(snap.ctx_pct), render.shown_pct(snap.plan_pct), snap.plan_label,
                render.blink_phase(snap, now))
        if psig != self.last['psig']:
            self.pov.present(render.plate(self.brain.atlas, snap, now, name=name, k=self.hud_k), x=self.plate_xy()[0])
            self.last['psig'] = psig

    def _log_bout_notes(self):
        """Bout start / contact / hit times go to the slot log (ids, times and move names only - never content)."""
        b = self.brain
        new = min(b.bout_log_n - self.last['notes'], len(b.bout_log))
        for what, bout, t, move in list(b.bout_log)[len(b.bout_log) - new:] if new > 0 else ():
            self.log.info('%s %s %.3f %s', what, bout, t, move)
        self.last['notes'] = b.bout_log_n

    def close(self):
        from minis_core import bus
        for w in (self.ov, self.pov):
            try:
                if w:
                    w.close()
            except Exception:
                pass
        bus.write_gone(self.slot, root=self.bus_root, now=self.wall())


_UP_CACHE = {}


def _up(im, m):
    """An effect / banner image scaled m x (nearest, cached by identity: the effect player hands out cached images)."""
    key = (id(im), m)
    got = _UP_CACHE.get(key)
    if got is not None and got[0] is im:
        return got[1]
    out = im.resize((im.width * m, im.height * m), 0)       # Image.NEAREST
    if len(_UP_CACHE) > 512:
        _UP_CACHE.clear()
    _UP_CACHE[key] = (im, out)
    return out


def hd_view(v, hd, base):
    """A brain view (RES 1 px) mapped onto an HD atlas's pixels: positions times hd.res / base.res, effect and banner images
    scaled to match (nearest), the frame index clamped to the HD animation's length."""
    m = max(1, int(round(hd.res / float(max(1, base.res)))))
    out = dict(v)
    out['x'] = v['x'] * m
    n = len(hd.anim[v['anim']]['frames'])
    out['frame'] = min(int(v['frame']), n - 1)
    out['fx'] = [(_up(im, m), lx * m, ty * m) + tuple(rest) for im, lx, ty, *rest in (v.get('fx') or [])]
    if v.get('banner'):
        bim, bx = v['banner']
        out['banner'] = (_up(bim, m), bx * m)
    sx, sy = v.get('shake') or (0, 0)
    out['shake'] = (sx * m, sy * m)
    if v.get('proj'):
        out['proj'] = dict(v['proj'], x=v['proj']['x'] * m)
    return out


def shrink(im, f):
    """Reduce a frame by f (< 1) with a box filter (Pillow premultiplies RGBA, so edges get no dark fringe)."""
    from PIL import Image
    w, h = max(1, int(round(im.width * f))), max(1, int(round(im.height * f)))
    return im.resize((w, h), Image.BOX)


def cmd_size(args):
    """`size 64|96|128`: the taskbar fighters' height.  Saved in control.json; running fighters restart to apply it."""
    from minis_core import control
    if not control.set_fighter_size(args.px):
        print('could not write control.json')
        return 1
    print(f'fighter size: {args.px} px' + (' (HD art)' if args.px > 64 else ''))
    if any(running(r) for r in ROLES):
        print('restarting so every window is rebuilt at the new size ...')
        return cmd_restart()
    return 0


def cmd_run(args):
    _fault = arm_fault_log(args.slot)  # noqa: F841
    shell = plat.shell()
    if args.slot == ARENA:
        if args.monitor is None:
            print('run arena: --monitor N is required')
            return 2
        return run_arena(dict(monitor=args.monitor, freeze=args.freeze, seconds=args.seconds, options=arena_cli_options(args)), shell,
                         load_config(log=get_logger('arena')),
                         seed=getattr(args, 'seed', None))
    return run_slot(args.slot, shell, load_config(log=get_logger(args.slot)))


# ------------------------------------------------------------------ arena process
def grab_monitor(shell, rect, log=None):
    """The ONE screen grab an arena makes (desktop weapons, --freeze), into RAM: an RGBA image of `rect`, or None.
    Windows: PIL's in-memory BitBlt grab (BGRA -> RGBA); macOS: the backend's Quartz grab, only when the Screen Recording
    permission is ALREADY granted (it is never requested).  Never under tests, never written anywhere."""
    if os.environ.get('MINIS_TESTING'):
        return None                                         # a test must never grab the real screen
    try:
        if plat.is_mac():
            fn = getattr(shell, 'grab_screen', None)
            return fn(rect) if fn is not None else None
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=rect, all_screens=True).convert('RGBA')
    except Exception as e:
        if log is not None:
            log.error('screen grab failed (desktop weapons use window shapes)\n' + safe_traceback(e))
        return None


def run_arena(opts, shell, cfg, monitor_rect=None, windows_fn=None, backdrop=None, surface=None, wall=time.time, mono=time.monotonic,
              max_seconds=None, seed=None, screen=None):
    """The arena process body.  Injectable for tests: `monitor_rect` (l, t, r, b) replaces the real monitor, `windows_fn()`
    the window-rect enumeration, `backdrop` a synthetic RAM image, `surface` a headless surface instead of the window,
    `screen` a synthetic RAM image standing in for the desktop-weapons grab.
    The monitor is grabbed at most ONCE, here, into RAM (grab_monitor), for desktop weapons (control.json `forge`, default
    on) and the freeze backdrop; it is handed to the arena, never written anywhere, and dropped when the arena closes.
    A headless run (a `surface`) never grabs: it uses `screen` or forges from window shapes."""
    from minis_core import arena as AR, bus, control, director, forge as FG, fx as fxmod, rounds
    from minis_core.atlas import Library
    log = get_logger('arena')
    if _own_process_with(shell, ARENA) is None:
        print('arena is already running')
        return 0
    mon = int(opts.get('monitor') or 0)
    if monitor_rect is None:
        mons = {m['index']: m for m in shell.monitors()}
        if mon not in mons:
            print(f'run arena: monitor {mon} does not exist')
            return 2
        rect, work = mons[mon]['rect'], mons[mon]['work']
    else:
        rect, work = tuple(monitor_rect), tuple(monitor_rect)
    floor_y = work[3] if work[3] < rect[3] else rect[3]      # the taskbar top when the taskbar is on this monitor
    if opts.get('freeze') and backdrop is None and plat.is_mac():
        log.info('arena: --freeze ignored on macOS (no screen capture)')
        opts = dict(opts, freeze=False)
    forge_on = control.forge_on(default=cfg.get('forge', True))
    windows_fn0 = windows_fn or (lambda: shell.window_rects(exclude=()))
    try:
        wins0 = list(windows_fn0())                         # rects at grab time: a window that moves later is forged from its shape
    except Exception:
        wins0 = []
    size = (rect[2] - rect[0], rect[3] - rect[1])
    grab = screen
    if grab is None and surface is None and (forge_on or (opts.get('freeze') and backdrop is None)):
        grab = grab_monitor(shell, rect, log)               # RAM only, for this process's life
    if grab is not None and grab.size != size:
        from PIL import Image
        grab = grab.resize(size, Image.NEAREST)
    if opts.get('freeze') and backdrop is None and grab is not None:
        backdrop = grab.copy() if forge_on else grab        # the freeze backdrop gets holes punched in: never the forge's copy
    if backdrop is not None and backdrop.size != size:
        from PIL import Image
        backdrop = backdrop.resize(size, Image.NEAREST)
    stage0 = AR.Stage(rect, wins0, floor_y, tuple(cfg.get('arena_min_window_px', (160, 100))))
    scr = FG.ScreenImage(grab if forge_on else None, rects=[(w['id'], w['l'], w['t'], w['r'], w['b']) for w in stage0.windows])
    grab = None                                             # the ScreenImage is the only reference left (plus a freeze backdrop)
    assign = director.read_assign() or DEFAULT_ASSIGN
    slots = {s: director.slot_assignment(assign, s) or DEFAULT_ASSIGN[s] for s in SLOTS}
    lib = Library(hd=True)
    atl = {s: lib[slots[s]['character']] for s in SLOTS}
    names = {s: slots[s].get('program') or atl[s].display for s in SLOTS}
    chars = {s: slots[s].get('source') or atl[s].character for s in SLOTS}     # V6: the record is per program
    buses = {s: bus.read(s, now=wall()) for s in SLOTS}
    scores = {s: rounds.score_of_bus(buses[s]) for s in SLOTS}
    arena = AR.Arena(stage0, atl, fxmod.default(),
                     seed=seed if seed is not None else int(wall() * 1000) % 100000, mode=control.winners(), scores=scores, backdrop=backdrop,
                     names=names, chars=chars, now=mono(), cfg=cfg, record=lambda w, l, where='arena': _arena_record(arena, w, l, where),
                     options=opts.get('options') or None, screen=scr, forge=forge_on)
    own = []
    if surface is None:
        aw = plat.module('arena_window')
        ArenaWindow, VK_ESCAPE = aw.ArenaWindow, aw.VK_ESCAPE
        win = ArenaWindow(rect, on_hittest=arena.hit_exit, on_click=lambda x, y: arena.request_exit(mono()) if arena.hit_exit(x, y) else None,
                          on_key=lambda vk: arena.request_exit(mono()) if vk == VK_ESCAPE else None)
        own = [win.hwnd]
    else:
        win = surface
    comp = AR.Compositor(arena, win)
    windows_fn = windows_fn or (lambda: shell.window_rects(exclude=own))
    started = wall()
    seconds = opts.get('seconds') or max_seconds
    fps = int(cfg.get('arena_fps', 30))
    budget = float(cfg.get('arena_cpu_budget_pct', 10.0))
    log.info('arena started monitor=%s freeze=%s seconds=%s forge=%s pixels=%s', mon, backdrop is not None, seconds, forge_on, scr.available)
    lp = dict(last_win=-1e9, last_hb=-1e9, last_cpu=None, cpu_pct=0.0, fps=fps)
    prof = dict(on=bool(os.environ.get('MINIS_ARENA_PROFILE')), t0=mono(), n=0, tick=0.0, render=0.0)   # FOUND-2: numbers only
    try:
        procs = plat.procs()
    except Exception:
        procs = None

    def step():
        """One arena frame -> seconds until the next, or None when the arena is done."""
        if arena.phase == 'done':
            return None
        t0 = mono()
        try:
            if not win.pump():
                return None
            now = mono()
            if now - lp['last_win'] >= 1.0:
                lp['last_win'] = now
                try:
                    arena.stage.update(windows_fn())
                except Exception as e:
                    log.error(safe_traceback(e))
            paused = control.paused()
            if paused != arena.paused:
                arena.paused = paused
            if control.arena_stop_requested(started) or (seconds and wall() - started >= float(seconds)):
                arena.request_exit(now)
            t1 = time.perf_counter()
            arena.tick(now)
            t2 = time.perf_counter()
            comp.render(now)
            if prof['on']:
                prof['n'] += 1
                prof['tick'] += t2 - t1
                prof['render'] += time.perf_counter() - t2
                if now - prof['t0'] >= 5.0:
                    st_ = getattr(win, 'stats', None) or {}
                    n = max(1, prof['n'])
                    log.info('arena profile: %d frames %.1f fps, tick %.2f ms, render %.2f ms (upload %.2f ms, tiles %.1f up / %.1f '
                             'skipped per frame), cpu %.1f%%', n, n / (now - prof['t0']), prof['tick'] / n * 1e3, prof['render'] / n * 1e3,
                             st_.get('upload_s', 0.0) / n * 1e3, st_.get('uploaded', 0) / n, st_.get('skipped', 0) / n, lp['cpu_pct'])
                    prof.update(t0=now, n=0, tick=0.0, render=0.0)
                    if st_:
                        st_.update(uploaded=0, skipped=0, upload_s=0.0, frames=0)
            if now - lp['last_hb'] >= 1.0:
                lp['last_hb'] = now
                st = arena.state()
                control.write_arena_state(dict(st, active=True, pid=os.getpid(), monitor=mon, fps=lp['fps'], cpu_pct=round(lp['cpu_pct'], 1),
                                               freeze=backdrop is not None), now=wall())   # st carries `freeze` too: ours wins
                if procs is not None:
                    tm = procs.times(os.getpid())
                    if tm and lp['last_cpu'] is not None:
                        lp['cpu_pct'] = (tm[1] - lp['last_cpu'][0]) / max(1e-3, wall() - lp['last_cpu'][1]) * 100.0
                        if lp['cpu_pct'] > budget and lp['fps'] > 20:
                            lp['fps'] = 20
                            log.info('arena: cpu %.1f%% over budget, 20 fps', lp['cpu_pct'])
                    if tm:
                        lp['last_cpu'] = (tm[1], wall())
        except Exception as e:
            log.error(safe_traceback(e))
            time.sleep(0.1)
        return max(0.0, 1.0 / lp['fps'] - (mono() - t0))
    try:
        drive(shell if surface is None else None, step)
    finally:
        try:
            control.clear_arena_state()
        finally:
            win.close()
        del backdrop
        arena.backdrop = None
        arena.forge.purge()                                 # the desktop-weapons grab and everything made from it leave RAM
        log.info('arena stopped: %s', arena.state())
    return 0


def _arena_record(arena, winner, loser, where='arena'):
    """The arena's match result, keyed by program (its `chars` are source ids), with the round score."""
    from minis_core import records
    side = {v: k for k, v in arena.chars.items()}
    w = getattr(arena, 'wins', {}) or {}
    score = (w.get(side.get(winner), 0), w.get(side.get(loser), 0)) if side.get(winner) and side.get(loser) else None
    return records.record(winner, loser, where=where, score=score)


def set_flash_effects(fxp, on):
    """Flash effects off (`minis.py flash off`, the menu): the effect player reports no white flash at all, so neither the
    taskbar fighter nor the arena ever whitens a frame.  Done from outside the engine by shadowing EffectPlayer.flash on
    this one instance; back on removes the shadow."""
    if on:
        fxp.__dict__.pop('flash', None)
    elif 'flash' not in fxp.__dict__:
        fxp.flash = lambda now: 0.0


def run_slot(slot, shell, cfg, detector_for=None):
    """The slot process body.  `shell` and `detector_for` are injectable so tests/two_process_harness.py can run real
    slot processes headless against fake sources."""
    log = get_logger(slot)
    if _own_process_with(shell, slot) is None:
        print(f'slot {slot} is already running')
        return 0
    f = Fighter(slot, cfg, shell, log=log, detector_for=detector_for)
    try:
        f.setup()
    except Exception as e:
        log.error('setup failed\n' + safe_traceback(e))
        raise
    log.info('slot %s started', slot)
    st = dict(errors=0)

    def step():
        try:
            dt = f.step()
            st['errors'] = 0
        except Exception as e:                    # one bad frame must not end the process, and must not pass silently
            st['errors'] += 1
            log.error(safe_traceback(e))
            dt = 2.0 if st['errors'] > 20 else 0.25
        return dt
    try:
        drive(shell, step)
    finally:
        f.close()
        log.info('slot %s stopped', slot)
    return 0


# ------------------------------------------------------------------ real-desktop self-test
def diff_mask(a, c, threshold=24):
    """Binary mask of changed pixels: what the fighters drew, never the taskbar's own pixels or button titles."""
    from PIL import ImageChops
    return ImageChops.difference(a.convert('RGB'), c.convert('RGB')).convert('L').point(lambda v: 255 if v > threshold else 0)


def count(mask, region=None):
    if region:
        mask = mask.crop(region)
    h = mask.convert('L').histogram()
    return sum(h) - h[0]


def cmd_selftest(args):
    """Real-desktop check.  Refuses unless the taskbar is at the bottom and <= 96 px high; captures only the taskbar rows
    of the roam zone, keeps nothing but thresholded difference masks, and restores whatever was running before.
    On macOS: selftest_mac (no capture at all - it reports window frames)."""
    if plat.is_mac():
        return selftest_mac(args)
    from PIL import ImageGrab, Image, ImageDraw
    from minis_win import shell
    from minis_core import director
    cfg = load_config()
    l, t, r, b, edge = shell.taskbar_rect()
    if edge != 3 or b - t > 96 or shell.taskbar_autohide():
        print(f'selftest-gui: refused (taskbar edge={edge}, band={b - t}px, autohide={shell.taskbar_autohide()}); needs a bottom taskbar <= 96 px')
        return 2
    was = {role: bool(running(role)) for role in ROLES}
    z0, z1 = cfg['zone']
    bbox = (int(z0 - 36), t, int(z1 + 36), b)
    ok, res = False, {}
    try:
        cmd_stop()
        time.sleep(0.8)
        bare = ImageGrab.grab(bbox=bbox, all_screens=False)
        cmd_start()
        time.sleep(8.0)
        vis = ImageGrab.grab(bbox=bbox, all_screens=False)
        shell.raise_taskbar()
        time.sleep(0.05)
        raised = ImageGrab.grab(bbox=bbox, all_screens=False)
        time.sleep(0.8)
        after = ImageGrab.grab(bbox=bbox, all_screens=False)
        masks = [diff_mask(bare, im) for im in (vis, raised, after)]
        del vis, raised, after, bare                      # raw captures are never written anywhere
        w, h = masks[0].size
        assigned = {s: director.slot_assignment(director.read_assign(), s) for s in SLOTS}
        res = dict(visible=count(masks[0]), visible_left=count(masks[0], (0, 0, w // 2, h)), visible_right=count(masks[0], (w // 2, 0, w, h)),
                   raised_before_tick=count(masks[1]), after_raise_tick=count(masks[2]),
                   assigned={s: (a or {}).get('character') for s, a in assigned.items()})
        ok = res['visible'] > 300 and res['after_raise_tick'] > 300
        if assigned['a']:
            ok = ok and res['visible_left'] > 80
        if assigned['b']:
            ok = ok and res['visible_right'] > 80
        comp = Image.new('L', (w, h * 3 + 12), 64)
        for i, m in enumerate(masks):
            comp.paste(m, (0, i * (h + 6)))
        out = (paths.qa_dir() or cfgmod.data_dir()) / 'gui-mask.png'
        out.parent.mkdir(exist_ok=True)
        comp.save(out)
        print(res)
        print('selftest-gui:', 'PASS' if ok else 'FAIL', '-> difference masks (fighters running / right after a raise / after the tick):', out)
    finally:
        if not args.keep:
            if not any(was.values()):
                cmd_stop()
            elif not all(was[r] for r in ROLES):
                cmd_stop()
                print('note: only some processes were running before; all were stopped - run `minis.py start` to restore')
    return 0 if ok else 1


def selftest_mac(args, shell=None, seconds=5.0, out=print):
    """macOS real-desktop check without any screen capture: two fighter windows (Claude, Codex idle frames) stand on the Dock
    strip for `seconds`, then the frames AppKit really gave them are compared with what was asked for.  It opens its own two
    windows (a running Taskbar Fighters is left alone) and closes them again."""
    from minis_core import control
    from minis_core.atlas import Library
    shell = shell or plat.shell()
    cfg = load_config()
    l, t, r, b, edge = shell.taskbar_rect()
    sc = cfgmod.ui_scale(max(24, b - t))
    size = control.fighter_size(default=cfg.get('fighter_size', 128))       # the art the real fighters use (64 | 96 | 128)
    lib = Library(hd=size > 64)
    z0, z1 = cfgmod.fight_zone(cfg)
    wins, ok = [], True
    try:
        for i, (char, facing) in enumerate((('claude', 1), ('codex', -1))):
            img = lib[char].frame_image('idle', 0, facing)
            if size == 96:
                img = shrink(img, 0.75)                                      # the same box-filter reduction Fighter.compose uses
            x = int(z0 + (z1 - z0) * (0.35 if i == 0 else 0.65)) * sc
            y = b - img.height * sc
            ov = shell.Overlay(f'minis-selftest-{char}', x, y, img.width, img.height, scale=sc)
            ov.present(img, x=x)
            wins.append((char, (x, y, x + img.width * sc, y + img.height * sc), ov))
        out(f'selftest-gui (macOS): strip {(l, t, r, b)} (bottom = Dock top / visible-frame bottom), sprite scale {sc}, '
            f'fighter size {size} px; '
            f'showing two fighters for {seconds:g} s ...')
        shell.spin(seconds)
        for char, want, ov in wins:
            got = tuple(ov.actual_rect())
            vis = bool(ov.panel.isVisible())
            close = all(abs(a - c) <= 1 for a, c in zip(want, got))
            on_strip = abs(got[3] - b) <= 1
            ok = ok and vis and close and on_strip
            out(f'  {char:6s} asked {want} got {got} visible={vis} level={int(ov.panel.level())} '
                f'{"OK" if vis and close and on_strip else "MISMATCH"}')
    except Exception as e:
        ok = False
        out(f'  error: {type(e).__name__}: {redact(str(e))[:200]}')
    finally:
        for _, _, ov in wins:
            try:
                ov.close()
            except Exception:
                pass
    out('selftest-gui: ' + ('PASS' if ok else 'FAIL') + ' (no screenshot was taken; positions come from the windows themselves)')
    return 0 if ok else 1


# ------------------------------------------------------------------ doctor
ISSUES_URL = 'https://github.com/mrktchris/taskbar-fighters/issues'


def redact(text, home=None):
    """The home folder becomes ~ (doctor output is meant to be pasted publicly)."""
    s = str(text)
    home = str(home if home is not None else Path.home())
    if len(home) > 3:
        s = s.replace(home, '~')
    return s


def _version(mod_name, attr='__version__'):
    try:
        import importlib
        m = importlib.import_module(mod_name)
        return str(getattr(m, attr, '?'))
    except Exception as e:
        return f'missing ({type(e).__name__})'


MAC_GRANT = ('System Settings > Privacy & Security > Screen & System Audio Recording, turn on the app you start Taskbar Fighters '
             'from (Terminal, iTerm, or the Python that runs it), then restart Taskbar Fighters')


def forge_report(shell):
    """One doctor line on desktop weapons: on/off, and on macOS whether real pixels are possible (Screen Recording is only
    ever checked with CGPreflightScreenCaptureAccess, never requested)."""
    from minis_core import control
    try:
        on = control.forge_on(default=load_config().get('forge', True))
    except Exception:
        on = True
    if not on:
        return 'desktop weapons: off (`python minis.py forge on` to turn them on)'
    if plat.is_mac():
        ok = None
        try:
            ok = shell.screen_capture_allowed() if shell is not None and hasattr(shell, 'screen_capture_allowed') else None
        except Exception:
            ok = None
        if ok:
            return ('desktop weapons: on, from real screen pixels (Screen Recording is granted; the arena grabs its display into '
                    f'RAM once and never saves it; `{prog_name()} forge off` before screen-sharing)')
        return ('desktop weapons: on, from window SHAPES (Screen Recording is not granted, and Taskbar Fighters never asks for it). '
                'For real pixels: ' + MAC_GRANT)
    return ('desktop weapons: on (the arena grabs its monitor into RAM once to forge weapons from real pixels and never saves it; '
            f'`{prog_name()} forge off` before screen-sharing or recording)')


def cmd_doctor(args=None, shell=None, probe=None, describe=None, out=print):
    """One report to paste to an AI agent or an issue: versions, backend, geometry, data dir, detected programs, and a
    real test window.  Names and numbers only; the home folder is shown as ~; no window titles; nothing is written."""
    import platform as pyplat
    checks = []
    headless = bool(getattr(args, 'headless', False))

    def check(name, ok, detail='', soft=False):
        """soft: under --headless a desktop check that cannot run is reported, not failed (CI has no GUI session)."""
        if soft and headless and not ok:
            out(f'  [skip] {name}' + (f': {redact(detail)}' if detail else '') + ' (headless)')
            return
        checks.append((name, bool(ok)))
        out(f'  [{"ok" if ok else "FAIL"}] {name}' + (f': {redact(detail)}' if detail else ''))

    out('Taskbar Fighters doctor')
    osname = plat.current()
    mac_ver = pyplat.mac_ver()[0] if osname == 'mac' else ''
    out(f'  os: {pyplat.system()} {mac_ver or pyplat.release()} ({pyplat.machine()})')
    out(f'  python: {pyplat.python_version()} ({redact(sys.executable)})')
    out(f'  Pillow: {_version("PIL")}')
    if osname == 'mac':
        out(f'  PyObjC: {_version("objc")}')
    out(f'  backend: {plat.label()}')
    out(f'  code: {redact(ROOT)}')
    out(f'  data dir: {redact(cfgmod.data_dir())}')
    check('python 3.12+', sys.version_info >= (3, 12), pyplat.python_version())
    if osname == 'mac':
        try:
            major = int((mac_ver or '0').split('.')[0])
        except ValueError:
            major = 0
        check('macOS 13+', major >= 13, mac_ver or 'unknown')
    check('Pillow', not _version('PIL').startswith('missing'))
    if shell is None:
        try:
            shell = plat.shell()
        except Exception as e:
            check('desktop backend loads', False, f'{type(e).__name__}: {str(e)[:300]}')   # importing needs no display: always a FAIL
            shell = None
    if shell is not None:
        check('desktop backend loads', True, plat.label())
        if plat.is_mac() and hasattr(shell, 'MinisView'):
            out(f'  AppKit classes: {shell.MinisPanel.__name__}, {shell.MinisView.__name__} defined')
        try:
            sw, sh = shell.screen_size()
            l, t, r, b, edge = shell.taskbar_rect()
            mons = shell.monitors()
            out(f'  screen: {sw}x{sh}, {len(mons)} monitor(s): ' + ', '.join(
                f"{m['index']}={m['rect'][2] - m['rect'][0]}x{m['rect'][3] - m['rect'][1]}" + (f"@{m['scale']:g}x" if m.get('scale') else '')
                for m in mons))
            if osname == 'mac' and hasattr(shell, 'dock_info'):
                d = shell.dock_info()
                out(f"  dock: {d['dock']}; fighter strip {d['rect']} (fighters stand on y={d['rect'][3]})")
            else:
                out(f'  taskbar: {(l, t, r, b)} edge={edge} autohide={shell.taskbar_autohide()}')
            if getattr(shell, 'taskbar_info', None) is not None:
                cfg = load_config()
                st = taskbar_stage(shell, cfg)
                cfgmod.apply_stage(cfg, st)
                aware = shell.dpi_awareness() if hasattr(shell, 'dpi_awareness') else '?'
                out(f"  dpi: {st['dpi'] * 100:g}% (awareness {aware}); sprite scale {st['scale']} (integer: crisp)")
                where = ('taskbar band' if st['layout'] == 'taskbar' else 'strip at the bottom of the work area') + f" y {st['band']}"
                out(f"  stage: edge={st['edge']}{' auto-hide' + (' (shown now)' if st['revealed'] else ' (hidden now)') if st['autohide'] else ''}; "
                    f"{where}; {'shown' if st['usable'] else 'hidden: ' + st['why']}")
                out(f"  zone: {list(cfg['zone'])} logical px ({st['zone_src']}"
                    + (f", from {st['parts_src']} element rects" if st['zone_src'] == 'auto' and st['parts_src'] else '')
                    + f"; screen x {int(cfg['zone'][0]) * st['scale']}-{int(cfg['zone'][1]) * st['scale']})")
                b, t = st['band'][1], st['band'][0]
            check('screen geometry', sw > 0 and sh > 0 and b > t, f'band {b - t} high, sprite scale {cfgmod.ui_scale(max(24, b - t))}')
        except Exception as e:
            check('screen geometry', False, f'{type(e).__name__}: {str(e)[:200]}', soft=True)
        if headless:
            out('  [skip] test overlay window (headless)')
        else:
            try:
                ok, detail = (probe or getattr(shell, 'probe_overlay', None) or (lambda: _probe_overlay_generic(shell)))()
                check('test overlay window', ok, detail)
            except Exception as e:
                check('test overlay window', False, f'{type(e).__name__}: {str(e)[:200]}')
    out('  ' + forge_report(shell))
    try:
        from minis_core import sources
        cfg = load_config()
        rows = (describe or (lambda: sources.describe(cfg, time.time())))()
        seen = [r for r in rows if r['state'] != '-']
        out(f'  AI programs seen: {len(seen)} of {len(rows)}' + (': ' + ', '.join(f"{r['program']} ({r['state']})" for r in seen) if seen else ''))
        check('program detection runs', True)
    except Exception as e:
        check('program detection runs', False, f'{type(e).__name__}: {str(e)[:200]}')
    try:
        st = {r: proc_state(r)[0] for r in ROLES}
        out('  running now: ' + ', '.join(f'{r}={s}' for r, s in st.items()))
    except Exception as e:
        out(f'  running now: unknown ({type(e).__name__})')
    bad = [n for n, ok in checks if not ok]
    out(('PASS' if not bad else 'FAIL') + f': {len(checks) - len(bad)} of {len(checks)} checks passed' + (f' (failed: {", ".join(bad)})' if bad else ''))
    out(f'Paste this output to your AI agent, or into an issue at {ISSUES_URL}')
    return 0 if not bad else 1


def _probe_overlay_generic(shell, seconds=1.0):
    """Windows: open a tiny transparent overlay for a second, pump it, close it."""
    from PIL import Image
    ov = shell.Overlay('minis-doctor', 40, 40, 8, 8)
    try:
        ok = ov.present(Image.new('RGBA', (8, 8), (255, 0, 0, 0)))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ov.pump()
            time.sleep(0.05)
        return bool(ok), 'layered window created, drawn and closed'
    finally:
        ov.close()


def add_arena_option_flags(p):
    """The match options shared by `arena` and its child `run arena` (docs/ARENA.md, Options)."""
    p.add_argument('--rounds', choices=('1', '3', '5', 'endless'), default=None, help='best of 1, 3 or 5, or endless')
    p.add_argument('--endless', action='store_true', help='free-for-all: rounds continue until stopped, nothing recorded')
    p.add_argument('--intensity', choices=('calm', 'normal', 'wild'), default=None, help='how much destruction and effects')
    p.add_argument('--no-intro', action='store_true', help='skip the VS card before round 1')
    p.add_argument('--no-outro', action='store_true', help="skip the winner's pose on the highest window")


def prog_name():
    """What --help calls this program: `python minis.py` in a checkout, `taskbar-fighters` for a pip install, the
    executable's own name in a frozen build."""
    if paths.frozen():
        return Path(sys.executable).name
    base = Path(sys.argv[0] if sys.argv and sys.argv[0] else 'minis.py').name.lower()
    return 'taskbar-fighters' if base.startswith('taskbar-fighters') else 'python minis.py'


def main(argv=None):
    ap = argparse.ArgumentParser(prog=prog_name(), description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, fn in (('start', cmd_start), ('stop', cmd_stop), ('status', cmd_status), ('pause', cmd_pause), ('resume', cmd_resume),
                     ('print-startup', cmd_print_startup), ('director', cmd_director), ('restart', cmd_restart)):
        sub.add_parser(name).set_defaults(fn=fn)
    r = sub.add_parser('run')
    r.add_argument('slot', choices=SLOTS + (ARENA,))
    r.add_argument('--monitor', type=int, default=None)
    r.add_argument('--freeze', action='store_true')
    r.add_argument('--seconds', type=float, default=None)
    r.add_argument('--seed', type=int, default=None)
    add_arena_option_flags(r)
    r.set_defaults(fn=cmd_run)
    w = sub.add_parser('winners', help='how match winners are drawn')
    w.add_argument('mode', choices=('decided', 'random'))
    w.set_defaults(fn=cmd_winners)
    rv = sub.add_parser('rival', help='rival mode: a sleeping partner is woken for a match now and then')
    rv.add_argument('state', choices=('on', 'off'))
    rv.set_defaults(fn=cmd_rival)
    sub.add_parser('detect', help='which known AI programs the sources see right now, and how').set_defaults(fn=cmd_detect)
    fl = sub.add_parser('flash', help='white flashes on big hits on or off')
    fl.add_argument('state', choices=('on', 'off'))
    fl.set_defaults(fn=cmd_flash)
    fg = sub.add_parser('forge', help='desktop weapons in the arena on or off (on: one RAM-only screen grab per arena)')
    fg.add_argument('state', choices=('on', 'off'))
    fg.set_defaults(fn=cmd_forge)
    sh = sub.add_parser('show', help='bring back a hidden fighter')
    sh.add_argument('slot', nargs='?', default=None, choices=SLOTS)
    sh.set_defaults(fn=cmd_show)
    fi = sub.add_parser('fighters', help='list programs, characters and the lineup; set / pin / auto / reset')
    fi.add_argument('action', nargs='?', default='list', choices=('list', 'set', 'pin', 'auto', 'reset'))
    fi.add_argument('rest', nargs='*')
    fi.set_defaults(fn=cmd_fighters)
    pk = sub.add_parser('pick', help='alias of `fighters pin`: keep a program on side a or b, or auto')
    pk.add_argument('slot', choices=SLOTS)
    pk.add_argument('program')
    pk.set_defaults(fn=cmd_pick)
    sk = sub.add_parser('skin', help='draw a program as another character (or default)')
    sk.add_argument('program')
    sk.add_argument('character')
    sk.set_defaults(fn=cmd_skin)
    sub.add_parser('monitors', help='list monitors for arena --monitor N').set_defaults(fn=cmd_monitors)
    sc = sub.add_parser('shortcut', help='Start-menu shortcut "Taskbar Fighters" (then pin it yourself); `remove` deletes it')
    sc.add_argument('action', nargs='?', default='create', choices=('create', 'remove'))
    sc.add_argument('--desktop', action='store_true', help='also put one on the Desktop')
    sc.set_defaults(fn=cmd_shortcut)
    ar = sub.add_parser('arena', help='arena mode: fighters break out onto a whole monitor')
    ar.add_argument('action', nargs='?', default='start', choices=('start', 'stop', 'capture'))
    ar.add_argument('path', nargs='?', default=None)
    ar.add_argument('--monitor', type=int, default=None, help='default: the Arena button\'s pick (arena_monitor, else the one other monitor)')
    ar.add_argument('--freeze', action='store_true', help='snapshot the monitor into RAM as the stage backdrop')
    ar.add_argument('--seconds', type=float, default=None, help='leave on its own after this long')
    ar.add_argument('--seed', type=int, default=None, help='fix the choreography seed (captures, previews)')
    add_arena_option_flags(ar)
    ar.set_defaults(fn=cmd_arena)
    p = sub.add_parser('plates', help='show or hide both HUD plates; macOS: put them in the menu bar or above the Dock')
    p.add_argument('state', choices=('on', 'off', 'menubar', 'dock'))
    p.set_defaults(fn=cmd_plates)
    d = sub.add_parser('demo', help='start one bout now')
    d.add_argument('kind', nargs='?', default='spar', choices=('spar', 'clash', 'ranged', 'match'))
    d.set_defaults(fn=cmd_demo)
    s = sub.add_parser('selftest-gui')
    s.add_argument('--keep', action='store_true', help='leave the fighters running afterwards')
    s.set_defaults(fn=cmd_selftest)
    dr = sub.add_parser('doctor', help='check this machine and print a report to paste to your AI agent or an issue')
    dr.add_argument('--headless', action='store_true', help='no test window (CI): environment, geometry and detection only')
    dr.set_defaults(fn=cmd_doctor)
    sz = sub.add_parser('size', help='taskbar fighter size in px: 64, 96 or 128 (HD); restarts running fighters')
    sz.add_argument('px', type=int, choices=cfgmod.FIGHTER_SIZES)
    sz.set_defaults(fn=cmd_size)
    au = sub.add_parser('autostart', help='macOS: start at login with a LaunchAgent (on | off | status)')
    au.add_argument('state', choices=('on', 'off', 'status'))
    au.set_defaults(fn=cmd_autostart)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except plat.UnsupportedPlatform as e:
        print(str(e))
        return 2
    except ImportError as e:                         # a missing desktop library (PyObjC on a Mac): say what to do
        if 'PyObjC' in str(e):
            print(str(e))
            return 2
        raise


if __name__ == '__main__':
    sys.exit(main())
