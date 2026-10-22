"""macOS playback for the optional sound effects (minis_core/sfx.py): one cached NSSound per file, played asynchronously
(NSSound.play returns at once and mixes in Core Audio), at a low volume.  EXPERIMENTAL: see docs/MAC-HANDOFF.md MAC-23."""
from __future__ import annotations


def player(volume=0.6):
    """-> play(path) using NSSound; raises ImportError without PyObjC (the caller then stays silent)."""
    from AppKit import NSSound
    cache = {}

    def play(path):
        key = str(path)
        snd = cache.get(key)
        if snd is None:
            snd = NSSound.alloc().initWithContentsOfFile_byReference_(key, True)
            if snd is None:
                return
            snd.setVolume_(float(volume))
            cache[key] = snd
        if snd.isPlaying():
            snd.stop()                                   # restart it: a second hit of the same kind replaces the first
        snd.play()
    play.sync = True                                     # AppKit: call it on the owner's (main) thread, it never blocks
    return play
