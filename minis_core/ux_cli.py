"""The UX layer's commands (minis.py hooks them in with one call): every Settings row, the guide / legend, replays, fight
codes, GIF export and the move book are reachable from the command line too.

  settings [open|list]            open the Settings window (while it runs) / print every setting, its value and its command
  settings set <row> <value>      change one row the way the window does (e.g. `settings set results off`)
  results|cards|signals on|off    the results strip after a match / hover cards / event signals
  startup on|off|status           start at sign-in (Windows: one "Taskbar Fighters.lnk" in shell:startup, reused, never
                                  duplicated; macOS: the LaunchAgent `autostart` manages)
  zone [show|edit|auto|<left> <right>]   the fight zone on the taskbar (minis.json `zone`); edit = the drag-to-set editor
  guide [--first|--reset]         the 10-second legend (--first: the three first-run cards; --reset: show them at next start)
  replay [CODE]                   play the last match's K.O. (or a pasted fight code) above the taskbar
  replay code                     print the last match's fight code and result
  replay --gif [PATH] [--final]   render the last match (or CODE) to a GIF offline: Pictures\\Taskbar Fighters by default
  book [list] [--fighter NAME]    open the move book (while it runs) / print seen counts per fighter
"""
from __future__ import annotations
import sys
from pathlib import Path

from . import ux


def add_parsers(sub, m):
    """Register the commands on minis.py's subparsers; `m` is the minis module (running(), ux_actions(), restart ...)."""
    st = sub.add_parser('settings', help='the Settings window, or every setting with its value and its command')
    st.add_argument('action', nargs='?', default=None, choices=('open', 'list', 'set'))
    st.add_argument('rest', nargs='*')
    st.set_defaults(fn=lambda a: cmd_settings(a, m))
    for name, what in (('results', 'the 4-second results strip after a match'), ('cards', 'hover cards over fighters and plates'),
                       ('signals', 'event signals: done flag, needs-you halo, second wind, finisher cue')):
        p = sub.add_parser(name, help=what + ' on or off')
        p.add_argument('state', choices=('on', 'off'))
        p.set_defaults(fn=lambda a, n=name: cmd_switch(a, n))
    su = sub.add_parser('startup', help='start at sign-in: on | off | status (Windows: shell:startup shortcut; macOS: LaunchAgent)')
    su.add_argument('state', choices=('on', 'off', 'status'))
    su.set_defaults(fn=lambda a: cmd_startup(a, m))
    z = sub.add_parser('zone', help='the fight zone on the taskbar: show | edit | auto | <left> <right>')
    z.add_argument('args', nargs='*')
    z.set_defaults(fn=lambda a: cmd_zone(a, m))
    g = sub.add_parser('guide', help='"What am I looking at?": the 10-second legend (--first: the first-run cards)')
    g.add_argument('--first', action='store_true')
    g.add_argument('--reset', action='store_true', help='show the first-run cards again at the next start')
    g.set_defaults(fn=lambda a: cmd_guide(a, m))
    r = sub.add_parser('replay', help='replay the last K.O. (or a fight code); `replay code` prints the code; --gif saves a GIF')
    r.add_argument('code', nargs='?', default=None)
    r.add_argument('--gif', nargs='?', const='', default=None, metavar='PATH', help='render a GIF offline (default: Pictures)')
    r.add_argument('--final', action='store_true', help='GIF of the deciding exchange only (default: the whole match)')
    r.set_defaults(fn=lambda a: cmd_replay(a, m))
    b = sub.add_parser('book', help='the move book: every move, set piece and finisher; seen ones animated')
    b.add_argument('action', nargs='?', default='open', choices=('open', 'list'))
    b.add_argument('--fighter', default=None)
    b.set_defaults(fn=lambda a: cmd_book(a, m))


def app_running(m):
    try:
        return bool(m.running('director'))
    except Exception:
        return False


def _request(m, kind, arg=None, what=None):
    if not app_running(m):
        print(f'Taskbar Fighters is not running: `{m.prog_name()} start` first, then try again.')
        return 1
    ux.request(kind, arg)
    print(f'asked the running app to open {what or kind}')
    return 0


# ---------------------------------------------------------------- settings
def _backend(m):
    from . import settings_ui
    startup = None
    try:
        startup = m.ux_actions()['startup']()
    except Exception:
        startup = None
    be = settings_ui.Backend(m.load_config(), startup=None, restart=(m.restart_all if app_running(m) else None))
    be.startup = startup
    if startup is not None:
        try:
            be.startup_state = startup.status()[0]
        except Exception:
            be.startup_state = 'unknown'
    return be


def show_value(row, v):
    if row['kind'] == 'toggle':
        if row['id'] == 'startup':
            return {'on': 'on', 'off': 'off', 'other': 'off (an entry for another copy exists)'}.get(v, str(v))
        return 'on' if v else 'off'
    if row['kind'] == 'choice':
        return dict(row['choices']).get(v, str(v))
    if row['kind'] == 'zone':
        return f'x {v[0]} - {v[1]}'
    return str(v)


def cmd_settings(a, m):
    from . import settings_ui
    action = a.action or ('open' if app_running(m) else 'list')
    if action == 'open':
        return _request(m, 'settings', what='Settings')
    be = _backend(m)
    rows = settings_ui.rows(be.has_sound())
    if action == 'set':
        if len(a.rest) < 2:
            print('settings set <row> <value>   rows: ' + ', '.join(r['id'] for r in rows))
            return 2
        rid, raw = a.rest[0], ' '.join(a.rest[1:])
        row = next((r for r in rows if r['id'] == rid), None)
        if row is None:
            print(f'no setting called {rid!r}; rows: ' + ', '.join(r['id'] for r in rows))
            return 2
        if row['kind'] == 'toggle':
            if raw not in ('on', 'off'):
                print(f'{rid}: on or off')
                return 2
            value = raw == 'on'
            if rid == 'startup':
                ok, msg = (be.startup.enable() if value else be.startup.disable()) if be.startup else (False, 'not available')
                print(msg)
                return 0 if ok else 1
        elif row['kind'] == 'choice':
            vals = {str(v): v for v, _ in row['choices']}
            vals.update({lab.lower(): v for v, lab in row['choices']})
            if raw.lower() not in vals:
                print(f"{rid}: one of {', '.join(str(v) for v, _ in row['choices'])}")
                return 2
            value = vals[raw.lower()]
        else:
            return cmd_zone(type('A', (), {'args': a.rest[1:]})(), m)
        msg = be.set(rid, value)
        print(f"{row['label']}: {show_value(row, be.get().get(rid))}" + (f'  ({msg})' if msg else ''))
        return 0
    vals = be.get()
    print('Taskbar Fighters settings (the Settings window shows the same; change one with the command on the right)\n')
    w = max(len(r['label']) for r in rows)
    for r in rows:
        print(f"  {r['label']:<{w}}  {show_value(r, vals.get(r['id'])):<40}  {m.prog_name()} {r['cli']}")
    print(f'\n  open the window: {m.prog_name()} settings open   (or the tray icon > Settings...)')
    return 0


def cmd_switch(a, name):
    ux.set_switch(name, a.state == 'on')
    print(f'{name}: {a.state}')
    return 0


def cmd_startup(a, m):
    try:
        st = m.ux_actions()['startup']()
    except Exception as e:
        print(f'start at sign-in is not available here ({type(e).__name__})')
        return 2
    if a.state == 'status':
        s, p = st.status()
        print(f'startup: {s} ({p})' if s != 'other' else f'startup: off - {p} starts another copy of Taskbar Fighters')
        return 0
    ok, msg = st.enable() if a.state == 'on' else st.disable()
    print(msg)
    return 0 if ok else 1


# ---------------------------------------------------------------- zone
def cmd_zone(a, m):
    from . import config as cfgmod
    args = list(getattr(a, 'args', []) or [])
    if not args or args[0] == 'show':
        cfg = m.load_config()
        z = cfg.get('zone')
        own = 'zone' in ux.read_settings()
        print(f"fight zone: x {z[0]} - {z[1]} ({'set in ' + str(ux.settings_path()) if own else 'auto: the default'})")
        return 0
    if args[0] == 'edit':
        return _request(m, 'zone', what='the zone editor')
    if args[0] == 'auto':
        if not ux.write_setting('zone', None):
            print(f'{ux.settings_path()} could not be written (is it valid JSON?)')
            return 1
        print(f"fight zone: auto ({cfgmod.DEFAULTS['zone'][0]} - {cfgmod.DEFAULTS['zone'][1]})")
    else:
        try:
            l, r = int(args[0]), int(args[1])
        except (IndexError, ValueError):
            print('zone <left> <right>   (screen x of the empty stretch of the taskbar, e.g. `zone 40 900`)')
            return 2
        from .settings_ui import MIN_ZONE_W
        if l < 0 or r - l < MIN_ZONE_W:
            print(f'the zone must start at 0 or later and be at least {MIN_ZONE_W} px wide (plates + scoreboard + room to fight)')
            return 2
        if not ux.write_setting('zone', [l, r]):
            print(f'{ux.settings_path()} could not be written (is it valid JSON?)')
            return 1
        print(f'fight zone: x {l} - {r} (in {ux.settings_path()})')
    if app_running(m):
        print('restarting so the fighters are laid out in the new zone ...')
        return m.cmd_restart()
    return 0


# ---------------------------------------------------------------- guide
def cmd_guide(a, m):
    if a.reset:
        ux.set_first_run_done(False)
        print('the first-run cards show again at the next start')
        return 0
    return _request(m, 'guide' if a.first else 'legend', what='the first-run cards' if a.first else 'the legend')


# ---------------------------------------------------------------- replay
def cmd_replay(a, m):
    from . import replay
    code = a.code
    if code == 'code':
        e = replay.last()
        if not e:
            print('no match recorded yet: `minis.py demo match` starts one')
            return 1
        print(replay.result_line(e, upper=False).replace(' · ', ', '))      # a plain console may not have the middle dot
        print(e.get('code') or '(no code for this match)')
        return 0
    try:
        plan, names, fcode, entry, warn = replay.resolve(code)
    except replay.CodeError as e:
        print(f'replay: {e}')
        return 2
    if plan is None:
        print(warn)
        return 1
    if warn:
        print('note: ' + warn)
    if a.gif is None:
        return _request(m, 'replay', code, what='the replay')
    from . import control
    out = Path(a.gif) if a.gif else replay.pictures_dir() / 'Taskbar Fighters' / replay.gif_name(plan)
    if out.suffix.lower() != '.gif':
        out = out / replay.gif_name(plan) if out.is_dir() or not out.suffix else out.with_suffix('.gif')
    print('rendering offline (the planner on a plain backdrop, never a screen capture) ...')
    p, n = replay.save_gif(replay.frames(plan, 'final' if a.final else 'all', fps=12, names=names, code=fcode,
                                         flashes=control.flashes_on(), label='TASKBAR FIGHTERS'), out)
    print(f'saved {p} ({n} frames)')
    if fcode:
        print(f'fight code: {fcode}')
    return 0


# ---------------------------------------------------------------- book
def cmd_book(a, m):
    from . import collection, lineup
    if a.action == 'open':
        return _request(m, 'book', (lineup.resolve_character(a.fighter) if a.fighter else None), what='the move book')
    from .atlas import Library
    lib = Library()
    seen = collection.read()
    print('Move book: what you have seen in fights so far (ids and counts only)\n')
    tg = tt = 0
    chars = lineup.characters()
    if a.fighter:
        cid = lineup.resolve_character(a.fighter)
        chars = [c for c in chars if c['id'] == cid]
    for c in chars:
        g, t = collection.counts(lib[c['id']], set(seen.get(c['id'], {})))
        tg, tt = tg + g, tt + t
        bar = '#' * int(round(20 * g / t)) if t else ''
        print(f"  {c['display']:<11} {g:>3} / {t:<3} {bar}")
    print(f'\n  all fighters {tg} / {tt}')
    return 0


if __name__ == '__main__':                                          # pragma: no cover
    sys.exit('run it through minis.py')
