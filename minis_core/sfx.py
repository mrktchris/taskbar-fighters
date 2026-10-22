"""Optional sound effects (V9).  OFF by default: `python minis.py sound on|off`, the menus' "Sound effects" checkmark,
control.json `sound`.

The sounds are short, original and procedurally generated (art/build_sfx.py: stdlib wave + math, deterministic) into
assets/sfx/*.wav; no third-party audio.  Playback never blocks a drawing loop: Windows hands the file to winsound with
SND_ASYNC, macOS to an NSSound (minis_mac/sound.py).  Quiet by design:
- volume is low (the files peak at about -12 dBFS; NSSound plays them at SFX_VOLUME),
- rate-limited (one sound of a kind per MIN_GAP_S, at most MAX_PER_S in any second; a new sound of higher priority may
  replace a pending one, never stack up),
- only ONE process plays the shared fight: the taskbar's slot `a` (it sees both rows of the shared timeline) or the arena
  process while an arena runs (the slots are hidden then); slot `b` and the director never play,
- silent while paused, hidden (a full-screen app, the taskbar elsewhere) or with sound off.
Nothing here reads or writes anything but the bundled .wav files.
"""
from __future__ import annotations
import os, sys, threading, time

NAMES = ('hit_light', 'hit_heavy', 'clash', 'whoosh', 'ko', 'forge', 'shatter', 'bell')
PRIORITY = {'ko': 5, 'bell': 4, 'shatter': 4, 'hit_heavy': 3, 'clash': 3, 'forge': 2, 'hit_light': 2, 'whoosh': 1}
MIN_GAP_S = {'whoosh': 0.12, 'hit_light': 0.08, 'hit_heavy': 0.12, 'clash': 0.12, 'forge': 0.5, 'shatter': 0.4, 'ko': 1.0,
             'bell': 1.0}
MAX_PER_S = 6
STALE_S = 0.3                     # an event this late (a hiccup, a replay) is not played
SFX_VOLUME = 0.6                  # macOS NSSound volume on top of the files' own low level

# taskbar timeline rows -> a sound (reactions are on the struck fighter's row; slot a replays both rows)
ROW_SOUNDS = {
    'hit': 'hit_light', 'hit_high': 'hit_light', 'hit_low': 'hit_light', 'hit_back': 'hit_light', 'pulled': 'hit_light',
    'air_hit': 'hit_light',
    'hit_heavy': 'hit_heavy', 'knockdown': 'hit_heavy', 'launched': 'hit_heavy', 'spiked': 'hit_heavy', 'thrown': 'hit_heavy',
    'block_hit': 'clash', 'parry': 'clash', 'clash': 'clash', 'guard_crush': 'clash',
    'ko': 'ko',
}
# arena notes (Arena.note kinds) -> a sound
ARENA_SOUNDS = {
    'block': 'clash', 'clash_meet': 'clash', 'clash_win': 'shatter', 'forge_crack': 'clash',
    'whiff': 'whoosh', 'air_dash': 'whoosh', 'through': 'whoosh', 'strike': 'whoosh', 'double_jump': 'whoosh',
    'knockdown': 'hit_heavy', 'crater': 'hit_heavy', 'wall_bounce': 'hit_light',
    'forge_cut': 'forge', 'forge_morph': 'forge', 'forge_shatter': 'shatter', 'shatter': 'shatter',
    'intro': 'bell', 'winner': 'bell',
}


def sfx_dir():
    from . import paths
    return paths.assets_dir() / 'sfx'


def sound_for_arena(kind, kw):
    """-> the sound name for an arena note, or None."""
    if kind == 'hit':
        try:
            return 'hit_heavy' if float(kw.get('dmg') or 0) >= 14 else 'hit_light'
        except (TypeError, ValueError):
            return 'hit_light'
    if kind == 'round':
        return 'ko' if kw.get('ko') else 'bell'
    return ARENA_SOUNDS.get(kind)


def sound_for_banner(kind):
    k = str(kind or '')
    if k == 'ko':
        return 'ko'
    if k.startswith('round') or k in ('fight', 'winner', 'time'):
        return 'bell'
    return None


# ---------------------------------------------------------------- backends
def _win_backend():
    import winsound
    flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT

    def play(path):
        winsound.PlaySound(str(path), flags)
    return play


def _mac_backend():
    from minis_mac import sound                                   # NSSound, imported only when a sound is wanted
    return sound.player(SFX_VOLUME)


def default_backend():
    """-> play(path) for this OS, or None (no audio: tests, Linux, an import failure)."""
    if os.environ.get('MINIS_TESTING'):
        return None
    try:
        if sys.platform == 'win32':
            return _win_backend()
        if sys.platform == 'darwin':
            return _mac_backend()
    except Exception:
        return None
    return None


class Player:
    """Plays one named sound at a time, asynchronously, rate-limited.  `enabled()` is read on every play (control.json
    `sound`, cached by mtime); `quiet` is set by the owner (paused, hidden, full screen).  `backend(path)` must not block
    for long; it runs on a small daemon worker thread so even a slow first file open never stalls a frame."""

    def __init__(self, enabled=None, backend='auto', clock=time.monotonic, folder=None):
        self.enabled = enabled or (lambda: False)
        self.backend = default_backend() if backend == 'auto' else backend
        self.clock = clock
        self.folder = folder
        self.quiet = False
        self.last = {}                                            # name -> time last played
        self.recent = []                                          # play times in the last second
        self.played = []                                          # (time, name): bounded log for tests / the QA log
        self._pending = None
        self._cv = threading.Condition()
        self._worker = None

    def path(self, name):
        from pathlib import Path
        return Path(self.folder) / f'{name}.wav' if self.folder else sfx_dir() / f'{name}.wav'

    def play(self, name, t=None, now=None):
        """Ask for sound `name` (an event at time t, now = the clock).  -> True when it was handed to the backend."""
        if name not in NAMES:
            return False
        now = self.clock() if now is None else now
        if t is not None and now - t > STALE_S:
            return False
        if self.quiet or self.backend is None:
            return False
        try:
            if not self.enabled():
                return False
        except Exception:
            return False
        if now - self.last.get(name, -1e9) < MIN_GAP_S.get(name, 0.1):
            return False
        self.recent = [x for x in self.recent if now - x < 1.0]
        if len(self.recent) >= MAX_PER_S:
            return False
        self.last[name] = now
        self.recent.append(now)
        self.played.append((now, name))
        del self.played[:-64]
        self._dispatch(name)
        return True

    def _dispatch(self, name):
        if getattr(self.backend, 'sync', False):          # macOS NSSound: returns at once, wants the calling (main) thread
            try:
                p = self.path(name)
                if p.is_file():
                    self.backend(p)
            except Exception:
                pass
            return
        with self._cv:
            if self._pending is None or PRIORITY.get(name, 0) >= PRIORITY.get(self._pending, 0):
                self._pending = name
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='minis-sfx', daemon=True)
                self._worker.start()
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while self._pending is None:
                    self._cv.wait()
                name, self._pending = self._pending, None
            try:
                p = self.path(name)
                if p.is_file():
                    self.backend(p)
            except Exception:
                pass                                                 # a sound is never worth an error in a draw loop


def control_enabled():
    """control.json `sound` (default off)."""
    from . import control
    return lambda: control.sound_on()
