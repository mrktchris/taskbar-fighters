"""User controls shared by every fighter: %LOCALAPPDATA%\\minis\\control.json
  {"paused": bool, "plates": bool, "winners": "decided"|"random", "demo": {"id", "kind", "ts"}, "arena_stop": ts,
   "rival": bool, "flashes": bool, "picker": {"id", "slots", "ts"},
   "lineup": {"a": "auto"|program id, "b": ..., "skins": {program id: character id}},
   "hidden": {slot: until (wall-clock seconds; 0 = until `minis.py show`)}}
and the arena's own heartbeat file arena.json {"pid", "monitor", "freeze", "phase", "round", "hp", "ts"} (written by the
arena process every ~1 s; the taskbar fighters hide while it is fresh)."""
from __future__ import annotations
import json, time
from pathlib import Path

from . import config as cfgmod
from .bus import write_json_atomic


def control_path() -> Path:
    return cfgmod.data_dir() / 'control.json'


_cache = {}


def read(path=None) -> dict:
    p = Path(path) if path else control_path()
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)   # os.replace makes a new file: a same-size rewrite in one mtime tick still misses
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


def paused(path=None) -> bool:
    return bool(read(path).get('paused', False))


def _update(path, **kw) -> bool:
    data = dict(read(path), ts=time.time(), **kw)
    return write_json_atomic(Path(path) if path else control_path(), data)


def set_paused(flag: bool, path=None) -> bool:
    return _update(path, paused=bool(flag))


def plates_on(path=None) -> bool:
    """HUD plates shown (the default) or hidden entirely (`minis.py plates off`, or the right-click menu)."""
    return read(path).get('plates', True) is not False


def set_plates(flag: bool, path=None) -> bool:
    return _update(path, plates=bool(flag))


HUD_POSITIONS = ('dock', 'menubar')


def hud_position(path=None) -> str:
    """macOS: where the HUD plates sit - 'dock' (above the Dock, the default) or 'menubar' (in the menu bar, beside the
    notch).  `minis.py plates menubar|dock` or the fighter menu.  Windows keeps them in the taskbar and never reads it."""
    v = read(path).get('hud_position')
    return v if v in HUD_POSITIONS else 'dock'


def set_hud_position(pos: str, path=None) -> bool:
    return _update(path, hud_position=pos if pos in HUD_POSITIONS else 'dock')


def rival_on(path=None, default=True) -> bool:
    """Rival mode (V5.1): a sleeping partner is woken for a match now and then.  `minis.py rival on|off` or the menu;
    `default` is the config value when control.json has no say."""
    v = read(path).get('rival')
    return bool(default) if v is None else bool(v)


def set_rival(flag: bool, path=None) -> bool:
    return _update(path, rival=bool(flag))


def flashes_on(path=None, default=True) -> bool:
    """Impact frames and white screen flashes (V6).  `minis.py effects flashes on|off`; `default` is the config value
    (`flashes`) when control.json has no say.  Off: no flash of any kind, only the hit effects."""
    v = read(path).get('flashes')
    return bool(default) if v is None else bool(v)


def set_flashes(flag: bool, path=None) -> bool:
    return _update(path, flashes=bool(flag))


def forge_on(path=None, default=True) -> bool:
    """Desktop weapons in the arena (V8, the owner's default: on): the arena grabs its monitor ONCE into RAM to forge
    weapons from real screen pixels, and never saves it.  `minis.py forge on|off` or the menu's "Desktop weapons";
    off = no grab and no forge, and an arena already running drops its grab within ~2 s."""
    v = read(path).get('forge')
    return bool(default) if v is None else bool(v)


def set_forge(flag: bool, path=None) -> bool:
    return _update(path, forge=bool(flag))


def sound_on(path=None) -> bool:
    """V9 sound effects: off unless the owner turned them on (`minis.py sound on`, the menus' Sound effects)."""
    return read(path).get('sound') is True


def set_sound(flag: bool, path=None) -> bool:
    return _update(path, sound=bool(flag))


def fighter_size(path=None, default=128) -> int:
    """Taskbar fighter size in px (64 | 96 | 128): control.json `fighter_size` (set by `minis.py size N` and the menu),
    else `default` (config `fighter_size`)."""
    from .config import fighter_size_of
    v = read(path).get('fighter_size')
    return fighter_size_of(default, 128) if v is None else fighter_size_of(v, fighter_size_of(default, 128))


def set_fighter_size(size, path=None) -> bool:
    from .config import FIGHTER_SIZES
    if int(size) not in FIGHTER_SIZES:
        return False
    return _update(path, fighter_size=int(size))


PICKER_MAX_AGE_S = 5.0


def request_picker(slots=('a', 'b'), path=None, now=None) -> bool:
    """Ask the director (which hosts the scoreboard) to open the fighter-select screen for `slots` (the right-click menu's
    "Select fighters..." lives in a slot process; one host means one select screen at a time)."""
    now = time.time() if now is None else now
    slots = [s for s in ('a', 'b') if s in tuple(slots or ())] or ['a', 'b']
    return _update(path, picker={'id': '%x' % int(now * 1000), 'slots': slots, 'ts': now})


def picker_request(path=None, now=None):
    """-> {'id','slots','ts'} of a select-screen request younger than PICKER_MAX_AGE_S, else None."""
    d = read(path).get('picker')
    now = time.time() if now is None else now
    try:
        if isinstance(d, dict) and d.get('id') and 0 <= now - float(d['ts']) <= PICKER_MAX_AGE_S:
            slots = [s for s in ('a', 'b') if s in (d.get('slots') or ())] or ['a', 'b']
            return dict(d, slots=slots)
    except (KeyError, TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------- fighter select (V6)
AUTO = 'auto'


def lineup(path=None) -> dict:
    """-> {'a': 'auto'|program id, 'b': ..., 'skins': {program id: character id}}, always well formed.  A pick keeps that
    program in its slot (asleep when it is not detected); 'auto' is the director's own choice; a skin is the character a
    program is drawn as.  The same program in both slots: slot b falls back to auto."""
    raw = read(path).get('lineup')
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for s in ('a', 'b'):
        v = raw.get(s)
        out[s] = v.strip() if isinstance(v, str) and v.strip() else AUTO
    if out['a'] != AUTO and out['a'] == out['b']:
        out['b'] = AUTO
    skins = raw.get('skins')
    out['skins'] = {k: v for k, v in (skins.items() if isinstance(skins, dict) else ()) if isinstance(k, str) and isinstance(v, str) and k and v}
    return out


def _write_lineup(lu, path=None) -> bool:
    return _update(path, lineup={'a': lu['a'], 'b': lu['b'], 'skins': dict(lu['skins'])})


def set_pick(slot, program, path=None) -> bool:
    """Pin `program` (a source id, or 'auto') to `slot`.  Picking the program the other slot holds moves it here and puts
    the other slot back on auto (one program never fights itself)."""
    if slot not in ('a', 'b'):
        raise ValueError(slot)
    lu = lineup(path)
    program = (program or AUTO).strip() or AUTO
    lu[slot] = program
    o = 'b' if slot == 'a' else 'a'
    if program != AUTO and lu[o] == program:
        lu[o] = AUTO
    return _write_lineup(lu, path)


def set_skin(program, character, path=None) -> bool:
    """Draw `program` as `character`; character None / 'default' gives the program its own character back."""
    lu = lineup(path)
    if character in (None, '', 'default'):
        lu['skins'].pop(program, None)
    else:
        lu['skins'][program] = character
    return _write_lineup(lu, path)


def reset_lineup(skins=True, path=None) -> bool:
    """Both slots back to auto; `skins=True` also forgets every skin (`fighters reset`), False keeps them (`fighters auto`)."""
    lu = lineup(path)
    lu['a'] = lu['b'] = AUTO
    if skins:
        lu['skins'] = {}
    return _write_lineup(lu, path)


# ---------------------------------------------------------------- hide / show (V6: undoable, visible on the scoreboard)
def hide(slot, seconds=None, path=None, now=None) -> bool:
    """Hide one fighter for `seconds`, or until `show` when seconds is None."""
    now = time.time() if now is None else now
    h = dict(read(path).get('hidden') or {}) if isinstance(read(path).get('hidden'), dict) else {}
    h[slot] = 0 if seconds is None else now + float(seconds)
    return _update(path, hidden=h)


def show(slot=None, path=None) -> bool:
    """Bring back one hidden fighter, or both (slot None)."""
    h = read(path).get('hidden')
    h = dict(h) if isinstance(h, dict) else {}
    for s in (('a', 'b') if slot is None else (slot,)):
        h.pop(s, None)
    return _update(path, hidden=h)


def hidden_left(slot, path=None, now=None):
    """-> None (shown), float('inf') (hidden until `show`) or the seconds left of a timed hide."""
    h = read(path).get('hidden')
    if not isinstance(h, dict) or slot not in h:
        return None
    now = time.time() if now is None else now
    try:
        until = float(h[slot])
    except (TypeError, ValueError):
        return None
    if until == 0:
        return float('inf')
    left = until - now
    return left if left > 0 else None


DEMO_KINDS = ('spar', 'clash', 'ranged', 'match')
WINNER_MODES = ('decided', 'random')
ARENA_FRESH_S = 4.0


def winners(path=None) -> str:
    """How match winners are drawn: `decided` (biased by the health score, the default) or `random`."""
    v = read(path).get('winners')
    return v if v in WINNER_MODES else 'decided'


def set_winners(mode: str, path=None) -> bool:
    if mode not in WINNER_MODES:
        raise ValueError(mode)
    return _update(path, winners=mode)


# ---------------------------------------------------------------- arena mode
def arena_path() -> Path:
    return cfgmod.data_dir() / 'arena.json'


def write_arena_state(state: dict, path=None, now=None) -> bool:
    """The arena process's heartbeat (numbers / enums only: pid, monitor index, phase, round, hp)."""
    now = time.time() if now is None else now
    return write_json_atomic(Path(path) if path else arena_path(), dict(state, ts=now))


def clear_arena_state(path=None) -> bool:
    return write_json_atomic(Path(path) if path else arena_path(), {'active': False, 'ts': time.time()})


def arena_state(path=None, now=None):
    """-> the arena heartbeat while it is fresh and active, else None."""
    d = read(path or arena_path())
    now = time.time() if now is None else now
    try:
        # A heartbeat stamped a little AFTER `now` is the freshest one: the reader took its clock before reading, and the
        # arena wrote in between (common on a busy machine).  Only one from far in the future (a clock jump) is distrusted.
        if d.get('active') and -ARENA_FRESH_S <= now - float(d.get('ts', 0)) <= ARENA_FRESH_S:
            return d
    except (TypeError, ValueError):
        pass
    return None


def arena_active(path=None, now=None) -> bool:
    return arena_state(path, now) is not None


def request_arena_stop(path=None, now=None) -> bool:
    now = time.time() if now is None else now
    return _update(path, arena_stop=now)


def arena_stop_requested(since, path=None) -> bool:
    """True when an `arena stop` was asked for after the arena started (`since`, wall-clock)."""
    try:
        return float(read(path).get('arena_stop', 0)) > float(since)
    except (TypeError, ValueError):
        return False
DEMO_MAX_AGE_S = 15.0


def request_demo(kind='spar', path=None, now=None) -> bool:
    """Ask the fighters for one bout right now (`minis.py demo`, or the right-click menu).  Only the choreography is
    forced: the plates keep showing the real state and numbers."""
    if kind not in DEMO_KINDS:
        raise ValueError(kind)
    now = time.time() if now is None else now
    return _update(path, demo={'id': '%x' % int(now * 1000), 'kind': kind, 'ts': now})


def demo(path=None, now=None):
    """-> {'id','kind','ts'} of a demo request younger than DEMO_MAX_AGE_S, else None."""
    d = read(path).get('demo')
    now = time.time() if now is None else now
    try:
        if isinstance(d, dict) and d.get('kind') in DEMO_KINDS and 0 <= now - float(d['ts']) <= DEMO_MAX_AGE_S:
            return d
    except (KeyError, TypeError, ValueError):
        pass
    return None
