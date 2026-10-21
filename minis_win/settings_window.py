"""The Settings window and the fight-zone editor (minis_core.settings_ui draws both).  Portable: the backend `shell` is
injected (Windows layered window or macOS NSPanel), exactly like select_window.py.

SettingsWindow  a popup above the taskbar that takes the keyboard focus while it is open (it was opened by the owner);
                it closes on Esc, Close, a right-click or when another window takes the focus.
ZoneWindow      a strip the width of the screen over the taskbar band and a toolbar just above it: the whole band takes the
                mouse while it is open (no taskbar clicks get through by accident), the desktop above it stays click-through
                except the toolbar.  Arrow keys nudge the zone by 10 px, Enter saves, Esc cancels.
"""
from __future__ import annotations

from .ux_window import ModelWindow, fit_scale, taskbar_top


def open_settings(shell, model, mono, scale=2, centre_x=None, on_close=None):
    s = fit_scale(shell, model.W, model.H, scale)
    return ModelWindow(shell, model, mono, 'minis-settings', scale=s, centre_x=centre_x, on_close=on_close)


def zone_geometry(shell, scale=1):
    """-> (screen width in logical px, band height in logical px, window x, window y) for the zone editor."""
    from minis_core import settings_ui as S
    sw, sh = shell.screen_size()
    l, t, r, b, edge = shell.taskbar_rect()
    if edge != 3:
        b, t = sh, sh - 48
    band = max(24, (b - t) // max(1, scale))
    return sw // max(1, scale), band, 0, taskbar_top(shell) - S.BAR_H * scale


class ZoneWindow(ModelWindow):
    """The zone editor needs press / drag / release, not just clicks: the model's on_event gets every mouse event.  It
    closes when the model leaves 'open' (save | auto | cancel); on_close(model) acts on that."""

    def on_event(self, kind, mx, my):
        now = self.mono()
        if kind in ('down', 'move', 'up'):
            self.model.on_event(kind, mx, my, now)
        elif kind == 'rclick':
            self.model.phase = 'cancel'


def open_zone(shell, model, mono, scale=1, on_close=None):
    _, _, x, y = zone_geometry(shell, scale)
    return ZoneWindow(shell, model, mono, 'minis-zone', scale=scale, xy=(x, y), close_on_blur=False, on_close=on_close,
                      hittest=lambda cx, cy: model.solid(cx, cy))
