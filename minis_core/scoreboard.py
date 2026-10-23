"""The right-side taskbar widget (scoreboard): pure layout + rendering + hit-testing.  The director process hosts it
in a third layered window (minis.py Scoreboard) just left of the centred icon cluster.

Row 1  "Claude 3-1  vs  Codex 1-3": short program labels (never truncated with a dot) and W-L per PROGRAM; a click on a
       name opens the fighter-select screen for that side (the small caret says so).
Row 2  during a bout: two readable HP bars and the round score; for a few seconds after a match a plain result line
       ("CLAUDE WINS 2-1"); otherwise the 7-day context sparkline and one status word (paused / arena / hidden 52m + show).
Row 3  three 20 px buttons: Pause/Resume, Arena/Exit arena, Bout now.
Only the names, the buttons and a visible "show" are solid to the mouse (hit()); everything else is click-through.
Numbers, short program names and enums only: never window titles or content.
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from .render import canvas, font, text, TRACK, AMBER, RED

W, H = 190, 44
BTN_Y0, BTN_Y1 = 23, 42                                   # 20 px tall at scale 1 (a 48 px taskbar band)
BUTTONS = (('pause', (3, BTN_Y0, 63, BTN_Y1)), ('arena', (66, BTN_Y0, 124, BTN_Y1)), ('bout', (127, BTN_Y0, 187, BTN_Y1)))
NAMES = (('name_a', (2, 0, 90, 13)), ('name_b', (100, 0, 188, 13)))
SHOW = (150, 12, 188, 21)                                  # the "show" link next to "hidden 52m" (solid only while shown)
ROW2_Y0, ROW2_Y1 = 14, 21                                  # HP bars: 8 px tall
BAR_W = 78
SPARK_X, SPARK_PITCH = 40, 5                              # the 7-day sparkline: first bar x, bar pitch
BG, EDGE, INK, DIM = (18, 18, 22, 215), (90, 90, 104, 190), (230, 230, 240), (160, 160, 175)
BTN_BG, BTN_EDGE, BTN_ON = (40, 40, 48, 255), (120, 120, 136, 255), (70, 70, 84, 255)
GREEN, GOLD, LINK = (150, 220, 150), (255, 214, 92), (140, 190, 255)
MODE_COLOR = {'taskbar': GREEN, 'arena': (255, 196, 80), 'paused': (255, 120, 110)}


def left_x(cfg) -> int:
    """Screen x of the widget: cfg['scoreboard_x'], else just left of the icon cluster (zone end + 36, i.e. x 936 here)."""
    v = cfg.get('scoreboard_x')
    if v is None:
        v = int(cfg['zone'][1]) + 36 - W
    return int(v)


def enabled(cfg) -> bool:
    return bool(cfg.get('scoreboard', True))


def _in(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def hit(x, y, state=None):
    """-> 'pause' | 'arena' | 'bout' | 'name_a' | 'name_b' | 'show' under client point (x, y) in logical px, or None
    (click-through).  'show' only exists while a fighter is hidden (needs `state`)."""
    for name, r in BUTTONS + NAMES:
        if _in(r, x, y):
            return name
    if state and state.get('hidden') and _in(SHOW, x, y) and state.get('hp') is None and not state.get('result'):
        return 'show'
    return None


def labels(state):
    paused = state.get('mode') == 'paused' or state.get('paused')
    return {'pause': 'Resume' if paused else 'Pause', 'arena': 'Exit arena' if state.get('arena') else 'Arena', 'bout': 'Bout now'}


def _fit(d, s, maxw, size, bold=True):
    """Last resort only (labels are short by design): cut whole characters, no trailing dot."""
    f = font(size, bold)
    while len(s) > 1 and d.textlength(s, font=f) > maxw:
        s = s[:-1]
    return s


def hidden_text(hidden) -> str:
    """{'b': 3120.0} -> 'B hidden 52m'; inf -> 'hidden'; both -> 'both hidden'."""
    if not hidden:
        return ''
    who = 'both' if len(hidden) == 2 else next(iter(hidden)).upper()
    left = min(hidden.values())
    if left == float('inf'):
        return f'{who} hidden'
    m = max(1, int(left // 60 + (1 if left % 60 else 0)))
    return f'{who} hidden {m // 60}h{m % 60:02d}' if m >= 60 else f'{who} hidden {m}m'


_cache = {}


def signature(state):
    hp = state.get('hp') or {}
    hid = tuple(sorted((k, -1 if v == float('inf') else int(v // 60)) for k, v in (state.get('hidden') or {}).items()))
    return (tuple(state.get('names', {}).get(s) for s in 'ab'), tuple(tuple(state.get('records', {}).get(s, (0, 0))) for s in 'ab'),
            state.get('mode'), bool(state.get('arena')), bool(state.get('paused')), hp.get('a'), hp.get('b'),
            tuple(sorted((state.get('wins') or {}).items())), state.get('pressed'), state.get('result'), hid,
            tuple(None if v is None else int(v) for v in (state.get('spark') or ())), state.get('toast'))


def render(state, k=1) -> Image.Image:
    """state: names {a,b}, records {a: (w, l), b: (w, l)}, mode, arena, paused, hp {a, b} | None, wins {a, b}, pressed,
    result (str | None), hidden {slot: seconds left | inf}, spark [7 values | None], toast (str | None: an achievement
    just unlocked, shown for 3 s in row 2 ahead of the result line; growth).
    k: pixel density (1 everywhere but a macOS Retina screen: drawn 2x and nearly opaque; the layout is the same)."""
    key = signature(state) + ((k,) if k > 1 else ())
    im = _cache.get(key)
    if im is None:
        if len(_cache) > 64:
            _cache.clear()
        im = _cache[key] = _render(state, k)
    return im


def _star(d, x, y, col):
    """A 9 px five-point star at (x, y) (top-left): the toast's badge mark, drawn (a font may lack the glyph)."""
    import math
    pts = []
    for i in range(10):
        r = 4.5 if i % 2 == 0 else 1.9
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((x + 4.5 + r * math.cos(a), y + 4.8 + r * math.sin(a)))
    d.polygon(pts, fill=col)


def _caret(d, x, y, col):
    d.polygon([(x, y), (x + 4, y), (x + 2, y + 2)], fill=col)


def _render(state, k=1):
    im, d = canvas(W, H, k)
    d.rounded_rectangle([0, 0, W - 1, H - 1], 5, fill=BG if k == 1 else BG[:3] + (242,), outline=EDGE)
    names = state.get('names') or {}
    recs = state.get('records') or {}
    hp = state.get('hp') or {}
    wins = state.get('wins') or {}
    fb, fr = font(10, True), font(9, False)
    # row 1: clickable names + records
    for slot, (x0, _, x1, _) in (('a', NAMES[0][1]), ('b', NAMES[1][1])):
        nm = names.get(slot) or '-'
        w, l = recs.get(slot, (0, 0))
        rec = f' {w}-{l}'
        room = x1 - x0 - 8 - int(d.textlength(rec, font=fr))
        nm = _fit(d, nm, room, 10, True)
        nw = int(d.textlength(nm, font=fb))
        total = nw + int(d.textlength(rec, font=fr)) + 7
        sx = x0 + 2 if slot == 'a' else x1 - total
        text(d, (sx, 0), nm, INK, 10)
        text(d, (sx + nw, 1), rec, DIM, 9, False)
        _caret(d, sx + total - 5, 6, DIM + (255,))
    vs = 'vs'
    text(d, (W // 2 - int(d.textlength(vs, font=fr)) // 2, 1), vs, DIM, 9, False)
    # row 2
    mode = state.get('mode') or 'taskbar'
    if hp.get('a') is not None or hp.get('b') is not None:
        for slot, x0, flip in (('a', 4, False), ('b', W - 4 - BAR_W, True)):
            v = hp.get(slot)
            v = 0 if v is None else max(0, min(100, int(v)))
            fill = GREEN if v > 50 else (AMBER if v > 25 else RED)
            d.rectangle([x0, ROW2_Y0, x0 + BAR_W, ROW2_Y1], fill=TRACK + (255,), outline=(90, 90, 104, 255))
            w = int((BAR_W - 1) * v / 100.0)
            if w:
                if flip:
                    d.rectangle([x0 + BAR_W - w, ROW2_Y0 + 1, x0 + BAR_W - 1, ROW2_Y1 - 1], fill=fill + (255,))
                else:
                    d.rectangle([x0 + 1, ROW2_Y0 + 1, x0 + w, ROW2_Y1 - 1], fill=fill + (255,))
        rnd = f"{wins.get('a', 0)}-{wins.get('b', 0)}"
        text(d, (W // 2 - int(d.textlength(rnd, font=fb)) // 2, 11), rnd, MODE_COLOR['arena'], 10)
    elif state.get('toast'):                                   # growth: an achievement just unlocked (achievements.Toaster)
        t = state['toast']                                     # learning.ToastSlot: (kind, text); a bare string is a badge
        kind, msg = t if isinstance(t, (tuple, list)) and len(t) == 2 else ('unlocked', t)
        if kind == 'learned':                                  # learning.py: a fighter taught itself a move
            col = (150, 236, 160)
            d.rectangle([7, 13, 13, 19], fill=col + (255,))
            lab = 'LEARNED'
        else:
            col = GOLD
            _star(d, 6, 11, GOLD + (255,))
            lab = 'UNLOCKED'
        text(d, (17, 12), lab, DIM, 9, False)
        x = 17 + int(d.textlength(lab, font=fr)) + 5
        s = _fit(d, str(msg), W - x - 5, 10, True)
        text(d, (x, 11), s, col, 10)
    elif state.get('result'):
        s = _fit(d, state['result'], W - 10, 10, True)
        text(d, (W // 2 - int(d.textlength(s, font=fb)) // 2, 11), s, GOLD, 10)
    else:
        spark = list(state.get('spark') or [])
        x = 5
        if spark:                                              # 7-day context sparkline (history.json: numbers + dates only)
            text(d, (x, 12), '7 days', DIM, 9, False)
            for i, v in enumerate(spark[-7:]):
                bx = SPARK_X + i * SPARK_PITCH
                d.rectangle([bx, 14, bx + 3, 21], fill=TRACK + (255,))
                if v is not None:
                    h = max(1, int(round(8 * max(0.0, min(100.0, float(v))) / 100.0)))
                    col = GREEN if v < 70 else (AMBER if v < 90 else RED)
                    d.rectangle([bx, 22 - h, bx + 3, 21], fill=col + (255,))
        hid = state.get('hidden') or {}
        if hid:
            word = hidden_text(hid)
            text(d, (SHOW[0] - 4 - int(d.textlength(word, font=fr)), 12), word, DIM, 9, False)
            d.rounded_rectangle([SHOW[0], SHOW[1] + 1, SHOW[2], SHOW[3]], 2, outline=LINK + (255,))
            text(d, (SHOW[0] + (SHOW[2] - SHOW[0] - int(d.textlength('show', font=font(9, True)))) // 2 + 1, 12), 'show', LINK, 9, True)
        elif mode in ('paused', 'arena'):
            word = {'paused': 'paused', 'arena': 'arena on'}[mode]
            text(d, (W - 6 - int(d.textlength(word, font=fb)), 11), word, MODE_COLOR[mode], 10)
        else:
            hint = 'click a name to pick'
            text(d, (W - 6 - int(d.textlength(hint, font=fr)), 12), hint, (120, 120, 134), 9, False)
    # row 3: buttons
    lab = labels(state)
    for name, (x0, y0, x1, y1) in BUTTONS:
        on = state.get('pressed') == name
        d.rounded_rectangle([x0, y0, x1, y1], 4, fill=BTN_ON if on else BTN_BG, outline=BTN_EDGE)
        s = _fit(d, lab[name], x1 - x0 - 6, 10)
        text(d, (x0 + (x1 - x0 - int(d.textlength(s, font=fb))) // 2, y0 + 3), s, INK, 10)
    return im


class Model:
    """Builds the render state from plain inputs: assignment, bus payloads, record.json, control flags."""

    def __init__(self, cfg):
        self.cfg = cfg

    @staticmethod
    def names_from(assign, lib=None):
        from .sources import short_label
        out = {}
        for s in 'ab':
            a = (assign or {}).get(s) if isinstance(assign, dict) else None
            out[s] = short_label(a.get('source'), a.get('program')) if isinstance(a, dict) and a.get('source') else None
        return out

    @staticmethod
    def result_line(assign, record, now):
        """'CLAUDE WINS 2-1' for a match that ended in the last few seconds, else None."""
        from . import records
        from .sources import short_label
        last = records.last_result(record, now) if now is not None else None
        if not last:
            return None
        sc = last.get('score')
        tail = f' {sc[0]}-{sc[1]}' if isinstance(sc, list) and len(sc) == 2 else ''
        return f"{short_label(last['winner']).upper()} WINS{tail}"

    @staticmethod
    def state(assign, buses, record, paused, arena, winners, pressed=None, spark=None, now=None, hidden=None, toast=None):
        from . import records
        names = Model.names_from(assign)
        rec = record if isinstance((record or {}).get('programs'), dict) else dict(record or {}, programs=records.migrate((record or {}).get('characters')))
        srcs = {s: ((assign or {}).get(s) or {}).get('source') if isinstance((assign or {}).get(s), dict) else None for s in 'ab'}
        recs = {s: records.for_program(rec, srcs[s]) if srcs[s] else (0, 0) for s in 'ab'}
        hp = {}
        wins = {}
        for s in 'ab':
            b = (buses or {}).get(s) or {}
            if b.get('hp') is not None:
                hp[s] = b.get('hp')
            if isinstance(b.get('wins'), dict):
                wins = {k: int(v) for k, v in b['wins'].items() if k in 'ab'}
        mode = 'paused' if paused else ('arena' if arena else 'taskbar')
        return dict(names=names, records=recs, mode=mode, arena=bool(arena), paused=bool(paused), hp=hp or None, wins=wins,
                    winners=winners, pressed=pressed, spark=list(spark) if spark else None,
                    result=None if hp else Model.result_line(assign, rec, now), hidden=dict(hidden or {}),
                    toast=None if hp else toast)
