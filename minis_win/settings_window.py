"""The Settings window and the fight-zone editor (minis_core.settings_ui draws both).  Portable: the backend `shell` is
injected (Windows layered window or macOS NSPanel), exactly like select_window.py.

SettingsWindow  a popup above the fighters' band that takes the keyboard focus while it is open (it was opened by the
                owner); it closes on Esc, Close, a right-click or when another window takes the focus.
ZoneWindow      a strip the width of the band's monitor over the band and a toolbar just above it: the whole band takes the
                mouse while it is open (no taskbar clicks get through by accident), the desktop above it stays click-through
                except the toolbar.  Arrow keys nudge the zone by 10 px, Enter saves, Esc cancels.
`stage` is config.stage's layout (any taskbar edge, DPI, the band's monitor) when the host has one; without it the band is
the bottom taskbar (macOS: the Dock strip).
"""
from __future__ import annotations

from .ux_window import ModelWindow, area_of, fit_scale, taskbar_top


def open_settings(shell, model, mono, scale=2, centre_x=None, on_close=None, stage=None):
    s = fit_scale(shell, model.W, model.H, scale, stage=stage)
    return ModelWindow(shell, model, mono, 'minis-settings', scale=s, centre_x=centre_x, on_close=on_close, stage=stage)


def zone_geometry(shell, scale=1, stage=None):
    """-> (band width in logical px, band height in logical px, window x, window y) for the zone editor."""
    from minis_core import settings_ui as S
    if stage and stage.get('band'):
        t, b = stage['band']
        x0, x1, top, _ = area_of(shell, stage)
    else:
        sw, sh = shell.screen_size()
        l, t, r, b, edge = shell.taskbar_rect()
        if edge != 3:
            b, t = sh, sh - 48
        x0, x1, top = 0, sw, taskbar_top(shell)
    band = max(24, int(b - t) // max(1, scale))
    return (x1 - x0) // max(1, scale), band, int(x0), top - S.BAR_H * scale


class ZoneWindow(ModelWindow):
    """The zone editor needs press / drag / release, not just clicks: the model's on_event gets every mouse event.  It
    closes when the model leaves 'open' (save | auto | cancel); on_close(model) acts on that."""

    def on_event(self, kind, mx, my):
        now = self.mono()
        if kind in ('down', 'move', 'up'):
            self.model.on_event(kind, mx, my, now)
        elif kind == 'rclick':
            self.model.phase = 'cancel'


def open_zone(shell, model, mono, scale=1, on_close=None, stage=None):
    _, _, x, y = zone_geometry(shell, scale, stage)
    return ZoneWindow(shell, model, mono, 'minis-zone', scale=scale, xy=(x, y), close_on_blur=False, on_close=on_close,
                      hittest=lambda cx, cy: model.solid(cx, cy))
