"""Instant replay above the taskbar (UX item 7): the last match's deciding exchange and K.O., played again from its plan by
the same planner and renderer, on the neutral backdrop (minis_core.replay) - never a screen capture.  The frames are made on
a worker thread so the director's loop (the scoreboard, the tray) never waits; the window plays them as they arrive.

A click (or a right-click) closes it; it closes itself 1.5 s after the last frame.  It never takes the keyboard focus.
Portable: `shell` is injected, like select_window.py."""
from __future__ import annotations
import threading
from collections import deque

from .ux_window import placement


class ReplayWindow:
    def __init__(self, shell, frames_fn, mono, centre_x=None, scale=1, log=None, title='minis-replay', stage=None):
        """frames_fn() -> an iterable of (RGBA image, ms) - minis_core.replay.frames(...) bound to a plan."""
        from minis_core import replay
        self.shell, self.mono, self.log = shell, mono, log
        self.scale = max(1, int(scale))
        self.q = deque()
        self.done = False
        self.closed = False
        self.error = None
        self.shown = 0
        self.next_t = None
        self.end_t = None
        x, y = placement(shell, replay.W, replay.H, self.scale, centre_x, stage=stage)
        self.ov = shell.Overlay(title, x, y, replay.W, replay.H, scale=self.scale, on_event=self.on_event,
                                on_hittest=lambda cx, cy: True)
        first = replay.backdrop()
        self.ov.present(first, x=x)

        def work():
            try:
                for item in frames_fn():
                    if self.closed:
                        return
                    self.q.append(item)
            except Exception as e:                             # a broken plan / missing art: say so in the log, close
                self.error = f'{type(e).__name__}: {str(e)[:160]}'
            finally:
                self.done = True
        self.thread = threading.Thread(target=work, name='minis-replay', daemon=True)
        self.thread.start()

    def on_event(self, kind, mx, my):
        if kind in ('up', 'rclick'):
            self.close()

    def step(self):
        """-> False once closed."""
        if self.closed:
            return False
        now = self.mono()
        if self.error and not self.q:
            if self.log:
                self.log.info('replay: %s', self.error)
            self.close()
            return False
        if self.q and (self.next_t is None or now >= self.next_t):
            im, ms = self.q.popleft()
            self.ov.present(im)
            self.shown += 1
            self.next_t = (now if self.next_t is None else max(now - 0.2, self.next_t)) + ms / 1000.0
        elif self.done and not self.q:
            if self.end_t is None:
                self.end_t = now + 1.5
            elif now >= self.end_t:
                self.close()
                return False
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
