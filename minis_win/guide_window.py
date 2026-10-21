"""The first-run guide and the legend over the taskbar strip (minis_core.guide draws them).  Portable (shell injected).

One window spans the strip (plates .. scoreboard) and the rows just above the taskbar.  It never takes the keyboard focus
and only the cards take the mouse (Next / Skip, a click on the legend closes it); everything else clicks through to the
desktop and the taskbar."""
from __future__ import annotations

from .ux_window import ModelWindow, taskbar_top


def open_guide(shell, model, mono, scale=1, on_close=None):
    from minis_core import guide as G
    x = int(model.x0 * scale)
    y = taskbar_top(shell) - G.GH * scale
    return ModelWindow(shell, model, mono, 'minis-guide', scale=scale, xy=(x, y), activatable=False, close_on_blur=False,
                       on_close=on_close, hittest=lambda cx, cy: model.hit(cx, cy) is not None)
