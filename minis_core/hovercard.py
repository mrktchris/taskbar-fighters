"""The hover card (UX item 5): rest the mouse on a fighter or its plate for a moment and a small card says, in plain words,
what that program is doing - "working · 3 min", "waiting for you · 1 min 37 s", "context 77%", "usage limit, resets in
1h", its record and how it stands against the fighter it is facing.  It goes away when the mouse leaves.

Only the program's name, state words and numbers appear: never a prompt, a window title or a file name.  The card is a
click-through window that never takes focus (minis_win/card_window.py shows it; the fighter process owns it).
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from .render import font, text, AMBER, RED

DWELL_S, LEAVE_S = 0.6, 0.25
W = 178
BG, INK, DIM = (16, 16, 22, 244), (236, 236, 244), (165, 165, 180)
STATE_COL = {'working': (150, 220, 150), 'waiting': AMBER, 'done': (255, 214, 92), 'idle': (190, 190, 205), 'sleeping': (150, 150, 165),
             'limit': RED}


def dur(seconds) -> str:
    """52 -> '52 s', 97 -> '1 min 37 s', 600 -> '10 min', 7300 -> '2 h 1 min', 90000 -> '1 day'."""
    s = max(0, int(seconds or 0))
    if s < 60:
        return f'{s} s'
    m, s = divmod(s, 60)
    if m < 10:
        return f'{m} min {s} s' if s else f'{m} min'
    if m < 60:
        return f'{m} min'
    h, m = divmod(m, 60)
    if h < 24:
        return f'{h} h {m} min' if m else f'{h} h'
    d = h // 24
    return f'{d} day' + ('s' if d > 1 else '')


def lines(info) -> list:
    """info: name, state, since_s (seconds in this state), ctx, plan_pct, plan_label, resets_in, waiting_s (cfg), dormant,
    bot, record (w, l) | None, opponent (label) | None, h2h (w, l) | None, rival_in (s) | None, rival_kind, flag (bool).
    -> [(text, colour, bold)] - the first line is the program name."""
    st = info.get('state') or 'sleeping'
    since = info.get('since_s')
    out = [(str(info.get('name') or '?'), tuple(info.get('accent') or INK), True)]
    if info.get('bot'):
        out.append(('the sparring bot: it stands in when only one AI program is in use', DIM, False))
    elif st == 'working':
        out.append(('working' + (f' · {dur(since)}' if since is not None else ''), STATE_COL['working'], False))
    elif st == 'waiting':
        unanswered = (since or 0) + float(info.get('waiting_s') or 45)
        out.append((f'waiting for you · {dur(unanswered)}', AMBER, True))
        out.append(('a tool call is waiting for your answer', DIM, False))
    elif st == 'done':
        out.append(('just finished a task', STATE_COL['done'], False))
    elif st == 'limit':
        r = info.get('resets_in')
        out.append(((f'usage limit, resets in {r}' if r else 'at its context limit'), RED, True))
    elif st == 'idle':
        out.append(('idle' + (f' · {dur(since)}' if since is not None else ''), STATE_COL['idle'], False))
    else:
        out.append((('not running · asleep' if info.get('dormant') else 'asleep') + (f' · {dur(since)}' if since and since > 60 else ''),
                    STATE_COL['sleeping'], False))
    if info.get('flag'):
        out.append(('task done: the flag goes away now', STATE_COL['done'], False))
    ctx = info.get('ctx')
    if not info.get('bot'):
        if ctx is None:
            out.append(('context: no numbers for this program' if info.get('process') else 'context unknown', DIM, False))
        else:
            c = int(round(ctx))
            col = RED if c >= 90 else (AMBER if c >= 70 else INK)
            out.append((f'context {c}%' + (' · near its limit' if 85 <= c < 90 else ''), col, False))
        if info.get('plan_pct') is not None:
            pl = f"{info.get('plan_label') or 'plan'} {int(round(info['plan_pct']))}%"
            if info.get('resets_in') and st != 'limit':
                pl += f" · resets in {info['resets_in']}"
            out.append((pl, INK, False))
    if info.get('rival_in') is not None and st == 'sleeping':
        what = 'rival bout' if info.get('rival_kind') == 'clash' else 'rival match'
        out.append((f"{what} in ~{rival_minutes(info['rival_in'])}", (140, 190, 255), False))
    rec = info.get('record')
    if rec is not None:
        s = f'record {rec[0]}-{rec[1]}'
        opp, hh = info.get('opponent'), info.get('h2h')
        if opp and hh and (hh[0] or hh[1]):
            s += f' · vs {opp} {hh[0]}-{hh[1]}'
        elif opp:
            s += f' · facing {opp}'
        out.append((s, DIM, False))
    if info.get('learned'):                                   # learning.summary_line: 'learned 3 moves'
        out.append((str(info['learned']), (150, 236, 160), False))
    return out


def rival_minutes(seconds) -> str:
    s = max(0.0, float(seconds or 0))
    if s < 45:
        return '1 min' if s > 5 else 'a moment'
    m = int(round(s / 60.0))
    return f'{m} min' if m < 60 else dur(s)


def _wrap(d, s, f, maxw):
    words, out, cur = s.split(' '), [], ''
    for w in words:
        nxt = (cur + ' ' + w).strip()
        if d.textlength(nxt, font=f) <= maxw or not cur:
            cur = nxt
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


_cache = {}


def render(info, k=1) -> Image.Image:
    """The card image (logical px; k = HUD density, 2 on a Retina Mac)."""
    key = (tuple(sorted((a, str(b)) for a, b in info.items())), k)
    im = _cache.get(key)
    if im is not None:
        return im
    if len(_cache) > 64:
        _cache.clear()
    from .render import canvas
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    rows = []
    for i, (s, col, bold) in enumerate(lines(info)):
        f = font(11 if i == 0 else 9, True if i == 0 else bold)
        for part in _wrap(probe, s, f, W - 16):
            rows.append((part, col, i == 0, bold))
    h = 8 + sum(14 if first else 11 for _, _, first, _ in rows) + 4
    im, d = canvas(W, h, k)
    accent = tuple(info.get('accent') or (140, 140, 160))
    border = AMBER if info.get('state') == 'waiting' else accent
    d.rounded_rectangle([0, 0, W - 1, h - 1], 5, fill=BG if k == 1 else BG[:3] + (250,), outline=border + (255,),
                        width=2 if info.get('state') == 'waiting' else 1)
    y = 4
    for s, col, first, bold in rows:
        if first:
            dot = STATE_COL.get(info.get('state') or 'sleeping', DIM)
            d.rectangle([W - 14, y + 4, W - 9, y + 9], fill=dot + (255,))
            text(d, (7, y), s, col, 11)
            y += 14
        else:
            text(d, (8, y), s, col, 9, bold)
            y += 11
    _cache[key] = im
    return im


class Dwell:
    """Hover timing: inside for DWELL_S -> show; outside for LEAVE_S -> hide.  update(inside, now) -> visible."""

    def __init__(self, dwell=DWELL_S, leave=LEAVE_S):
        self.dwell, self.leave = dwell, leave
        self.enter_t = None
        self.leave_t = None
        self.visible = False
        self.target = None

    def update(self, target, now):
        """target: what the mouse is over ('fighter' | 'plate' | None)."""
        if target is not None:
            self.leave_t = None
            if self.enter_t is None:
                self.enter_t = now
            self.target = target
            if not self.visible and now - self.enter_t >= self.dwell:
                self.visible = True
        else:
            self.enter_t = None
            if self.visible:
                if self.leave_t is None:
                    self.leave_t = now
                if now - self.leave_t >= self.leave:
                    self.visible = False
                    self.target = None
            else:
                self.target = None
        return self.visible


def place(target_rect, card_w, card_h, screen_w, below=False, margin=4):
    """(x, y) screen px of a card over (or, `below`, under) target_rect = (l, t, r, b), centred on it, kept on screen."""
    l, t, r, b = target_rect
    x = int((l + r) / 2 - card_w / 2)
    x = max(margin, min(int(screen_w) - card_w - margin, x))
    y = int(b + margin) if below else int(t - card_h - margin)
    return x, max(margin, y)
