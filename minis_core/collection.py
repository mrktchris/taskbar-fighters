"""The move book (UX item 8): every move, set piece and finisher of every fighter; the ones you have seen are drawn animated
with their name and type, the rest are silhouettes with a "?".

collection.json in the data folder (ids and times only):
  {"seen": {character id: {key: first-seen wall time}}}     key = "m:<move>" | "p:<set piece>" | "f:ko"
Written by both fighter processes: each keeps its own set in memory and merges it into the file (read, union, write), so a
lost race heals on the next flush.  Only character ids, move ids and times are stored.

The book window itself is minis_win/book_window.py; this module is the catalogue, the tracker and the pure Model
(layout, input, rendering) like minis_core.select.
"""
from __future__ import annotations
import json, time
from pathlib import Path

from PIL import Image, ImageDraw

from . import config as cfgmod
from .bus import write_json_atomic
from .render import font, text, wrap

SECTIONS = (('attacks', 'ATTACKS', ('strike', 'special', 'super', 'ultimate', 'throw')),
            ('defense', 'DEFENSE', ('defense', 'reaction')),
            ('everyday', 'EVERYDAY', ('locomotion', 'emote', 'state', 'pair', 'support')),
            ('pieces', 'SET PIECES', ()),
            ('finishers', 'FINISHERS', ()))
CAT_ORDER = ('strike', 'throw', 'special', 'super', 'ultimate', 'defense', 'reaction', 'locomotion', 'state', 'emote', 'pair',
             'support')


def path() -> Path:
    return cfgmod.data_dir() / 'collection.json'


def read(p=None) -> dict:
    """-> {character: {key: ts}} (empty on a missing / broken file)."""
    p = Path(p) if p else path()
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        s = d.get('seen') if isinstance(d, dict) else None
        if isinstance(s, dict):
            return {c: {k: float(v) for k, v in keys.items() if isinstance(k, str)} for c, keys in s.items()
                    if isinstance(c, str) and isinstance(keys, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {}


def merge(mine, p=None) -> bool:
    """Union `mine` ({character: {key: ts}}) into the file, keeping the earliest first-seen time."""
    cur = read(p)
    changed = False
    for ch, keys in (mine or {}).items():
        row = cur.setdefault(ch, {})
        for k, ts in keys.items():
            if k not in row or ts < row[k]:
                row[k] = float(ts)
                changed = True
    if not changed and Path(p or path()).exists():
        return True
    return write_json_atomic(Path(p) if p else path(), {'seen': cur, 'ts': time.time()})


class Tracker:
    """Per fighter process: note what is seen, flush now and then (at most every `every_s`)."""

    def __init__(self, p=None, every_s=10.0):
        self.p, self.every_s = p, every_s
        self.seen = {}
        self.dirty = False
        self.last_flush = -1e18
        self.last_anim = None

    def note(self, character, key, now=None):
        if not character or not key:
            return False
        row = self.seen.setdefault(str(character), {})
        if key in row:
            return False
        row[key] = time.time() if now is None else float(now)
        self.dirty = True
        return True

    def note_move(self, character, anim, now=None):
        k = (character, anim)
        if k == self.last_anim:
            return False
        self.last_anim = k
        return self.note(character, 'm:' + str(anim), now)

    def note_match(self, chars, pieces, ko_winner_char=None, now=None):
        for c in set(chars or ()):
            for pc in pieces or ():
                self.note(c, 'p:' + str(pc), now)
        if ko_winner_char:
            self.note(ko_winner_char, 'f:ko', now)

    def flush(self, mono, force=False):
        if not self.dirty or (not force and mono - self.last_flush < self.every_s):
            return False
        self.last_flush = mono
        if merge(self.seen, self.p):
            self.dirty = False
            return True
        return False


# ---------------------------------------------------------------- the catalogue
def entries(atlas):
    """-> {section id: [entry]} for one character.  entry: {key, name, type, anim (what to draw) | None, desc, absent}."""
    from . import setpieces
    out = {sid: [] for sid, _, _ in SECTIONS}
    anims = atlas.anim
    cat_of = {n: (a.get('cat') or 'emote') for n, a in anims.items()}
    order = {c: i for i, c in enumerate(CAT_ORDER)}
    for sid, _, cats in SECTIONS[:3]:
        names = sorted((n for n in anims if cat_of[n] in cats), key=lambda n: (order.get(cat_of[n], 99), n))
        for n in names:
            a = anims[n]
            typ = a['type'].replace('_', ' ') if isinstance(a.get('type'), str) and a['type'] != cat_of[n] else cat_of[n]
            out[sid].append(dict(key='m:' + n, name=n.replace('_', ' '), type=typ, anim=n, desc=str(a.get('desc') or ''), absent=False))
    for name in setpieces.ORDER:
        pc = setpieces.PIECES[name]
        lander = pc.get('lander', 'att')
        beats = [b for b in pc['beats'] if b['who'] == lander] or pc['beats']
        anim = None
        for b in reversed(beats):
            anim = setpieces.fill(atlas, b['slot'])
            if anim:
                break
        absent = any(setpieces.fill(atlas, b['slot']) is None for b in pc['beats'] if b['who'] == 'att')
        out['pieces'].append(dict(key='p:' + name, name=pc.get('title', name), type='set piece', anim=anim if anim in anims else None,
                                  desc=str(pc.get('desc') or ''), absent=absent))
    sig = atlas.signature() if hasattr(atlas, 'signature') else {}
    for role in ('ultimate', 'super'):
        n = sig.get(role)
        if n and n in anims:
            out['finishers'].append(dict(key='m:' + n, name=n.replace('_', ' '), type=role, anim=n,
                                         desc=str(anims[n].get('desc') or ''), absent=False))
    win = 'victory2' if 'victory2' in anims else 'victory'
    out['finishers'].append(dict(key='f:ko', name='K.O. finisher', type='finisher', anim=win if win in anims else None,
                                 desc='Win a match by K.O.: the freeze, the slow-motion fall and the winner\'s pose.', absent=False))
    return out


def counts(atlas, seen_keys):
    """-> (seen, total) over every section (absent set pieces left out)."""
    tot = got = 0
    for lst in entries(atlas).values():
        for e in lst:
            if e['absent']:
                continue
            tot += 1
            got += e['key'] in seen_keys
    return got, tot


# ---------------------------------------------------------------- the book (pure model, like select.Model)
BG, EDGE, INK, DIM, GREY = (16, 16, 22, 242), (110, 110, 128, 255), (236, 236, 244), (160, 160, 175), (96, 96, 108)
TILE, TILE_SEL = (34, 34, 44, 255), (52, 52, 66, 255)
GOLD = (255, 214, 92)
PAD = 6
HEAD_H = 26
STRIP_H = 34
TAB_H = 16
CW, CH, CP = 74, 78, 46                # cell width, height (portrait + a two-line name + the type), portrait height
COLS, ROWS = 7, 3
FOOT_H = 48
FPS = 8
VK = dict(left=0x25, up=0x26, right=0x27, down=0x28, enter=0x0D, space=0x20, esc=0x1B, back=0x08, tab=0x09, pgup=0x21,
          pgdn=0x22, home=0x24)


class Book:
    """State, layout, input and rendering of the move book.  chars: [{'id','display'}] (lineup.characters()); seen:
    collection.read(); lib: an atlas Library (64 px sheets); start: the character to open on."""

    def __init__(self, chars, seen, lib, start=None, now=0.0):
        self.chars = [c for c in chars if isinstance(c, dict) and c.get('id')]
        self.seen = {c: set(keys) for c, keys in (seen or {}).items()}
        self.lib = lib
        self.ci = next((i for i, c in enumerate(self.chars) if c['id'] == start), 0)
        self.si = 0
        self.page = 0
        self.cur = 0
        self.hover = None
        self.phase = 'open'
        self.t0 = now
        self._entries = {}
        self._crop = {}
        self._box = {}
        self.W = PAD * 2 + COLS * CW + (COLS - 1) * 4
        self.strip_y = PAD + HEAD_H
        self.tab_y = self.strip_y + STRIP_H + 2
        self.grid_y = self.tab_y + TAB_H + 6
        self.foot_y = self.grid_y + ROWS * (CH + 4) + 2
        self.H = self.foot_y + FOOT_H + PAD

    # ------------------------------------------------------------ data
    @property
    def char(self):
        return self.chars[self.ci]['id'] if self.chars else 'generic'

    def atlas(self, cid=None):
        return self.lib[cid or self.char]

    def section_entries(self, cid=None, si=None):
        cid = cid or self.char
        if cid not in self._entries:
            try:
                self._entries[cid] = entries(self.atlas(cid))
            except Exception:
                self._entries[cid] = {sid: [] for sid, _, _ in SECTIONS}
        return self._entries[cid][SECTIONS[self.si if si is None else si][0]]

    def pages(self):
        return max(1, -(-len(self.section_entries()) // (COLS * ROWS)))

    def visible(self):
        e = self.section_entries()
        n = COLS * ROWS
        return e[self.page * n:(self.page + 1) * n]

    def is_seen(self, entry, cid=None):
        return entry['key'] in self.seen.get(cid or self.char, ())

    def selected(self):
        v = self.visible()
        i = self.hover if isinstance(self.hover, int) else self.cur
        return v[i] if 0 <= i < len(v) else None

    # ------------------------------------------------------------ layout + hit-testing
    def strip_rects(self):
        n = max(1, len(self.chars))
        w = min(32, (self.W - 2 * PAD) // n)
        x0 = (self.W - n * w) // 2
        return [(x0 + i * w, self.strip_y, x0 + i * w + w - 2, self.strip_y + STRIP_H - 2) for i in range(n)]

    def tab_rects(self):
        out, x = [], PAD
        f = font(9, True)
        d = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        for _, label, _ in SECTIONS:
            w = int(d.textlength(label, font=f)) + 14
            out.append((x, self.tab_y, x + w, self.tab_y + TAB_H))
            x += w + 3
        return out

    def page_rects(self):
        y0, y1 = self.tab_y, self.tab_y + TAB_H
        return (self.W - PAD - 52, y0, self.W - PAD - 38, y1), (self.W - PAD - 14, y0, self.W - PAD, y1)

    def cell_rect(self, i):
        c, r = i % COLS, i // COLS
        x = PAD + c * (CW + 4)
        y = self.grid_y + r * (CH + 4)
        return x, y, x + CW, y + CH

    def hit(self, x, y):
        for i, r in enumerate(self.strip_rects()):
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return 'char', i
        for i, r in enumerate(self.tab_rects()):
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return 'tab', i
        prev, nxt = self.page_rects()
        if prev[0] <= x <= prev[2] and prev[1] <= y <= prev[3]:
            return 'page', -1
        if nxt[0] <= x <= nxt[2] and nxt[1] <= y <= nxt[3]:
            return 'page', 1
        for i in range(len(self.visible())):
            r = self.cell_rect(i)
            if r[0] <= x < r[2] and r[1] <= y < r[3]:
                return 'cell', i
        return None

    # ------------------------------------------------------------ input
    def set_char(self, i):
        if self.chars:
            self.ci = i % len(self.chars)
            self.page, self.cur = 0, 0

    def set_section(self, i):
        self.si = i % len(SECTIONS)
        self.page, self.cur = 0, 0

    def turn(self, d):
        self.page = (self.page + d) % self.pages()
        self.cur = min(self.cur, max(0, len(self.visible()) - 1))

    def key(self, vk, now=None):
        if self.phase != 'open':
            return
        n = len(self.visible())
        if vk == VK['esc']:
            self.phase = 'closed'
        elif vk == VK['tab']:
            self.set_section(self.si + 1)
        elif vk in (VK['pgdn'], VK['pgup']):
            self.turn(1 if vk == VK['pgdn'] else -1)
        elif vk == VK['home']:
            self.set_char(self.ci + 1)
        elif vk in (VK['left'], VK['right']):
            d = -1 if vk == VK['left'] else 1
            j = self.cur + d
            if j < 0 or j >= n:
                if self.pages() > 1:
                    self.turn(d)
                    self.cur = 0 if d > 0 else max(0, len(self.visible()) - 1)
                else:
                    self.cur = j % max(1, n)
            else:
                self.cur = j
        elif vk in (VK['up'], VK['down']):
            j = self.cur + (-COLS if vk == VK['up'] else COLS)
            if 0 <= j < n:
                self.cur = j
            elif vk == VK['up']:
                self.set_char(self.ci - 1)
            else:
                self.set_char(self.ci + 1)
        self.hover = None

    def click(self, x, y, now=None):
        h = self.hit(x, y)
        if not h:
            return
        kind, i = h
        if kind == 'char':
            self.set_char(i)
        elif kind == 'tab':
            self.set_section(i)
        elif kind == 'page':
            self.turn(i)
        elif kind == 'cell':
            self.cur = i

    def move(self, x, y):
        h = self.hit(x, y)
        self.hover = h[1] if h and h[0] == 'cell' else None

    def wheel(self, delta, now=None):
        self.turn(-1 if delta > 0 else 1)

    def frame_key(self, now):
        return (self.phase, self.ci, self.si, self.page, self.cur, self.hover, int((now - self.t0) * FPS))

    # ------------------------------------------------------------ drawing
    def _anim_box(self, atlas, anim):
        """Union of the alpha boxes of an animation's frames (cached), so a cell never jitters while it plays."""
        key = (atlas.character, anim)
        if key not in self._box:
            bb = None
            for i in range(len(atlas.anim[anim]['frames'])):
                b = atlas.frame_image(anim, i, 1).getchannel('A').getbbox()
                if b:
                    bb = b if bb is None else (min(bb[0], b[0]), min(bb[1], b[1]), max(bb[2], b[2]), max(bb[3], b[3]))
            self._box[key] = bb or (0, 0, atlas.cell[0], atlas.cell[1])
        return self._box[key]

    def _frame_at(self, atlas, anim, t):
        frames = atlas.anim[anim]['frames']
        total = sum(f['ms'] for f in frames) or 1
        ms = int(t * 1000) % (total + 400)                       # a short rest on the last frame between plays
        for i, f in enumerate(frames):
            ms -= f['ms']
            if ms < 0:
                return i
        return len(frames) - 1

    def portrait(self, cid, anim, t, seen, w=CW, h=CP):
        """The move's frame at time t, fitted into w x h (whole-pixel scale only); a dark silhouette when not seen."""
        atlas = self.atlas(cid)
        if anim not in atlas.anim:
            anim = 'idle'
        i = self._frame_at(atlas, anim, t) if seen else min(len(atlas.anim[anim]['frames']) - 1, atlas.anim[anim].get('hit_frame', 1))
        key = (cid, anim, i, seen, w, h)
        im = self._crop.get(key)
        if im is not None:
            return im
        if len(self._crop) > 1500:
            self._crop.clear()
        bb = self._anim_box(atlas, anim)
        fr = atlas.frame_image(anim, i, 1).crop(bb)
        if fr.width > w - 2 or fr.height > h - 2:
            k = min((w - 2) / max(1, fr.width), (h - 2) / max(1, fr.height))
            fr = fr.resize((max(1, int(fr.width * k)), max(1, int(fr.height * k))), Image.NEAREST)
        if not seen:
            a = fr.getchannel('A').point(lambda v: 255 if v > 40 else 0)
            fr = Image.new('RGBA', fr.size, (58, 58, 74, 255))
            fr.putalpha(a)
        out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        out.alpha_composite(fr, ((w - fr.width) // 2, h - 1 - fr.height))
        self._crop[key] = out
        return out

    def render(self, now) -> Image.Image:
        im = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        d.rounded_rectangle([0, 0, self.W - 1, self.H - 1], 6, fill=BG, outline=EDGE)
        t = now - self.t0
        atlas = self.atlas()
        accent = tuple(atlas.accent)
        keys = self.seen.get(self.char, set())
        got, tot = counts(atlas, keys)
        # header
        text(d, (PAD + 2, PAD - 1), 'MOVE BOOK', INK, 11)
        name = self.chars[self.ci]['display'] if self.chars else atlas.display
        text(d, (PAD + 2, PAD + 13), name, accent, 10)
        nw = int(d.textlength(name, font=font(10, True)))
        text(d, (PAD + 8 + nw, PAD + 14), f'{got} of {tot} seen', DIM, 9, False)
        bar_x0, bar_x1 = self.W - PAD - 150, self.W - PAD - 2
        d.rectangle([bar_x0, PAD + 4, bar_x1, PAD + 9], fill=(58, 58, 66, 255))
        if tot:
            d.rectangle([bar_x0, PAD + 4, bar_x0 + int((bar_x1 - bar_x0) * got / tot), PAD + 9], fill=accent + (255,))
        allg = sum(counts(self.atlas(c['id']), self.seen.get(c['id'], set()))[0] for c in self.chars[:20])
        allt = sum(counts(self.atlas(c['id']), set())[1] for c in self.chars[:20])
        s = f'all fighters {allg} / {allt}'
        text(d, (bar_x1 - int(d.textlength(s, font=font(9, False))), PAD + 13), s, DIM, 9, False)
        # fighter strip
        for i, r in enumerate(self.strip_rects()):
            cid = self.chars[i]['id']
            sel = i == self.ci
            d.rectangle(r, fill=TILE_SEL if sel else TILE)
            p = self.portrait(cid, 'idle', t if sel else 0.0, True, r[2] - r[0], r[3] - r[1] - 1)
            if not sel:
                p = p.copy()
                p.putalpha(p.getchannel('A').point(lambda v: int(v * 0.6)))
            im.alpha_composite(p, (r[0], r[1]))
            g, n = counts(self.atlas(cid), self.seen.get(cid, set()))
            if n and g == n:
                d.rectangle([r[2] - 5, r[1] + 1, r[2] - 1, r[1] + 5], fill=GOLD + (255,))
            if sel:
                d.rectangle([r[0] - 1, r[1] - 1, r[2] + 1, r[3] + 1], outline=accent + (255,), width=2)
        # tabs + pages
        for i, r in enumerate(self.tab_rects()):
            sid, label, _ = SECTIONS[i]
            on = i == self.si
            d.rounded_rectangle(r, 3, fill=(70, 70, 86, 255) if on else (30, 30, 38, 255), outline=(accent + (255,)) if on else (70, 70, 84, 255))
            text(d, (r[0] + 7, r[1] + 2), label, INK if on else DIM, 9)
        prev, nxt = self.page_rects()
        if self.pages() > 1:
            pg = f'{self.page + 1}/{self.pages()}'
            text(d, ((prev[2] + nxt[0]) // 2 - int(d.textlength(pg, font=font(9, False))) // 2, prev[1] + 2), pg, DIM, 9, False)
            for r, ch in ((prev, '<'), (nxt, '>')):
                d.rounded_rectangle(r, 2, outline=(110, 110, 128, 255))
                text(d, (r[0] + 4, r[1] + 2), ch, INK, 9)
        # grid
        blink = int(now * 3) % 2 == 0
        vis = self.visible()
        for i, e in enumerate(vis):
            x0, y0, x1, y1 = self.cell_rect(i)
            seen = self.is_seen(e)
            sel = (self.hover if isinstance(self.hover, int) else self.cur) == i
            d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=TILE_SEL if sel else TILE)
            if e['absent']:
                text(d, (x0 + 4, y0 + CP // 2 - 6), 'not in this', GREY, 8, False)
                text(d, (x0 + 4, y0 + CP // 2 + 3), "fighter's style", GREY, 8, False)
            elif e['anim']:
                im.alpha_composite(self.portrait(self.char, e['anim'], t + i * 0.37, seen), (x0, y0))
            if not seen and not e['absent']:
                f = font(16, True)
                q = '?'
                d.text((x0 + (CW - int(d.textlength(q, font=f))) // 2, y0 + 10), q, fill=(150, 150, 170), font=f)
            f8, f9 = font(8, True), font(9, False)
            names = wrap(e['name'] if seen else '? ? ?', CW - 4, 8, True)[:2]
            for j, nm in enumerate(names):                     # whole names, on two lines when they need them
                text(d, (x0 + (CW - int(d.textlength(nm, font=f8))) // 2, y0 + CP + 1 + 9 * j), nm, INK if seen else GREY, 8)
            ty = e['type']
            text(d, (x0 + (CW - int(d.textlength(ty, font=f9))) // 2, y0 + CP + 2 + 9 * len(names)), ty,
                 (150, 210, 150) if seen else GREY, 9, False)
            if sel and (blink or self.hover is not None):
                d.rectangle([x0 - 1, y0 - 1, x1, y1], outline=accent + (255,), width=2)
        if not vis:
            text(d, (PAD + 6, self.grid_y + 20), 'nothing here for this fighter', DIM, 9, False)
        # footer: the selected entry, then the keys
        e = self.selected()
        if e is not None:
            seen = self.is_seen(e)
            line = (f"{e['name']}: {e['desc']}" if seen and e['desc'] else e['name'] if seen else
                    ("Not in this fighter's style." if e['absent'] else 'Not seen yet: it shows up in a fight on your taskbar.'))
            for j, ln in enumerate(wrap(line, self.W - 2 * PAD - 4)[:3]):
                text(d, (PAD + 2, self.foot_y + 11 * j), ln, INK if seen else DIM, 9, False)
        hint = 'Arrows move   Tab section   Up/Down past the grid: fighter   PgUp/PgDn page   Esc close'
        f9 = font(9, False)
        text(d, ((self.W - int(d.textlength(hint, font=f9))) // 2, self.foot_y + 36), hint, GREY, 9, False)
        return im
