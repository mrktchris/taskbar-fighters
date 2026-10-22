"""Window drivers for the UX layer: a pure model (minis_core: settings_ui, collection, guide, ...) shown in one of our own
layered windows.  Like select_window.py these take the backend `shell` as an argument and use only its Overlay surface
(present, move, show, reassert_topmost, focus, close), so the same code drives the Windows window class and the macOS
NSPanel; tests pass a fake shell and no real window is ever made by a test.

ModelWindow   a popup above the taskbar that may take the keyboard focus (Settings, the move book) - only while it is
              open, and only because the owner asked for it (a tray click, a menu item, a command)
ImagePopup    a click-through picture that never takes the mouse or the focus (hover card, results strip, a toast)
"""
from __future__ import annotations

MARGIN = 8
BLUR_GRACE_S = 1.0


def taskbar_top(shell, stage=None):
    """Screen y of the fighters' band's top edge: the stage's band (config.stage: the taskbar, or the strip beside a top /
    left / right taskbar) when the host passes one, else the taskbar rect (macOS: the Dock strip), else screen bottom - 48."""
    if stage and stage.get('band'):
        return int(stage['band'][0])
    l, t, r, b, edge = shell.taskbar_rect()
    if edge == 3:
        return t
    return shell.screen_size()[1] - 48


def area_of(shell, stage=None):
    """(x0, x1, top, monitor_top) the popups stay inside: the band's monitor (which may sit at negative x / y) when a stage is
    known, else the primary screen."""
    if stage and stage.get('monitor'):
        ml, mt, mr, mb = stage['monitor']
        return int(ml), int(mr), taskbar_top(shell, stage), int(mt)
    sw, sh = shell.screen_size()
    return 0, int(sw), taskbar_top(shell, stage), 0


def placement(shell, w, h, scale, centre_x=None, stage=None):
    """(x, y) screen px of a w x h (logical) popup just above the fighters' band, centred on centre_x, kept on its monitor."""
    x0, x1, top, mtop = area_of(shell, stage)
    pw, ph = w * scale, h * scale
    cx = (x0 + x1) // 2 if centre_x is None else int(centre_x)
    return max(x0 + MARGIN, min(x1 - pw - MARGIN, cx - pw // 2)), max(mtop + MARGIN, top - ph - MARGIN)


def fit_scale(shell, w, h, want, stage=None):
    """The largest whole-pixel scale <= want at which a w x h popup fits above the band."""
    try:
        x0, x1, top, mtop = area_of(shell, stage)
        sw, room = x1 - x0, top - mtop - 2 * MARGIN
    except Exception:
        return max(1, int(want))
    s = max(1, int(want))
    while s > 1 and (h * s > room or w * s > sw - 2 * MARGIN):
        s -= 1
    return s


class ModelWindow:
    """model: render(now) -> RGBA, frame_key(now), phase ('open' while shown), and any of click(x, y, now), move(x, y),
    wheel(delta, now), key(vk, now), tick(now).  on_close(model) runs once when it closes."""

    def __init__(self, shell, model, mono, title, scale=2, centre_x=None, xy=None, activatable=True, close_on_blur=True,
                 on_close=None, hittest=None, stage=None):
        self.shell, self.model, self.mono = shell, model, mono
        self.scale = max(1, int(scale))
        self.close_on_blur, self.on_close = close_on_blur, on_close
        self.closed = False
        self.opened = mono()
        x, y = xy if xy is not None else placement(shell, model.W, model.H, self.scale, centre_x, stage=stage)
        self.ov = shell.Overlay(title, x, y, model.W, model.H, scale=self.scale, on_event=self.on_event,
                                on_hittest=hittest or (lambda cx, cy: True), on_key=self.on_key if activatable else None,
                                activatable=activatable, on_blur=self.on_blur if activatable else None)
        now = mono()
        self.ov.present(model.render(now), x=x)
        self.last_key = model.frame_key(now)
        if activatable:
            try:
                self.ov.focus()
            except Exception:
                pass                                       # no focus: the mouse still works, and a click activates it

    def _call(self, name, *a):
        fn = getattr(self.model, name, None)
        if fn is not None:
            fn(*a)

    def on_event(self, kind, mx, my):
        now = self.mono()
        if kind == 'up':
            self._call('click', mx, my, now)
        elif kind == 'move':
            self._call('move', mx, my)
        elif kind == 'wheel':
            self._call('wheel', mx, now)
        elif kind == 'rclick':
            self.model.phase = 'closed'

    def on_key(self, vk):
        self._call('key', vk, self.mono())

    def on_blur(self):
        """Another window took the focus: close.  Not in the first moments after opening: when Windows refuses this process
        the foreground (opened from a command, not a click), the focus attempt itself ends in a deactivation, and the
        window must stay open until the owner clicks it or presses Esc."""
        if self.mono() - self.opened < BLUR_GRACE_S:
            return
        if self.close_on_blur and getattr(self.model, 'phase', None) == 'open':
            self.model.phase = 'closed'

    def step(self):
        """Advance and redraw on change.  -> False once the window is closed."""
        if self.closed:
            return False
        now = self.mono()
        self._call('tick', now)
        if getattr(self.model, 'phase', 'open') != 'open':
            self.close()
            return False
        k = self.model.frame_key(now)
        if k != self.last_key:
            self.ov.present(self.model.render(now))
            self.last_key = k
        self.ov.reassert_topmost()
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.ov.close()
        except Exception:
            pass
        if self.on_close is not None:
            try:
                self.on_close(self.model)
            except Exception:
                pass


class ImagePopup:
    """A click-through picture (no mouse, no focus): show(image, x, y), hide(), close().  Created on first show."""

    def __init__(self, shell, title, scale=1):
        self.shell, self.title, self.scale = shell, title, max(1, int(scale))
        self.ov = None
        self.shown = False
        self.key = None

    def show(self, img, x, y, key=None):
        if self.ov is None:
            self.ov = self.shell.Overlay(self.title, int(x), int(y), img.width // max(1, int(img.info.get('density', 1))),
                                         img.height // max(1, int(img.info.get('density', 1))), scale=self.scale,
                                         on_hittest=lambda cx, cy: False)
        if (int(x), int(y)) != (self.ov.x, self.ov.y):
            self.ov.move(int(x), int(y))
        if key is None or key != self.key or not self.shown:
            self.ov.present(img, x=int(x))
            self.key = key
        if not self.shown:
            self.ov.show(True)
            self.shown = True
        self.ov.reassert_topmost()

    def hide(self):
        if self.ov is not None and self.shown:
            self.ov.show(False)
        self.shown = False

    def close(self):
        if self.ov is not None:
            try:
                self.ov.close()
            except Exception:
                pass
        self.ov = None
        self.shown = False
