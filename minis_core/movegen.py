"""The no-new-art half of move synthesis (docs/LEARNING.md), shipped in the package so EVERY install can learn.

A learned move is (character, base move, operator, seed[, source character]).  The operators here - `retime` (a faster
startup, a harder snap), `twin` (the first cut pulled, a re-chamber, the second cut lands) and `feint` (a stutter
between two wind-up keys, then the real strike) - re-sequence and re-time the frames a character's sheet already has, so
they need no rig and write no image: minis_core.learning.LearnedAtlas draws a learned row by pointing its frames back
into the base row.  Their QA (the fluid-pass timing rules, and the silhouette rule that a feint / twin really shows two
different shapes) runs on the shipped frames, also here.

The REDRAWN operators (`amplify`, `spin`, `mimic`) need the rig in art/ and so only a source checkout has them:
art/evolve.py re-exports everything below and adds that tier (and overrides `available` / `eligible_render_ops`).  In a
pip / zip install `available()` is False and `eligible_render_ops()` is empty, so learning never queues a redraw there.
The learned-move cache helpers (a capped, least-recently-used folder under the data dir) live here too: they are plain
file operations, and a cached redraw made in a checkout still plays in that same data folder.
"""
from __future__ import annotations
import json, os, random, re, time
from pathlib import Path

ID_RE = re.compile(r'[a-z0-9_]{1,48}')      # character, move and source ids: the only names that ever reach a path


def valid_id(s):
    """A character / move / program id: 1-48 of [a-z0-9_] (what the art and the generator produce).  Anything else - a
    path separator, '..', a drive, upper case, a space - is refused before it can name a file."""
    return isinstance(s, str) and ID_RE.fullmatch(s) is not None

VERSION = 2                                  # bump when a variant's frames would change: cached renders are re-made
REMAP_OPS = ('retime', 'twin', 'feint')
RENDER_OPS = ('amplify', 'spin', 'mimic')
OPS = REMAP_OPS + RENDER_OPS
SUFFIX = {'retime': 'ii', 'twin': 'twin', 'feint': 'feint', 'amplify': 'grand', 'spin': 'spiral', 'mimic': 'borrowed'}
LABEL = {'retime': '{} II', 'twin': 'Twin {}', 'feint': '{} Feint', 'amplify': 'Grand {}', 'spin': 'Spiral {}', 'mimic': 'Borrowed {}'}
INVENT_WORDS = ('Drift', 'Echo', 'Rift', 'Ember', 'Gale', 'Tide', 'Spark', 'Veil', 'Arc', 'Pulse', 'Shade', 'Flare')
MAX_FRAMES = 12

CACHE_MAX_BYTES = 24 * 1024 * 1024
SIZES = (1, 2)

# ---------------------------------------------------------------- ids and names
def variant_id(base, op, seed, how='mastery'):
    """The learned row's name.  Stable per (base, op) for mastery / counter / mimic variants (one character evolves a
    move one way), seed-tagged for inventions and counters so two never collide."""
    if how == 'invention':
        return f'{base}_x{int(seed) % 4096:03x}'
    if how == 'counter':
        return f'{base}_vs{int(seed) % 4096:03x}'
    return f'{base}_{SUFFIX.get(op, op)}'


def display_name(move_id, base, op, how='mastery', seed=0, vs=None):
    """A readable, original name derived from the ids (never stored)."""
    b = base.replace('_', ' ').title()
    if how == 'invention':
        return f'{b} {INVENT_WORDS[int(seed) % len(INVENT_WORDS)]}'
    if how == 'counter':
        return f'{b} vs {str(vs or "all").title()}'
    return LABEL.get(op, '{} Variant').format(b)


# ---------------------------------------------------------------- timing helpers (shared by both tiers)
def _round10(ms, lo=40):
    return max(lo, int(round(ms / 10.0)) * 10)


def dedupe(ms, keep=()):
    """No two consecutive frames share a duration (the fluid-pass rule): the later one of an equal pair is nudged by 10 ms,
    away from the value of the frame after it; `keep` indices (smear frames) are never touched."""
    ms = list(ms)
    for i in range(1, len(ms)):
        if ms[i] == ms[i - 1]:
            if i in keep:
                ms[i - 1] = ms[i - 1] + 10 if (i - 2 < 0 or ms[i - 2] != ms[i - 1] + 10) else ms[i - 1] - 10
            else:
                nxt = ms[i + 1] if i + 1 < len(ms) else None
                ms[i] = ms[i] + 10 if nxt != ms[i] + 10 else ms[i] + 20
    return ms


def warp_air(keys, old_ms, new_ms):
    """Retimed frames: the `air` curve's keys (ms on the row clock) move with the frame boundaries they fall in, so the lift
    stays on the same frames.  Piecewise-linear in each frame."""
    if not keys:
        return keys
    ob = [0]
    nb = [0]
    for o, n in zip(old_ms, new_ms):
        ob.append(ob[-1] + o)
        nb.append(nb[-1] + n)
    out = []
    for k in keys:
        t = float(k[0])
        i = 0
        while i + 1 < len(ob) - 1 and t >= ob[i + 1]:
            i += 1
        span = max(1e-6, float(ob[i + 1] - ob[i]))
        u = min(1.0, max(0.0, (t - ob[i]) / span))
        nt = nb[i] + u * (nb[i + 1] - nb[i])
        out.append([int(round(nt))] + list(k[1:]))
    return out


def timing_qa(frames_ms, hit_frame, smear_frames, hitstop_ms, cat='strike'):
    """-> [failures] for the fluid-pass timing rules on a strike's frame durations (tests/test_art.py
    test_v5_timing_rules_on_every_strike + the V7 'winds up longer than it strikes' rule)."""
    bad = []
    ms = list(frames_ms)
    if not ms or len(ms) > MAX_FRAMES:
        bad.append(f'{len(ms)} frames')
        return bad
    if any(x <= 0 for x in ms):
        bad.append('a frame with ms <= 0')
    if any(x == y for x, y in zip(ms, ms[1:])):
        bad.append(f'even timing {ms}')
    if cat in ('strike', 'ultimate'):
        if hit_frame is None or not 0 <= hit_frame < len(ms):
            bad.append('no hit frame')
            return bad
        if not smear_frames:
            bad.append('no smear frame')
        else:
            if any(ms[i] > 110 for i in smear_frames):
                bad.append('a smear frame is held')
            if not any(i <= hit_frame for i in smear_frames):
                bad.append('the smear comes after the contact')
            if sum(ms[:min(smear_frames)]) <= ms[min(smear_frames)]:
                bad.append('no wind-up before the strike')
        if (hitstop_ms or 0) < 150:
            bad.append('hitstop under 150 ms')
    return bad


# ---------------------------------------------------------------- tier 1: remap operators (numbers only)
BASE_TYPES = (None, 'string', 'gust', 'riposte')   # rows a variant may grow from: plain strikes played standing in place


def eligible_base(entry):
    """A row a fighter may evolve, counter or borrow: a strike with a hit frame and a smear that the choreographer plays as a
    plain strike (not a throw, a dash-through, a chain pull, a launcher's air slash or a spike: those carry engine flags a
    variant would lose)."""
    if not isinstance(entry, dict) or entry.get('cat') != 'strike' or 'hit_frame' not in entry:
        return False
    if entry.get('type') not in BASE_TYPES or entry.get('proj_frame') is not None:
        return False
    return bool(entry.get('smear_frames'))


def eligible_remap_ops(entry):
    """Which remap operators a base anim.json row allows.  Strikes with a hit frame and a smear; rows with an `air` curve
    only retime (their lift is warped with the frames; re-sequenced frames would fall out of step with it)."""
    if not eligible_base(entry):
        return ()
    sm = entry.get('smear_frames') or []
    hf = int(entry['hit_frame'])
    if min(sm) < 1 or hf < min(sm):
        return ()
    if entry.get('air'):
        return ('retime',)
    ops = ['retime']
    n = len(entry['frames'])
    if n + 3 <= MAX_FRAMES:
        ops.append('twin')
    if min(sm) >= 2 and n + 2 <= MAX_FRAMES:
        ops.append('feint')
    return tuple(ops)


def remap(entry, op, seed, name=None, how='mastery'):
    """-> a new anim entry (dict) for a remap variant of a base anim.json row, or None when the operator does not apply or
    the result fails the timing QA.  frames[i]['src'] is the base frame index the engine draws; `remap` lists them too."""
    if op not in eligible_remap_ops(entry):
        return None
    rng = random.Random(int(seed) * 1000003 + hash_str(op))
    fr = entry['frames']
    ms = [int(f['ms']) for f in fr]
    dx = [float(f.get('dx') or 0) for f in fr]
    sm = sorted(int(i) for i in entry['smear_frames'])
    s0, hf = sm[0], int(entry['hit_frame'])
    n = len(fr)
    src = list(range(n))
    air = entry.get('air')
    if op == 'retime':
        k = 0.66 + 0.08 * rng.random()                        # the wind-up loses a third of its length
        new = [(_round10(m * k, 50) if i < s0 else m) for i, m in enumerate(ms)]
        new[hf] = _round10(ms[hf] + 20)                       # ...and the contact is held a touch longer: a sharper snap
        new_ms = dedupe(new, keep=set(sm))
        if air:
            air = warp_air(air, ms, new_ms)
        new_src, new_dx, hit, smears = src, dx, hf, sm
    elif op == 'twin':
        w = s0 - 1                                            # the last wind-up key: a short re-chamber between the two cuts
        new_src = src[:hf] + [w, s0] + src[hf:]               # the first cut is pulled (its smear, no contact), the second lands
        new_ms = ms[:hf] + [70, 40] + ms[hf:]
        new_dx = dx[:hf] + [0.0, 3.0] + dx[hf:]
        hit = hf + 2
        smears = sm + [hf + 1]
        new_ms = dedupe(new_ms, keep=set(smears))
    else:                                                     # feint: a stutter-step fake out of the wind-up, then the real cut
        a, b = s0 - 2, s0 - 1
        new_src = src[:s0] + [a, b] + src[s0:]
        new_ms = ms[:s0] + [60, 50] + ms[s0:]
        new_ms[b] = _round10(ms[b] * 0.7, 50)
        new_dx = dx[:s0] + [1.0, 0.0] + dx[s0:]
        hit = hf + 2
        smears = [i + 2 for i in sm]
        new_ms = dedupe(new_ms, keep=set(smears))
    bad = timing_qa(new_ms, hit, smears, entry.get('hitstop_ms'), entry.get('cat'))
    if bad:
        return None
    out = {k: v for k, v in entry.items() if k not in ('row', 'frames', 'grip', 'grip2', 'cancel_frame', 'fx', 'input')}
    out['frames'] = [dict(i=i, ms=int(m), dx=float(d), src=int(s)) for i, (m, d, s) in enumerate(zip(new_ms, new_dx, new_src))]
    out['remap'] = [int(s) for s in new_src]
    out['hit_frame'] = int(hit)
    out['smear_frames'] = [int(i) for i in smears]
    out['loop'] = False
    out['type'] = 'learned'
    if air:
        out['air'] = air
    base = entry.get('name') or name or 'move'
    out['learned'] = dict(how=how, base=base, op=op, seed=int(seed), tier='remap')
    out['desc'] = _desc(op, base)
    return out


def hash_str(s):
    h = 2166136261
    for ch in str(s):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _desc(op, base, src=None):
    b = base.replace('_', ' ')
    return {'retime': f'An evolved {b}: the wind-up is a third shorter and the cut snaps harder.',
            'twin': f'A two-hit {b}: the first cut is checked, the second one lands.',
            'feint': f'A {b} out of a stutter-step fake: the shoulders go, the cut comes a beat later.',
            'amplify': f'A bigger {b}: a longer reach, a wider arc, a deeper lunge.',
            'spin': f'A {b} wound up out of a full spin.',
            'mimic': f'A crude {b} learned by watching {str(src or "an opponent").title()}, done with its own weapon.'}.get(op, b)


REMAP_IOU_MAX = {'feint': 0.65, 'twin': 0.88}   # the frames a feint / twin inserts must read as different shapes (silhouette
                                               # IoU below this).  Measured over the roster: a feint between two wind-up keys that
                                               # differ by 1-2 px (every jab, the heavies' ground slam, the iai crouch: 0.66-0.88) read as a stall
                                               # at 4x, not a fake, so they are rejected.
_REMAP_OK = {}


def remap_qa(atlas, base, op, seed=1):
    """Image QA for a remap variant, on the base row's real frames (both facings, this atlas's resolution): the frames a
    feint inserts (the two wind-up keys it stutters between) and the re-chamber a twin inserts (against its smear) must
    differ as silhouettes, or the variant reads as a stall instead of a fake / a second cut.  retime adds no new image.
    -> [failures].  `atlas` needs frame_image(name, i, facing)."""
    e = atlas.anim.get(base) if hasattr(atlas, 'anim') else None
    if op == 'retime' or not e:
        return []
    sm = sorted(int(i) for i in e.get('smear_frames') or [])
    if not sm:
        return ['no smear']
    s0 = sm[0]
    pairs = [(s0 - 2, s0 - 1)] if op == 'feint' else [(s0 - 1, s0)]
    bad = []
    for facing in (1, -1):
        for a, b in pairs:
            if a < 0:
                return ['not enough wind-up frames']
            iou = _iou(_mask(atlas.frame_image(base, a, facing)), _mask(atlas.frame_image(base, b, facing)))
            if iou >= REMAP_IOU_MAX[op]:
                bad.append(f'{op}: frames {a} and {b} read the same (IoU {iou:.2f})')
    return bad


def remap_ok(atlas, base, op):
    """remap_qa, cached per (character, res, base, op)."""
    key = (getattr(atlas, 'character', '?'), getattr(atlas, 'res', 1), base, op)
    if key not in _REMAP_OK:
        try:
            _REMAP_OK[key] = not remap_qa(atlas, base, op)
        except Exception:
            _REMAP_OK[key] = False
    return _REMAP_OK[key]


def _mask(im):
    return im.getchannel('A').point(lambda v: 255 if v > 40 else 0)


def _iou(a, b):
    pa, pb = a.load(), b.load()
    w, h = a.size
    inter = union = 0
    for y in range(h):
        for x in range(w):
            u, v = pa[x, y] > 0, pb[x, y] > 0
            inter += u and v
            union += u or v
    return inter / float(union) if union else 1.0



def cache_root(data_dir):
    return Path(data_dir) / 'learned'


def _inside(path, root):
    try:
        return os.path.commonpath([str(Path(path).resolve()), str(root)]) == str(root)
    except ValueError:                                 # a different drive
        return False


def cache_paths(data_dir, character, move_id):
    """(folder, metadata JSON, {res: sheet PNG}) of a cached variant.  Raises ValueError for an id that is not a plain
    id, or for a path that would resolve outside <data dir>/learned (a crafted learning.json or bus plan)."""
    if not valid_id(character) or not valid_id(move_id):
        raise ValueError('not an id')
    root = cache_root(data_dir).resolve()
    d = root / character
    mp = d / f'{move_id}.json'
    pngs = {r: d / f'{move_id}.r{r}.png' for r in SIZES}
    for q in [d, mp] + list(pngs.values()):
        if not _inside(q, root):
            raise ValueError('outside the cache')
    return d, mp, pngs


def cached(data_dir, character, move_id):
    """The cached variant's metadata when every file of it is there and current, else None (also for an invalid id)."""
    try:
        d, mp, pngs = cache_paths(data_dir, character, move_id)
        meta = json.loads(mp.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or meta.get('code_v') != VERSION or not all(p.is_file() for p in pngs.values()):
        return None
    return meta


def load_sheet(data_dir, character, move_id, res):
    """The cached sheet image at `res` (R frames in row 0, L frames in row 1), or None."""
    from PIL import Image
    try:
        _, _, pngs = cache_paths(data_dir, character, move_id)
    except ValueError:
        return None
    try:
        touch(data_dir, character, move_id)
        return Image.open(pngs[res]).convert('RGBA')
    except (OSError, KeyError):
        return None


# ---------------------------------------------------------------- the cache: size cap + LRU
def _index_path(data_dir):
    return cache_root(data_dir) / 'index.json'


def _read_index(data_dir):
    try:
        d = json.loads(_index_path(data_dir).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(data_dir, idx):
    try:
        p = _index_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(idx, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, p)
    except OSError:
        pass


def touch(data_dir, character, move_id, now=None):
    if not valid_id(character) or not valid_id(move_id):
        return
    idx = _read_index(data_dir)
    idx[f'{character}/{move_id}'] = float(time.time() if now is None else now)
    _write_index(data_dir, idx)


TMP_STALE_S = 600.0           # a temp file this old belongs to a build that died: it is removed
YOUNG_S = 60.0                # an orphan sheet younger than this may be a build between its renames: left alone


def _files(data_dir):
    """{(character, id): [paths]} of every file in the cache (sheets, metadata, rejection sidecars, temps), grouped by the
    part of the name before its first dot; files whose folder or id is not a plain id are grouped under their own name."""
    root = cache_root(data_dir)
    out = {}
    if not root.is_dir():
        return out
    for ch in root.iterdir():
        if not ch.is_dir():
            continue
        for f in ch.iterdir():
            if f.is_file():
                out.setdefault((ch.name, f.name.split('.', 1)[0]), []).append(f)
    return out


def _size(files):
    n = 0
    for f in files:
        try:
            n += f.stat().st_size
        except OSError:
            pass
    return n


def cache_size(data_dir):
    """Every byte in the cache: complete variants, orphans, sidecars and temps alike."""
    return sum(_size(v) for v in _files(data_dir).values())


def evict(data_dir, cap=CACHE_MAX_BYTES, now=None):
    """Remove stale temps and orphans (sheets without their metadata) first, then whole variants least recently used until
    the cache - every file in it - is under `cap` bytes.  -> [evicted 'character/id' keys]."""
    wall = time.time() if now is None else now
    idx = _read_index(data_dir)
    groups = _files(data_dir)
    gone = []

    def drop(key, files):
        for f in files:
            try:
                f.unlink()
            except OSError:
                pass
        idx.pop(f'{key[0]}/{key[1]}', None)
        gone.append(f'{key[0]}/{key[1]}')
    for key in list(groups):
        files = groups[key]
        stale_tmp = [f for f in files if f.name.endswith('.tmp') and wall - _mtime(f) > TMP_STALE_S]
        for f in stale_tmp:
            try:
                f.unlink()
            except OSError:
                pass
        files = [f for f in files if f not in stale_tmp]
        meta = [f for f in files if f.name == f'{key[1]}.json']
        sheets = [f for f in files if f.suffix == '.png']
        if not meta and sheets and all(wall - _mtime(f) > YOUNG_S for f in sheets):
            drop(key, files)                                 # an orphan: no metadata will ever claim these sheets
            groups.pop(key)
        elif stale_tmp:
            groups[key] = files
            if not files:
                groups.pop(key)
                gone.append(f'{key[0]}/{key[1]}')
    total = sum(_size(v) for v in groups.values())
    order = sorted(groups, key=lambda k: (idx.get(f'{k[0]}/{k[1]}', min((_mtime(f) for f in groups[k]), default=0.0)), k))
    for key in order:
        if total <= cap:
            break
        total -= _size(groups[key])
        drop(key, groups[key])
    if gone:
        _write_index(data_dir, idx)
    return gone


def _mtime(f):
    try:
        return f.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------- the redrawn tier is not in the package
def available():
    """The redrawn tier (art/evolve.py) is not here: a packaged install learns remap variants only."""
    return False


def eligible_render_ops(entry, src_available=False):
    return ()
