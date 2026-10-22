r"""Where pictures Taskbar Fighters makes for you are written (growth): the stats card and stream snapshots.

  default           <data dir>/exports/   (%LOCALAPPDATA%\minis\exports, ~/Library/Application Support/minis/exports)
  --out <folder>    an EXISTING folder you name: the file goes inside it under its default name
  --out <x.png>     a .png path you name, in a folder that already exists
Nothing else: no silent default outside the data folder, no folder is created outside it, and a path that is neither of
the above is refused.  "Share my stats card..." writes to the default and opens that folder with the file selected.
"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

from . import config as cfgmod


class ExportPathError(ValueError):
    pass


def exports_dir() -> Path:
    d = cfgmod.data_dir() / 'exports'
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve(out, default_name) -> Path:
    """-> the file to write.  out None: <data dir>/exports/<default_name>.  Otherwise an existing folder (+ default_name)
    or a .png path whose folder exists; anything else raises ExportPathError."""
    if out in (None, ''):
        return exports_dir() / default_name
    p = Path(os.path.expanduser(str(out)))
    if p.is_dir():
        return p / default_name
    if p.suffix.lower() == '.png' and p.parent.is_dir() and not p.is_dir():
        return p
    raise ExportPathError(f'{out}: give an existing folder, or a .png file in an existing folder '
                          f'(default: {exports_dir()})')


def reveal(path):
    """Open the folder holding `path` with the file selected (Explorer / Finder).  Never under tests."""
    if os.environ.get('MINIS_TESTING'):
        return False
    p = str(Path(path).resolve())
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', p])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', p])
    else:
        return False
    return True
