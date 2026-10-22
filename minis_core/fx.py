"""Effects library: fx.json + fx.png (built by the ART side), with procedural placeholders when the sheet is missing.

Schema (docs/V4-WORKORDER.md, "Shared interfaces"):
  {"res": 2, "effects": {"<name>": {"frames": [{"x","y","w","h","ms"}], "anchor": "hand|ground|center", "offset": [dx, dy],
                                     "loop": false, "layer": "front|back", "hit_frame": n,
                                     "travel": {"speed": px/s} | null, "shake": {"frames": n, "amp": px} | null,
                                     "grow": {"from_w": px, "to_w": px, "ms": n} | absent, "flash": true | absent}}}
`grow` (V5, optional): a beam that extends from its anchor edge from `from_w` to `to_w` pixels over `ms`, holds, then
retracts / fades over the last frame (`retract_ms` overrides).  `flash` (optional): a one-frame white screen flash on the
effect's hit frame.  Both are read when present; an effect without them plays exactly as before.
`res` is optional; a sheet without it is taken as RES 2 (built beside assets_hd).  Frames are crops from fx.png.

Where the sheet is looked for (first hit wins, then per-character sheets are merged on top):
  assets_hd/fx/fx.json, assets_hd/fx.json, assets/fx/fx.json, assets/fx.json, then assets_hd/<character>/fx.json.
Nothing here is required to exist: every generic effect (hit_light, hit_heavy, block_spark, dust, ko_stars, crack_small,
crack_big, shatter, explosion, letters, ko_text, round_text) has a simple procedural stand-in, and an unknown ultimate
name gets a generic burst, so the engine renders the same choreography with or without the art.

Text banners: `banner(kind)` for kind in round1 | round2 | round3 | fight | ko | winner | time (V6; `banner('winner', name=...)`
is the winner's name banner).  From the sheet it reads
`round_text` frames in that order (ROUND 1, ROUND 2, ROUND 3, FIGHT!, WINNER) and `ko_text` for K.O.; individually
named effects (`round_1`, `round_2`, `round_3`, `fight`, `winner`, `ko`) win over that convention when present.
"""
from __future__ import annotations
import json, math, random
from pathlib import Path
from PIL import Image, ImageDraw

from .render import font, text as _text

from . import paths as _paths
ROOT = _paths.bundle_root()                         # the folder holding assets/ and assets_hd/ (paths.py)
CANDIDATES = (ROOT / 'assets_hd' / 'fx' / 'fx.json', ROOT / 'assets_hd' / 'fx.json', ROOT / 'assets' / 'fx' / 'fx.json', ROOT / 'assets' / 'fx.json')
GENERIC = ('hit_light', 'hit_heavy', 'block_spark', 'dust', 'ko_stars', 'crack_small', 'crack_big', 'shatter', 'explosion', 'letters', 'ko_text', 'round_text')
BANNERS = ('round1', 'round2', 'round3', 'fight', 'ko', 'winner', 'time')
BANNER_TEXT = {'round1': 'ROUND 1', 'round2': 'ROUND 2', 'round3': 'ROUND 3', 'fight': 'FIGHT!', 'ko': 'K.O.', 'winner': 'WINNER', 'time': 'TIME'}
BANNER_NAMES = {'round1': 'round_1', 'round2': 'round_2', 'round3': 'round_3', 'fight': 'fight', 'ko': 'ko', 'winner': 'winner', 'time': 'time'}
ROUND_TEXT_ORDER = ('round1', 'round2', 'round3', 'fight', 'winner')
LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


class Effect:
    """One effect: frames [(RGBA, ms)] at `res`, plus placement and playback metadata."""

    def __init__(self, name, frames, anchor='center', offset=(0, 0), loop=False, layer='front', hit_frame=None,
                 travel=None, shake=None, res=2, procedural=False, grow=None, flash=False):
        if not frames:
            raise ValueError(f'{name}: no frames')
        self.name, self.frames = name, [(im, max(1, int(ms))) for im, ms in frames]
        self.anchor = anchor if anchor in ('hand', 'ground', 'center') else 'center'
        self.offset = (int(offset[0]), int(offset[1])) if isinstance(offset, (list, tuple)) and len(offset) == 2 else (0, 0)
        self.loop, self.layer = bool(loop), ('back' if layer == 'back' else 'front')
        self.hit_frame = None if hit_frame is None else max(0, min(len(self.frames) - 1, int(hit_frame)))
        self.travel = dict(speed=float(travel['speed'])) if isinstance(travel, dict) and travel.get('speed') else None
        self.shake = dict(frames=int(shake.get('frames', 0)), amp=float(shake.get('amp', 0))) if isinstance(shake, dict) and shake.get('frames') else None
        self.res, self.procedural = max(1, int(res)), procedural
        self.total_ms = sum(ms for _, ms in self.frames)
        self.grow = self._grow(grow)
        self.flash = bool(flash)
        self._cache = {}

    def _grow(self, g):
        """{'from_w','to_w','ms','retract_ms'} in this effect's pixels, or None.  Bad values mean no growth, never an error."""
        if not isinstance(g, dict):
            return None
        try:
            w_full = max(im.width for im, _ in self.frames)
            to_w = int(g.get('to_w', w_full))
            from_w = int(g.get('from_w', 0))
            ms = int(g.get('ms', 0))
        except (TypeError, ValueError):
            return None
        if to_w <= 0 or ms <= 0:
            return None
        to_w = min(to_w, w_full)
        from_w = max(0, min(from_w, to_w))
        try:
            retract = int(g.get('retract_ms', self.frames[-1][1]))
        except (TypeError, ValueError):
            retract = self.frames[-1][1]
        retract = max(0, min(retract, max(0, self.total_ms - ms)))
        return dict(from_w=from_w, to_w=to_w, ms=ms, retract_ms=retract)

    def extent(self, elapsed_ms):
        """-> (start, end, alpha) of the visible beam span in this effect's pixels from the anchor edge, for a growing
        effect: extends from_w -> to_w over `ms`, holds, then the start edge races to the end while it fades.
        None when the effect does not grow."""
        g = self.grow
        if g is None:
            return None
        el = max(0.0, float(elapsed_ms))
        if el <= g['ms']:
            return 0, g['from_w'] + (g['to_w'] - g['from_w']) * el / g['ms'], 1.0
        t_ret = self.total_ms - g['retract_ms']
        if g['retract_ms'] <= 0 or el < t_ret or self.loop:
            return 0, g['to_w'], 1.0
        k = min(1.0, (el - t_ret) / float(g['retract_ms']))
        return g['to_w'] * k, g['to_w'], 1.0 - 0.85 * k

    def hit_ms(self):
        """Milliseconds from the start to the hit frame (0 without one)."""
        if self.hit_frame is None:
            return 0
        return sum(ms for _, ms in self.frames[:self.hit_frame])

    def locate(self, elapsed_ms):
        """-> (frame index, finished)."""
        if self.loop:
            elapsed_ms = elapsed_ms % self.total_ms
        elif elapsed_ms >= self.total_ms:
            return len(self.frames) - 1, True
        t = 0
        for i, (_, ms) in enumerate(self.frames):
            t += ms
            if elapsed_ms < t:
                return i, False
        return len(self.frames) - 1, not self.loop

    def image(self, i, facing=1, scale=1.0):
        """Frame i, flipped for a left-facing owner, scaled by `scale` (nearest neighbour; cached)."""
        i = max(0, min(len(self.frames) - 1, int(i)))
        key = (i, facing >= 0, round(scale, 3))
        im = self._cache.get(key)
        if im is None:
            if len(self._cache) > 256:
                self._cache.clear()
            im = self.frames[i][0]
            if facing < 0:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if scale != 1.0:
                im = im.resize((max(1, int(round(im.width * scale))), max(1, int(round(im.height * scale)))), Image.NEAREST)
            self._cache[key] = im
        return im


# ---------------------------------------------------------------- procedural stand-ins (RES 2 geometry)
def _canvas(w, h):
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _burst(size, color, spikes, phase, core=(255, 255, 255, 255)):
    im, d = _canvas(size, size)
    c = size / 2.0
    r = c * (0.45 + 0.5 * phase)
    pts = []
    for k in range(spikes * 2):
        a = math.pi * k / spikes
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((c + rr * math.cos(a), c + rr * math.sin(a)))
    d.polygon(pts, fill=color)
    cr = max(1, r * 0.3 * (1.0 - phase))
    d.ellipse([c - cr, c - cr, c + cr, c + cr], fill=core)
    return im


def _hit(size, color, n=3, spikes=6):
    return [(_burst(size, color, spikes, k / max(1, n - 1)), 50) for k in range(n)]


def _spark(size):
    out = []
    for k in range(3):
        im, d = _canvas(size, size)
        c = size / 2.0
        for j in range(5):
            a = -math.pi / 2 + (j - 2) * 0.5
            L = c * (0.5 + 0.5 * k / 2)
            d.line([(c, c), (c + L * math.cos(a), c + L * math.sin(a))], fill=(255, 240, 160, 255), width=max(1, size // 24))
        out.append((im, 50))
    return out


def _dust(size):
    out = []
    for k in range(4):
        im, d = _canvas(size, size // 2)
        for j in range(4):
            x = size / 2 + (j - 1.5) * size * 0.2 * (1 + k * 0.4)
            r = size * 0.08 * (1.4 - k * 0.25)
            d.ellipse([x - r, size // 2 - r * 2 - k * 2, x + r, size // 2 - k * 2], fill=(200, 196, 190, 190 - k * 40))
        out.append((im, 70))
    return out


def _stars(size):
    out = []
    for k in range(4):
        im, d = _canvas(size, size // 2)
        for j in range(3):
            a = k * 0.8 + j * 2.1
            x, y = size / 2 + math.cos(a) * size * 0.35, size / 4 + math.sin(a) * size * 0.12
            r = size * 0.06
            d.polygon([(x, y - r), (x + r * 0.4, y - r * 0.3), (x + r, y), (x + r * 0.4, y + r * 0.3), (x, y + r), (x - r * 0.4, y + r * 0.3), (x - r, y), (x - r * 0.4, y - r * 0.3)],
                      fill=(255, 226, 122, 255))
        out.append((im, 120))
    return out


def _crack(size, big, seed=7):
    rng = random.Random(seed)
    im, d = _canvas(size, size)
    c = size / 2.0
    for j in range(8 if big else 5):
        a = rng.uniform(0, 2 * math.pi)
        x, y = c, c
        for seg in range(4 if big else 3):
            L = size * rng.uniform(0.08, 0.2)
            a += rng.uniform(-0.5, 0.5)
            nx, ny = x + L * math.cos(a), y + L * math.sin(a)
            d.line([(x, y), (nx, ny)], fill=(240, 244, 255, 230), width=2 if big else 1)
            d.line([(x + 1, y + 1), (nx + 1, ny + 1)], fill=(30, 30, 40, 160), width=1)
            x, y = nx, ny
    return [(im, 100)]


def _shards(size, n=6, seed=3):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        im, d = _canvas(size // 3, size // 3)
        w = size // 3
        pts = [(rng.uniform(0, w), rng.uniform(0, w)) for _ in range(3)]
        d.polygon(pts, fill=(220, 228, 245, 220), outline=(255, 255, 255, 255))
        out.append((im, 60))
    return out


def _explosion(size):
    out = []
    cols = [(255, 240, 180, 255), (255, 170, 60, 255), (230, 80, 30, 240), (90, 60, 50, 200), (60, 50, 50, 120)]
    for k in range(5):
        im, d = _canvas(size, size)
        c = size / 2.0
        r = c * (0.3 + 0.7 * k / 4)
        d.ellipse([c - r, c - r, c + r, c + r], fill=cols[k])
        if k < 3:
            r2 = r * 0.5
            d.ellipse([c - r2, c - r2, c + r2, c + r2], fill=(255, 255, 240, 255))
        out.append((im, 70))
    return out


def _glyphs(size):
    out = []
    for sz in (size, size // 2):
        for ch in LETTERS:
            im, d = _canvas(sz + 4, sz + 6)
            _text(d, (2, 0), ch, (245, 245, 250, 255), sz)
            out.append((im, 100))
    return out


def _beam(size):
    out = []
    for k in range(6):
        im, d = _canvas(size * 2, size // 2)
        h = size // 2
        L = size * 2 * min(1.0, 0.3 + k * 0.25)
        d.rectangle([0, h * 0.3, L, h * 0.7], fill=(120, 200, 255, 230))
        d.rectangle([0, h * 0.42, L, h * 0.58], fill=(255, 255, 255, 255))
        out.append((im, 90))
    return out


def text_image(txt, size=28, fill=(255, 236, 120, 255), outline=(40, 20, 10, 255)):
    """Text with a dark outline (banners, the signal marks).  Through render.text: the shipped pixel font up to 12 px (a 1 px
    outline suits its 1 px strokes), an OS face above."""
    f = font(size, True)
    im0, d0 = _canvas(4, 4)
    w = int(d0.textlength(txt, font=f)) + 8
    im, d = _canvas(w, size + 10)
    o = 1 if size <= 12 else 2
    for dx, dy in ((-o, 0), (o, 0), (0, -o), (0, o), (-1, -1), (1, 1), (1, -1), (-1, 1)):
        _text(d, (4 + dx, 2 + dy), txt, outline, size)
    _text(d, (4, 2), txt, fill, size)
    return im


def procedural(name, res=2):
    """A stand-in Effect for a generic or unknown effect name (RES 2 sizes; the renderer scales by res)."""
    u = 16 * res
    if name == 'hit_light':
        return Effect(name, _hit(2 * u, (255, 230, 120, 255)), anchor='center', res=res, procedural=True)
    if name == 'hit_heavy':
        return Effect(name, _hit(3 * u, (255, 140, 60, 255), 4, 8), anchor='center', shake={'frames': 4, 'amp': 3 * res}, res=res, procedural=True)
    if name == 'block_spark':
        return Effect(name, _spark(2 * u), anchor='hand', res=res, procedural=True)
    if name == 'dust':
        return Effect(name, _dust(3 * u), anchor='ground', offset=(0, 0), layer='back', res=res, procedural=True)
    if name == 'ko_stars':
        return Effect(name, _stars(3 * u), anchor='center', offset=(0, -14 * res), loop=True, res=res, procedural=True)
    if name == 'crack_small':
        return Effect(name, _crack(3 * u, False), anchor='center', res=res, procedural=True)
    if name == 'crack_big':
        return Effect(name, _crack(5 * u, True, seed=11), anchor='center', res=res, procedural=True)
    if name == 'shatter':
        return Effect(name, _shards(5 * u), anchor='center', res=res, procedural=True)
    if name == 'explosion':
        return Effect(name, _explosion(6 * u), anchor='center', shake={'frames': 8, 'amp': 6 * res}, res=res, procedural=True)
    if name == 'letters':
        return Effect(name, _glyphs(12 * res), anchor='center', res=res, procedural=True)
    if name == 'alert':                                     # waiting?: a bouncing "!" over the head, loops until the state changes
        frames = []
        for k in range(4):
            im = text_image('!', 12 * res, (255, 196, 80, 255), (60, 30, 10, 255))
            pad, _ = _canvas(im.width, im.height + 4 * res)
            pad.alpha_composite(im, (0, (0, 2, 4, 2)[k] * res // 2))
            frames.append((pad, 140))
        return Effect(name, frames, anchor='center', offset=(0, -34 * res), loop=True, res=res, procedural=True)
    if name == 'ko_text':
        return Effect(name, [(text_image('K.O.', 20 * res, (255, 90, 70, 255)), 1500)], anchor='center', res=res, procedural=True)
    if name == 'round_text':
        return Effect(name, [(text_image(BANNER_TEXT[k], 14 * res), 1200) for k in ROUND_TEXT_ORDER], anchor='center', res=res, procedural=True)
    # an ultimate (or anything else) without art: a beam-ish burst from the hand, with a shake
    return Effect(name, _beam(4 * u), anchor='hand', offset=(2 * u, -u // 2), hit_frame=3, shake={'frames': 6, 'amp': 4 * res}, res=res, procedural=True)


# ---------------------------------------------------------------- the library
class Fx:
    def __init__(self, paths=None, characters=(), res=None):
        self.effects = {}
        self.loaded_from = []
        self.errors = {}
        self.res = res
        found = [p for p in (paths if paths is not None else CANDIDATES) if Path(p).is_file()]
        for p in found[:1] + [ROOT / 'assets_hd' / c / 'fx.json' for c in characters]:
            if Path(p).is_file():
                self._load(Path(p))
        if self.res is None:
            self.res = 2
        self._procedural = {}

    def _load(self, path):
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
            sheet = Image.open(path.with_name(meta.get('sheet', 'fx.png'))).convert('RGBA')
        except (OSError, ValueError) as e:
            self.errors[str(path)] = type(e).__name__
            return
        res = int(meta.get('res') or 2)
        if self.res is None:
            self.res = res
        effects = meta.get('effects') if isinstance(meta.get('effects'), dict) else {}
        for name, e in effects.items():
            try:
                frames = []
                for f in e.get('frames') or []:
                    box = (int(f['x']), int(f['y']), int(f['x']) + int(f['w']), int(f['y']) + int(f['h']))
                    if box[2] > sheet.width or box[3] > sheet.height or int(f['w']) <= 0 or int(f['h']) <= 0:
                        raise ValueError('frame outside the sheet')
                    frames.append((sheet.crop(box), int(f.get('ms', 80))))
                self.effects[name] = Effect(name, frames, e.get('anchor', 'center'), e.get('offset', (0, 0)), e.get('loop', False),
                                            e.get('layer', 'front'), e.get('hit_frame'), e.get('travel'), e.get('shake'), res,
                                            grow=e.get('grow'), flash=e.get('flash', False))
            except (KeyError, TypeError, ValueError) as err:
                self.errors[f'{path.name}:{name}'] = type(err).__name__
        self.loaded_from.append(str(path))

    # ---- lookup
    def __contains__(self, name):
        return name in self.effects

    def has_art(self, name) -> bool:
        return name in self.effects

    def get(self, name) -> Effect:
        """The effect from the sheet, else a procedural stand-in (never None, never raises)."""
        e = self.effects.get(name)
        if e is None:
            e = self._procedural.get(name)
            if e is None:
                e = self._procedural[name] = procedural(name, self.res)
        return e

    def names(self):
        return sorted(set(self.effects) | set(GENERIC))

    # ---- text + letters
    def banner(self, kind, name=None) -> Image.Image:
        """The banner image.  V6: `winner` with a `name` is the name banner '<NAME> WINS' (drawn centred over the winner);
        `time` (a round called on time) is a named `time` effect when the sheet has one, else drawn text."""
        if kind not in BANNERS:
            raise ValueError(kind)
        if (kind == 'winner' and name) or (kind == 'time' and BANNER_NAMES[kind] not in self.effects):
            txt = f'{str(name).upper()[:16]} WINS' if kind == 'winner' else BANNER_TEXT[kind]
            cache = self.__dict__.setdefault('_text_banners', {})
            if txt not in cache:
                cache[txt] = text_image(txt, 14 * self.res, (255, 236, 120, 255) if kind == 'winner' else (255, 255, 255, 255))
            return cache[txt]
        e = self.effects.get(BANNER_NAMES[kind])
        if e is not None:
            return e.frames[0][0]
        if kind == 'ko':
            e = self.effects.get('ko_text')
            if e is not None:
                return e.frames[0][0]
        else:
            e = self.effects.get('round_text')
            if e is not None and len(e.frames) >= len(ROUND_TEXT_ORDER):
                return e.frames[ROUND_TEXT_ORDER.index(kind)][0]
        return self.get('ko_text' if kind == 'ko' else 'round_text').frames[0 if kind == 'ko' else ROUND_TEXT_ORDER.index(kind)][0]

    def letter(self, rng) -> Image.Image:
        """A random glyph for a letter spray (random letters only: never text read from anywhere)."""
        e = self.get('letters')
        return e.frames[rng.randrange(len(e.frames))][0]


_default = None


def default() -> Fx:
    """The shared sheet plus every built character's own sheet (assets_hd/<character>/fx.json), loaded once."""
    global _default
    if _default is None:
        try:
            chars = sorted(p.name for p in (ROOT / 'assets_hd').iterdir() if (p / 'fx.json').is_file())
        except OSError:
            chars = []
        _default = Fx(characters=chars)
    return _default
