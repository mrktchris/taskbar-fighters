"""Procedural move synthesis (docs/LEARNING.md): new move VARIANTS built from existing pose keyframes, so a fighter can
teach itself a move nobody drew by hand.

A variant is a pure function of (character, base move, operator, seed[, source character]) and is regenerated from those
numbers on any machine; nothing it produces is shipped.  Two tiers:

  remap operators   `retime` (faster startup), `twin` (a two-hit string), `feint` (a stutter-step fake, then the real cut).
                    They re-sequence and re-time the FRAMES THE SHEET ALREADY HAS, so they need no rig, no art pipeline and
                    no cache: the engine draws them through minis_core.learning.LearnedAtlas (a learned row whose frames
                    point back into the base row).  Available in every install (checkout, pip, the Windows zip).
  render operators  `amplify` (a bigger arc and reach), `spin` (a torso spin wound into the strike), `mimic` (another
                    weapon family's move drawn with this fighter's own body and weapon: a ninja's crude take on the ronin's
                    iai cut).  They edit the POSE keys and render new frames through the same rig that builds assets/, at
                    64 and 128 px in both facings, into a per-character cache under the data folder (never into the repo),
                    with a size cap and LRU eviction.  Only in a checkout (the rig lives in art/).

Every variant goes through `qa()` before it may be learned: the same bars the art tests hold the shipped sheets to -
no anchor jitter over one pixel between grounded frames, the weapon attached to the hand on every frame, a readable
silhouette (the contact pose differs from idle, the smear draws its crescent), a measured reach, the colour caps (and no
colour the character's own sheet does not already have), both facings a mirror, 64 and 128 px, the fluid-pass timing
rules (a smear before the contact, no two consecutive frames with the same duration, hitstop on the contact).  A variant
that fails any of them is rejected and never learned.

  python art/evolve.py variants <character> [--ops a,b] [--out DIR]    build every eligible variant, print PASS / REJECT
  python art/evolve.py review <character> [--out qa/learning]          4x frame-by-frame review sheets (both facings, onion
                                                                       skin, ms / HIT / smear labels, a 1x taskbar strip)
Names are generic and original (no franchise names): "<Move> II", "Twin <Move>", "<Move> Feint", "Grand <Move>",
"Spiral <Move>", "Borrowed <Move>", and inventions take a seeded word ("<Move> Drift").
"""
from __future__ import annotations
import json, math, os, random, sys, time
from pathlib import Path

VERSION = 1                                  # bump when a variant's frames would change: cached renders are re-made
REMAP_OPS = ('retime', 'twin', 'feint')
RENDER_OPS = ('amplify', 'spin', 'mimic')
OPS = REMAP_OPS + RENDER_OPS
SUFFIX = {'retime': 'ii', 'twin': 'twin', 'feint': 'feint', 'amplify': 'grand', 'spin': 'spiral', 'mimic': 'borrowed'}
LABEL = {'retime': '{} II', 'twin': 'Twin {}', 'feint': '{} Feint', 'amplify': 'Grand {}', 'spin': 'Spiral {}', 'mimic': 'Borrowed {}'}
INVENT_WORDS = ('Drift', 'Echo', 'Rift', 'Ember', 'Gale', 'Tide', 'Spark', 'Veil', 'Arc', 'Pulse', 'Shade', 'Flare')
MAX_FRAMES = 12
CAP = {1: 31, 2: 63}                         # colours WITHOUT transparency per RES (art/build_fighters.CAPS minus one)
CACHE_MAX_BYTES = 24 * 1024 * 1024
SIZES = (1, 2)
_ART = None
_MOVES = {}


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


# ---------------------------------------------------------------- the art pipeline (checkout only)
def art_dir():
    return Path(__file__).resolve().parent


def available():
    """The render tier needs the rig (art/rig.py, art/moves.py, art/roster.py, art/build_fighters.py) and Pillow."""
    global _ART
    if _ART is not None:
        return _ART
    try:
        d = art_dir()
        ok = all((d / f).is_file() for f in ('rig.py', 'moves.py', 'roster.py', 'build_fighters.py'))
        if ok:
            _art()
        _ART = bool(ok)
    except Exception:
        _ART = False
    return _ART


def _art():
    """-> (rig, moves, roster, build_fighters) imported from art/ (added to sys.path once)."""
    d = str(art_dir())
    if d not in sys.path:
        sys.path.insert(0, d)
    import rig, moves, roster, build_fighters  # noqa: E401
    return rig, moves, roster, build_fighters


def base_moves(character):
    """moves.build_moves(character), cached: the processed (settled, fitted) keyframes of every move."""
    if character not in _MOVES:
        _, moves, roster, _ = _art()
        _MOVES[character] = moves.build_moves(roster.get(character))
    return _MOVES[character]


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


# ---------------------------------------------------------------- tier 2: render operators (pose keys through the rig)
def eligible_render_ops(entry, src_available=False):
    """amplify / spin for grounded strikes with a hand smear; mimic when a source character is named."""
    if not eligible_base(entry) or entry.get('air'):
        return ()
    ops = ['amplify', 'spin']
    if src_available:
        ops.append('mimic')
    return tuple(ops)


def _is_hand_smear(ps):
    return bool(ps.smear_f or ps.smear_b)


def _mimic_source(src_char, base):
    """The pose function of `base` as the source character fights it: a family move (with per-character renames), or
    its signature strike template.  -> (fn producing a move dict, desc) or None."""
    _, moves, roster, _ = _art()
    ch = roster.get(src_char)
    fam = moves.family_of(ch)
    swap = moves.CHAR_MOVES.get(ch.name, {})
    for name, fn, desc in moves.FAMILY_MOVES[fam]:
        name2, fn2, desc2 = swap.get(name, (name, fn, desc))
        if name2 == base:
            return (lambda d=desc2, f=fn2: f(d)), desc2
    sig = ch.signature.get('strike')
    if sig == base and base in ch.sig_moves:
        tpl, desc, opts = ch.sig_moves[base]
        return (lambda d=desc, t=tpl, o=opts: moves.TEMPLATES[t](d, **o)), desc
    return None


def _pose_variant(character, base, op, seed, src_char=None):
    """-> (move dict with edited (Pose, ms) frames, meta) for a render operator, or None when it does not apply."""
    rig, moves, roster, BF = _art()
    from dataclasses import replace
    ch = roster.get(character)
    body = ch.body
    rng = random.Random(int(seed) * 7919 + hash_str(op) + hash_str(base))
    mv0 = None
    if op == 'mimic':
        if not src_char or src_char == character:
            return None
        got = _mimic_source(src_char, base)
        if got is None:
            return None
        fn, desc = got
        mv0 = fn()
        if 'hit_frame' not in mv0 or mv0.get('air_spec') or mv0.get('proj_frame') is not None or mv0['cat'] != 'strike':
            return None
        mv0['power'] = max(1, int(mv0.get('power', 1)) - 1)   # a borrowed move is a weaker copy
        mv0['hitstop_ms'] = moves.HITSTOP.get(mv0['power'], 150)
    else:
        bm = base_moves(character)
        if base not in bm:
            return None
        mv0 = dict(bm[base])
        mv0['frames'] = list(mv0['frames'])
    frames = [(ps, ms) for ps, ms in mv0['frames']]
    if not frames or len(frames) > MAX_FRAMES:
        return None
    sm = [i for i, (ps, _) in enumerate(frames) if rig.is_smear(ps)]
    if not sm:
        return None
    s0, hf = sm[0], int(mv0['hit_frame'])
    out = []
    if op == 'amplify':
        k = 1.18 + 0.1 * rng.random()
        for i, (ps, ms) in enumerate(frames):
            if s0 <= i <= hf + 1 and _is_hand_smear(frames[s0][0]):
                hf_ = (ps.hf[0] * k, ps.hf[1] * k)
                sm_f = (ps.smear_f[0] * 1.1, ps.smear_f[1] * 1.1) if ps.smear_f else ps.smear_f
                ps = replace(ps, hf=hf_, lean=ps.lean + 5, dx=ps.dx + (2 if i == s0 else 0), smear_f=sm_f)
            elif s0 <= i <= hf + 1:                               # a kick: the foot reaches further
                ps = replace(ps, ff=(ps.ff[0] * k, ps.ff[1]), lean=ps.lean + 3, dx=ps.dx + (2 if i == s0 else 0))
            elif i < s0:
                ps = replace(ps, hf=(ps.hf[0] * 1.08, ps.hf[1] * 1.08))     # a longer coil
            out.append((ps, ms))
    elif op == 'spin':
        for i, (ps, ms) in enumerate(frames):
            if i == s0:
                prev = frames[i - 1][0]
                wa = (prev.wa if prev.wa is not None else -60.0) + (120.0 if rng.random() < 0.5 else -120.0)
                spin = replace(prev, turn=0.35, lean=prev.lean - 4, hf=(-prev.hf[0] * 0.8, prev.hf[1]), wa=((wa + 180) % 360) - 180,
                               face='g', dx=1.0)
                out.append((spin, 70))
                ps = replace(ps, smear_f=(spin.hf if ps.smear_f else ps.smear_f), ghost=())
            out.append((ps, ms))
    else:                                                        # mimic: the poses as the source draws them, this body's weapon
        out = frames
    mv = dict(mv0, frames=out)
    sm2 = [i for i, (ps, _) in enumerate(out) if rig.is_smear(ps)]
    mv['smear_frames'] = sm2
    mv['hit_frame'] = hf + (1 if op == 'spin' else 0)
    ms = [m for _, m in out]
    ms = dedupe(ms, keep=set(sm2))
    mv['frames'] = [(ps, m) for (ps, _), m in zip(out, ms)]
    mv['loop'] = False
    mv.pop('cancel_frame', None)
    mv.pop('air_spec', None)
    mv.pop('air', None)
    moves.fit_weapons(body, mv)                                  # the weapon never turned by the solver (V7 rule 1)
    mv['frames'] = moves._fit_chain(body, mv['frames'])
    stance = base_moves(character)['idle']['frames'][0][0]
    moves.settle_to_stance(mv, stance)
    moves.inbetween_weapons(body, mv)
    if mv.pop('_stance_end', False):
        mv['frames'][-1] = (stance, mv['frames'][-1][1])
    moves.settle_frame(body, mv, stance)
    for ps_, ms_ in mv['frames']:
        if ms_ <= 0:
            return None
    ann = moves.annotate_contact(ch, {base: dict(mv)})[base]
    mv['hit'], mv['height'] = ann.get('hit'), ann.get('height')
    if op == 'mimic':
        src_meta = base_moves(src_char).get(base) or {}
        mv['height'] = src_meta.get('height', mv['height'])
    mv['type'] = 'learned'
    mv['family'] = moves.family_of(ch)
    mv['desc'] = _desc(op, base, src_char)
    return mv, dict(op=op, base=base, seed=int(seed), src=src_char)


def render_frames(character, mv, res):
    """The variant's frames through the real builder at `res`: [dict(r, l, buf, pose, ms, meta)]."""
    rig, moves, roster, BF = _art()
    ch = roster.get(character)
    rig.set_res(res)
    try:
        return BF.render_move(ch, '_learned', mv, None)
    finally:
        rig.set_res(1)


# ---------------------------------------------------------------- QA on rendered frames
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


def _colours(ims):
    out = set()
    for im in ims:
        for n, c in im.getcolors(1 << 20) or ():
            if c[3]:
                out.add(c[:3])
    return out


def qa(character, mv, frames, res, base_palette, idle_frame, min_reach=10.0):
    """-> [failures] for one rendered variant at `res` (empty = clean).  `frames` from render_frames; `base_palette` the
    character's own sheet colours (RGB set) at that res; `idle_frame` its idle frame 0 (right-facing) at that res."""
    rig, moves, roster, BF = _art()
    body = roster.get(character).body
    bad = []
    S = res
    cw = 64 * S
    n = len(frames)
    ms = [f['ms'] for f in frames]
    sm = mv.get('smear_frames') or []
    hf = mv.get('hit_frame')
    bad += timing_qa(ms, hf, sm, mv.get('hitstop_ms'), mv.get('cat', 'strike'))
    lows = []
    for i, f in enumerate(frames):
        for side in ('r', 'l'):
            im = f[side]
            bb = im.getchannel('A').getbbox()
            if bb is None:
                bad.append(f'frame {i}{side}: empty')
                continue
            if bb[1] < 1:
                bad.append(f'frame {i}{side}: touches the top edge')
            if bb[3] > 60 * S:
                bad.append(f'frame {i}{side}: below the outline row')
            if bb[0] < 0 or bb[2] > cw:
                bad.append(f'frame {i}{side}: outside the cell')
        br, bl = f['r'].getchannel('A').getbbox(), f['l'].getchannel('A').getbbox()
        if br and bl and (abs((cw - br[2]) - bl[0]) > 1 or abs((cw - br[0]) - bl[2]) > 1):
            bad.append(f'frame {i}: the left facing is not a mirror')
        lows.append(br[3] if br else None)
        # the weapon stays in the hand: weapon pixels within reach of the hand pixels (the rig's part buffer)
        ps = f['pose']
        if body.weapon is not None and not ps.nowf and not ps.flash:
            buf = f['buf']
            px = buf.load()
            wid = {rig.PID[k] for k in ('wpn_f', 'hilt_f', 'blade_hl')}
            hid = {rig.PID[k] for k in ('hand_f', 'cuff_f')}
            wp = [(x, y) for y in range(cw) for x in range(cw) if px[x, y] in wid]
            hp = [(x, y) for y in range(cw) for x in range(cw) if px[x, y] in hid]
            if not wp:
                bad.append(f'frame {i}: no weapon drawn')
            elif not hp:
                bad.append(f'frame {i}: no hand drawn')
            else:
                d = min(abs(ax - bx) + abs(ay - by) for ax, ay in wp[::max(1, len(wp) // 60)] for bx, by in hp[::max(1, len(hp) // 40)])
                if d > 3 * S:
                    bad.append(f'frame {i}: the weapon left the hand ({d} px)')
    # anchors: between two consecutive grounded frames without authored travel the soles stay on the same row
    for i in range(n - 1):
        pa, pb = frames[i]['pose'], frames[i + 1]['pose']
        if pa.dx or pb.dx or pa.flash or pb.flash or lows[i] is None or lows[i + 1] is None:
            continue
        ga = (pa.ff[1] == 0 or pa.fb[1] == 0) and pa.lean > -45 and 0 <= pa.dy < 12
        gb = (pb.ff[1] == 0 or pb.fb[1] == 0) and pb.lean > -45 and 0 <= pb.dy < 12
        if ga and gb and abs(lows[i] - lows[i + 1]) > S:
            bad.append(f'frames {i}-{i + 1}: anchor jitter {abs(lows[i] - lows[i + 1])} px')
    # silhouette: the contact pose reads as its own shape, the smear draws its crescent
    if hf is not None and 0 <= hf < n and idle_frame is not None:
        if _iou(_mask(frames[hf]['r']), _mask(idle_frame)) >= 0.8:
            bad.append('the contact pose reads like idle')
        if sm and sm[0] >= 1 and _iou(_mask(frames[hf]['r']), _mask(frames[sm[0] - 1]['r'])) >= 0.92:
            bad.append('the contact pose reads like the wind-up')
    if sm:
        i = sm[0]
        ps = frames[i]['pose']
        if _is_hand_smear(ps) and frames[i]['buf'].tobytes().count(bytes([rig.PID['swoosh']])) == 0:
            bad.append(f'frame {i}: no crescent on the smear')
    # reach, measured from the striking pixels
    reach = None
    if hf is not None and 0 <= hf < n:
        rig.set_res(res)
        try:
            reach = BF.hit_reach(frames[hf]['buf'], frames[hf]['pose'])
        finally:
            rig.set_res(1)
        if reach is None or reach < min_reach * S:
            bad.append(f'reach {reach} under {min_reach * S}')
    # colours: inside the cap, and nothing the character's own sheet does not have
    cols = _colours([f[s] for f in frames for s in ('r', 'l')])
    if len(cols) > CAP[res]:
        bad.append(f'{len(cols)} colours over the cap {CAP[res]}')
    if base_palette:
        new = cols - set(base_palette)
        if new:
            bad.append(f'{len(new)} colours not in the sheet')
    return bad, reach


# ---------------------------------------------------------------- build a render variant into the cache
def cache_root(data_dir):
    return Path(data_dir) / 'learned'


def cache_paths(data_dir, character, move_id):
    d = cache_root(data_dir) / character
    return d, d / f'{move_id}.json', {r: d / f'{move_id}.r{r}.png' for r in SIZES}


def cached(data_dir, character, move_id):
    """The cached variant's metadata when every file of it is there and current, else None."""
    d, mp, pngs = cache_paths(data_dir, character, move_id)
    try:
        meta = json.loads(mp.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if meta.get('code_v') != VERSION or not all(p.is_file() for p in pngs.values()):
        return None
    return meta


def _sheet_palette(character, res):
    """The character's built sheet colours at `res` (RGB set), read through minis_core.atlas when it is importable."""
    try:
        from minis_core.atlas import Atlas
        a = Atlas(character, hd=(res == 2))
        return _colours(list(a.sheets.values())), a.frame_image('idle', 0, 1)
    except Exception:
        return set(), None


def build(data_dir, character, base, op, seed, src_char=None, how='mastery', move_id=None, sizes=SIZES):
    """Render one variant at every size, run the QA, write the cache files.  -> (meta, failures): meta None when rejected.
    Deterministic in its arguments: the same files on any machine."""
    if not available():
        return None, ['art pipeline not available']
    got = _pose_variant(character, base, op, seed, src_char)
    if got is None:
        return None, ['operator does not apply']
    mv, info = got
    move_id = move_id or variant_id(base, op, seed, how)
    d, mp, pngs = cache_paths(data_dir, character, move_id)
    per_res = {}
    failures = []
    images = {}
    for res in sizes:
        frames = render_frames(character, mv, res)
        pal, idle = _sheet_palette(character, res)
        bad, reach = qa(character, mv, frames, res, pal, idle)
        if bad:
            failures += [f'res {res}: {b}' for b in bad]
            continue
        cw = 64 * res
        sheet = _new_sheet(cw, len(frames))
        for i, f in enumerate(frames):
            sheet.paste(f['r'], (i * cw, 0))
            sheet.paste(f['l'], (i * cw, cw))
        images[res] = sheet
        per_res[str(res)] = dict(reach=reach, frames=[dict(i=i, ms=int(f['ms']), dx=float(f['pose'].dx * res)) for i, f in enumerate(frames)])
    if failures:
        return None, failures
    entry = dict(cat='strike', loop=False, type='learned', family=mv.get('family'), desc=mv.get('desc', ''),
                 hit_frame=int(mv['hit_frame']), power=int(mv.get('power', 1)), hitstop_ms=int(mv.get('hitstop_ms') or 150),
                 smear_frames=[int(i) for i in mv.get('smear_frames') or []], hit=mv.get('hit'), height=mv.get('height'),
                 learned=dict(how=how, base=base, op=op, seed=int(seed), tier='render', src=src_char))
    if mv.get('shake'):
        entry['shake'] = dict(frames=int(mv['shake']['frames']), amp=int(mv['shake']['amp']))
    meta = dict(code_v=VERSION, id=move_id, character=character, spec=[character, base, op, int(seed), src_char, how],
                entry=entry, res=per_res, bytes=0, ts=time.time())
    try:
        d.mkdir(parents=True, exist_ok=True)
        total = 0
        for res, im in images.items():
            im.save(pngs[res])
            total += pngs[res].stat().st_size
        meta['bytes'] = total
        mp.write_text(json.dumps(meta, separators=(',', ':')), encoding='utf-8')
    except OSError as e:
        return None, [f'cache write failed: {type(e).__name__}']
    evict(data_dir)
    return meta, []


def _new_sheet(cw, n):
    from PIL import Image
    return Image.new('RGBA', (cw * n, cw * 2), (0, 0, 0, 0))


def load_sheet(data_dir, character, move_id, res):
    """The cached sheet image at `res` (R frames in row 0, L frames in row 1), or None."""
    from PIL import Image
    _, _, pngs = cache_paths(data_dir, character, move_id)
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
    idx = _read_index(data_dir)
    idx[f'{character}/{move_id}'] = float(time.time() if now is None else now)
    _write_index(data_dir, idx)


def cache_size(data_dir):
    total = 0
    root = cache_root(data_dir)
    if not root.is_dir():
        return 0
    for ch in root.iterdir():
        if ch.is_dir():
            for p in ch.iterdir():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return total


def evict(data_dir, cap=CACHE_MAX_BYTES, now=None):
    """Drop the least recently used variants until the cache is under `cap` bytes.  -> [evicted ids]."""
    root = cache_root(data_dir)
    if not root.is_dir():
        return []
    idx = _read_index(data_dir)
    items = []
    for ch in root.iterdir():
        if not ch.is_dir():
            continue
        for mp in ch.glob('*.json'):
            mid = mp.stem
            key = f'{ch.name}/{mid}'
            files = [mp] + [p for p in ch.glob(f'{mid}.r*.png')]
            size = sum(p.stat().st_size for p in files if p.is_file())
            items.append((idx.get(key, 0.0), key, files, size))
    total = sum(s for _, _, _, s in items)
    gone = []
    for used, key, files, size in sorted(items):
        if total <= cap:
            break
        for p in files:
            try:
                p.unlink()
            except OSError:
                pass
        idx.pop(key, None)
        total -= size
        gone.append(key)
    if gone:
        _write_index(data_dir, idx)
    return gone


# ---------------------------------------------------------------- review sheets (the owner's bar: every frame clean, at 4x)
def review_sheet(character, mv, frames_by_res, label):
    """One PNG: both facings at 4x (RES 1) over an onion skin of the previous frame, ms / HIT / smear labels, the 128 px
    frames at 2x below, and a 1x strip on a taskbar mock."""
    from PIL import Image, ImageDraw, ImageFont
    f1, f2 = frames_by_res.get(1) or [], frames_by_res.get(2) or []
    n = max(len(f1), len(f2))
    lab = 46
    rows = []
    for res, fr, sc in ((1, f1, 4), (2, f2, 2)):
        if fr:
            rows.append((res, fr, sc))
    cell = 256
    W_ = lab + n * cell
    H_ = sum(2 * (cell + 26) + 8 for _ in rows) + 64 + 48 + 24
    im = Image.new('RGB', (W_, H_), (32, 32, 32))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('arialbd.ttf', 12)
        big = ImageFont.truetype('arialbd.ttf', 16)
    except OSError:
        font = big = ImageFont.load_default()
    sm = set(mv.get('smear_frames') or [])
    y = 0
    for res, fr, sc in rows:
        for side in ('r', 'l'):
            d.text((4, y + cell // 2), f'{side.upper()} {64 * res}px', fill=(230, 230, 230), font=big)
            for i, f in enumerate(fr):
                x = lab + i * cell
                if i > 0:
                    prev = fr[i - 1][side].resize((cell, cell), Image.NEAREST).getchannel('A')
                    ghost = Image.new('RGB', (cell, cell), (110, 40, 40))
                    im.paste(ghost, (x, y), prev.point(lambda v: 90 if v else 0))
                b = f[side].resize((cell, cell), Image.NEAREST)
                im.paste(b, (x, y), b)
                d.line([(x, y + 57 * 4), (x + cell - 1, y + 57 * 4)], fill=(70, 70, 70))
                hit = i == mv.get('hit_frame')
                tag = f'{i}: {f["ms"]}ms' + (' HIT' if hit else '') + (' sm' if i in sm else '')
                d.text((x + 3, y + cell + 4), tag, fill=(255, 200, 90) if hit else (170, 170, 170), font=font)
            y += cell + 26
        y += 8
    # 1x strip on a taskbar
    d.rectangle([0, y, W_, y + 64], fill=(46, 58, 82))
    d.rectangle([0, y + 16, W_, y + 64], fill=(20, 22, 28))
    for i, f in enumerate(f1):
        x = lab + i * (2 * 64 + 8)
        if x + 128 > W_:
            break
        for k, side in enumerate(('r', 'l')):
            im.paste(f[side], (x + k * 64, y), f[side])
    d.text((6, y + 68), label, fill=(220, 220, 220), font=big)
    return im


def build_cli(a):
    """`build`: render + QA + cache one variant; a rejection leaves <id>.rejected.json (its failures) so the fighter
    process that asked knows it must fall back.  Exit 0 built, 1 rejected, 2 no art pipeline."""
    root = str(art_dir().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    if not available():
        return 2
    mid = variant_id(a.base, a.op, a.seed, a.how)
    d, mp, pngs = cache_paths(a.data, a.character, mid)
    meta, bad = build(a.data, a.character, a.base, a.op, a.seed, a.src, a.how, mid)
    if meta is None:
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f'{mid}.rejected.json').write_text(json.dumps(dict(id=mid, code_v=VERSION, failures=bad[:12], ts=time.time())), encoding='utf-8')
        except OSError:
            pass
        print(f'REJECT {a.character} {mid}: ' + '; '.join(bad[:6]))
        return 1
    print(f'BUILT  {a.character} {mid} ({meta["bytes"]} bytes)')
    return 0


def _cli(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('variants', help='build every eligible variant of a character into a cache dir and report PASS / REJECT')
    v.add_argument('character')
    v.add_argument('--ops', default=','.join(OPS))
    v.add_argument('--out', default=os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'Temp', 'minis-evolve'))
    v.add_argument('--seed', type=int, default=1)
    v.add_argument('--mimic-from', default=None, help='source character for `mimic` (default: the next roster character)')
    r = sub.add_parser('review', help='4x frame-by-frame review sheets of every variant that passes QA')
    r.add_argument('character')
    r.add_argument('--out', default='qa/learning')
    r.add_argument('--ops', default=','.join(OPS))
    r.add_argument('--seed', type=int, default=1)
    r.add_argument('--mimic-from', default=None)
    r.add_argument('--one-sheet', action='store_true', help='also stack every variant into one tall PNG per character')
    b = sub.add_parser('build', help='render ONE variant into the learned-move cache (minis_core.learning spawns this out of process)')
    b.add_argument('character')
    b.add_argument('base')
    b.add_argument('op', choices=RENDER_OPS)
    b.add_argument('seed', type=int)
    b.add_argument('--from', dest='src', default=None, help='source character (mimic)')
    b.add_argument('--how', default='mastery', choices=('mastery', 'counter', 'mimic', 'invention'))
    b.add_argument('--data', required=True, help='the data folder (the cache is <data>/learned/<character>/)')
    a = ap.parse_args(argv)
    if a.cmd == 'build':
        return build_cli(a)
    if not available():
        print('the art pipeline is not available here (art/rig.py missing)')
        return 2
    root = str(art_dir().parent)                          # run as a script: the repo root is not on sys.path by itself
    if root not in sys.path:
        sys.path.insert(0, root)
    rig, moves, roster, BF = _art()
    from minis_core.atlas import Atlas
    atlas = Atlas(a.character)
    ops = [o for o in a.ops.split(',') if o]
    src = a.mimic_from
    if src is None:
        names = list(roster.NAMES)
        src = names[(names.index(a.character) + 1) % len(names)]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n_pass = n_rej = 0
    sheets = []
    bases = [n for n, e in atlas.anim.items() if eligible_base(e)]
    src_bases = [n for n, e in Atlas(src).anim.items() if eligible_base(e) and not e.get('air')
                 and (e.get('type') in ('string', 'gust', 'riposte') or n == Atlas(src).signature()['strike'])]
    for op in ops:
        if op in REMAP_OPS:
            for b in bases:
                e = dict(atlas.anim[b], name=b)
                got = remap(e, op, a.seed)
                if got is None:
                    if op in eligible_remap_ops(e):
                        n_rej += 1
                        print(f'REJECT {a.character} {b} {op}: timing')
                    continue
                img_bad = [f'res {r}: {x}' for r in SIZES for x in remap_qa(Atlas(a.character, hd=(r == 2)), b, op)]
                if img_bad:
                    n_rej += 1
                    print(f'REJECT {a.character} {variant_id(b, op, a.seed)} ({op}, remap): ' + '; '.join(img_bad[:2]))
                    continue
                n_pass += 1
                mid = variant_id(b, op, a.seed)
                print(f'PASS   {a.character} {mid} ({op}, remap): {[f["ms"] for f in got["frames"]]} hit {got["hit_frame"]}')
                if a.cmd == 'review':
                    fbr = {}
                    for res in SIZES:
                        at = Atlas(a.character, hd=(res == 2))
                        fbr[res] = [dict(r=at.frame_image(b, f['src'], 1), l=at.frame_image(b, f['src'], -1), ms=f['ms']) for f in got['frames']]
                    sh = review_sheet(a.character, got, fbr, f'{a.character} {mid} ({op}, remap of {b}: frames {got["remap"]})')
                    pth = out / f'{a.character}-{mid}-4x.png'
                    sh.save(pth)
                    sheets.append(sh)
                    print(f'       -> {pth}')
            continue
        todo = [(b, None) for b in bases if not atlas.anim[b].get('air')] if op != 'mimic' else [(b, src) for b in src_bases]
        for b, sc in todo:
            got = _pose_variant(a.character, b, op, a.seed, sc)
            if got is None:
                continue
            mv, info = got
            frames_by_res, bad_all = {}, []
            for res in SIZES:
                fr = render_frames(a.character, mv, res)
                pal, idle = _sheet_palette(a.character, res)
                bad, reach = qa(a.character, mv, fr, res, pal, idle)
                frames_by_res[res] = fr
                bad_all += [f'res {res}: {x}' for x in bad]
            mid = variant_id(b, op, a.seed)
            if bad_all:
                n_rej += 1
                print(f'REJECT {a.character} {mid} ({op}): ' + '; '.join(bad_all[:4]))
                continue
            n_pass += 1
            print(f'PASS   {a.character} {mid} ({op}{", from " + sc if sc else ""}): {[m for _, m in mv["frames"]]} hit {mv["hit_frame"]}')
            if a.cmd == 'review':
                sh = review_sheet(a.character, mv, frames_by_res, f'{a.character} {mid} ({op}{", from " + sc if sc else ""})')
                p = out / f'{a.character}-{mid}-4x.png'
                sh.save(p)
                sheets.append(sh)
                print(f'       -> {p}')
    if a.cmd == 'review' and getattr(a, 'one_sheet', False) and sheets:
        from PIL import Image
        W_ = max(s.width for s in sheets)
        tall = Image.new('RGB', (W_, sum(s.height + 12 for s in sheets)), (24, 24, 24))
        y = 0
        for s in sheets:
            tall.paste(s, (0, y))
            y += s.height + 12
        p = out / f'{a.character}-learned-variants-4x.png'
        tall.save(p)
        print(f'one sheet -> {p}')
    print(f'{n_pass} passed, {n_rej} rejected')
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
