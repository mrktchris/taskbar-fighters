"""The fighter-select popup window: one layered, topmost window ABOVE the taskbar showing minis_core.select.Model.

It is the one minis window that takes the keyboard focus, and only while it is open: it is created activatable, asks for
the foreground once (it was opened by the owner's own click, so Windows allows it), and cancels itself when another
window takes the focus.  It draws only its own pixels (portraits from our sheets, text, frames).  `shell` is injectable:
tests pass a fake with an Overlay class, so no real window is ever created by a test.
"""
from __future__ import annotations

MARGIN = 8


def placement(shell, w, h, scale, centre_x=None, area=None):
    """-> (x, y) in screen px for a w x h (logical) popup: just above the taskbar, centred on `centre_x` (screen px), kept
    on the primary screen.  area=(x0, x1, top) (physical px, from config.stage: the fighters' band and its monitor's x span)
    places it above that band instead - any taskbar edge, any monitor."""
    pw, ph = w * scale, h * scale
    if area is not None:
        x0, x1, top = (int(v) for v in area)
    else:
        l, t, r, b, edge = shell.taskbar_rect()
        sw, sh = shell.screen_size()
        x0, x1, top = 0, sw, (t if edge == 3 else sh)
    cx = (x0 + x1) // 2 if centre_x is None else int(centre_x)
    x = max(x0 + MARGIN, min(x1 - pw - MARGIN, cx - pw // 2))
    y = max(MARGIN, top - ph - MARGIN)
    return x, y


class SelectWindow:
    def __init__(self, shell, model, mono, on_done, scale=2, centre_x=None, area=None):
        """on_done(model) is called once, when the last player confirms (model.phase == 'vs'); the window closes itself
        after the VS card, or at once on cancel."""
        self.shell, self.model, self.mono, self.on_done = shell, model, mono, on_done
        self.scale = max(1, int(scale))
        self.done_called = False
        self.closed = False
        self.last_key = None
        x, y = placement(shell, model.W, model.H, self.scale, centre_x, area=area)
        self.ov = shell.Overlay('minis-select', x, y, model.W, model.H, scale=self.scale, on_event=self.on_event,
                                on_hittest=lambda cx, cy: True, on_key=self.on_key, activatable=True, on_blur=self.on_blur)
        self.ov.present(model.render(mono()), x=x)
        self.last_key = model.frame_key(mono())
        try:
            self.ov.focus()
        except Exception:
            pass                                          # no focus: the mouse still works, and a click activates it

    def on_event(self, kind, mx, my):
        now = self.mono()
        if kind == 'up':
            self.model.click(mx, my, now)
        elif kind == 'move':
            self.model.move(mx, my)
        elif kind == 'wheel':
            self.model.wheel(mx, now)
        elif kind == 'rclick':
            self.model.cancel(now)

    def on_key(self, vk):
        self.model.key(vk, self.mono())

    def on_blur(self):
        self.model.cancel(self.mono())

    def step(self):
        """Advance, write the result once, redraw on change.  -> False once the window is closed."""
        if self.closed:
            return False
        now = self.mono()
        m = self.model
        m.tick(now)
        if m.phase in ('vs', 'done') and not self.done_called:
            self.done_called = True
            try:
                self.on_done(m)
            except Exception:
                pass
        if m.phase in ('done', 'cancel'):
            self.close()
            return False
        k = m.frame_key(now)
        if k != self.last_key:
            self.ov.present(m.render(now))
            self.last_key = k
        self.ov.reassert_topmost()
        return True

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.ov.close()
            except Exception:
                pass
