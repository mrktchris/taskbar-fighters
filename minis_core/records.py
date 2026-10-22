r"""W-L records per PROGRAM (V6), in the same %LOCALAPPDATA%\minis\record.json the V4 engine writes.

V4/V5 keyed records by character, so every program drawn with the generic skin (aider, opencode, Grok, the sparring bot)
shared one line.  Now:
  {"programs": {source id: {"w", "l"}}, "characters": {...frozen V5 data...}, "matches": n,
   "last": {"winner": source id, "loser": source id, "score": [w, l], "ts", "where"}}
Migration: a file without "programs" is read as if each character that belongs to exactly one program (claude, codex,
cursor, gemini, ollama, lmstudio) were that program's record; the shared `generic` line cannot be split and stays in
"characters" only.  The first write stores the migrated table.  Only source ids and numbers are stored.
"""
from __future__ import annotations
import time
from pathlib import Path

from .bus import write_json_atomic

# characters that stand for exactly one program (sources.CHARACTER is many-to-one for 'generic' only)
UNIQUE_CHARACTER_PROGRAM = {'claude': 'claude', 'codex': 'codex', 'cursor': 'cursor', 'gemini': 'gemini', 'ollama': 'ollama',
                            'lmstudio': 'lmstudio'}


def _rounds():
    from . import rounds
    return rounds


def read(path=None) -> dict:
    """record.json with a `programs` table (migrated in memory from `characters` when the file predates V6)."""
    rec = dict(_rounds().read_record(path))
    progs = rec.get('programs')
    if not isinstance(progs, dict):
        rec['programs'] = migrate(rec.get('characters'))
        rec['migrated'] = True
    return rec


def migrate(characters) -> dict:
    out = {}
    for ch, v in (characters.items() if isinstance(characters, dict) else ()):
        prog = UNIQUE_CHARACTER_PROGRAM.get(ch)
        if prog and isinstance(v, dict):
            try:
                out[prog] = {'w': int(v.get('w', 0)), 'l': int(v.get('l', 0))}
            except (TypeError, ValueError):
                pass
    return out


def for_program(rec, source_id) -> tuple:
    v = ((rec or {}).get('programs') or {}).get(source_id) or {}
    try:
        return int(v.get('w', 0)), int(v.get('l', 0))
    except (TypeError, ValueError, AttributeError):
        return 0, 0


def record(winner, loser, path=None, now=None, where='taskbar', score=None, facts=None) -> bool:
    """One match result keyed by program (source id).  Atomic; False instead of raising on disk trouble.
    facts (growth, optional; achievements.match_facts): numbers and booleans about the match, appended to the capped
    `log` and folded into the lifetime per-program `totals`.  Only source ids, move ids and numbers are stored."""
    rounds = _rounds()
    p = Path(path) if path else rounds.record_path()
    rec = read(p)
    rec.pop('migrated', None)
    progs = rec['programs']
    for sid, key in ((winner, 'w'), (loser, 'l')):
        e = progs.setdefault(str(sid), {'w': 0, 'l': 0})
        e[key] = int(e.get(key, 0)) + 1
    rec['matches'] = int(rec.get('matches', 0) or 0) + 1
    last = dict(winner=str(winner), loser=str(loser), ts=time.time() if now is None else now, where=where)
    if score and len(score) == 2:
        last['score'] = [int(score[0]), int(score[1])]
    rec['last'] = last
    try:
        from . import achievements
        achievements.fold(rec, last, facts)
    except Exception:                    # the W-L line above must land even if the extras cannot
        pass
    return write_json_atomic(p, rec)


def last_result(rec, now, show_s=8.0):
    """-> {'winner','loser','score'} of a match that ended less than `show_s` ago (the scoreboard's result line), else None."""
    last = (rec or {}).get('last')
    if not isinstance(last, dict) or not isinstance(last.get('winner'), str):
        return None
    try:
        age = float(now) - float(last.get('ts', 0))
    except (TypeError, ValueError):
        return None
    if not 0 <= age <= show_s:
        return None
    return last
