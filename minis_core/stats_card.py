r"""The shareable stats card (growth): `python minis.py card [--out PATH] [--share]` renders a 1200 x 675 PNG of "my agents'
record" - each program's fighter sprite, W-L, win %, streak, favourite move, bouts, top rival - and the achievement badges.

Inputs are record.json, history.json and achievements.json only (achievements.stats).  What reaches the picture: program
display names (short labels such as "Claude", "Codex"), character sprites drawn from our own sheets, move names from our
own move list, numbers and dates.  Never a prompt, a window title, a path or a file name.  Nothing is uploaded: the PNG
is written to <data dir>/exports/ (or an existing folder / .png path you type with --out; minis_core/exports.py), and
--share opens that folder with the card selected.
"""
from __future__ import annotations
import datetime, os, time
from pathlib import Path
from PIL import Image, ImageDraw

from . import achievements as ACH
from .render import font

W, H = 1200, 675
BG_TOP, BG_BOT = (20, 18, 38), (8, 8, 16)
INK, DIM, FAINT = (240, 238, 248), (176, 174, 198), (104, 102, 130)
GOLD, SILVER, BRONZE = (255, 206, 84), (196, 206, 222), (214, 140, 82)
GREEN, RED = (120, 220, 140), (255, 110, 110)
TIER = {1: BRONZE, 2: SILVER, 3: GOLD}
MAX_CARDS = 4
CARD_W, CARD_H, CARD_Y = 270, 366, 112
BADGE_Y = 496


def _vgrad(w, h, top, bot):
    g = Image.new('RGB', (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
    return g.resize((w, h)).convert('RGBA')


def _text(d, xy, s, fill, size, bold=True, anchor=None):
    d.text(xy, s, fill=fill, font=font(size, bold), anchor=anchor)


def _fit(d, s, maxw, size, bold=True):
    f = font(size, bold)
    if d.textlength(s, font=f) <= maxw:
        return s
    while len(s) > 1 and d.textlength(s + '…', font=f) > maxw:
        s = s[:-1]
    return s + '…'


def move_name(mid) -> str:
    """'spin_kick' -> 'Spin Kick' (our own move ids only)."""
    return ' '.join(w.capitalize() for w in str(mid or '').replace('-', '_').split('_') if w) or '-'


def _sprite(lib, character, pose='idle', facing=1):
    """Our own HD sheet frame cropped to its pixels, or None."""
    try:
        a = lib[character]
        name = pose if pose in a.anim else 'idle'
        n = len(a.anim[name]['frames'])
        im = a.frame_image(name, n - 1 if name != 'idle' else 0, facing)
        bb = im.getbbox()
        return (im.crop(bb) if bb else im), a
    except Exception:
        return None, None


def _paste_scaled(canvas, im, cx, bottom, max_h, max_w):
    k = max(1, min(max_h // max(1, im.height), max_w // max(1, im.width)))
    big = im.resize((im.width * k, im.height * k), Image.NEAREST)
    shadow = Image.new('RGBA', (int(big.width * 1.1), 10), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([0, 0, shadow.width - 1, 9], fill=(0, 0, 0, 110))
    canvas.alpha_composite(shadow, (int(cx - shadow.width / 2), int(bottom - 6)))
    canvas.alpha_composite(big, (int(cx - big.width / 2), int(bottom - big.height)))


# ---------------------------------------------------------------- the badge medallions
def _icon(d, kind, cx, cy, r, col):
    """Tiny vector glyphs for the medallions (our own drawing)."""
    import math
    if kind == 'star':
        pts = [(cx + (r if i % 2 == 0 else r * 0.42) * math.cos(-math.pi / 2 + i * math.pi / 5),
                cy + (r if i % 2 == 0 else r * 0.42) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]
        d.polygon(pts, fill=col)
    elif kind == 'sword':
        d.polygon([(cx - 2, cy + r * 0.4), (cx - 2, cy - r), (cx, cy - r - 3), (cx + 2, cy - r), (cx + 2, cy + r * 0.4)], fill=col)
        d.rectangle([cx - r * 0.6, cy + r * 0.4, cx + r * 0.6, cy + r * 0.4 + 3], fill=col)
        d.rectangle([cx - 1.5, cy + r * 0.4 + 3, cx + 1.5, cy + r], fill=col)
    elif kind == 'swords':
        for s in (-1, 1):
            d.line([(cx - s * r, cy + r), (cx + s * r * 0.8, cy - r * 0.8)], fill=col, width=4)
        d.line([(cx - r * 0.7, cy + r * 0.35), (cx + r * 0.7, cy + r * 0.35)], fill=col, width=3)
    elif kind == 'fist':
        d.rounded_rectangle([cx - r * 0.8, cy - r * 0.5, cx + r * 0.8, cy + r * 0.7], 4, fill=col)
        for i in range(4):
            x = cx - r * 0.8 + i * r * 0.4
            d.line([(x, cy - r * 0.5), (x, cy - r * 0.1)], fill=(0, 0, 0, 120), width=1)
        d.rectangle([cx - r * 0.5, cy + r * 0.7, cx + r * 0.5, cy + r], fill=col)
    elif kind == 'clock':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)
        d.line([(cx, cy), (cx, cy - r * 0.65)], fill=col, width=3)
        d.line([(cx, cy), (cx + r * 0.5, cy)], fill=col, width=3)
    elif kind == 'shield':
        d.polygon([(cx - r * 0.85, cy - r * 0.8), (cx + r * 0.85, cy - r * 0.8), (cx + r * 0.75, cy + r * 0.2), (cx, cy + r),
                   (cx - r * 0.75, cy + r * 0.2)], fill=col)
    elif kind == 'flame':
        d.polygon([(cx, cy - r), (cx + r * 0.75, cy + r * 0.1), (cx + r * 0.45, cy + r), (cx - r * 0.45, cy + r),
                   (cx - r * 0.75, cy + r * 0.1), (cx - r * 0.2, cy - r * 0.2)], fill=col)
    elif kind == 'heart':
        d.ellipse([cx - r, cy - r * 0.7, cx, cy + r * 0.3], fill=col)
        d.ellipse([cx, cy - r * 0.7, cx + r, cy + r * 0.3], fill=col)
        d.polygon([(cx - r * 0.95, cy), (cx + r * 0.95, cy), (cx, cy + r)], fill=col)
    elif kind == 'crown':
        d.polygon([(cx - r, cy + r * 0.6), (cx - r, cy - r * 0.6), (cx - r * 0.45, cy), (cx, cy - r), (cx + r * 0.45, cy),
                   (cx + r, cy - r * 0.6), (cx + r, cy + r * 0.6)], fill=col)
    elif kind == 'bolt':
        d.polygon([(cx + r * 0.25, cy - r), (cx - r * 0.6, cy + r * 0.15), (cx - r * 0.05, cy + r * 0.15), (cx - r * 0.3, cy + r),
                   (cx + r * 0.6, cy - r * 0.15), (cx + r * 0.05, cy - r * 0.15)], fill=col)
    elif kind == 'hammer':
        d.rectangle([cx - r, cy - r * 0.75, cx + r * 0.4, cy - r * 0.1], fill=col)
        d.rectangle([cx - r * 0.35, cy - r * 0.1, cx - r * 0.05, cy + r], fill=col)
    elif kind == 'ring':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=4)
        d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=col)
    elif kind == 'eye':
        d.ellipse([cx - r, cy - r * 0.55, cx + r, cy + r * 0.55], outline=col, width=4)
        d.ellipse([cx - r * 0.32, cy - r * 0.32, cx + r * 0.32, cy + r * 0.32], fill=col)
    elif kind == 'check':
        d.line([(cx - r * 0.75, cy), (cx - r * 0.2, cy + r * 0.6), (cx + r * 0.8, cy - r * 0.6)], fill=col, width=7)
    elif kind == 'moon':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        d.ellipse([cx - r * 0.35, cy - r * 1.05, cx + r * 1.3, cy + r * 0.6], fill=(0, 0, 0, 0))
    else:
        d.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], fill=col)


def badge(aid, on=True, size=44):
    """One achievement medallion as an RGBA image (size x size)."""
    a = ACH.BY_ID[aid]
    tier, icon = a.tier, a.icon
    k = 4                                                              # drawn 4x, reduced: smooth rims on a flat card
    s = size * k
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rim = TIER[tier] if on else (70, 70, 86)
    face = tuple(int(c * 0.32) for c in rim) if on else (34, 34, 44)
    d.ellipse([0, 0, s - 1, s - 1], fill=rim + (255,))
    d.ellipse([s * 0.09, s * 0.09, s * 0.91, s * 0.91], fill=face + (255,))
    glyph = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    _icon(ImageDraw.Draw(glyph), icon, s / 2, s / 2, s * 0.27, (rim if on else (96, 96, 112)) + (255,))
    im.alpha_composite(glyph)                                          # (the moon's bite is cut out of the glyph layer only)
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------- the card
RANK_COL = {'Bronze': BRONZE, 'Silver': SILVER, 'Gold': GOLD, 'Master': (186, 140, 255), 'Legend': (255, 120, 92)}


def rows(rec, label=None, look=None):
    """-> per-program dicts, most bouts first: achievements.careers() plus name, character and the head-to-head line
    against its most frequent opponent ('rival': (name, wins, losses))."""
    from . import sources
    label = label or sources.short_label
    look = look or (lambda sid: sources.CHARACTER.get(sid, 'generic'))
    out = []
    for sid, c in ACH.careers(rec).items():
        r = dict(c, source=sid, name=label(sid), character=look(sid), rival=None)
        if c.get('rival'):
            h = ACH.head_to_head(rec, sid, c['rival'])
            r['rival'] = (label(c['rival']), h['wins'][sid], h['wins'][c['rival']])
        out.append(r)
    out.sort(key=lambda r: (-r['bouts'], -r['w'], r['name'].lower()))
    return out


def identity(data, rec, label=None):
    """The headline: 'Your main: CLAUDE · 34-29 vs Codex · 3 comebacks' (numbers and program names only), or None."""
    if not data:
        return None
    main = data[0]
    bits = [f"Your main: {main['name'].upper()}"]
    if main['rival']:
        bits.append(f"{main['rival'][1]}-{main['rival'][2]} vs {main['rival'][0]}")
    if main.get('comebacks'):
        bits.append(f"{main['comebacks']} comeback{'s' if main['comebacks'] != 1 else ''}")
    elif main.get('ko'):
        bits.append(f"{main['ko']} KO{'s' if main['ko'] != 1 else ''}")
    return '  ·  '.join(bits)


def _overlay_lines(im, step=4, alpha=7):
    lay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    for y in range(0, im.height, step):
        ld.line([(0, y), (im.width, y)], fill=(255, 255, 255, alpha))
    im.alpha_composite(lay)


def _pill(d, x, y, s, col, size=13):
    f = font(size, True)
    w = int(d.textlength(s, font=f)) + 16
    d.rounded_rectangle([x - w // 2, y, x + w // 2, y + size + 8], (size + 8) // 2, fill=tuple(int(c * 0.28) for c in col), outline=col, width=1)
    d.text((x, y + 3), s, fill=col, font=f, anchor='ma')


def render(rec, hist=None, ach_path=None, lib=None, label=None, look=None, now=None, icon_path=None) -> Image.Image:
    """The 1200 x 675 card as an RGB image (pure: nothing written)."""
    from . import sources
    label = label or sources.short_label
    now = time.time() if now is None else now
    if lib is None:
        from .atlas import Library
        lib = Library(hd=True)
    S = ACH.stats(rec)
    data = rows(rec, label, look)
    have = ACH.unlocked(ach_path, rec)
    im = _vgrad(W, H, BG_TOP, BG_BOT)
    _overlay_lines(im)
    d = ImageDraw.Draw(im)
    # ---- header
    try:
        from . import paths
        ic = Image.open(icon_path or paths.icon_path('minis-256.png')).convert('RGBA').resize((64, 64), Image.LANCZOS)
        im.alpha_composite(ic, (40, 24))
        tx = 120
    except Exception:
        tx = 40
    _text(d, (tx, 22), "MY AGENTS' RECORD", INK, 40)
    who = identity(data, rec, label)
    _text(d, (tx + 2, 72), who or 'No matches yet', GOLD if who else DIM, 20)
    when = datetime.datetime.fromtimestamp(now).strftime('%d %b %Y').lstrip('0')
    _text(d, (W - 40, 30), f"{S['matches']} match{'es' if S['matches'] != 1 else ''}", INK, 26, anchor='ra')
    _text(d, (W - 40, 66), f'Taskbar Fighters  ·  {when}', DIM, 16, False, anchor='ra')
    # ---- program cards
    shown = data[:MAX_CARDS]
    if not shown:
        _text(d, (W // 2, CARD_Y + 140), 'No matches yet', INK, 34, anchor='mm')
        _text(d, (W // 2, CARD_Y + 186), 'start one with  python minis.py demo match', DIM, 20, False, anchor='mm')
    n = len(shown)
    gap = 22
    total = n * CARD_W + (n - 1) * gap if n else 0
    x0 = (W - total) // 2
    for i, r in enumerate(shown):
        x = x0 + i * (CARD_W + gap)
        spr, atlas = _sprite(lib, r['character'], 'victory' if i == 0 else 'idle')
        acc = tuple(atlas.accent) if atlas is not None else (200, 200, 210)
        card = Image.new('RGBA', (CARD_W, CARD_H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 14, fill=(26, 25, 44, 236), outline=acc + (255,), width=2)
        glow = _vgrad(CARD_W - 4, 150, tuple(int(c * 0.45) for c in acc), (26, 25, 44))
        mask = Image.new('L', glow.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, glow.width - 1, glow.height + 20], 12, fill=255)
        card.paste(glow, (2, 2), mask)
        im.alpha_composite(card, (x, CARD_Y))
        cx = x + CARD_W // 2
        _pill(d, cx, CARD_Y + 12, r['rank'].upper(), RANK_COL.get(r['rank'], SILVER))
        if spr is not None:
            _paste_scaled(im, spr, cx, CARD_Y + 166, 124, CARD_W - 40)
        _text(d, (cx, CARD_Y + 176), _fit(d, r['name'], CARD_W - 24, 26), INK, 26, anchor='ma')
        _text(d, (cx, CARD_Y + 206), f"{r['w']}-{r['l']}", acc, 40, anchor='ma')
        bx0, bx1, by = x + 22, x + CARD_W - 22, CARD_Y + 258
        d.rounded_rectangle([bx0, by, bx1, by + 10], 5, fill=(52, 50, 76))
        fillw = int((bx1 - bx0) * r['pct'] / 100.0)
        if fillw > 0:
            d.rounded_rectangle([bx0, by, bx0 + max(10, fillw), by + 10], 5, fill=GREEN if r['pct'] >= 50 else RED)
        _text(d, (bx0, by + 14), f"{r['pct']}% wins", DIM, 15, False)
        _text(d, (bx1, by + 14), f"{r['bouts']} bouts", DIM, 15, False, anchor='ra')
        riv = f"{r['rival'][1]}-{r['rival'][2]} vs {r['rival'][0]}" if r['rival'] else '-'
        lines = [('STREAK', f"{r['streak']}  (best {r['best_streak']})"), ('FAV MOVE', move_name(r['favourite']) if r['favourite'] else '-'),
                 ('HEAD TO HEAD', riv)]
        for j, (k, v) in enumerate(lines):
            yy = CARD_Y + 296 + j * 21
            _text(d, (bx0, yy + 1), k, FAINT, 12)
            _text(d, (bx1, yy - 2), _fit(d, v, CARD_W - 140, 16, False), INK, 16, False, anchor='ra')
    if len(data) > MAX_CARDS:
        more = len(data) - MAX_CARDS
        _text(d, (W - 40, CARD_Y + CARD_H + 6), f'+{more} more program{"s" if more > 1 else ""}', FAINT, 14, False, anchor='ra')
    # ---- achievements (every one shown, earned or not: the criteria are open)
    n_have = sum(1 for a in ACH.IDS if a in have)
    _text(d, (40, BADGE_Y), 'ACHIEVEMENTS', INK, 18)
    _text(d, (194, BADGE_Y + 3), f'{n_have} / {len(ACH.IDS)}', GOLD, 15, False)
    per_row = -(-len(ACH.IDS) // 2)
    cell = (W - 80) // per_row
    order = sorted(ACH.IDS, key=lambda a: (a not in have, ACH.IDS.index(a)))
    for i, aid in enumerate(order):
        col, row = i % per_row, i // per_row
        bx = 40 + col * cell + (cell - 40) // 2
        by = BADGE_Y + 30 + row * 64
        on = aid in have
        im.alpha_composite(badge(aid, on, 40), (bx, by))
        _text(d, (bx + 20, by + 44), _fit(d, ACH.BY_ID[aid].name, cell - 2, 11, on), INK if on else FAINT, 11, on, anchor='ma')
    _text(d, (W - 40, H - 6), 'numbers only · made offline by Taskbar Fighters', FAINT, 12, False, anchor='rd')
    return im.convert('RGB')


def default_name(now=None) -> str:
    return 'taskbar-fighters-stats-' + datetime.datetime.fromtimestamp(time.time() if now is None else now).strftime('%Y%m%d-%H%M%S') + '.png'


def build(out=None, now=None, lib=None):
    """Render from the live record and write it where exports.resolve says: <data dir>/exports/ by default, or the
    existing folder / .png path the user typed.  -> the written Path (raises exports.ExportPathError for anything else)."""
    from . import exports, history, records
    from . import control, director, lineup
    target = exports.resolve(out, default_name(now))
    try:
        lu, data = control.lineup(), director.read_assign() or {}
        look = lambda sid: lineup.look_of(sid, lu, data)            # noqa: E731  (the look the owner picked, if any)
    except Exception:
        look = None
    img = render(records.read(), history.read(), lib=lib, look=look, now=now)
    img.save(target, optimize=True)
    return target


def reveal(path):
    from . import exports
    return exports.reveal(path)


def cmd(args, out=print):
    from . import exports, records
    try:
        target = build(getattr(args, 'out', None))
    except exports.ExportPathError as e:
        out(f'stats card: refused: {e}')
        return 2
    out(f'stats card: {target}')
    for ln in ACH.career_lines(records.read()):
        out(ln)
    if getattr(args, 'share', False):
        reveal(target)
    return 0


def share_async(spawn, argv_fn):
    """The menus' "Share my stats card…": render in a child process (`card --share`: <data dir>/exports/, then that
    folder opens with the card selected) so no window loop stalls."""
    if os.environ.get('MINIS_TESTING'):
        return False
    spawn(argv_fn('card', '--share'))
    return True
