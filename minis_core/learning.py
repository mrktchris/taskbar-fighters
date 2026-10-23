r"""Fighters teach themselves new moves (docs/LEARNING.md).

Each PROGRAM (source id: claude, codex, grok, ...) keeps a skill memory in <data dir>/learning.json: counters and seeds
only - move ids, character ids, program ids, operator names and numbers.  Nothing from the agents' content, no
network, no prompts.  Experience comes from the fights the fighter really has on the taskbar and from its idle practice
(the shadowboxing it already does while its agent works):

  used[move]    how often it threw a move, and how it went (hit / whiff / block)        -> MASTERY: an evolved variant
  taken[kind]   how often it was hit by a slash / blunt / pierce                       -> COUNTER: a riposte that answers it
  seen[prog:move] an opponent's weapon move watched or taken                           -> MIMICRY: a crude borrowed copy
  trial         a procedurally generated variant it is trying out while shadowboxing  -> INVENTION: learned after N reps
  wins / losses / pieces                                                               (the record, for the book and the CLI)

A variant is (character, base move, operator, seed[, source character]) - see art/evolve.py - and is regenerated from
those numbers wherever it is needed, so nothing is shipped and two machines agree.  Remap variants (retime, twin, feint)
re-sequence the frames the sheet already has (minis_core/movegen.py: every install, pip and the Windows zip included);
render variants (amplify, spin, mimic) are drawn by the rig into a cache under the data folder, and need art/evolve.py,
so only a source checkout redraws.  A packaged install learns mastery / counters / inventions through the remap
operators and never learns a borrowed (mimic) move.

Determinism between the two fighter processes: the INVITER reads learning.json at plan time and writes both sides' kits
INTO THE PLAN (`plan['learn'] = {'v': file version, 'kit': {slot: {move id: {'w', 'kind', 'vs', 'spec'}}}}`); both
processes build the rows from those specs (`prepare`), so they render the same kit even if the file changes between the
invite and the accept.  Every row lives in a LearnedAtlas overlay (a subclass of Atlas that shares the base sheets and
adds rows), served by a LearnedLibrary that wraps the Library the brain and the HD renderer already use.

Hooks into the engine (all listed in docs/LEARNING.md): choreo.Picker takes the kit (weights, counters); rounds.Bout
passes it per slot; brain.Brain owns a Learner (plan, prepare, after_bout, practice, home, banner).
"""
from __future__ import annotations
import atexit, importlib.util, json, math, os, random, subprocess, sys, time, weakref
from collections import Counter
from pathlib import Path

from . import config as cfgmod, paths as _paths
from .atlas import Atlas
from .bus import write_json_atomic

VERSION = 1
FILE = 'learning.json'
MASTERY_N = 30               # uses of one move (fights count 1, practice reps 1/2) -> its evolved variant
COUNTER_K = 45               # hits taken of one kind (slash / blunt / pierce) -> a counter that answers it
MIMIC_M = 24                 # one opponent move watched or taken this often -> a borrowed copy
INVENT_REPS = 40             # practice reps of a trial variant -> learned (a rep plays the trial PRACTICE_P of the time)
TRIAL_GAP = 90               # shadowbox reps after an invention before the next trial starts
KIT_MAX = 6                  # learned moves a program keeps
MASTERY_MAX = 3              # ... of which at most this many are evolved variants, so counters, borrowed moves and inventions keep room
COUNTER_MAX = 2              # ... and at most this many counters
LEARN_GAP_BOUTS = 15         # at most one new move every this many bouts: a kit grows over weeks of fights, never in a burst
COUNTER_DECAY_K = 3          # a counter only fires on a parry: it goes stale three times slower than a strike
DECAY_BOUTS = 25             # bouts without using a learned move -> its weight starts halving every 10 more...
FORGET_BOUTS = 60            # ... and after this many it is forgotten (its counters stay)
EVICT_BOUTS = DECAY_BOUTS    # a full kit makes room only with a move unused this long: learning never churns
W_BASE, W_LEVEL, W_MAX = 0.6, 0.15, 1.2
PARRY_K = 1.6                # a learned counter widens the parry window against its kind
BANNER_S = 2.8
TOAST_S = 3.0
PRACTICE_P = 0.35            # a shadowbox rep plays the trial / a learned move this often (seeded by the brain)
LOCK_TIMEOUT_S = 0.5
MAX_BUILDS = 2               # render builds running at once (each one python process); more wait their turn
BUILD_TIMEOUT_S = 180.0      # a build still running after this is killed (only our own children) and reaped
KINDS, HIT_KINDS = ('strike', 'counter'), ('slash', 'blunt', 'pierce')
HOWS = ('mastery', 'counter', 'mimic', 'invention')
BOUT_KINDS = ('spar', 'clash', 'match')
_EVOLVE = None
_LIBS = weakref.WeakSet()
_KNOWN = {}                  # character -> {move id: spec} every row this process has been asked for (new wrappers load them)


# ---------------------------------------------------------------- art/evolve.py (the synthesis module, loaded by path)
def evolve():
    """The move generator: art/evolve.py in a source checkout (all six operators, the redrawn tier included), else the
    packaged minis_core.movegen (retime / twin / feint; its `available()` is False, so nothing is ever redrawn)."""
    global _EVOLVE
    if _EVOLVE is None:
        p = _paths.REPO / 'art' / 'evolve.py'
        mod = None
        if _paths.checkout() and p.is_file():
            try:
                spec = importlib.util.spec_from_file_location('evolve', p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                mod = None
        if mod is None:
            from . import movegen as mod
        _EVOLVE = mod
    return _EVOLVE


def enabled():
    return evolve() is not None


def redraws():
    """True when this install can redraw moves (amplify / spin / mimic): a source checkout with art/."""
    ev = evolve()
    return bool(ev is not None and ev.available())


# ---------------------------------------------------------------- validation (everything that arrives from a file or a bus plan)
def valid_id(x):
    from .movegen import valid_id as v
    return v(x)


def valid_spec(spec):
    """[character, base, op, seed, source | None, how] with plain ids, a known operator and how, a bounded int seed."""
    ev = evolve()
    if not isinstance(spec, (list, tuple)) or len(spec) != 6 or ev is None:
        return False
    ch, base, op, seed, src, how = spec
    return (valid_id(ch) and valid_id(base) and op in ev.OPS and isinstance(seed, int) and not isinstance(seed, bool)
            and 0 <= seed < 2 ** 31 and (src is None or valid_id(src)) and how in HOWS)


def _num(w, lo, hi):
    return isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and lo <= w <= hi


def valid_kit_entry(mid, v, character):
    """One kit entry from a plan: its spec belongs to `character` (the plan's fighter on that slot) and derives `mid`, its
    weight is a finite number in 0..W_MAX, its kind and hit kind are known."""
    if not valid_id(mid) or not isinstance(v, dict) or not valid_spec(v.get('spec')):
        return False
    spec = v['spec']
    if spec[0] != character or move_id_of(spec) != mid:
        return False
    if not _num(v.get('w'), 0.0, W_MAX) or v.get('kind', 'strike') not in KINDS:
        return False
    return v.get('vs') is None or v.get('vs') in HIT_KINDS


# ---------------------------------------------------------------- the file
def path(p=None) -> Path:
    return Path(p) if p else cfgmod.data_dir() / FILE


def read(p=None) -> dict:
    """learning.json as a dict with `v` and `programs` (empty on a missing / broken file)."""
    try:
        d = json.loads(path(p).read_text(encoding='utf-8'))
        if isinstance(d, dict) and isinstance(d.get('programs'), dict):
            d.setdefault('v', 0)
            d.setdefault('version', VERSION)
            return d
    except (OSError, ValueError):
        pass
    return {'version': VERSION, 'v': 0, 'programs': {}}


def update(fn, p=None) -> bool:
    """Read-modify-write under the shared lock (minis_core/filelock.py: an O_EXCL lock file carrying its owner's token, so
    a holder that stalled can never delete a newer owner's lock; Windows delete-pending is retried).  Both fighter
    processes write when a bout ends.  `fn(doc)` edits the dict in place; `v` counts every write.  False when the lock
    could not be taken or the write failed."""
    from . import filelock
    target = path(p)
    with filelock.locked(target, timeout=LOCK_TIMEOUT_S) as ok:
        if not ok:
            return False
        doc = read(target)
        fn(doc)
        doc['v'] = int(doc.get('v', 0)) + 1
        doc['version'] = VERSION
        return write_json_atomic(target, doc)


def program_seed(program) -> int:
    return evolve().hash_str('seed:' + str(program)) & 0x7FFFFFFF if evolve() else 1


def _entry(doc, program, character=None):
    e = doc['programs'].get(program)
    if not isinstance(e, dict):
        e = doc['programs'][program] = dict(character=character, seed=program_seed(program), bouts=0, matches=0, wins=0, losses=0,
                                            practice=0, trials=0, forgotten=0, used={}, taken={}, seen={}, pieces={}, learned={},
                                            pending=[], trial=None)
    if character:
        e['character'] = character
    for k, d in (('used', {}), ('taken', {}), ('seen', {}), ('pieces', {}), ('learned', {}), ('pending', []), ('trial', None)):
        e.setdefault(k, d if not isinstance(d, (dict, list)) else type(d)())
    return e


# ---------------------------------------------------------------- the kit a program fights with
def _idle(rec, bouts):
    idle = max(0, _int(bouts) - _int(rec.get('last', bouts), _int(bouts)))
    return idle // COUNTER_DECAY_K if rec.get('kind') == 'counter' else idle


def _int(v, default=0):
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _weight(rec, bouts):
    lvl = max(0, _int(rec.get('level', 0)))
    w = min(W_MAX, W_BASE + W_LEVEL * lvl)
    idle = _idle(rec, bouts)
    if idle > DECAY_BOUTS:
        w *= 0.5 ** ((idle - DECAY_BOUTS) / 10.0)
    return round(w, 3)


def kit_for(program, character, doc=None):
    """{move id: {'w', 'kind', 'vs', 'spec'}}: the learned moves the program brings to a fight while wearing `character`,
    with weights that grow with mastery and decay with disuse.  Rows learned in another skin stay home."""
    doc = read() if doc is None else doc
    e = (doc.get('programs') or {}).get(program)
    if not isinstance(e, dict):
        return {}
    out = {}
    for mid, rec in (e.get('learned') or {}).items():
        spec = rec.get('spec') if isinstance(rec, dict) else None
        if not valid_spec(spec) or spec[0] != character or move_id_of(spec) != mid:
            continue                                         # a hand-edited or damaged entry never reaches a fight
        kind = rec.get('kind', 'strike') if rec.get('kind', 'strike') in KINDS else 'strike'
        vs = rec.get('vs') if rec.get('vs') in HIT_KINDS else None
        out[mid] = dict(w=float(_weight(rec, e.get('bouts', 0))), kind=kind, vs=vs, spec=list(spec))
    return out


def attach(plan, programs, doc=None):
    """Write both sides' kits into the plan (inviter side).  programs: {slot: program id | None}.  -> plan."""
    if not enabled():
        return plan
    doc = read() if doc is None else doc
    chars = plan.get('chars') or {}
    kits = {}
    for slot, prog in (programs or {}).items():
        if prog and chars.get(slot):
            k = kit_for(prog, chars[slot], doc)
            if k:
                kits[slot] = k
    if kits:
        plan['learn'] = dict(v=int(doc.get('v', 0)), kit=kits)
    else:
        plan.pop('learn', None)
    return plan


# ---------------------------------------------------------------- the overlay atlas and library
class LearnedAtlas(Atlas):
    """An Atlas that shares a base atlas's sheets and adds learned rows: remap rows whose frames point back into a base row,
    and rendered rows read from the cache sheet.  Everything the engine asks (anim, timings, reach, signature) works
    through the inherited methods on the merged `anim`."""

    def __init__(self, base):                         # no Atlas.__init__: everything is borrowed from `base`
        vars(self).update(vars(base))
        self.base = base
        self.anim = dict(base.anim)
        self.meta = dict(base.meta, anims=self.anim)
        self._total = dict(base._total)
        self._crop = {}
        self._ucrop = {}
        self.rows = {}

    def add_remap(self, move_id, entry, base_name):
        entry = dict(entry)
        entry['row'] = -1
        self.anim[move_id] = entry
        self._total[move_id] = sum(int(f['ms']) for f in entry['frames'])
        self.rows[move_id] = ('remap', base_name, [int(f['src']) for f in entry['frames']], None)

    def add_render(self, move_id, entry, sheet):
        entry = dict(entry)
        entry['row'] = -1
        self.anim[move_id] = entry
        self._total[move_id] = sum(int(f['ms']) for f in entry['frames'])
        self.rows[move_id] = ('render', None, None, sheet)

    def frame_image(self, name, i, facing):
        r = self.rows.get(name)
        if r is None:
            return self.base.frame_image(name if name in self.base.anim else 'idle', i if name in self.base.anim else 0, facing)
        kind, base_name, remap, sheet = r
        n = len(self.anim[name]['frames'])
        i = max(0, min(n - 1, int(i)))
        if kind == 'remap':
            return self.base.frame_image(base_name, remap[i], facing)
        key = (name, i, facing >= 0)
        im = self._crop.get(key)
        if im is None:
            cw = self.cell[0]
            row = 0 if facing >= 0 else 1
            im = sheet.crop((i * cw, row * cw, (i + 1) * cw, (row + 1) * cw))
            self._crop[key] = im
        return im

    def unarmed_frame(self, name, i, facing):
        if name in self.rows:
            return self.frame_image(name, i, facing)
        return self.base.unarmed_frame(name, i, facing)

    def grip(self, name, i, facing):
        return None if name in self.rows else self.base.grip(name, i, facing)

    def grip2(self, name, i, facing):
        return None if name in self.rows else self.base.grip2(name, i, facing)


class LearnedLibrary:
    """Wraps an atlas Library: every atlas it serves is a LearnedAtlas carrying the rows this process knows about."""

    def __init__(self, base):
        self.base = base
        self._wrapped = {}
        _LIBS.add(self)

    def wrap(self, atlas):
        if isinstance(atlas, LearnedAtlas):
            return atlas
        key = id(atlas)
        w = self._wrapped.get(key)
        if w is None:
            w = self._wrapped[key] = LearnedAtlas(atlas)
            for spec in list(_KNOWN.get(atlas.character, {}).values()):
                try:
                    load_row(w, spec)
                except Exception:
                    pass
        return w

    def __getitem__(self, character):
        return self.wrap(self.base[character])

    def __contains__(self, character):
        return character in self.base

    def __getattr__(self, k):
        return getattr(self.base, k)


def wrap_library(lib):
    if isinstance(lib, LearnedLibrary):
        return lib
    for w in list(_LIBS):
        if w.base is lib:
            return w
    return LearnedLibrary(lib)


def wrap_atlases(atlases):
    """A plain {character: Atlas} dict -> {character: LearnedAtlas} (tests, previews)."""
    return {c: (a if isinstance(a, LearnedAtlas) else LearnedAtlas(a)) for c, a in atlases.items()}


def move_id_of(spec):
    return evolve().variant_id(spec[1], spec[2], spec[3], spec[5] if len(spec) > 5 else 'mastery')


def row_ready(spec, data_dir=None):
    """A row buildable right now: remap always (if the base exists in the character's atlas); render when cached."""
    ev = evolve()
    if ev is None or not isinstance(spec, (list, tuple)) or len(spec) < 6:
        return False
    if spec[2] in ev.REMAP_OPS:
        return True
    return ev.cached(data_dir or cfgmod.data_dir(), spec[0], move_id_of(spec)) is not None


def load_row(atlas, spec, data_dir=None):
    """Build the learned row `spec` into a LearnedAtlas (both resolutions pick their own frames).  -> True when the row is
    there, False when it cannot be built here (then the bout must not be played with it)."""
    ev = evolve()
    if ev is None or not isinstance(atlas, LearnedAtlas) or not valid_spec(spec) or spec[0] != atlas.character:
        return False
    character, base, op, seed, src, how = list(spec)[:6]
    mid = ev.variant_id(base, op, seed, how)
    _KNOWN.setdefault(character, {})[mid] = list(spec)
    if mid in atlas.rows:
        return True
    if op in ev.REMAP_OPS:
        e = atlas.base.anim.get(base)
        if e is None:
            return False
        entry = ev.remap(dict(e, name=base), op, seed, how=how)
        if entry is None or not ev.remap_ok(atlas.base, base, op):      # timing and silhouette QA, at this atlas's resolution
            return False
        atlas.add_remap(mid, entry, base)
        return True
    dd = data_dir or cfgmod.data_dir()
    meta = ev.cached(dd, character, mid)
    if meta is None:
        return False
    res = str(2 if atlas.res >= 2 else 1)
    pr = (meta.get('res') or {}).get(res)
    sheet = ev.load_sheet(dd, character, mid, int(res))
    if not pr or sheet is None:
        return False
    entry = dict(meta['entry'], frames=pr['frames'], reach=pr.get('reach'))
    if entry.get('shake'):
        entry['shake'] = dict(frames=int(entry['shake']['frames']), amp=int(entry['shake']['amp']) * int(res))
    atlas.add_render(mid, entry, sheet)
    return True


def prepare(plan, atlases, data_dir=None):
    """Both sides call this before a bout (brain._possible): every row the plan's kits name is loaded into the atlases the
    bout will use.  -> False when one cannot be built here, so the invite is declined instead of playing a different kit."""
    learn = plan.get('learn') if isinstance(plan, dict) else None
    if not learn:
        return True
    if evolve() is None:
        return False
    chars = plan.get('chars') or {}
    kits = learn.get('kit') if isinstance(learn, dict) else None
    if not isinstance(kits, dict):
        return False
    for slot, kit in kits.items():                          # validate everything before building anything
        ch = chars.get(slot)
        if slot not in ('a', 'b') or not valid_id(ch) or not isinstance(kit, dict) or len(kit) > KIT_MAX:
            return False
        if not all(valid_kit_entry(mid, v, ch) for mid, v in kit.items()):
            return False
    for slot, kit in kits.items():
        ch = chars.get(slot)
        try:
            atlas = atlases[ch]
        except Exception:
            return False
        if not isinstance(atlas, LearnedAtlas):
            if isinstance(atlases, LearnedLibrary):
                atlas = atlases.wrap(atlas)
            else:
                return False
        for mid, v in kit.items():
            spec = v['spec']
            if not load_row(atlas, spec, data_dir):
                return False
            for lib in list(_LIBS):                          # the HD renderer's library draws the same rows
                try:
                    load_row(lib.wrap(lib.base[spec[0]]), spec, data_dir)
                except Exception:
                    pass
    return True


# ---------------------------------------------------------------- experience -> learning events
def _hit_kind(atlas, move):
    return ((atlas.anim.get(move) or {}).get('hit')) if atlas is not None else None


def observe(program, character, opp_program, opp_character, summary, slot, kind, atlases, p=None, now=None):
    """Fold one finished bout into `program`'s memory (its own side only; the other process folds the other side) and
    decide at most one learning event.  -> the unlock dict {'id', 'how', 'spec', 'name'} or None."""
    if not enabled() or not isinstance(summary, dict) or kind not in BOUT_KINDS or not program:
        return None
    ev = evolve()
    beats = summary.get('beats') or {}
    other = 'b' if slot == 'a' else 'a'
    mine, theirs = beats.get(slot) or [], beats.get(other) or []
    try:
        A = atlases[character]
        D = atlases[opp_character] if opp_character else None
    except Exception:
        A = D = None
    used, taken, seen = Counter(), Counter(), Counter()
    hits, whiffs, blocks = Counter(), Counter(), Counter()
    for b in mine:
        if not isinstance(b, dict) or b.get('kind') not in ('strike', 'special', 'super', 'ultimate', 'counter') or not isinstance(b.get('anim'), str):
            continue
        m = b['anim']
        used[m] += 1
        o = b.get('outcome')
        if o in ('hit', 'guard_break'):
            hits[m] += 1
        elif o in ('whiff',):
            whiffs[m] += 1
        else:
            blocks[m] += 1
    for b in theirs:
        if not isinstance(b, dict) or b.get('kind') not in ('strike', 'special', 'super', 'ultimate', 'counter') or not isinstance(b.get('anim'), str):
            continue
        m = b['anim']
        if b.get('outcome') in ('hit', 'guard_break'):
            hk = _hit_kind(D, m)
            if hk in ('slash', 'blunt', 'pierce'):
                taken[hk] += 1
        if opp_program and D is not None and ev.eligible_base(D.anim.get(m)) and (D.anim.get(m) or {}).get('type') != 'learned':
            seen[f'{opp_program}:{m}'] += 1
    won = kind == 'match' and summary.get('winner') == slot
    lost = kind == 'match' and summary.get('loser') == slot
    pieces = [x for x in ((summary.get('story') or {}).get('pieces') or []) if isinstance(x, str)]
    out = {}

    def fold(doc):
        e = _entry(doc, program, character)
        e['bouts'] = int(e.get('bouts', 0)) + 1
        if kind == 'match':
            e['matches'] = int(e.get('matches', 0)) + 1
            e['wins'] = int(e.get('wins', 0)) + (1 if won else 0)
            e['losses'] = int(e.get('losses', 0)) + (1 if lost else 0)
        for m, n in used.items():
            u = e['used'].setdefault(m, {'n': 0, 'hit': 0, 'whiff': 0, 'block': 0, 'prac': 0})
            u['n'] = int(u.get('n', 0)) + n
            u['hit'] = int(u.get('hit', 0)) + hits[m]
            u['whiff'] = int(u.get('whiff', 0)) + whiffs[m]
            u['block'] = int(u.get('block', 0)) + blocks[m]
            if m in e['learned']:
                e['learned'][m]['uses'] = int(e['learned'][m].get('uses', 0)) + n
                e['learned'][m]['last'] = e['bouts']
                lvl = int(e['learned'][m].get('uses', 0)) // MASTERY_N
                e['learned'][m]['level'] = max(int(e['learned'][m].get('level', 0)), lvl)
        for k, n in taken.items():
            e['taken'][k] = int(e['taken'].get(k, 0)) + n
        for k, n in seen.items():
            e['seen'][k] = int(e['seen'].get(k, 0)) + n
        for pc in pieces:
            e['pieces'][pc] = int(e['pieces'].get(pc, 0)) + 1
        _decay(e)
        got = _learn_step(e, A, atlases, opp_program, opp_character, now)
        if got:
            out.update(got)
    update(fold, p)
    return out or None


def _decay(e):
    """Forget learned moves unused for FORGET_BOUTS bouts (their weight had already decayed to nothing)."""
    bouts = int(e.get('bouts', 0))
    for mid in list(e['learned']):
        rec = e['learned'][mid]
        if _idle(rec, bouts) >= FORGET_BOUTS:
            del e['learned'][mid]
            e['forgotten'] = int(e.get('forgotten', 0)) + 1


def paced(e):
    """LEARN_GAP_BOUTS have passed since the last new move (the first one waits for none)."""
    last = e.get('last_learn')
    return last is None or int(e.get('bouts', 0)) - int(last) >= LEARN_GAP_BOUTS


def has_room(e):
    """A kit under the cap, or one holding a move unused for EVICT_BOUTS bouts (that one makes room).  A full kit of moves
    still in use learns nothing new: the loop never churns."""
    if len(e['learned']) < KIT_MAX:
        return True
    bouts = int(e.get('bouts', 0))
    return any(_idle(r, bouts) >= EVICT_BOUTS for r in e['learned'].values())


def _make_room(e):
    if len(e['learned']) < KIT_MAX:
        return True
    bouts = int(e.get('bouts', 0))
    stale = [(mid, r) for mid, r in e['learned'].items() if _idle(r, bouts) >= EVICT_BOUTS]
    if not stale:
        return False
    worst = min(stale, key=lambda kv: (int(kv[1].get('uses', 0)), int(kv[1].get('last', 0)), kv[0]))
    del e['learned'][worst[0]]
    e['forgotten'] = int(e.get('forgotten', 0)) + 1
    return True


def _unlock(e, spec, how, kind='strike', vs=None, now=None):
    ev = evolve()
    mid = ev.variant_id(spec[1], spec[2], spec[3], how)
    if mid in e['learned'] or not paced(e):
        return None
    if not _make_room(e):
        return None
    e['last_learn'] = int(e.get('bouts', 0))
    e['learned'][mid] = dict(how=how, spec=[spec[0], spec[1], spec[2], int(spec[3]), spec[4], how], kind=kind, vs=vs, level=0, uses=0,
                             last=int(e.get('bouts', 0)), ts=round(time.time() if now is None else float(now), 1))
    return dict(id=mid, how=how, spec=e['learned'][mid]['spec'], kind=kind, vs=vs,
                name=ev.display_name(mid, spec[1], spec[2], how, spec[3], vs))


def _ops_for(entry, render_ok, atlas=None, base=None):
    ev = evolve()
    ops = [o for o in ev.eligible_remap_ops(entry) if atlas is None or ev.remap_ok(getattr(atlas, 'base', atlas), base, o)]
    if render_ok:
        ops += [o for o in ev.eligible_render_ops(entry) if o != 'mimic']
    return ops


def _render_ok():
    ev = evolve()
    return bool(ev and ev.available() and not os.environ.get('MINIS_LEARN_NO_RENDER'))


def _pending_ready(e, data_dir=None):
    """Render variants waiting for their cache files: the first one that is there (or its remap fallback when the build
    was rejected), as (spec, how, kind, vs), or None."""
    ev = evolve()
    dd = data_dir or cfgmod.data_dir()
    keep = []
    got = None
    for pnd in e.get('pending') or []:
        spec = pnd.get('spec')
        if not isinstance(spec, list) or len(spec) < 6:
            continue
        mid = ev.variant_id(spec[1], spec[2], spec[3], spec[5])
        if got is None and ev.cached(dd, spec[0], mid) is not None:
            got = (spec, pnd.get('how', spec[5]), pnd.get('kind', 'strike'), pnd.get('vs'))
            continue
        if _rejected(dd, spec[0], mid):
            fb = pnd.get('fallback')
            if got is None and fb:
                got = (fb, pnd.get('how', spec[5]), pnd.get('kind', 'strike'), pnd.get('vs'))
            continue
        if int(e.get('bouts', 0)) - int(pnd.get('since', 0)) > 12:      # a build that never came back: let it go
            continue
        spawn_build(spec, dd)                                # still wanted: asked again (deduplicated, capped)
        keep.append(pnd)
    e['pending'] = keep
    return got


def _rejected(data_dir, character, mid):
    return (evolve().cache_root(data_dir) / character / f'{mid}.rejected.json').is_file()


def _queue_render(e, spec, how, kind, vs, fallback):
    """A render variant is built out of process (spawn_build); the unlock waits in `pending` until its cache files exist."""
    for pnd in e.get('pending') or []:
        if pnd.get('spec') == spec:
            return
    e.setdefault('pending', []).append(dict(spec=list(spec), how=how, kind=kind, vs=vs, fallback=list(fallback) if fallback else None,
                                            since=int(e.get('bouts', 0))))
    spawn_build(spec)


def _learn_step(e, A, atlases, opp_program, opp_character, now=None):
    """At most one learning event per bout, in a fixed order: a render build that came back, mastery, a counter, mimicry."""
    ev = evolve()
    if A is None or not has_room(e) or not paced(e):
        return None
    ready = _pending_ready(e)
    if ready:
        spec, how, kind, vs = ready
        got = _unlock(e, spec, how, kind, vs, now)
        if got:
            return got
    character = A.character
    learned_bases = {(r.get('spec') or [None, None])[1]: r for r in e['learned'].values() if r.get('how') == 'mastery'}
    pending_bases = {(p.get('spec') or [None, None])[1] for p in e.get('pending') or []}
    steps = (_step_mastery, _step_counter, _step_mimic)
    k = int(e.get('bouts', 0)) % len(steps)                   # the three sources take turns at the one slot per bout
    for step in steps[k:] + steps[:k]:
        got = step(e, A, atlases, opp_program, opp_character, character, learned_bases, pending_bases, now)
        if got:
            return got
    return None


def _step_mastery(e, A, atlases, opp_program, opp_character, character, learned_bases, pending_bases, now):
    """A move used MASTERY_N times (fights, plus half credit for practice reps) -> its evolved variant."""
    ev = evolve()
    if len(learned_bases) >= MASTERY_MAX:
        return None
    for m, u in sorted(e['used'].items(), key=lambda kv: (-(int(kv[1].get('n', 0)) + int(kv[1].get('prac', 0)) // 2), kv[0])):
        if m in learned_bases or m in pending_bases or not ev.eligible_base(A.anim.get(m)) or (A.anim.get(m) or {}).get('type') == 'learned':
            continue
        if int(u.get('n', 0)) + int(u.get('prac', 0)) // 2 < MASTERY_N:
            continue
        rng = random.Random(ev.hash_str(f'{character}:{m}:mastery'))
        ops = _ops_for(A.anim[m], _render_ok(), A, m)
        if not ops:
            continue
        op = ops[rng.randrange(len(ops))]
        seed = ev.hash_str(f'{character}:{m}') % 100000
        spec = [character, m, op, seed, None, 'mastery']
        if op in ev.REMAP_OPS:
            return _unlock(e, spec, 'mastery', now=now)
        remap_ops = [o for o in ev.eligible_remap_ops(A.anim[m]) if ev.remap_ok(getattr(A, 'base', A), m, o)]
        fb = [character, m, remap_ops[0], seed, None, 'mastery'] if remap_ops else None
        if ev.cached(cfgmod.data_dir(), character, ev.variant_id(m, op, seed, 'mastery')) is not None:
            return _unlock(e, spec, 'mastery', now=now)
        _queue_render(e, spec, 'mastery', 'strike', None, fb)
        return None
    return None


def _step_counter(e, A, atlases, opp_program, opp_character, character, learned_bases, pending_bases, now):
    """Hit by one kind COUNTER_K times -> a sharpened riposte that answers that kind."""
    ev = evolve()
    have_vs = {r.get('vs') for r in e['learned'].values() if r.get('kind') == 'counter'}
    if len(have_vs) >= COUNTER_MAX:
        return None
    rip = next((n for n, a in A.anim.items() if a.get('type') == 'riposte'), None) or ('cross' if 'cross' in A.anim else None)
    if not rip or not ev.eligible_base(A.anim.get(rip)):
        return None
    for hk, n in sorted(e['taken'].items(), key=lambda kv: (-int(kv[1]), kv[0])):
        if int(n) >= COUNTER_K and hk not in have_vs:
            seed = ev.hash_str(f'{character}:counter:{hk}') % 4096
            spec = [character, rip, 'retime', seed, None, 'counter']
            return _unlock(e, spec, 'counter', kind='counter', vs=hk, now=now)
    return None


def _step_mimic(e, A, atlases, opp_program, opp_character, character, learned_bases, pending_bases, now):
    """An opponent's weapon move watched MIMIC_M times -> a crude copy in this weapon family (render tier)."""
    ev = evolve()
    if not (_render_ok() and opp_program and opp_character and opp_character != character):
        return None
    try:
        D = atlases[opp_character]
    except Exception:
        return None
    have_mimic = {(r.get('spec') or [None, None])[1] for r in e['learned'].values() if r.get('how') == 'mimic'}
    for key, n in sorted(e['seen'].items(), key=lambda kv: (-int(kv[1]), kv[0])):
        prog, _, m = key.partition(':')
        if prog != opp_program or int(n) < MIMIC_M or m in have_mimic or m in pending_bases or m in A.anim:
            continue
        if not ev.eligible_base(D.anim.get(m)) or D.anim[m].get('air'):
            continue
        seed = ev.hash_str(f'{character}:mimic:{m}:{opp_character}') % 100000
        spec = [character, m, 'mimic', seed, opp_character, 'mimic']
        if ev.cached(cfgmod.data_dir(), character, ev.variant_id(m, 'mimic', seed, 'mimic')) is not None:
            return _unlock(e, spec, 'mimic', now=now)
        _queue_render(e, spec, 'mimic', 'strike', None, None)
        return None
    return None


# ---------------------------------------------------------------- idle practice -> invention
def practice(program, character, move, atlas, rng=None, p=None, now=None):
    """One shadowbox rep.  Counts practice for `move` and runs the invention loop: with no trial, a seeded (base, operator)
    is tried (remap: built now; render: built out of process); with a trial ready, the rep plays it PRACTICE_P of the time
    and counts toward INVENT_REPS.  -> (move to play, unlock dict | None)."""
    if not enabled() or not program or not isinstance(atlas, LearnedAtlas):
        return move, None
    ev = evolve()
    out = {'play': move, 'unlock': None, 'roll': 1.0}

    def fold(doc):
        e = _entry(doc, program, character)
        e['practice'] = int(e.get('practice', 0)) + 1
        # its own seeded stream (program seed x rep count): the brain's rng, and so its shadowbox sequence, is untouched
        prng = random.Random(int(e.get('seed', 1)) * 1000003 + e['practice'])
        roll = out['roll'] = prng.random()
        u = e['used'].setdefault(move, {'n': 0, 'hit': 0, 'whiff': 0, 'block': 0, 'prac': 0})
        u['prac'] = int(u.get('prac', 0)) + 1
        tr = e.get('trial')
        if tr and (not isinstance(tr, dict) or not isinstance(tr.get('spec'), list) or tr['spec'][0] != character):
            tr = e['trial'] = None
        if tr is None:
            if has_room(e) and int(e.get('practice', 0)) - int(e.get('last_invention', -TRIAL_GAP)) >= TRIAL_GAP:
                e['trial'] = _new_trial(e, atlas)
            return
        spec = tr['spec']
        mid = ev.variant_id(spec[1], spec[2], spec[3], 'invention')
        if spec[2] in ev.RENDER_OPS:
            if _rejected(cfgmod.data_dir(), character, mid):
                e['trial'] = None
                e['trials_failed'] = int(e.get('trials_failed', 0)) + 1
                return
            if ev.cached(cfgmod.data_dir(), character, mid) is None:
                if int(e.get('practice', 0)) - int(tr.get('since', 0)) > 40:
                    e['trial'] = None                        # a build that never came back
                else:
                    spawn_build(spec)                        # asked again if its worker is gone (deduplicated, capped)
                return
        if not load_row(atlas, spec):
            e['trial'] = None
            e['trials_failed'] = int(e.get('trials_failed', 0)) + 1
            return
        if roll < PRACTICE_P:
            out['play'] = mid
            tr['reps'] = int(tr.get('reps', 0)) + 1
            if tr['reps'] >= INVENT_REPS:
                e['trial'] = None
                e['last_invention'] = int(e.get('practice', 0))
                got = _unlock(e, spec, 'invention', now=now)
                if got:
                    out['unlock'] = got
    update(fold, p)
    if out['play'] != move and out['play'] not in atlas.anim:
        out['play'] = move
    practice.last_roll = out['roll']
    return out['play'], out['unlock']


def _new_trial(e, atlas):
    """The next variant to try out, seeded from the program's own seed and its trial count (so the same program invents the
    same things in the same order on any machine)."""
    ev = evolve()
    character = atlas.character
    e['trials'] = int(e.get('trials', 0)) + 1
    rng = random.Random(int(e.get('seed', 1)) * 31 + e['trials'] * 97)
    bases = [n for n, a in atlas.base.anim.items() if ev.eligible_base(a)]
    if not bases:
        return None
    learned_ids = set(e['learned'])
    for _ in range(8):
        base = bases[rng.randrange(len(bases))]
        ops = _ops_for(atlas.base.anim[base], _render_ok(), atlas, base)
        if not ops:
            continue
        op = ops[rng.randrange(len(ops))]
        seed = rng.randrange(1, 1 << 30)
        mid = ev.variant_id(base, op, seed, 'invention')
        if mid in learned_ids or mid in atlas.anim:
            continue
        spec = [character, base, op, seed, None, 'invention']
        if op in ev.REMAP_OPS:
            if ev.remap(dict(atlas.base.anim[base], name=base), op, seed, how='invention') is None:
                continue
        else:
            spawn_build(spec)
        return dict(spec=spec, reps=0, since=int(e.get('practice', 0)))
    return None


_BUILDS = {}                  # tuple(spec) -> (Popen, started monotonic): our own render children


def _mono():
    return time.monotonic()


def active_builds():
    return list(_BUILDS)


def reap_builds():
    """Collect finished render children; kill (our own children only) and collect any that ran past BUILD_TIMEOUT_S."""
    for key, (proc, t0) in list(_BUILDS.items()):
        try:
            rc = proc.poll()
        except Exception:
            rc = -1
        if rc is not None:
            _BUILDS.pop(key, None)
        elif _mono() - t0 > BUILD_TIMEOUT_S:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
            _BUILDS.pop(key, None)


def reset_builds():
    """Stop every render child this process started (at exit, and in tests)."""
    for key, (proc, t0) in list(_BUILDS.items()):
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=1.0)
        except Exception:
            pass
    _BUILDS.clear()


atexit.register(reset_builds)


def spawn_build(spec, data_dir=None):
    """Render a variant out of process (art/evolve.py build ...), so the fighter's redraw loop never stalls on the rig.
    At most MAX_BUILDS at once, one per spec (asking again while it runs is a no-op that answers True), each killed after
    BUILD_TIMEOUT_S.  -> True when a build for `spec` is running, False when none could be started (no rig, the switch
    MINIS_LEARN_NO_RENDER, an invalid spec, or the cap: the caller asks again later)."""
    ev = evolve()
    if ev is None or not ev.available() or os.environ.get('MINIS_LEARN_NO_RENDER') or not valid_spec(spec):
        return False
    reap_builds()
    key = tuple(spec)
    if key in _BUILDS:
        return True
    if len(_BUILDS) >= MAX_BUILDS:
        return False
    dd = str(data_dir or cfgmod.data_dir())
    character, base, op, seed, src, how = list(spec)[:6]
    cmd = [sys.executable, str(_paths.REPO / 'art' / 'evolve.py'), 'build', character, base, op, str(int(seed)), '--how', how, '--data', dd]
    if src:
        cmd += ['--from', src]
    try:
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x08000000                 # CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except OSError:
        return False
    _BUILDS[key] = (proc, _mono())
    return True


# ---------------------------------------------------------------- the brain-side learner
class Learner:
    """One per Brain.  Every hook in brain.py calls one method here; with the art module absent they all return quietly."""

    def __init__(self, brain, on=False):
        self.b = brain
        self.on = bool(on)          # writes experience only when the real fighter process turns it on (minis.py Fighter.setup);
                                    # test brains and the simulator never touch learning.json.  Reading a plan's kit always works.
        self.queue = []                                      # learned moments to show: {'id', 'name', ...}
        self.last_banner = None

    # identities (program ids come from the telemetry snapshot and the partner's bus payload)
    def program(self):
        return getattr(self.b.snap, 'who', None) if self.b.snap is not None else None

    def partner_program(self):
        p = self.b.partner
        return p.get('who') if isinstance(p, dict) else None

    def plan(self, plan):
        if not self.on:
            return plan
        try:
            me, you = self.b.slot, 'b' if self.b.slot == 'a' else 'a'
            return attach(plan, {me: self.program(), you: self.partner_program()})
        except Exception:
            plan.pop('learn', None)
            return plan

    def possible(self, plan):
        try:
            return prepare(plan, self.b.atlases)
        except Exception:
            return not plan.get('learn')

    def after_bout(self, sc, now):
        """A bout this fighter played just ended: fold its own side into learning.json; queue a learned moment."""
        if not self.on or not sc or sc.get('kind') not in BOUT_KINDS or not enabled():
            return None
        try:
            plan = sc.get('plan') or {}
            chars = plan.get('chars') or {}
            you = 'b' if self.b.slot == 'a' else 'a'
            got = observe(self.program(), self.b.character, self.partner_program(), chars.get(you), sc.get('summary'), self.b.slot,
                          sc['kind'], self.b.atlases, now=None)
        except Exception:
            got = None
        if got:
            self._queue(got)
        return got

    def _queue(self, got):
        try:
            for lib in list(_LIBS):
                load_row(lib.wrap(lib.base[got['spec'][0]]), got['spec'])
            load_row(self.b.atlas, got['spec'])
        except Exception:
            pass
        self.queue.append(got)

    def practice(self, move, now):
        """A shadowbox rep: count it, maybe play the trial variant or a learned move instead."""
        if not self.on or not enabled() or not move:
            return move
        try:
            play, got = practice(self.program(), self.b.character, move, self.b.atlas, now=None)
        except Exception:
            return move
        if got:
            self._queue(got)
        roll = getattr(practice, 'last_roll', 1.0)
        if play == move and roll >= 1.0 - 0.34 * (1.0 - PRACTICE_P):   # (the same private draw) a learned move gets its reps too
            mine = {mid for _, mid, _ in learned_list(program=self.program())}
            kit = sorted(m for m in self.b.atlas.rows if m in mine and self.b.atlas.anim[m].get('cat') == 'strike')
            if kit:
                play = kit[int(roll * 997) % len(kit)]
        return play if play in self.b.atlas.anim else move

    def home(self, now):
        """The learned moment, at home and awake: the fighter plays the new move once under a LEARNED banner.  (Each home
        tick also reaps finished or overdue render children.)"""
        if self.on and _BUILDS:
            reap_builds()
        if not self.on or not self.queue or self.b.paused or self.b.mode != 'home' or now < getattr(self.b, 'hold_until', 0.0):
            return False
        st = self.b.state()
        if st in ('sleeping', 'limit') or self.b.anim not in ('idle', 'work', 'type', 'wait', 'rage'):
            return False
        got = self.queue.pop(0)
        if got['id'] not in self.b.atlas.anim:
            return False
        self.b.play(got['id'], now, loop=False)
        self.b.banner = dict(kind='learned', until=now + BANNER_S, x=self.b.x, name=got['name'])
        self.last_banner = got
        return True

    def banner_image(self, fx, banner):
        """The 'LEARNED: <MOVE>' banner image (fx.text_image, the same type as the name banner)."""
        from .fx import text_image
        txt = f"LEARNED: {str(banner.get('name') or '').upper()[:22]}"
        cache = self.__dict__.setdefault('_banners', {})
        if txt not in cache:
            cache[txt] = text_image(txt, 14 * fx.res, (150, 236, 160, 255))
        return cache[txt]


# ---------------------------------------------------------------- read-only views: CLI, book, hover card, scoreboard toast
def learned_list(doc=None, program=None):
    """[(program, move id, record)] of every learned move, newest first."""
    doc = read() if doc is None else doc
    out = []
    for prog, e in sorted((doc.get('programs') or {}).items()):
        if program and prog != program:
            continue
        for mid, rec in (e.get('learned') or {}).items():
            out.append((prog, mid, rec))
    out.sort(key=lambda t: -float(t[2].get('ts', 0) or 0))
    return out


def name_of(mid, rec):
    ev = evolve()
    spec = rec.get('spec') or [None, mid, '', 0]
    if ev is None:
        return mid.replace('_', ' ').title()
    return ev.display_name(mid, spec[1], spec[2], rec.get('how', 'mastery'), spec[3], rec.get('vs'))


def how_line(rec, e=None):
    """'learned by mastery of iai slash (used 14 times)' - the sentence under a learned move."""
    spec = rec.get('spec') or [None, '?', '?', 0, None]
    base = str(spec[1]).replace('_', ' ')
    how = rec.get('how')
    if how == 'mastery':
        n = int(((e or {}).get('used') or {}).get(spec[1], {}).get('n', 0))
        return f'mastered {base} ({n} thrown in fights)' if n else f'mastered {base}'
    if how == 'counter':
        n = int(((e or {}).get('taken') or {}).get(rec.get('vs'), 0))
        return f'learned the hard way: hit by {rec.get("vs")} attacks {n} times'
    if how == 'mimic':
        return f'borrowed from {str(spec[4] or "an opponent").title()} after watching its {base}'
    if how == 'invention':
        return f'invented while shadowboxing (a {spec[2]} variation of {base})'
    return str(how)


def summary_line(program, doc=None):
    """'learned 3 moves' for a hover card, or None."""
    n = len(learned_list(doc, program))
    return None if not n else f'learned {n} move' + ('' if n == 1 else 's')


BOOK_TYPE = {'mastery': 'mastered', 'counter': 'counter', 'mimic': 'borrowed', 'invention': 'invented'}


def book_entries(character, doc=None, program=None, label=None):
    """Entries for the move book's LEARNED tab (collection.learned_entries): every move a program learned while wearing
    `character`, one entry per move (programs that learned the same one share it), newest first.  Each has the book's
    shape - key 'l:<id>', name, type (mastered / counter / borrowed / invented: fits a cell), anim, desc (who and how) -
    plus `programs`, `how` and `spec` (the book builds the row from it)."""
    doc = read() if doc is None else doc
    if label is None:
        try:
            from .sources import short_label as label
        except Exception:
            label = str
    by = {}
    for prog, mid, rec in learned_list(doc, program):
        spec = rec.get('spec') or []
        if len(spec) < 6 or spec[0] != character:
            continue
        e = (doc.get('programs') or {}).get(prog) or {}
        if mid not in by:
            by[mid] = dict(key='l:' + mid, name=name_of(mid, rec), type=BOOK_TYPE.get(rec.get('how'), 'learned'), anim=mid, absent=False,
                           programs=[], how=rec.get('how'), spec=list(spec), lines=[])
        by[mid]['programs'].append(prog)
        by[mid]['lines'].append(f'{label(prog)} {how_line(rec, e)}')
    out = []
    for mid, ent in by.items():
        ent['desc'] = '; '.join(ent.pop('lines'))
        out.append(ent)
    return out


def first_by(how='any', doc=None):
    """The program that learned the earliest move (of kind `how`, or any), for an achievement's 'by'; None if none."""
    best = None
    for prog, mid, rec in learned_list(doc):
        if how != 'any' and rec.get('how') != how:
            continue
        ts = float(rec.get('ts', 0) or 0)
        if best is None or ts < best[0]:
            best = (ts, prog)
    return best[1] if best else None


def stats(doc=None):
    """Numbers for badges and the card: {'learned': total, 'by_how': {...}, 'programs': {id: n}, 'forgotten': n}."""
    doc = read() if doc is None else doc
    by_how, progs = Counter(), {}
    forgotten = 0
    for prog, e in (doc.get('programs') or {}).items():
        progs[prog] = len(e.get('learned') or {})
        forgotten += int(e.get('forgotten', 0) or 0)
        for rec in (e.get('learned') or {}).values():
            by_how[rec.get('how', '?')] += 1
    return dict(learned=sum(progs.values()), by_how=dict(by_how), programs=progs, forgotten=forgotten, v=int(doc.get('v', 0)))


class Toaster:
    """Director side (scoreboard): poll(now) -> 'Claude: Iai Slash II' while a new learned move should show, else None.
    Re-reads learning.json (checked at most every `every_s`).  The scoreboard shares one toast row between this and the
    achievement badges through ToastSlot, which calls check() and drains `queue`."""

    def __init__(self, p=None, every_s=1.0, wall=time.time, label=None):
        self.p, self.every_s, self.wall = p, every_s, wall
        self.label = label
        self.seen = None
        self.next = -1e18
        self.queue = []
        self.showing = None

    def check(self, now):
        doc = read(self.p)
        have = {(prog, mid) for prog, mid, _ in learned_list(doc)}
        if self.seen is None:
            self.seen = have                                  # the first look seeds silently: an old file never floods the board
            return []
        new = sorted(have - self.seen)
        self.seen = have
        for prog, mid in new:
            rec = (doc['programs'].get(prog) or {}).get('learned', {}).get(mid) or {}
            lab = self.label(prog) if self.label else prog
            self.queue.append(f'{lab}: {name_of(mid, rec)}')
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


class ToastSlot:
    """The scoreboard's ONE toast row, shared by every source that queues toasts (achievements.Toaster: 'UNLOCKED <badge>',
    learning.Toaster: 'LEARNED <program>: <move>').  Each source keeps finding new items through its own check(now); this
    drains them into one FIFO and shows one at a time for TOAST_S seconds, in the order they arrived: two unlocks at once
    queue, never overlap.  poll(now) -> (kind, text) showing now, or None."""

    def __init__(self, sources, every_s=1.0, wall=time.time):
        self.sources = list(sources)                         # [(kind, toaster with .check(now) and .queue)]
        self.every_s, self.wall = every_s, wall
        self.next = -1e18
        self.queue = []
        self.showing = None                                  # (kind, text, until)

    def poll(self, now=None):
        now = self.wall() if now is None else now
        if now >= self.next:
            self.next = now + self.every_s
            for kind, src in self.sources:
                try:
                    src.check(now)
                except Exception:
                    pass
                while getattr(src, 'queue', None):
                    self.queue.append((kind, src.queue.pop(0)))
        if self.showing and now >= self.showing[2]:
            self.showing = None
        if self.showing is None and self.queue:
            kind, text = self.queue.pop(0)
            self.showing = (kind, text, now + TOAST_S)
        return (self.showing[0], self.showing[1]) if self.showing else None


def toast_slot(wall=time.time, label=None):
    """The director's shared slot: achievements first in the list (a badge and the move that earned it arrive together)."""
    from . import achievements
    if label is None:
        try:
            from .sources import short_label as label
        except Exception:
            label = None
    return ToastSlot([('unlocked', achievements.Toaster(wall=wall)), ('learned', Toaster(wall=wall, label=label))], wall=wall)


# ---------------------------------------------------------------- privacy
ID_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789_:-.')


def audit_privacy(doc):
    """Every leaf of learning.json must be a number, a bool, None, or a short lowercase id (move / character / program /
    operator / how).  -> [paths of offending leaves]; empty is clean."""
    bad = []

    def walk(v, where):
        if isinstance(v, dict):
            for k, x in v.items():
                if not isinstance(k, str) or len(k) > 64 or any(c not in ID_CHARS for c in k.lower()) or k != k.lower():
                    bad.append(where + '/' + str(k)[:20] + ' (key)')
                walk(x, where + '/' + str(k)[:20])
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f'{where}[{i}]')
        elif isinstance(v, str):
            if len(v) > 48 or any(c not in ID_CHARS for c in v) or ' ' in v:
                bad.append(where)
        elif v is None or isinstance(v, (bool, int, float)):
            return
        else:
            bad.append(where)
    walk(doc, '')
    return bad


# ---------------------------------------------------------------- `minis.py learned [program]`
def lines(doc=None, program=None, label=None):
    doc = read() if doc is None else doc
    lab = label or (lambda s: s)
    progs = doc.get('programs') or {}
    if program and program not in progs:
        return [f'{program}: nothing learned yet (no fights recorded for it)']
    out = []
    st = stats(doc)
    out.append(f"learned moves: {st['learned']} across {len([p for p, n in st['programs'].items() if n])} programs"
               + (f", {st['forgotten']} forgotten" if st['forgotten'] else '') + ('' if redraws() else ' (this install learns re-timed / re-sequenced moves; redrawn ones need a source checkout)'))
    for prog, e in sorted(progs.items()):
        if program and prog != program:
            continue
        L = e.get('learned') or {}
        out.append(f"{lab(prog)} as {e.get('character')}: {len(L)} learned, {int(e.get('bouts', 0))} bouts, {int(e.get('wins', 0))}-{int(e.get('losses', 0))}, "
                   f"{int(e.get('practice', 0))} practice reps")
        for mid, rec in sorted(L.items(), key=lambda kv: -float(kv[1].get('ts', 0) or 0)):
            out.append(f"  {name_of(mid, rec):24s} {how_line(rec, e)}; used {int(rec.get('uses', 0))} times, level {int(rec.get('level', 0))}")
        tr = e.get('trial')
        if isinstance(tr, dict) and isinstance(tr.get('spec'), list):
            s = tr['spec']
            out.append(f"  trying out: a {s[2]} variation of {str(s[1]).replace('_', ' ')} ({int(tr.get('reps', 0))}/{INVENT_REPS} reps)")
        for pnd in e.get('pending') or []:
            s = pnd.get('spec') or []
            if len(s) >= 3:
                out.append(f"  building: {s[2]} variant of {str(s[1]).replace('_', ' ')} (render)")
    return out


def cmd(args=None, out=print):
    try:
        from .sources import short_label
    except Exception:
        short_label = None
    for ln in lines(program=getattr(args, 'program', None), label=short_label):
        out(ln)
    return 0


# ---------------------------------------------------------------- the balance simulation
def simulate(n=300, seed0=1, programs=None, p=None, practice_reps=3, atlases=None, fx=None, progress=None):
    """Play `n` seeded matches between programs (default: four programs over four characters) through the real
    rounds.make_match with learning switched on, with `practice_reps` shadowbox reps between matches, writing to the
    learning file `p` (a temp dir in tests).  -> dict: learned per program over time, kit sizes, top move share per
    character, learned-move share of all attacks, forgotten count, time to first unlock."""
    from . import rounds, fx as fxmod
    from .atlas import Library
    ev = evolve()
    progs = programs or [('claude', 'claude'), ('codex', 'codex'), ('gemini', 'gemini'), ('knight', 'knight')]
    lib = LearnedLibrary(Library()) if atlases is None else atlases
    fxd = fx or fxmod.default()
    per = {}
    attacks = Counter()
    learned_hits = Counter()
    first = {}
    pairs = [(a, b) for a in progs for b in progs if a != b]
    rng = random.Random(seed0)
    rows = []
    for i in range(n):
        (pa, ca), (pb, cb) = pairs[i % len(pairs)]
        plan = dict(kind='match', left='a', right='b', pos={'a': 500.0, 'b': 532.0}, t0=1000.0, seed=seed0 + i, chars={'a': ca, 'b': cb},
                    mode='decided', scores={'a': 100.0, 'b': 100.0}, id=f'sim:{i}', deadline=1003.0, span=60.0)
        attach(plan, {'a': pa, 'b': pb}, read(p))
        if not prepare(plan, lib):
            plan.pop('learn', None)
        atl = {ca: lib[ca], cb: lib[cb]}
        tl, t_end, s = rounds.make_match(plan, atl, fxd)
        for slot, prog, ch, oprog, och in (('a', pa, ca, pb, cb), ('b', pb, cb, pa, ca)):
            c = per.setdefault(ch, Counter())
            for b in s['beats'][slot]:
                if b.get('kind') in ('strike', 'special', 'super', 'ultimate', 'counter'):
                    c[b['anim']] += 1
                    attacks[ch] += 1
                    if (lib[ch].anim.get(b['anim']) or {}).get('type') == 'learned':
                        learned_hits[ch] += 1
            got = observe(prog, ch, oprog, och, s, slot, 'match', lib, p=p)
            if got and prog not in first:
                first[prog] = i + 1
            for _ in range(practice_reps):
                pool = [m for m in ('jab', 'cross', 'uppercut', 'low_kick', 'roundhouse') if m in lib[ch].anim]
                practice(prog, ch, pool[rng.randrange(len(pool))], lib[ch], rng, p=p)
        if progress and (i + 1) % progress == 0:
            d = read(p)
            rows.append((i + 1, {pr: len((d['programs'].get(pr) or {}).get('learned') or {}) for pr, _ in progs}))
    doc = read(p)
    kits = {pr: sorted((doc['programs'].get(pr) or {}).get('learned') or {}) for pr, _ in progs}
    top = {}
    for ch, c in per.items():
        tot = sum(c.values())
        m, k = c.most_common(1)[0] if c else ('-', 0)
        top[ch] = dict(move=m, share=round(k / float(max(1, tot)), 3), distinct=len(c), learned_share=round(learned_hits[ch] / float(max(1, tot)), 3),
                       learned_moves=sorted(x for x in c if (lib[ch].anim.get(x) or {}).get('type') == 'learned'))
    st = stats(doc)
    return dict(matches=n, kits=kits, kit_sizes={pr: len(k) for pr, k in kits.items()}, kit_max=KIT_MAX, top=top, first_unlock=first,
                by_how=st['by_how'], forgotten=st['forgotten'], over_time=rows, privacy=audit_privacy(doc), max_share=max([t['share'] for t in top.values()] or [0]))


if __name__ == '__main__':
    import tempfile
    if len(sys.argv) > 1 and sys.argv[1] == 'sim':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        d = Path(tempfile.mkdtemp(prefix='minis-learn-sim-'))
        os.environ.setdefault('MINIS_LEARN_NO_RENDER', '1')
        print(json.dumps(simulate(n, p=d / FILE, progress=max(1, n // 12)), indent=1))
    else:
        print('usage: python -m minis_core.learning sim [n]')
