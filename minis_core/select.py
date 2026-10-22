"""The fighter-select screen (V6): pure state machine, layout, hit-testing and rendering.  The window that shows it is
minis_win/select_window.py (hosted by the director, next to the scoreboard).

Two stages per player, as in classic fighting-game select screens:
  WHO   a row of program tiles - AUTO first, then every program that is detected or remembered (plus the sparring bot and
        whatever a slot has picked).  Each tile shows the portrait of the character that program is drawn as.
  LOOK  a grid of every character on disk (read from the roster each time the screen opens, so 13 or 30 characters just
        grow the grid), the program's current look highlighted.  AUTO skips this stage.
P1 (red, left slot a) chooses first, then P2 (blue, slot b); opened from a scoreboard name, only that side chooses.
Keys: arrows move, Enter/Space confirm, Backspace back, Esc cancel.  Mouse: click a tile to choose it (clicking the
highlighted character again keeps it), wheel moves through the looks.  Confirming the last player flashes "VS" briefly;
the owner writes the lineup when `phase` turns 'vs'.  Only short program labels, character names and portraits drawn
from our own sheets appear here.
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from .render import font, text

AUTO = 'auto'
P_COL = {'a': (236, 72, 72), 'b': (84, 146, 255)}
P_TAG = {'a': '1P', 'b': '2P'}
BG, EDGE, INK, DIM, GREY = (16, 16, 22, 240), (110, 110, 128, 255), (236, 236, 244), (160, 160, 175), (96, 96, 108)
TILE_BG = (34, 34, 44, 255)
PAD, GAP = 6, 4
HEAD_H, SECT_H, FOOT_H = 24, 11, 12
TW, TH, TP = 46, 66, 44                  # program tile: width, height, portrait height (label + state below)
CW, CH, CP = 44, 50, 37                  # character tile (44: "Barbarian" and "LM Studio" fit the pixel font whole)
MAX_WHO_COLS, MAX_LOOK_COLS = 9, 7
VS_S = 0.9
VK = dict(left=0x25, up=0x26, right=0x27, down=0x28, enter=0x0D, space=0x20, esc=0x1B, back=0x08, tab=0x09)


class Model:
    def __init__(self, slots, rows, lineup, chars, portrait=None, now=0.0):
        """slots: the players, e.g. ('a', 'b') or ('b',).  rows: lineup.programs() entries (source, label, character, state)
        to offer.  lineup: control.lineup().  chars: lineup.characters().  portrait(character, t, w, h) -> RGBA image."""
        self.players = [s for s in ('a', 'b') if s in tuple(slots)] or ['a', 'b']
        self.rows = [dict(source=AUTO, label='AUTO', character=None, state='')] + [dict(r) for r in rows]
        self.chars = list(chars)
        self.portrait = portrait
        self.lineup = {'a': lineup.get('a', AUTO), 'b': lineup.get('b', AUTO)}
        self.skins = dict(lineup.get('skins') or {})
        self.active = 0
        self.stage = 'who'
        self.cur = {}
        for s in self.players:
            pick = self.lineup.get(s, AUTO)
            self.cur[s] = next((i for i, r in enumerate(self.rows) if r['source'] == pick), 0)
        self.look = 0
        self.choice = {}                       # slot -> program id | 'auto', once that player confirmed
        self.phase = 'select'
        self.vs_until = None
        self.msg, self.msg_until = '', 0.0
        self.hover = None
        self.t0 = now
        self._layout()

    # ------------------------------------------------------------ queries
    @property
    def slot(self):
        return self.players[self.active]

    def own_character(self, source):
        for r in self.rows:
            if r['source'] == source:
                return r['character']
        return None

    def look_of(self, source):
        if source in (None, AUTO):
            return None
        return self.skins.get(source) or self.own_character(source)

    def display(self, cid):
        return next((c['display'] for c in self.chars if c['id'] == cid), str(cid))

    def label(self, source):
        return next((r['label'] for r in self.rows if r['source'] == source), str(source))

    def result(self):
        """-> (picks {slot: program id | 'auto'}, skins {program: character}) - what to write when phase is 'vs'."""
        return dict(self.choice), dict(self.skins)

    # ------------------------------------------------------------ layout
    def _layout(self):
        n = len(self.rows)
        self.who_cols = min(n, MAX_WHO_COLS)
        who_rows = -(-n // self.who_cols)
        m = max(1, len(self.chars))
        self.look_cols = min(m, MAX_LOOK_COLS)
        look_rows = -(-m // self.look_cols)
        who_w = self.who_cols * TW + (self.who_cols - 1) * GAP
        look_w = self.look_cols * CW + (self.look_cols - 1) * GAP
        self.W = PAD * 2 + max(who_w, look_w, 236)
        y = PAD + HEAD_H + 2
        self.who_y = y + SECT_H
        x0 = (self.W - who_w) // 2
        self.who_rects = [(x0 + (i % self.who_cols) * (TW + GAP), self.who_y + (i // self.who_cols) * (TH + GAP)) for i in range(n)]
        y = self.who_y + who_rows * (TH + GAP) + 2
        self.look_y = y + SECT_H
        x1 = (self.W - look_w) // 2
        self.look_rects = [(x1 + (i % self.look_cols) * (CW + GAP), self.look_y + (i // self.look_cols) * (CH + GAP)) for i in range(m)]
        y = self.look_y + look_rows * (CH + GAP)
        self.foot_y = y + 1
        self.H = self.foot_y + FOOT_H + PAD - 2

    def hit(self, x, y):
        """-> ('who', i) | ('look', i) | None."""
        for i, (tx, ty) in enumerate(self.who_rects):
            if tx <= x < tx + TW and ty <= y < ty + TH:
                return 'who', i
        for i, (tx, ty) in enumerate(self.look_rects):
            if i < len(self.chars) and tx <= x < tx + CW and ty <= y < ty + CH:
                return 'look', i
        return None

    # ------------------------------------------------------------ input
    def _say(self, msg, now, secs=1.6):
        self.msg, self.msg_until = msg, now + secs

    def _taken_by(self, source):
        """The other player who already chose `source` in this session (a program never fights itself), else None."""
        if source == AUTO:
            return None
        for s, v in self.choice.items():
            if s != self.slot and v == source:
                return s
        return None

    def _confirm_who(self, now):
        r = self.rows[self.cur[self.slot]]
        who = self._taken_by(r['source'])
        if who:
            self._say(f"{r['label']} is {P_TAG[who]}'s fighter", now)
            return
        if r['source'] == AUTO:
            self._finish_player(AUTO, now)
            return
        self.stage = 'look'
        cid = self.look_of(r['source'])
        self.look = next((i for i, c in enumerate(self.chars) if c['id'] == cid), 0)

    def _confirm_look(self, now):
        src = self.rows[self.cur[self.slot]]['source']
        if self.chars:
            cid = self.chars[self.look]['id']
            if cid == self.own_character(src):
                self.skins.pop(src, None)
            else:
                self.skins[src] = cid
        self._finish_player(src, now)

    def _finish_player(self, source, now):
        self.choice[self.slot] = source
        if self.active + 1 < len(self.players):
            self.active += 1
            self.stage = 'who'
        else:
            self.phase, self.vs_until = 'vs', now + VS_S

    def back(self, now):
        if self.stage == 'look':
            self.stage = 'who'
        elif self.active > 0:
            self.active -= 1
            self.choice.pop(self.slot, None)
            self.stage = 'who'

    def cancel(self, now=None):
        if self.phase == 'select':
            self.phase = 'cancel'

    def key(self, vk, now):
        if self.phase != 'select':
            return
        if vk == VK['esc']:
            self.cancel(now)
        elif vk == VK['back']:
            self.back(now)
        elif vk in (VK['enter'], VK['space']):
            self._confirm_who(now) if self.stage == 'who' else self._confirm_look(now)
        elif vk in (VK['left'], VK['right'], VK['up'], VK['down']):
            if self.stage == 'who':
                n, cols = len(self.rows), self.who_cols
                d = {VK['left']: -1, VK['right']: 1, VK['up']: -cols, VK['down']: cols}[vk]
                if vk in (VK['up'], VK['down']) and n <= cols:
                    return
                self.cur[self.slot] = (self.cur[self.slot] + d) % n
            else:
                n, cols = max(1, len(self.chars)), self.look_cols
                d = {VK['left']: -1, VK['right']: 1, VK['up']: -cols, VK['down']: cols}[vk]
                if vk == VK['up'] and self.look < cols:
                    self.stage = 'who'                     # up out of the grid: back to the programs
                    return
                self.look = (self.look + d) % n

    def click(self, x, y, now):
        if self.phase != 'select':
            return
        h = self.hit(x, y)
        if h is None:
            return
        kind, i = h
        if kind == 'who':
            if self.stage == 'look' and self.cur[self.slot] != i:
                self.stage = 'who'
            self.cur[self.slot] = i
            self._confirm_who(now)
        elif kind == 'look' and self.stage == 'look':
            self.look = i
            self._confirm_look(now)

    def wheel(self, delta, now):
        if self.phase == 'select' and self.stage == 'look' and self.chars:
            self.look = (self.look + (-1 if delta > 0 else 1)) % len(self.chars)

    def move(self, x, y):
        self.hover = self.hit(x, y)

    def tick(self, now):
        if self.phase == 'vs' and now >= self.vs_until:
            self.phase = 'done'

    # ------------------------------------------------------------ rendering
    def frame_key(self, now):
        """Everything the picture depends on (the owner redraws only when it changes; portraits animate at ~8 fps)."""
        return (self.phase, self.active, self.stage, tuple(sorted(self.cur.items())), self.look, tuple(sorted(self.choice.items())),
                tuple(sorted(self.skins.items())), self.msg if now < self.msg_until else '', self.hover, int((now - self.t0) * 8),
                int(now * 3) % 2)

    def _portrait(self, cid, t, w, h):
        if cid is None or self.portrait is None:
            return None
        try:
            return self.portrait(cid, t, w, h)
        except Exception:
            return None

    def _draw_auto(self, d, x, y, w, h):
        q = '?'
        qw = int(d.textlength(q, font=font(11, True))) * 2                   # the pixel font, 2x: a 16 px tall '?'
        text(d, (x + (w - qw) // 2, y + h // 2 - 12), q, (200, 200, 215), 11, True, scale=2)

    def render(self, now) -> Image.Image:
        im = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        d.rounded_rectangle([0, 0, self.W - 1, self.H - 1], 6, fill=BG, outline=EDGE)
        t = now - self.t0
        if self.phase in ('vs', 'done'):
            self._render_vs(im, d, t)
            return im
        self._render_head(d)
        text(d, (PAD, self.who_y - SECT_H), 'WHO', DIM, 9, True)
        blink = int(now * 3) % 2 == 0
        for i, ((x, y), r) in enumerate(zip(self.who_rects, self.rows)):
            grey = r['state'] == 'not seen'
            d.rectangle([x, y, x + TW - 1, y + TH - 1], fill=TILE_BG)
            if r['source'] == AUTO:
                self._draw_auto(d, x, y, TW, TP)
            else:
                p = self._portrait(self.look_of(r['source']), t, TW, TP)
                if p is not None:
                    if grey:
                        p = p.copy()
                        p.putalpha(p.getchannel('A').point(lambda v: v // 2))
                    im.alpha_composite(p, (x, y))
            lab = r['label']
            f = font(9, True)
            while len(lab) > 1 and d.textlength(lab, font=f) > TW - 2:
                lab = lab[:-1]
            text(d, (x + (TW - int(d.textlength(lab, font=f))) // 2, y + TP + 1), lab, GREY if grey else INK, 9)
            st = {'': 'director', 'bot': 'stand-in', 'waiting': 'waiting?'}.get(r['state'], r['state'])
            f8 = font(8, False)
            col = (150, 220, 150) if r['state'] in ('working', 'waiting') else DIM
            text(d, (x + (TW - int(d.textlength(st, font=f8))) // 2, y + TP + 11), st, col, 8, False)
            for s in self.players:
                if self.cur.get(s) != i:
                    continue
                chosen = s in self.choice
                is_active = s == self.slot and self.stage == 'who'
                if chosen or is_active and blink or (s == self.slot and self.stage == 'look'):
                    self._cursor(d, x, y, TW, TH, s)
        text(d, (PAD, self.look_y - SECT_H), 'LOOK' if self.stage != 'look' else
             f'LOOK for {self.label(self.rows[self.cur[self.slot]]["source"])}', P_COL[self.slot] if self.stage == 'look' else DIM, 9, True)
        for i, ((x, y), c) in enumerate(zip(self.look_rects, self.chars)):
            active = self.stage == 'look'
            d.rectangle([x, y, x + CW - 1, y + CH - 1], fill=TILE_BG)
            p = self._portrait(c['id'], t if active else 0.0, CW, CP)
            if p is not None:
                if not active:
                    p = p.copy()
                    p.putalpha(p.getchannel('A').point(lambda v: int(v * 0.55)))
                im.alpha_composite(p, (x, y))
            lab = c['display']
            f = font(8, True)
            while len(lab) > 1 and d.textlength(lab, font=f) > CW - 2:
                lab = lab[:-1]
            text(d, (x + (CW - int(d.textlength(lab, font=f))) // 2, y + CP + 1), lab, INK if active else GREY, 8)
            if active and i == self.look and (blink or True):
                self._cursor(d, x, y, CW, CH, self.slot)
        msg = self.msg if now < self.msg_until else ''
        hint = msg or 'Arrows move   Enter choose   Backspace back   Esc cancel'
        f = font(9, False)
        text(d, ((self.W - int(d.textlength(hint, font=f))) // 2, self.foot_y), hint, (255, 196, 80) if msg else DIM, 9, False)
        return im

    def _render_head(self, d):
        f = font(10, True)
        title = 'SELECT FIGHTERS' if len(self.players) == 2 else f'SELECT {P_TAG[self.players[0]]} FIGHTER'
        text(d, ((self.W - int(d.textlength(title, font=f))) // 2, PAD - 2), title, INK, 10)
        for s in self.players:
            src = self.choice.get(s) or self.rows[self.cur[s]]['source']
            name = 'AUTO' if src == AUTO else self.label(src)
            lk = self.look_of(src)
            if lk and src != AUTO and lk != self.own_character(src):
                name += f' as {self.display(lk)}'
            s_txt = f'{P_TAG[s]} {name}'
            f9 = font(9, True)
            x = PAD if s == 'a' else self.W - PAD - int(d.textlength(s_txt, font=f9))
            if len(self.players) == 1:
                x = PAD
            text(d, (x, PAD + 9), s_txt, P_COL[s], 9)

    def _cursor(self, d, x, y, w, h, slot):
        col = P_COL[slot] + (255,)
        d.rectangle([x - 1, y - 1, x + w, y + h], outline=col, width=2)
        tag = P_TAG[slot]
        f = font(8, True)
        tw = int(d.textlength(tag, font=f)) + 4
        tx = x - 1 if slot == 'a' else x + w + 1 - tw
        d.rectangle([tx, y - 1, tx + tw - 1, y + 8], fill=col)
        text(d, (tx + 2, y - 1), tag, (255, 255, 255), 8)

    def _render_vs(self, im, d, t):
        sides = [s for s in ('a', 'b') if s in self.choice]
        if len(sides) == 1:                                          # one side chose: show it against the other's current pick
            o = 'b' if sides[0] == 'a' else 'a'
            sides = sorted(sides + [o])
        bw = (self.W - 2 * PAD) // 2
        ph = min(self.H - 30, 96)
        for i, s in enumerate(sides):
            src = self.choice.get(s, self.lineup.get(s, AUTO))
            x = PAD + i * bw
            cid = self.look_of(src)
            if cid:
                p = self._portrait(cid, t, min(bw - 20, ph), ph)
                if p is not None:
                    if i == 1:
                        p = p.transpose(Image.FLIP_LEFT_RIGHT)
                    im.alpha_composite(p, (x + (bw - p.width) // 2, 6))
            else:
                self._draw_auto(d, x, 6, bw, ph)
            name = 'AUTO' if src == AUTO else self.label(src)
            f = font(11, True)
            text(d, (x + (bw - int(d.textlength(name, font=f))) // 2, self.H - 20), name, P_COL[s], 11)
        vs = 'VS'
        x = (self.W - int(d.textlength(vs, font=font(11, True))) * 3) // 2   # the pixel font, 3x: a 24 px tall VS
        y = self.H // 2 - 20
        text(d, (x + 2, y + 2), vs, (0, 0, 0), 11, True, scale=3)
        text(d, (x, y), vs, (255, 214, 92), 11, True, scale=3)


# ---------------------------------------------------------------- portraits from our own sheets
class Portraits:
    """Idle-animated portraits cut from a character's own 64 px sheet (atlas.Library): the union box of its idle frames,
    top-aligned (head and shoulders first), scaled down only when it does not fit."""

    def __init__(self, lib):
        self.lib = lib
        self.box = {}
        self.cache = {}

    def _bbox(self, atlas):
        k = atlas.character
        if k not in self.box:
            bb = None
            for i in range(len(atlas.anim['idle']['frames'])):
                b = atlas.frame_image('idle', i, 1).getchannel('A').getbbox()
                if b:
                    bb = b if bb is None else (min(bb[0], b[0]), min(bb[1], b[1]), max(bb[2], b[2]), max(bb[3], b[3]))
            self.box[k] = bb or (0, 0, atlas.cell[0], atlas.cell[1])
        return self.box[k]

    def frame_index(self, atlas, t):
        frames = atlas.anim['idle']['frames']
        total = sum(f['ms'] for f in frames) or 1
        ms = int(t * 1000) % total
        for i, f in enumerate(frames):
            ms -= f['ms']
            if ms < 0:
                return i
        return 0

    def __call__(self, character, t, w, h):
        atlas = self.lib[character]
        i = self.frame_index(atlas, t)
        key = (atlas.character, i, w, h)
        im = self.cache.get(key)
        if im is not None:
            return im
        if len(self.cache) > 512:
            self.cache.clear()
        bb = self._bbox(atlas)
        fr = atlas.frame_image('idle', i, 1).crop(bb)
        k = min(1.0, (w - 2) / max(1, fr.width))
        up = int(min((w - 2) // max(1, fr.width), (h - 2) // max(1, fr.height)))
        if up >= 2:                                                    # big boxes (the VS card): whole-pixel upscale only
            fr = fr.resize((fr.width * up, fr.height * up), Image.NEAREST)
        elif k < 1.0:
            fr = fr.resize((max(1, int(fr.width * k)), max(1, int(fr.height * k))), Image.NEAREST)
        out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        out.alpha_composite(fr.crop((0, 0, fr.width, min(fr.height, h - 2))), ((w - fr.width) // 2, 2))
        self.cache[key] = out
        return out


def offer(rows, lineup):
    """The program tiles: everything detected or remembered, the bot, and whatever a slot has picked.  Never-seen programs
    are left out (the right-click menu lists them greyed)."""
    keep = {lineup.get('a'), lineup.get('b')}
    order = {'working': 0, 'waiting': 0, 'done': 1, 'limit': 1, 'idle': 2, 'sleeping': 3, 'asleep': 4, 'bot': 6}
    out = [r for r in rows if r['state'] != 'not seen' or r['source'] in keep]
    return sorted(out, key=lambda r: (order.get(r['state'], 5), r['label'].lower()))
