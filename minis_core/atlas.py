"""Load a fighter atlas (assets/<character>/anim.json + sheets) and answer timing questions about it.

Characters come from a roster (art/roster.py builds assets/<character>/).  Whatever exists on disk is usable; an unknown
character falls back to `generic`, then to `claude`.  Specials and supers are read from the atlas's `signature` metadata,
never inferred from the character's name (except the documented fallback for atlases built before `signature` existed).
"""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image

from . import paths as _paths
ROOT = _paths.bundle_root()                         # the clone, or the PyInstaller / py2app / wheel location (paths.py)
ASSETS = _paths.assets_dir()
ASSETS_HD = _paths.assets_hd_dir()                   # RES 2 build (128 px cells); absent until the art build lands

# Plate tag / accent before the roster wrote them into anim.json.
LEGACY_TAG = {'claude': '/reverse', 'codex': '$reverse'}
LEGACY_ACCENT = {'claude': (240, 161, 132), 'codex': (169, 157, 255)}
DEFAULT_ACCENT = (200, 200, 210)
# Signature fallback for atlases without a `signature` block (the original two fighters).
LEGACY_SIGNATURE = {'claude': {'strike': 'spin_kick', 'special': 'slash_wave', 'super': 'reverse'},
                    'codex': {'strike': 'ground_pound', 'special': 'deploy', 'super': 'sudo'}}


class AtlasError(ValueError):
    pass


def _hex(c):
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        return tuple(int(v) for v in c[:3])
    s = str(c or '').lstrip('#')
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def validate(meta):
    """Raise AtlasError for metadata the player cannot animate (instead of dividing by zero at runtime)."""
    anims = meta.get('anims')
    if not isinstance(anims, dict) or not anims:
        raise AtlasError('no anims')
    if 'idle' not in anims:
        raise AtlasError('no idle anim')
    for name, a in anims.items():
        fr = a.get('frames') or []
        if not fr:
            raise AtlasError(f'{name}: no frames')
        if any(int(f.get('ms', 0)) <= 0 for f in fr):
            raise AtlasError(f'{name}: frame with ms <= 0')
        lr = a.get('loop_range')
        if lr is not None:
            if not (isinstance(lr, (list, tuple)) and len(lr) == 2 and 0 <= lr[0] <= lr[1] < len(fr)):
                raise AtlasError(f'{name}: bad loop_range {lr}')
    p = meta.get('projectile') or {}
    if p and (int(p.get('w', 0)) <= 0 or int(p.get('h', 0)) <= 0):
        raise AtlasError('projectile without size')


def _upscale_meta(meta, k):
    """The RES 1 metadata as it would read at RES k: cell, anchor, ground_y, projectile size and speed scale with it."""
    m = json.loads(json.dumps(meta))
    m['cell'] = [int(v) * k for v in m['cell']]
    m['anchor'] = {s: int(v) * k for s, v in m['anchor'].items()}
    if 'ground_y' in m:
        m['ground_y'] = int(m['ground_y']) * k
    p = m.get('projectile') or {}
    for key in ('w', 'h', 'speed'):
        if key in p:
            p[key] = int(p[key]) * k
    for a in m['anims'].values():
        if isinstance(a.get('hand'), (list, tuple)) and len(a['hand']) == 2:
            a['hand'] = [float(a['hand'][0]) * k, float(a['hand'][1]) * k]
        for key in ('grip', 'grip2'):                   # V8 forge: per-frame grips, px relative to anchor / ground
            if isinstance(a.get(key), list):
                a[key] = [[float(g[0]) * k, float(g[1]) * k] + list(g[2:]) if isinstance(g, list) and len(g) >= 4 else None
                          for g in a[key]]
    m['res'] = k
    m['upscaled'] = True
    return m


class Atlas:
    """hd=True loads assets_hd/<character> (RES 2, 128 px cells).  Until that build exists the RES 1 sheets are scaled
    2x nearest-neighbour so every caller sees the HD geometry (`res`, `cell`, `anchor`, `ground_y`) either way."""

    def __init__(self, character: str, root=None, hd=False):
        self.hd, self.upscaled = bool(hd), False
        if root:
            d = Path(root)
        elif hd and (ASSETS_HD / character / 'anim.json').is_file():
            d = ASSETS_HD / character
        else:
            d = ASSETS / character
        self.meta = json.loads((d / 'anim.json').read_text(encoding='utf-8'))
        validate(self.meta)
        want = 2 if hd else 1
        have = int(self.meta.get('res') or 1)
        k = 1
        if want != have:
            if want % have:
                raise AtlasError(f'cannot scale a RES {have} atlas to RES {want}')
            k = want // have                                    # RES 1 sheets stand in for a missing HD build
            self.meta = _upscale_meta(self.meta, k)
            self.upscaled = True
        self.res = int(self.meta.get('res') or 1)
        self.character = self.meta.get('character') or self.meta.get('who') or character
        self.who = self.character                        # older callers
        self.display = self.meta.get('display') or self.character.capitalize()
        self.tag = self.meta.get('tag') or LEGACY_TAG.get(self.character, self.character)
        self.accent = _hex(self.meta.get('accent')) or LEGACY_ACCENT.get(self.character, DEFAULT_ACCENT)
        self.cell = tuple(self.meta['cell'])
        self.anim = self.meta['anims']
        self.sheets = {s: self._scaled(Image.open(d / v).convert('RGBA'), k) for s, v in self.meta['sheets'].items()}
        self._dir, self._k = d, k
        self._unarmed = None                             # V8 forge: sheet_unarmed*.png, loaded on first use
        self._ucrop = {}
        pm = self.meta.get('projectile') or {}
        self.proj = self._scaled(Image.open(d / pm['file']).convert('RGBA'), k) if pm.get('file') else None
        self.ground_y = int(self.meta.get('ground_y', self.cell[1] - 7 * self.res))
        self.proj_frames = max(1, int(pm.get('frames', 3))) if pm else 1
        self._crop = {}
        self._pcrop = {}
        self._total = {n: sum(f['ms'] for f in a['frames']) for n, a in self.anim.items()}

    @staticmethod
    def _scaled(im, k):
        return im if k == 1 else im.resize((im.width * k, im.height * k), Image.NEAREST)

    # ---- identity
    def signature(self) -> dict:
        """{'strike','special','super','ultimate'} -> move name or None; only moves this atlas really has.
        An atlas built before ultimates existed has `ultimate` None; callers fall back to the super (see `ultimate()`)."""
        sig = self.meta.get('signature')
        if not isinstance(sig, dict):
            sig = LEGACY_SIGNATURE.get(self.character)
        if not isinstance(sig, dict):
            sig = {'strike': None, 'super': None,
                   'special': next((n for n, a in self.anim.items() if 'proj_frame' in a), None)}
        return {k: (sig.get(k) if sig.get(k) in self.anim else None) for k in ('strike', 'special', 'super', 'ultimate')}

    def ultimate(self):
        """The move a round's 40-damage finisher plays: `signature.ultimate`, else the super, else the signature strike."""
        sig = self.signature()
        return sig['ultimate'] or sig['super'] or sig['strike']

    def power(self, name, default=1) -> int:
        a = self.anim.get(name) or {}
        return int(a.get('power') or default)

    def hand(self, name):
        """(dx, dy) of the striking hand from the hip / ground point for a move, in this atlas's pixels, or None."""
        h = (self.anim.get(name) or {}).get('hand')
        if isinstance(h, (list, tuple)) and len(h) == 2:
            return float(h[0]), float(h[1])
        return None

    def move_fx(self, name):
        """The effects a move asks for, from its `fx` list: [(seconds from the move's start, effect name, until_s | None)].
        A move without the list (or an atlas built before V4) asks for one effect named after the move at its contact."""
        a = self.anim.get(name) or {}
        out = []
        for e in a.get('fx') or []:
            if not isinstance(e, dict) or not e.get('name'):
                continue
            fr = e.get('at', e.get('from', 0))
            try:
                t0 = self.start_ms(name, int(fr)) / 1000.0
                t1 = (self.start_ms(name, int(e['to']) + 1) / 1000.0) if 'to' in e else None
            except (TypeError, ValueError, IndexError):
                continue
            out.append((t0, str(e['name']), t1))
        if not out and a:
            out.append((self.contact_ms(name) / 1000.0 if 'hit_frame' in a else self.total_ms(name) * 0.6 / 1000.0, name, None))
        return out

    # ---- images
    def anchor(self, facing: int) -> int:
        return self.meta['anchor']['R' if facing >= 0 else 'L']

    def frame_image(self, name: str, i: int, facing: int) -> Image.Image:
        if name not in self.anim:
            name, i = 'idle', 0
        n = len(self.anim[name]['frames'])
        i = max(0, min(n - 1, int(i)))                   # a bad index draws the nearest real frame, never a blank crop
        key = (name, i, facing >= 0)
        im = self._crop.get(key)
        if im is None:
            w, h = self.cell
            r = self.anim[name]['row']
            sheet = self.sheets['R' if facing >= 0 else 'L']
            im = sheet.crop((i * w, r * h, (i + 1) * w, (r + 1) * h))
            self._crop[key] = im
        return im

    def _unarmed_sheets(self):
        if self._unarmed is None:
            self._unarmed = {}
            for s, v in (self.meta.get('sheets_unarmed') or {}).items():
                try:
                    self._unarmed[s] = self._scaled(Image.open(self._dir / v).convert('RGBA'), self._k)
                except OSError:
                    self._unarmed = {}
                    break
        return self._unarmed

    def unarmed_frame(self, name: str, i: int, facing: int) -> Image.Image:
        """V8 forge: the frame without its held weapon(s) (the hands still close round the grip), for drawing a forged
        weapon in the hand.  Falls back to frame_image when the atlas was built without the unarmed sheets."""
        sheets = self._unarmed_sheets()
        side = 'R' if facing >= 0 else 'L'
        if side not in sheets:
            return self.frame_image(name, i, facing)
        if name not in self.anim:
            name, i = 'idle', 0
        n = len(self.anim[name]['frames'])
        i = max(0, min(n - 1, int(i)))
        key = (name, i, side)
        im = self._ucrop.get(key)
        if im is None:
            w, h = self.cell
            r = self.anim[name]['row']
            im = sheets[side].crop((i * w, r * h, (i + 1) * w, (r + 1) * h))
            self._ucrop[key] = im
        return im

    def _grip(self, key, name, i, facing):
        gl = (self.anim.get(name) or {}).get(key)
        if not isinstance(gl, list) or not gl:
            return None
        g = gl[max(0, min(len(gl) - 1, int(i)))]
        if not isinstance(g, (list, tuple)) or len(g) < 4:
            return None
        x, y, ang = float(g[0]), float(g[1]), float(g[2])
        if facing < 0:                                   # the left sheet is the mirror about the anchor column centre
            x, ang = -x, 180.0 - ang
        return x, y, ((ang + 180.0) % 360.0) - 180.0, str(g[3])

    def grip(self, name: str, i: int, facing: int):
        """V8 forge: (x, y, angle_deg, hand) of the main weapon's grip on frame i in this atlas's px, for the sheet of
        that facing: x right of the anchor column centre (anchor(facing) + 0.5), y below the top of the ground_y row
        (negative = up), angle in screen degrees of the weapon axis from the grip toward the tip (0 = screen-right,
        -90 = up).  None when no weapon is held on that frame or the atlas carries no grip data."""
        return self._grip('grip', name, i, facing)

    def grip2(self, name: str, i: int, facing: int):
        """The back hand's grip (a second weapon, or the second hand on a two-handed one), same shape as grip(), or None."""
        return self._grip('grip2', name, i, facing)

    def proj_image(self, i: int, facing: int) -> Image.Image:
        k = (int(i) % self.proj_frames, facing >= 0)
        im = self._pcrop.get(k)
        if im is None:
            w = self.meta['projectile']['w']
            h = self.meta['projectile']['h']
            im = self.proj.crop((k[0] * w, 0, (k[0] + 1) * w, h))
            if not k[1]:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            self._pcrop[k] = im
        return im

    # ---- timing
    def total_ms(self, name: str) -> int:
        return self._total[name]

    def start_ms(self, name: str, i: int) -> int:
        return sum(f['ms'] for f in self.anim[name]['frames'][:i])

    def contact_ms(self, name: str) -> int:
        a = self.anim[name]
        return self.start_ms(name, a['hit_frame']) if 'hit_frame' in a else 0

    def locate(self, name: str, elapsed_ms: float, loop: bool):
        """-> (frame index, finished).  Honors loop_range: intro frames play once, then the range loops."""
        if name not in self.anim:
            return 0, True
        a = self.anim[name]
        frames = a['frames']
        total = self._total[name]
        elapsed_ms = max(0.0, elapsed_ms)
        if not loop:
            if elapsed_ms >= total:
                return len(frames) - 1, True
            return self._idx(frames, elapsed_ms), False
        lr = a.get('loop_range')
        if lr:
            lo, hi = lr
            intro = sum(f['ms'] for f in frames[:lo])
            if elapsed_ms < intro:
                return self._idx(frames, elapsed_ms), False
            seg = frames[lo:hi + 1]
            seg_total = sum(f['ms'] for f in seg)
            return lo + self._idx(seg, (elapsed_ms - intro) % seg_total), False
        return self._idx(frames, elapsed_ms % total), False

    @staticmethod
    def _idx(frames, ms):
        t = 0
        for i, f in enumerate(frames):
            t += f['ms']
            if ms < t:
                return i
        return len(frames) - 1


# ---------------------------------------------------------------- character library
def root_is_default(root) -> bool:
    try:
        return Path(root).resolve() == ASSETS.resolve()
    except OSError:
        return False


def available(root=None) -> list:
    base = Path(root) if root else ASSETS
    try:
        return sorted(p.name for p in base.iterdir() if (p / 'anim.json').is_file())
    except OSError:
        return []


def resolve(character, root=None) -> str:
    """The character that will really be drawn: itself if built, else `generic`, else `claude`."""
    have = available(root)
    if root is None and isinstance(character, str) and character.startswith('pack-'):
        from . import packs                                  # growth: an installed skin pack (packs.py, data only)
        have = have + packs.character_ids()
    for c in (character, 'generic', 'claude'):
        if c and c in have:
            return c
    return 'claude'


class Library:
    """Character -> Atlas, loaded on first use and cached.  A broken atlas falls back like a missing one.
    hd=True serves HD atlases (assets_hd, or the RES 1 sheets scaled 2x when the HD build is missing)."""

    def __init__(self, root=None, hd=False):
        self.root = Path(root) if root else ASSETS
        self.hd = bool(hd)
        self._cache = {}
        self.errors = {}

    def __getitem__(self, character):
        a = self._cache.get(character)
        if a is not None:
            return a
        for c in (character, 'generic', 'claude'):
            if c in self._cache:
                a = self._cache[c]
                break
            try:
                pdir = None
                if c.startswith('pack-') and root_is_default(self.root):
                    from . import packs                      # growth: skin packs load from <data dir>/packs/<name>/64|128
                    pdir = packs.char_dir(c, self.hd)
                if pdir is not None:
                    a = Atlas(c, pdir, hd=self.hd)
                elif self.hd and root_is_default(self.root):
                    a = Atlas(c, hd=True)                   # assets_hd/<c> when built, else assets/<c> scaled 2x
                else:
                    a = Atlas(c, self.root / c, hd=self.hd)
                self._cache[c] = a
                break
            except (OSError, ValueError, KeyError) as e:
                self.errors[c] = repr(e)
        if a is None:
            raise AtlasError(f'no usable atlas for {character!r}')
        self._cache[character] = a
        return a

    def __contains__(self, character):
        return True
