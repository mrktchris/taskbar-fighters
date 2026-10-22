"""Fight-quality QA: frame-by-frame review sheets and a pop / teleport audit, straight from the rig (no build needed).

  python art/qa_fight.py strip <character> <move>[,<move>...] [--res 1|2] [--out DIR]
      One PNG per move: the right- and left-facing frames at 4x (RES 1) or 2x (RES 2, the same screen size), lifted by the
      row's `air` curve at each frame's middle (the engine's jump), with the previous frame's silhouette as a faint
      onion skin behind it (a pop shows as two shapes that do not overlap), ms / HIT / smear / lift labels, and a 1x
      strip of both facings on a taskbar.
  python art/qa_fight.py audit [--res 1|2] [--chars a,b] [--tip 12] [--hip 4]
      Every move of every character: frame-to-frame jumps of the weapon tip (design px) and of the hips that are not a
      smear, a contact after a smear or authored travel, plus rows that hop inside the cell instead of using `air`.
      Includes the step from a one-shot's last frame back into idle.
  python art/qa_fight.py before-after <before.png> <after.png> <out.png> [--label TEXT]
      Stacks two sheets with labels (hand-polish before / after).
"""
from __future__ import annotations
import argparse, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
import rig  # noqa: E402
import roster  # noqa: E402
import build_fighters as BF  # noqa: E402
import moves as MV  # noqa: E402

DEFAULT_OUT = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'Temp', 'minis-fight-qa')
BG = (32, 32, 32)
DESK = (46, 58, 82)
BAR = (20, 22, 28)
HEADROOM = 30                    # RES 1 px of window above the cell (minis_core.config.JUMP_HEADROOM)
RETURNS_TO_IDLE = ('strike', 'special', 'super', 'ultimate', 'defense', 'emote', 'pair', 'throw')


def font(sz):
    for f in ('segoeuib.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def _mid_lift(mv, i):
    ms = [m for _, m in mv['frames']]
    t = sum(ms[:i]) + ms[i] / 2.0
    return MV.air_at(mv.get('air'), t)


def render(ch, name, res):
    rig.set_res(res)
    try:
        mv = MV.build_moves(ch)[name]
        idle_pts = BF.idle_scarf(ch) if ch.body.has_tail else None
        fr = BF.render_move(ch, name, mv, None if name == 'idle' else idle_pts)
    finally:
        rig.set_res(1)
    return mv, fr


def strip(name, move, res=1, scale=None):
    ch = roster.get(name)
    mv, fr = render(ch, move, res)
    sc = scale or (4 if res == 1 else 2)
    cell = 64 * res * sc
    head = HEADROOM * res * sc
    lab = 40
    n = len(fr)
    W_ = lab + n * cell
    row_h = head + cell + 30
    one = 64 * res
    H1 = (HEADROOM + 64) * res
    im = Image.new('RGB', (W_, 2 * row_h + H1 + 40), BG)
    d = ImageDraw.Draw(im)
    f = font(12 if res == 1 else 13)
    smear = set(mv.get('smear_frames') or [])
    for r, side in enumerate(('r', 'l')):
        y0 = r * row_h
        d.text((6, y0 + head + cell // 2), side.upper(), fill=(230, 230, 230), font=font(18))
        for i, fdat in enumerate(fr):
            x = lab + i * cell
            lift = int(round(_mid_lift(mv, i) * res * sc))
            if i > 0:                                        # onion skin: the previous frame's silhouette
                prev = fr[i - 1][side].resize((cell, cell), Image.NEAREST).getchannel('A')
                lp = int(round(_mid_lift(mv, i - 1) * res * sc))
                ghost = Image.new('RGB', (cell, cell), (110, 40, 40))
                im.paste(ghost, (x, y0 + head - lp), prev.point(lambda v: 90 if v else 0))
            big = fdat[side].resize((cell, cell), Image.NEAREST)
            im.paste(big, (x, y0 + head - lift), big)
            d.line([(x, y0 + head + 57 * res * sc), (x + cell - 1, y0 + head + 57 * res * sc)], fill=(70, 70, 70))
            hit = i == mv.get('hit_frame')
            tag = f'{i}: {fdat["ms"]}ms' + (' HIT' if hit else '') + (' sm' if i in smear else '')
            if mv.get('air'):
                tag += f' h{_mid_lift(mv, i):.0f}'
            d.text((x + 3, y0 + head + cell + 2), tag, fill=(255, 200, 90) if hit else (170, 170, 170), font=f)
    # 1x: both facings on a taskbar, lifted
    y1 = 2 * row_h + 10
    d.rectangle([0, y1, W_, y1 + H1], fill=DESK)
    d.rectangle([0, y1 + H1 - 48 * res, W_, y1 + H1], fill=BAR)
    for i, fdat in enumerate(fr):
        lift = int(round(_mid_lift(mv, i) * res))
        x = lab + i * (2 * one + 8)
        if x + 2 * one > W_:
            break
        for k, side in enumerate(('r', 'l')):
            im.paste(fdat[side], (x + k * one, y1 + HEADROOM * res - lift), fdat[side])
    d.text((6, y1 + H1 + 4), f'{name} {move} RES {res}', fill=(200, 200, 200), font=f)
    return im


# ---------------------------------------------------------------- audit
def _tip(body, ps):
    sk = rig.skeleton(body, ps)
    w = sk['wf']
    if w is None:
        return None
    return rig.weapon_point(w, 1.0)


def _hip(body, ps):
    bf = rig.body_frame(body, ps)
    return bf['hip']


def audit(chars=None, res=1, tip_thr=12.0, hip_thr=4.0, flip_deg=100.0):
    rig.set_res(res)
    out = []
    try:
        for name in chars or roster.NAMES:
            ch = roster.get(name)
            body = ch.body
            mvs = MV.build_moves(ch)
            idle0 = mvs['idle']['frames'][0][0]
            for mname, mv in mvs.items():
                poses = [ps for ps, _ in mv['frames']]
                ms = [m for _, m in mv['frames']]
                smear = set(mv.get('smear_frames') or [])
                pairs = [(i - 1, i) for i in range(1, len(poses))]
                if mv['loop']:
                    lo, hi = mv.get('loop_range') or (0, len(poses) - 1)
                    pairs.append((hi, lo))
                seq = list(poses)
                if not mv['loop'] and mv.get('cat') in RETURNS_TO_IDLE and mname not in MV.HELD_LAST:
                    seq.append(idle0)
                    pairs.append((len(poses) - 1, len(poses)))
                for a, b in pairs:
                    pa, pb = seq[a], seq[b]
                    if b < len(poses) and (b in smear or (a in smear and b == mv.get('hit_frame'))):
                        continue
                    if b < len(poses) and (b in smear or a in smear):
                        continue
                    ta, tb = _tip(body, pa), _tip(body, pb)
                    if ta is not None and tb is not None:
                        dt = math.hypot(tb[0] - ta[0], tb[1] - ta[1])
                        aa, ab = MV._wangle(body, pa), MV._wangle(body, pb)
                        turn = abs(MV._angdiff(ab, aa)) if aa is not None and ab is not None else 0.0
                        if dt >= tip_thr and turn >= flip_deg:
                            out.append((dt, name, mname, a, b, 'flip', ms[a] if a < len(ms) else 0))
                        elif dt >= tip_thr:
                            out.append((dt, name, mname, a, b, 'tip', ms[a] if a < len(ms) else 0))
                    ha, hb = _hip(body, pa), _hip(body, pb)
                    dh = math.hypot(hb[0] - ha[0], hb[1] - ha[1])
                    if dh >= hip_thr and not (pa.lean < -60 or pb.lean < -60):
                        out.append((dh, name, mname, a, b, 'hip', ms[a] if a < len(ms) else 0))
                if 'air' not in mv and min(ps.dy for ps in poses) <= -4:
                    out.append((-min(ps.dy for ps in poses), name, mname, -1, -1, 'cell-hop', 0))
    finally:
        rig.set_res(1)
    return out


def before_after(a, b, out, label=''):
    ia, ib = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    w = max(ia.width, ib.width)
    im = Image.new('RGB', (w, ia.height + ib.height + 60), BG)
    d = ImageDraw.Draw(im)
    d.text((6, 4), f'BEFORE {label}', fill=(255, 160, 140), font=font(18))
    im.paste(ia, (0, 28))
    d.text((6, 32 + ia.height), f'AFTER {label}', fill=(160, 255, 170), font=font(18))
    im.paste(ib, (0, 56 + ia.height))
    im.save(out)
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd')
    ap.add_argument('args', nargs='*')
    ap.add_argument('--res', type=int, default=1)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--chars', default='')
    ap.add_argument('--tip', type=float, default=12.0)
    ap.add_argument('--hip', type=float, default=4.0)
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    if a.cmd == 'strip':
        os.makedirs(a.out, exist_ok=True)
        for mv in a.args[1].split(','):
            p = os.path.join(a.out, f'{a.args[0]}-{mv}-res{a.res}.png')
            strip(a.args[0], mv, a.res).save(p)
            print(p)
    elif a.cmd == 'audit':
        rows = audit(a.chars.split(',') if a.chars else None, a.res, a.tip, a.hip)
        for v, name, mname, i, j, kind, ms in sorted(rows, key=lambda r: -r[0]):
            print(f'{v:6.1f} {kind:8s} {name:10s} {mname:18s} f{i}->f{j} ({ms} ms)')
        print(f'{len(rows)} flagged')
    elif a.cmd == 'before-after':
        print(before_after(a.args[0], a.args[1], a.args[2], a.label))
    else:
        ap.error(a.cmd)
