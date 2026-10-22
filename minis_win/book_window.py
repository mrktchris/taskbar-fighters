"""The move book window (minis_core.collection.Book draws it).  Portable (shell injected), like select_window.py: a popup
above the fighters' band that takes the keyboard focus while it is open; Esc, a right-click or another window taking the
focus closes it."""
from __future__ import annotations

from .ux_window import ModelWindow, fit_scale


def open_book(shell, model, mono, scale=2, centre_x=None, on_close=None, stage=None):
    return ModelWindow(shell, model, mono, 'minis-book', scale=fit_scale(shell, model.W, model.H, scale, stage=stage),
                       centre_x=centre_x, on_close=on_close, stage=stage)
