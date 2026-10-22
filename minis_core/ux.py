"""The UX layer's own small state file and the request channel between the CLI, the tray, the fighters and the director.

ux.json in the data folder (numbers, ids and enums only):
  {"first_run_done": bool,                  the first-run guide was shown (or skipped) once; it never comes back on its own
   "results": bool, "cards": bool,          the results strip after a match / hover cards (default on; Settings or the CLI)
   "signals": bool,                         victory flags, "needs you", second wind, finisher cue (default on)
   "request": {"id", "kind", "arg", "ts"}}  ask the director to open a window: settings | book | legend | guide | replay | gif

Why a file of its own: control.json is shared with three other work streams; the UX switches and the window requests live
here so they never collide with those keys.  The director hosts every UX window (one host = one window of each kind at a
time); it polls the request like it polls the select-screen request in control.json.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

from . import config as cfgmod
from .bus import write_json_atomic

KINDS = ('settings', 'book', 'legend', 'guide', 'replay', 'gif', 'zone')
REQUEST_MAX_AGE_S = 6.0
SWITCHES = {'results': True, 'cards': True, 'signals': True}


def path() -> Path:
    return cfgmod.data_dir() / 'ux.json'


_cache = {}


def read(p=None) -> dict:
    p = Path(p) if p else path()
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)
        hit = _cache.get(str(p))
        if hit and hit[0] == sig:
            return hit[1]
        data = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        return {}
    _cache[str(p)] = (sig, data)
    return data


def update(p=None, _after_read=None, **kw) -> bool:
    """Change some keys, keeping the rest: the read-modify-write runs under a lock (filelock) - the CLI, the director and
    both fighters write this file.  False when the lock could not be taken.  _after_read: a test hook."""
    from .filelock import locked
    target = Path(p) if p else path()
    with locked(target) as ok:
        if not ok:
            return False
        data = dict(read(target), ts=time.time(), **kw)
        if _after_read is not None:
            _after_read()
        return write_json_atomic(target, data)


def switch(name, p=None) -> bool:
    v = read(p).get(name)
    return SWITCHES.get(name, True) if v is None else bool(v)


def set_switch(name, flag, p=None) -> bool:
    if name not in SWITCHES:
        raise ValueError(name)
    return update(p, **{name: bool(flag)})


def first_run_done(p=None) -> bool:
    return bool(read(p).get('first_run_done'))


def set_first_run_done(flag=True, p=None) -> bool:
    return update(p, first_run_done=bool(flag))


def request(kind, arg=None, p=None, now=None) -> bool:
    """Ask the director to open a UX window (`kind` in KINDS); `arg` is a short string (a fight code)."""
    if kind not in KINDS:
        raise ValueError(kind)
    now = time.time() if now is None else now
    return update(p, request={'id': '%x' % int(now * 1000), 'kind': kind, 'arg': None if arg is None else str(arg)[:120], 'ts': now})


def pending(p=None, now=None):
    """-> the request dict while it is younger than REQUEST_MAX_AGE_S, else None."""
    r = read(p).get('request')
    now = time.time() if now is None else now
    try:
        if isinstance(r, dict) and r.get('kind') in KINDS and r.get('id') and 0 <= now - float(r['ts']) <= REQUEST_MAX_AGE_S:
            return r
    except (KeyError, TypeError, ValueError):
        pass
    return None


def quiet(control_read=None) -> bool:
    """Calm / quiet mode, when another part of the app offers one (control.json `quiet` or `calm`): the event signals drop
    their motion and flourishes and keep only the static marks."""
    try:
        if control_read is None:
            from . import control
            control_read = control.read
        d = control_read() or {}
        return bool(d.get('quiet') or d.get('calm'))
    except Exception:
        return False


def testing() -> bool:
    """Under the test suite nothing opens on its own (the first-run guide waits for a test that asks for it)."""
    return bool(os.environ.get('MINIS_TESTING'))


# ---------------------------------------------------------------- where minis.json lives
def settings_path() -> Path:
    """The minis.json the Settings window (and `minis.py zone`) writes: in the data folder, never in the install folder (the
    app writes only under its data folder, or to a path you choose).  Its keys override the hand-written minis.json next to
    minis.py; `"zone": "auto"` means the default zone even when the hand-written file sets one."""
    return cfgmod.data_dir() / 'minis.json'


OVERLAY_KEYS = ('zone',)


def apply_overlay(cfg, p=None) -> dict:
    """cfg with the data folder's minis.json applied (only the keys the UI writes)."""
    over = read_settings(p)
    for k in OVERLAY_KEYS:
        if k not in over:
            continue
        v = over[k]
        if k == 'zone':
            if v == 'auto':
                cfg['zone'] = list(cfgmod.DEFAULTS['zone'])
            elif isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v) and v[1] > v[0]:
                cfg['zone'] = [int(v[0]), int(v[1])]
    return cfg


def read_settings(p=None) -> dict:
    p = Path(p) if p else settings_path()
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_setting(key, value, p=None) -> bool:
    """Set (value not None) or remove (None) one key in minis.json, keeping every other key and the file's indentation
    style simple (2 spaces).  A minis.json that does not parse is left alone (False): never overwrite someone's file."""
    from .filelock import locked
    p = Path(p) if p else settings_path()
    with locked(p) as ok:
        if not ok:
            return False
        data = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return False
            if not isinstance(data, dict):
                return False
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        try:
            tmp = p.with_name(f'.{p.stem}.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
            os.replace(tmp, p)
            return True
        except OSError:
            return False
