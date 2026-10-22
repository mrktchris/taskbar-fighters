"""Open at login (macOS): the one LaunchAgent plist `minis.py autostart on|off` already manages (launchd.py), behind the same
small interface as minis_win.startup.Startup, so the Settings window's checkbox and `minis.py startup on|off` work the same
on both systems.  Written only on request; a plist that runs another copy is left alone."""
from __future__ import annotations

from . import launchd


class Startup:
    def __init__(self, python, root, argv=None, home=None):
        self.python, self.root, self.argv, self.home = python, root, argv, home

    @property
    def path(self):
        return launchd.plist_path(self.home)

    def status(self):
        p = self.path
        if not p.exists():
            return 'off', p
        try:
            ours = launchd.is_ours(p.read_bytes(), self.root, argv=self.argv)
        except OSError:
            ours = False
        return ('on' if ours else 'other'), p

    def enable(self):
        st, p = self.status()
        if st == 'on':
            return True, f'already on: {p}'
        if st == 'other':
            return False, f'{p} starts another copy: left alone'
        return launchd.install(self.python, self.root, self.home, argv=self.argv)

    def disable(self):
        st, p = self.status()
        if st == 'off':
            return True, 'already off'
        if st == 'other':
            return False, f'{p} starts another copy: left alone'
        return launchd.uninstall(self.root, self.home, argv=self.argv)
