"""Compose one window frame (logical pixels): sprite + HUD plate + projectile.  Pure Pillow, no Win32."""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont

from .atlas import LEGACY_TAG, LEGACY_ACCENT, DEFAULT_ACCENT
from .config import PLATE_W, PLATE_H

CELL = 64
ACCENT = LEGACY_ACCENT          # kept for older callers; the plate now takes name/accent from the atlas
TAG = LEGACY_TAG
AMBER, RED, RED_DIM, TRACK = (255, 196, 80), (255, 96, 96), (190, 60, 60), (58, 58, 66)
STATE_WORD = {'working': 'working', 'idle': 'idle', 'done': 'done', 'waiting': 'waiting?', 'sleeping': 'sleeping', 'limit': 'limit'}
PLATE_GAP = 18
SEGS = 10

_font_cache = {}
# Windows first (unchanged order); then macOS, where Arial lives under these names (Supplemental since macOS 10.15).
# Regular text on macOS is PT Sans (ships with macOS in Supplemental/): Arial 9 px runs ~15% wider than Segoe UI and pushed
# the plate's reset countdown off; PT Sans matches Segoe UI's width.  An absolute path: on Windows it never loads.
BOLD_FONTS = ('segoeuib.ttf', 'arialbd.ttf', 'Arial Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
              '/Library/Fonts/Arial Bold.ttf')
REGULAR_FONTS = ('segoeui.ttf', '/System/Library/Fonts/Supplemental/PTSans.ttc', 'arial.ttf', 'Arial.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/Library/Fonts/Arial.ttf')


PIXEL_MAX = 12                                    # up to this size the UI's own pixel font (minis_core.pixelfont) is the font


def os_font(size, bold=True):
    """An OS TrueType face (large text only: banners, the arena HUD, the VS card); Pillow's default bitmap when none loads."""
    k = (size, bold)
    if k not in _font_cache:
        f = None
        for n in (BOLD_FONTS if bold else REGULAR_FONTS):
            try:
                f = ImageFont.truetype(n, size)
                break
            except Exception:
                pass
        _font_cache[k] = f or ImageFont.load_default()
        _font_key[id(_font_cache[k])] = k
    return _font_cache[k]


_font_key = {}                                    # id(font) -> (size, bold): lets KDraw find the k-times-larger face


def font(size, bold=True):
    """The font for `size` px of UI text: the shipped pixel font up to PIXEL_MAX (identical on every OS; measured by
    ImageDraw.textlength through its getlength, drawn only by text()), an OS face above it."""
    if int(size) <= PIXEL_MAX:
        from . import pixelfont
        return pixelfont.for_size(size, bold)
    return os_font(size, bold)


def is_pixel(f):
    return hasattr(f, 'mask') and hasattr(f, 'glyph')


class KDraw:
    """An ImageDraw stand-in that takes the same logical-px calls the HUD code makes and draws them k times finer
    (macOS Retina: a 2x image shown at 1x points).  Boxes keep their exact pixel area; text is the k-times face,
    antialiased, which at 2x reads like the system's own text.  Never used at k=1, so Windows draws exactly as before."""

    def __init__(self, im, k):
        self.d, self.k, self.fontmode = ImageDraw.Draw(im), int(k), '1'

    def _box(self, b):
        k = self.k
        return [b[0] * k, b[1] * k, b[2] * k + k - 1, b[3] * k + k - 1]

    def _font(self, f):
        size, bold = _font_key.get(id(f), (9, False))
        return font(size * self.k, bold)

    def rectangle(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(self._box(box), fill=fill, outline=outline, width=width * self.k)

    def rounded_rectangle(self, box, radius=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self._box(box), radius * self.k, fill=fill, outline=outline, width=width * self.k)

    def polygon(self, xy, fill=None, outline=None):
        self.d.polygon([(x * self.k, y * self.k) for x, y in xy], fill=fill, outline=outline)

    def textlength(self, s, font=None):
        if is_pixel(font):
            return font.getlength(s)
        return self.d.textlength(s, font=self._font(font)) / self.k

    def text(self, xy, s, fill=None, font=None, scale=1):
        if is_pixel(font):                            # the pixel font at k x scale: crisp on Retina, the same shapes as 1x
            self.d.bitmap((xy[0] * self.k, xy[1] * self.k), font.mask(s, self.k * scale), fill=fill)
            return
        self.d.fontmode = 'L'
        self.d.text((xy[0] * self.k, xy[1] * self.k), s, fill=fill, font=self._font(font))


def canvas(w, h, k=1):
    """-> (image, draw) for a HUD element of w x h logical px.  k > 1: a k-times image tagged info['density'] = k (the
    macOS overlay shows it at w x h points) and a KDraw.  k = 1: a plain image and ImageDraw, exactly as before."""
    if k <= 1:
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        return im, ImageDraw.Draw(im)
    im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    im.info['density'] = int(k)
    return im, KDraw(im, k)


TEXT_BOOST = 1.7                                  # coverage gain of the small UI text (see text())
_BOOST_LUT = [min(255, int(v * TEXT_BOOST)) for v in range(256)]
_mask_cache = {}


def text_mask(s, size=9, bold=True):
    """-> (L mask, dx): the string's coverage mask, drawn antialiased and then sharpened, and its x offset from the pen."""
    key = (s, size, bold)
    m = _mask_cache.get(key)
    if m is None:
        f = os_font(size, bold)
        l, t, r, b = f.getbbox(s)
        dx = min(0, l)
        im = Image.new('L', (max(1, r - dx + 1), max(1, b + 1)), 0)
        dd = ImageDraw.Draw(im)
        dd.fontmode = 'L'
        dd.text((-dx, 0), s, fill=255, font=f)
        m = (im.point(_BOOST_LUT), dx)
        if len(_mask_cache) > 2048:
            _mask_cache.clear()
        _mask_cache[key] = m
    return m


def wrap(s, maxw, size=9, bold=False):
    """Split `s` into lines no wider than maxw px (on spaces; a single over-long word keeps its own line, never cut)."""
    import re
    f = font(size, bold)
    out, cur = [], ''
    for tok in re.findall(r'\S+|\s+', str(s)):                     # runs of spaces are kept inside a line
        if tok.isspace():
            cur = cur + tok if cur else cur
            continue
        nxt = cur + tok
        if not cur.strip() or f.getlength(nxt) <= maxw:
            cur = nxt
        else:
            out.append(cur.rstrip())
            cur = tok
    if cur.strip():
        out.append(cur.rstrip())
    return out or ['']


def text(d, xy, s, fill, size=9, bold=True, scale=1):
    """UI text.  Up to PIXEL_MAX px it is the shipped pixel font (minis_core.pixelfont), drawn as a mask at whole-pixel
    `scale` - identical on Windows, macOS and in a bundle, with no OS font involved.  (FreeType's monochrome hinting of the
    OS fonts at 8-11 px tore words apart: "m inis", "C laude".)  Above it an OS face, antialiased and sharpened (TEXT_BOOST).
    KDraw (macOS Retina) draws the pixel font at k x scale and the OS face k times finer."""
    f = font(size, bold)
    if isinstance(d, KDraw):
        d.text(xy, s, fill=fill, font=f, scale=scale)
        return
    if is_pixel(f):
        d.bitmap((int(xy[0]), int(xy[1])), f.mask(s, scale), fill=fill)
        return
    mask, dx = text_mask(s, size, bold)
    if scale > 1:
        mask = mask.resize((mask.width * scale, mask.height * scale), Image.NEAREST)
    d.bitmap((int(xy[0]) + dx * scale, int(xy[1])), mask, fill=fill)


def style_of(who_or_atlas):
    """-> (name, accent).  The plate's first line is the program's NAME (atlas `display`: Claude, Codex, Gemini ...);
    the sigil tag (`/reverse`) is only a fallback for an atlas without one.  Accepts an Atlas, or a legacy character."""
    if hasattr(who_or_atlas, 'tag'):
        return getattr(who_or_atlas, 'display', None) or who_or_atlas.tag, tuple(who_or_atlas.accent)
    return LEGACY_TAG.get(who_or_atlas, str(who_or_atlas)), LEGACY_ACCENT.get(who_or_atlas, DEFAULT_ACCENT)


def shown_pct(v):
    return None if v is None else int(round(v))


def blink_phase(snap, t):
    """The red blink runs whenever context is at 90%+ (or the state is limit), whatever the state word says.
    The phase belongs in every cache key and redraw signature, or a cached plate freezes mid-blink."""
    if snap is None:
        return 0
    c = shown_pct(snap.ctx_pct)
    if snap.state == 'limit' or (c is not None and c >= 90):
        return int(t * 2) % 2 + 1
    return 0


def bar_color(pct, accent, phase):
    if pct is None:
        return TRACK
    if pct >= 90:
        return RED if phase != 2 else RED_DIM
    if pct >= 70:
        return AMBER
    return accent


def filled_segments(ctx):
    """Segments from the same rounded integer the label shows (half-up), so a cached plate is never off by one."""
    c = shown_pct(ctx)
    return 0 if c is None else max(0, min(SEGS, (c * SEGS + 50) // 100))


_plate_cache = {}


def plate(style, snap, t, width=PLATE_W, name=None, k=1, dmg=None):
    """k: pixel density (1 everywhere but a macOS Retina screen, where the plate is drawn 2x and nearly opaque).
    dmg: V9, the fighter's damage % while a match plays (None otherwise): it takes the state word's place, small, in a
    colour that warms with the damage; a `waiting?` state still wins (it needs the user)."""
    tag, accent = style_of(style)
    tag = name or tag
    dmg = None if dmg is None else int(round(float(dmg)))
    key = (tag, accent, snap.state if snap else None, shown_pct(snap.ctx_pct) if snap else None,
           shown_pct(snap.plan_pct) if snap else None, snap.plan_label if snap else '', getattr(snap, 'resets_in', '') if snap else '',
           blink_phase(snap, t), width, dmg) + ((k,) if k > 1 else ())
    im = _plate_cache.get(key)
    if im is None:
        if len(_plate_cache) > 96:
            _plate_cache.clear()
        im = _plate_cache[key] = _plate(tag, accent, snap, blink_phase(snap, t), width, k, dmg)
    return im


def dmg_colour(dmg):
    """White at 0 %, through amber, to red at 60 % and over (the damage meter's warmth)."""
    k = max(0.0, min(1.0, dmg / 60.0))
    if k < 0.5:
        u = k / 0.5
        return tuple(int(a + (b - a) * u) for a, b in zip((235, 235, 240), AMBER))
    u = (k - 0.5) / 0.5
    return tuple(int(a + (b - a) * u) for a, b in zip(AMBER, RED))


def _fit(d, s, maxw, size, bold):
    """Shorten `s` with a trailing '.' until it fits maxw pixels."""
    f = font(size, bold)
    if d.textlength(s, font=f) <= maxw:
        return s
    while len(s) > 1 and d.textlength(s + '.', font=f) > maxw:
        s = s[:-1]
    return s + '.'


def _plate(tag, accent, snap, phase, width=PLATE_W, k=1, dmg=None):
    """Fighting-game HUD plate, two lines.  Shows state + numbers only, never titles or content."""
    h = PLATE_H
    im, d = canvas(width, h, k)
    state = snap.state if snap else 'sleeping'
    waiting = state == 'waiting'                  # needs your approval: amber border + amber state word, visible at a glance
    # k > 1 is macOS, where the plate floats over app windows (no dark taskbar behind it): nearly opaque, so nothing shows through
    d.rounded_rectangle([0, 0, width - 1, h - 1], 4, fill=(18, 18, 22, 200 if k == 1 else 242), outline=(AMBER + (255,)) if waiting else accent + (150,),
                        width=2 if waiting else 1)
    sw = STATE_WORD.get(state, state)
    if dmg is not None and not waiting:                    # V9: during a match the damage % takes the state word's place
        sw = f'{dmg}%'
        sww = int(d.textlength(sw, font=font(9, True)))
        text(d, (width - 5 - sww, 2), sw, dmg_colour(dmg), 9, True)
    else:
        sww = int(d.textlength(sw, font=font(9, False)))
        text(d, (width - 5 - sww, 2), sw, AMBER if waiting else ((190, 190, 205) if state != 'limit' else RED), 9, False)
    text(d, (5, 1), _fit(d, tag, width - 5 - sww - 5 - 4, 10, True), accent, 10)
    ctx = snap.ctx_pct if snap else None
    x0, y0 = 5, 15
    filled = filled_segments(ctx)
    col = bar_color(shown_pct(ctx), accent, phase)
    for i in range(SEGS):
        d.rectangle([x0 + i * 4, y0, x0 + i * 4 + 2, y0 + 6], fill=(col if i < filled else TRACK) + (255,))
    lx = x0 + SEGS * 4 + 3
    room = width - lx - 3
    c = shown_pct(ctx)
    plan = None if not snap or snap.plan_pct is None else f'{snap.plan_label} {shown_pct(snap.plan_pct)}%'.strip()
    resets = (getattr(snap, 'resets_in', '') or '') if plan else ''
    head = 'ctx -' if c is None else f'ctx {c}%'
    short = '-' if c is None else f'{c}%'
    f9 = font(9, False)
    label = None
    cands = []
    if plan and resets:                            # "wk 12% · 2d 4h": the reset countdown next to the plan figure (CodexBar-style)
        cands += [f'{head} {plan} · {resets}', f'{short} {plan} · {resets}', f'{short} {plan} {resets}']
    for cand in cands + ([f'{head} {plan}', f'{short} {plan}'] if plan else []) + [head, short]:
        if d.textlength(cand, font=f9) <= room:
            label = cand
            break
    text(d, (lx, 13), label or _fit(d, short, room, 9, False), (230, 230, 240), 9, False)
    return im


def plate_x(hip, facing, pw, bounds, gap=PLATE_GAP, half=20):
    """The plate sits behind the fighter.  If that side would leave the window bounds it flips to the front side, and
    only if neither side fits is it clamped (and then it can overlap the sprite)."""
    behind = hip - (gap + pw) if facing >= 0 else hip + gap
    front = hip + gap if facing >= 0 else hip - (gap + pw)
    for px in (behind, front):
        if bounds[0] <= px and px + pw <= bounds[1]:
            return px
    return max(bounds[0], min(bounds[1] - pw, behind))


def compose(style, atlas, view, snap, t, cfg, bounds=(0, 4000), show_plate=True):
    """-> (RGBA canvas, x0): a tight canvas around sprite + plate + projectile + effects, and its left edge in screen px.
    A small window is far cheaper for the desktop compositor than one spanning the whole roam zone.
    `style` is the Atlas (or legacy character name) whose tag/accent the plate uses.
    view['fx'] = effect placements [(image, left, top, layer, ...)] in the same logical px (back layer behind the sprite,
    front over it), view['banner'] = (image, centre x) drawn along the top, view['shake'] = (dx, dy) applied to the
    fighter and its effects (never to the plate).  Everything is clipped to the cell height."""
    if isinstance(style, str) and style == getattr(atlas, 'character', None):
        style = atlas
    cell_h = atlas.cell[1] if hasattr(atlas, 'cell') else CELL
    res = int(getattr(atlas, 'res', 1) or 1)
    top = int(round(float(view.get('headroom') or 0) * res))     # V7.1: window rows above the cell (airborne fighters)
    lift = int(round(float(view.get('lift') or 0.0) * res))      # V7.1: how high the fighter is (the `air` trajectory)
    sdx, sdy = view.get('shake') or (0, 0)
    sdy += top
    parts = []                                    # (image, screen_x, y)
    for im, lx, ty, layer, *_ in (view.get('fx') or []):
        if layer == 'back':
            parts.append((im, lx + sdx, ty + sdy))
    fr = atlas.frame_image(view['anim'], view['frame'], view['facing'])
    eye = view.get('eye')
    if eye and eye != (0, 0):
        from . import eyes
        fr = eyes.shift_eyes(fr, eyes.eye_pixels(atlas, view['anim'], view['frame'], view['facing']), eye[0] * atlas.res, eye[1] * atlas.res)
    if view.get('dim'):
        fr = fr.copy()
        fr.putalpha(fr.getchannel('A').point(lambda v: int(v * 0.55)))
    hip = int(round(view['x']))
    parts.append((fr, hip - atlas.anchor(view['facing']) + sdx, sdy - lift))
    if view.get('proj') and atlas.proj is not None:
        p = view['proj']
        pf = atlas.proj_image(p['frame'], p['dir'])
        pdy = int(round(float(p.get('dy') or 0.0) * res))        # V7.1: aimed at the opponent's height
        parts.append((pf, int(round(p['x'] - pf.width / 2)) + sdx, cell_h // 2 - pf.height // 2 + sdy + pdy))
    for im, lx, ty, layer, *_ in (view.get('fx') or []):
        if layer != 'back':
            parts.append((im, lx + sdx, ty + sdy))
    if view.get('banner'):
        bim, bx = view['banner']
        parts.append((bim, int(round(bx - bim.width / 2)), top))
    n_fight = len(parts)                          # everything so far belongs to the fight; the plate is never flashed over
    if show_plate and cfg.get('plate', True):
        pl = plate(style, snap, t)
        parts.append((pl, plate_x(hip, view['facing'], pl.width, bounds), 27))
    fx0 = min(p[1] for p in parts[:n_fight])
    fx1 = max(p[1] + p[0].width for p in parts[:n_fight])
    clip = view.get('clip')
    if clip:                                      # V7.1: never draw over a plate or the scoreboard (fight band, RES 1 px)
        c0, c1 = int(round(clip[0] * res)), int(round(clip[1] * res))
        fx0, fx1 = max(fx0, c0), min(fx1, c1)
        if fx1 <= fx0:
            fx0, fx1 = c0, c0 + 1
    x0 = min([fx0] + [p[1] for p in parts[n_fight:]])
    x1 = max([fx1] + [p[1] + p[0].width for p in parts[n_fight:]])
    cell_h += top
    canvas = Image.new('RGBA', (x1 - x0, cell_h), (0, 0, 0, 0))
    fight = Image.new('RGBA', (fx1 - fx0, cell_h), (0, 0, 0, 0))
    for im, sx, sy in parts[:n_fight]:
        _paste_clipped(fight, im, sx - fx0, sy)
    _paste_clipped(canvas, fight, fx0 - x0, 0)
    flash = float(view.get('flash') or 0.0)
    if flash > 0:                                 # V5: one-frame white flash over the fighter and its effects (plate-safe)
        white = Image.new('RGBA', (fx1 - fx0, cell_h), (255, 255, 255, 255))
        white.putalpha(_flash_mask(canvas, fx0 - x0, white.size, min(1.0, flash)))
        canvas.alpha_composite(white, (fx0 - x0, 0))
    for im, sx, sy in parts[n_fight:]:
        _paste_clipped(canvas, im, sx - x0, sy)
    return canvas, x0


def _flash_mask(canvas, x, size, k):
    """The flash whitens the drawn pixels (sprite + effects) by `k`, never the transparent taskbar around them."""
    region = canvas.crop((x, 0, x + size[0], size[1])).getchannel('A')
    return region.point(lambda v, k=k: int(v * k))


def compose_full(style, atlas, view, snap, t, zone_w, cfg, win_x=0, show_plate=True):
    """Full-width frame for previews / the simulator (window origin at screen x = win_x)."""
    canvas, x0 = compose(style, atlas, view, snap, t, cfg, bounds=(win_x, win_x + zone_w), show_plate=show_plate)
    full = Image.new('RGBA', (zone_w, canvas.height), (0, 0, 0, 0))
    _paste_clipped(full, canvas, x0 - win_x, 0)
    return full


def _paste_clipped(dst, src, x, y=0):
    w, h = dst.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(src.width, w - x), min(src.height, h - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    dst.alpha_composite(src.crop((sx0, sy0, sx1, sy1)), (max(0, x), max(0, y)))
