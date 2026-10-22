"""Fighter select (V6): who fights (a program per slot, or auto) and what each program looks like (a character).

The lineup lives in control.json (control.lineup / set_pick / set_skin); the director honours it (director.py).  This
module holds the pieces the CLI, the right-click menu and the select screen share:
  characters()      the selectable characters, read from assets/ on every call (art can be added while minis runs)
  programs(assign)  the programs to choose from, with their state, from the director's assign.json
  fighter_menu()    the right-click menu as data (submenus, checkmarks, greyed items) + what each id does
  resolve_name()    'claude code' / 'Grok' / 'ninja' -> a program or a character
"""
from __future__ import annotations
import json
from pathlib import Path

from . import atlas as atlasmod, sources

AUTO = 'auto'
NOT_CHARACTERS = ('fx',)
GENERIC = 'generic'


# ---------------------------------------------------------------- characters
def characters(root=None) -> list:
    """-> [{'id', 'display'}] for every character with an assets/<id>/anim.json, alphabetical by display name, `generic`
    last.  Nothing is hard-coded: a new directory from the art build is selectable at once."""
    base = Path(root) if root else atlasmod.ASSETS
    out = []
    try:
        dirs = [p for p in base.iterdir() if p.is_dir() and p.name not in NOT_CHARACTERS and (p / 'anim.json').is_file()]
    except OSError:
        dirs = []
    for p in dirs:
        try:
            meta = json.loads((p / 'anim.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue                                       # unreadable: it could not be drawn either
        disp = meta.get('display') if isinstance(meta, dict) else None
        out.append({'id': p.name, 'display': str(disp or p.name.capitalize())})
    if root is None:                                       # growth: installed skin packs (pack-<name>), validated data only
        try:
            from . import packs
            out += [c for c in packs.characters() if c['id'] not in {o['id'] for o in out}]
        except Exception:
            pass
    return sorted(out, key=lambda c: (c['id'] == GENERIC, c['display'].lower(), c['id']))


def character_ids(root=None) -> list:
    return [c['id'] for c in characters(root)]


def display_of(character, chars=None) -> str:
    for c in (chars if chars is not None else characters()):
        if c['id'] == character:
            return c['display']
    return str(character)


# ---------------------------------------------------------------- programs
NOT_SEEN = 'not seen'


def programs(assign) -> list:
    """-> [{'source','program','label','character','state'}] from assign.json's `programs` list (the director writes it),
    falling back to the static table when the director has not written one.  state: working / idle / waiting / done /
    limit / sleeping (live), 'asleep' (seen within the dormant window), 'bot', or 'not seen'."""
    rows = (assign or {}).get('programs') if isinstance(assign, dict) else None
    out = []
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get('source'), str):
                sid = r['source']
                out.append(dict(source=sid, program=str(r.get('program') or sources.PROGRAM.get(sid, sid)),
                                label=str(r.get('label') or sources.short_label(sid)),
                                character=str(r.get('character') or sources.CHARACTER.get(sid, GENERIC)),
                                state=str(r.get('state') or NOT_SEEN)))
    if not out:
        for sid in sources.known_programs():
            out.append(dict(source=sid, program=sources.PROGRAM.get(sid, sid), label=sources.short_label(sid),
                            character=sources.CHARACTER.get(sid, GENERIC), state='bot' if sid == sources.SPARRING else NOT_SEEN))
    return out


def state_word(state) -> str:
    return {'asleep': 'asleep', 'bot': 'stand-in', NOT_SEEN: 'not seen'}.get(state, state)


def known_ids(assign=None) -> list:
    ids = [r['source'] for r in programs(assign)]
    for sid in sources.known_programs():
        if sid not in ids:
            ids.append(sid)
    return ids


def resolve_name(text, assign=None, chars=None):
    """'Claude Code' / 'claude' / 'GROK' / 'Bot' -> ('program', id); 'ninja' / 'Agent' -> ('character', id); 'auto' ->
    ('auto', 'auto'); else (None, None).  A name that is both (claude, codex, gemini ...) resolves to the program."""
    k = str(text or '').strip().lower()
    if not k:
        return None, None
    if k == AUTO:
        return 'auto', AUTO
    for r in programs(assign):
        if k in (r['source'].lower(), r['program'].lower(), r['label'].lower()):
            return 'program', r['source']
    for sid in sources.known_programs():
        if k in (sid, sources.PROGRAM.get(sid, sid).lower(), sources.short_label(sid).lower()):
            return 'program', sid
    for c in (chars if chars is not None else characters()):
        if k in (c['id'].lower(), c['display'].lower()):
            return 'character', c['id']
    return None, None


def resolve_character(text, chars=None):
    """A character only (the `skin` command): id or display name, any case -> id, else None."""
    k = str(text or '').strip().lower()
    for c in (chars if chars is not None else characters()):
        if k in (c['id'].lower(), c['display'].lower()):
            return c['id']
    return None


def own_character(source_id, assign=None) -> str:
    for r in programs(assign):
        if r['source'] == source_id:
            return r['character']
    return sources.CHARACTER.get(source_id, GENERIC)


def look_of(source_id, lu, assign=None) -> str:
    """The character a program is drawn as: its skin, else its own character."""
    sk = (lu or {}).get('skins') or {}
    return sk.get(source_id) or own_character(source_id, assign)


# ---------------------------------------------------------------- the right-click menu, as data
QUIT_ALL, HIDE_1H, PLATES, PAUSE, BOUT, MATCH, WIN_DECIDED, ARENA, RIVAL, HIDE, SELECT, WIN_RANDOM, FLASH = range(1, 14)
HUD_DOCK, HUD_MENUBAR = 14, 15                     # macOS only: the Plates position submenu
FORGE = 16                                         # V8: Desktop weapons (arena forging) on / off
CARD = 17                                          # growth: Share my stats card...
SOUND = 18                                         # V9: Sound effects on / off (default off; 17 was taken by growth's CARD)
PICK_AUTO, PICK_BASE = 100, 101
LOOK_DEFAULT, LOOK_BASE = 300, 301
SIZE_BASE = 400                                    # SIZE_BASE + px: the Fighter size submenu (464 / 496 / 528)


def fighter_menu(slot, assign, lu, flags, chars):
    """-> (items, actions).  items is the menu for minis_win.shell.Overlay.menu:
         (id, label[, {'checked','radio','disabled'}]) | None (separator) | (label, [items]) (submenu)
       actions: {id: (kind, value)} for the Fighter and Look submenus.  flags: paused, plates, rival, flash, arena (bools),
       winners ('decided'|'random'), and on macOS hud_pos ('dock'|'menubar': adds the Plates position submenu)."""
    me = (assign or {}).get(slot) if isinstance(assign, dict) else None
    me = me if isinstance(me, dict) else {}
    src = me.get('source')
    pick = (lu or {}).get(slot, AUTO)
    other_pick = (lu or {}).get('b' if slot == 'a' else 'a', AUTO)
    actions = {PICK_AUTO: ('pick', AUTO)}
    fighters = [(PICK_AUTO, 'Auto (most recently used)', {'radio': True, 'checked': pick == AUTO}), None]
    for i, r in enumerate(programs(assign)):
        mid = PICK_BASE + i
        actions[mid] = ('pick', r['source'])
        word = state_word(r['state']) + ('; other side' if other_pick == r['source'] else '')
        fighters.append((mid, f"{r['label']}  ({word})",
                         {'radio': True, 'checked': pick == r['source'], 'disabled': r['state'] == NOT_SEEN and pick != r['source']}))
    looks = []
    if src:
        cur = ((lu or {}).get('skins') or {}).get(src)
        actions[LOOK_DEFAULT] = ('skin', None)
        looks.append((LOOK_DEFAULT, f'Default ({display_of(own_character(src, assign), chars)})', {'radio': True, 'checked': cur is None}))
        looks.append(None)
        for i, c in enumerate(chars):
            mid = LOOK_BASE + i
            actions[mid] = ('skin', c['id'])
            looks.append((mid, c['display'], {'radio': True, 'checked': cur == c['id']}))
    sizes = []
    for px in (64, 96, 128):
        actions[SIZE_BASE + px] = ('size', px)
        sizes.append((SIZE_BASE + px, f'{px} px' + (' (HD)' if px > 64 else ''), {'radio': True, 'checked': flags.get('size', 128) == px}))
    name = sources.short_label(src, me.get('program')) if src else 'this side'
    items = [(f'Fighter ({"left" if slot == "a" else "right"} side)', fighters)]
    if looks:
        items.append((f'Look ({name})', looks))
    items += [(SELECT, 'Select fighters...'), None,
              (PAUSE, 'Pause all animations', {'checked': bool(flags.get('paused'))}),
              (PLATES, 'HUD plates', {'checked': bool(flags.get('plates', True))}),
              (FLASH, 'Flash effects', {'checked': bool(flags.get('flash', True))}),
              (SOUND, 'Sound effects', {'checked': bool(flags.get('sound', False))}),
              (RIVAL, 'Rival mode (wake a sleeping partner to fight)', {'checked': bool(flags.get('rival', True))}),
              ('Who wins', [(WIN_DECIDED, 'Healthier program usually wins', {'radio': True, 'checked': flags.get('winners') != 'random'}),
                            (WIN_RANDOM, 'Coin flip', {'radio': True, 'checked': flags.get('winners') == 'random'})]),
              ('Fighter size', sizes),
              None,
              (BOUT, 'Start a bout now'), (MATCH, 'Start a match now (best of 3)'),
              (ARENA, 'Arena mode', {'checked': bool(flags.get('arena'))}),
              (FORGE, 'Desktop weapons (arena grabs the screen into RAM)', {'checked': bool(flags.get('forge', True))}),
              (CARD, 'Share my stats card…'),
              None,
              (HIDE, f'Hide this fighter ({name})'), (HIDE_1H, 'Hide for 1 hour'), (QUIT_ALL, 'Quit Taskbar Fighters (stops everything)')]
    if flags.get('hud_pos') in ('dock', 'menubar'):
        at = next(i for i, it in enumerate(items) if it and it[0] == PLATES) + 1
        items.insert(at, ('Plates position', [(HUD_DOCK, 'Above the Dock', {'radio': True, 'checked': flags['hud_pos'] == 'dock'}),
                                              (HUD_MENUBAR, 'In the menu bar', {'radio': True, 'checked': flags['hud_pos'] == 'menubar'})]))
    return items, actions


def labels_of(items) -> list:
    """Flat list of every label in a menu spec (tests, diagnostics)."""
    out = []
    for it in items:
        if it is None:
            continue
        if isinstance(it[1], list):
            out.append(it[0])
            out += labels_of(it[1])
        else:
            out.append(it[1])
    return out


def find_item(items, label_prefix):
    """-> the (id, label[, opts]) entry whose label starts with `label_prefix` (submenus searched), or None."""
    for it in items:
        if it is None:
            continue
        if isinstance(it[1], list):
            got = find_item(it[1], label_prefix)
            if got:
                return got
        elif str(it[1]).startswith(label_prefix):
            return it
    return None
