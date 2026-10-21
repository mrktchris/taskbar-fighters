"""First-run guide and the "What am I looking at?" legend (UX item 2).

Guide: on the very first start, three short cards in turn, each pointing down at the real thing on the taskbar:
  1  a fighter   "Each fighter is an AI tool on your PC"
  2  the plates  "Plates: what it is doing + context %"
  3  the board   "Right-click a fighter or the tray for everything"
Next / Skip on each card; it shows once (ux.json first_run_done) and never comes back on its own.  Each card moves on by
itself after a while, so ignoring it is fine too.  It never takes the keyboard focus.

Legend: tray > "What am I looking at?" (or `minis.py guide`) shows every label at once for 10 seconds, with the one-line key
to the fights (fight = working, handoff = task done, K.O. = context limit, amber = needs you).  A click closes it early.

Pure model: layout, timing, hit-testing and rendering.  minis_win/guide_window.py puts it in a click-through window over
the taskbar strip (only the cards take the mouse).
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from .render import font, text

GH = 104                           # the overlay's height above the taskbar (logical px)
CARD_W, CARD_H = 236, 66
STEP_S = 14.0                      # a card moves on by itself after this long
LEGEND_S = 10.0
BG, EDGE, INK, DIM = (16, 16, 22, 244), (110, 110, 128, 255), (236, 236, 244), (170, 170, 185)
AMBER, LINK, GOLD = (255, 196, 80), (140, 190, 255), (255, 214, 92)
KEY_LINE = 'fight = an agent is working   ·   handoff = a task finished   ·   K.O. = context limit   ·   amber = needs you'


def steps(names=None):
    """The three cards: (target, title, body lines, accent)."""
    who = (names or {}).get('a') or 'Claude Code'
    return [('fighter', 'Each fighter is an AI tool on your PC',
             [f'This one is {who}. Fighting = it is working;', 'a handoff = it finished a task.'], (240, 161, 132)),
            ('plates', 'Plates: what it is doing + context %',
             ['working · idle · waiting? · done · limit, and how full', 'its context window is (amber = needs you).'], AMBER),
            ('board', 'Right-click a fighter or the tray for everything',
             ['Settings, fighter select, replays, the move book.', 'Click a name on the scoreboard to pick fighters.'], LINK)]


class Guide:
    """kind: 'guide' (three cards in turn) | 'legend' (all labels for 10 s).  span: (x0, x1) screen-logical px the overlay
    covers; targets: {'fighter': x, 'plates': (x0, x1), 'board': (x0, x1)} in the same px (None = not on screen)."""

    def __init__(self, kind, span, targets, names=None, now=0.0, plates_note=None):
        self.kind = kind
        self.x0, self.x1 = int(span[0]), int(span[1])
        self.W, self.H = max(CARD_W + 8, self.x1 - self.x0), GH
        self.targets = dict(targets or {})
        self.steps = steps(names)
        self.plates_note = plates_note
        self.i = 0
        self.t_step = now
        self.t0 = now
        self.phase = 'open'
        self.pressed = None
        self.hover = None

    # ---------------------------------------------------------- geometry
    def target_x(self, name):
        t = self.targets.get(name)
        if t is None:
            return None
        if isinstance(t, (tuple, list)):
            return (float(t[0]) + float(t[1])) / 2.0 - self.x0
        return float(t) - self.x0

    def card_rect(self, i=None, w=CARD_W, h=CARD_H, y=4):
        name = self.steps[self.i if i is None else i][0]
        tx = self.target_x(name)
        if tx is None:
            tx = self.W / 2
        x = int(max(2, min(self.W - w - 2, tx - w / 2)))
        return x, y, x + w, y + h

    def buttons(self):
        x0, y0, x1, y1 = self.card_rect()
        nxt = (x1 - 62, y1 - 19, x1 - 6, y1 - 5)
        skip = (x1 - 106, y1 - 19, x1 - 66, y1 - 5)
        return {'next': nxt, 'skip': skip}

    def hit(self, x, y):
        """-> 'next' | 'skip' | 'card' | 'legend' | None (click-through)."""
        if self.phase != 'open':
            return None
        if self.kind == 'legend':
            for r in self._legend_boxes().values():
                if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                    return 'legend'
            return None
        for name, r in self.buttons().items():
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return name
        r = self.card_rect()
        if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
            return 'card'
        return None

    # ---------------------------------------------------------- input / time
    def click(self, x, y, now):
        h = self.hit(x, y)
        if h == 'next':
            self.advance(now)
        elif h == 'skip':
            self.phase = 'done'
        elif h == 'legend':
            self.phase = 'closed'
        return h

    def advance(self, now):
        if self.i + 1 >= len(self.steps):
            self.phase = 'done'
        else:
            self.i += 1
            self.t_step = now

    def tick(self, now):
        if self.phase != 'open':
            return
        if self.kind == 'legend':
            if now - self.t0 >= LEGEND_S:
                self.phase = 'closed'
        elif now - self.t_step >= STEP_S:
            self.advance(now)

    def move(self, x, y):
        self.hover = self.hit(x, y)

    def frame_key(self, now):
        return (self.phase, self.i, self.hover, self.pressed, int((now - self.t0) * 4))

    # ---------------------------------------------------------- drawing
    def _arrow(self, d, x_from, y_from, x_to, col):
        y_to = self.H - 3
        x_to = max(4, min(self.W - 4, x_to))
        d.line([(x_from, y_from), (x_from, y_from + 6)], fill=col + (255,), width=2)
        if abs(x_to - x_from) > 2:
            d.line([(x_from, y_from + 6), (x_to, y_from + 6)], fill=col + (255,), width=2)
        d.line([(x_to, y_from + 6), (x_to, y_to - 4)], fill=col + (255,), width=2)
        d.polygon([(x_to - 4, y_to - 5), (x_to + 4, y_to - 5), (x_to, y_to)], fill=col + (255,))

    def _card(self, d, r, title, body, col, foot=None):
        x0, y0, x1, y1 = r
        d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], 5, fill=BG, outline=col + (255,), width=2)
        text(d, (x0 + 8, y0 + 4), title, col, 10)
        for j, ln in enumerate(body):
            text(d, (x0 + 8, y0 + 19 + 11 * j), ln, INK, 9, False)
        if foot:
            text(d, (x0 + 8, y1 - 17), foot, DIM, 9, False)

    def render(self, now):
        im = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        if self.phase != 'open':
            return im
        if self.kind == 'legend':
            return self._render_legend(im, d, now)
        name, title, body, col = self.steps[self.i]
        r = self.card_rect()
        tx = self.target_x(name)
        if tx is not None:
            self._arrow(d, (r[0] + r[2]) // 2, r[3] - 1, int(tx), col)
        if name == 'plates' and self.plates_note:
            body = body + [self.plates_note]
        self._card(d, r, title, body, col, foot=f'{self.i + 1} / {len(self.steps)}')
        for key, (bx0, by0, bx1, by1) in self.buttons().items():
            on = self.hover == key
            lab = ('Got it' if self.i + 1 >= len(self.steps) else 'Next >') if key == 'next' else 'Skip'
            fill = (col if key == 'next' else (60, 60, 72)) + (255,)
            d.rounded_rectangle([bx0, by0, bx1, by1], 3, fill=fill if (on or key == 'next') else (40, 40, 48, 255),
                                outline=(150, 150, 166, 255))
            ink = (20, 20, 26) if key == 'next' else INK
            text(d, (bx0 + (bx1 - bx0 - int(d.textlength(lab, font=font(9, True)))) // 2, by0 + 1), lab, ink, 9)
        left = max(0.0, STEP_S - (now - self.t_step))
        d.rectangle([r[0] + 8, r[3] - 3, r[0] + 8 + int((r[2] - r[0] - 16) * left / STEP_S), r[3] - 3], fill=col + (140,))
        return im

    def _legend_boxes(self):
        out = {}
        w, h = 168, 30
        for j, (name, title, body, col) in enumerate(self.steps):
            tx = self.target_x(name)
            if tx is None:
                continue
            x = int(max(2, min(self.W - w - 2, tx - w / 2)))
            out[name] = (x, 30, x + w, 30 + h)
        names = list(out)                                              # keep the three labels from overlapping
        names.sort(key=lambda n: out[n][0])
        for a, b in zip(names, names[1:]):
            if out[b][0] < out[a][2] + 4:
                shift = out[a][2] + 4 - out[b][0]
                x0, y0, x1, y1 = out[b]
                out[b] = (x0 + shift, y0, x1 + shift, y1)
        f = font(9, False)
        probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        kw = int(probe.textlength(KEY_LINE, font=f)) + 16
        kx = max(2, (self.W - kw) // 2)
        out['key'] = (kx, 2, kx + kw, 24)
        return out

    def _render_legend(self, im, d, now):
        boxes = self._legend_boxes()
        lab = {'fighter': ('AI program = fighter', 'name on the plate, W-L on the board'),
               'plates': ('state word + context %', 'amber border = waiting for you'),
               'board': ('scoreboard', 'W-L · HP · Pause / Arena / Bout now')}
        for name, title, body, col in self.steps:
            if name not in boxes:
                continue
            r = boxes[name]
            tx = self.target_x(name)
            self._arrow(d, (r[0] + r[2]) // 2, r[3] - 1, int(tx), col)
            d.rounded_rectangle([r[0], r[1], r[2] - 1, r[3] - 1], 4, fill=BG, outline=col + (255,))
            t1, t2 = lab[name]
            if name == 'plates' and self.plates_note:
                t2 = self.plates_note
            text(d, (r[0] + 6, r[1] + 2), t1, col, 9)
            text(d, (r[0] + 6, r[1] + 15), t2, INK, 9, False)
        k = boxes['key']
        d.rounded_rectangle([k[0], k[1], k[2] - 1, k[3] - 1], 4, fill=BG, outline=EDGE)
        text(d, (k[0] + 8, k[1] + 4), KEY_LINE, INK, 9, False)
        left = max(0.0, LEGEND_S - (now - self.t0))
        d.rectangle([k[0] + 6, k[3] - 3, k[0] + 6 + int((k[2] - k[0] - 12) * left / LEGEND_S), k[3] - 3], fill=GOLD + (200,))
        return im
