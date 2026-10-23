"""The UX layer at run time: what the director and each fighter process do with it.  minis.py only hooks these in.

Host (director process, beside the scoreboard it already hosts):
  - opens the windows asked for through ux.json (tray, CLI, fighter menu): Settings, the zone editor, the move book, the
    legend, the replay, a GIF export (on a worker thread)
  - the first-run guide, once, a few seconds after the fighters first appear
  - the results strip over the scoreboard for 4 s after each match, and small toasts ("saved ... (its folder opens)"); exports go to <data folder>/exports
SlotUx (each fighter process):
  - event signals on its fighter (minis_core.signals), the hover card, the rival countdown on a sleeping plate, the
    post-match beat (victory pose / bow), the move book's "seen" notes, and storing a finished match for replays

Everything stays inside our own windows; no screen capture, nothing over the network, no focus stolen (only Settings and the
book take the keyboard, and only because the owner opened them).
"""
from __future__ import annotations
import logging, threading, time

from . import config as cfgmod, ux

AWAKE = ('working', 'idle', 'done', 'waiting')
FIRST_RUN_DELAY_S = 5.0
TOAST_S = 4.5


def _null_log():
    return logging.getLogger('minis.null')


# ======================================================================== the director side
class Host:
    def __init__(self, board, actions=None):
        self.b = board
        self.actions = dict(actions or {})
        self.log = getattr(board, 'log', None) or _null_log()
        self.win = {}
        self.last_req = None
        self.next_poll = -1e9
        self.next_results = -1e9
        self.shown_id = None
        self.strip = None
        self.strip_entry = None
        self.strip_t0 = 0.0
        self.toast = None
        self.toast_text = None
        self.toast_until = 0.0
        self.gif = None
        self.first_run_at = None
        self.lib = None
        self.after_zone = None

    # ---------------------------------------------------------- set-up
    def setup(self, now=None):
        req = ux.pending(now=self.b.wall())
        self.last_req = req and req.get('id')               # a request from before this process started is not replayed
        last = None
        try:
            from . import replay
            last = replay.last()
        except Exception:
            pass
        self.shown_id = last and last.get('id')             # never announce a match from before this start
        if not ux.first_run_done() and not ux.testing():
            self.first_run_at = (self.b.mono() if now is None else now) + FIRST_RUN_DELAY_S

    def library(self):
        if self.lib is None:
            self.lib = getattr(self.b, 'lib', None)
            if self.lib is None:
                from .atlas import Library
                self.lib = self.b.lib = Library()
        return self.lib

    # ---------------------------------------------------------- the loop
    def step(self):
        now = self.b.mono()
        for k, w in list(self.win.items()):
            try:
                alive = w.step()
            except Exception as e:
                self.log.error('ux window %s failed: %s', k, type(e).__name__)
                alive = False
                try:
                    w.close()
                except Exception:
                    pass
            if not alive:
                self.win.pop(k, None)
        if now >= self.next_poll:
            self.next_poll = now + 0.25
            req = ux.pending(now=self.b.wall())
            if req and req.get('id') != self.last_req:
                self.last_req = req.get('id')
                self.open(req['kind'], req.get('arg'))
        if self.first_run_at is not None and now >= self.first_run_at:
            if self.board_visible():
                self.first_run_at = None
                self.open('guide')
            else:
                self.first_run_at = now + 2.0
        if now >= self.next_results:
            self.next_results = now + 0.5
            self._check_results(now)
        self._draw_strip(now)
        self._draw_toast(now)

    def board_visible(self):
        ov = getattr(self.b, 'ov', None)
        return bool(ov is not None and getattr(ov, 'visible', False) and not getattr(self.b, 'hidden', True))

    # ---------------------------------------------------------- geometry
    def scale(self):
        g = getattr(self.b, 'g', None) or {}
        return int(g.get('scale', 1) or 1)

    def stage(self):
        """config.stage's layout for the scoreboard's band (any taskbar edge, DPI, its monitor), or None on a legacy shell."""
        g = getattr(self.b, 'g', None) or {}
        st = g.get('stage')
        return st if isinstance(st, dict) and st.get('band') else None

    def centre_x(self):
        cfg = self.b.cfg
        c = (cfg['zone'][0] + cfg['zone'][1]) // 2 * self.scale()
        try:
            import minis_platform as plat
            if plat.is_mac():
                c = int(self.b.shell.screen_size()[0]) // 2
        except Exception:
            pass
        return c

    def targets(self):
        """-> (span, targets {'fighter': x, 'plates': (x0, x1) | None, 'board': (x0, x1)}, names, plates_note) in logical px."""
        from . import bus, control, director, scoreboard as SB, sources
        cfg = self.b.cfg
        z0, z1 = cfg['zone']
        size = control.fighter_size(default=cfg.get('fighter_size', 128))
        k = size / 64.0
        bl = int(self.b.left()) if hasattr(self.b, 'left') else SB.left_x(cfg)
        a = bus.read('a', now=self.b.wall())
        fz = cfgmod.fight_zone(cfg, size)
        fx = float(a['x']) * k if a and a.get('x') is not None else (fz[0] + fz[1]) / 2.0 - 40 * k
        plates = (z0, z0 + 2 * cfgmod.PLATE_W + cfgmod.PLATE_SPACING)
        note = None
        try:
            import minis_platform as plat
            if plat.is_mac() and control.hud_position() == 'menubar':
                plates, note = None, 'they sit in the menu bar, beside the notch'
        except Exception:
            pass
        x0 = max(0, min(z0, bl) - 4)
        x1 = max(bl + SB.W, int(z1) + 36) + 4
        try:
            sw = int(self.b.shell.screen_size()[0]) // max(1, self.scale())
            x1 = min(x1, sw)
        except Exception:
            pass
        assign = director.read_assign() or {}
        names = {}
        for s in ('a', 'b'):
            sa = director.slot_assignment(assign, s)
            if sa:
                names[s] = sa.get('program') or sources.short_label(sa.get('source'))
        return (x0, x1), {'fighter': fx, 'plates': plates, 'board': (bl, bl + SB.W)}, names, note

    # ---------------------------------------------------------- windows
    def open(self, kind, arg=None):
        try:
            getattr(self, '_open_' + kind)(arg)
            self.log.info('ux: %s', kind)
        except Exception as e:
            self.log.error('ux: %s could not open (%s: %s)', kind, type(e).__name__, str(e)[:160])

    def _close(self, kind):
        w = self.win.pop(kind, None)
        if w is not None:
            w.close()

    def _open_settings(self, arg=None):
        from . import settings_ui
        from minis_win.settings_window import open_settings
        self._close('settings')
        startup = None
        make = self.actions.get('startup')
        if make is not None:
            try:
                startup = make()
            except Exception:
                startup = None
        be = settings_ui.Backend(self.b.cfg, startup=startup, restart=self.actions.get('restart'),
                                 edit_zone=lambda: self._edit_zone_from_settings(), log=self.log)
        model = settings_ui.Model(be, now=self.b.mono())
        self.win['settings'] = open_settings(self.b.shell, model, self.b.mono, scale=max(2, self.scale() * 2), centre_x=self.centre_x(),
                                           stage=self.stage())

    def _edit_zone_from_settings(self):
        w = self.win.get('settings')
        if w is not None:
            w.model.phase = 'closed'                     # the editor sits where the settings window would cover it
        self.after_zone = 'settings'
        self._open_zone()

    def _open_zone(self, arg=None):
        from . import scoreboard as SB, settings_ui
        from minis_win.settings_window import open_zone, zone_geometry
        self._close('zone')
        sc = self.scale()
        sw, band, x0, _ = zone_geometry(self.b.shell, sc, self.stage())
        cfg = self.b.cfg
        model = settings_ui.ZoneEdit(sw, band, cfg['zone'], plate_w=2 * cfgmod.PLATE_W + cfgmod.PLATE_SPACING, board=(SB.W, 36),
                                     auto=cfgmod.DEFAULTS['zone'], now=self.b.mono(), origin=x0 // max(1, sc))
        self.win['zone'] = open_zone(self.b.shell, model, self.b.mono, scale=sc, on_close=self._zone_done, stage=self.stage())

    def _zone_done(self, model):
        restart = self.actions.get('restart')
        if model.phase == 'save':
            z = model.result()
            if ux.write_setting('zone', z):
                self.say(f'zone saved: x {z[0]} - {z[1]}' + (' · restarting ...' if restart else ''))
                if restart:
                    restart()
            else:
                self.say('minis.json could not be written (is it valid JSON?)')
        elif model.phase == 'auto':
            ux.write_setting('zone', 'auto')
            self.say('zone back to auto' + (' · restarting ...' if restart else ''))
            if restart:
                restart()
        elif self.after_zone == 'settings':
            self.after_zone = None
            self._open_settings()

    def _open_book(self, arg=None):
        from . import collection, director, lineup
        from minis_win.book_window import open_book
        self._close('book')
        start = arg
        if not start:
            sa = director.slot_assignment(director.read_assign() or {}, 'a')
            start = sa.get('character') if sa else None
        model = collection.Book(lineup.characters(), collection.read(), self.library(), start=start, now=self.b.mono())
        self.win['book'] = open_book(self.b.shell, model, self.b.mono, scale=max(2, self.scale() * 2), centre_x=self.centre_x(), stage=self.stage())

    def _open_guide(self, arg=None, kind='guide'):
        from . import guide
        from minis_win.guide_window import open_guide
        self._close('guide')
        span, targets, names, note = self.targets()
        model = guide.Guide(kind, span, targets, names=names, now=self.b.mono(), plates_note=note)

        def done(m):
            if m.kind == 'guide':
                ux.set_first_run_done(True)              # shown (or skipped) once: never again on its own
        self.win['guide'] = open_guide(self.b.shell, model, self.b.mono, scale=self.scale(), on_close=done, stage=self.stage())

    def _open_legend(self, arg=None):
        self._open_guide(arg, kind='legend')

    def _open_replay(self, arg=None):
        from . import control, replay
        from minis_win.replay_window import ReplayWindow
        self._close('replay')
        try:
            plan, names, code, entry, warn = replay.resolve(arg)
        except replay.CodeError as e:
            self.say(f'replay: {e}')
            return
        if plan is None:
            self.say(warn or 'no match to replay yet')
            return
        if warn:
            self.say(warn)
        flashes = control.flashes_on(default=self.b.cfg.get('flashes', True))
        summary = None
        self.win['replay'] = ReplayWindow(self.b.shell, lambda: replay.frames(plan, 'final', fps=20, names=names, code=code, flashes=flashes,
                                                                               summary=summary),
                                          self.b.mono, centre_x=self.centre_x(), scale=self.scale(), log=self.log, stage=self.stage())

    def _open_gif(self, arg=None):
        from . import control, replay
        if self.gif is not None and self.gif.is_alive():
            self.say('a GIF is already being made ...')
            return
        try:
            plan, names, code, entry, warn = replay.resolve(arg)
        except replay.CodeError as e:
            self.say(f'GIF: {e}')
            return
        if plan is None:
            self.say(warn or 'no match to save yet')
            return
        flashes = control.flashes_on(default=self.b.cfg.get('flashes', True))
        out = replay.exports_dir() / replay.gif_name(plan)
        if not replay.inside_exports(out):                    # cannot happen with safe_id names; refused rather than trusted
            self.say('GIF refused: the output would leave the exports folder')
            return
        self.say('making the GIF ... (a few seconds)', 30.0)

        def work():
            try:
                p, n = replay.save_gif(replay.frames(plan, 'all', fps=12, names=names, code=code, flashes=flashes, label='TASKBAR FIGHTERS'), out)
                self.say(f'saved {p.name} (its folder opens)')
                self.log.info('gif: %d frames written to the exports folder', n)
                replay.reveal(p)
            except Exception as e:
                self.say(f'GIF failed ({type(e).__name__})')
                self.log.error('gif failed: %s', type(e).__name__)
        self.gif = threading.Thread(target=work, name='minis-gif', daemon=True)
        self.gif.start()

    # ---------------------------------------------------------- results strip + toasts
    def _check_results(self, now):
        from . import control, replay, results
        try:
            e = replay.last()
        except Exception:
            return
        if not results.fresh(e, self.b.wall(), self.shown_id):
            return
        self.shown_id = e.get('id')
        if not ux.switch('results') or control.paused() or not self.board_visible():
            return
        self.strip_entry, self.strip_t0 = e, now

    def strip_xy(self, w, h):
        sc = self.scale()
        from . import scoreboard as SB
        right = (int(self.b.left()) + SB.W) * sc
        g = getattr(self.b, 'g', None) or {}
        y = int(g.get('y', 0)) - h * sc - 4
        return right - w * sc, y

    def _draw_strip(self, now):
        from . import results
        if self.strip_entry is None:
            return
        t = now - self.strip_t0
        if t >= results.SHOW_S or not self.board_visible():
            self.strip_entry = None
            if self.strip is not None:
                self.strip.hide()
            return
        if self.strip is None:
            from minis_win.ux_window import ImagePopup
            self.strip = ImagePopup(self.b.shell, 'minis-results', scale=self.scale())
        im = results.render(self.strip_entry, t, self.library())
        x, y = self.strip_xy(im.width, im.height)
        self.strip.show(im, x, results.slide_y(t, y, self.scale()), key=(self.strip_entry.get('id'), int(t * 10)))

    def say(self, msg, secs=TOAST_S):
        self.toast_text = str(msg)
        self.toast_until = self.b.mono() + secs

    def _draw_toast(self, now):
        if not self.toast_text:
            return
        if now >= self.toast_until:
            self.toast_text = None
            if self.toast is not None:
                self.toast.hide()
            return
        if self.toast is None:
            from minis_win.ux_window import ImagePopup
            self.toast = ImagePopup(self.b.shell, 'minis-toast', scale=self.scale())
        im = toast_image(self.toast_text)
        x, y = self.strip_xy(im.width, im.height + (46 if self.strip_entry else 0))
        self.toast.show(im, x, y, key=self.toast_text)

    def close(self):
        for w in list(self.win.values()):
            try:
                w.close()
            except Exception:
                pass
        self.win.clear()
        for p in (self.strip, self.toast):
            if p is not None:
                p.close()


def toast_image(msg):
    from PIL import Image, ImageDraw
    from .render import font, text, wrap
    lines = wrap(msg, 400, 9, True)                                    # whole messages, wrapped, never cut
    w = int(max(font(9, True).getlength(ln) for ln in lines)) + 16
    h = 7 + 11 * len(lines)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], 4, fill=(16, 16, 22, 236), outline=(120, 120, 136, 255))
    for j, ln in enumerate(lines):
        text(d, (8, 3 + 11 * j), ln, (236, 236, 244), 9)
    return im


# ======================================================================== the fighter side
class SlotUx:
    """One fighter process's share of the UX layer.  Every call is guarded: a UX problem never stops a fighter."""

    def __init__(self, fighter):
        from . import collection, hovercard, signals
        self.f = fighter
        self.sig = signals.Signals(getattr(fighter, 'cfg', {}))
        self.dwell = hovercard.Dwell()
        self.card = None
        self.card_target = None
        self.tracker = collection.Tracker()
        self.state = None
        self.since = None                    # wall time the current state started (the hover card's "· 3 min")
        self.sigkey = None
        self.next_switch = -1e9
        self.on = {'signals': True, 'cards': True}
        self.quiet = False
        self.next_hover = -1e9
        self.next_beat = -1e9
        self.beat_done = None
        self.next_flush = -1e9
        self.failed = set()
        self.log = getattr(fighter, 'log', None) or _null_log()
        try:
            from . import replay
            last = replay.last()
            self.beat_done = last and last.get('id')       # a match from before this start gets no taskbar beat
        except Exception:
            pass

    def _guard(self, what, fn, *a, default=None):
        try:
            return fn(*a)
        except Exception as e:
            if what not in self.failed:
                self.failed.add(what)
                self.log.error('ux %s failed: %s', what, type(e).__name__)
            return default

    # ---------------------------------------------------------- hooks called from minis.Fighter
    def on_snapshot(self, snap, now, wall):
        self._guard('snapshot', self._on_snapshot, snap, now, wall)

    def _on_snapshot(self, snap, now, wall):
        st = getattr(snap, 'state', None)
        if st != self.state:
            self.state, self.since = st, wall
        if self.on['signals']:
            self.sig.on_snapshot(snap, now, paused=bool(getattr(self.f, 'paused', False)))

    def decorate(self, v, now):
        out = self._guard('signals', self._decorate, v, now)
        return v if out is None else out

    def _decorate(self, v, now):
        f = self.f
        if not self.on['signals'] or f.assigned is None or f.brain is None:
            return v
        ov, anim = self.sig.overlays(v, f.brain.atlas, now, paused=f.paused, flashes=bool(getattr(f, 'flash', True)), quiet=self.quiet)
        key = self.sig.key(now, paused=f.paused, still=self.quiet)
        if key != self.sigkey:
            self.sigkey = key
            f.last['sig'] = None                           # the mark changed: redraw now
        if not ov:
            return v
        v = dict(v)
        v['fx'] = list(v.get('fx') or []) + ov
        if anim:
            v['busy'] = True
        return v

    def step(self, now, wall):
        self._guard('step', self._step, now, wall)

    def _step(self, now, wall):
        f = self.f
        if now >= self.next_switch:
            self.next_switch = now + 2.0
            self.on = {'signals': ux.switch('signals'), 'cards': ux.switch('cards')}
            self.quiet = ux.quiet()
        b = f.brain
        if b is None or f.assigned is None:
            self._hide_card()
            return
        self.tracker.note_move(b.character, b.anim, wall)
        if now >= self.next_flush:
            self.next_flush = now + 10.0
            self.tracker.flush(now)
        free = self._free()
        if free:
            for mv in self.sig.take_moves():
                if mv in b.atlas.anim:
                    b.play(mv, now, loop=False)
                    break
        elif f.paused:
            self.sig.take_moves()
        if now >= self.next_beat:
            self.next_beat = now + 0.5
            self._beat(now, wall, free)
        if now >= self.next_hover:
            self.next_hover = now + 0.1
            self._hover(now, wall)

    def _free(self):
        b = self.f.brain
        return bool(not self.f.paused and b.mode == 'home' and b.script is None and b.bout is None and b.pending is None
                    and b.anim in ('idle', 'wait', 'rage', 'work', 'type', 'powerup', 'sleep'))

    def _beat(self, now, wall, free):
        from . import replay, results
        e = replay.last()
        if not e or e.get('id') == self.beat_done:
            return
        if wall - float(e.get('ts', 0)) > 12.0:
            self.beat_done = e.get('id')
            return
        if not free:
            return
        self.beat_done = e.get('id')
        mv = results.taskbar_beat(e, (self.f.assigned or {}).get('source'), self.f.slot)
        b = self.f.brain
        if mv == 'victory' and 'victory2' in b.atlas.anim:
            mv = 'victory2'
        if mv and mv in b.atlas.anim:
            b.play(mv, now, loop=False)

    # ---------------------------------------------------------- hover card
    def fighter_rect(self):
        f = self.f
        if f.ov is None or not f.ov.visible or f.g is None:
            return None
        sc = f.g['scale']
        k = f.k
        cx = f.brain.x * k * sc
        atlas = f.brain.atlas
        win_top = f.g['y']
        feet = win_top + (cfgmod.headroom_px(f.size) + getattr(atlas, 'ground_y', 57) * k) * sc
        return (cx - 15 * k * sc, feet - 48 * k * sc, cx + 15 * k * sc, feet)

    def plate_rect(self):
        f = self.f
        p = f.pov
        if p is None or not p.visible:
            return None
        sc = f.g['scale'] if f.g else 1
        return (p.x, p.y, p.x + cfgmod.PLATE_W * sc, p.y + cfgmod.PLATE_H * sc)

    def _hover(self, now, wall):
        f = self.f
        fn = getattr(f.shell, 'cursor_pos', None)
        cur = None
        if fn is not None and not f.hidden:
            try:
                cur = fn()
            except Exception:
                cur = None
        target = None
        rects = {'fighter': self.fighter_rect(), 'plate': self.plate_rect()}
        if cur is not None:
            for name, r in rects.items():
                if r and r[0] <= cur[0] <= r[2] and r[1] <= cur[1] <= r[3]:
                    target = name
                    break
        if target is not None and self.sig.flag:
            self.sig.hovered(now)                          # the done flag has been seen
            f.last['sig'] = None
        visible = self.dwell.update(target if self.on['cards'] else None, now)
        if not visible or rects.get(self.dwell.target) is None:
            self._hide_card()
            return
        info = self.card_info(wall)
        from . import hovercard
        img = hovercard.render(info, k=getattr(f, 'hud_k', 1))
        sc = f.g['scale'] if f.g else 1
        try:
            sw = int(f.shell.screen_size()[0])
        except Exception:
            sw = 4000
        below = self.dwell.target == 'plate' and getattr(f, 'hud_pos', 'dock') == 'menubar'
        dens = max(1, int(img.info.get('density', 1)))
        x, y = hovercard.place(rects[self.dwell.target], img.width // dens * sc, img.height // dens * sc, sw, below=below)
        if self.card is None:
            from minis_win.ux_window import ImagePopup
            self.card = ImagePopup(f.shell, f'minis-{f.slot}-card', scale=sc)
        self.card.show(img, x, y, key=tuple(sorted((k, str(v)) for k, v in info.items())))

    def _hide_card(self):
        if self.card is not None:
            self.card.hide()

    def card_info(self, wall):
        from . import director, records, replay, sources
        f = self.f
        a = f.assigned or {}
        snap = f.snap
        src = a.get('source')
        st = getattr(snap, 'state', None) or 'sleeping'
        info = dict(name=f.display_name(), accent=tuple(f.brain.atlas.accent), state=st,
                    since_s=(wall - self.since) if self.since is not None else None,
                    ctx=getattr(snap, 'ctx_pct', None), plan_pct=getattr(snap, 'plan_pct', None), plan_label=getattr(snap, 'plan_label', ''),
                    resets_in=getattr(snap, 'resets_in', '') or None, waiting_s=f.cfg.get('waiting_seconds', 45),
                    dormant=bool(a.get('dormant')), bot=bool(a.get('bot')), process=src not in ('claude', 'codex'), flag=self.sig.flag)
        if src and not a.get('bot'):
            info['record'] = records.for_program(records.read(), src)
            other = director.slot_assignment(director.read_assign(getattr(f, 'assign_path', None)), 'b' if f.slot == 'a' else 'a')
            if other and other.get('source'):
                info['opponent'] = sources.short_label(other['source'], other.get('program'))
                info['h2h'] = replay.h2h(src, other['source'])
            try:
                from . import learning
                info['learned'] = learning.summary_line(src)          # 'learned 3 moves', or None
            except Exception:
                pass
        ri = self.rival_left(wall)
        if ri is not None:
            info['rival_in'], info['rival_kind'] = ri
        return info

    # ---------------------------------------------------------- rival countdown
    def publish_extra(self, pub, wall):
        """Add the rival countdown to this fighter's bus payload when it is the awake side of a rival pairing."""
        r = self._guard('publish', self._rival_out, default=None)
        if r:
            pub = dict(pub, rival_in=r[0], rival_kind=r[1])
        return pub

    def _rival_out(self):
        f = self.f
        b, p = f.brain, f.partner
        if b is None or not p or not getattr(b, 'rival', True) or p.get('state') != 'sleeping' or b.state() not in AWAKE:
            return None
        working = b.state() == 'working'
        due = (b.next_rival_spar if working else b.next_rival) - f.mono()
        return max(0, int(round(due))), ('clash' if working else 'match')

    def rival_left(self, wall):
        """-> (seconds, kind) until the partner wakes this sleeping fighter, or None."""
        p = self.f.partner
        if not p or self.state != 'sleeping' or p.get('rival_in') is None:
            return None
        try:
            left = float(p['rival_in']) - max(0.0, wall - float(p.get('ts', wall)))
        except (TypeError, ValueError):
            return None
        return max(0.0, left), p.get('rival_kind') or 'match'

    # ---------------------------------------------------------- the plate
    def plate_snap(self, snap, now):
        out = self._guard('plate', self.sig.plate_snap, snap, now)
        return snap if out is None else out

    def plate_key(self, now, wall):
        r = self.rival_left(wall)
        from .hovercard import rival_minutes
        refill = self.sig.second is not None and now - self.sig.second[0] < 1.7
        return (rival_minutes(r[0]) if r else None, r[1] if r else None, int(now * 12) if refill else 0)

    def plate_image(self, base, wall):
        """The plate with its second line replaced by the rival countdown while this fighter sleeps and one is due."""
        r = self.rival_left(wall)
        if r is None:
            return base
        out = self._guard('plate', _rival_plate, base, r)
        return base if out is None else out

    # ---------------------------------------------------------- a finished match
    def on_record(self):
        self._guard('record', self._on_record)

    def _on_record(self):
        from . import director, replay, sources
        f = self.f
        b = f.brain
        plan = (b.script or {}).get('plan') if b is not None else None
        summ = getattr(b, 'last_match', None)
        if not plan or plan.get('kind') != 'match' or not summ:
            return
        mine = (f.assigned or {}).get('source')
        o = 'b' if f.slot == 'a' else 'a'
        other = director.slot_assignment(director.read_assign(getattr(f, 'assign_path', None)), o) or {}
        progs = {f.slot: mine, o: other.get('source')}
        labels = {f.slot: sources.short_label(mine, (f.assigned or {}).get('program')) if mine else None,
                  o: sources.short_label(other.get('source'), other.get('program')) if other.get('source') else None}
        e = replay.store(plan, summ, progs, labels)
        chars = list((plan.get('chars') or {}).values())
        ko_win = (plan.get('chars') or {}).get(summ.get('winner')) if summ.get('final_ko') else None
        self.tracker.note_match(chars, ((e or {}).get('stats') or {}).get('pieces') or (summ.get('story') or {}).get('pieces') or [],
                                ko_win, time.time())
        self.tracker.flush(0, force=True)

    def close(self):
        self._guard('close', self._close)

    def _close(self):
        if self.card is not None:
            self.card.close()
        self.tracker.flush(0, force=True)


def _rival_plate(base, r):
    """Paint 'rival match in ~6 min' over the plate's second line (same plate background, same small font)."""
    from PIL import ImageDraw
    from .hovercard import rival_minutes
    from .render import KDraw, text
    im = base.copy()
    k = int(base.info.get('density', 1) or 1)
    d = KDraw(im, k) if k > 1 else ImageDraw.Draw(im)
    w = base.width // k
    d.rectangle([3, 14, w - 4, 23], fill=(18, 18, 22, 200 if k == 1 else 242))      # below the state word's descenders
    what = 'rival bout' if r[1] == 'clash' else 'rival match'
    text(d, (5, 13), f'{what} in ~{rival_minutes(r[0])}', (140, 190, 255), 9, False)
    if k > 1:
        im.info['density'] = k
    return im
