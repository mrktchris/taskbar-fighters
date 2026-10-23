r"""Achievements, careers, head-to-head records and local ranks (growth) - computed from record.json only.

Public API (stable; the `ux` branch's settings window, results screen, replay and collection book call these):
  match_facts(summary, slot_src, plan=None)   a taskbar match summary -> facts keyed by program (+ the replay plan)
  arena_facts(arena, winner_side)             the same from the arena's own counters
  fold(rec, last, facts)                      records.record calls it: append to rec['log'], fold into totals / h2h
  stats(rec, hist=None)                       every number below, in one dict
  careers(rec) -> {program: Career dict}      lifetime W-L, KOs, streaks, ultimates, flawless rounds, comebacks, rank
  head_to_head(rec, a, b) -> dict             lifetime {a: wins, b: wins} + the last 10 between them
  rank_of(wins) -> (name, floor wins, next)   local rank by LIFETIME wins: it can only climb (never demotes)
  replay_plan(entry) -> dict | None           the stored plan of one log entry (seed + lineup), for an instant replay
  evaluate / progress / update / unlocked     the badges; Toaster (scoreboard); lines / cmd (`minis.py achievements`)
  ACHIEVEMENTS, BY_ID, IDS, FAMILIES          the badge table (every criterion is shown openly: there are no secret ones)

record.json fields this module owns (written by records.record in the same atomic write as the W-L line):
  log     the newest LOG_MAX matches, oldest first: {w, l, ts, where, s: [w, l], ko, fl, cb, pf, ult: [ids], boost: [ids],
          pieces: [set-piece ids], replay: {v, seed, kind, left, right, chars, pos, span, mode, scores, boost}}
          `replay` holds only what rounds.make_match needs to rebuild the same timeline: a seed, slot letters, character
          and program ids, positions, the winners mode and the two health scores (numbers).  No context %, no state.
  totals  lifetime per program {ko, flawless, comebacks, perfects, sweeps, ults, boosts, best_streak, moves: {move: hits}}
  h2h     lifetime per pair "a|b" (ids sorted) -> {a: wins, b: wins}
  seen    {"pieces": [taskbar set-piece ids seen in a recorded match]}
  forges  lifetime desktop weapons forged in arena matches
history.json is not read: no badge rewards context use, token totals, hours or late nights.

The badges are Fight, Discovery or Partnership badges, each with its criterion in the open.  None rewards usage volume,
hours worked or time of day, and nothing is ever taken away for being away.
Unlocks persist in <data dir>/achievements.json {"version": 1, "unlocked": {id: {"ts": wall s, "by": program id|null}}}.
The director's scoreboard is the only writer (Toaster.poll): when record.json changes it re-evaluates, stores what is new
and shows each new badge as a small 3 s toast.  The first evaluation on a machine (no file yet) stores what was already
earned silently, so an old record never floods the scoreboard.  `minis.py achievements` and the stats card only read.
"""
from __future__ import annotations
import datetime, json, os, time
from collections import Counter, namedtuple
from pathlib import Path

from . import config as cfgmod
from .bus import write_json_atomic

TOAST_S = 3.0
LOG_MAX = 500
MOVES_KEEP = 16                       # per program: the most-landed move ids kept in totals (the card's favourite move)
REPLAY_V = 1
RANKS = (('Bronze', 0), ('Silver', 10), ('Gold', 25), ('Master', 60), ('Legend', 120))     # by lifetime wins
FAMILIES = ('Fight', 'Discovery', 'Partnership')


def path() -> Path:
    return cfgmod.data_dir() / 'achievements.json'


# ---------------------------------------------------------------- facts about one match
def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def replay_of(plan):
    """The replayable part of a match plan (brain.Brain._plan): ids and numbers only, or None."""
    if not isinstance(plan, dict) or not isinstance(plan.get('seed'), int):
        return None
    left, right = plan.get('left'), plan.get('right')
    if left not in ('a', 'b') or right not in ('a', 'b') or left == right:
        return None
    out = {'v': REPLAY_V, 'seed': int(plan['seed']), 'kind': str(plan.get('kind') or 'match'), 'left': left, 'right': right}
    chars = plan.get('chars') or {}
    out['chars'] = {s: str(chars[s]) for s in ('a', 'b') if isinstance(chars.get(s), str)}
    pos = plan.get('pos') or {}
    out['pos'] = {s: round(_num(pos.get(s)), 3) for s in ('a', 'b') if _num(pos.get(s)) is not None}
    if _num(plan.get('span')) is not None:
        out['span'] = round(_num(plan['span']), 3)
    out['mode'] = plan.get('mode') if plan.get('mode') in ('decided', 'random') else 'decided'
    sc = plan.get('scores') or {}
    out['scores'] = {s: round(_num(sc.get(s)), 1) for s in ('a', 'b') if _num(sc.get(s)) is not None}
    out['boost'] = [s for s in plan.get('boost') or () if s in ('a', 'b')]
    return out


def replay_plan(entry, t0=0.0):
    """A log entry's stored plan, ready for rounds.make_match (t0 added), or None when the entry has none."""
    r = (entry or {}).get('replay') if isinstance(entry, dict) else None
    if not isinstance(r, dict) or r.get('v') != REPLAY_V:
        return None
    p = {k: v for k, v in r.items() if k != 'v'}
    p.update(t0=float(t0), id=f"replay:{r.get('seed')}", deadline=float(t0))
    if not p.get('boost'):
        p.pop('boost', None)
    return p


def match_facts(summary, slot_src, plan=None):
    """A taskbar match summary (rounds.make_match, brain.last_match) -> facts keyed by PROGRAM.  slot_src: {slot: source id}.
    -> {'ko', 'flawless' (rounds the winner won at full HP), 'perfect', 'comeback' (lost round 1, won the match),
        'ult': [ids that landed an ultimate], 'boost': [ids whose agent had just finished a task], 'pieces': [set pieces],
        'moves': {id: {move: hits}}, 'replay': replay_of(plan)}  or None when the summary is missing or malformed."""
    try:
        if not isinstance(summary, dict) or summary.get('winner') not in slot_src:
            return None
        champ = summary['winner']
        rounds = [r for r in summary.get('rounds') or [] if isinstance(r, dict)]
        won = [r for r in rounds if r.get('winner') == champ]
        flawless = [r for r in won if int((r.get('hp') or {}).get(champ, 0)) >= 100]
        beats = summary.get('beats') or {}
        ult, moves = [], {}
        for slot, src in slot_src.items():
            if not src:
                continue
            c = Counter()
            for b in beats.get(slot) or []:
                if not isinstance(b, dict) or b.get('outcome') != 'hit':
                    continue
                if b.get('kind') == 'ultimate' and src not in ult:
                    ult.append(src)
                if b.get('kind') in ('strike', 'special', 'super', 'ultimate', 'counter') and isinstance(b.get('anim'), str):
                    c[b['anim']] += 1
            if c:
                moves[src] = dict(c.most_common(MOVES_KEEP))
        story = summary.get('story') or {}
        boost = [slot_src[s] for s in ((plan or {}).get('boost') or ()) if slot_src.get(s)] if story.get('boosts') else []
        return dict(ko=summary.get('final_ko') is not None, flawless=len(flawless),
                    perfect=bool(won) and len(flawless) == len(won) == len(rounds), comeback=bool(rounds) and rounds[0].get('winner') != champ,
                    ult=ult, boost=boost, pieces=[str(p) for p in story.get('pieces') or [] if isinstance(p, str)], moves=moves,
                    replay=replay_of(plan))
    except Exception:
        return None


def arena_facts(arena, winner_side):
    """The arena's own counters at its match end -> the same facts (no move counts and no replay: the arena is real time)."""
    try:
        chars = dict(getattr(arena, 'chars', {}) or {})
        loser_side = 'b' if winner_side == 'a' else 'a'
        f = getattr(arena, 'f', {}) or {}
        used = getattr(arena, 'used_ult', {}) or {}
        hp = getattr(f.get(winner_side), 'hp', 0)
        forges = int(((arena.forge.state() or {}).get('forges')) or 0) if getattr(arena, 'forge', None) is not None else 0
        return dict(ko=bool(getattr(f.get(loser_side), 'down', False)), flawless=1 if hp is not None and hp >= 100 else 0, perfect=False,
                    comeback=False, ult=[chars[s] for s in 'ab' if used.get(s) and chars.get(s)], boost=[], pieces=[], moves={},
                    forges=forges)
    except Exception:
        return None


def _pair(a, b):
    return '|'.join(sorted((str(a), str(b))))


def fold(rec, last, facts):
    """Append one result to rec['log'] and fold it into rec['totals'] / rec['h2h'] (records.record calls this before its
    single atomic write)."""
    w, l = last['winner'], last['loser']
    entry = {'w': w, 'l': l, 'ts': float(last.get('ts') or 0), 'where': str(last.get('where') or 'taskbar')}
    if isinstance(last.get('score'), list):
        entry['s'] = list(last['score'])
    f = facts if isinstance(facts, dict) else {}
    if f:
        entry.update(ko=bool(f.get('ko')), fl=int(f.get('flawless') or 0), cb=bool(f.get('comeback')), pf=bool(f.get('perfect')),
                     ult=[str(s) for s in f.get('ult') or []])
        if f.get('boost'):
            entry['boost'] = [str(s) for s in f['boost']]
        if f.get('pieces'):
            entry['pieces'] = [str(p) for p in f['pieces']]
        if isinstance(f.get('replay'), dict):
            entry['replay'] = f['replay']
    log = rec.get('log') if isinstance(rec.get('log'), list) else []
    log.append(entry)
    rec['log'] = log[-LOG_MAX:]
    tot = rec.get('totals') if isinstance(rec.get('totals'), dict) else {}
    rec['totals'] = tot

    def t(src):
        e = tot.get(src)
        if not isinstance(e, dict):
            e = tot[src] = {}
        return e

    def add(src, key, n=1):
        if n:
            t(src)[key] = int(t(src).get(key, 0) or 0) + int(n)
    h2h = rec.get('h2h') if isinstance(rec.get('h2h'), dict) else {}
    rec['h2h'] = h2h
    pr = h2h.get(_pair(w, l)) if isinstance(h2h.get(_pair(w, l)), dict) else {w: 0, l: 0}
    pr[w] = int(pr.get(w, 0) or 0) + 1
    pr.setdefault(l, 0)
    h2h[_pair(w, l)] = pr
    cur = streaks(rec['log']).get(w, (0, 0))[0]                       # lifetime best streak survives the log cap
    t(w)['best_streak'] = max(int(t(w).get('best_streak', 0) or 0), cur)
    t(l)
    s = entry.get('s')
    if s and len(s) == 2 and s[1] == 0:
        add(w, 'sweeps')
    if f:
        add(w, 'ko', 1 if f.get('ko') else 0)
        add(w, 'flawless', int(f.get('flawless') or 0))
        add(w, 'comebacks', 1 if f.get('comeback') else 0)
        add(w, 'perfects', 1 if f.get('perfect') else 0)
        for src in f.get('ult') or []:
            add(src, 'ults')
        for src in f.get('boost') or []:
            add(src, 'boosts')
        for src, mv in (f.get('moves') or {}).items():
            c = Counter({k: int(v) for k, v in (t(src).get('moves') or {}).items()})
            c.update({str(k): int(v) for k, v in mv.items()})
            t(src)['moves'] = dict(c.most_common(MOVES_KEEP))
        if f.get('pieces'):
            seen = rec.get('seen') if isinstance(rec.get('seen'), dict) else {}
            seen['pieces'] = sorted(set(seen.get('pieces') or []) | {str(p) for p in f['pieces']})
            rec['seen'] = seen
        if f.get('forges'):
            rec['forges'] = int(rec.get('forges', 0) or 0) + int(f['forges'])


# ---------------------------------------------------------------- careers, head-to-head, ranks
def streaks(log):
    """-> {src: (current win streak, best win streak)} over the log, oldest first."""
    cur, best = Counter(), Counter()
    for e in log:
        w, l = e.get('w'), e.get('l')
        cur[w] += 1
        best[w] = max(best[w], cur[w])
        cur[l] = 0
    return {s: (cur[s], best[s]) for s in set(cur) | set(best)}


def rank_of(wins):
    """-> (rank name, wins that rank starts at, wins for the next rank | None).  Ranks follow LIFETIME wins, which never go
    down, so a rank once reached is a floor: nobody is ever demoted."""
    wins = max(0, int(wins or 0))
    name, floor, nxt = RANKS[0][0], 0, None
    for i, (n, at) in enumerate(RANKS):
        if wins >= at:
            name, floor = n, at
            nxt = RANKS[i + 1][1] if i + 1 < len(RANKS) else None
    return name, floor, nxt


def _log(rec):
    return [e for e in (rec.get('log') or []) if isinstance(e, dict) and isinstance(e.get('w'), str) and isinstance(e.get('l'), str)]


def head_to_head(rec, a, b):
    """-> {'a': id, 'b': id, 'wins': {a: n, b: n} (lifetime), 'last10': {a: n, b: n}, 'meetings': n}."""
    rec = rec if isinstance(rec, dict) else {}
    pr = ((rec.get('h2h') or {}).get(_pair(a, b))) or {}
    wins = {a: int(pr.get(a, 0) or 0), b: int(pr.get(b, 0) or 0)}
    met = [e for e in _log(rec) if {e['w'], e['l']} == {a, b}]
    if not pr and met:                                              # a record written before h2h existed: count the log
        wins = {a: sum(1 for e in met if e['w'] == a), b: sum(1 for e in met if e['w'] == b)}
    last = met[-10:]
    return dict(a=a, b=b, wins=wins, last10={a: sum(1 for e in last if e['w'] == a), b: sum(1 for e in last if e['w'] == b)},
                meetings=wins[a] + wins[b])


def pairs(rec):
    """-> [head_to_head dicts] for every pair that has met, most meetings first."""
    rec = rec if isinstance(rec, dict) else {}
    keys = set((rec.get('h2h') or {}).keys()) | {_pair(e['w'], e['l']) for e in _log(rec)}
    out = [head_to_head(rec, *k.split('|', 1)) for k in keys if '|' in k]
    return sorted(out, key=lambda h: (-h['meetings'], h['a'], h['b']))


def careers(rec):
    """-> {program: {w, l, bouts, pct, ko, flawless, comebacks, perfects, sweeps, ults, boosts, streak, best_streak, rank,
    rank_floor, rank_next, favourite (move id | None), rival (id | None)}} for every program with a recorded match."""
    rec = rec if isinstance(rec, dict) else {}
    progs = rec.get('programs') if isinstance(rec.get('programs'), dict) else {}
    tot = rec.get('totals') if isinstance(rec.get('totals'), dict) else {}
    st = streaks(_log(rec))
    meet = {}
    for h in pairs(rec):
        for x, y in ((h['a'], h['b']), (h['b'], h['a'])):
            if h['meetings'] > meet.get(x, ('', 0))[1]:
                meet[x] = (y, h['meetings'])
    out = {}
    for sid, v in progs.items():
        try:
            w, l = int(v.get('w', 0)), int(v.get('l', 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if w + l <= 0:
            continue
        t = tot.get(sid) if isinstance(tot.get(sid), dict) else {}
        mv = t.get('moves') or {}
        name, floor, nxt = rank_of(w)
        cur, best = st.get(sid, (0, 0))
        out[sid] = dict(w=w, l=l, bouts=w + l, pct=round(100.0 * w / (w + l)), streak=cur,
                        best_streak=max(best, int(t.get('best_streak', 0) or 0)), rank=name, rank_floor=floor, rank_next=nxt,
                        favourite=max(mv.items(), key=lambda kv: (kv[1], kv[0]))[0] if mv else None,
                        rival=meet.get(sid, (None, 0))[0],
                        **{k: int(t.get(k, 0) or 0) for k in ('ko', 'flawless', 'comebacks', 'perfects', 'sweeps', 'ults', 'boosts')})
    return out


def stats(rec, hist=None):
    """Everything the badges and the card read, from a record.json dict.  (`hist` is accepted for callers that pass it and
    ignored: no badge reads usage history.)"""
    rec = rec if isinstance(rec, dict) else {}
    progs = rec.get('programs') if isinstance(rec.get('programs'), dict) else {}
    log = _log(rec)
    tot = rec.get('totals') if isinstance(rec.get('totals'), dict) else {}
    wl = {}
    for s, v in progs.items():
        try:
            wl[s] = (int(v.get('w', 0)), int(v.get('l', 0)))
        except (TypeError, ValueError, AttributeError):
            pass
    car = careers(rec)
    pp = pairs(rec)

    def total(key):
        return sum(int((v or {}).get(key, 0) or 0) for v in tot.values() if isinstance(v, dict))
    return dict(
        programs=wl, matches=max(int(rec.get('matches', 0) or 0), sum(w for w, _ in wl.values())), log=log, totals=tot,
        careers=car, pairs=pp, streaks=streaks(log), best_streak=max([c['best_streak'] for c in car.values()] or [0]),
        winners=sorted(s for s, (w, _) in wl.items() if w > 0), fought=sorted(s for s, (w, l) in wl.items() if w + l > 0),
        pair_max=max([h['meetings'] for h in pp] or [0]),
        ko=total('ko'), flawless=total('flawless'), comebacks=total('comebacks'), perfects=total('perfects'), sweeps=total('sweeps'),
        ults=total('ults'), boosts=total('boosts'), arena_wins=sum(1 for e in log if e.get('where') == 'arena'),
        forges=int(rec.get('forges', 0) or 0), pieces=sorted(((rec.get('seen') or {}).get('pieces') or [])) if isinstance(rec.get('seen'), dict) else [],
        learn=_learning_stats())


def _learning_stats():
    """learning.stats() (moves the fighters taught themselves: ids and counts from learning.json, nothing else), or empty
    numbers when the module or the file cannot be read."""
    try:
        from . import learning
        s = learning.stats()
        s['first'] = {how: learning.first_by(how) for how in ('any', 'counter')}
        return s
    except Exception:
        return dict(learned=0, by_how={}, programs={}, forgotten=0, first={})


# ---------------------------------------------------------------- the badges
Achievement = namedtuple('Achievement', 'id name desc tier icon family met by progress')


def _first(log, test):
    """The program that first did it (the oldest log entry passing test(entry) -> its winner), or None."""
    for e in log:
        try:
            if test(e):
                return e.get('w')
        except Exception:
            continue
    return None


def _top(S, key):
    best = None
    for s, c in S['careers'].items():
        if c.get(key) and (best is None or c[key] > best[1]):
            best = (s, c[key])
    return best[0] if best else None


def _streak_by(n):
    def by(S):
        return next((s for s, c in sorted(S['careers'].items()) if c['best_streak'] >= n), None)
    return by


def _n(key, need):
    return lambda S: (min(need, S[key]), need)


def _all_pieces():
    try:
        from . import setpieces
        return sorted(setpieces.PIECES)
    except Exception:
        return []


A = Achievement
ACHIEVEMENTS = [
    # Fight: what happened in the fights themselves
    A('first_blood', 'First Blood', 'Win a first match', 1, 'sword', 'Fight', lambda S: bool(S['winners']),
      lambda S: _first(S['log'], lambda e: True), lambda S: (min(1, len(S['winners'])), 1)),
    A('first_ko', 'First KO', 'Win a match by knockout', 1, 'fist', 'Fight', lambda S: S['ko'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('ko')), _n('ko', 1)),
    A('clean_sweep', 'Clean Sweep', 'Win a match 2-0', 1, 'star', 'Fight', lambda S: S['sweeps'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('s') and e['s'][1] == 0), _n('sweeps', 1)),
    A('ultimate', 'Ultimate!', 'Land an ultimate', 1, 'star', 'Fight', lambda S: S['ults'] >= 1,
      lambda S: next((e['ult'][0] for e in S['log'] if e.get('ult')), None), _n('ults', 1)),
    A('hat_trick', 'Hat Trick', 'One program wins 3 matches in a row', 1, 'flame', 'Fight', lambda S: S['best_streak'] >= 3,
      _streak_by(3), _n('best_streak', 3)),
    A('flawless', 'Flawless', 'Win a round without losing any HP', 2, 'heart', 'Fight', lambda S: S['flawless'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('fl')), _n('flawless', 1)),
    A('comeback', 'Comeback', 'Lose round 1, then win the match', 2, 'bolt', 'Fight', lambda S: S['comebacks'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('cb')), _n('comebacks', 1)),
    A('signature', 'Signature Style', 'Land 10 ultimates', 2, 'star', 'Fight', lambda S: S['ults'] >= 10, lambda S: _top(S, 'ults'),
      _n('ults', 10)),
    A('arena_champ', 'Arena Champion', 'Win a match in the arena', 2, 'crown', 'Fight', lambda S: S['arena_wins'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('where') == 'arena'), _n('arena_wins', 1)),
    A('perfect', 'Perfect', 'Win a match 2-0 with both rounds flawless', 3, 'crown', 'Fight', lambda S: S['perfects'] >= 1,
      lambda S: _first(S['log'], lambda e: e.get('pf')), _n('perfects', 1)),
    A('unstoppable', 'Unstoppable', 'One program wins 10 matches in a row', 3, 'flame', 'Fight', lambda S: S['best_streak'] >= 10,
      _streak_by(10), _n('best_streak', 10)),
    # Discovery: seeing what the game has
    A('regular', 'Ten Bouts', 'Watch 10 matches', 1, 'clock', 'Discovery', lambda S: S['matches'] >= 10, None, _n('matches', 10)),
    A('centurion', 'Centurion', 'Watch 100 matches', 2, 'shield', 'Discovery', lambda S: S['matches'] >= 100, None, _n('matches', 100)),
    A('set_piece', 'Cinema', 'See a cinematic set piece in a match', 1, 'eye', 'Discovery', lambda S: len(S['pieces']) >= 1, None,
      lambda S: (min(1, len(S['pieces'])), 1)),
    A('directors_cut', "Director's Cut", 'See every taskbar set piece', 3, 'eye', 'Discovery',
      lambda S: bool(_all_pieces()) and set(_all_pieces()) <= set(S['pieces']), None,
      lambda S: (len(set(_all_pieces()) & set(S['pieces'])), len(_all_pieces()))),
    A('blacksmith', 'Blacksmith', 'Forge a desktop weapon in an arena match', 1, 'hammer', 'Discovery', lambda S: S['forges'] >= 1, None,
      _n('forges', 1)),
    A('forge_master', 'Forge Master', 'Forge 10 desktop weapons', 2, 'hammer', 'Discovery', lambda S: S['forges'] >= 10, None,
      _n('forges', 10)),
    A('full_house', 'Full House', 'Three different programs win a match', 2, 'ring', 'Discovery', lambda S: len(S['winners']) >= 3, None,
      lambda S: (min(3, len(S['winners'])), 3)),
    A('squad', 'Squad', 'Five different programs fight', 2, 'ring', 'Discovery', lambda S: len(S['fought']) >= 5, None,
      lambda S: (min(5, len(S['fought'])), 5)),
    # Partnership: your agents and the fighters, together
    A('job_done', 'Job Done', 'A fighter opens a match with its super because its agent just finished a task', 1, 'check',
      'Partnership', lambda S: S['boosts'] >= 1, lambda S: next((e['boost'][0] for e in S['log'] if e.get('boost')), None),
      _n('boosts', 1)),
    A('teamwork', 'Teamwork', 'Ten matches opened by a finished task', 2, 'check', 'Partnership', lambda S: S['boosts'] >= 10,
      lambda S: _top(S, 'boosts'), _n('boosts', 10)),
    A('self_taught', 'Self-Taught', 'A fighter teaches itself a new move', 1, 'bolt', 'Discovery',
      lambda S: S['learn']['learned'] >= 1, lambda S: S['learn']['first'].get('any'),
      lambda S: (min(1, S['learn']['learned']), 1)),
    A('student', 'Student of the Game', 'A fighter learns a counter to the attack that keeps hitting it', 2, 'shield', 'Discovery',
      lambda S: S['learn']['by_how'].get('counter', 0) >= 1, lambda S: S['learn']['first'].get('counter'),
      lambda S: (min(1, S['learn']['by_how'].get('counter', 0)), 1)),
    A('rivalry', 'Old Rivals', 'The same two programs meet 10 times', 2, 'swords', 'Partnership', lambda S: S['pair_max'] >= 10, None,
      _n('pair_max', 10)),
]
del A
IDS = [a.id for a in ACHIEVEMENTS]
BY_ID = {a.id: a for a in ACHIEVEMENTS}


def evaluate(rec, hist=None):
    """-> {id: program id | None} for every badge the record meets right now."""
    S = stats(rec)
    out = {}
    for a in ACHIEVEMENTS:
        try:
            if a.met(S):
                out[a.id] = a.by(S) if a.by else None
        except Exception:
            continue
    return out


def progress(rec, hist=None):
    """-> {id: (have, need) | None}: how far each criterion is (shown openly next to every locked badge)."""
    S = stats(rec)
    out = {}
    for a in ACHIEVEMENTS:
        try:
            out[a.id] = a.progress(S) if a.progress else None
        except Exception:
            out[a.id] = None
    return out


def read(p=None) -> dict:
    try:
        d = json.loads(Path(p or path()).read_text(encoding='utf-8'))
        if isinstance(d, dict) and isinstance(d.get('unlocked'), dict):
            d['unlocked'] = {k: v for k, v in d['unlocked'].items() if k in BY_ID and isinstance(v, dict)}
            return d
    except (OSError, ValueError):
        pass
    return {'version': 1, 'unlocked': {}}


def update(rec, hist=None, now=None, p=None):
    """Store newly met badges.  -> [ids newly unlocked] (empty on the very first evaluation: those are seeded silently).
    Unlocks are never removed."""
    now = time.time() if now is None else now
    p = Path(p or path())
    first = not p.exists()
    d = read(p)
    met = evaluate(rec)
    new = [aid for aid in IDS if aid in met and aid not in d['unlocked']]
    if not new and not first:
        return []
    for aid in new:
        d['unlocked'][aid] = {'ts': now, 'by': met[aid]}
    d['version'] = 1
    if first:
        d['seeded'] = now
    write_json_atomic(p, d)
    return [] if first else new


def unlocked(p=None, rec=None, hist=None):
    """Read-only view for the CLI and the card: stored unlocks, plus anything met now that the director has not stored
    yet (ts None).  -> {id: {'ts', 'by'}}."""
    out = {k: dict(v) for k, v in read(p)['unlocked'].items()}
    if rec is not None:
        for aid, by in evaluate(rec).items():
            out.setdefault(aid, {'ts': None, 'by': by})
    return out


# ---------------------------------------------------------------- the scoreboard toast
class Toaster:
    """Director side.  poll(now) re-evaluates when record.json changes (checked at most every `every_s`) and returns the
    text of the toast showing now ('First KO'), or None.  Each new badge shows for TOAST_S seconds, one after another."""

    def __init__(self, record_path=None, ach_path=None, every_s=1.0, wall=time.time):
        self.rp, self.ap = record_path, ach_path
        self.every_s, self.wall = every_s, wall
        self.sig = None
        self.next = -1e18
        self.queue = []
        self.showing = None                     # (text, until)

    def _sig(self):
        from . import rounds
        try:
            st = os.stat(self.rp or rounds.record_path())
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        try:                                    # learning.json too: Self-Taught / Student of the Game unlock when it changes
            from . import learning
            lt = os.stat(learning.path())
            return (sig, (lt.st_mtime_ns, lt.st_size))
        except (OSError, ImportError):
            return (sig, None) if sig is not None else None

    def check(self, now):
        sig = self._sig()
        if sig == self.sig:
            return []
        self.sig = sig
        if sig is None:
            return []
        from . import records
        new = update(records.read(self.rp), now=now, p=self.ap)
        self.queue.extend(BY_ID[a].name for a in new)
        return new

    def poll(self, now=None):
        now = self.wall() if now is None else now
        if now >= self.next:
            self.next = now + self.every_s
            try:
                self.check(now)
            except Exception:
                pass
        if self.showing and now >= self.showing[1]:
            self.showing = None
        if self.showing is None and self.queue:
            self.showing = (self.queue.pop(0), now + TOAST_S)
        return self.showing[0] if self.showing else None


# ---------------------------------------------------------------- `minis.py achievements`
def lines(rec, ach_path=None, label=None, tz=None):
    """The CLI listing: one line per badge, grouped by family, unlocked first; names and numbers only."""
    from .sources import short_label
    label = label or short_label
    have = unlocked(ach_path, rec)
    prog = progress(rec)
    out = [f'achievements: {sum(1 for a in IDS if a in have)} of {len(IDS)} unlocked (every criterion is listed; none are secret)']
    for fam in FAMILIES:
        out.append(f'{fam}:')
        for a in sorted((a for a in ACHIEVEMENTS if a.family == fam), key=lambda a: (a.id not in have, IDS.index(a.id))):
            if a.id in have:
                h = have[a.id]
                when = datetime.datetime.fromtimestamp(h['ts'], tz).strftime('%Y-%m-%d') if h.get('ts') else 'now'
                who = f", by {label(h['by'])}" if h.get('by') else ''
                out.append(f"  [x] {a.name:16s} {a.desc} ({when}{who})")
            else:
                pg = prog.get(a.id)
                out.append(f"  [ ] {a.name:16s} {a.desc}" + (f' ({pg[0]}/{pg[1]})' if pg else ''))
    return out


def career_lines(rec, label=None):
    """Career table + head-to-head lines (`minis.py card` prints them).  Names and numbers only."""
    from .sources import short_label
    label = label or short_label
    car = careers(rec)
    if not car:
        return ['careers: no matches recorded yet']
    out = ['careers (lifetime):']
    for sid, c in sorted(car.items(), key=lambda kv: (-kv[1]['w'], kv[0])):
        nxt = f", {c['rank_next'] - c['w']} wins to the next rank" if c['rank_next'] else ''
        out.append(f"  {label(sid):12s} {c['w']:>4}-{c['l']:<4} {c['pct']:>3}%  {c['rank']:7s} KO {c['ko']}, best streak "
                   f"{c['best_streak']}, ultimates {c['ults']}, flawless rounds {c['flawless']}, comebacks {c['comebacks']}{nxt}")
    out.append('head to head:')
    for h in pairs(rec)[:12]:
        a, b = h['a'], h['b']
        if h['wins'][b] > h['wins'][a]:
            a, b = b, a
        out.append(f"  {label(a)} vs {label(b)} {h['wins'][a]}-{h['wins'][b]} (last 10: {h['last10'][a]}-{h['last10'][b]})")
    return out


def cmd(args=None, out=print):
    from . import records
    for ln in lines(records.read()):
        out(ln)
    return 0
