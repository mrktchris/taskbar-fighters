r"""Start with Windows: one "Taskbar Fighters.lnk" in the user's Startup folder (shell:startup), the same shortcut
`minis.py shortcut` writes to the Start menu.  Only on request (the Settings checkbox or `minis.py startup on`).

- An existing "Taskbar Fighters.lnk" that runs THIS copy (`"<root>\minis.py" start`, or this executable) is reused: turning it
  on again writes nothing, so there is never a second entry.
- One that runs ANOTHER copy is left alone and reported (it is not ours to replace or remove).
- Off deletes it only when it is ours.

The shortcut work (reading, writing a .lnk) goes through callables injected by minis.py (read_shortcut / write_shortcut /
shortcut_is_ours / shortcut_spec), so this module never runs PowerShell itself and tests pass fakes.
"""
from __future__ import annotations
import os
from pathlib import Path

NAME = 'Taskbar Fighters.lnk'


def startup_dir():
    base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    return Path(base) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


class Startup:
    """reader(path) -> (target, arguments) | None; writer(path, spec) -> bool; is_ours(target, arguments) -> bool;
    spec() -> the shortcut fields; folder: the Startup folder (injectable)."""

    def __init__(self, reader, writer, is_ours, spec, folder=None):
        self.reader, self.writer, self.is_ours, self.spec = reader, writer, is_ours, spec
        self.folder = Path(folder) if folder else startup_dir()

    @property
    def path(self):
        return self.folder / NAME

    def status(self):
        """-> ('on' | 'off' | 'other', path).  'other': a Taskbar Fighters.lnk for another copy is there."""
        p = self.path
        if not p.exists():
            return 'off', p
        got = self.reader(p)
        return ('on' if got and self.is_ours(*got) else 'other'), p

    def enable(self):
        st, p = self.status()
        if st == 'on':
            return True, f'already on: reusing {p}'
        if st == 'other':
            return False, f'{p} starts another copy of Taskbar Fighters: left alone (remove it yourself to use this one)'
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.writer(p, self.spec()):
            return True, f'on: {p}'
        return False, f'{p}: could not be written'

    def disable(self):
        st, p = self.status()
        if st == 'off':
            return True, 'already off'
        if st == 'other':
            return False, f'{p} starts another copy: left alone'
        try:
            p.unlink()
        except OSError as e:
            return False, f'{p}: could not be removed ({type(e).__name__})'
        return True, f'off: removed {p}'
