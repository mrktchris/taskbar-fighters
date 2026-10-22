"""Desktop weapons (docs/ARENA.md "Forging"): during an arena match a fighter reaches toward a window or the desktop, a
glowing outline cuts a piece out of the REAL screen image, the piece lifts off (the arena paints a dark jagged hole where
it was), shatters into pixel blocks and re-assembles as a weapon shaped to the fighter's weapon family, textured with
the piece's own pixels.  The weapon is held for a few exchanges, cracks on every hit it lands and finally shatters into
pixel debris.  A fighter can also rip out a slab and throw it, and pieces that impacts knock off windows can be picked
up and forged.

Privacy - these are engineering rules, and tests/test_forge.py proves each one:
- The monitor is grabbed ONCE, at arena start, into RAM (minis.run_arena) and handed in as a ScreenImage.  This module
  only crops that in-memory image; it never grabs the screen itself, never opens a file, never logs a pixel, and
  state() reports numbers only.
- ScreenImage refuses to be pickled, and its repr names a size, never content.
- Forge.disable() (`minis.py forge off` mid-match) and Forge.purge() (the arena closing) drop the image and every image
  this module derived from it; the compositor repaints those rectangles without them.
- Without an image (macOS without the Screen Recording permission, a grab that failed, or a window that moved since the
  grab) a weapon is forged from the window's SHAPE instead: a stylized glass / steel texture drawn from the rectangle's
  outline, so the feature still plays and no pixel is needed.

Everything here is paint on the overlay: the outline, the hole, the flying piece and the weapon are drawables the arena
composites.  No window is touched; only the rectangle list and the RAM image are read.
"""
from __future__ import annotations
import math, random
from collections import OrderedDict, deque
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# ---------------------------------------------------------------- tuning
FAMILIES = ('blade', 'greatsword', 'axe', 'spear', 'club', 'shards', 'slab')
FAMILY_OF = {'claude': 'blade', 'lmstudio': 'blade', 'gemini': 'blade', 'generic': 'blade', 'knight': 'greatsword',
             'barbarian': 'axe', 'cursor': 'spear', 'ollama': 'spear', 'oni': 'club', 'monk': 'club', 'codex': 'shards',
             'nomad': 'shards', 'kunoichi': 'shards'}
WEAPON_WORDS = (('greatsword', 'greatsword'), ('claymore', 'greatsword'), ('axe', 'axe'), ('spear', 'spear'), ('lance', 'spear'),
                ('staff', 'spear'), ('club', 'club'), ('kanabo', 'club'), ('tonfa', 'club'), ('mace', 'club'), ('hammer', 'club'),
                ('kunai', 'shards'), ('fan', 'shards'), ('chakram', 'shards'), ('shuriken', 'shards'), ('sword', 'blade'),
                ('katana', 'blade'), ('blade', 'blade'), ('dagger', 'blade'))
# weapon length / width (stage px) and the size of the screen region it is cut from
DIMS = {'blade': (232, 30), 'greatsword': (252, 58), 'axe': (206, 92), 'spear': (330, 28), 'club': (176, 54), 'shards': (118, 36),
        'slab': (150, 112)}
SOURCE = {'blade': (264, 34), 'greatsword': (210, 230), 'axe': (190, 200), 'spear': (360, 16), 'club': (124, 124), 'shards': (176, 132),
          'slab': (156, 116)}
TARGETS = {'calm': (1, 1), 'normal': (2, 4), 'wild': (5, 7)}          # forges per match (min, max)
USES = {'calm': 2, 'normal': 3, 'wild': 4}                            # exchanges a forged weapon lasts
LOOSE_P = {'calm': 0.25, 'normal': 0.5, 'wild': 0.75}                 # a heavy crack knocks a piece off the window
SLAB_P = 0.3
CRACKS_TO_SHATTER = 3
MORPH_FRAMES = 8                                                      # 6-10 frames at 30 fps
CELL = 10                                                             # morph block size (stage px)
PAD = 7                                                               # room round a silhouette for its rim and glow
ANGLE_STEP = 6                                                        # rotation cache granularity (degrees)
PRESENT = (84.0, -156.0)                                              # where a lifted piece floats while it morphs
HOLE_RGBA = (12, 12, 16, 244)
HOLES_MAX = 10
LOOSE_MAX = 3
DEBRIS_MAX = 140
# forge timeline (seconds)
T_OUTLINE, T_CUT, T_LIFT, T_SETTLE = 0.32, 0.08, 0.30, 0.12
T_MORPH = MORPH_FRAMES / 30.0
T_WINDUP, SLAB_SPEED, SLAB_MAX_S = 0.2, 1500.0, 0.75
GRAVITY = 2100.0


def family_for(atlas):
    """The forge family of a fighter: anim.json `forge` / `weapon` when the art names one, else the roster table, else a
    blade (a new character still forges something sensible)."""
    meta = getattr(atlas, 'meta', None) or {}
    for k in ('forge', 'weapon_family'):
        if meta.get(k) in FAMILIES:
            return meta[k]
    w = str(meta.get('weapon') or '').lower()
    for word, fam in WEAPON_WORDS:
        if word in w:
            return fam
    return FAMILY_OF.get(getattr(atlas, 'character', None), 'blade')


def targets(intensity, rng):
    lo, hi = TARGETS.get(intensity, TARGETS['normal'])
    n = lo
    while n < hi and rng.random() < 0.5:
        n += 1
    return n


def _ease(k):
    k = max(0.0, min(1.0, k))
    return 0.5 - 0.5 * math.cos(math.pi * k)


def _ease_out(k):
    k = max(0.0, min(1.0, k))
    return 1.0 - (1.0 - k) ** 3


def _lerp(a, b, k):
    return a + (b - a) * k


# ---------------------------------------------------------------- the RAM-only screen image
class ScreenImage:
    """The monitor as it looked when the arena started, in RAM only.  Regions are cropped from it; nothing is ever written.
    `rects` are the window rectangles at grab time (stage px): a window that has moved since no longer matches its pixels,
    so its pieces are forged from its shape instead."""
    __slots__ = ('_img', 'size', 'rects')

    def __init__(self, img, rects=None):
        if img is not None and img.mode != 'RGBA':
            img = img.convert('RGBA')
        self._img = img
        self.size = img.size if img is not None else (0, 0)
        self.rects = {int(r[0]): tuple(int(v) for v in r[1:5]) for r in (rects or ())}

    @property
    def available(self):
        return self._img is not None

    def region(self, box):
        """-> an RGBA crop of the in-memory image (a new image, RAM only), or None."""
        if self._img is None:
            return None
        x0, y0, x1, y1 = [int(v) for v in box]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.size[0], x1), min(self.size[1], y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        return self._img.crop((x0, y0, x1, y1))

    def matches(self, win):
        """True when window `win` (a Stage window dict) is where it was at grab time, so its pixels are current."""
        if not self.rects:
            return True
        r = self.rects.get(int(win['id']))
        return r is not None and r == (win['l'], win['t'], win['r'], win['b'])

    def drop(self):
        self._img = None

    def __repr__(self):
        return f'<ScreenImage {self.size[0]}x{self.size[1]} {"in RAM" if self._img is not None else "dropped"}>'

    def __reduce__(self):
        raise TypeError('ScreenImage holds a screen grab: RAM only, it is never pickled or written')

    __reduce_ex__ = lambda self, proto: self.__reduce__()           # noqa: E731


# ---------------------------------------------------------------- silhouettes (pure)
def silhouette(family, L=None, W=None):
    """-> (mask 'L' image, grip (x, y), cy): the weapon shape pointing along +x, its grip near the left end.  The image is
    the weapon's length + 2 * PAD wide; every family keeps its own proportions."""
    dl, dw = DIMS[family]
    L, W = int(L or dl), int(W or dw)
    w, h = L + 2 * PAD, W + 2 * PAD
    cy = h / 2.0
    m = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(m)
    x0 = PAD
    grip = (x0 + 16.0, cy)
    if family == 'blade':
        bw = W * 0.6
        curve = W * 0.22                                            # a slight upward curve, like a sabre
        top, bot = [], []
        n = 12
        for i in range(n + 1):
            k = i / n
            x = x0 + 44 + (L - 44 - 30) * k
            off = -curve * k * k
            top.append((x, cy - bw / 2 + off))
            bot.append((x, cy + bw / 2 + off))
        tip = (x0 + L, cy - curve * 1.35)
        d.polygon([(x0, cy - 5), (x0 + 38, cy - 5), (x0 + 38, cy - W / 2), (x0 + 44, cy - W / 2)] + top + [tip] + bot[::-1] +
                  [(x0 + 44, cy + W / 2), (x0 + 38, cy + W / 2), (x0 + 38, cy + 5), (x0, cy + 5)], fill=255)
    elif family == 'greatsword':
        bw = W * 0.66
        d.ellipse([x0, cy - 9, x0 + 16, cy + 9], fill=255)          # pommel
        d.rectangle([x0 + 8, cy - 6, x0 + 50, cy + 6], fill=255)    # two-hand grip
        d.rectangle([x0 + 48, cy - W / 2, x0 + 60, cy + W / 2], fill=255)    # crossguard
        d.polygon([(x0 + 58, cy - bw / 2), (x0 + L - 44, cy - bw / 2 + 3), (x0 + L, cy), (x0 + L - 44, cy + bw / 2 - 3), (x0 + 58, cy + bw / 2)],
                  fill=255)
        grip = (x0 + 26.0, cy)
    elif family == 'axe':
        d.rectangle([x0, cy - 6, x0 + L - 14, cy + 6], fill=255)    # haft
        hx = x0 + L - 86
        head = [(hx, cy - 4), (hx - 12, cy - W * 0.30), (hx + 6, cy - W * 0.50), (hx + 44, cy - W * 0.62), (hx + 74, cy - W * 0.50),
                (hx + 86, cy - W * 0.28), (hx + 70, cy - 4)]
        d.polygon(head, fill=255)
        d.polygon([(hx + 18, cy + 4), (hx + 10, cy + W * 0.22), (hx + 34, cy + W * 0.36), (hx + 58, cy + W * 0.18), (hx + 52, cy + 4)], fill=255)
        grip = (x0 + 22.0, cy)
    elif family == 'spear':
        d.rectangle([x0, cy - 4.5, x0 + L - 58, cy + 4.5], fill=255)
        d.rectangle([x0 + L - 66, cy - 7, x0 + L - 56, cy + 7], fill=255)    # collar
        d.polygon([(x0 + L - 58, cy), (x0 + L - 44, cy - W / 2), (x0 + L - 18, cy - W * 0.3), (x0 + L, cy), (x0 + L - 18, cy + W * 0.3),
                   (x0 + L - 44, cy + W / 2)], fill=255)
        grip = (x0 + L * 0.34, cy)                                  # held near the middle third
    elif family == 'club':
        d.polygon([(x0, cy - 7), (x0 + L - 26, cy - W / 2), (x0 + L - 26, cy + W / 2), (x0, cy + 7)], fill=255)
        d.ellipse([x0 + L - 52, cy - W / 2, x0 + L, cy + W / 2], fill=255)
        for i in range(4):                                          # studs along the head
            sx = x0 + L * 0.45 + i * (L * 0.12)
            r = 3 + i * 0.6
            ww = 7 + (W / 2 - 7) * ((sx - x0) / L)
            d.ellipse([sx - r, cy - ww - r, sx + r, cy - ww + r], fill=255)
            d.ellipse([sx - r, cy + ww - r, sx + r, cy + ww + r], fill=255)
    elif family == 'shards':
        rng = random.Random(7)
        for k, a in enumerate((-0.22, 0.0, 0.22)):                  # a fan of three glass shards between the fingers
            Ls = L * (0.82 + 0.09 * (k == 1))
            ca, sa = math.cos(a), math.sin(a)
            pts = [(0, -5), (Ls * 0.18, -W * 0.34), (Ls * 0.55, -W * 0.22 + rng.uniform(-2, 2)), (Ls, 0), (Ls * 0.6, W * 0.2 + rng.uniform(-2, 2)),
                   (Ls * 0.2, W * 0.3), (0, 5)]
            d.polygon([(x0 + 4 + px * ca - py * sa, cy + px * sa + py * ca) for px, py in pts], fill=255)
        grip = (x0 + 8.0, cy)
    else:                                                           # slab: a jagged rectangle ripped out of the desktop
        rng = random.Random(11)
        pts = _jagged_rect(x0, cy - W / 2, x0 + L, cy + W / 2, rng, 5, 7)
        d.polygon(pts, fill=255)
        grip = (x0 + L / 2.0, cy)
    return m, grip, cy


def _jagged_rect(x0, y0, x1, y1, rng, amp=6, n=8):
    """A rectangle outline with jagged, torn edges (clockwise from the top-left)."""
    pts = []
    for i in range(n):
        pts.append((_lerp(x0, x1, i / n), y0 + rng.uniform(-amp * 0.3, amp)))
    for i in range(n):
        pts.append((x1 - rng.uniform(-amp * 0.3, amp), _lerp(y0, y1, i / n)))
    for i in range(n):
        pts.append((_lerp(x1, x0, i / n), y1 - rng.uniform(-amp * 0.3, amp)))
    for i in range(n):
        pts.append((x0 + rng.uniform(-amp * 0.3, amp), _lerp(y1, y0, i / n)))
    return pts


def fit_texture(piece, size):
    """The piece's pixels laid onto a weapon's bounding box: turned a quarter if that keeps more of it, cropped to the
    weapon's aspect (never squashed), then resampled.  -> RGBA image of `size`."""
    tw, th = size
    pw, ph = piece.size
    if (pw >= ph) != (tw >= th) and min(pw, ph) > 0:
        piece = piece.transpose(Image.ROTATE_90)
        pw, ph = piece.size
    want = tw / float(th)
    if pw / float(ph) > want:
        cw = int(round(ph * want))
        x0 = (pw - cw) // 2
        piece = piece.crop((x0, 0, x0 + cw, ph))
    else:
        ch = max(1, int(round(pw / want)))
        y0 = (ph - ch) // 2
        piece = piece.crop((0, y0, pw, y0 + ch))
    down = piece.width >= tw
    return piece.resize((tw, th), Image.BOX if down else Image.NEAREST).convert('RGBA')


def shape_texture(size, seed, kind='glass'):
    """No pixels: a stylized texture from a window's shape alone - frosted glass with a sheen, or brushed steel.  Used
    without the Screen Recording permission (macOS) or when a window moved since the grab."""
    w, h = size
    rng = random.Random(seed)
    if kind == 'steel':
        im = Image.linear_gradient('L').resize((w, h)).point(lambda v: 120 + v // 3)
        im = Image.merge('RGBA', (im, im.point(lambda v: v + 6), im.point(lambda v: min(255, v + 18)), Image.new('L', (w, h), 255)))
    else:
        im = Image.new('RGBA', (w, h), (178, 210, 240, 235))
        g = Image.linear_gradient('L').resize((w, h)).point(lambda v: v // 5)
        im = Image.merge('RGBA', (ImageChops.subtract(im.getchannel('R'), g), ImageChops.subtract(im.getchannel('G'), g), im.getchannel('B'),
                                  im.getchannel('A')))
    d = ImageDraw.Draw(im)
    for _ in range(3):                                              # diagonal sheen streaks
        x = rng.uniform(-h, w)
        sw = rng.uniform(5, 14)
        d.polygon([(x, h), (x + sw, h), (x + sw + h * 0.8, 0), (x + h * 0.8, 0)], fill=(255, 255, 255, 120))
    d.rectangle([0, 0, w - 1, h - 1], outline=(70, 96, 140, 255))   # the window's own outline survives as the edge
    return im


def _dilate(mask, r):
    return mask.filter(ImageFilter.MaxFilter(2 * r + 1)) if r > 0 else mask


def build_weapon(family, texture, glow_rgb, seed=1):
    """-> dict(levels=[RGBA per crack level 0..3], mask, grip, cy, family): the weapon painted with `texture` clipped to its
    silhouette, a bevel for volume, a bright rim and the fighter's element glow (so it reads on any desktop), plus the
    progressive crack overlays."""
    mask, grip, cy = silhouette(family)
    w, h = mask.size
    bb = mask.getbbox() or (0, 0, w, h)
    tex = fit_texture(texture, (bb[2] - bb[0], bb[3] - bb[1]))
    body = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    body.paste(tex, (bb[0], bb[1]))
    body.putalpha(ImageChops.multiply(body.getchannel('A'), mask))
    if family in ('blade', 'greatsword', 'axe', 'spear', 'club'):   # the grip end darkened: it reads as a handle
        hand = Image.new('L', (w, h), 0)
        ImageDraw.Draw(hand).rectangle([0, 0, int(grip[0] + 22), h], fill=150)
        hand = ImageChops.multiply(hand, mask)
        body = Image.composite(Image.new('RGBA', (w, h), (28, 24, 30, 255)), body, hand)
    up = ImageChops.subtract(mask, ImageChops.offset(mask, 0, 2))     # top edge: a highlight
    dn = ImageChops.subtract(mask, ImageChops.offset(mask, 0, -2))    # bottom edge: a shadow
    body.alpha_composite(Image.merge('RGBA', (up, up, up, up.point(lambda v: v * 120 // 255))))
    body.alpha_composite(Image.merge('RGBA', [Image.new('L', (w, h), 0)] * 3 + [dn.point(lambda v: v * 120 // 255)]))
    rim = ImageChops.subtract(_dilate(mask, 1), mask)
    halo = ImageChops.subtract(_dilate(mask, 4), mask).filter(ImageFilter.GaussianBlur(1.6))
    base = Image.new('RGBA', (w, h), tuple(glow_rgb) + (0,))
    base.putalpha(halo.point(lambda v: min(255, v * 200 // 255)))
    base.alpha_composite(body)
    base.alpha_composite(Image.merge('RGBA', (rim, rim, rim, rim.point(lambda v: v * 235 // 255))))
    levels = [base]
    rng = random.Random(seed)
    lines = []
    ix = bb[0] + (bb[2] - bb[0]) * rng.uniform(0.55, 0.8)            # the impact point the cracks run from
    for lvl in range(1, CRACKS_TO_SHATTER + 1):
        for _ in range(2 + lvl):
            a = rng.uniform(0, 2 * math.pi)
            x, y = ix + rng.uniform(-10, 10), cy + rng.uniform(-4, 4)
            seg = [(x, y)]
            for _ in range(2 + lvl):
                a += rng.uniform(-0.6, 0.6)
                L = rng.uniform(8, 16 + 6 * lvl)
                x, y = x + math.cos(a) * L, y + math.sin(a) * L * 0.6
                seg.append((x, y))
            lines.append(seg)
        ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for seg in lines:
            d.line([(px + 1, py + 1) for px, py in seg], fill=(16, 14, 22, 230), width=2)
            d.line(seg, fill=(255, 255, 255, 235), width=1)
        ov.putalpha(ImageChops.multiply(ov.getchannel('A'), mask))
        im = base.copy()
        im.alpha_composite(ov)
        levels.append(im)
    return dict(levels=levels, mask=mask, grip=grip, cy=cy, family=family, size=(w, h))


def rotate_about(img, pivot, deg):
    """Rotate `img` counter-clockwise by `deg` (as seen on screen) with room to spare -> (image, where `pivot` lands)."""
    if deg % 360 == 0:
        return img, (float(pivot[0]), float(pivot[1]))
    out = img.rotate(deg, resample=Image.NEAREST, expand=True)
    cx, cy = img.width / 2.0, img.height / 2.0
    dx, dy = pivot[0] - cx, pivot[1] - cy
    r = math.radians(deg)
    nx = dx * math.cos(r) + dy * math.sin(r)
    ny = -dx * math.sin(r) + dy * math.cos(r)
    return out, (out.width / 2.0 + nx, out.height / 2.0 + ny)


def hole_image(poly, box, hot_rgb=None):
    """The dark, jagged hole a cut leaves (painted by the arena; the real window under it is never touched).  `poly` is in
    absolute stage px, `box` its bounding box.  hot_rgb: a glowing cut edge in the forger's colour (fades after a beat)."""
    x0, y0, x1, y1 = box
    w, h = int(x1 - x0) + 8, int(y1 - y0) + 8
    pts = [(px - x0 + 4, py - y0 + 4) for px, py in poly]
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=HOLE_RGBA)
    inner = [(4 + (px - 4) * 0.94 + w * 0.03, 4 + (py - 4) * 0.9 + h * 0.06) for px, py in pts]   # depth: a darker inner wall
    d.polygon(inner, fill=(4, 4, 6, 250))
    d.line(pts + [pts[0]], fill=(70, 72, 84, 255), width=2)          # the torn edge catches the light
    if hot_rgb is not None:
        d.line(pts + [pts[0]], fill=tuple(hot_rgb) + (230,), width=3)
        d.line(pts + [pts[0]], fill=(255, 250, 230, 255), width=1)
    return im


def outline_image(poly, box, progress, rgb, flash=False):
    """The glowing cut outline drawn on round the region (progress 0..1 of its perimeter); flash: the whole outline white."""
    x0, y0, x1, y1 = box
    w, h = int(x1 - x0) + 16, int(y1 - y0) + 16
    pts = [(px - x0 + 8, py - y0 + 8) for px, py in poly] + [(poly[0][0] - x0 + 8, poly[0][1] - y0 + 8)]
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if flash:
        d.polygon(pts[:-1], fill=(255, 255, 255, 70))
        d.line(pts, fill=tuple(rgb) + (200,), width=7)
        d.line(pts, fill=(255, 255, 255, 255), width=3)
        return im
    seglen = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    want = sum(seglen) * max(0.0, min(1.0, progress))
    run = [pts[0]]
    for (a, b), L in zip(zip(pts, pts[1:]), seglen):
        if want <= 0:
            break
        if L <= want:
            run.append(b)
            want -= L
        else:
            k = want / max(L, 1e-6)
            run.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
            want = 0
    if len(run) >= 2:
        d.line(run, fill=tuple(rgb) + (150,), width=7)
        d.line(run, fill=(255, 255, 255, 250), width=2)
        hx, hy = run[-1]
        d.ellipse([hx - 5, hy - 5, hx + 5, hy + 5], fill=(255, 255, 240, 255))      # the cutting spark at the head
    return im


def piece_image(piece, poly, box, rgb):
    """The cut piece: the region's pixels clipped to the torn outline, with a thin bright rim and a glow."""
    x0, y0, x1, y1 = box
    w, h = piece.size
    m = Image.new('L', (w, h), 0)
    ImageDraw.Draw(m).polygon([(px - x0, py - y0) for px, py in poly], fill=255)
    out = Image.new('RGBA', (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    mm = Image.new('L', out.size, 0)
    mm.paste(m, (PAD, PAD))
    halo = ImageChops.subtract(_dilate(mm, 4), mm).filter(ImageFilter.GaussianBlur(1.6))
    out.paste(Image.new('RGBA', out.size, tuple(rgb) + (255,)), (0, 0), halo)
    body = Image.new('RGBA', out.size, (0, 0, 0, 0))
    body.paste(piece, (PAD, PAD))
    body.putalpha(ImageChops.multiply(body.getchannel('A'), mm))
    out.alpha_composite(body)
    rim = ImageChops.subtract(_dilate(mm, 1), mm)
    out.alpha_composite(Image.merge('RGBA', (rim, rim, rim, rim.point(lambda v: v * 230 // 255))))
    return out


def debris_cells(img, x, y, rng, cell=14, limit=60):
    """Break an image (placed with its top-left at x, y) into small squares of its own pixels -> [(crop, cx, cy)]."""
    out = []
    a = img.getchannel('A')
    for j in range(0, img.height, cell):
        for i in range(0, img.width, cell):
            c = rng.randint(cell - 5, cell + 3)
            box = (i, j, min(img.width, i + c), min(img.height, j + c))
            if (a.crop(box).getbbox()) is None:
                continue
            out.append((img.crop(box), x + (box[0] + box[2]) / 2.0, y + (box[1] + box[3]) / 2.0))
    if len(out) > limit:
        rng.shuffle(out)
        out = out[:limit]
    return out


class _LRU(OrderedDict):
    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def get_or(self, key, make):
        if key in self:
            self.move_to_end(key)
            return self[key]
        v = self[key] = make()
        if len(self) > self.cap:
            self.popitem(last=False)
        return v


# ---------------------------------------------------------------- held weapons, jobs, loose pieces
class Weapon:
    """A forged weapon in a fighter's hand.  It has no swing of its own: every drawn frame it sits at the frame's `grip`
    (anim.json, V8 art), rotated to the grip angle with the pivot at the grip point, so it moves exactly with the arm.  A
    dual-wielder (`dual`) holds a second copy at `grip2`; a two-handed grip2 is the same weapon's second hand and is not
    drawn twice.  `hist` keeps the last placements for the smear that follows the real tip path."""

    def __init__(self, slot, family, art, uses, pixels, dual=False):
        self.slot, self.family, self.art = slot, family, art
        self.uses, self.cracks = uses, 0
        self.pixels = pixels                                        # textured from the screen grab (False: from a shape)
        self.dual = bool(dual)
        self.t_armed = None
        self.hidden = False
        self.hist = {'grip': deque(maxlen=6), 'grip2': deque(maxlen=6)}   # (t, gx, gy, screen angle, frame key)
        self._rot = _LRU(60)
        self.length = art['size'][0] - PAD - art['grip'][0]        # grip to tip

    def image(self, deg, facing):
        """The weapon rotated `deg` counter-clockwise (right-facing space), mirrored for facing -1 -> (image, pivot)."""
        step = int(round(deg / ANGLE_STEP)) * ANGLE_STEP
        lvl = min(self.cracks, CRACKS_TO_SHATTER)

        def make():
            im, piv = rotate_about(self.art['levels'][lvl], self.art['grip'], step)
            if facing < 0:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
                piv = (im.width - piv[0], piv[1])
            return im, piv
        return self._rot.get_or((lvl, step, facing >= 0), make)

    def ghost(self, deg, facing, q):
        im, piv = self.image(deg, facing)

        def make():
            g = im.copy()
            g.putalpha(im.getchannel('A').point(lambda v: v * q // 4))
            return g
        return self._rot.get_or(('ghost', id(im), q), make), piv


def SP_frame_hit(atlas, anim):
    from . import arena_setpieces as SP
    return SP.frame_of(atlas, anim, 'hit')


def screen_to_deg(ang, facing):
    """A grip angle (screen degrees, 0 = right, -90 = up, already mirrored for facing -1) -> Weapon.image's `deg`."""
    a_r = ang if facing >= 0 else 180.0 - ang                     # back to the right-facing sheet's angle
    return -(((a_r + 180.0) % 360.0) - 180.0)


def is_dual(atlas):
    """Two weapons (a second grip at a different angle on some frame), or one weapon held in two hands."""
    for name in ('idle', 'walk', 'jab', 'cross'):
        for i in range(len((atlas.anim.get(name) or {}).get('frames') or [])):
            g, g2 = atlas.grip(name, i, 1), atlas.grip2(name, i, 1)
            if g and g2 and abs(((g[2] - g2[2]) + 180.0) % 360.0 - 180.0) > 15.0:
                return True
    return False


class Job:
    """One forge in progress: kind 'weapon' (cut + morph into a weapon), 'slab' (cut + throw), 'pickup' (a loose piece)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.done = False
        self.stage = 'outline'
        self.frames = {}
        self.hit_done = False


# ---------------------------------------------------------------- the controller
class Forge:
    """Owned by the Arena.  enabled=False: no forge ever starts (control.json `forge` off).  screen=None: shape mode."""

    def __init__(self, arena, screen=None, enabled=False, seed=1):
        self.ar = arena
        self.enabled = bool(enabled)
        self.screen = screen if (enabled and screen is not None and getattr(screen, 'available', False)) else None   # off: never held
        self.rng = random.Random(seed * 7919 + 13)                  # its own stream: the fight's choreography is unchanged
        self.target = targets(arena.opts['intensity'], self.rng) if enabled else 0
        self.uses = USES.get(arena.opts['intensity'], 3)
        self.done = 0
        self.round_done = 0
        self.round_start_done = 0
        self.jobs = []
        self.weapons = {}
        self.loose = []
        self.debris = []
        self.holes = []                                             # dict(img, x, y, wid, hot_until, cold, box)
        self.slabs = []
        self.cut_seq = 0
        self.purged = False
        self._cache = _LRU(160)

    # ---- privacy
    @property
    def pixels(self):
        """True while a screen grab is held in RAM (the heartbeat reports it, and `arena capture` refuses)."""
        return self.screen is not None and self.screen.available

    def disable(self, now):
        """`forge off` mid-match: no new forge, the grab and every image made from it are dropped at once."""
        self.enabled = False
        self.purge(now)

    def purge(self, now=None):
        """Drop the screen image and every pixel-derived image (weapons, pieces, morph frames, debris, caches).  The holes
        stay: they are paint, made of no pixel.  The rectangles of what vanished go to the arena's repaint list."""
        rects = []
        for w in self.weapons.values():
            rects.append(self._weapon_rect(w))
        for j in self.jobs:
            rects.append(j.box)
            if getattr(j, 'last_rect', None):
                rects.append(j.last_rect)
        for p in self.loose:
            rects.append(p.get('last_rect') or p['box'])
        for s in self.slabs:
            rects.append(s.get('last_rect') or (s['x'] - 200, s['y'] - 200, s['x'] + 200, s['y'] + 200))
        for d in self.debris:
            rects.append((d[1] - 30, d[2] - 30, d[1] + 30, d[2] + 30))
        for j in self.jobs:
            b = self.ar.f.get(j.slot)
            if b is not None and not getattr(j, 'setpiece', False):
                b.pose = None
        self.weapons, self.jobs, self.loose, self.slabs, self.debris = {}, [], [], [], []
        self._cache.clear()
        if self.screen is not None:
            self.screen.drop()
        self.screen = None
        self.purged = True
        self.ar.holes.extend(r for r in rects if r)

    def _weapon_rect(self, w):
        b = self.ar.f[w.slot]
        return (b.x - 360, b.y - 420, b.x + 360, b.y + 120)

    # ---- planning
    def new_round(self):
        self.round_done = 0
        self.round_start_done = self.done

    def owed(self):
        return max(0, self.target - self.done) if not self.ar.endless else 1

    def want(self, att, dfn, k, now):
        """Should this exchange be a forge, and who forges?  -> slot or None.  Spreads the match's 2-4 (calm 1, wild 5-7)
        forges over the rounds still to come, favours dramatic moments (low HP, match point, a comeback)."""
        ar = self.ar
        if not self.enabled or self.jobs or ar.sp is not None:
            return None
        if now - ar.round_t0 > 25.0 - 5.0:                         # rounds.ROUND_CAP_S - 5: no forge into the time call
            return None
        if any(ar.f[s].down or ar.f[s].hp <= 0 or ar.f[s].hang or ar.f[s].climb for s in 'ab'):
            return None
        who = att
        low = min('ab', key=lambda s: ar.f[s].hp)
        if ar.f[low].hp <= 35 and low not in self.weapons:         # desperation: the fighter in trouble rips out a weapon
            who = low
        if not ar.f[who].grounded or ar.f[who].hover:
            who = 'b' if who == 'a' else 'a'
            if not ar.f[who].grounded or ar.f[who].hover:
                return None                                         # forging is done standing on something
        o = 'b' if who == 'a' else 'a'
        if who in self.weapons and o not in self.weapons and ar.f[o].grounded and not ar.f[o].hover:
            who = o                                                 # the unarmed one answers with a weapon of its own
        if ar.endless:
            return who if self.rng.random() < 0.12 else None
        owed = self.target - self.done
        if owed <= 0:
            return None
        left = max(1, ar.to_win - max(ar.wins.values()))           # rounds that must still be played (at least)
        due = math.ceil(max(0, self.target - self.round_start_done) / float(left)) - self.round_done
        el = now - ar.round_t0
        if due > 0:
            p = 0.28 + 0.14 * k + (0.25 if ar.f[low].hp <= 35 else 0.0) + (0.2 if max(ar.wins.values()) >= ar.to_win - 1 else 0.0)
            if el > (7.0 if due == 1 else 3.0) or k >= (4 if due == 1 else 2):
                p = 1.0
        else:
            p = 0.1 if k >= 2 else 0.0
        if k < 1 and ar.round == 1 and due <= 1:
            return None                                             # let the first round open with a straight exchange
        return who if self.rng.random() < p else None

    def kind_for(self, slot):
        b = self.ar.f[slot]
        near = [p for p in self.loose if p['state'] == 'rest' and abs(p['x'] - b.x) < 760]
        if near:
            return 'pickup'
        if slot in self.weapons or self.rng.random() < SLAB_P:
            return 'slab'
        return 'weapon'

    # ---- regions
    def _occluded(self, win, box):
        for w in self.ar.stage.windows:
            if w is win:
                return False
            if w['l'] < box[2] and box[0] < w['r'] and w['t'] < box[3] and box[1] < w['b']:
                return True
        return False

    def _clear_of_holes(self, box):
        for h in self.holes:
            hb = h['box']
            if hb[0] < box[2] and box[0] < hb[2] and hb[1] < box[3] and box[1] < hb[3]:
                return False
        return True

    def _desktop_free(self, box):
        return not any(w['l'] < box[2] and box[0] < w['r'] and w['t'] < box[3] and box[1] < w['b'] for w in self.ar.stage.windows)

    def regions(self, family, b):
        """Candidate cut regions for a family near fighter `b`: [(score, box, win or None, kind)], best first."""
        st = self.ar.stage
        sw, sh = SOURCE[family]
        top = 64 + 6                                                # below the HUD band
        out = []

        def add(box, win, kind):
            x0, y0, x1, y1 = [int(round(v)) for v in box]
            if x0 < 4 or y0 < top or x1 > st.w - 4 or y1 > st.h - 2 or x1 - x0 < 24 or y1 - y0 < 8:
                return
            box = (x0, y0, x1, y1)
            if not self._clear_of_holes(box):
                return
            if win is not None and self._occluded(win, box):
                return
            if win is None and kind == 'desktop' and not self._desktop_free(box):
                return
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            score = math.hypot(cx - b.x, (cy - (b.y - 120)) * 1.3) + (0 if win is not None else 160)
            if kind == 'taskbar':                                   # the taskbar is a spear's home; others prefer a window
                score += -120 if family == 'spear' else 520
            out.append((score, box, win, kind))
        for win in st.windows:
            ww, wh = win['r'] - win['l'], win['b'] - win['t']
            if family in ('blade',):
                L = min(sw, ww - 24)
                th = min(sh, max(18, wh // 5))
                x0 = min(max(b.x - L / 2.0, win['l'] + 12), win['r'] - 12 - L)
                add((x0, win['t'] + 2, x0 + L, win['t'] + 2 + th), win, 'title')
            elif family == 'spear':
                L = min(sw, ww - 24)
                x0 = min(max(b.x - L / 2.0, win['l'] + 12), win['r'] - 12 - L)
                add((x0, win['b'] - sh - 4, x0 + L, win['b'] - 4), win, 'edge')
            else:
                cw, ch = min(sw, ww - 20), min(sh, wh - 44)
                if cw < 60 or ch < 50:
                    continue
                x0 = min(max(b.x + b.facing * 70 - cw / 2.0, win['l'] + 10), win['r'] - 10 - cw)
                y0 = min(max(b.y - 150 - ch / 2.0, win['t'] + 38), win['b'] - 6 - ch)
                add((x0, y0, x0 + cw, y0 + ch), win, 'chunk')
        fy = st.floor_y
        if st.h - fy >= 18:                                         # the taskbar band under the floor line
            th = min(16 if family == 'spear' else sh, st.h - fy - 4)
            L = sw if family in ('spear', 'blade') else min(sw, 220)
            for x0 in (b.x - L / 2.0, b.x + b.facing * 140 - L / 2.0):
                x0 = min(max(x0, 8), st.w - 8 - L)
                add((x0, fy + (st.h - fy - th) / 2.0, x0 + L, fy + (st.h - fy - th) / 2.0 + th), None, 'taskbar')
        for dx in (0, 260, -260, 520, -520):                        # bare desktop near the fighter
            cw, ch = sw, sh
            x0 = min(max(b.x + dx - cw / 2.0, 8), st.w - 8 - cw)
            y0 = min(max(b.y - 170 - ch / 2.0, top + 4), fy - ch - 8)
            add((x0, y0, x0 + cw, y0 + ch), None, 'desktop')
        out.sort(key=lambda r: r[0])
        return out

    def _cut_poly(self, box):
        x0, y0, x1, y1 = box
        amp = 3 if min(x1 - x0, y1 - y0) < 30 else 6
        n = max(4, int((x1 - x0) / 36))
        rng = random.Random(self.cut_seq * 31 + 7)
        pts = []
        for i in range(n):
            pts.append((_lerp(x0, x1, i / n), y0 + rng.uniform(0, amp)))
        m = max(2, int((y1 - y0) / 36))
        for i in range(m):
            pts.append((x1 - rng.uniform(0, amp), _lerp(y0, y1, i / m)))
        for i in range(n):
            pts.append((_lerp(x1, x0, i / n), y1 - rng.uniform(0, amp)))
        for i in range(m):
            pts.append((x0 + rng.uniform(0, amp), _lerp(y1, y0, i / m)))
        return pts

    def _texture_from(self, box, win, kind, seed):
        """-> (RGBA piece of the box, pixels?): the screen grab's pixels when they are current, else a shape texture."""
        pix = None
        if self.screen is not None and (win is None or self.screen.matches(win)):
            pix = self.screen.region(box)
        if pix is not None:
            return pix, True
        return shape_texture((int(box[2] - box[0]), int(box[3] - box[1])), seed, 'steel' if kind in ('title', 'taskbar', 'edge') else 'glass'), False

    def glow_of(self, slot):
        from . import arena_setpieces as SP
        b = self.ar.f[slot]
        el = SP.element_for(b.atlas)
        body = SP.COLORS[el][1]
        return tuple(body) if body is not None else tuple(b.atlas.accent)

    # ---- starting a forge
    def start(self, slot, kind, now, quick=False, setpiece=False):
        """Begin a forge for `slot` -> the Job, or None (no region, disabled).  quick: the short version a set piece plays
        inside its stance; setpiece: the set piece owns the fighter's pose."""
        if not self.enabled or any(j.slot == slot for j in self.jobs):
            return None
        ar = self.ar
        b = ar.f[slot]
        fam = family_for(b.atlas)
        glow = self.glow_of(slot)
        self.cut_seq += 1
        seed = self.rng.randrange(1 << 30)
        if kind == 'pickup':
            near = sorted((p for p in self.loose if p['state'] == 'rest'), key=lambda p: abs(p['x'] - b.x))
            if not near:
                kind = 'weapon'
            else:
                p = near[0]
                p['state'] = 'claimed'
                b.target, b.fly_until, b.hover = (p['x'], p['y']), now + 1.4, False
                b.fly_speed = 1300.0
                b.play('dash', now, loop=False, hold='idle')
                job = Job(kind='pickup', slot=slot, family=fam, glow=glow, t0=now, box=p['box'], poly=p['poly'], piece=p['img'], pixels=p['pixels'],
                          src=(p['x'], p['y'] - p['img'].height / 2.0), loose=p, quick=False, setpiece=setpiece, seed=seed, wid=None)
                job.stage = 'go'
                self._begin(job, b, now)
                return job
        region_fam = 'slab' if kind == 'slab' else fam
        cands = self.regions(region_fam, b)
        if not cands:
            return None
        pick = cands[0] if len(cands) == 1 or self.rng.random() < 0.7 else cands[1]
        _, box, win, rkind = pick
        poly = self._cut_poly(box)
        tex, pixels = self._texture_from(box, win, rkind, seed)
        piece = piece_image(tex, poly, box, glow)
        job = Job(kind=kind, slot=slot, family=fam if kind != 'slab' else 'slab', glow=glow, t0=now, box=box, poly=poly, piece=piece, pixels=pixels,
                  src=((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0), quick=quick, setpiece=setpiece, seed=seed,
                  wid=(win['id'] if win is not None else None), texture=tex, loose=None)
        self._begin(job, b, now)
        return job

    def _begin(self, job, b, now):
        ar = self.ar
        self.jobs.append(job)
        self.done += 1
        self.round_done += 1
        ar.note('forge', now, who=job.slot, move=job.kind)
        k = 0.62 if job.quick else 1.0
        job.t_outline, job.t_lift = T_OUTLINE * k, T_LIFT * (0.7 if job.quick else 1.0)
        if job.kind != 'pickup':
            job.tx = b.facing if job.setpiece else (1 if job.src[0] >= b.x else -1)
            if not job.setpiece:
                b.facing = job.tx
                b.target, b.vx = None, 0.0
                self._reach_pose(b)
        job.t_stage = now

    def _reach_pose(self, b):
        """An arm thrown out towards the region: a jab / palm contact frame, else the stance."""
        from . import arena_setpieces as SP
        for name in ('jab', 'palm', 'punch', 'cross'):
            a = b.atlas.anim.get(name)
            if a and 'hit_frame' in a:
                b.pose = (name, SP.frame_of(b.atlas, name, 'hit'))
                return
        b.pose = SP.resolve_slot(b.atlas, 'stance')

    # ---- ticking
    def tick(self, now, dt):
        ar = self.ar
        if ar.phase in ('exit', 'done'):
            if self.weapons or self.jobs or self.loose or self.slabs:
                for s in list(self.weapons):
                    self.shatter(s, now)
                for j in list(self.jobs):
                    self._finish(j, now, release=True)
            self._tick_debris(now, dt)
            return
        for j in list(self.jobs):
            self._tick_job(j, now)
        for s, w in list(self.weapons.items()):
            b = ar.f[s]
            w.hidden = bool(b.alpha is not None and b.alpha < 0.5)
        self._tick_loose(now, dt)
        self._tick_slabs(now, dt)
        self._tick_debris(now, dt)
        for h in list(self.holes):                                  # a window that moved or closed takes its hole with it
            if h['wid'] is not None:
                w = ar.stage.window_by_id(h['wid'])
                if w is None or (w['l'], w['t'], w['r'], w['b']) != h['wrect']:
                    self.holes.remove(h)
                    ar.holes.append(h['rect'])

    def _present_pt(self, b, job):
        f = job.tx if hasattr(job, 'tx') else b.facing
        return b.x + f * PRESENT[0], b.y + PRESENT[1]

    def _tick_job(self, j, now):
        ar = self.ar
        b = ar.f[j.slot]
        el = now - j.t_stage
        if b.hp <= 0 and not j.setpiece:
            self._finish(j, now, release=True)
            return
        if j.stage == 'go':                                         # pickup: dash to the loose piece
            if (b.target is None and abs(b.x - j.loose['x']) < 60) or el > 1.6:
                b.target, b.fly_speed = None, None
                b.facing = 1 if j.loose['x'] >= b.x else -1
                j.tx = b.facing
                if 'crouch' in b.atlas.anim:
                    from . import arena_setpieces as SP
                    b.pose = ('crouch', SP.frame_of(b.atlas, 'crouch', 'last'))
                j.stage, j.t_stage = 'lift', now
                if j.loose in self.loose:
                    self.loose.remove(j.loose)
                ar.note('forge_pickup', now, who=j.slot)
            return
        if j.stage == 'outline':
            if el >= j.t_outline:
                j.stage, j.t_stage = 'cut', now
            return
        if j.stage == 'cut':
            if el >= T_CUT:
                self._add_hole(j, now)
                j.stage, j.t_stage = 'lift', now
                ar.fxp.add_shake(now, 3, 3 * ar.I['shake_k'])
                ar.note('forge_cut', now, who=j.slot)
            return
        if j.stage == 'lift':
            if el >= j.t_lift:
                if j.kind == 'slab':
                    j.stage, j.t_stage = 'windup', now
                    if not j.setpiece:
                        b.pose = None
                        mv = next((m for m in ('throw', 'cross', 'jab') if m in b.atlas.anim), 'idle')
                        b.play(mv, now, loop=False, hold='idle')
                else:
                    j.stage, j.t_stage = 'morph', now
                    if not j.setpiece:
                        from . import arena_setpieces as SP
                        r = SP.resolve_slot(b.atlas, 'charge')
                        if r is not None and r[0] == '@play':
                            b.pose = None
                            b.play(r[1], now)
                        else:
                            b.pose = r
                    self._morph_debris(j, now)
                    ar.note('forge_morph', now, who=j.slot)
            return
        if j.stage == 'windup':
            if el >= T_WINDUP:
                self._throw(j, now)
                self._finish(j, now, release=True)
            return
        if j.stage == 'morph':
            if el >= T_MORPH:
                self._arm(j, now)
                j.stage, j.t_stage = 'settle', now
            return
        if j.stage == 'settle' and el >= T_SETTLE:
            self._finish(j, now, release=True)

    def _finish(self, j, now, release):
        if j in self.jobs:
            self.jobs.remove(j)
        j.done = True
        b = self.ar.f.get(j.slot)
        if release and b is not None and not j.setpiece:
            b.pose = None
            if not b.down and b.anim not in ('idle',):
                b.play('idle', now)
        if getattr(j, 'last_rect', None):
            self.ar.holes.append(j.last_rect)

    def _add_hole(self, j, now):
        ar = self.ar
        x0, y0, x1, y1 = j.box
        hot = hole_image(j.poly, j.box, j.glow)
        cold = hole_image(j.poly, j.box, None)
        win = ar.stage.window_by_id(j.wid) if j.wid is not None else None
        h = dict(img=hot, cold=cold, x=int(x0) - 4, y=int(y0) - 4, wid=j.wid, hot_until=now + 0.9, box=j.box,
                 wrect=(win['l'], win['t'], win['r'], win['b']) if win else None, rect=(int(x0) - 6, int(y0) - 6, int(x1) + 6, int(y1) + 6))
        self.holes.append(h)
        while len(self.holes) > HOLES_MAX:
            old = self.holes.pop(0)
            ar.holes.append(old['rect'])

    def _arm(self, j, now):
        ar = self.ar
        old = self.weapons.pop(j.slot, None)
        if old is not None:
            self.shatter_weapon(old, now)
        art = getattr(j, 'art', None)                               # built by the morph's first frame
        if art is None:
            tex = j.piece.crop((PAD, PAD, j.piece.width - PAD, j.piece.height - PAD)) if j.kind == 'pickup' else j.texture
            art = build_weapon(j.family, tex, j.glow, seed=j.seed)
        b = ar.f[j.slot]
        w = Weapon(j.slot, j.family, art, self.uses, j.pixels, dual=is_dual(b.atlas))
        w.t_armed = now
        self.weapons[j.slot] = w
        pl = self.placement(b, w, now)
        if pl is not None:
            ar._burst_ring(now, pl[0], pl[1])
        ar.note('forge_armed', now, who=j.slot, move=j.family)

    def _morph_debris(self, j, now):
        """The part of the piece the weapon does not use falls away as pixel debris when the morph starts."""
        if j.kind == 'pickup':
            return
        b = self.ar.f[j.slot]
        px, py = self._present_pt(b, j)
        rng = random.Random(j.seed + 3)
        cells = debris_cells(j.piece, px - j.piece.width / 2.0, py - j.piece.height / 2.0, rng, cell=16, limit=18)
        for im, cx, cy in cells[::2]:
            a = rng.uniform(0, 2 * math.pi)
            sp = rng.uniform(120, 360)
            self._debris(im, cx, cy, math.cos(a) * sp, math.sin(a) * sp - 260, now + rng.uniform(0.6, 0.9), now)

    # ---- the held weapon
    def placement(self, b, w, now, which='grip'):
        """(gx, gy, screen angle) of a held weapon this frame, from the drawn frame's grip in the art, or None when that
        frame holds nothing in that hand.  The grip is relative to the anchor column centre and the ground_y row, so it
        lands where the sprite is drawn (jitter included)."""
        from .arena import SCALE
        anim = b.drawn_anim()
        idx = b.frame(now)[0]
        fn = b.atlas.grip if which == 'grip' else b.atlas.grip2
        try:
            g = fn(anim, idx, b.facing)
        except Exception:
            g = None
        if g is None:
            return None
        l, t, r, bt = b.sprite_rect()
        gx = l + b.jitter + (b.atlas.anchor(b.facing) + 0.5 + g[0]) * SCALE
        gy = t + (b.atlas.ground_y + g[1]) * SCALE
        lift = getattr(b, 'row_lift', None)
        if lift is not None:
            gy -= lift(now)                                # V9: an ultimate / emote leap lifts the sprite: the weapon goes with it
        return gx, gy, g[2]

    def armed(self, slot):
        """True while `slot` holds a forged weapon: the arena then draws it from its unarmed sheet."""
        return slot in self.weapons

    def held(self, slot, now, layer):
        """Drawables for `slot`'s forged weapon: layer 'back' = the second weapon of a dual-wielder (behind the body),
        'front' = the main weapon and its smear."""
        w = self.weapons.get(slot)
        if w is None or w.hidden:
            return []
        b = self.ar.f[slot]
        if layer == 'back':
            return self._weapon_drawables(b, w, now, 'grip2') if w.dual else []
        return self._weapon_drawables(b, w, now, 'grip')

    def on_hit_landed(self, slot, now, heavy=False, final=False):
        w = self.weapons.get(slot)
        if w is None:
            return
        w.cracks += CRACKS_TO_SHATTER if final else (2 if heavy else 1)
        self.ar.note('forge_crack', now, who=slot)
        if w.cracks >= CRACKS_TO_SHATTER:
            self.shatter(slot, now)

    def on_exchange_end(self, slots, now):
        for s in slots:
            w = self.weapons.get(s)
            if w is None or w.t_armed is None or now - w.t_armed < 0.5:
                continue
            w.uses -= 1
            if w.uses <= 0:
                self.shatter(s, now)

    def shatter(self, slot, now):
        w = self.weapons.pop(slot, None)
        if w is not None:
            self.shatter_weapon(w, now)

    def shatter_weapon(self, w, now):
        """The weapon breaks into its own pixels: small squares that burst from the crack, fall and fade."""
        ar = self.ar
        b = ar.f[w.slot]
        rng = random.Random(int(now * 1000) + 5)
        cx = cy = None
        for which in (('grip', 'grip2') if w.dual else ('grip',)):
            pl = self.placement(b, w, now, which)
            if pl is None:                                          # nothing in that hand this frame: break it at the chest
                pl = (b.x + b.facing * 40.0, b.y - 110.0, -45.0 if b.facing > 0 else -135.0)
            gx, gy, ang = pl
            im, piv = w.image(screen_to_deg(ang, b.facing), b.facing)
            x, y = gx - piv[0], gy - piv[1]
            cx, cy = x + im.width / 2.0, y + im.height / 2.0
            for cim, px, py in debris_cells(im, x, y, rng, cell=12, limit=40):
                a = math.atan2(py - cy, px - cx) + rng.uniform(-0.5, 0.5)
                sp = rng.uniform(160, 520)
                self._debris(cim, px, py, math.cos(a) * sp, math.sin(a) * sp - 320, now + rng.uniform(0.8, 1.25), now)
            ar.holes.append((int(x) - 4, int(y) - 4, int(x + im.width) + 4, int(y + im.height) + 4))
        ar.fxp.spawn_at('hit_light', now, cx, cy, b.facing)
        ar.note('forge_shatter', now, who=w.slot)

    # ---- slabs (thrown)
    def _throw(self, j, now):
        ar = self.ar
        b = ar.f[j.slot]
        other = 'b' if j.slot == 'a' else 'a'
        T = ar.f[other]
        sx, sy = self._present_pt(b, j)
        tx, ty = T.center()
        dist = max(1.0, math.hypot(tx - sx, ty - sy))
        flight = min(SLAB_MAX_S, dist / SLAB_SPEED)
        self.slabs.append(dict(img=j.piece, x=sx, y=sy, x0=sx, y0=sy, t0=now, flight=max(0.18, flight), tgt=other, slot=j.slot,
                               spin=1 if tx >= sx else -1, pixels=j.pixels, last_rect=None))
        ar.note('forge_throw', now, who=j.slot)

    def _tick_slabs(self, now, dt):
        ar = self.ar
        for s in list(self.slabs):
            T = ar.f[s['tgt']]
            tx, ty = T.center()
            k = min(1.0, (now - s['t0']) / s['flight'])
            arc = -90.0 * math.sin(math.pi * k)
            s['x'], s['y'] = _lerp(s['x0'], tx, k), _lerp(s['y0'], ty, k) + arc
            if k >= 1.0:
                self.slabs.remove(s)
                if s.get('last_rect'):
                    ar.holes.append(s['last_rect'])
                rng = random.Random(int(now * 1000) + 9)
                im = s['img']
                for cim, px, py in debris_cells(im, s['x'] - im.width / 2.0, s['y'] - im.height / 2.0, rng, cell=14, limit=50):
                    a = math.atan2(py - s['y'], px - s['x']) + rng.uniform(-0.6, 0.6)
                    sp = rng.uniform(200, 560)
                    self._debris(cim, px, py, math.cos(a) * sp, math.sin(a) * sp - 300, now + rng.uniform(0.7, 1.2), now)
                ar.note('forge_shatter', now, who=s['slot'])
                if T.hp > 0 and not T.down and ar.phase == 'fight':
                    ar._forge_hit(s['slot'], s['tgt'], now)

    # ---- loose pieces (knocked off a window by an impact)
    def on_window_crack(self, win, now, cx, cy, heavy):
        """A heavy crack can knock a chunk of real window off: it falls, lands and can be picked up and forged."""
        ar = self.ar
        if not self.enabled or not heavy or len(self.loose) >= LOOSE_MAX or ar.phase != 'fight':
            return
        if self.rng.random() >= LOOSE_P.get(ar.opts['intensity'], 0.5):
            return
        cw, ch = self.rng.randint(96, 140), self.rng.randint(70, 104)
        x0 = min(max(cx - cw / 2.0, win['l'] + 6), win['r'] - 6 - cw)
        y0 = min(max(cy - ch / 2.0, win['t'] + 6), win['b'] - 6 - ch)
        box = (int(x0), int(y0), int(x0 + cw), int(y0 + ch))
        if x0 < win['l'] or y0 < max(win['t'], 70) or self._occluded(win, box) or not self._clear_of_holes(box):
            return
        self.cut_seq += 1
        poly = self._cut_poly(box)
        tex, pixels = self._texture_from(box, win, 'chunk', self.cut_seq)
        glow = (236, 240, 255)
        piece = piece_image(tex, poly, box, glow)
        j = Job(poly=poly, box=box, glow=(255, 236, 200), wid=win['id'])
        self._add_hole(j, now)
        self.loose.append(dict(img=piece, poly=poly, box=box, x=(box[0] + box[2]) / 2.0, y=float(box[3]) + PAD, vy=-140.0, vx=self.rng.uniform(-90, 90),
                               state='fall', until=now + 14.0, pixels=pixels, last_rect=None))
        ar.note('forge_loose', now)

    def _tick_loose(self, now, dt):
        ar = self.ar
        for p in list(self.loose):
            if p['state'] == 'fall':
                y0 = p['y']
                p['vy'] = min(2000.0, p['vy'] + GRAVITY * dt)
                p['y'] += p['vy'] * dt
                p['x'] = min(max(p['x'] + p['vx'] * dt, 60.0), ar.stage.w - 60.0)
                for x0, x1, y in ar.stage.platforms():
                    if x0 <= p['x'] <= x1 and y0 <= y <= p['y']:
                        p['y'], p['state'] = float(y), 'rest'
                        ar.fxp.spawn_at('dust', now, p['x'], y - 6)
                        break
                if p['y'] > ar.stage.h + 200:
                    self.loose.remove(p)
            elif p['state'] == 'rest' and now >= p['until']:
                self.loose.remove(p)
                im = p['img']
                rng = random.Random(int(now * 1000))
                for cim, px, py in debris_cells(im, p['x'] - im.width / 2.0, p['y'] - im.height, rng, cell=16, limit=24):
                    self._debris(cim, px, py, rng.uniform(-120, 120), rng.uniform(-260, -60), now + 0.8, now)
                if p.get('last_rect'):
                    ar.holes.append(p['last_rect'])

    # ---- debris
    def _debris(self, img, x, y, vx, vy, t_end, now):
        if len(self.debris) >= DEBRIS_MAX:
            self.debris.pop(0)
        self.debris.append([img, float(x), float(y), float(vx), float(vy), float(t_end), float(now), 0])

    def _tick_debris(self, now, dt):
        fy = self.ar.stage.floor_y
        keep = []
        for d in self.debris:
            if now >= d[5]:
                continue
            d[4] += GRAVITY * dt
            d[1] += d[3] * dt
            d[2] += d[4] * dt
            if d[2] > fy - 4:
                if d[7] == 0 and d[4] > 160:
                    d[2], d[4], d[3], d[7] = fy - 4, -d[4] * 0.28, d[3] * 0.5, 1         # one bounce on the taskbar line
                else:
                    d[2], d[4], d[3] = fy - 4, 0.0, d[3] * 0.8
            keep.append(d)
        self.debris = keep

    # ---- drawing
    def drawables(self, now, layer):
        """'back': holes and resting loose pieces (behind the fighters); 'front': outlines, tethers, flying pieces, the morph,
        held weapons with their smear, thrown slabs and debris."""
        out = []
        ar = self.ar
        if layer == 'back':
            for h in self.holes:
                out.append((h['img'] if now < h['hot_until'] else h['cold'], h['x'], h['y']))
            for p in self.loose:
                im = p['img']
                r = (int(p['x'] - im.width / 2.0), int(p['y'] - im.height))
                out.append((im, r[0], r[1]))
                p['last_rect'] = (r[0], r[1], r[0] + im.width, r[1] + im.height)
            return out
        for j in self.jobs:
            out.extend(self._job_drawables(j, now))
        for s in self.slabs:
            k = int((now - s['t0']) * 24) % 8
            im = self._cache.get_or(('slab', id(s['img']), k, s['spin']), lambda: s['img'].rotate(-s['spin'] * k * 45, resample=Image.NEAREST, expand=True))
            x, y = int(s['x'] - im.width / 2.0), int(s['y'] - im.height / 2.0)
            out.append((im, x, y))
            s['last_rect'] = (x, y, x + im.width, y + im.height)
        for d in self.debris:
            q = max(1, min(4, int(4 * (d[5] - now) / max(1e-3, d[5] - d[6])) + 1))
            im = d[0] if q >= 4 else self._cache.get_or(('fade', id(d[0]), q), lambda d=d, q=q: _faded(d[0], q))
            out.append((im, int(d[1] - im.width / 2.0), int(d[2] - im.height / 2.0)))
        return out

    def _job_drawables(self, j, now):
        ar = self.ar
        b = ar.f[j.slot]
        el = now - j.t_stage
        out = []
        if j.stage == 'outline':
            k = el / max(1e-3, j.t_outline)
            step = int(min(1.0, k) * 12)
            im = self._cache.get_or(('outline', id(j), step), lambda: outline_image(j.poly, j.box, step / 12.0, j.glow))
            out.append((im, int(j.box[0]) - 8, int(j.box[1]) - 8))
            out.extend(self._tether(j, b, now))
        elif j.stage == 'cut':
            im = self._cache.get_or(('outline', id(j), 'flash'), lambda: outline_image(j.poly, j.box, 1.0, j.glow, flash=True))
            out.append((im, int(j.box[0]) - 8, int(j.box[1]) - 8))
        elif j.stage in ('lift', 'windup'):
            px, py = self._present_pt(b, j)
            if j.stage == 'lift':
                k = _ease(el / max(1e-3, j.t_lift))
                x, y = _lerp(j.src[0], px, k), _lerp(j.src[1], py, k) - 50.0 * math.sin(math.pi * k)
                tilt = int(round(-j.tx * 12 * k / 4.0)) * 4
            else:
                x, y = px - j.tx * 20 * min(1.0, el / T_WINDUP), py - 16 * min(1.0, el / T_WINDUP)
                tilt = -j.tx * 12
            im = self._cache.get_or(('tilt', id(j), tilt), lambda: j.piece.rotate(tilt, resample=Image.NEAREST, expand=True) if tilt else j.piece)
            r = (int(x - im.width / 2.0), int(y - im.height / 2.0))
            out.append((im, r[0], r[1]))
            j.last_rect = (r[0], r[1], r[0] + im.width, r[1] + im.height)
        elif j.stage == 'morph':
            idx = min(MORPH_FRAMES - 1, int(el * 30))
            im, ox, oy = self._morph_frame(j, idx)
            px, py = self._present_pt(b, j)
            r = (int(px - ox), int(py - oy))
            out.append((im, r[0], r[1]))
            j.last_rect = (r[0], r[1], r[0] + im.width, r[1] + im.height)
        return out

    def _tether(self, j, b, now):
        """A thin glowing line from the reaching hand to the cut (quantized, cached per job)."""
        hx, hy = b.x + j.tx * 70, b.y - 118
        tx, ty = self._outline_head(j, now)
        q = lambda v: int(v / 6) * 6
        key = ('tether', id(j), q(hx), q(hy), q(tx), q(ty))

        def make():
            x0, y0 = min(hx, tx) - 6, min(hy, ty) - 6
            w, h = int(abs(tx - hx)) + 12, int(abs(ty - hy)) + 12
            im = Image.new('RGBA', (max(1, w), max(1, h)), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            a, c = (hx - x0, hy - y0), (tx - x0, ty - y0)
            d.line([a, c], fill=tuple(j.glow) + (110,), width=6)
            d.line([a, c], fill=(255, 255, 255, 220), width=2)
            return im, int(x0), int(y0)
        im, x0, y0 = self._cache.get_or(key, make)
        return [(im, x0, y0)]

    def _outline_head(self, j, now):
        k = min(1.0, (now - j.t_stage) / max(1e-3, j.t_outline))
        pts = j.poly + [j.poly[0]]
        segs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        want = sum(segs) * k
        for (a, b), L in zip(zip(pts, pts[1:]), segs):
            if want <= L:
                t = want / max(L, 1e-6)
                return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            want -= L
        return pts[-1]

    def _morph_frame(self, j, idx):
        """Frame idx of the pixel-shatter / re-assemble: blocks of the piece scatter outwards, then gather into the weapon's
        silhouette, carrying the weapon's own texture in the second half.  -> (image, ox, oy) with (ox, oy) the morph centre."""
        key = ('morph', id(j), idx)
        if key in self._cache:
            return self._cache.get_or(key, None)
        st = getattr(j, 'morph', None)
        if st is None:
            if j.kind == 'pickup':
                tex = j.piece.crop((PAD, PAD, j.piece.width - PAD, j.piece.height - PAD))
            else:
                tex = j.texture
            art = build_weapon(j.family, tex, j.glow, seed=j.seed)
            j.art = art
            dst = art['levels'][0]
            src = j.piece
            rng = random.Random(j.seed + 1)
            blocks = []
            dw, dh = dst.size
            sw_, sh_ = src.size
            mA = art['mask']
            for y in range(0, dh, CELL):
                for x in range(0, dw, CELL):
                    box = (x, y, min(dw, x + CELL), min(dh, y + CELL))
                    if mA.crop(box).getbbox() is None:
                        continue
                    u, v = (x + CELL / 2.0) / dw, (y + CELL / 2.0) / dh
                    sx, sy = u * sw_, v * sh_
                    a = rng.uniform(0, 2 * math.pi)
                    blocks.append(dict(dbox=box, dc=(x + CELL / 2.0 - dw / 2.0, y + CELL / 2.0 - dh / 2.0), sc=(sx - sw_ / 2.0, sy - sh_ / 2.0),
                                       sbox=(int(max(0, sx - CELL)), int(max(0, sy - CELL)), int(min(sw_, sx + CELL)), int(min(sh_, sy + CELL))),
                                       dir=(math.cos(a), math.sin(a) - 0.4), spread=rng.uniform(14, 40), delay=rng.uniform(0, 0.18)))
            st = j.morph = dict(blocks=blocks, src=src, dst=dst)
        t = idx / float(MORPH_FRAMES - 1)
        pos = []
        for bl in st['blocks']:
            k = max(0.0, min(1.0, (t - bl['delay']) / (1.0 - bl['delay']))) if t < 1.0 else 1.0
            e = _ease(k)
            s = math.sin(math.pi * k) * bl['spread']
            cx = _lerp(bl['sc'][0], bl['dc'][0], e) + bl['dir'][0] * s
            cy = _lerp(bl['sc'][1], bl['dc'][1], e) + bl['dir'][1] * s
            img = st['src'].crop(bl['sbox']) if k < 0.5 else st['dst'].crop(bl['dbox'])
            if k < 0.5 and img.size != (CELL, CELL):
                img = img.resize((CELL, CELL), Image.NEAREST)
            pos.append((img, cx, cy))
        xs = [p[1] for p in pos] or [0.0]
        ys = [p[2] for p in pos] or [0.0]
        x0, y0 = min(xs) - CELL * 2, min(ys) - CELL * 2
        w, h = int(max(xs) - x0 + CELL * 2) + 1, int(max(ys) - y0 + CELL * 2) + 1
        im = Image.new('RGBA', (max(1, w), max(1, h)), (0, 0, 0, 0))
        for img, cx, cy in pos:
            im.alpha_composite(img, (int(cx - x0 - img.width / 2.0), int(cy - y0 - img.height / 2.0)))
        if idx == MORPH_FRAMES - 1:                                 # the last frame IS the weapon (no block seams)
            dst = st['dst']
            im = dst.copy()
            x0, y0 = -dst.width / 2.0, -dst.height / 2.0
        res = (im, int(-x0), int(-y0))
        return self._cache.get_or(key, lambda: res)

    def _weapon_drawables(self, b, w, now, which):
        pl = self.placement(b, w, now, which)
        if pl is None:
            return []
        gx, gy, ang = pl
        out = []
        h = w.hist[which]
        key = (b.drawn_anim(), b.frame(now)[0], b.facing)
        if not h or h[-1][4] != key:
            h.append((now, gx, gy, ang, key))
        recent = [p for p in h if now - p[0] <= 0.12]
        turn = abs(((recent[-1][3] - recent[0][3]) + 180.0) % 360.0 - 180.0) if len(recent) >= 2 else 0.0
        mv = b.atlas.anim.get(key[0]) or {}
        striking = 'hit_frame' in mv and abs(key[1] - SP_frame_hit(b.atlas, key[0])) <= 1     # around the contact only, never a recovery
        if turn >= 25.0 and striking:                               # a fast swing: ghosts at the art's own previous grips ...
            for q, p in zip((1, 2), recent[-3:-1]):
                g, piv = w.ghost(screen_to_deg(p[3], b.facing), b.facing, q)
                out.append((g, int(p[1] - piv[0]), int(p[2] - piv[1])))
            out.append(self._smear(w, recent, which))               # ... and a crescent along the tip's real path
        settle = w.t_armed is not None and now - w.t_armed < T_SETTLE and which == 'grip'
        if settle:                                                  # from the morph point into the hand
            k = _ease((now - w.t_armed) / T_SETTLE)
            px, py = b.x + b.facing * PRESENT[0], b.y + PRESENT[1]
            gx, gy = _lerp(px, gx, k), _lerp(py, gy, k)
            a0 = 0.0 if b.facing > 0 else 180.0
            ang = a0 + ((ang - a0 + 180.0) % 360.0 - 180.0) * k
        im, piv = w.image(screen_to_deg(ang, b.facing), b.facing)
        out.append((im, int(gx - piv[0]), int(gy - piv[1])))
        return out

    def _smear(self, w, pts, which):
        """The swing smear: a crescent swept by the outer part of the weapon along the placements the art actually drew,
        each step between two drawn frames subdivided (grip moved linearly, angle the short way round) so it curves like
        the real tip path instead of cutting a straight chord; older parts fainter, a white edge on the tip side."""
        L = w.length
        pts = pts[-3:]
        path = []
        for a, b in zip(pts, pts[1:]):
            da = ((b[3] - a[3]) + 180.0) % 360.0 - 180.0
            n = max(2, int(abs(da) / 8.0) + 1)
            for k in range(n):
                t = k / float(n)
                path.append((_lerp(a[1], b[1], t), _lerp(a[2], b[2], t), a[3] + da * t))
        path.append((pts[-1][1], pts[-1][2], pts[-1][3]))
        tips = [(x + math.cos(math.radians(a)) * L, y + math.sin(math.radians(a)) * L) for x, y, a in path]
        mids = [(x + math.cos(math.radians(a)) * L * 0.62, y + math.sin(math.radians(a)) * L * 0.62) for x, y, a in path]
        q = lambda v: int(v // 4) * 4
        key = ('smear', id(w), which, tuple((q(x), q(y)) for x, y in tips[::3]), q(tips[-1][0]), q(tips[-1][1]))
        if not hasattr(w, 'art_glow'):
            w.art_glow = self.glow_of(w.slot)

        def make():
            xs = [x for x, y in tips + mids]
            ys = [y for x, y in tips + mids]
            x0, y0 = int(min(xs)) - 6, int(min(ys)) - 6
            im = Image.new('RGBA', (int(max(xs)) - x0 + 7, int(max(ys)) - y0 + 7), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            T = [(x - x0, y - y0) for x, y in tips]
            M = [(x - x0, y - y0) for x, y in mids]
            m = len(T)
            for k in range(m - 1):                                  # faint at the tail, strong behind the weapon
                a = int(40 + 120 * ((k + 1) / float(m - 1)) ** 1.5)
                d.polygon([M[k], T[k], T[k + 1], M[k + 1]], fill=tuple(w.art_glow) + (a,))
            d.line(T[m // 3:], fill=(255, 255, 255, 220), width=3, joint='curve')
            return im, x0, y0
        im, x0, y0 = self._cache.get_or(key, make)
        return (im, x0, y0)

    def state(self):
        """Numbers only (the heartbeat): never a pixel, a region or a window id."""
        return dict(on=self.enabled, pixels=self.pixels, forges=self.done, armed=sorted(self.weapons))


def _faded(img, q):
    out = img.copy()
    out.putalpha(img.getchannel('A').point(lambda v: v * q // 4))
    return out
