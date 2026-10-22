r"""Instant replay, fight codes and GIF export (UX item 7).  Everything here is offline: a match is a pure function of its
plan (seed, the two characters, positions, odds, boost) and the art on disk, so the last match can be played again - on a
small window above the taskbar or into a GIF - by running the same planner on a neutral backdrop.  No screen capture.

replay.json in the data folder (numbers and ids only - never names of files, titles or content):
  {"matches": [{"id", "ts", "plan": {...}, "programs": {slot: source id}, "labels": {slot: short label},
                "winner": slot, "loser": slot, "wins": {slot: n}, "stats": {...}, "code"}, ...],   newest last, at most KEEP
   "h2h": {"<source>|<source>": [wins of the first, wins of the second]}}                     head-to-head per program pair
The plan's `scores` (the health weights behind `decided` mode) are kept here so the replay is exact; a fight code carries
only their ratio (the odds), never a context or state number.

Fight code: TF2-<char a>-<char b>-<base32 payload>, e.g. TF2-claude-codex-0g7d2k9x4m... (a hyphen inside an id is written as a dot)  The payload holds: format
version, which slot stood left, the seed, the odds as a reduced ratio, both positions (1/256 px), the span, the boost
flags and the outcome (to say when a different engine version would play the code differently).  `minis.py replay CODE`
plays it; anyone with the app can paste it.

ENGINE: bump it when the choreography (rounds.py / choreo.py / setpieces.py) changes what a plan produces, so an old code
is reported as made by an older engine instead of silently playing a different fight.
"""
from __future__ import annotations
import json, math, os, random, sys, time
from pathlib import Path

from . import config as cfgmod
from .bus import write_json_atomic

KEEP = 12
ENGINE = 1
CODE_PREFIX = 'TF2'                      # TF1 wrote the ids as plain hyphen fields; TF2 escapes a '-' inside an id as '.'
ID_RE = __import__('re').compile(r'^(?=.{1,40}$)[a-z0-9_]+(-[a-z0-9_]+)*$')   # a fighter / pack id (`pack-shadow-ronin`): hyphens
                                                                             # only between words, so '.' / '..' never pass as ids
B32 = '0123456789abcdefghjkmnpqrstvwxyz'                 # Crockford base32, lower case (no i, l, o, u)
PLAN_KEYS = ('kind', 'left', 'right', 'pos', 't0', 'seed', 'chars', 'span', 'boost', 'mode', 'scores')


def path() -> Path:
    return cfgmod.data_dir() / 'replay.json'


def read(p=None) -> dict:
    p = Path(p) if p else path()
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(d, dict):
            d.setdefault('matches', [])
            d.setdefault('h2h', {})
            if isinstance(d['matches'], list) and isinstance(d['h2h'], dict):
                return d
    except (OSError, ValueError):
        pass
    return {'matches': [], 'h2h': {}}


def clean_plan(plan) -> dict:
    """Only what the match planner reads (numbers, slot ids, character ids): never `rival` / `demo` / deadlines / ids."""
    out = {}
    for k in PLAN_KEYS:
        if k in (plan or {}):
            v = plan[k]
            if k in ('pos', 'scores', 'chars') and isinstance(v, dict):
                v = {str(s): (float(x) if k != 'chars' else str(x)) for s, x in v.items() if s in ('a', 'b')}
            elif k == 'boost':
                v = [s for s in (v or ()) if s in ('a', 'b')]
            out[k] = v
    out['kind'] = 'match'
    return out


# ---------------------------------------------------------------- stats of a match (from the planner's own summary)
def stats_of(summary) -> dict:
    """{'hits', 'best_combo', 'ultimate', 'pieces', 'rounds', 'ko'} from rounds.make_match's summary.  A combo is the longest
    run of landed attacks by one fighter inside one exchange (an approach move, a miss, a block or a defender's beat ends it)."""
    beats = (summary or {}).get('beats') or {}
    hits, best, ult = 0, 0, False
    for slot, lst in beats.items():
        run = 0
        for b in lst or ():
            if not isinstance(b, dict):
                continue
            landed = b.get('who') == 'att' and b.get('outcome') == 'hit' and b.get('kind') != 'move'
            if landed:
                hits += 1
                run += 1
                best = max(best, run)
                if b.get('kind') == 'ultimate' or (b.get('dmg') or 0) >= 40:
                    ult = True
            elif b.get('kind') == 'move' or b.get('who') == 'dfn' or b.get('outcome') in ('block', 'whiff', 'parry', 'clash'):
                run = 0
    story = (summary or {}).get('story') or {}
    rounds = (summary or {}).get('rounds') or []
    return dict(hits=int(hits), best_combo=int(best), ultimate=bool(ult), pieces=[str(p) for p in story.get('pieces') or []],
                rounds=len(rounds), ko=bool((summary or {}).get('final_ko')))


def result_line(entry, upper=True) -> str:
    """'CLAUDE WINS 2-1 · 23 hits · best combo 5 · ultimate landed' (the results strip and the CLI)."""
    st = entry.get('stats') or {}
    w = entry.get('winner')
    name = (entry.get('labels') or {}).get(w) or (entry.get('plan', {}).get('chars') or {}).get(w) or '?'
    wins = entry.get('wins') or {}
    sc = sorted((int(v) for v in wins.values()), reverse=True)
    head = f"{name.upper() if upper else name} WINS" + (f' {sc[0]}-{sc[1]}' if len(sc) == 2 else '')
    bits = [f"{st.get('hits', 0)} hits"]
    if st.get('best_combo', 0) >= 2:
        bits.append(f"best combo {st['best_combo']}")
    if st.get('ultimate'):
        bits.append('ultimate landed')
    return ' · '.join([head] + bits)


# ---------------------------------------------------------------- storing a finished match
def pair_key(x, y):
    return '|'.join(sorted((str(x), str(y))))


def store(plan, summary, programs, labels=None, now=None, p=None) -> dict | None:
    """Keep the match that just ended (the fighter that writes record.json calls this).  -> the stored entry, or None."""
    if not isinstance(plan, dict) or plan.get('kind') != 'match' or not isinstance(summary, dict) or not summary.get('winner'):
        return None
    now = time.time() if now is None else now
    d = read(p)
    win, lose = summary['winner'], summary['loser']
    cp = clean_plan(plan)
    entry = dict(id='%x' % int(now * 1000), ts=float(now), plan=cp, programs={s: str(v) for s, v in (programs or {}).items() if v},
                 labels={s: str(v) for s, v in (labels or {}).items() if v}, winner=win, loser=lose,
                 wins={s: int(v) for s, v in (summary.get('wins') or {}).items()}, stats=stats_of(summary))
    try:
        entry['code'] = encode(cp, summary)
    except Exception:
        entry['code'] = None
    d['matches'] = (d['matches'] + [entry])[-KEEP:]
    pw, pl = entry['programs'].get(win), entry['programs'].get(lose)
    if pw and pl and pw != pl:
        k = pair_key(pw, pl)
        cur = d['h2h'].get(k) if isinstance(d['h2h'].get(k), list) and len(d['h2h'].get(k)) == 2 else [0, 0]
        first = sorted((pw, pl))[0]
        cur = [int(cur[0]) + (1 if pw == first else 0), int(cur[1]) + (0 if pw == first else 1)]
        d['h2h'][k] = cur
    return entry if write_json_atomic(Path(p) if p else path(), d) else None


def last(p=None):
    m = read(p)['matches']
    return m[-1] if m else None


def h2h(mine, theirs, p=None) -> tuple:
    """-> (my wins, their wins) between two programs, from the replay history."""
    if not mine or not theirs or mine == theirs:
        return 0, 0
    v = read(p)['h2h'].get(pair_key(mine, theirs))
    if not isinstance(v, list) or len(v) != 2:
        return 0, 0
    first = sorted((mine, theirs))[0]
    return (int(v[0]), int(v[1])) if mine == first else (int(v[1]), int(v[0]))


# ---------------------------------------------------------------- fight codes
def _varint(n):
    n = int(n)
    if n < 0:
        raise ValueError('negative')
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varint(buf, i):
    n = shift = 0
    while True:
        if i >= len(buf):
            raise ValueError('truncated')
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n, i
        if shift > 63:
            raise ValueError('too long')


def _b32(data: bytes) -> str:
    n, bits, out = 0, 0, []
    for byte in data:
        n = (n << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(B32[(n >> bits) & 31])
    if bits:
        out.append(B32[(n << (5 - bits)) & 31])
    return ''.join(out)


def _unb32(s: str) -> bytes:
    n, bits, out = 0, 0, bytearray()
    for ch in s.lower():
        ch = {'o': '0', 'i': '1', 'l': '1'}.get(ch, ch)
        v = B32.find(ch)
        if v < 0:
            raise ValueError(f'not a fight code character: {ch!r}')
        n = (n << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((n >> bits) & 0xFF)
    return bytes(out)


def _odds(plan):
    """The `decided` odds as a reduced integer ratio of the two health weights (or None for an even match)."""
    sc = plan.get('scores') or {}
    l, r = plan['left'], plan['right']
    try:
        a, b = int(round(float(sc.get(l, 0)) * 10)), int(round(float(sc.get(r, 0)) * 10))
    except (TypeError, ValueError):
        return None
    if a < 0 or b < 0 or a + b <= 0 or a == b:
        return None
    g = math.gcd(a, b)
    return a // g, b // g


def encode(plan, summary=None) -> str:
    chars = plan['chars']
    for c in (chars['a'], chars['b']):
        if not ID_RE.match(str(c)):
            raise ValueError('character id')
    odds = _odds(plan) if plan.get('mode', 'decided') == 'decided' else None
    flags = ((1 if plan['left'] == 'b' else 0) | (2 if plan.get('mode') == 'random' else 0) | (4 if odds else 0)
             | (8 if 'a' in (plan.get('boost') or ()) else 0) | (16 if 'b' in (plan.get('boost') or ()) else 0))
    body = bytearray([ENGINE, flags])
    body += _varint(plan['seed'])
    if odds:
        body += _varint(odds[0]) + _varint(odds[1])
    for s in ('a', 'b'):
        body += _varint(int(round(float(plan['pos'][s]) * 256)))
    body += _varint(int(round(float(plan.get('span', 110.0)) * 1000)))
    out = 0xFF
    if summary and summary.get('winner') in ('a', 'b'):
        w = summary.get('wins') or {}
        out = (0 if summary['winner'] == 'a' else 1) | (min(3, int(w.get('a', 0))) << 1) | (min(3, int(w.get('b', 0))) << 3)
    body.append(out)
    body.append(sum(body) & 0xFF)
    return f"{CODE_PREFIX}-{id_out(chars['a'])}-{id_out(chars['b'])}-{_b32(bytes(body))}"


def id_out(cid):
    return str(cid).replace('-', '.')


def id_in(field):
    """A code's id field -> the id, checked against ID_RE (a path separator, a dot that is not an escaped hyphen, an
    upper-case letter or anything over 40 characters is refused: the id names a folder and a file)."""
    cid = str(field).replace('.', '-')
    if not ID_RE.match(cid):
        raise CodeError(f'not a fighter id: {field!r}')
    return cid


class CodeError(ValueError):
    pass


def decode(code) -> tuple:
    """-> (plan, expected outcome {'winner', 'wins'} | None, engine version).  Raises CodeError with a plain reason."""
    parts = str(code or '').strip().split('-')
    if len(parts) == 4 and parts[0].upper() == 'TF1':
        raise CodeError('a TF1 code is from an earlier build; this one reads TF2 codes')
    if len(parts) != 4 or parts[0].upper() != CODE_PREFIX:
        raise CodeError('a fight code looks like TF2-<fighter>-<fighter>-<code>')
    _, ca, cb, payload = parts
    ca, cb = id_in(ca), id_in(cb)
    try:
        buf = _unb32(payload)
    except ValueError as e:
        raise CodeError(str(e)) from None
    if len(buf) < 6 or (sum(buf[:-1]) & 0xFF) != buf[-1]:
        raise CodeError('this fight code is damaged (check every character)')
    try:
        ver, flags = buf[0], buf[1]
        i = 2
        seed, i = _read_varint(buf, i)
        scores = None
        if flags & 4:
            n, i = _read_varint(buf, i)
            m, i = _read_varint(buf, i)
            scores = (n, m)
        pa, i = _read_varint(buf, i)
        pb, i = _read_varint(buf, i)
        span, i = _read_varint(buf, i)
        outb = buf[i]
    except (ValueError, IndexError):
        raise CodeError('this fight code is damaged (check every character)') from None
    left = 'b' if flags & 1 else 'a'
    right = 'a' if left == 'b' else 'b'
    plan = dict(kind='match', left=left, right=right, pos={'a': pa / 256.0, 'b': pb / 256.0}, t0=0.0, seed=int(seed),
                chars={'a': ca, 'b': cb}, span=span / 1000.0, mode='random' if flags & 2 else 'decided',
                boost=[s for s, bit in (('a', 8), ('b', 16)) if flags & bit])
    plan['scores'] = {left: float(scores[0]), right: float(scores[1])} if scores else {left: 1.0, right: 1.0}
    expect = None if outb == 0xFF else dict(winner='b' if outb & 1 else 'a', wins={'a': (outb >> 1) & 3, 'b': (outb >> 3) & 3})
    return plan, expect, int(ver)


# ---------------------------------------------------------------- the planner, offline
def summarize(plan, lib=None):
    """Run the match planner on a plan: -> (t_end, summary).  Cheap (no drawing)."""
    from . import brain as B, fx as fxmod
    from .atlas import Library
    lib = lib or Library()
    tl, t_end, _ = B.make_timeline('match', dict(plan, t0=float(plan.get('t0') or 0.0)), lib, fxmod.default())
    return t_end, getattr(B.make_timeline, 'last_summary', None) or {}


def window_of(plan, summary, part='final'):
    """(start, end) in the plan's own time for `part`: 'final' = the deciding exchange and the K.O. (about 6-9 s), 'all' =
    the whole match."""
    t0 = float(plan.get('t0') or 0.0)
    rounds = summary.get('rounds') or []
    ko = summary.get('final_ko') or {}
    t1 = float(rounds[-1]['t1']) if rounds else t0 + 20.0
    end = t1 + 3.6 if ko else t1 + 2.8
    if part == 'all':
        return t0 - 0.3, end
    if ko:
        start = max(float(rounds[-1]['t0']) if rounds else t0, float(ko['tc']) - 4.5)
    else:
        start = max(t0, t1 - 6.0)
    return start, end


# ---------------------------------------------------------------- the offline renderer
W, H = 600, 236                     # the replay frame: desktop rows + a 48 px taskbar band, room for 128 px fighters + a jump
TASKBAR = 48
DESK, BAND, LINE = (24, 26, 34, 255), (32, 32, 32, 255), (58, 58, 62, 255)
SIZE = 128


def _hd_view(v, hd, base):
    """minis.hd_view, kept here so the core does not import the CLI module: a RES 1 view mapped onto an HD atlas."""
    from PIL import Image
    m = max(1, int(round(hd.res / float(max(1, base.res)))))
    out = dict(v)
    out['x'] = v['x'] * m
    n = len(hd.anim[v['anim']]['frames'])
    out['frame'] = min(int(v['frame']), n - 1)
    out['fx'] = [(im.resize((im.width * m, im.height * m), Image.NEAREST), lx * m, ty * m) + tuple(rest) for im, lx, ty, *rest in (v.get('fx') or [])]
    if v.get('banner'):
        bim, bx = v['banner']
        out['banner'] = (bim.resize((bim.width * m, bim.height * m), Image.NEAREST), bx * m)
    sx, sy = v.get('shake') or (0, 0)
    out['shake'] = (sx * m, sy * m)
    if v.get('proj'):
        out['proj'] = dict(v['proj'], x=v['proj']['x'] * m)
    return out                                                    # `clip` stays in RES 1 px: compose scales it


def backdrop(w=W, h=H):
    """The neutral backdrop the docs use: a flat dark desktop and a Windows-11-dark taskbar band.  Nothing from a screen."""
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (w, h), DESK)
    d = ImageDraw.Draw(im)
    for y in range(h - TASKBAR):                                  # a faint vertical gradient so it does not read as a hole
        k = y / max(1, h - TASKBAR)
        c = tuple(int(DESK[i] + (30 - DESK[i]) * k * 0.35) for i in range(3)) + (255,)
        d.line([(0, y), (w, y)], fill=c)
    d.rectangle([0, h - TASKBAR, w, h - 1], fill=BAND)
    d.line([(0, h - TASKBAR), (w, h - TASKBAR)], fill=LINE)
    return im


class Renderer:
    """Plays a plan with two Brains on a fake clock (the headless simulator's way) and draws frames on the neutral backdrop.
    `flashes` follows the owner's Flash effects switch (off: no white flash or impact frame in the replay either)."""

    def __init__(self, plan, names=None, code=None, flashes=True, lib=None, hd=None, label='REPLAY'):
        from . import sim
        from .atlas import Library
        from .brain import Brain
        self.plan = dict(clean_plan(plan), t0=float(plan.get('t0') or 0.0))
        self.lib = lib or Library()
        self.hd = hd if hd is not None else Library(hd=True)
        self.names = dict(names or {})
        self.code, self.label = code, label
        cfg = dict(cfgmod.DEFAULTS)
        cfg.update({'bout_min_s': 9e6, 'bout_max_s': 9e6, 'clash_min_s': 9e6, 'clash_max_s': 9e6, 'match_min_s': 9e6,
                    'match_max_s': 9e6, 'rival': False})
        self.cfg = cfg
        pos = self.plan['pos']
        self.mid = (float(pos['a']) + float(pos['b'])) / 2.0
        zone = (self.mid - 200.0, self.mid + 200.0)
        T = self.plan['t0'] - 1.0
        self.brains = {}
        for i, s in enumerate(('a', 'b')):
            b = Brain(s, self.lib[self.plan['chars'][s]], self.lib, cfg, random.Random(7 + i), T, zone=zone, run=f'replay{s}',
                      record=lambda *a, **k: True)
            b.flashes = bool(flashes)
            b.rival = False
            b.x = b.home_x = float(pos[s])
            b.home = (b.x - 2.0, b.x + 2.0)
            b.facing = 1 if s == self.plan['left'] else -1
            self.brains[s] = b
        self.tele = {s: sim.FakeTelemetry(s, [(0, 'idle', None)], t0=T) for s in ('a', 'b')}
        self.bus = {s: b.publish() for s, b in self.brains.items()}
        for s, b in self.brains.items():
            b.partner = self.bus['b' if s == 'a' else 'a']
            b._commit('match', self.plan, T)
        self.now = T
        self.sim = sim
        self.k = 2                                                # 64 -> 128 px (the HD art)
        self.x0 = int(round(self.mid * self.k - W / 2))           # screen x of the frame's left edge (HD px)
        self._wins, self._hp = {}, {}
        self._bg = backdrop()

    def advance(self, t):
        """Step the two fighters up to plan time t (coarse steps are fine: the timeline is applied by time)."""
        while self.now < t - 1e-9:
            self.now = min(t, self.now + 0.1)
            self.sim.step(self.brains, self.tele, self.now, self.bus)

    def frame(self, t, slow=False):
        """The picture at plan time t (call with increasing t)."""
        from PIL import Image
        from . import render
        if t > self.now:
            self.now = t
            self.sim.step(self.brains, self.tele, t, self.bus)
        im = self._bg.copy()
        hr = cfgmod.headroom_px(SIZE)
        drop = cfgmod.feet_drop(SIZE)
        for s in ('a', 'b'):
            b = self.brains[s]
            v = b.view(t)
            hd = self.hd[b.character]
            if v['anim'] not in hd.anim:
                v = dict(v, anim='idle', frame=0)
            fr = render.compose_full(hd, hd, _hd_view(v, hd, b.atlas), None, t, W, self.cfg, win_x=self.x0, show_plate=False)
            y0 = H - SIZE + drop - hr
            layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            layer.paste(fr.crop((0, 0, W, min(fr.height, H - y0))), (0, y0))
            im.alpha_composite(layer)
        self._hud(im, slow)
        return im

    def _hud(self, im, slow):
        """A fighting-game HUD: names in each fighter's accent, HP bars from the match's own @hp values, round pips, the
        REPLAY tag and the fight code.  Names are short program labels or character names; no state or context numbers."""
        from PIL import ImageDraw
        from .render import font, text
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        left = self.plan['left']
        right = 'b' if left == 'a' else 'a'
        BW = 214
        for s, side in ((left, 0), (right, 1)):
            b = self.brains[s]
            if b.round and isinstance(b.round.get('wins'), dict):
                self._wins = dict(b.round['wins'])
            if b.hp is not None:
                self._hp[s] = b.hp
            name = (self.names.get(s) or b.atlas.display).upper()
            x0 = 12 if side == 0 else W - 12 - BW
            col = tuple(b.atlas.accent)
            f12 = font(12, True)
            nx = x0 if side == 0 else W - 12 - int(d.textlength(name, font=f12))
            text(d, (nx + 1, 7), name, (0, 0, 0), 12)
            text(d, (nx, 6), name, col, 12)
            d.rectangle([x0, 24, x0 + BW, 33], fill=(40, 40, 48, 255), outline=(110, 110, 126, 255))
            v = max(0, min(100, int(self._hp.get(s, 100))))
            w = int((BW - 2) * v / 100.0)
            fill = (150, 220, 150) if v > 50 else ((255, 196, 80) if v > 25 else (255, 96, 96))
            if w:
                if side == 0:
                    d.rectangle([x0 + 1, 25, x0 + w, 32], fill=fill + (255,))
                else:
                    d.rectangle([x0 + BW - w, 25, x0 + BW - 1, 32], fill=fill + (255,))
            wins = int(self._wins.get(s, 0))
            for k in range(2):
                px = x0 + (k * 12 if side == 0 else BW - 9 - k * 12)
                d.rectangle([px, 37, px + 8, 41], fill=((255, 214, 92, 255) if k < wins else (58, 58, 66, 255)))
        tag = self.label + ('  ·  SLOW MOTION' if slow else '')
        f = font(10, True)
        tw = int(d.textlength(tag, font=f))
        d.rounded_rectangle([W // 2 - tw // 2 - 7, 7, W // 2 + tw // 2 + 7, 22], 4, fill=(196, 44, 44, 240))
        text(d, (W // 2 - tw // 2, 8), tag, (255, 255, 255), 10)
        if self.code:
            f9 = font(9, False)
            text(d, (W // 2 - int(d.textlength(self.code, font=f9)) // 2, 44), self.code, (150, 152, 168), 9, False)
        foot = 'Taskbar Fighters  ·  demo render on a plain backdrop, never a screen capture'
        text(d, (10, H - 16), foot, (120, 122, 136), 9, False)


def schedule(start, end, fps, slow_from=None, slow_k=0.5):
    """Plan times for each output frame: real time until `slow_from`, then `slow_k` x speed (the K.O. in slow motion)."""
    out, t = [], start
    dt = 1.0 / fps
    while t <= end + 1e-9:
        slow = slow_from is not None and t >= slow_from
        out.append((t, slow))
        t += dt * (slow_k if slow else 1.0)
    return out


def frames(plan, part='final', fps=15, names=None, code=None, flashes=True, slow=True, lib=None, hd=None, label='REPLAY',
           summary=None, limit=None):
    """Generator of (image, ms) for `part` of the match.  The K.O. plays at half speed when `slow`."""
    from .atlas import Library
    lib = lib or Library()
    plan = dict(clean_plan(plan), t0=float(plan.get('t0') or 0.0))
    if summary is None:
        _, summary = summarize(plan, lib)
    start, end = window_of(plan, summary, part)
    ko = (summary.get('final_ko') or {}).get('tc')
    r = Renderer(plan, names=names, code=code, flashes=flashes, lib=lib, hd=hd, label=label)
    r.advance(start)
    n = 0
    for t, s in schedule(start, end, fps, slow_from=(float(ko) - 0.5) if (ko and slow) else None):
        yield r.frame(t, slow=s), int(round(1000.0 / fps))
        n += 1
        if limit and n >= limit:
            return


# ---------------------------------------------------------------- GIF export
def exports_dir() -> Path:
    """Where exports go unless you name a path: <data folder>/exports (the app writes only under its data folder, or to a
    path you choose)."""
    return cfgmod.data_dir() / 'exports'


def reveal(path):
    """Open the folder holding `path` with the file selected (Explorer /select, Finder -R).  Never under tests.
    -> True when asked of the OS."""
    if os.environ.get('MINIS_TESTING'):
        return False
    import subprocess
    p = str(Path(path).resolve())
    try:
        if sys.platform == 'win32':
            exe = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'explorer.exe')
            subprocess.Popen([exe, '/select,' + p], close_fds=True)
        elif sys.platform == 'darwin':
            subprocess.Popen(['/usr/bin/open', '-R', p], close_fds=True)
        else:
            return False
        return True
    except OSError:
        return False


def gif_name(entry_or_plan, now=None) -> str:
    plan = entry_or_plan.get('plan', entry_or_plan)
    ch = plan.get('chars') or {}
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(time.time() if now is None else now))
    return f"taskbar-fighters-{safe_id(ch.get('a'))}-vs-{safe_id(ch.get('b'))}-{stamp}.gif"


def safe_id(cid) -> str:
    """An id reduced to [a-z0-9_-] (at most 40) for a file name; 'x' when nothing is left."""
    import re
    return re.sub(r'[^a-z0-9_-]', '', str(cid or '').lower())[:40] or 'x'


def inside_exports(path) -> bool:
    """The resolved path lies under the exports folder (the default output must, whatever an id or code contained)."""
    try:
        Path(path).resolve().relative_to(exports_dir().resolve())
        return True
    except (ValueError, OSError):
        return False


def save_gif(frame_iter, out, colors=96):
    """Write (image, ms) frames as a looping GIF.  -> (path, frame count)."""
    from PIL import Image
    fr, ms = [], []
    for im, d in frame_iter:
        fr.append(im.convert('RGB'))
        ms.append(d)
    if not fr:
        raise ValueError('no frames')
    pal = fr[len(fr) // 2].quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in fr]
    ms[-1] = max(ms[-1], 1500)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name('.' + out.name + '.tmp')
    q[0].save(tmp, format='GIF', save_all=True, append_images=q[1:], duration=ms, loop=0, optimize=True, disposal=1)
    os.replace(tmp, out)
    return out, len(q)


def resolve(code=None, p=None):
    """-> (plan, names, code, entry, warning) for the last stored match, or for a pasted fight code."""
    if code:
        plan, expect, ver = decode(code)
        from .atlas import Library
        lib = Library()
        missing = [c for c in plan['chars'].values() if lib[c].character != c]
        warn = None
        if missing:
            warn = f"fighter(s) not on this computer: {', '.join(missing)} (drawn as stand-ins)"
        if ver != ENGINE:
            warn = f'this code was made by a different engine version ({ver}, this one is {ENGINE}): the fight may play differently'
        elif expect:
            _, summ = summarize(plan, lib)
            if summ.get('winner') != expect['winner'] or {k: int(v) for k, v in (summ.get('wins') or {}).items()} != expect['wins']:
                warn = 'this code plays differently on this version of the engine'
        return plan, {}, encode(plan, expect), None, warn
    e = last(p)
    if e is None:
        return None, None, None, None, 'no match has been recorded yet: start one with `minis.py demo match`'
    return e['plan'], e.get('labels') or {}, e.get('code'), e, None
