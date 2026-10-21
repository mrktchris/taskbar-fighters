"""The Settings window (UX item 1): a small window of its own, drawn as pixel art like the select screen, with every switch
the app has, a "Start with Windows" / "Open at login" box, and a drag-to-set fight zone.  Every row is also a command
(`minis.py settings list` prints them all with their current value).

Pieces (pure; the windows are minis_win/settings_window.py and minis_win/zone_window.py):
  ROWS / rows()     the rows: id, label, kind (toggle | choice | zone), help line, the CLI that does the same
  Backend           reads and writes the real values (control.json, ux.json, minis.json, the startup entry); injectable
  Model             layout, keyboard and mouse, rendering
  ZoneEdit          the zone editor over the taskbar: the current zone as a highlighted bar with a handle at each end
                    (drag them, or drag the bar), Save / Reset to auto / Cancel.  Saving writes `zone` to minis.json and
                    restarts the fighters (their windows are laid out from it)

Desktop weapons: the owner's choice stays "always real pixels" by default; the row only makes the switch obvious (its help
line says exactly what it does whenever it is on).
"""
from __future__ import annotations
import threading

from PIL import Image, ImageDraw

from .render import font, text, wrap

BG, EDGE, INK, DIM, GREY = (16, 16, 22, 242), (110, 110, 128, 255), (236, 236, 244), (165, 165, 180), (96, 96, 108)
ON, OFF, SEL = (120, 210, 130), (70, 70, 84), (44, 44, 56, 255)
AMBER, LINK, RED = (255, 196, 80), (140, 190, 255), (255, 110, 100)
PAD, HEAD_H, LINE1_H, FOOT_H = 8, 26, 14, 40
W = 352
STARTUP_HELP = {'on': 'on: Taskbar Fighters starts when you sign in', 'other': 'a startup entry for another copy of the app exists',
                'unknown': 'checking ...'}
VK = dict(left=0x25, up=0x26, right=0x27, down=0x28, enter=0x0D, space=0x20, esc=0x1B, back=0x08, tab=0x09)


def startup_label(is_mac=None):
    if is_mac is None:
        import minis_platform as plat
        is_mac = plat.is_mac()
    return 'Open at login' if is_mac else 'Start with Windows'


def rows(has_sound=False, is_mac=None):
    """-> [{id, label, kind, choices?, help, cli}]."""
    r = [dict(id='size', label='Fighter size', kind='choice', choices=[(64, '64'), (96, '96'), (128, '128 HD')],
              help='fighter height in px; the fighters restart to apply it', cli='size 64|96|128'),
         dict(id='plates', label='HUD plates', kind='toggle', help='name, state and context % beside the fighters', cli='plates on|off'),
         dict(id='flash', label='Flash effects', kind='toggle', help='white flashes and impact frames on big hits', cli='flash on|off')]
    if has_sound:
        r.append(dict(id='sound', label='Sound', kind='toggle', help='K.O., ultimate and "needs you" cues', cli='sound on|off'))
    r += [dict(id='forge', label='Desktop weapons', kind='toggle',
               help='arena: one screen picture held in RAM to forge weapons, never saved', cli='forge on|off'),
          dict(id='rival', label='Rival mode', kind='toggle', help='wake a sleeping partner for a match now and then', cli='rival on|off'),
          dict(id='winners', label='Who wins', kind='choice', choices=[('decided', 'Healthier'), ('random', 'Coin flip')],
               help='healthier program usually wins, or a coin flip', cli='winners decided|random'),
          dict(id='results', label='Results after a match', kind='toggle', help='a 4-second strip with the score and three numbers',
               cli='results on|off'),
          dict(id='cards', label='Hover cards', kind='toggle', help='rest the mouse on a fighter or plate: its state in words',
               cli='cards on|off'),
          dict(id='signals', label='Event signals', kind='toggle', help='done flag, needs-you halo, second wind, finisher cue',
               cli='signals on|off'),
          dict(id='startup', label=startup_label(is_mac), kind='toggle', help='starts Taskbar Fighters when you sign in',
               cli='startup on|off'),
          dict(id='zone', label='Fight zone', kind='zone', help='where on the taskbar they fight', cli='zone <left> <right> | zone auto')]
    return r


class Backend:
    """Current values and setters.  get() -> {row id: value}; set(id, value) -> message (str) or None.  startup and size
    changes may take a moment (a shortcut written through PowerShell, a restart): they run off the window's thread and
    `pending` names the row until it is done."""

    def __init__(self, cfg, startup=None, restart=None, edit_zone=None, log=None):
        self.cfg = cfg
        self.startup = startup                  # object with status() -> 'on'|'off'|'other'|'unknown', enable(), disable()
        self.restart = restart
        self.edit_zone = edit_zone              # () -> None: open the zone editor
        self.log = log
        self.pending = set()
        self.startup_state = 'unknown'
        self.message = ''
        self._lock = threading.Lock()
        if startup is not None:
            self._run('startup', self._read_startup)

    def _run(self, rid, fn):
        with self._lock:
            if rid in self.pending:
                return
            self.pending.add(rid)

        def go():
            try:
                fn()
            except Exception as e:                                    # never take the window down
                self.message = f'{rid}: {type(e).__name__}'
            finally:
                with self._lock:
                    self.pending.discard(rid)
        threading.Thread(target=go, name=f'minis-settings-{rid}', daemon=True).start()

    def _read_startup(self):
        try:
            self.startup_state = self.startup.status()[0]
        except Exception:
            self.startup_state = 'unknown'

    @staticmethod
    def has_sound():
        from . import control
        return hasattr(control, 'sound_on') and hasattr(control, 'set_sound')

    def get(self):
        from . import control, ux
        c = self.cfg
        v = dict(size=control.fighter_size(default=c.get('fighter_size', 128)), plates=control.plates_on(),
                 flash=control.flashes_on(default=c.get('flashes', True)), forge=control.forge_on(default=c.get('forge', True)),
                 rival=control.rival_on(default=c.get('rival', True)), winners=control.winners(),
                 results=ux.switch('results'), cards=ux.switch('cards'), signals=ux.switch('signals'),
                 startup=self.startup_state, zone=tuple(int(x) for x in c.get('zone', (40, 900))))
        if self.has_sound():
            try:
                v['sound'] = bool(control.sound_on())
            except Exception:
                v['sound'] = False
        return v

    def set(self, rid, value):
        from . import control, ux
        if rid == 'size':
            if int(value) == control.fighter_size(default=self.cfg.get('fighter_size', 128)):
                return None
            control.set_fighter_size(int(value))
            if self.restart is not None and self.restart():
                return 'restarting the fighters at the new size ...'
            return f'fighter size {value}: applies at the next start'
        if rid == 'plates':
            control.set_plates(bool(value))
        elif rid == 'flash':
            control.set_flashes(bool(value))
        elif rid == 'sound':
            control.set_sound(bool(value))
        elif rid == 'forge':
            control.set_forge(bool(value))
            return None if value else 'desktop weapons off: the arena takes no screen picture'
        elif rid == 'rival':
            control.set_rival(bool(value))
        elif rid == 'winners':
            control.set_winners(str(value))
        elif rid in ('results', 'cards', 'signals'):
            ux.set_switch(rid, bool(value))
        elif rid == 'startup':
            if self.startup is None:
                return 'not available here'

            def flip():
                ok, msg = (self.startup.enable() if value else self.startup.disable())
                self.message = msg
                self._read_startup()
            self._run('startup', flip)
            return 'working ...'
        elif rid == 'zone':
            if value == 'edit' and self.edit_zone is not None:
                self.edit_zone()
                return None
            if value == 'auto':
                ux.write_setting('zone', 'auto')
                if self.restart is not None and self.restart():
                    return 'zone back to auto: restarting ...'
                return 'zone back to auto: applies at the next start'
        return None


class Model:
    """The Settings window's state, layout, input and drawing."""

    def __init__(self, backend, now=0.0, is_mac=None, title='SETTINGS'):
        self.backend = backend
        self.rows = rows(backend.has_sound(), is_mac)
        self.values = backend.get()
        self.cur = 0
        self.hover = None
        self.phase = 'open'
        self.msg, self.msg_until = '', 0.0
        self.t0 = now
        self.title = title
        self.W = W
        self.rows_y = PAD + HEAD_H
        self.help_w = self.W - 2 * PAD - 6
        self.ys = []                                      # every help line is shown whole: rows grow to fit it
        y = self.rows_y
        for r in self.rows:
            n = max(len(wrap(h, self.help_w)) for h in self.help_variants(r))
            self.ys.append((y, y + LINE1_H + 11 * n + 3))
            y += LINE1_H + 11 * n + 5
        self.foot_y = y + 2
        self.H = self.foot_y + FOOT_H + PAD

    def help_variants(self, r):
        if r['id'] == 'startup':
            return [r['help']] + list(STARTUP_HELP.values())
        if r['id'] == 'zone':
            return ['x 10000 - 10000 px on the taskbar (10000 wide)']
        return [r['help']]

    def help_of(self, r, v):
        if r['id'] == 'startup':
            return STARTUP_HELP.get(v, r['help'])
        if r['id'] == 'zone' and isinstance(v, (tuple, list)):
            return f'x {v[0]} - {v[1]} px on the taskbar ({v[1] - v[0]} wide)'
        return r['help']

    def refresh(self):
        self.values = self.backend.get()

    # ---------------------------------------------------------- layout
    def row_rect(self, i):
        y0, y1 = self.ys[i]
        return PAD, y0, self.W - PAD, y1

    def controls(self, i):
        """-> [(name, value, rect)] of a row's clickable parts."""
        r = self.rows[i]
        x0, y0, x1, y1 = self.row_rect(i)
        cy = y0 + 1
        if r['kind'] == 'toggle':
            return [('toggle', None, (x1 - 46, cy, x1 - 4, cy + 13))]
        if r['kind'] == 'choice':
            out, x = [], x1 - 4
            f = font(9, True)
            probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
            for val, lab in reversed(r['choices']):
                w = int(probe.textlength(lab, font=f)) + 12
                out.append(('choice', val, (x - w, cy, x, cy + 13)))
                x -= w + 2
            return list(reversed(out))
        if r['kind'] == 'zone':
            return [('zone', 'edit', (x1 - 124, cy, x1 - 76, cy + 13)), ('zone', 'auto', (x1 - 72, cy, x1 - 4, cy + 13))]
        return []

    def close_rect(self):
        return self.W - PAD - 56, self.foot_y + 25, self.W - PAD, self.foot_y + 39

    def hit(self, x, y):
        cx0, cy0, cx1, cy1 = self.close_rect()
        if cx0 <= x <= cx1 and cy0 <= y <= cy1:
            return ('close', None, None)
        for i in range(len(self.rows)):
            for name, val, (a, b, c, d) in self.controls(i):
                if a <= x <= c and b <= y <= d:
                    return (name, val, i)
            x0, y0, x1, y1 = self.row_rect(i)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return ('row', None, i)
        return None

    # ---------------------------------------------------------- input
    def say(self, msg, now, secs=3.0):
        if msg:
            self.msg, self.msg_until = msg, now + secs

    def apply(self, i, value, now):
        r = self.rows[i]
        if r['id'] in self.backend.pending:
            return
        try:
            msg = self.backend.set(r['id'], value)
        except Exception as e:
            msg = f"{r['label']}: could not be changed ({type(e).__name__})"
        self.refresh()
        self.say(msg, now)

    def toggle(self, i, now, direction=0):
        r = self.rows[i]
        v = self.values.get(r['id'])
        if r['kind'] == 'toggle':
            cur = v == 'on' if r['id'] == 'startup' else bool(v)
            if r['id'] == 'startup' and v in ('other', 'unknown'):
                cur = False
            self.apply(i, not cur, now)
        elif r['kind'] == 'choice':
            vals = [c[0] for c in r['choices']]
            j = vals.index(v) if v in vals else 0
            self.apply(i, vals[(j + (direction or 1)) % len(vals)], now)
        elif r['kind'] == 'zone':
            self.apply(i, 'edit', now)

    def key(self, vk, now):
        if self.phase != 'open':
            return
        if vk == VK['esc']:
            self.phase = 'closed'
        elif vk in (VK['up'], VK['down']):
            self.cur = (self.cur + (-1 if vk == VK['up'] else 1)) % len(self.rows)
        elif vk in (VK['left'], VK['right']):
            r = self.rows[self.cur]
            if r['kind'] == 'choice':
                vals = [c[0] for c in r['choices']]
                v = self.values.get(r['id'])
                j = vals.index(v) if v in vals else 0
                j = max(0, min(len(vals) - 1, j + (-1 if vk == VK['left'] else 1)))
                if vals[j] != v:
                    self.apply(self.cur, vals[j], now)
            elif r['kind'] == 'toggle':
                want = vk == VK['right']
                v = self.values.get(r['id'])
                cur = v == 'on' if r['id'] == 'startup' else bool(v)
                if want != cur:
                    self.apply(self.cur, want, now)
        elif vk in (VK['enter'], VK['space']):
            self.toggle(self.cur, now)
        self.hover = None

    def click(self, x, y, now):
        h = self.hit(x, y)
        if h is None:
            return None
        name, val, i = h
        if name == 'close':
            self.phase = 'closed'
        elif name == 'toggle':
            self.cur = i
            self.toggle(i, now)
        elif name == 'choice':
            self.cur = i
            if val != self.values.get(self.rows[i]['id']):
                self.apply(i, val, now)
        elif name == 'zone':
            self.cur = i
            self.apply(i, val, now)
        elif name == 'row':
            self.cur = i
        return name

    def move(self, x, y):
        h = self.hit(x, y)
        self.hover = (h[0], h[1], h[2]) if h else None

    def frame_key(self, now):
        return (self.phase, self.cur, self.hover, tuple(sorted((k, str(v)) for k, v in self.values.items())),
                tuple(sorted(self.backend.pending)), self.msg if now < self.msg_until else '', self.backend.message,
                int(now * 3) % 2 if self.backend.pending else 0)

    def tick(self, now):
        if self.backend.message:
            self.say(self.backend.message, now, 4.0)
            self.backend.message = ''
            self.refresh()
        elif self.backend.pending or int(now) % 2 == 0:
            self.refresh()

    # ---------------------------------------------------------- drawing
    def _toggle(self, d, rect, on, pending=False, other=False):
        x0, y0, x1, y1 = rect
        col = (AMBER if other else ON) if on else OFF
        d.rounded_rectangle([x0, y0, x1, y1], 6, fill=col + (255,), outline=(20, 20, 26, 255))
        k = (x1 - 13, y0 + 1) if on else (x0 + 1, y0 + 1)
        d.rounded_rectangle([k[0], k[1], k[0] + 11, k[1] + 10], 5, fill=(240, 240, 248, 255))
        lab = '...' if pending else ('On' if on else 'Off')
        f = font(9, True)
        if on:
            text(d, (x0 + 5, y0), lab, (20, 30, 20), 9)
        else:
            text(d, (x1 - 5 - int(d.textlength(lab, font=f)), y0), lab, INK, 9)

    def render(self, now) -> Image.Image:
        im = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        d.rounded_rectangle([0, 0, self.W - 1, self.H - 1], 6, fill=BG, outline=EDGE)
        text(d, (PAD + 2, PAD - 2), self.title, INK, 11)
        sub = 'Taskbar Fighters'
        text(d, (self.W - PAD - int(d.textlength(sub, font=font(9, False))), PAD), sub, DIM, 9, False)
        d.line([(PAD, PAD + HEAD_H - 6), (self.W - PAD, PAD + HEAD_H - 6)], fill=(60, 60, 72, 255))
        for i, r in enumerate(self.rows):
            x0, y0, x1, y1 = self.row_rect(i)
            sel = i == self.cur
            if sel:
                d.rounded_rectangle([x0 - 3, y0 - 1, x1 + 3, y1], 3, fill=SEL, outline=(90, 90, 110, 255))
            v = self.values.get(r['id'])
            pend = r['id'] in self.backend.pending
            text(d, (x0 + 2, y0 + 1), r['label'], INK, 10)
            hcol = GREY if not sel else DIM
            if r['id'] == 'forge' and v:
                hcol = AMBER                                   # make it obvious while it is on
            for j, ln in enumerate(wrap(self.help_of(r, v), self.help_w)):
                text(d, (x0 + 2, y0 + LINE1_H + 1 + 11 * j), ln, hcol, 9, False)
            for name, val, rect in self.controls(i):
                hov = self.hover is not None and self.hover[2] == i and self.hover[1] == val and self.hover[0] == name
                if name == 'toggle':
                    on = (v == 'on') if r['id'] == 'startup' else bool(v)
                    self._toggle(d, rect, on, pend or (r['id'] == 'startup' and v == 'unknown'), other=r['id'] == 'forge' and on)
                elif name == 'choice':
                    lab = dict(r['choices'])[val]
                    on = v == val
                    d.rounded_rectangle(rect, 3, fill=((90, 90, 112) if on else (36, 36, 44)) + (255,),
                                        outline=(LINK + (255,)) if on else ((150, 150, 166, 255) if hov else (80, 80, 94, 255)))
                    text(d, (rect[0] + (rect[2] - rect[0] - int(d.textlength(lab, font=font(9, True)))) // 2, rect[1]), lab,
                         INK if on else DIM, 9)
                elif name == 'zone':
                    lab = 'Edit...' if val == 'edit' else 'Reset to auto'
                    d.rounded_rectangle(rect, 3, fill=((70, 70, 86) if hov else (40, 40, 50)) + (255,), outline=(130, 130, 146, 255))
                    text(d, (rect[0] + (rect[2] - rect[0] - int(d.textlength(lab, font=font(9, True)))) // 2, rect[1]), lab, INK, 9)
        msg = self.msg if now < self.msg_until else ''
        lines = wrap(msg, self.W - 2 * PAD - 4)[:2] if msg else ['Arrows choose   Enter / Space change   Esc close']
        for j, ln in enumerate(lines):
            text(d, (PAD + 2, self.foot_y + 11 * j + (5 if len(lines) == 1 else 0)), ln, AMBER if msg else GREY, 9, False)
        text(d, (PAD + 2, self.foot_y + 26), 'Every row is also a command: minis.py settings list', GREY, 9, False)
        cx0, cy0, cx1, cy1 = self.close_rect()
        hov = self.hover is not None and self.hover[0] == 'close'
        d.rounded_rectangle([cx0, cy0, cx1, cy1], 3, fill=((80, 80, 98) if hov else (52, 52, 64)) + (255,), outline=(150, 150, 166, 255))
        text(d, (cx0 + (cx1 - cx0 - int(d.textlength('Close', font=font(9, True)))) // 2, cy0 + 1), 'Close', INK, 9)
        return im


# ---------------------------------------------------------------- the fight-zone editor
MIN_ZONE_W = 600                         # plates (260) + scoreboard (154 inside the zone) + room for a bout
BAR_H = 30                               # the toolbar above the taskbar band
GRAB = 7


class ZoneEdit:
    """sw: screen width (logical px); band: taskbar band height (logical); zone: (z0, z1); plate_w: both plates' width;
    board_w: the scoreboard's width inside the zone (it sits at z1 + 36 - SB.W).  Coordinates are window-local: the window
    spans x 0..sw and y 0..BAR_H + band (the band is the taskbar)."""

    def __init__(self, sw, band, zone, plate_w=260, board=(190, 36), auto=(40, 900), now=0.0):
        self.sw, self.band = int(sw), int(band)
        self.z0, self.z1 = int(zone[0]), int(zone[1])
        self.orig = (self.z0, self.z1)
        self.auto = tuple(int(v) for v in auto)
        self.plate_w = int(plate_w)
        self.board_w, self.board_off = int(board[0]), int(board[1])
        self.W, self.H = self.sw, BAR_H + self.band
        self.drag = None                                    # ('left' | 'right' | 'bar', grab offset)
        self.hover = None
        self.phase = 'open'                                 # open -> save | auto | cancel
        self.t0 = now

    def clamp(self):
        self.z0 = max(0, min(self.z0, self.sw - MIN_ZONE_W))
        self.z1 = max(self.z0 + MIN_ZONE_W, min(self.z1, self.sw - 4))

    def _mid(self):
        return max(250, min(self.sw - 270, (self.z0 + self.z1) // 2))

    def buttons(self):
        mid = self._mid()
        y0, y1 = 6, BAR_H - 6
        return {'save': (mid + 70, y0, mid + 120, y1), 'auto': (mid + 124, y0, mid + 206, y1), 'cancel': (mid + 210, y0, mid + 260, y1)}

    def readout_x(self):
        return self._mid() - 240

    def hit(self, x, y):
        for k, (a, b, c, d) in self.buttons().items():
            if a <= x <= c and b <= y <= d:
                return k
        if y >= BAR_H:
            if abs(x - self.z0) <= GRAB:
                return 'left'
            if abs(x - self.z1) <= GRAB:
                return 'right'
            if self.z0 < x < self.z1:
                return 'bar'
            return 'band'
        r0 = self.readout_x()
        if r0 - 6 <= x <= r0 + 300 and y < BAR_H:
            return 'toolbar'
        return None

    def solid(self, x, y):
        """The window takes the mouse on the toolbar and the whole taskbar band (no taskbar clicks while editing)."""
        return y >= BAR_H or self.hit(x, y) is not None

    def on_event(self, kind, x, y, now=0.0):
        if self.phase != 'open':
            return
        if kind == 'down':
            h = self.hit(x, y)
            if h in ('left', 'right'):
                self.drag = (h, 0)
            elif h == 'bar':
                self.drag = ('bar', x - self.z0)
        elif kind == 'move':
            if self.drag:
                which, off = self.drag
                w = self.z1 - self.z0
                if which == 'left':
                    self.z0 = min(int(x), self.z1 - MIN_ZONE_W)
                elif which == 'right':
                    self.z1 = max(int(x), self.z0 + MIN_ZONE_W)
                else:
                    self.z0 = int(x - off)
                    self.z1 = self.z0 + w
                    if self.z0 < 0:
                        self.z0, self.z1 = 0, w
                    if self.z1 > self.sw - 4:
                        self.z1, self.z0 = self.sw - 4, self.sw - 4 - w
                self.clamp()
            self.hover = self.hit(x, y)
        elif kind == 'up':
            was = self.drag
            self.drag = None
            if not was:
                h = self.hit(x, y)
                if h in ('save', 'cancel', 'auto'):
                    self.phase = h

    def key(self, vk, now=0.0):
        if vk == VK['esc']:
            self.phase = 'cancel'
        elif vk == VK['enter']:
            self.phase = 'save'
        elif vk in (VK['left'], VK['right']):
            d = -10 if vk == VK['left'] else 10
            self.z0 += d
            self.z1 += d
            self.clamp()

    def result(self):
        return [int(self.z0), int(self.z1)]

    def frame_key(self, now):
        return (self.phase, self.z0, self.z1, self.hover, bool(self.drag), int(now * 2) % 2)

    def render(self, now):
        im = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.fontmode = '1'
        y0, y1 = BAR_H, self.H - 1
        d.rectangle([0, y0, self.W - 1, y1], fill=(0, 0, 0, 150))                      # a film over the whole taskbar
        z0, z1 = self.z0, self.z1
        d.rectangle([z0, y0, z1, y1], fill=(60, 120, 200, 70), outline=(140, 190, 255, 255), width=2)
        pw = min(self.plate_w, z1 - z0)
        d.rectangle([z0 + 2, y0 + 2, z0 + pw, y1 - 2], fill=(255, 196, 80, 40))
        text(d, (z0 + 8, y0 + (self.band - 10) // 2), 'plates', AMBER, 9)
        bx0 = z1 + self.board_off - self.board_w
        d.rectangle([max(z0 + pw + 2, bx0), y0 + 2, z1 - 2, y1 - 2], fill=(150, 220, 150, 36))
        text(d, (max(z0 + pw + 4, bx0 + 6), y0 + (self.band - 10) // 2), 'scoreboard', (150, 220, 150), 9)
        mid_l, mid_r = z0 + pw, max(z0 + pw, bx0)
        lab = 'fighters'
        if mid_r - mid_l > 60:
            text(d, ((mid_l + mid_r) // 2 - int(d.textlength(lab, font=font(10, True))) // 2, y0 + (self.band - 12) // 2), lab, INK, 10)
        for which, x in (('left', z0), ('right', z1)):
            hot = (self.drag and self.drag[0] == which) or self.hover == which
            col = (255, 255, 255, 255) if hot else (140, 190, 255, 255)
            d.rectangle([x - 3, y0, x + 3, y1], fill=col)
            for k in range(3):
                gy = y0 + self.band // 2 - 6 + k * 5
                d.rectangle([x - 1, gy, x, gy + 1], fill=(40, 60, 90, 255))
        # toolbar
        rx = self.readout_x()
        d.rounded_rectangle([rx - 6, 4, rx + 300, BAR_H - 4], 4, fill=(16, 16, 22, 236), outline=(110, 110, 128, 255))
        text(d, (rx, 7), f'Fight zone  x {z0} - {z1}  ({z1 - z0} px)', INK, 10)
        hint = 'drag the ends or the bar'
        text(d, (rx + 300 - 6 - int(d.textlength(hint, font=font(9, False))), 8), hint, DIM, 9, False)
        for k, (a, b, c, e) in self.buttons().items():
            lab = {'save': 'Save', 'auto': 'Reset to auto', 'cancel': 'Cancel'}[k]
            hot = self.hover == k
            fill = ((90, 170, 110) if k == 'save' else (60, 60, 74)) if not hot else ((120, 200, 140) if k == 'save' else (90, 90, 110))
            d.rounded_rectangle([a, b, c, e], 3, fill=fill + (255,), outline=(170, 170, 186, 255))
            text(d, (a + (c - a - int(d.textlength(lab, font=font(9, True)))) // 2, b + 3), lab, (16, 16, 20) if k == 'save' else INK, 9)
        return im
