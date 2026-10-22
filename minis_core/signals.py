"""Real-event signals (UX item 4): the four moments that matter get their own unmistakable mark on the fighter.

  task done      'finished' event   a small victory flag over the fighter's head; it stays until the mouse passes over the
                                    fighter (the "ready for review" signal - the handoff alone was easy to miss)
  needs you      state 'waiting'    the clearest thing on screen: a gentle amber halo pulsing round the fighter (on top of the
                                    bouncing "!" and the amber plate border it already had), and a wave now and then.  Never a
                                    popup, never focus, never a sound
  second wind    ctx drops sharply  (context compaction: the same session falls from 85%+ to under 40%) a comeback flourish:
                                    "SECOND WIND", rising sparks, a power-up, and the plate's meter refills in front of you
  finisher cue   near the limit     "DANGER" once when context first passes 85%; "FINISH!" over the fighter as its limit K.O.
                                    lands, so a limit reads as a finisher and not a random loss

Respect: paused -> no motion (the flag and a still halo stay, nothing new starts); quiet / calm mode -> only the static
marks; Flash effects off -> no pulse, the halo stays still; full-screen apps, the arena and a hidden fighter hide the window
anyway.  Everything here is numbers and enums from the snapshot; no text from a transcript ever reaches it.

The overlay images are drawn in the brain's RES 1 pixels and handed to render.compose as front effects (view['fx']), so they
move, shake and scale with the fighter exactly like its own sparks (2x pixel art at 128 px).
"""
from __future__ import annotations
import math

from PIL import Image, ImageDraw

COMPACT_FROM, COMPACT_TO = 85.0, 40.0
DANGER_AT, DANGER_REARM = 85.0, 80.0
SECOND_WIND_S, DANGER_S, FINISH_S, REFILL_S = 3.0, 2.8, 1.8, 1.6
WAVE_EVERY_S = 30.0
AMBER, GOLD, GREEN, RED = (255, 196, 80), (255, 214, 92), (130, 235, 140), (255, 86, 70)


def _text(txt, size, fill, outline=(20, 14, 10, 255)):
    from .fx import text_image
    return text_image(txt, size, fill + (255,) if len(fill) == 3 else fill, outline)


_cache = {}


def flag_image(phase=0):
    """A 12 x 16 px victory flag: a dark pole, a gold pennant with a white tick, two wave phases."""
    key = ('flag', phase)
    if key in _cache:
        return _cache[key]
    im = Image.new('RGBA', (13, 17), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, 2, 16], fill=(40, 30, 24, 255))                      # pole + outline
    d.rectangle([1, 0, 2, 0], fill=(255, 236, 170, 255))                    # finial
    off = (0, 1)[phase % 2]
    pts = [(3, 1), (12, 2 + off), (11, 5 + off), (12, 8 + off), (3, 8)]
    d.polygon(pts, fill=GOLD + (255,), outline=(90, 60, 20, 255))
    d.line([(5, 5), (6, 6), (9, 3)], fill=(255, 255, 255, 255))             # the tick
    _cache[key] = im
    return im


def halo_image(r, alpha):
    """The needs-you halo: an amber ellipse outline round the fighter's feet (r = half width, RES 1 px)."""
    key = ('halo', int(r), int(alpha))
    if key in _cache:
        return _cache[key]
    w, h = 2 * int(r) + 4, max(6, int(r * 0.42) + 4)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, w - 1, h - 1], outline=(120, 70, 10, int(alpha * 0.8)), width=1)          # a dark rim so it reads on any taskbar
    d.ellipse([1, 1, w - 2, h - 2], outline=AMBER + (int(alpha),), width=1)
    d.ellipse([2, 2, w - 3, h - 3], outline=(255, 236, 170, int(alpha * 0.7)), width=1)
    if len(_cache) > 400:
        _cache.clear()
    _cache[key] = im
    return im


def spark_image():
    if 'spark' not in _cache:
        im = Image.new('RGBA', (3, 3), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.point([(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)], fill=GREEN + (255,))
        _cache['spark'] = im
    return _cache['spark']


def text_mark(kind):
    key = ('text', kind)
    if key not in _cache:
        txt, col = {'second': ('SECOND WIND', GREEN), 'danger': ('DANGER', RED), 'finish': ('FINISH!', GOLD)}[kind]
        _cache[key] = _text(txt, 9, col)
    return _cache[key]


class Signals:
    """One fighter's signal state.  Feed it every snapshot (on_snapshot, BEFORE the brain consumes the events); ask it for
    the overlays of each drawn frame (overlays), the plate's snapshot (plate_snap) and the moves to play (take_moves)."""

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.flag = False                 # task done: up until hovered
        self.flag_since = None
        self.waiting_since = None
        self.state = None
        self.state_since = None
        self.sid = None
        self.ctx = None
        self.second = None                # (t_start, ctx_from, ctx_to)
        self.danger_until = 0.0
        self.danger_armed = True
        self.finish_until = 0.0
        self.next_wave = 0.0
        self.moves = []                   # anims the owner should play when the fighter is free (wave, powerup)
        self.events = []                  # what happened, for tests and the log: (t, kind)

    # ---------------------------------------------------------- input
    def on_snapshot(self, snap, now, paused=False):
        """`now`: monotonic seconds.  Reads state, ctx, sid and the one-shot events; never content."""
        if snap is None:
            return
        st = getattr(snap, 'state', None)
        if st != self.state:
            self.state, self.state_since = st, now
            if st == 'waiting':
                self.waiting_since = now
                if not paused:
                    self.moves.append('wave')
                self.next_wave = now + WAVE_EVERY_S
            elif self.waiting_since is not None:
                self.waiting_since = None
        elif st == 'waiting' and now >= self.next_wave and not paused:
            self.next_wave = now + WAVE_EVERY_S
            self.moves.append('wave')
        evs = list(getattr(snap, 'events', None) or ())
        if 'finished' in evs:
            self.flag, self.flag_since = True, now
            self.events.append((now, 'flag'))
        if 'limit' in evs:
            self.finish_until = now + FINISH_S
            self.events.append((now, 'finish'))
        ctx = getattr(snap, 'ctx_pct', None)
        sid = getattr(snap, 'sid', '') or ''
        if ctx is not None:
            same = self.sid is None or sid == self.sid or not sid or not self.sid
            if same and self.ctx is not None and self.ctx >= COMPACT_FROM and ctx < COMPACT_TO and st != 'sleeping':
                self.second = (now, float(self.ctx), float(ctx))
                self.events.append((now, 'second_wind'))
                if not paused:
                    self.moves.append('powerup')
            if ctx >= DANGER_AT and st != 'limit' and self.danger_armed and 'limit' not in evs:
                self.danger_until = now + DANGER_S
                self.danger_armed = False
                self.events.append((now, 'danger'))
            elif ctx < DANGER_REARM:
                self.danger_armed = True
            self.ctx = float(ctx)
        if sid:
            self.sid = sid

    def hovered(self, now=None):
        """The mouse passed over the fighter: the done flag has been seen."""
        if self.flag:
            self.flag = False
            self.events.append((now, 'flag_seen'))
            return True
        return False

    def take_moves(self):
        out, self.moves = self.moves, []
        return out

    # ---------------------------------------------------------- output
    def active(self, now):
        return bool(self.flag or self.state == 'waiting' or (self.second and now - self.second[0] < SECOND_WIND_S)
                    or now < self.danger_until or now < self.finish_until)

    def key(self, now, paused=False, still=False):
        """Changes whenever the overlay picture changes (the owner's redraw signature)."""
        moving = not (paused or still)
        return (self.flag, self.state == 'waiting', bool(self.second and now - self.second[0] < SECOND_WIND_S),
                now < self.danger_until, now < self.finish_until, int(now * 8) % 16 if moving and self.active(now) else 0)

    def overlays(self, view, atlas, now, paused=False, flashes=True, quiet=False):
        """-> [(image, left, top, 'front')] in RES 1 px for this frame, and whether they animate."""
        out = []
        anim = False
        x = float(view.get('x', 0.0))
        lift = float(view.get('lift') or 0.0)
        top = head_top(atlas, view) - lift
        still = paused or quiet
        y_next = top - 3
        if self.flag:
            ph = 0 if still else int(now * 2.5) % 2
            im = flag_image(ph)
            out.append((im, int(round(x - 2)), int(round(y_next - im.height)), 'front'))
            y_next -= im.height + 1
            anim = anim or not still
        if self.state == 'waiting':
            ground = atlas.ground_y if hasattr(atlas, 'ground_y') else 57
            if still or not flashes:
                r, a = 15, 200
            else:
                k = (now % 1.6) / 1.6
                r, a = 12 + 7 * k, 200 * (1.0 - k) ** 1.2 + 55
                anim = True
            im = halo_image(r, a)
            out.append((im, int(round(x - im.width / 2)), int(round(ground - im.height / 2 + 1)), 'back'))
        if not quiet:
            if self.second and now - self.second[0] < SECOND_WIND_S and not paused:
                el = now - self.second[0]
                im = text_mark('second')
                out.append((im, int(round(x - im.width / 2)), int(round(y_next - im.height + 4 - min(4, el * 6))), 'front'))
                y_next -= im.height - 2
                sp = spark_image()
                for i in range(6):
                    ph = (el * 1.3 + i / 6.0) % 1.0
                    sx = x + math.sin(i * 2.1 + el * 3) * (8 + i % 3 * 3)
                    sy = (atlas.ground_y if hasattr(atlas, 'ground_y') else 57) - ph * 38
                    out.append((sp, int(round(sx)), int(round(sy)), 'front'))
                anim = True
            if now < self.finish_until:
                im = text_mark('finish')
                el = FINISH_S - (self.finish_until - now)
                bob = 0 if paused else int(min(3, el * 10))
                out.append((im, int(round(x - im.width / 2)), int(round(y_next - im.height + 6 - bob)), 'front'))
                anim = anim or not paused
            elif now < self.danger_until and self.state != 'limit':
                im = text_mark('danger')
                vis = paused or int(now * 3) % 2 == 0 or not flashes
                if vis:
                    out.append((im, int(round(x - im.width / 2)), int(round(y_next - im.height + 6)), 'front'))
                anim = anim or (flashes and not paused)
        return out, anim

    def plate_snap(self, snap, now):
        """The plate's snapshot: during a second wind the context meter sweeps down from the old fill to the new one (the
        "refill"), else the snapshot itself."""
        if snap is None or not self.second:
            return snap
        t0, a, b = self.second
        el = now - t0
        if el < 0 or el >= REFILL_S:
            return snap
        import copy
        s2 = copy.copy(snap)
        k = el / REFILL_S
        s2.ctx_pct = a + (b - a) * (1 - (1 - k) ** 2)
        s2.events = []
        return s2


_head = {}


def head_top(atlas, view):
    """y (RES 1 px, cell coordinates) of the top of the fighter's drawn pixels in this frame (cached per frame)."""
    try:
        key = (atlas.character, view['anim'], int(view['frame']), view['facing'] >= 0)
    except (KeyError, TypeError):
        return 14
    v = _head.get(key)
    if v is None:
        try:
            bb = atlas.frame_image(view['anim'], view['frame'], view['facing']).getchannel('A').getbbox()
            v = (bb[1] / float(max(1, getattr(atlas, 'res', 1)))) if bb else 14
        except Exception:
            v = 14
        if len(_head) > 4000:
            _head.clear()
        _head[key] = v
    return v
