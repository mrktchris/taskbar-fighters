"""Build every roster character: python art/build_fighters.py [--out assets] [--res 1|2] [--cap N] [--only <character>[,<character>]]

Writes <out>/<character>/{sheet.png, sheet_l.png, proj.png, anim.json, fx.png, fx.json}.  Characters come from art/roster.py.
`--res 2` renders the same pose data into 128 px cells (assets_hd/, <= 64 colours); `--res 1` is the 64 px taskbar build
(assets/, <= 32 colours) and is byte-identical to the V3 output for every move that existed then.  `--all` builds both.

Hand-polished frames: drop a 64x64 RGBA PNG drawn in the character's palette at
    art/hand/<character>/<move>_<frameindex>.png          (or set MINIS_HAND_DIR to use another folder)
and the builder uses it instead of the generated right-facing frame.  For the 128 px build (RES 2) the file is
    art/hand/<character>/<move>_<frameindex>@2x.png       (128x128; V9 - a 64 px file is never used at RES 2)
An optional <move>_<frameindex>[@2x]_l.png is used as the left-facing frame instead of the mirror (the HD build shades
after mirroring, light from the top-left on both facings, so a mirrored HD frame would be lit from the wrong side).
art/hand_polish.py writes all of them from the generated frames plus a reviewed list of pixel edits.  The left-facing frame is its mirror with the cap
sigil redrawn un-mirrored at the generator's sigil position (keep the sigil where the generator put it), touching only
cap-cloth or sigil-coloured pixels so a hand drawn over the cap stays on top.
"""
from __future__ import annotations
import argparse, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw  # noqa: E402
import rig  # noqa: E402
from rig import W, H, HIP_X, GROUND, PID, NAME, render_parts, mirror_parts, mirror_rgba, finish, palette_of  # noqa: E402
from moves import build_moves, combo_for  # noqa: E402
import roster  # noqa: E402
import fx as FXMOD  # noqa: E402

COLS = 8
PROJ_W, PROJ_H, PROJ_FRAMES = 24, 20, 3          # design units; the strip is RES x this
CREDITS = ('Animation reference & inspiration: LuizMelo (Martial Hero, CC0), Mattz Art / xzany (Samurai pack), '
           'GandalfHardcore (Archer pack). All frames are original; see docs/CREDITS.md.')
SCHEMA_NOTES = {                                 # V5 keys the engine may read; everything older is unchanged
    'hitstop_ms': 'per move: how long both fighters should freeze when hit_frame lands (light 150, medium 180, heavy 220, ultimate 260-320).',
    'shake': 'per move, optional {frames, amp}: screen shake the fighter itself asks for on its hit_frame (amp in px at this res).',
    'smear_frames': 'per move, optional: frame indices drawn as smears (one-frame motion arcs); play them short (<= 50 ms), never hold them.',
    'credits': 'top level: the reference-pack credit line to show in-game.',
    'type': 'V7, per move: what the move is to the choreographer (string, riposte, air, spike, throw, through, guard_break, '
            'pull, gust, boomerang, taunt; reactions launched, air_hit, spiked, thrown, pulled, guard_crush).',
    'family': 'V7, per move: the weapon family it belongs to (blade, dual, polearm, staff, chain, bow, fans, heavy).',
    'input': 'V7, per move: the fighting-game input label shown in the move list (decoration; nothing reads it as input).',
    'armor': 'V7, per move: true = a light hit during the wind-up does not make the fighter flinch.',
    'pull_frame': 'V7, per move: the frame the chain yanks the opponent in.',
    'catch_frame': 'V7, per move: the frame a thrown boomerang projectile is caught again.',
    'cancel_frame': 'V7, per move: in a string, the next hit may start at this frame (the rest of the move is cancelled).',
    'lock_frame': 'V7, per move: the frame two clashing weapons meet (the clash row).',
    'hit': 'V7, per move: slash / blunt / pierce: which contact spark the engine draws.',
    'height': 'V7, per move: high / mid / low / back: which directional reaction the defender plays.',
    'combo': "V7, top level: the character's 3-hit string, played with cancel timing.",
    'grip': 'V8 forge, per move: one entry per frame for the front (main) weapon hand, [x, y, angle_deg, hand] or null '
            'when no weapon is held (a thrown chakram).  x = px right of the anchor column CENTRE (anchor.R + 0.5) in the '
            'right-facing sheet; y = px below the top of the ground_y row (negative = up); for the left-facing sheet negate '
            'x and use 180 - angle.  angle = screen degrees of the rendered weapon axis from the grip toward the tip '
            '(0 = forward, -90 = up; a bow: the arrow direction, the bow stands across it; a chakram: toward the ring centre).  '
            "hand 'f' (front) / 'b'.  Pair it with sheet_unarmed*.png to draw another weapon in the hand.",
    'grip2': "V8 forge, per move: the same for the back hand when it holds a second weapon (dual) or the grip of a "
             "two-handed weapon (same angle as grip), else null per frame.",
    'sheets_unarmed': 'V8 forge, top level: the same cells, rows and frames with the held weapon(s), their swing crescents '
                      'and streaks and a nocked string / arrow not drawn (the hands still close round the empty grip).',
    'air': 'V8, per airborne move: the trajectory the engine draws, [[t_ms, h], [t_ms, h, ease], ...]; t_ms on the row clock '
           '(frame starts from the ms values), h = RES 1 design px above the floor (the same at every res; multiply by res), '
           "ease of the segment ending at that key: 'o' rise, 'i' fall, 'h' hang, else linear.  Before the first key the first h, "
           'after the last key the last h (a row may end in the air).  The frames carry only the pose.',
}
CAPS = {1: 32, 2: 64}                            # colours incl. transparency per RES
OUT_DIRS = {1: 'assets', 2: 'assets_hd'}


def hand_dir():
    """Read per call so tests (and artists) can point MINIS_HAND_DIR somewhere else."""
    return os.environ.get('MINIS_HAND_DIR') or os.path.join(HERE, 'hand')


# ---------------------------------------------------------------- scarf / ponytail
def head_attach(body, pose):
    """Where the scarf / ponytail hangs from, in design units: the rig's own head geometry (squash included)."""
    bf = rig.body_frame(body, pose)
    ox, oy = rig.rot(body.tail_anchor, bf['tilt'])
    return (bf['head'][0] + ox, bf['head'][1] + oy)


SEG_MIN, SEG_MAX = 0.7, 1.5      # segment length bounds, in units of the rest segment length
FLOOR = GROUND - 2.5              # lowest scarf centre line: the 3 px cloth band then ends on the ground row


def scarf_step(body, pts, ps):
    """One frame of cloth lag: each point eases toward a trailing target, then the segment is held to
    [SEG_MIN, SEG_MAX] x its rest length so a sudden anchor jump (falling, getting up) never stretches a pole."""
    n_seg, seg = body.tail_seg
    a = head_attach(body, ps)
    new = [a]
    for k in range(1, n_seg + 1):
        px, py = pts[k]
        tx = new[k - 1][0] - seg * 0.92 - 0.20 * ps.dx
        ty = new[k - 1][1] + 0.55 + 0.35 * k + (0.10 * ps.dx if ps.dx < 0 else 0) - (0.5 if ps.dy < 0 else 0)
        nx, ny = px + 0.55 * (tx - px), py + 0.55 * (ty - py)
        ax, ay = new[k - 1]
        dx, dy = nx - ax, ny - ay
        d = math.hypot(dx, dy)
        if d < 1e-6:
            nx, ny, d = ax - seg, ay, seg
            dx, dy = -seg, 0.0
        lo, hi = seg * SEG_MIN, seg * SEG_MAX
        if d < lo or d > hi:
            k_ = (lo if d < lo else hi) / d
            nx, ny = ax + dx * k_, ay + dy * k_
        if ny > FLOOR:                                   # the cloth lies on the taskbar instead of sinking into it
            ny = FLOOR
            ddx = nx - ax
            ddy = ny - ay
            dd = math.hypot(ddx, ddy)
            if dd > hi:                                  # keep the segment length after sliding along the floor
                nx = ax + math.copysign(math.sqrt(max(0.0, hi * hi - ddy * ddy)), ddx if ddx else -1.0)
            elif dd < lo and abs(ddy) < lo:
                nx = ax + math.copysign(math.sqrt(lo * lo - ddy * ddy), ddx if ddx else -1.0)
        new.append((nx, ny))
    return new


def _rest(body, a):
    n_seg, seg = body.tail_seg
    return [(a[0] - seg * k * 0.95, a[1] + 0.8 * k) for k in range(n_seg + 1)]


def _run(body, poses, pts):
    out = []
    for ps in poses:
        pts = scarf_step(body, pts, ps)
        out.append(pts)
    return out, pts


PASSES = 6


def idle_scarf(ch):
    """The idle loop's settled scarf: the state the scarf is in when any move starts from idle."""
    ch = roster.get(ch)
    body = ch.body
    idle = [f[0] for f in build_moves(ch)['idle']['frames']]
    pts = _rest(body, head_attach(body, idle[0]))
    for _ in range(PASSES):
        _, pts = _run(body, idle, pts)
    return pts


def scarf_track(body, poses, loop=False, loop_range=None, start=None):
    """Per-frame scarf points.  Non-looping moves start from the idle scarf (moved to the move's first anchor);
    looping moves are simulated until the loop range repeats, so the last loop frame flows into the first."""
    if not body.has_tail:
        return [None] * len(poses)
    if start is None:
        start = _rest(body, head_attach(body, poses[0]))
    a0 = head_attach(body, poses[0])
    ox, oy = a0[0] - start[0][0], a0[1] - start[0][1]
    pts = [(x + ox, y + oy) for x, y in start]
    if not loop:
        return _run(body, poses, pts)[0]
    lo, hi = loop_range if loop_range else (0, len(poses) - 1)
    intro, pts = _run(body, poses[:lo], pts)
    seg = poses[lo:hi + 1]
    for _ in range(PASSES):
        looped, pts = _run(body, seg, pts)
    outro, _ = _run(body, poses[hi + 1:], pts)
    return intro + looped + outro


# ---------------------------------------------------------------- frame helpers
LERP_FIELDS = ('dx', 'cx', 'dy', 'lean', 'tilt', 'sq', 'chest', 'turn')
LERP_PAIRS = ('head', 'hf', 'hb', 'ff', 'fb')


def lerp_pose(a, b, k):
    """The pose k of the way from a to b: numeric fields interpolate, everything else (face, fx, bends) is b's."""
    kw = {f: getattr(a, f) + (getattr(b, f) - getattr(a, f)) * k for f in LERP_FIELDS}
    for f in LERP_PAIRS:
        pa, pb = getattr(a, f), getattr(b, f)
        kw[f] = (pa[0] + (pb[0] - pa[0]) * k, pa[1] + (pb[1] - pa[1]) * k)
    from dataclasses import replace
    return replace(b, fx=(), ghost=(), flash=False, aura=0, doc='', smear_f=(), smear_b=(), smear_ff=(), smear_fb=(), **kw)


GHOST_DENSITY = (2, 5, 9, 12)         # one pixel in N for the 1st, 2nd, 3rd, 4th copy back: nearest is a checker, the rest thin out
GHOST_SCALE = (0.92, 0.85, 0.78, 0.72)


def ghost(im, offsets, body, mirrored, pose=None, prev=None):
    """A real afterimage: 3-4 copies of the fighter trailing BEHIND it along the motion arc, each one further back,
    smaller (scaled toward the ground anchor) and sparser.  Each copy is rendered from the pose interpolated between the
    previous keyframe and this one, so the trail follows the arc the body actually took, not a stack of this frame.
    'holo' bodies (the cyber-samurai look) use neon scanlines instead of a checker."""
    if not offsets:
        return im
    S = rig.RES
    cw, ax, ay = rig.cell_px(), rig.hip_x_px(), rig.ground_px()
    out = im.copy()
    op = out.load()
    pal = body.palette
    g = pal[body.ghost_group]
    style = body.ghost_style
    holo = style == 'holo'
    tones = [pal['trim']['hi'], pal['cloth']['hi'], pal['trim']['base'], pal['trim']['sh']] if holo else [g['hi'], g['base'], g['sh'], g['sh']]
    sparks = []                                                        # 'spark': star points left in the trail
    behind = -1.0 if (pose is None or pose.dx >= 0) else 1.0          # ghosts trail opposite to the travel direction
    if mirrored:
        behind = -behind
    n = len(offsets)
    for gi, off in enumerate(offsets):
        k = 1.0 - (gi + 1) / (n + 1)                                   # how far along prev -> now this copy sits
        gp = lerp_pose(prev, pose, k) if (pose is not None and prev is not None) else (pose or rig.Pose())
        buf, meta = rig.render_parts(body, gp, None)
        if mirrored:
            buf = rig.mirror_parts(buf, meta, body)
        src = rig.finish(buf, body, gp, meta['hip'][1]).load()
        sc = GHOST_SCALE[min(gi, len(GHOST_SCALE) - 1)]
        dens = GHOST_DENSITY[min(gi, len(GHOST_DENSITY) - 1)]
        col = tones[min(gi, len(tones) - 1)] + (255,)
        shift = behind * off * S
        for y in range(cw):
            for x in range(cw):
                if op[x, y][3]:
                    continue
                sx = ax + (x - shift - ax) / sc                        # inverse map: dest -> source around the anchor
                sy = ay + (y - ay) / sc
                sxi, syi = rig.rnd(sx), rig.rnd(sy)
                if not (0 <= sxi < cw and 0 <= syi < cw) or not src[sxi, syi][3]:
                    continue
                if holo:                                               # scanlines, broken into dashes that thin out
                    on = ((y // S) % 2 == 0) and ((x // S + gi * 2) % (dens + 1) < 2)
                elif style == 'streak':                                # horizontal speed-line dashes, every third row
                    on = ((y // S + gi) % 3 == 0) and ((x // S + gi * 3) % (dens + 3) < 4)
                else:
                    on = ((x // S) * 3 + (y // S) * 5 + gi * 2) % dens == 0
                if on:
                    op[x, y] = col
                    if style == 'spark' and ((x // S) * 7 + (y // S) * 11 + gi) % 29 == 0:
                        sparks.append((x, y, gi))
    if style == 'spark':                                               # four-point sparkles scattered through the trail
        for x, y, gi in sparks:
            c = (pal['trim']['hi'] if gi == 0 else tones[min(gi, len(tones) - 1)]) + (255,)
            for dx, dy in ((0, 0), (-S, 0), (S, 0), (0, -S), (0, S)):
                if 0 <= x + dx < cw and 0 <= y + dy < cw and not op[x + dx, y + dy][3]:
                    op[x + dx, y + dy] = c
    return out


STRIKE_PARTS = {'hf': ('hand_f', 'cuff_f', 'arm_f_fo', 'wpn_f', 'hilt_f', 'blade_hl'), 'hb': ('hand_b', 'cuff_b', 'arm_b_fo', 'wpn_b', 'hilt_b'),
                'ff': ('shoe_f', 'sole_f', 'leg_f_sh', 'boot_f'), 'fb': ('shoe_b', 'sole_b', 'leg_b_sh', 'boot_b')}
IMPACT_FX = ('spark', 'spark_s', 'block')
MISSILE_FX = ('arrow', 'kunai', 'chain', 'gust')
BODY_IDS = {PID[n] for n in rig.PART_ORDER if n not in rig.NOLINE and n not in ('doc', 'doc_line')}


def frame_history(poses, i, loop):
    """(previous pose, pose two back) for frame i: a loop wraps round, a one-shot starts from its own first pose."""
    n = len(poses)
    if loop:
        return poses[(i - 1) % n], poses[(i - 2) % n]
    return (poses[i - 1] if i >= 1 else poses[0]), (poses[i - 2] if i >= 2 else poses[0])


def ghost_prev(im, body, prev, mirrored, pose):
    """The smear frame's ghosted previous pose: a checker of the ghost tone wherever the striking limb (and its weapon)
    was on the previous frame and this frame is not - one copy, not a trail."""
    S = rig.RES
    buf, meta = rig.render_parts(body, prev, None)
    if mirrored:
        buf = rig.mirror_parts(buf, meta, body)
    out = im.copy()
    op, bp = out.load(), buf.load()
    col = body.palette[body.ghost_group]['hi'] + (255,)
    cw = rig.cell_px()
    sides = [s_ for s_, k in (('f', 'smear_f'), ('b', 'smear_b')) if getattr(pose, k)]
    legs = [s_ for s_, k in (('f', 'smear_ff'), ('b', 'smear_fb')) if getattr(pose, k)]
    ids = set()
    for s_ in sides:
        ids |= {rig.PID[n] for n in (f'arm_{s_}_fo', f'cuff_{s_}', f'hand_{s_}', f'wpn_{s_}', f'hilt_{s_}')}
    for s_ in legs:
        ids |= {rig.PID[n] for n in (f'leg_{s_}_sh', f'shoe_{s_}', f'boot_{s_}', f'sole_{s_}')}
    for y in range(cw):
        for x in range(cw):
            if op[x, y][3] or bp[x, y] not in ids:
                continue
            if ((x // S) + (y // S)) % 2 == 0:
                op[x, y] = col
    return out



def hit_reach(buf, pose):
    """Reach of a strike, from the pixels that actually strike: the limb the impact effect is anchored to
    (or the whole body when the hit has no limb anchor, e.g. ground_pound's shockwave).  Distance from the hip
    column to the outer edge of the outline around the furthest striking pixel."""
    anc = next((f[1] for f in pose.fx if f[0] in IMPACT_FX and f[1] in STRIKE_PARTS), None)
    px = buf.load()
    S = rig.RES
    cw, hipx = rig.cell_px(), rig.hip_x_px()

    def edge(ids):
        xs = [x for y in range(cw) for x in range(cw) if px[x, y] in ids]
        return max(xs) + 1 + S - hipx if xs else None    # one past the limb, plus the RES px outline
    if any(f[0] in MISSILE_FX for f in pose.fx):         # V7: an in-cell missile (arrow, kunai, chain, gust) is what lands
        fx_ids = {PID[n] for n in ('fx_a', 'fx_b', 'fx_w', 'fx_c')}
        xs = [x for y in range(cw) for x in range(cw) if px[x, y] in fx_ids]
        return max(xs) + 1 - hipx
    if anc is None:                                      # a slam: the shockwave is what lands
        if any(f[0] == 'shock' for f in pose.fx):
            fx_ids = {PID[n] for n in ('fx_a', 'fx_b', 'fx_w', 'fx_c')}
            xs = [x for y in range(cw) for x in range(cw) if px[x, y] in fx_ids]
            return max(xs) + 1 - hipx                    # effects carry no outline
        return edge(BODY_IDS)
    # a limb hidden behind its twin (Codex's short arms put the rear fist exactly behind the lead arm in `cross`):
    # what lands is the visible pair, so measure both limbs of that kind
    twin = {'hf': 'hb', 'hb': 'hf', 'ff': 'fb', 'fb': 'ff'}[anc]
    return edge({PID[n] for n in STRIKE_PARTS[anc]}) or edge({PID[n] for n in STRIKE_PARTS[anc] + STRIKE_PARTS[twin]})


def _col(pal, spec):
    g, t = spec.split('.')
    return pal[g][t]


class _SD:
    """ImageDraw in DESIGN units: every coordinate is multiplied by RES, a point is a RES x RES block, a line is RES wide.
    At RES 1 every call is the exact PIL call the V3 builder made."""

    def __init__(self, im):
        self.d = ImageDraw.Draw(im)
        self.S = rig.RES

    def _c(self, c):
        return tuple(c) + (255,) if len(c) == 3 else tuple(c)

    def rectangle(self, box, fill):
        S = self.S
        x0, y0, x1, y1 = box
        self.d.rectangle([x0 * S, y0 * S, x1 * S + S - 1, y1 * S + S - 1], fill=self._c(fill))

    def ellipse(self, box, fill):
        S = self.S
        x0, y0, x1, y1 = box
        self.d.ellipse([x0 * S, y0 * S, x1 * S + S - 1, y1 * S + S - 1], fill=self._c(fill))

    def point(self, xy, fill):
        S = self.S
        x, y = xy
        if S == 1:
            self.d.point((x, y), fill=self._c(fill))
        else:
            self.d.rectangle([rig.rnd(x * S), rig.rnd(y * S), rig.rnd(x * S) + S - 1, rig.rnd(y * S) + S - 1], fill=self._c(fill))

    def line(self, pts, fill):
        S = self.S
        if S == 1:
            self.d.line(pts, fill=self._c(fill))
        else:
            self.d.line([(x * S, y * S) for x, y in pts], fill=self._c(fill), width=S)


def projectile(ch):
    """3-frame projectile strip, drawn from the character's palette (style from the roster), at the current RES."""
    body, spec = ch.body, ch.projectile
    pal = body.palette
    S = rig.RES
    cols = [_col(pal, c) for c in spec.get('cols', ())]
    fr = []
    for k in range(PROJ_FRAMES):
        im = Image.new('RGBA', (PROJ_W * S, PROJ_H * S), (0, 0, 0, 0))
        d = _SD(im)
        st = spec['style']
        if st == 'arc':                              # crescent wave (Claude's '/' slash wave)
            r = 11 + (k - 1) * 1
            for col, th in zip(cols, (5, 3, 1)):
                pts = [(6 + r * math.cos(math.radians(a)), 10 + r * math.sin(math.radians(a)) * 0.95) for a in range(-60, 61, 6)]
                for j in range(len(pts) - 1):
                    for t in range(th):
                        d.line([(pts[j][0] - t, pts[j][1]), (pts[j + 1][0] - t, pts[j + 1][1])], fill=col)
            for (sx, sy) in [(2, 4 + k), (3, 15 - k), (0, 10)]:
                d.point((sx, sy), fill=_col(pal, spec['spark']))
        elif st == 'term':                           # terminal block with a glyph (Codex '>_', Cursor '>|')
            ink, face, shade = cols
            mark = _col(pal, spec['mark'])
            d.rectangle([5, 4, 22, 15], fill=ink)
            d.rectangle([6, 5, 21, 14], fill=face)
            d.rectangle([6, 12, 21, 14], fill=shade)
            for (dx, dy) in [(0, 0), (1, 1), (2, 2), (1, 3), (0, 4)]:
                d.point((8 + dx, 6 + dy), fill=mark)
            if spec['glyph'].endswith('_'):
                d.line([(12, 11), (16, 11)], fill=mark)
            else:                                    # a blinking caret: brighter on the middle frame
                d.line([(13, 5), (13, 11)], fill=mark)
                if k == 1:
                    d.line([(14, 5), (14, 11)], fill=mark)
            for t in range(3 + k):
                d.line([(0, 6 + t * 3), (3 + (t % 2) * 2, 6 + t * 3)], fill=_col(pal, spec['trail']))
        elif st == 'star':                           # four-point sparkle (Gemini)
            core, mid, rim = cols
            cx, cy = 14, 10
            arm = 7 + (k % 2)
            for i in range(1, arm + 1):
                w_ = 1 if i > 2 else 2
                c = core if i <= 2 else (mid if i <= 5 else rim)
                for s_ in range(-w_ + 1, w_):
                    for (x, y) in ((cx + i, cy + s_), (cx - i, cy + s_), (cx + s_, cy + i), (cx + s_, cy - i)):
                        d.point((x, y), fill=c)
            d.rectangle([cx - 1, cy - 1, cx + 1, cy + 1], fill=core)
            for (sx, sy) in [(3, 4 + k), (2, 15 - k), (0, 10)]:
                d.point((sx, sy), fill=_col(pal, spec['spark']))
        elif st == 'orb':                            # round orb with a highlight and a trail (Ollama, generic)
            ol, face, hi = cols
            cx, cy, r = 15, 10, 6 + (k == 1)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ol)
            d.ellipse([cx - r + 1, cy - r + 1, cx + r - 1, cy + r - 1], fill=face)
            d.ellipse([cx - 3, cy - 4, cx, cy - 1], fill=hi)
            for t in range(3 + k):
                d.line([(0 + t % 2, 5 + t * 3), (6 - (t % 2) * 2, 5 + t * 3)], fill=_col(pal, spec['trail']))
        else:
            raise ValueError(f'{ch.name}: unknown projectile style {st}')
        fr.append(im)
    strip = Image.new('RGBA', (PROJ_W * S * PROJ_FRAMES, PROJ_H * S), (0, 0, 0, 0))
    for k, im in enumerate(fr):
        strip.paste(im, (PROJ_W * S * k, 0))
    return strip


# ---------------------------------------------------------------- V8 forge: grip data
def grips(body, pose):
    """-> (grip, grip2) for one frame at the current RES (see SCHEMA_NOTES 'grip')."""
    S = rig.RES
    sk = rig.skeleton(body, pose)
    ax, gy = rig.hip_x_px() + 0.5, rig.ground_px()

    def entry(hand, ang, side):
        return [round(hand[0] * S - ax, 1), round(hand[1] * S - gy, 1), round(((ang + 180.0) % 360.0) - 180.0, 1), side]
    wf = sk['wf']
    g1 = entry(wf['hand'], wf['a'], 'f') if wf is not None else None
    g2 = None
    if sk['wb'] is not None:
        g2 = entry(sk['wb']['hand'], sk['wb']['a'], 'b')
    elif (wf is not None and wf['spec'].grip2 and body.weapon_b is None and not pose.free_b and pose.doc != 'hb'):
        g2 = entry(sk['hb'], wf['a'], 'b')
    return g1, g2


# ---------------------------------------------------------------- build
def render_move(ch, name, mv, idle_pts=None):
    """-> list of dict(r, l, pose, ms, buf, meta, scarf) for one move (hand overrides applied)."""
    body = ch.body
    poses = [f[0] for f in mv['frames']]
    if mv['loop']:
        scarf = scarf_track(body, poses, True, mv.get('loop_range'), start=idle_pts)
    else:
        scarf = scarf_track(body, poses, False, start=idle_pts)
    out = []
    for i, (pose, ms) in enumerate(mv['frames']):
        prev, prev2 = frame_history(poses, i, mv['loop'])
        buf, meta = render_parts(body, pose, scarf[i], prev=prev, hist=(prev2, prev))
        hip_y = meta['hip'][1]
        gprev = prev if prev is not None else pose
        im_r = ghost(finish(buf, body, pose, hip_y), pose.ghost, body, False, pose, gprev)
        im_l = ghost(finish(mirror_parts(buf, meta, body), body, pose, hip_y), pose.ghost, body, True, pose, gprev)
        if rig.is_smear(pose) and prev is not None and not pose.flash and not pose.ghost:
            im_r = ghost_prev(im_r, body, prev, False, pose)
            im_l = ghost_prev(im_l, body, prev, True, pose)
        if not os.environ.get('MINIS_NO_CLEAN'):                # V9: every frame, both facings: no stray pixels, clean corners
            import hand_polish
            im_r = hand_polish.clean(im_r, body, rig.RES, buf, orphans=False)[0]
            im_l = hand_polish.clean(im_l, body, rig.RES, buf.transpose(Image.FLIP_LEFT_RIGHT), orphans=False)[0]
        hp = os.path.join(hand_dir(), ch.name, f'{name}_{i}' + ('@%dx' % rig.RES if rig.RES > 1 else '') + '.png')
        if os.path.exists(hp) and not rig.UNARMED:       # an artist's frame (same palette, same cell size) replaces the generated one
            hand = Image.open(hp).convert('RGBA')
            if hand.size == (rig.cell_px(), rig.cell_px()):
                im_r = hand
                hpl = hp[:-4] + '_l.png'                 # V9: its own left-facing frame (HD light stays top-left), else the mirror
                hand_l = Image.open(hpl).convert('RGBA') if os.path.exists(hpl) else None
                im_l = hand_l if hand_l is not None and hand_l.size == hand.size else mirror_rgba(im_r, meta, body)
        out.append(dict(r=im_r, l=im_l, pose=pose, ms=ms, buf=buf, meta=meta, scarf=scarf[i]))
    return out


def build(character, out_root, res=1, cap=None, with_fx=True):
    """Build one character at `res` into <out_root>/<character>/.  Fails loudly when the sheet exceeds `cap` colours."""
    ch = roster.get(character)
    rig.set_res(res)
    S = rig.RES
    cw, hipx, ground = rig.cell_px(), rig.hip_x_px(), rig.ground_px()
    cap = CAPS.get(res, 64) if cap is None else cap
    body = ch.body
    moves = build_moves(ch)
    names = list(moves.keys())
    idle_pts = idle_scarf(ch) if body.has_tail else None
    sheet_r = Image.new('RGBA', (COLS * cw, len(names) * cw), (0, 0, 0, 0))
    sheet_l = Image.new('RGBA', (COLS * cw, len(names) * cw), (0, 0, 0, 0))
    unarmed_r = Image.new('RGBA', (COLS * cw, len(names) * cw), (0, 0, 0, 0))
    unarmed_l = Image.new('RGBA', (COLS * cw, len(names) * cw), (0, 0, 0, 0))
    unarmed_frames = []
    anim, all_frames, hands = {}, [], {}
    for r, name in enumerate(names):
        mv = moves[name]
        assert len(mv['frames']) <= COLS, f'{ch.name}/{name}: more than {COLS} frames'
        frames, reach, proj_from = [], None, None
        grip, grip2 = [], []
        rig.UNARMED = True                               # V8 forge: the same frames without the held weapon(s)
        try:
            for i, f in enumerate(render_move(ch, name, mv, None if name == 'idle' else idle_pts)):
                unarmed_r.paste(f['r'], (i * cw, r * cw))
                unarmed_l.paste(f['l'], (i * cw, r * cw))
                unarmed_frames += [f['r'], f['l']]
        finally:
            rig.UNARMED = False
        for i, f in enumerate(render_move(ch, name, mv, None if name == 'idle' else idle_pts)):
            g1, g2 = grips(body, f['pose'])
            grip.append(g1)
            grip2.append(g2)
            sheet_r.paste(f['r'], (i * cw, r * cw))
            sheet_l.paste(f['l'], (i * cw, r * cw))
            all_frames += [f['r'], f['l']]
            frames.append(dict(i=i, ms=f['ms'], dx=f['pose'].dx * S))
            m = f['meta']
            hands[(name, i)] = m                         # hand / hip positions in px for effect anchors
            if mv.get('hit_frame') == i:
                reach = hit_reach(f['buf'], f['pose'])
            if mv.get('proj_frame') == i:
                proj_from = (round(m['hf'][0] - hipx, 1), round(m['hf'][1] - m['hip'][1], 1))
        entry = dict(row=r, loop=mv['loop'], cat=mv['cat'], desc=mv['desc'], frames=frames)
        if mv.get('loop_range'):
            entry['loop_range'] = list(mv['loop_range'])
        for k in ('hit_frame', 'proj_frame', 'release_frame', 'grab_frame', 'power', 'hitstop_ms',
                  'type', 'family', 'input', 'armor', 'pull_frame', 'catch_frame', 'cancel_frame', 'lock_frame', 'hit', 'height', 'air'):    # V7 keys after the V3-V6 ones; V8 `air`
            if k in mv:
                entry[k] = mv[k]
        if 'stride' in mv:
            entry['stride'] = mv['stride'] * S
        if mv.get('shake'):                              # V5: the fighter's own landing shake (design px -> px)
            entry['shake'] = dict(frames=int(mv['shake']['frames']), amp=int(mv['shake']['amp']) * S)
        if mv.get('smear_frames'):
            entry['smear_frames'] = list(mv['smear_frames'])
        if reach is not None:
            entry['reach'] = reach
        if proj_from is not None:
            entry['proj_from'] = list(proj_from)
        if mv.get('fx'):                                 # V4: which effects play on which frames (see fx.py)
            entry['fx'] = [dict(e) for e in mv['fx']]
        elif name == ch.signature.get('super'):          # the super's burst art (fx.py `<super>_burst`); without this the
            at = mv.get('hit_frame', len(mv['frames']) // 2)    # engine looked for an effect named after the move and drew a stand-in
            entry['fx'] = [dict(name=f'{name}_burst', at=int(at))]
        if mv.get('support'):
            entry['support'] = mv['support']
        entry['grip'] = grip                             # V8 forge (after every older key)
        entry['grip2'] = grip2
        anim[name] = entry
    cols = palette_of(all_frames)
    if len(cols) + 1 > cap:
        raise SystemExit(f'{ch.name} @RES {S}: {len(cols)} colours + transparency exceeds the cap of {cap}')
    ucols = palette_of(unarmed_frames)
    if len(ucols) + 1 > cap:
        raise SystemExit(f'{ch.name} @RES {S}: unarmed sheets use {len(ucols)} colours + transparency, over the cap of {cap}')
    d_out = os.path.join(out_root, ch.name)
    os.makedirs(d_out, exist_ok=True)
    sheet_r.save(os.path.join(d_out, 'sheet.png'))
    sheet_l.save(os.path.join(d_out, 'sheet_l.png'))
    unarmed_r.save(os.path.join(d_out, 'sheet_unarmed.png'))
    unarmed_l.save(os.path.join(d_out, 'sheet_unarmed_l.png'))
    projectile(ch).save(os.path.join(d_out, 'proj.png'))
    meta = dict(who=ch.name, character=ch.name, display=ch.display, tag=ch.tag, accent=ch.accent,
                signature=dict(ch.signature),
                cell=[cw, cw], cols=COLS, ground_y=ground, anchor={'R': hipx, 'L': cw - 1 - hipx},
                sheets={'R': 'sheet.png', 'L': 'sheet_l.png'},
                sheets_unarmed={'R': 'sheet_unarmed.png', 'L': 'sheet_unarmed_l.png'},
                projectile=dict(file='proj.png', frames=PROJ_FRAMES, w=PROJ_W * S, h=PROJ_H * S, speed=130 * S,
                                kind=ch.projectile['kind'], move=ch.signature['special'], style=ch.projectile['style']),
                palette=['#%02X%02X%02X' % c for c in sorted(cols)], colors=len(cols), anims=anim, res=S,
                credits=CREDITS, schema_notes=SCHEMA_NOTES)
    combo = combo_for(ch)
    if combo:
        meta['combo'] = combo                            # V7: the character's 3-hit string (choreo.combo_of)
    if with_fx:
        meta['fx'] = dict(file='fx.json', sheet='fx.png')
        FXMOD.build_character(ch, d_out, res=S, cap=cap, hands=hands, anims=anim)
    with open(os.path.join(d_out, 'anim.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)
    print(f'{ch.name} @RES {S}: {len(names)} moves, {sum(len(m["frames"]) for m in moves.values())} frames, {len(cols)} colors (+transparent), cap {cap}')
    return meta


def build_all(res, out_root=None, only=None, with_fx=True):
    rig.set_res(res)
    out_root = out_root or os.path.join(os.path.dirname(HERE), OUT_DIRS.get(res, f'assets_x{res}'))
    for name in roster.NAMES:
        if only is None or name in only:
            build(name, out_root, res=res, with_fx=with_fx)
    if with_fx:                                           # the shared generic sheet the engine looks for first
        FXMOD.build_shared(os.path.join(out_root, 'fx'), res=res, cap=CAPS.get(res, 64))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='output root (default: assets for --res 1, assets_hd for --res 2)')
    ap.add_argument('--res', type=int, default=1, help='resolution factor: 1 = 64 px cells, 2 = 128 px cells')
    ap.add_argument('--all', action='store_true', help='build RES 1 into assets/ and RES 2 into assets_hd/')
    ap.add_argument('--no-fx', action='store_true', help='skip the effects sheets')
    ap.add_argument('--only', help='comma-separated character names (default: the whole roster)')
    a = ap.parse_args()
    only = set(a.only.split(',')) if a.only else None
    unknown = (only or set()) - set(roster.NAMES)
    if unknown:
        ap.error(f'unknown character(s): {", ".join(sorted(unknown))}; roster: {", ".join(roster.NAMES)}')
    for res in ((1, 2) if a.all else (a.res,)):
        build_all(res, a.out if not a.all else None, only, with_fx=not a.no_fx)
