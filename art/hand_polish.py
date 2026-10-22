"""Hand-polish pass (V9): python art/hand_polish.py [write|check|sheets [--out DIR]]

The rig generates every frame; this pass corrects the most-seen ones pixel by pixel and saves them through the builder's
hand-polish hook (art/build_fighters.py): art/hand/<character>/<move>_<frame>.png (64 px) and ..._<frame>@2x.png (128 px).
Both facings are written (..._l.png): the 128 px build shades AFTER mirroring (light from the top-left on both facings), so
a mirrored right frame would be lit from the wrong side; each facing is corrected from its own generated frame, and a
manual edit given in right-facing coordinates is mirrored onto the left frame.

Which frames: TARGETS - the idle key pose, the signature strike's contact frame and the KO pose of the four most-seen
fighters (claude, codex, gemini, cursor), plus the knight's idle.  Rows that loop (idle, the KO stars) get the same
correction on every frame of the loop where the generated pixels are the same, so nothing flickers on and off.

What a correction is, in order (every step is reviewed at 1x and 4x, before / after, with `sheets`):
1. specks: a single pixel that matches none of its eight neighbours and touches at most two of them (a stray pixel left
   on the silhouette by the rasterizer) is cleared;
2. orphans inside a shape: a pixel whose four side neighbours all share one other colour takes that colour - except
   face ink and paper (eyes, brows, mouths, teeth), outlines, effects and the weapon's own highlight;
3. outline doubles: where a one-pixel outline steps in an L (three outline pixels round a corner) the corner pixel that
   does not touch the shape is cleared, so diagonals read as clean 1 px lines;
4. EDITS: explicit per-frame pixel edits found by eye (colour = another pixel of the same frame, or a palette tone).
Every colour written exists in that character's generated sheet at that resolution: the palette never grows.
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw  # noqa: E402
import rig  # noqa: E402
import roster  # noqa: E402
import build_fighters as BF  # noqa: E402
from moves import build_moves  # noqa: E402

HAND = os.path.join(HERE, 'hand')
DEFAULT_OUT = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'Temp', 'minis-hand-polish')

# (character, move or @strike / @ultimate, frame index or 'hit', [extra frames of the same loop], why)
TARGETS = [
    ('claude', 'idle', 0, 'all', 'idle key pose: the most-seen frame on the taskbar'),
    ('codex', 'idle', 0, 'all', 'idle key pose'),
    ('gemini', 'idle', 0, 'all', 'idle key pose'),
    ('cursor', 'idle', 0, 'all', 'idle key pose'),
    ('knight', 'idle', 0, 'all', 'idle key pose (the most-picked extra)'),
    ('claude', '@strike', 'hit', None, 'signature strike: the contact frame, held through the hitstop'),
    ('codex', '@strike', 'hit', None, 'signature strike contact'),
    ('gemini', '@strike', 'hit', None, 'signature strike contact'),
    ('cursor', '@strike', 'hit', None, 'signature strike contact'),
    ('claude', 'ko', 4, 'loop', 'KO pose: held for a second at every match point'),
    ('codex', 'ko', 4, 'loop', 'KO pose'),
    ('gemini', 'ko', 4, 'loop', 'KO pose'),
    ('cursor', 'ko', 4, 'loop', 'KO pose'),
]

# explicit edits found by eye: (character, move, frame, res) -> [(x, y, colour)]; colour '@x,y' = the colour of that pixel
# of the same generated frame, 'group.tone' = a palette tone, None = transparent
EDITS = {}


def move_name(ch, move):
    return ch.signature[move[1:]] if move.startswith('@') else move


def generated(ch, name, res):
    """(move, right frames, right part buffers, left frames, left part buffers) of one row at `res`, generated with the
    hand folder switched off."""
    old = os.environ.get('MINIS_HAND_DIR')
    os.environ['MINIS_HAND_DIR'] = os.path.join(HERE, '__no_hand__')
    old_clean = os.environ.get('MINIS_NO_CLEAN')
    os.environ['MINIS_NO_CLEAN'] = '1'                     # the raw rig frame: this pass shows (and makes) every correction
    rig.set_res(res)
    try:
        mv = build_moves(ch)[name]
        idle_pts = BF.idle_scarf(ch) if ch.body.has_tail else None
        fr = BF.render_move(ch, name, mv, None if name == 'idle' else idle_pts)
    finally:
        rig.set_res(1)
        if old is None:
            os.environ.pop('MINIS_HAND_DIR', None)
        else:
            os.environ['MINIS_HAND_DIR'] = old
        if old_clean is None:
            os.environ.pop('MINIS_NO_CLEAN', None)
        else:
            os.environ['MINIS_NO_CLEAN'] = old_clean
    return (mv, [f['r'] for f in fr], [f['buf'] for f in fr], [f['l'] for f in fr],
            [f['buf'].transpose(Image.FLIP_LEFT_RIGHT) for f in fr])


def protected_colours(body):
    """Face ink / paper, outlines, effects: never touched by the automatic steps."""
    pal = body.palette
    keep = set()
    for g in ('ink', 'paper', 'fx', 'flash'):
        for v in (pal.get(g) or {}).values():
            if isinstance(v, tuple):
                keep.add(tuple(v[:3]))
    for g, tones in pal.items():
        if isinstance(tones, dict) and 'ol' in tones:
            keep.add(tuple(tones['ol'][:3]))
    return keep


N8 = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
N4 = ((0, -1), (-1, 0), (1, 0), (0, 1))


FX_PARTS = {rig.PID[n] for n in rig.NOLINE if n in rig.PID}


def _candidates(im):
    """(specks, corners): opaque pixels with at most two opaque neighbours, and opaque pixels with exactly two opaque side
    neighbours - the only places steps 1 and 3 can apply, found with two 3x3 kernels instead of a Python loop."""
    from PIL import ImageChops
    w, h = im.size
    a = Image.new('L', (w + 2, h + 2), 0)                          # a transparent border, so a shifted copy wraps zeros
    a.paste(im.getchannel('A').point(lambda v: 1 if v else 0), (1, 1))
    n8, n4 = Image.new('L', a.size, 0), Image.new('L', a.size, 0)
    for dx, dy in N8:                                              # exact integer sums (a convolution kernel rounds
        sh = ImageChops.offset(a, dx, dy)                          # differently across Pillow versions: macOS CI vs here)
        n8 = ImageChops.add(n8, sh)
        if (dx, dy) in N4:
            n4 = ImageChops.add(n4, sh)
    box = (1, 1, w + 1, h + 1)
    av, v8, v4 = _pixels(a.crop(box)), _pixels(n8.crop(box)), _pixels(n4.crop(box))
    specks = [(i % w, i // w) for i, (o, c) in enumerate(zip(av, v8)) if o and c <= 2]
    corners = [(i % w, i // w) for i, (o, c) in enumerate(zip(av, v4)) if o and c == 2]
    return specks, corners


def clean(im, body, res, buf=None, orphans=True):
    """Steps 1-3 (see the module doc), on the BODY only: effects drawn into the cell (dust, shock, sparks, smears, streaks)
    are never touched - `buf` is the rig's part-id buffer of the same frame.  orphans=False skips step 2 (the builder runs
    steps 1 and 3 on every frame; step 2 is for the reviewed targets).  -> (image, [(x, y, before, after)])"""
    out = im.copy()
    src = im.load()
    px = out.load()
    w, h = im.size
    keep = protected_colours(body)
    changes = []
    bp = buf.load() if buf is not None else None

    def is_fx(x, y):
        if bp is None:
            return False
        if bp[x, y] in FX_PARTS:
            return True
        if bp[x, y] == 0:                                          # an outline pixel: fx carry no outline, so it is fx
            near = [bp[x + dx, y + dy] for dx, dy in N8 if 0 <= x + dx < w and 0 <= y + dy < h]
            return not any(v and v not in FX_PARTS for v in near)
        return False

    def at(x, y):
        return src[x, y] if 0 <= x < w and 0 <= y < h else (0, 0, 0, 0)
    specks, corners = _candidates(im)
    if res == 1:
        for x, y in specks:
            c = src[x, y]
            if is_fx(x, y):
                continue
            opaque = [n for n in (at(x + dx, y + dy) for dx, dy in N8) if n[3]]
            if all(n[:3] != c[:3] for n in opaque):
                px[x, y] = (0, 0, 0, 0)                                    # 1. a speck hanging off the silhouette
                changes.append((x, y, c, None))
    if orphans:
        for y in range(h):
            for x in range(w):
                c = px[x, y]
                if not c[3] or c[:3] in keep or is_fx(x, y):
                    continue
                side = [at(x + dx, y + dy) for dx, dy in N4]
                if all(s[3] for s in side) and len({s[:3] for s in side}) == 1 and side[0][:3] != c[:3] and side[0][:3] not in keep:
                    px[x, y] = side[0]                                      # 2. an orphan inside a shape
                    changes.append((x, y, c, side[0]))
    ol = outline_colours(body)
    src2 = out.copy().load()

    def at2(x, y):
        return src2[x, y] if 0 <= x < w and 0 <= y < h else (0, 0, 0, 0)
    def is_ol(x, y):
        """A real outline pixel: part id 0 in the rig buffer (a dark boot or glove is drawn in the outline colour, and
        the toe's own outline next to it is not a double); by colour alone when there is no buffer."""
        c = at2(x, y)
        if not c[3] or c[:3] not in ol:
            return False
        return bp is None or not (0 <= x < w and 0 <= y < h) or bp[x, y] == 0
    for x, y in corners:                                                   # 3. outline doubles on a corner
        c = src2[x, y]
        if not c[3] or not is_ol(x, y) or is_fx(x, y):
            continue
        for (ax, ay), (bx, by) in (((0, -1), (1, 0)), ((1, 0), (0, 1)), ((0, 1), (-1, 0)), ((-1, 0), (0, -1))):
            dg = at2(x + ax + bx, y + ay + by)
            oa, ob = at2(x - ax, y - ay), at2(x - bx, y - by)
            if is_ol(x + ax, y + ay) and is_ol(x + bx, y + by) and dg[3] and not oa[3] and not ob[3]:
                px[x, y] = (0, 0, 0, 0)
                changes.append((x, y, c, None))
                break
    return out, changes


def outline_colours(body):
    return {tuple(t['ol'][:3]) for t in body.palette.values() if isinstance(t, dict) and 'ol' in t}


def colour_of(spec, im, body):
    if spec is None:
        return (0, 0, 0, 0)
    if isinstance(spec, str) and spec.startswith('@'):
        x, y = (int(v) for v in spec[1:].split(','))
        return im.getpixel((x, y))
    if isinstance(spec, str) and '.' in spec:
        g, t = spec.split('.')
        return tuple(body.palette[g][t][:3]) + (255,)
    return tuple(spec)


def polish(ch, name, i, res, gen=None, side='r'):
    """-> (before, after, changes) for one frame of one facing."""
    mv, frames, bufs, frames_l, bufs_l = gen or generated(ch, name, res)
    before = (frames if side == 'r' else frames_l)[i]
    after, changes = clean(before, ch.body, res, (bufs if side == 'r' else bufs_l)[i])
    cw = before.width
    for x, y, spec in EDITS.get((ch.name, name, i, res), ()):
        if side == 'l':
            x = cw - 1 - x
            if isinstance(spec, str) and spec.startswith('@'):
                sx, sy = (int(v) for v in spec[1:].split(','))
                spec = f'@{cw - 1 - sx},{sy}'
        c = colour_of(spec, before, ch.body)
        changes.append((x, y, after.getpixel((x, y)), c))
        after.putpixel((x, y), c)
    return before, after, changes


def frames_of(ch, mv, sel, loop):
    n = len(mv['frames'])
    i = mv.get('hit_frame') if sel == 'hit' else int(sel)
    if loop == 'all':
        return list(range(n))
    if loop == 'loop':
        lo, hi = mv.get('loop_range') or (0, n - 1)
        return list(range(lo, hi + 1))
    return [i]


def plan():
    """-> [(ch, name, frame index)] every frame this pass writes."""
    out = []
    for cname, move, sel, loop, _why in TARGETS:
        ch = roster.get(cname)
        name = move_name(ch, move)
        mv = build_moves(ch)[name]
        for i in frames_of(ch, mv, sel, loop):
            out.append((ch, name, i))
    return out


def write(root=HAND):
    written, report = [], []
    cache = {}
    for ch, name, i in plan():
        for res in (1, 2):
            key = (ch.name, name, res)
            if key not in cache:
                cache[key] = generated(ch, name, res)
            outs = [polish(ch, name, i, res, cache[key], side) for side in ('r', 'l')]
            if not any(o[2] for o in outs):
                continue
            d = os.path.join(root, ch.name)
            os.makedirs(d, exist_ok=True)
            stem = os.path.join(d, f'{name}_{i}' + ('@2x' if res == 2 else ''))
            outs[0][1].save(stem + '.png')
            outs[1][1].save(stem + '_l.png')
            written += [stem + '.png', stem + '_l.png']
            report.append(dict(character=ch.name, move=name, frame=i, res=res, pixels_right=len(outs[0][2]), pixels_left=len(outs[1][2])))
    with open(os.path.join(root, 'POLISH.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
        f.write('\n')
    return written, report


def check(root=HAND):
    """Every hand frame: the cell size of its resolution, opaque pixels only in colours of the character's generated
    sheet, and within a few pixels of the generated frame (a correction, not a redraw)."""
    problems = []
    cache = {}
    for ch, name, i in plan():
        for res in (1, 2):
            for side, k in (('', 1), ('_l', 3)):
                p = os.path.join(root, ch.name, f'{name}_{i}' + ('@2x' if res == 2 else '') + side + '.png')
                if os.path.exists(p):
                    key = (ch.name, name, res)
                    if key not in cache:
                        cache[key] = generated(ch, name, res)
                    problems += _check_one(p, cache[key][k], i)
    return problems


def _pixels(im):
    fn = getattr(im, 'get_flattened_data', None)        # Pillow 12.3+ deprecates getdata
    return fn() if fn is not None else im.getdata()


def _check_one(p, frames, i):
    """One hand file against the generated frames of its row and facing."""
    im = Image.open(p).convert('RGBA')
    gen = frames[i]
    if im.size != gen.size:
        return [f'{p}: size {im.size} != {gen.size}']
    pal = set()
    for f in frames:
        pal |= {c[:3] for c in _pixels(f) if c[3]}
    problems = []
    bad = {c[:3] for c in _pixels(im) if c[3] and c[:3] not in pal}
    diff = sum(1 for a, b in zip(_pixels(im), _pixels(gen)) if a != b)
    if bad:
        problems.append(f'{p}: {len(bad)} colours outside the generated palette')
    if diff > 0.04 * im.width * im.height:
        problems.append(f'{p}: {diff} pixels changed (a correction should stay small)')
    return problems


# ---------------------------------------------------------------- review sheets
def _zoom(im, k, bg=(40, 40, 46)):
    b = Image.new('RGBA', im.size, bg + (255,))
    b.alpha_composite(im)
    return b.resize((im.width * k, im.height * k), Image.NEAREST).convert('RGB')


def sheet(ch, name, i, out_dir):
    """Before / after of one frame: 1x and 4x (64 px), 2x (128 px, the same screen size as 4x of 64), both facings,
    with the changed pixels circled on the 'after' zoom."""
    from PIL import ImageFont
    rows = []
    for res, k in ((1, 4), (2, 2)):
        gen = generated(ch, name, res)
        before, after, changes = polish(ch, name, i, res, gen)
        b_l, a_l, _ = polish(ch, name, i, res, gen, 'l')
        tiles = [_zoom(before, 1), _zoom(after, 1), _zoom(before, k), _zoom(after, k), _zoom(b_l, k), _zoom(a_l, k)]
        za = tiles[3]
        d = ImageDraw.Draw(za)
        for x, y, *_ in changes:
            d.rectangle([x * k - 1, y * k - 1, x * k + k, y * k + k], outline=(255, 60, 200))
        rows.append((res, tiles, len(changes)))
    W_ = sum(t.width for t in rows[0][1]) + 7 * 8
    H_ = sum(max(t.height for t in r[1]) + 22 for r in rows) + 24
    im = Image.new('RGB', (W_, H_), (24, 24, 28))
    d = ImageDraw.Draw(im)
    d.text((6, 4), f'{ch.name} {name} frame {i}: before | after (1x), before | after (zoom, changed pixels marked), left-facing before | after',
           fill=(230, 230, 230))
    y = 24
    for res, tiles, n in rows:
        d.text((6, y), f'RES {res} ({64 * res} px): {n} pixels changed', fill=(255, 200, 120))
        x = 6
        for t in tiles:
            im.paste(t, (x, y + 18))
            x += t.width + 8
        y += max(t.height for t in tiles) + 22
    p = os.path.join(out_dir, f'{ch.name}-{name}-{i}.png')
    im.save(p)
    return p


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('write', 'check', 'sheets'))
    ap.add_argument('--out', default=DEFAULT_OUT)
    a = ap.parse_args()
    if a.cmd == 'write':
        w, rep = write()
        print(f'{len(w)} hand frames written')
        for r in rep:
            print(r)
    elif a.cmd == 'check':
        pr = check()
        print('\n'.join(pr) or 'OK')
        sys.exit(1 if pr else 0)
    else:
        os.makedirs(a.out, exist_ok=True)
        for cname, move, sel, loop, _ in TARGETS:
            ch = roster.get(cname)
            name = move_name(ch, move)
            mv = build_moves(ch)[name]
            i = mv.get('hit_frame') if sel == 'hit' else int(sel)
            print(sheet(ch, name, i, a.out))
