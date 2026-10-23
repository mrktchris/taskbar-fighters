"""Procedural move synthesis (docs/LEARNING.md): new move VARIANTS built from existing pose keyframes, so a fighter can
teach itself a move nobody drew by hand.

A variant is a pure function of (character, base move, operator, seed[, source character]) and is regenerated from those
numbers on any machine; nothing it produces is shipped.  Two tiers:

  remap operators   `retime` (faster startup), `twin` (a two-hit string), `feint` (a stutter-step fake, then the real cut).
                    They re-sequence and re-time the FRAMES THE SHEET ALREADY HAS, so they need no rig, no art pipeline and
                    no cache: the engine draws them through minis_core.learning.LearnedAtlas (a learned row whose frames
                    point back into the base row).
  render operators  `amplify` (a bigger arc and reach), `spin` (a torso spin wound into the strike), `mimic` (another
                    weapon family's move drawn with this fighter's own body and weapon: a ninja's crude take on the ronin's
                    iai cut).  They edit the POSE keys and render new frames through the same rig that builds assets/, at
                    64 and 128 px in both facings, into a per-character cache under the data folder (never into the repo),
                    with a size cap and LRU eviction.
The remap tier lives in minis_core/movegen.py (re-exported here), so the pip wheel and the Windows zip learn those moves
too; this file adds the redrawn tier, which needs the rig and so only a source checkout has it.

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

if str(Path(__file__).resolve().parent.parent) not in sys.path:      # minis_core, also when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from minis_core.movegen import *  # noqa: F401,F403,E402  (the remap tier, ids, names, timing / silhouette QA, the cache)
from minis_core.movegen import (_round10, _desc, _mask, _iou, _index_path, _read_index, _write_index,  # noqa: F401,E402
                                REMAP_OPS, RENDER_OPS, OPS, MAX_FRAMES, CACHE_MAX_BYTES, SIZES)

CAP = {1: 31, 2: 63}                         # colours WITHOUT transparency per RES (art/build_fighters.CAPS minus one)
_ART = None
_MOVES = {}



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
        if not src_char or src_char == character or base in base_moves(character):
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
        # a real turn of the whole body: a side-on coil (shoulders square to the camera), then a BACK-TURNED key (the coil
        # drawn from the other facing: hips and shoulders swapped, the back to the opponent; render_frames swaps that
        # frame's facings), then the smear sweeps the blade round from behind the back into the contact
        flip = []
        for i, (ps, ms) in enumerate(frames):
            if i == s0:
                prev = frames[i - 1][0]
                wa = (prev.wa if prev.wa is not None else -60.0) + (120.0 if rng.random() < 0.5 else -120.0)
                side = replace(prev, turn=0.35, lean=prev.lean - 4, hf=(-prev.hf[0] * 0.8, prev.hf[1]), wa=((wa + 180) % 360) - 180,
                               face='g', dx=1.0, smear_f=(), smear_b=(), smear_ff=(), smear_fb=(), fx=(), ghost=())
                back = replace(prev, turn=0.7, lean=prev.lean + 2, face='g', dx=1.0, smear_f=(), smear_b=(), smear_ff=(), smear_fb=(),
                               fx=(), ghost=())
                out.append((side, 70))
                flip.append(len(out))
                out.append((back, 60))
                if ps.smear_f:                                    # the arc starts far behind the back: a wide crescent
                    ps = replace(ps, smear_f=(-abs(prev.hf[0]) - 6, prev.hf[1] - 2), ghost=())
                elif ps.smear_ff:
                    ps = replace(ps, smear_ff=(-abs(ps.ff[0]) - 4, ps.ff[1]), ghost=())
            out.append((ps, ms))
    else:                                                        # mimic: the poses as the source draws them, this body's weapon
        out = frames
    mv = dict(mv0, frames=out)
    sm2 = [i for i, (ps, _) in enumerate(out) if rig.is_smear(ps)]
    mv['smear_frames'] = sm2
    mv['hit_frame'] = hf + (2 if op == 'spin' else 0)
    if op == 'spin':
        mv['flip_frames'] = flip
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
    """The variant's frames through the real builder at `res`: [dict(r, l, buf, pose, ms, meta)].  A `flip_frames` key
    (the spin's back-turned frame) is drawn from the other facing: its right and left images swap, shifted so the hip
    stays on that facing's anchor column, and its part buffer is mirrored the same way (the QA reads it)."""
    from PIL import Image
    rig, moves, roster, BF = _art()
    ch = roster.get(character)
    rig.set_res(res)
    try:
        fr = BF.render_move(ch, '_learned', mv, None)
        cw, hip = rig.cell_px(), rig.hip_x_px()
    finally:
        rig.set_res(1)
    shift = hip - (cw - 1 - hip)                       # where the left sheet's hip sits, relative to the right sheet's
    for i in mv.get('flip_frames') or ():
        f = fr[i]
        r2, l2 = Image.new('RGBA', f['r'].size, (0, 0, 0, 0)), Image.new('RGBA', f['l'].size, (0, 0, 0, 0))
        r2.paste(f['l'], (shift, 0))
        l2.paste(f['r'], (-shift, 0))
        b2 = Image.new(f['buf'].mode, f['buf'].size, 0)
        b2.paste(f['buf'].transpose(Image.FLIP_LEFT_RIGHT), (shift, 0))
        fr[i] = dict(f, r=r2, l=l2, buf=b2, flipped=True)
    return fr


# ---------------------------------------------------------------- QA on rendered frames
def _colours(ims):
    out = set()
    for im in ims:
        for n, c in im.getcolors(1 << 20) or ():
            if c[3]:
                out.add(c[:3])
    return out


NOVELTY_IOU = 0.87            # a rendered variant needs one frame no base frame matches this closely (else it is not a new move)


def novelty(frames, base_frames):
    """-> the most novel frame's best match against the base row (min over variant frames of max IoU over base frames)."""
    if not base_frames:
        return 0.0
    bm = [_mask(b) for b in base_frames]
    return min(max(_iou(_mask(f['r']), b) for b in bm) for f in frames)


SPIN_TURN_MIN = 0.05          # the spin's back-turned frame must match the base's other facing by this margin
GHOST_BUDGET = 0              # stray opaque pixels allowed off the body / weapon / effects on a non-smear frame


def ghost_pixels(im, buf):
    """Opaque pixels of a frame that no rig part (body, weapon, cloth, effect) covers and that are not the 1 px outline
    around one: afterimage copies, smudges.  `buf` is the rig's part-id buffer of the same frame."""
    a, b = im.getchannel('A').load(), buf.load()
    w, h = im.size
    n = 0
    for y in range(h):
        for x in range(w):
            if a[x, y] and not b[x, y]:
                if not any(0 <= x + dx < w and 0 <= y + dy < h and b[x + dx, y + dy]
                           for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)):
                    n += 1
    return n


def qa(character, mv, frames, res, base_palette, idle_frame, min_reach=10.0, base_frames=None, base_frames_l=None):
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
    # novelty: an operator whose edits the fit passes undid (a greatsword pulled back in) is the base move again
    if base_frames:
        nv = novelty(frames, base_frames)
        if nv >= NOVELTY_IOU:
            bad.append(f'no new shape: every frame matches the base move (IoU {nv:.2f})')
    # a spin must really turn: one frame matches the base move's OTHER-facing frames clearly better than its own-facing ones
    if mv.get('flip_frames') is not None:
        turned = 0.0
        if base_frames_l and base_frames:
            for f in frames:
                m = _mask(f['r'])
                own = max(_iou(m, _mask(b)) for b in base_frames)
                other = max(_iou(m, _mask(b)) for b in base_frames_l)
                turned = max(turned, other - own)
        if turned < SPIN_TURN_MIN:
            bad.append(f'the spin never turns the body (best turned-frame margin {turned:.2f})')
    # ghost-pixel budget: outside a smear (and the authored afterimages of a key with `ghost`) nothing may sit off the body
    for i, f in enumerate(frames):
        ps = f['pose']
        if i in set(sm) or ps.ghost or ps.flash or (i and rig.is_smear(frames[i - 1]['pose'])):
            continue
        stray = ghost_pixels(f['r'], f['buf'])          # (not `n`: that is the frame count the reach check below reads)
        if stray > GHOST_BUDGET:
            bad.append(f'frame {i}: {stray} stray pixels off the body (afterimage outside a smear)')
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
    else:
        bad.append(f'no contact frame to measure the reach on (hit_frame {hf} of {n})')   # a check that cannot run fails
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
def _base_frames(character, base, res, facing=1):
    """The character's own row `base` (right-facing, or `facing`) at `res`, or [] when it has none (a borrowed move)."""
    try:
        from minis_core.atlas import Atlas
        a = Atlas(character, hd=(res == 2))
        if base not in a.anim:
            return []
        return [a.frame_image(base, i, facing) for i in range(len(a.anim[base]['frames']))]
    except Exception:
        return []


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
    try:
        d, mp, pngs = cache_paths(data_dir, character, move_id)
    except ValueError:
        return None, ['not an id']
    per_res = {}
    failures = []
    images = {}
    for res in sizes:
        frames = render_frames(character, mv, res)
        pal, idle = _sheet_palette(character, res)
        bad, reach = qa(character, mv, frames, res, pal, idle, base_frames=_base_frames(character, base, res),
                        base_frames_l=_base_frames(character, base, res, -1))
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
    suffix = f'.{os.getpid()}.{random.getrandbits(32):08x}.tmp'
    staged, placed = [], []
    try:                                       # every file is written to a temp name, then renamed; the metadata last, so a
        d.mkdir(parents=True, exist_ok=True)   # variant is in the cache only once all of it is (cached() reads the JSON)
        total = 0
        for res, im in images.items():
            t = Path(str(pngs[res]) + suffix)
            staged.append((t, pngs[res]))
            im.save(t, format='PNG')
            total += t.stat().st_size
        meta['bytes'] = total
        t = Path(str(mp) + suffix)
        staged.append((t, mp))
        t.write_text(json.dumps(meta, separators=(',', ':')), encoding='utf-8')
        for t, final in staged:
            os.replace(t, final)
            placed.append(final)
    except OSError as e:
        for t, final in staged:                # nothing half-built stays behind, inside or outside the size cap
            for q in (t, final if final in placed else None):
                if q is not None:
                    try:
                        q.unlink()
                    except OSError:
                        pass
        return None, [f'cache write failed: {type(e).__name__}']
    evict(data_dir)
    return meta, []


def _new_sheet(cw, n):
    from PIL import Image
    return Image.new('RGBA', (cw * n, cw * 2), (0, 0, 0, 0))



# ---------------------------------------------------------------- review sheets (the owner's bar: every frame clean, at 4x)
def review_sheet(character, mv, frames_by_res, label, onion=False):
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
                if onion and i > 0:                     # review aid only (--onion): the previous frame's silhouette, not in the sprite
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
    d.text((6, y + 68), label + ('   [dark red = onion skin of the previous frame: a review aid, not in the sprite]' if onion else ''),
           fill=(220, 220, 220), font=big)
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
    try:
        d, mp, pngs = cache_paths(a.data, a.character, mid)
    except ValueError:
        print('REJECT: not an id')
        return 1
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
    r.add_argument('--onion', action='store_true', help='draw the previous frame faintly behind each frame (a review aid)')
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
    src_bases = [n for n, e in Atlas(src).anim.items() if eligible_base(e) and not e.get('air') and n not in atlas.anim
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
                    sh = review_sheet(a.character, got, fbr, f'{a.character} {mid} ({op}, remap of {b}: frames {got["remap"]})', onion=a.onion)
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
                bad, reach = qa(a.character, mv, fr, res, pal, idle, base_frames=_base_frames(a.character, b, res),
                                base_frames_l=_base_frames(a.character, b, res, -1))
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
                sh = review_sheet(a.character, mv, frames_by_res, f'{a.character} {mid} ({op}{", from " + sc if sc else ""})', onion=a.onion)
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
