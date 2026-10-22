"""Pixel-fighter rig (V6): pose data -> part-id buffer -> shaded, outlined RGBA frame.

V6 rebuilt the body: ~4.5 heads tall (50-54 px in the 64 px cell, 11 px head, 22 px legs), a held-weapon part with its own
pivot / length / palette and a big white crescent smear on every swing, per-character headgear (kasa, cowl, kabuto,
horned helm, hood, great helm, turban ...), armour plates, skirts, and short gravity-hanging cloth bits that lag one
frame (computed from the previous pose, so the rig stays stateless).

Pose data is authored for the old 16 px leg / 12 px arm body; the rig scales it per body: hand targets by `ka`, foot lifts
and hip drops by `kl`, foot spread by `stance` (walks pin it to 1 so the planted foot never slides), and rises (negative
dy) by KJ so a jump stays inside the cell.

Resolution: `set_res(k)` renders the same design data into a k*64 px cell.  At RES 2 the finish pass is real HD, not a
doubled frame: a 1 px outline, five tones per material (rim, highlight, base, shadow, deep shadow), tinted inner lines
where a part crosses another material, and HD-only detail drawn at pixel level (2x2 eyes with a white, armour seams,
blade highlights).  One light direction (top-left) in both facings: the left-facing frame is shaded after the mirror.
"""
from __future__ import annotations
import math, colorsys
from dataclasses import dataclass, replace, field
from PIL import Image, ImageDraw

W = H = 64             # design cell
GROUND = 57            # lowest body row of a planted foot (design)
HIP_X = 30             # hip column in the cell (facing right, design)
ANKLE_Y = GROUND - 2
RES = 1                # resolution factor: 1 = 64 px cell, 2 = 128 px cell
KJ = 0.42              # rises (negative dy) are scaled by this: a 52 px fighter has ~6 px of headroom
XMIN, XMAX, YMIN, YMAX = 2.0, 59.0, 3.0, 55.0     # where a weapon's ends may go (design, facing right)
TOP_CLEAR = 2          # rows 0..1 stay empty (the outline then never touches the top edge)
UNARMED = False        # V8 forge: True draws the held weapon(s), their swing crescent / streak and the nocked string+arrow
                       # NOT at all (the hands still close round the empty grip); build_fighters writes sheet_unarmed*.png


def set_res(k):
    """Render at k x the design resolution (1 or 2).  Affects every render/finish call after it."""
    global RES
    k = int(k)
    if k < 1:
        raise ValueError('RES must be >= 1')
    RES = k


def cell_px():
    return W * RES


def ground_px():
    """Lowest body row of a planted foot, in pixels at the current RES."""
    return GROUND * RES


def hip_x_px():
    return HIP_X * RES


PART_ORDER = ['swoosh', 'scarf_b', 'scarf_a', 'hood', 'back_b', 'arrow',
              'bitH', 'bitC', 'bitT', 'bitM',
              'leg_b_th', 'leg_b_sh', 'boot_b', 'shoe_b', 'sole_b',
              'arm_b_up', 'arm_b_fo', 'cuff_b', 'wpn_b', 'hilt_b', 'string', 'hand_b', 'pad_b',
              'torso', 'chest', 'vest', 'lapel', 'trace',
              'leg_f_th', 'leg_f_sh', 'boot_f', 'shoe_f', 'sole_f',
              'skirt', 'belt', 'beads',
              'head', 'ear', 'hair', 'beard', 'cap', 'visor', 'strap', 'band', 'helm', 'helm2', 'horn', 'mask', 'glow',
              'lens', 'sigil', 'eyew', 'eye', 'brow', 'mouth', 'seam',
              'arm_f_up', 'arm_f_fo', 'cuff_f', 'wpn_f', 'hilt_f', 'hand_f', 'pad_f', 'blade_hl',
              'doc', 'doc_line', 'streak', 'fx_a', 'fx_b', 'fx_w', 'fx_c', 'dust_l', 'dust_d',
              'crease']                                   # V7 HD: drawn last; coloured from the material under it
PID = {n: i + 1 for i, n in enumerate(PART_ORDER)}
NAME = {v: k for k, v in PID.items()}
Z = {PID[n]: i for i, n in enumerate(PART_ORDER)}

GROUP = {'head': 'skin', 'ear': 'skin', 'hand_b': 'skin', 'hand_f': 'skin', 'hair': 'hair', 'beard': 'hair',
         'torso': 'cloth', 'arm_b_up': 'cloth', 'arm_b_fo': 'cloth', 'arm_f_up': 'cloth', 'arm_f_fo': 'cloth',
         'hood': 'cloth', 'cap': 'cloth', 'visor': 'cloth', 'scarf_b': 'cloth', 'mask': 'cloth',
         'cuff_b': 'trim', 'cuff_f': 'trim', 'strap': 'trim', 'belt': 'trim', 'scarf_a': 'trim', 'helm2': 'trim', 'horn': 'trim',
         'lapel': 'trim', 'band': 'trim', 'trace': 'trim', 'vest': 'pants', 'skirt': 'pants',
         'leg_b_th': 'pants', 'leg_b_sh': 'pants', 'leg_f_th': 'pants', 'leg_f_sh': 'pants',
         'boot_b': 'shoe', 'boot_f': 'shoe', 'shoe_b': 'shoe', 'shoe_f': 'shoe', 'sole_b': 'sole', 'sole_f': 'sole',
         'chest': 'helm', 'pad_b': 'helm', 'pad_f': 'helm', 'helm': 'helm',
         'back_b': 'hilt', 'beads': 'hilt', 'wpn_b': 'metal', 'wpn_f': 'metal', 'hilt_b': 'hilt', 'hilt_f': 'hilt',
         'bitH': 'hair', 'bitC': 'cloth', 'bitT': 'trim', 'bitM': 'metal'}
DARK = {'leg_b_th', 'leg_b_sh', 'boot_b', 'shoe_b', 'sole_b', 'arm_b_up', 'arm_b_fo', 'cuff_b', 'hand_b', 'pad_b'}   # far side
FLAT = {'eye': ('ink', None), 'brow': ('ink', None), 'mouth': ('ink', None), 'eyew': ('paper', None),
        'sigil': ('trim', 'hi'), 'lens': ('trim', 'hi2'), 'glow': ('trim', 'hi2'), 'seam': ('helm', 'sh'),
        'blade_hl': ('metal', 'hi2'), 'string': ('paper', 'sh'), 'arrow': ('trim', 'hi'),
        'doc': ('paper', None), 'doc_line': ('paper', 'sh'), 'swoosh': ('fx', 'w'), 'streak': ('fx', 'c'),
        'fx_a': ('fx', 'a'), 'fx_b': ('fx', 'b'), 'fx_w': ('fx', 'w'), 'fx_c': ('fx', 'c'),
        'dust_l': ('shoe', 'hi'), 'dust_d': ('shoe', 'base'),          # V9: dust in the fighter's own shoe tones (no new colour)
        'crease': ('ink', 'crease')}
NOLINE = {'fx_a', 'fx_b', 'fx_w', 'fx_c', 'swoosh', 'streak', 'dust_l', 'dust_d'}
TEXT_FX = ('bigsigil', 'bigglyph', 'qmark', 'zzz')   # effects that are letters: never mirrored on left-facing frames
RIM_GROUPS = ('skin', 'hair', 'cloth', 'trim', 'pants', 'shoe', 'helm', 'metal', 'hilt')   # groups that get the HD rim tone

GLYPH = {'/': ["..#", "..#", ".#.", "#..", "#.."],
         '$': [".##", "##.", ".#.", ".##", "##."],
         '*': ["#.#", ".#.", "###", ".#.", "#.#"],
         '>': ["#..", ".#.", "..#", ".#.", "#.."],
         'o': [".#.", "#.#", "#.#", "#.#", ".#."],
         'L': ["#..", "#..", "#..", "#..", "###"],
         '+': [".#.", ".#.", "###", ".#.", ".#."],
         'x': ["#.#", "#.#", ".#.", "#.#", "#.#"],
         'T': ["###", ".#.", ".#.", ".#.", ".#."],
         'V': ["#.#", "#.#", "#.#", "#.#", ".#."],
         'Y': ["#.#", "#.#", ".#.", ".#.", ".#."],
         'O': ["###", "#.#", "#.#", "#.#", "###"],
         'H': ["#.#", "#.#", "###", "#.#", "#.#"]}
ZGLYPH = ["####", "..#.", ".#..", "####"]          # the sleep 'z': a real diagonal, so it never reads as 'I'


def hexrgb(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def mix(c0, c1, k):
    return tuple(int(round(a + (b - a) * k)) for a, b in zip(c0, c1))


def rim_tone(grp):
    """The HD-only rim tone of a group: its highlight pushed toward white."""
    return grp.get('hi2') or mix(grp['hi'], (255, 255, 255), 0.45)


def deep_tone(grp):
    """The HD-only deep-shadow tone of a group (between shadow and outline)."""
    return grp.get('sh2') or mix(grp['sh'], grp['ol'], 0.5)


def _hue_toward(h, target, deg):
    """Move hue h (0..1) toward target by at most deg degrees along the short way round."""
    d = ((target - h + 0.5) % 1.0) - 0.5
    step = math.copysign(min(abs(d), deg / 360.0), d)
    return (h + step) % 1.0


def ramp(base, hi=None, hi2=None, sh=None, sh2=None, ol=None, lift=0.34, drop=0.70, warm=10, cool=14):
    """A hue-shifted 6-tone material ramp from one base colour: highlights lean toward warm yellow, shadows toward cool
    violet (the standard pixel-art ramp), outlines are a dark tint of the material, never black.  Any tone can be given
    explicitly (a brand colour) instead of derived."""
    r, g, b = (c / 255.0 for c in hexrgb(base))
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    def tone(l2, dh_target, deg, ks):
        h2 = _hue_toward(h, dh_target, deg) if s > 0.06 else h
        s2 = max(0.0, min(1.0, s * ks))
        rr, gg, bb = colorsys.hls_to_rgb(h2, max(0.0, min(1.0, l2)), s2)
        return (int(round(rr * 255)), int(round(gg * 255)), int(round(bb * 255)))
    lift_k = lift * (0.55 if l < 0.22 else 1.0)          # very dark cloth gets a gentler highlight
    out = dict(base=hexrgb(base),
               hi=hexrgb(hi) if hi else tone(l + (1 - l) * lift_k, 1 / 6, warm, 0.95),
               hi2=hexrgb(hi2) if hi2 else tone(l + (1 - l) * min(0.92, lift_k * 2.1), 1 / 6, warm * 1.6, 0.85),
               sh=hexrgb(sh) if sh else tone(l * drop, 0.72, cool, 1.08),
               sh2=hexrgb(sh2) if sh2 else tone(l * drop * 0.74, 0.72, cool * 1.4, 1.1),
               ol=hexrgb(ol) if ol else tone(l * 0.36, 0.74, cool * 1.6, 0.95))
    return out


def _g(base, hi, sh, ol):
    return dict(base=hexrgb(base), hi=hexrgb(hi), sh=hexrgb(sh), ol=hexrgb(ol))


@dataclass(frozen=True)
class Weapon:
    """A held weapon.  `grip` = design px from the butt to the hand; `rel` = rest angle relative to the forearm (deg,
    screen space, + = clockwise); `slide` = a pole the hand can slide along to keep the weapon inside the cell."""
    kind: str
    length: float
    grip: float
    rel: float = -50.0
    width: float = 2.0
    slide: bool = False
    grip2: float = 0.0           # two-handed: the back hand holds the grip this far behind the front hand (0 = one hand)


@dataclass(frozen=True)
class Bit:
    """A short gravity-hanging cloth / hair / chain bit (2-3 segments) that lags the body by one frame.
    anchor: 'head' (head-local point) | 'hip' (torso-local a, b) | 'hb' / 'hf' (a hand).  rest: hanging angle in screen
    degrees for a right-facing fighter (90 = straight down, > 90 swings toward the back)."""
    anchor: str
    at: tuple
    n: int = 2
    seg: float = 2.2
    width: float = 2.0
    part: str = 'bitH'
    rest: float = 100.0
    lag: float = 0.30


@dataclass(frozen=True)
class Body:
    name: str = 'fighter'
    thigh: float = 11
    shin: float = 11
    torso: float = 15
    torso_w: float = 11
    upper: float = 7
    fore: float = 7
    limb: int = 3
    head_w: int = 11
    head_h: int = 11
    foot_len: int = 7
    sigil: str = '/'
    scarf: bool = False
    hood: bool = False
    palette: dict = None
    neck: float = 1.5
    waist: float = 0.74          # waist width / shoulder width
    hip_w: float = 0.84          # hip width / shoulder width
    leg_add: int = 1             # extra thigh thickness over `limb`
    stance: float = 1.25         # foot-spread scale of the pose data (walks override it with fk=1)
    hair: str = 'short'          # short | spiky | bald | topknot | bun | pony | wild | none
    headgear: str = ''           # kasa | cowl | crest | visor | horned | kabuto | hood | greathelm | turban | oni | band
    face: str = ''               # '' | 'mask' (cloth over nose and mouth) | 'glow' (glowing eyes) | 'slit' (helm slit)
    beard: bool = False
    chest: str = ''              # '' | robe | plate | bare | vest | gi | wrap
    pads: str = ''               # '' | angled | sode | round | fur
    skirt: str = ''              # '' | hakama | tassets | loin | robe | kilt
    sash: bool = False
    boots: bool = False
    gauntlet: bool = False
    sleeves: str = ''            # '' | loose
    quiver: bool = False
    beads: bool = False
    weapon: Weapon = None        # in the front hand
    weapon_b: Weapon = None      # in the back hand
    bits: tuple = ()
    groups: dict = field(default_factory=dict)    # part -> palette group overrides
    flats: dict = field(default_factory=dict)     # flat part -> (group, tone) overrides
    show_sigil: bool = False
    ghost_group: str = 'trim'
    ghost_style: str = 'dither'  # 'dither' | 'holo' | 'streak' | 'spark'
    ponytail: bool = False
    tail_anchor: tuple = (-5.0, 4.5)
    tail_seg: tuple = (3, 2.2)
    skin_tone_note: str = ''

    @property
    def kl(self):
        return (self.thigh + self.shin) / 16.0

    @property
    def ka(self):
        return (self.upper + self.fore) / 12.0

    @property
    def hip_y0(self):
        return ANKLE_Y - (self.thigh + self.shin) + 1

    @property
    def has_tail(self):
        return self.scarf or self.ponytail

    @property
    def lie_dy(self):
        """Hip drop (pose units) when lying flat: puts the hips on row 51 for every leg length."""
        return ((self.thigh + self.shin) - 5 - max(0.0, self.torso_w * 0.55 - 6.0)) / self.kl   # wide bodies lie higher

    @property
    def sit_dy(self):
        """Hip drop (pose units) when sitting: the same hip height above the floor for every leg length."""
        return ((self.thigh + self.shin) - 1) / self.kl


def group_of(body, nm):
    return body.groups.get(nm) or GROUP[nm]


def flat_of(body, nm):
    return body.flats.get(nm) or FLAT[nm]


_DEFAULT_PAL = {
    'skin': ramp('E9B88F'), 'hair': ramp('2B2420'), 'cloth': ramp('D97757'), 'trim': ramp('F0EEE6'),
    'pants': ramp('2E2B38'), 'shoe': ramp('3A3440'), 'sole': _g('1F1E1D', '45414F', '1F1E1D', '121118'),
    'ink': _g('1F1E1D', '1F1E1D', '1F1E1D', '1F1E1D'), 'paper': _g('F4F4F2', 'FFFFFF', 'A9A9B4', '4A4A55'),
    'helm': ramp('FFB86B'), 'metal': ramp('C8CCD8'), 'hilt': ramp('2A2230'),
    'fx': dict(a=hexrgb('FF9C2C'), b=hexrgb('FFE27A'), w=hexrgb('FFFFFF'), c=hexrgb('F0A184')),
    'flash': dict(fill=hexrgb('FFFFFF'), ol=hexrgb('B8BCD0')),
}
CLAUDE = Body('claude', palette=_DEFAULT_PAL, headgear='kasa', weapon=Weapon('katana', 17, 3.5))   # rig self-test body
CODEX = Body('codex', palette=_DEFAULT_PAL, headgear='cowl', face='mask')


@dataclass(frozen=True)
class Pose:
    dx: float = 0           # world root motion this frame (px, +forward)
    cx: float = 0           # in-cell shift of the whole body
    dy: float = 1           # hips lower by dy (negative = up)
    lean: float = 10        # torso lean, degrees, + = forward
    head: tuple = (1, 0)
    tilt: float = 0
    hf: tuple = (7, 3)      # front hand target, relative to the front shoulder
    hb: tuple = (3, 4)
    ff: tuple = (7, 0)      # front foot: (x from hip, lift above ground)
    fb: tuple = (-6, 0)
    eb_f: str = 'down'
    eb_b: str = 'down'
    kb_f: str = 'fwd'
    kb_b: str = 'fwd'
    face: str = 'f'
    fist_f: int = 3
    fist_b: int = 3
    open_f: bool = False
    turn: float = 1.0       # torso width scale (spin)
    fx: tuple = ()
    flash: bool = False
    aura: int = 0
    ang_f: float = 0        # foot angle, degrees
    ang_b: float = 0
    doc: str = ''           # '' | 'hf' | 'hb': which hand holds the diff
    ghost: tuple = ()       # afterimage: distances (design px) of each trailing copy back along the motion, nearest first
    sq: float = 1.0         # squash / stretch: torso length and head height scale by sq, head width by 1/sqrt(sq)
    chest: float = 1.0      # torso width scale on top of `turn` (inhale on idle, puff on a power-up)
    smear_f: tuple = ()     # (x, y) the front hand's PREVIOUS target: this frame the forearm is drawn as the arc it swept
    smear_b: tuple = ()
    smear_ff: tuple = ()    # previous (x, lift) target of the front foot: the shin is drawn as the kick's arc
    smear_fb: tuple = ()
    # ---- V6
    wa: float = None        # front weapon angle (screen deg, 0 = forward, -90 = up); None = the weapon's rest angle on the forearm
    wb: float = None        # back weapon angle
    fk: float = None        # foot-spread scale override (walks: 1.0, so the planted foot never slides)
    free_b: bool = False    # the back hand lets go of a two-handed weapon (holding a doc, gesturing)
    # ---- V7
    nowf: bool = False      # the front weapon has left the hand (a thrown chakram before it comes back)
    nock: bool = False      # a bow's string is drawn back to the rear hand with an arrow nocked
    # ---- V8 (air contract): the engine lifts an airborne sprite along anim.json `air`, so the in-cell anchors barely move;
    # vy is that world vertical motion since the previous frame (design px, + = down) so the hanging bits still trail it
    vy: float = 0.0


def is_smear(pose):
    return bool(pose.smear_f or pose.smear_b or pose.smear_ff or pose.smear_fb)


# ---------------------------------------------------------------- geometry helpers
def ik2(a, t, l1, l2, bend, maxy=None):
    dx, dy = t[0] - a[0], t[1] - a[1]
    d = max(1e-6, math.hypot(dx, dy))
    reach = l1 + l2 - 0.05 * RES
    if d > reach:
        k = reach / d
        dx, dy, d = dx * k, dy * k, reach
    ca = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    ang = math.acos(ca)
    base = math.atan2(dy, dx)
    e1 = (a[0] + l1 * math.cos(base + ang), a[1] + l1 * math.sin(base + ang))
    e2 = (a[0] + l1 * math.cos(base - ang), a[1] + l1 * math.sin(base - ang))
    key = {'down': lambda e: e[1], 'up': lambda e: -e[1], 'fwd': lambda e: e[0], 'back': lambda e: -e[0]}[bend]
    cands = [e1, e2]
    if maxy is not None:                         # a knee must never dip below the foot line
        ok = [c for c in cands if c[1] <= maxy]
        cands = ok or [min(cands, key=lambda c: c[1])]
    e = max(cands, key=key)
    return e, (a[0] + dx, a[1] + dy)


def rot(pt, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (pt[0] * c - pt[1] * s, pt[0] * s + pt[1] * c)


def rnd(v):
    return int(math.floor(v + 0.5))


def stamp(d, x, y, t, fill):
    t = max(1, int(t))
    x0, y0 = rnd(x - t / 2 + 0.5), rnd(y - t / 2 + 0.5)
    S = RES
    if t >= 4 * S:                               # fat limbs and fists: a square minus its four corners
        d.rectangle([x0 + S, y0, x0 + t - 1 - S, y0 + t - 1], fill=fill)
        d.rectangle([x0, y0 + S, x0 + t - 1, y0 + t - 1 - S], fill=fill)
    else:
        d.rectangle([x0, y0, x0 + t - 1, y0 + t - 1], fill=fill)


def thick_line(d, p0, p1, t, fill):
    n = max(1, int(math.ceil(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 1.5)))
    for i in range(n + 1):
        k = i / n
        stamp(d, p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k, t, fill)


def taper_line(d, p0, p1, t0, t1, fill):
    """A limb segment whose thickness runs from t0 at p0 to t1 at p1 (px): thick at the joint, thin at the extremity."""
    n = max(1, int(math.ceil(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 1.5)))
    for i in range(n + 1):
        k = i / n
        stamp(d, p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k, rnd(t0 + (t1 - t0) * k), fill)


def smear_arc(d, pivot, a, b, t, fill, inner=None):
    """A smear frame's limb: the arc a limb swept from `a` to `b` around `pivot`, drawn as one stroke that starts hairline
    at the old position and thickens to the limb width at the new one.  The arc bulges away from the pivot (a swing,
    not a chord).  `inner`, when given, is a lighter one-pixel streak along the middle of the sweep."""
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    vx, vy = mx - pivot[0], my - pivot[1]
    n = max(1e-6, math.hypot(vx, vy))
    chord = math.hypot(b[0] - a[0], b[1] - a[1])
    bulge = 0.30 * chord
    floor = (GROUND - 1.5) * RES                              # a sweep never dips into the taskbar
    c = (mx + vx / n * bulge, min(my + vy / n * bulge, floor))   # quadratic control point, outside the chord
    steps = max(6, int(chord * 1.5))
    pts = []
    for i in range(steps + 1):
        k = i / steps
        x = (1 - k) ** 2 * a[0] + 2 * (1 - k) * k * c[0] + k * k * b[0]
        y = (1 - k) ** 2 * a[1] + 2 * (1 - k) * k * c[1] + k * k * b[1]
        pts.append((x, min(y, floor)))
    for i in range(steps + 1):
        k = i / steps
        stamp(d, pts[i][0], pts[i][1], max(RES, rnd(RES + (t - RES) * k)), fill)
    if inner is not None:
        for i in range(steps // 4, 3 * steps // 4 + 1):
            stamp(d, pts[i][0], pts[i][1], RES, inner)


def poly(d, pts, fill):
    d.polygon([(rnd(x), rnd(y)) for x, y in pts], fill=fill)



def rot_rect(c, w, h, ang):
    pts = []
    for sx, sy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        rx, ry = rot((sx, sy), ang)
        pts.append((c[0] + rx, c[1] + ry))
    return pts


# head-local face offsets (head 11 px: centre at 0,0, the face looks toward +x)
_FACES_V5 = {
    'n': dict(eye=[(3, 1), (3, 2)], brow=[(3, -1), (4, -1)], mouth=[(3, 4), (4, 4)]),
    'f': dict(eye=[(3, 1), (3, 2)], brow=[(3, -1), (4, 0)], mouth=[(3, 4), (4, 4), (5, 3)]),
    'b': dict(eye=[(3, 2), (4, 2)], brow=[(3, -1), (4, -1)], mouth=[(3, 4), (4, 4)]),
    'h': dict(eye=[(2, 0), (3, 1), (2, 2)], brow=[(2, -2), (3, -2)], mouth=[(3, 4), (4, 4), (3, 5), (4, 5)]),
    'x': dict(eye=[(2, 0), (4, 0), (3, 1), (2, 2), (4, 2)], brow=[], mouth=[(3, 4), (4, 4), (5, 4)]),
    'w': dict(eye=[(2, 2), (3, 1), (4, 2)], brow=[], mouth=[(3, 3), (4, 4), (5, 4), (6, 3)]),
    'g': dict(eye=[(3, 1), (3, 2)], brow=[(3, -1), (4, -2)], mouth=[(3, 4), (4, 4), (5, 3)]),
    'z': dict(eye=[(2, 2), (3, 2), (4, 2)], brow=[], mouth=[(4, 4)]),
    'o': dict(eye=[(3, 0), (3, 1), (3, 2)], brow=[(2, -2), (3, -2), (4, -2)], mouth=[(4, 4), (4, 5)]),
    'back': dict(eye=[], brow=[], mouth=[]),
}
FACES = {k: {kk: [(x - 0.6, y - 1.6) for x, y in vv] for kk, vv in v.items()} for k, v in _FACES_V5.items()}


# ---------------------------------------------------------------- skeleton (design units, no drawing)
def body_frame(body: Body, pose: Pose):
    """Design-unit geometry every consumer shares: hip, shoulder, head centre, head tilt, the torso's unit axes."""
    kl = body.kl
    dy = pose.dy * kl if pose.dy >= 0 else pose.dy * KJ
    hip = (HIP_X + pose.cx * kl, body.hip_y0 + dy)
    fk = pose.fk if pose.fk is not None else body.stance
    reach = body.thigh + body.shin - 0.6
    sink = 0.0
    for tgt in (pose.ff, pose.fb):
        if tgt[1] == 0 and pose.lean > -45:
            hx = abs(tgt[0] * fk) + body.torso_w * 0.10
            if hx < reach:
                need = ANKLE_Y - math.sqrt(reach * reach - hx * hx)
                sink = max(sink, need - hip[1])
    if 0 < sink < 6:
        hip = (hip[0], hip[1] + sink)
    th = math.radians(pose.lean)
    u = (math.sin(th), -math.cos(th))
    v = (math.cos(th), math.sin(th))
    torso = body.torso * pose.sq
    S_ = (hip[0] + u[0] * torso, hip[1] + u[1] * torso)
    hh = body.head_h * pose.sq
    k = hh / 2 - 1 + body.neck
    hc = (S_[0] + u[0] * k + pose.head[0], S_[1] + u[1] * k + pose.head[1])
    tilt = pose.lean * 0.5 + pose.tilt
    return dict(hip=hip, S=S_, head=hc, tilt=tilt, u=u, v=v, torso=torso, head_h=hh,
                head_w=body.head_w / math.sqrt(pose.sq))


def skeleton(body: Body, pose: Pose):
    """Every joint, hand, ankle and weapon of a pose, in design units."""
    bf = body_frame(body, pose)
    u, v, S_ = bf['u'], bf['v'], bf['S']
    sk = dict(bf)
    ka, kl = body.ka, body.kl
    for side, tgt, bend in (('f', pose.hf, pose.eb_f), ('b', pose.hb, pose.eb_b)):
        sgn = 1.0 if side == 'f' else -1.0
        off = body.torso_w * 0.20 * pose.turn
        base = (S_[0] - u[0] * 2.3 + sgn * v[0] * off, S_[1] - u[1] * 2.3 + sgn * v[1] * off)
        t = (base[0] + tgt[0] * ka, base[1] + tgt[1] * ka)
        el, hand = ik2(base, t, body.upper, body.fore, bend)
        sk['sh_' + side], sk['el_' + side], sk['h' + side] = base, el, hand
    fk = pose.fk if pose.fk is not None else body.stance
    hip = bf['hip']
    for side, tgt, bend in (('f', pose.ff, pose.kb_f), ('b', pose.fb, pose.kb_b)):
        sgn = 1.0 if side == 'f' else -1.0
        hp = (hip[0] + sgn * v[0] * body.torso_w * 0.10, hip[1] + sgn * v[1] * body.torso_w * 0.10)
        t = (HIP_X + pose.cx * kl + tgt[0] * fk, ANKLE_Y - tgt[1] * kl)
        knee, ank = ik2(hp, t, body.thigh, body.shin, bend, maxy=GROUND - (body.limb + 1) / 2.0 - 0.5)
        sk['hp_' + side], sk['kn_' + side], sk['f' + side] = hp, knee, ank
    sk['wf'] = None if pose.nowf else place_weapon(body.weapon, sk['hf'], sk['el_f'], pose.wa)
    wf = sk['wf']
    if wf is not None and wf['spec'].grip2 and body.weapon_b is None and not pose.free_b and pose.doc != 'hb':
        g2 = min(wf['spec'].grip2, wf['grip'] + 0.5) if wf['spec'].kind not in ('spear', 'staff') else wf['spec'].grip2
        t = (sk['hf'][0] - wf['d'][0] * g2, sk['hf'][1] - wf['d'][1] * g2)
        el, hand = ik2(sk['sh_b'], t, body.upper, body.fore, pose.eb_b)
        sk['el_b'], sk['hb'] = el, hand
    sk['wb'] = place_weapon(body.weapon_b, sk['hb'], sk['el_b'], pose.wb)
    return sk


def _wfits(b, t):
    return all(XMIN <= p[0] <= XMAX and YMIN <= p[1] <= YMAX for p in (b, t))


def _wbad(b, t):
    """How far (design px) a weapon's ends stick out of the allowed box."""
    return sum(max(0.0, XMIN - p[0]) + max(0.0, p[0] - XMAX) + max(0.0, YMIN - p[1]) + max(0.0, p[1] - YMAX) for p in (b, t))


def _wends(spec, hand, a, g):
    d = (math.cos(math.radians(a)), math.sin(math.radians(a)))
    if spec.kind == 'bow':                         # a bow stands across the forearm, centred on the hand
        n = (-d[1], d[0])
        h = spec.length / 2.0
        return (hand[0] - n[0] * h, hand[1] - n[1] * h), (hand[0] + n[0] * h, hand[1] + n[1] * h)
    if spec.kind == 'chakram':
        r = spec.length / 2.0
        c = (hand[0] + d[0] * (r + 0.5), hand[1] + d[1] * (r + 0.5))
        return (c[0] - r, c[1] - r), (c[0] + r, c[1] + r)
    return (hand[0] - d[0] * g, hand[1] - d[1] * g), (hand[0] + d[0] * (spec.length - g), hand[1] + d[1] * (spec.length - g))


def place_weapon(spec, hand, el, ang):
    """Angle, grip and ends of a held weapon.  A weapon that would leave the cell first slides through the hand (poles),
    then turns in 6-degree steps toward the nearest angle that fits."""
    if spec is None:
        return None
    fa = math.degrees(math.atan2(hand[1] - el[1], hand[0] - el[0]))
    a = ang if ang is not None else fa + spec.rel
    g = spec.grip
    b, t = _wends(spec, hand, a, g)
    if not _wfits(b, t) and spec.slide:
        for g2 in [spec.grip + k * 0.5 for k in range(1, 40)] + [spec.grip - k * 0.5 for k in range(1, 40)]:
            if 2.0 <= g2 <= spec.length - 3.0:
                b, t = _wends(spec, hand, a, g2)
                if _wfits(b, t):
                    g = g2
                    break
    if not _wfits(b, t):
        # turn toward the side the weapon already leans: a blade over the top tips further back or further forward
        da = math.cos(math.radians(a))
        order = (-1, 1) if (min(b[1], t[1]) < YMIN and da < 0) else (1, -1)
        best = (_wbad(b, t), a, b, t)
        hit = None
        for k in range(1, 31):
            for s in order:
                a2 = a + s * 6 * k
                b2, t2 = _wends(spec, hand, a2, g)
                if _wfits(b2, t2):
                    hit = (a2, b2, t2)
                    break
                bad = _wbad(b2, t2)
                if bad < best[0]:
                    best = (bad, a2, b2, t2)
            if hit:
                break
        a, b, t = hit if hit else best[1:]
    d = (math.cos(math.radians(a)), math.sin(math.radians(a)))
    return dict(a=a, d=d, n=(-d[1], d[0]), hand=hand, butt=b, tip=t, grip=g, spec=spec)


def weapon_point(w, frac):
    """A point `frac` of the way from the butt to the tip (the strike point is ~0.85)."""
    if w['spec'].kind in ('bow', 'chakram', 'fan'):
        r = w['spec'].length * (0.5 if w['spec'].kind != 'fan' else 0.9)
        return (w['hand'][0] + w['d'][0] * r, w['hand'][1] + w['d'][1] * r)
    return (w['butt'][0] + (w['tip'][0] - w['butt'][0]) * frac, w['butt'][1] + (w['tip'][1] - w['butt'][1]) * frac)


# ---------------------------------------------------------------- drawing primitives in design units
class Pen:
    """Draws design-unit shapes into the part buffer at the current RES."""

    def __init__(self, d):
        self.d = d
        self.S = RES

    def P(self, p):
        return (p[0] * self.S, p[1] * self.S)

    def poly(self, pts, part):
        poly(self.d, [self.P(p) for p in pts], PID[part])

    def line(self, a, b, t, part):
        thick_line(self.d, self.P(a), self.P(b), max(1, rnd(t * self.S)), PID[part])

    def taper(self, a, b, t0, t1, part):
        taper_line(self.d, self.P(a), self.P(b), max(1, rnd(t0 * self.S)), max(1, rnd(t1 * self.S)), PID[part])

    def disc(self, c, r, part):
        S = self.S
        x0, y0 = rnd((c[0] - r) * S), rnd((c[1] - r) * S)
        x1, y1 = rnd((c[0] + r) * S) - 1, rnd((c[1] + r) * S) - 1
        if x1 >= x0 and y1 >= y0:
            self.d.ellipse([x0, y0, x1, y1], fill=PID[part])

    def ring(self, c, r, t, part):
        S = self.S
        self.d.ellipse([rnd((c[0] - r) * S), rnd((c[1] - r) * S), rnd((c[0] + r) * S) - 1, rnd((c[1] + r) * S) - 1],
                       outline=PID[part], width=max(1, rnd(t * S)))

    def dot(self, p, part):
        _px(self.d, rnd(p[0] * self.S), rnd(p[1] * self.S), PID[part])

    def hdline(self, a, b, part):
        """A one-pixel line at the real resolution (HD detail: seams, highlights)."""
        self.d.line([self.P(a), self.P(b)], fill=PID[part], width=1)


def _add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k)


def draw_weapon(pen, w, side, nock=None):
    """One held weapon: metal parts in wpn_<side>, wood / grip in hilt_<side>, an HD highlight along the blade."""
    if w is None:
        return
    sp, d, n, hand = w['spec'], w['d'], w['n'], w['hand']
    wp, hp = 'wpn_' + side, 'hilt_' + side
    k, L, wd = sp.kind, sp.length, sp.width
    hd = RES > 1
    if k in ('katana', 'short', 'energy', 'greatsword', 'dagger'):
        gb = _add(hand, d, 1.4 if k != 'greatsword' else 1.8)           # blade base, just past the guard
        tip = w['tip']
        bl = math.hypot(tip[0] - gb[0], tip[1] - gb[1])
        curve = 0.9 if k in ('katana', 'short', 'energy') else 0.0
        spine, edge = [], []
        steps = 8
        for i in range(steps + 1):
            t = i / steps
            c = _add(gb, d, bl * t)
            c = _add(c, n, -curve * t * t)                               # the katana curve: the tip lifts toward the spine
            hw = wd / 2.0 * (1.0 - 0.18 * t)
            if t > 0.82:
                hw *= max(0.0, (1.0 - t) / 0.18)
            spine.append(_add(c, n, -hw))
            edge.append(_add(c, n, hw * (0.9 if t > 0.82 else 1.0)))
        pen.poly(spine + [tip] + edge[::-1], wp)
        pen.line(w['butt'], _add(hand, d, 0.6), 1.7 if k != 'greatsword' else 2.0, hp)      # grip
        gl = {'katana': 1.6, 'short': 1.4, 'energy': 1.8, 'greatsword': 3.4, 'dagger': 1.8}[k]
        g0 = _add(hand, d, 1.0 if k != 'greatsword' else 1.3)
        pen.line(_add(g0, n, -gl), _add(g0, n, gl), 1.0 if k != 'greatsword' else 1.4, hp)  # guard
        if k == 'greatsword':
            pen.disc(w['butt'], 1.2, hp)                                 # pommel
        if hd:
            a = _add(_add(gb, d, bl * 0.08), n, -wd * 0.18)
            b = _add(_add(gb, d, bl * 0.74), n, -wd * 0.12 - curve * 0.5)
            pen.hdline(a, b, 'blade_hl')
    elif k == 'kunai':
        tip = w['tip']
        base = _add(hand, d, 1.0)
        mid = _add(base, d, (L - w['grip'] - 1.0) * 0.32)
        pen.poly([base, _add(mid, n, 1.3), tip, _add(mid, n, -1.3)], wp)
        pen.line(w['butt'], hand, 1.2, hp)
        pen.ring(_add(w['butt'], d, -0.6), 1.1, 0.6, wp)
        if hd:
            pen.hdline(_add(base, d, 0.6), _add(tip, d, -1.0), 'blade_hl')
    elif k == 'spear':
        tip = w['tip']
        hb = _add(tip, d, -5.2)
        pen.line(w['butt'], _add(hb, d, 0.5), 1.4, hp)
        pen.poly([tip, _add(hb, n, 2.3), _add(hb, d, 1.4), _add(hb, n, -2.3)], wp)
        pen.line(_add(hb, d, -0.6), _add(hb, d, -2.0), 2.0, wp)          # socket
        pen.line(w['butt'], _add(w['butt'], d, 1.4), 1.8, wp)            # butt cap
        if hd:
            pen.hdline(_add(hb, d, 1.2), _add(tip, d, -0.8), 'blade_hl')
    elif k == 'staff':
        pen.line(w['butt'], w['tip'], wd, hp)
        pen.line(w['butt'], _add(w['butt'], d, 2.2), wd + 0.8, wp)
        pen.line(w['tip'], _add(w['tip'], d, -2.2), wd + 0.8, wp)
        pen.line(_add(hand, d, 3.0), _add(hand, d, 3.8), wd + 0.4, wp)  # grip ring
        if hd:
            pen.hdline(_add(_add(w['butt'], d, 3), n, -0.5), _add(_add(w['tip'], d, -3), n, -0.5), 'blade_hl')
    elif k == 'kanabo':
        pen.line(w['butt'], _add(hand, d, 1.6), 1.7, hp)
        b0, tip = _add(hand, d, 1.6), w['tip']
        bl = math.hypot(tip[0] - b0[0], tip[1] - b0[1])
        pts_a, pts_b = [], []
        for i in range(7):
            t = i / 6
            c = _add(b0, d, bl * t)
            hw = 1.0 + (wd / 2.0 - 1.0) * min(1.0, t * 1.3)
            pts_a.append(_add(c, n, -hw))
            pts_b.append(_add(c, n, hw))
        pen.poly(pts_a + [_add(tip, d, 0.8)] + pts_b[::-1], wp)
        for i, t in enumerate((0.35, 0.55, 0.75, 0.92)):                 # iron studs, staggered
            c = _add(b0, d, bl * t)
            pen.dot(_add(c, n, (1 if i % 2 else -1) * wd * 0.22), 'blade_hl')
        pen.disc(w['butt'], 0.9, hp)
    elif k == 'axe':
        tip = w['tip']
        pen.line(w['butt'], tip, 1.6, hp)
        hc = _add(tip, d, -2.2)
        pen.poly([_add(hc, d, -2.6), _add(_add(hc, d, -4.4), n, 4.6), _add(_add(hc, d, -0.5), n, 5.6),
                  _add(_add(hc, d, 3.2), n, 4.4), _add(hc, d, 1.8)], wp)
        pen.poly([_add(hc, d, -1.0), _add(_add(hc, d, 0.2), n, -2.8), _add(hc, d, 1.2)], wp)   # back spike
        if hd:
            pen.hdline(_add(_add(hc, d, -3.6), n, 4.6), _add(_add(hc, d, 2.4), n, 4.4), 'blade_hl')
    elif k == 'tonfa':
        pen.line(w['butt'], w['tip'], wd, hp)
        pen.disc(w['butt'], wd * 0.6, hp)
        pen.line(hand, _add(hand, n, -2.0), 1.4, hp)                     # the side handle (under the fist)
        if hd:
            pen.hdline(_add(_add(w['butt'], d, 1), n, -0.5), _add(_add(w['tip'], d, -1), n, -0.5), 'blade_hl')
    elif k == 'fan':
        r = L
        pts = [hand]
        for i in range(11):
            a = math.radians(w['a'] - 55 + 110 * i / 10)
            pts.append((hand[0] + math.cos(a) * r, hand[1] + math.sin(a) * r))
        pen.poly(pts, wp)
        for i in (2, 5, 8):                                              # ribs
            a = math.radians(w['a'] - 55 + 110 * i / 10)
            e = (hand[0] + math.cos(a) * r * 0.9, hand[1] + math.sin(a) * r * 0.9)
            (pen.hdline if hd else (lambda p, q, part: None))(hand, e, 'seam')
        a0, a1 = math.radians(w['a'] - 55), math.radians(w['a'] + 55)
        pen.line((hand[0] + math.cos(a0) * r * 0.95, hand[1] + math.sin(a0) * r * 0.95), hand, 1.0, hp)
        pen.line((hand[0] + math.cos(a1) * r * 0.95, hand[1] + math.sin(a1) * r * 0.95), hand, 1.0, hp)
    elif k == 'chakram':
        r = L / 2.0
        c = _add(hand, d, r + 0.5)
        pen.ring(c, r, 1.6, wp)
        for i in range(4):
            a = math.radians(w['a'] + 45 + 90 * i)
            pen.line((c[0] + math.cos(a) * r, c[1] + math.sin(a) * r), (c[0] + math.cos(a) * (r + 1.4), c[1] + math.sin(a) * (r + 1.4)), 1.0, wp)
        if hd:
            pen.d.arc([rnd((c[0] - r + 0.8) * RES), rnd((c[1] - r + 0.8) * RES), rnd((c[0] + r - 0.8) * RES), rnd((c[1] + r - 0.8) * RES)],
                      200, 290, fill=PID['blade_hl'], width=1)
    elif k == 'bow':
        h = L / 2.0
        pts = []
        for i in range(9):
            t = -1 + 2 * i / 8
            pts.append(_add(_add(hand, n, t * h), d, 2.6 * (1 - t * t) - 1.4))
        tips = (pts[0], pts[-1])
        if nock is not None:                                             # V7: string drawn back to the rear hand, arrow nocked
            pen.line(tips[0], nock, 0.6, 'string')
            pen.line(nock, tips[1], 0.6, 'string')
            pen.line(nock, _add(hand, d, 3.0), 1.0, 'arrow')
            pen.dot(_add(hand, d, 3.6), 'blade_hl' if RES > 1 else 'arrow')
        else:
            pen.line(tips[0], tips[1], 0.6, 'string')
        for a_, b_ in zip(pts, pts[1:]):
            pen.line(a_, b_, 1.5, hp)
        pen.line(_add(hand, n, -1.2), _add(hand, n, 1.2), 2.2, wp)       # leather grip
        pen.dot(tips[0], wp)
        pen.dot(tips[1], wp)


def draw_swoosh(pen, pivot, a, b, width, part='swoosh'):
    """The crescent smear of a swing: the band between the path of the striking point (outer edge) and a path `width`
    inside it, hairline at the start and widest just before the end.  It goes round the front of the pivot."""
    ra, rb = math.hypot(a[0] - pivot[0], a[1] - pivot[1]), math.hypot(b[0] - pivot[0], b[1] - pivot[1])
    if ra < 1 or rb < 1:
        return
    aa, ab = math.atan2(a[1] - pivot[1], a[0] - pivot[0]), math.atan2(b[1] - pivot[1], b[0] - pivot[0])
    da = (ab - aa + math.pi) % (2 * math.pi) - math.pi
    alt = da - math.copysign(2 * math.pi, da)
    if math.cos(aa + alt / 2) > 0.25 and math.cos(aa + da / 2) < -0.1:   # swing round the front, not the back
        da = alt
    chord = math.hypot(b[0] - a[0], b[1] - a[1])
    if abs(da) < math.radians(12) and chord < 4:
        return
    if abs(da) < math.radians(25):                    # a thrust: a tapered speed band along the line of the stab
        nx, ny = -(b[1] - a[1]) / chord, (b[0] - a[0]) / chord
        ux, uy = (b[0] - a[0]) / chord, (b[1] - a[1]) / chord
        w = min(width * 0.45, 3.2)
        pen.poly([a, (b[0] + nx * w / 2, b[1] + ny * w / 2), (b[0] + ux * 1.5, b[1] + uy * 1.5), (b[0] - nx * w / 2, b[1] - ny * w / 2)], part)
        for off, k0 in ((w / 2 + 1.6, 0.25), (-(w / 2 + 1.6), 0.4)):      # speed lines either side of the stab
            pen.taper((a[0] + ux * chord * k0 + nx * off, a[1] + uy * chord * k0 + ny * off),
                      (b[0] - ux * 1.0 + nx * off, b[1] - uy * 1.0 + ny * off), 0.6, 1.2, part)
        return
    steps = max(8, int(abs(da) * max(ra, rb) / 1.5))
    outer, inner = [], []
    for i in range(steps + 1):
        t = i / steps
        ang = aa + da * t
        r = ra + (rb - ra) * t
        w = width * (math.sin(math.pi * min(1.0, t * 1.12)) ** 0.7) * (0.35 + 0.65 * t)
        outer.append((pivot[0] + math.cos(ang) * r, pivot[1] + math.sin(ang) * r))
        inner.append((pivot[0] + math.cos(ang) * max(0.5, r - w), pivot[1] + math.sin(ang) * max(0.5, r - w)))
    floor, ceil = GROUND - 1.0, TOP_CLEAR + 0.6               # squash the crescent against the floor and the cell top
    pen.poly([(x, max(ceil, min(y, floor))) for x, y in outer + inner[::-1]], part)


def draw_streak(pen, pivot, a, b, part='streak'):
    """A thin tapered speed streak along the path from a to b round the pivot (drawn on the frame after a smear)."""
    ra, rb = math.hypot(a[0] - pivot[0], a[1] - pivot[1]), math.hypot(b[0] - pivot[0], b[1] - pivot[1])
    aa, ab = math.atan2(a[1] - pivot[1], a[0] - pivot[0]), math.atan2(b[1] - pivot[1], b[0] - pivot[0])
    da = (ab - aa + math.pi) % (2 * math.pi) - math.pi
    alt = da - math.copysign(2 * math.pi, da)
    if math.cos(aa + alt / 2) > 0.25 and math.cos(aa + da / 2) < -0.1:
        da = alt
    if abs(da) < math.radians(15):
        return
    steps = max(6, int(abs(da) * max(ra, rb) / 1.2))
    for i in range(steps // 2, steps - 1):
        t = i / steps
        ang, r = aa + da * t, ra + (rb - ra) * t
        p = (pivot[0] + math.cos(ang) * (r + 1.5), pivot[1] + math.sin(ang) * (r + 1.5))
        if p[1] < GROUND - 1:
            stamp(pen.d, p[0] * RES, p[1] * RES, RES if t < 0.75 else RES + (1 if RES > 1 else 0), PID[part])


def bit_points(body, pose, bit, prev=None):
    """Points of one hanging bit.  It hangs at `rest`, and swings opposite to how far its anchor moved since `prev`."""
    def anchor(ps):
        bf = body_frame(body, ps)
        if bit.anchor == 'head':
            r_ = rot(bit.at, bf['tilt'])
            return (bf['head'][0] + r_[0], bf['head'][1] + r_[1])
        if bit.anchor in ('hb', 'hf'):
            return skeleton(body, ps)[bit.anchor]
        u, v = bf['u'], bf['v']
        a_, b_ = bit.at
        return (bf['hip'][0] + v[0] * a_ + u[0] * b_, bf['hip'][1] + v[1] * a_ + u[1] * b_)
    a = anchor(pose)
    pa = anchor(prev) if prev is not None else a
    vel = (a[0] - pa[0] + pose.dx * 0.5, a[1] - pa[1] + pose.vy)
    g = (math.cos(math.radians(bit.rest)), math.sin(math.radians(bit.rest)))
    pts = [a]
    for k in range(bit.n):
        lag = bit.lag * (1 + 0.6 * k)
        dx_, dy_ = g[0] - vel[0] * lag * 0.35, g[1] - vel[1] * lag * 0.35
        if dy_ < 0.15:                                    # a bit can flutter up to horizontal, never stand on end
            dy_ = 0.15
        n_ = math.hypot(dx_, dy_)
        p = (pts[-1][0] + dx_ / n_ * bit.seg, min(GROUND - 2.0, pts[-1][1] + dy_ / n_ * bit.seg))
        pts.append(p)
    return pts


def draw_bit(pen, pts, bit):
    n = len(pts) - 1
    for i in range(n):
        t0 = bit.width * (1 - 0.35 * i / max(1, n))
        t1 = bit.width * (1 - 0.35 * (i + 1) / max(1, n)) * (0.6 if i == n - 1 else 1)
        pen.taper(pts[i], pts[i + 1], t0, max(1.0, t1), bit.part)


def _px(d, x, y, fill):
    """One DESIGN pixel at cell position (x, y): a RES x RES block (a single pixel at RES 1)."""
    S = RES
    cw = W * S
    if 0 <= x < cw and 0 <= y < cw:
        if S == 1:
            d.point((x, y), fill=fill)
        else:
            d.rectangle([x, y, x + S - 1, y + S - 1], fill=fill)


def fx_draw(d, kind, x, y, extra=0, sigil='/'):
    """Small in-frame effects.  (x, y) is a cell position; the pattern offsets are design pixels."""
    x, y = rnd(x), rnd(y)
    S = RES
    a, b, w_, c = PID['fx_a'], PID['fx_b'], PID['fx_w'], PID['fx_c']

    def P(dx, dy, p):
        _px(d, x + dx * S, y + dy * S, p)
    if kind == 'spark':                  # 5x5 impact burst
        for (dx, dy, p) in [(0, 0, w_), (-1, 0, b), (1, 0, b), (0, -1, b), (0, 1, b),
                            (-2, 0, a), (2, 0, a), (0, -2, a), (0, 2, a), (-1, -1, a), (1, 1, a), (1, -1, a), (-1, 1, a)]:
            P(dx, dy, p)
    elif kind == 'spark_s':
        for (dx, dy, p) in [(0, 0, w_), (-1, 0, b), (1, 0, b), (0, -1, b), (0, 1, b)]:
            P(dx, dy, p)
    elif kind == 'block':                # cyan-white parry/block flash, uses white + accent
        for (dx, dy, p) in [(0, 0, w_), (-1, 0, c), (1, 0, c), (0, -1, c), (0, 1, c), (-2, -2, w_), (2, 2, w_), (2, -2, w_), (-2, 2, w_)]:
            P(dx, dy, p)
    elif kind == 'star':
        for (dx, dy, p) in [(0, 0, w_), (-1, 0, b), (1, 0, b), (0, -1, b), (0, 1, b)]:
            P(dx, dy, p)
    elif kind == 'zzz':
        s = 1 + (extra % 2)
        pts = [(xx, yy) for yy, row in enumerate(ZGLYPH) for xx, ch in enumerate(row) if ch == '#']
        for (dx, dy) in pts:
            for sx in range(s):
                for sy in range(s):
                    P(dx * s + sx, dy * s + sy, w_)
    elif kind == 'sweat':
        for (dx, dy, p) in [(0, 0, w_), (0, 1, w_), (-1, 2, c), (0, 2, c), (1, 2, c)]:
            P(dx, dy, p)
    elif kind in ('dust', 'dust2'):
        # V9: a small shaded puff in the fighter's own shoe tones (was a flat white blob): lit on top, darker at the
        # floor; `dust2` is the same puff a beat later, thinner and wider, about to vanish
        L_, D_ = PID['dust_l'], PID['dust_d']
        pts = ([(0, 0, L_), (1, 0, L_), (-1, 1, L_), (0, 1, D_), (1, 1, D_), (2, 1, L_)] if kind == 'dust'
               else [(-1, 0, L_), (2, 0, L_), (-2, 1, D_), (0, 1, L_), (3, 1, D_)])
        for (dx, dy, p) in pts:
            P(dx, dy, p)
    elif kind == 'thumb':
        P(0, 0, PID['hand_f'])
        P(0, -1, PID['hand_f'])
    elif kind == 'qmark':
        for (dx, dy) in [(0, 0), (1, 0), (2, 1), (1, 2), (1, 4)]:
            P(dx, dy, w_)
        P(1, 3, w_)
    elif kind == 'excl':
        for dy in range(4):
            P(0, dy, b)
        P(0, 5, b)
    elif kind == 'rewind':               # << glyph (Claude super)
        for off in (0, 4):
            for (dx, dy) in [(3, 0), (2, 1), (1, 2), (2, 3), (3, 4)]:
                P(off + dx - 3, dy, w_)
                P(off + dx - 2, dy, a if dy not in (2,) else b)
    elif kind == 'bigsigil':             # big $ above the head (Codex super)
        rows = ["..###..", ".#.#...", ".###...", "..###..", "...#.#.", "..###..", "...#..."]
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                if ch == '#':
                    P(xx - 3, yy, b if yy in (3,) else w_)
    elif kind == 'bigglyph':             # the character's own cap sigil at 2x above the head (supers)
        for yy, row in enumerate(GLYPH[sigil]):
            for xx, ch in enumerate(row):
                if ch == '#':
                    for sx in range(2):
                        for sy in range(2):
                            P(-3 + xx * 2 + sx, yy * 2 + sy, b if yy == 2 else w_)
    elif kind == 'charge':
        for (dx, dy, p) in [(0, 0, w_), (3, -2, b), (-3, -1, b), (2, 3, a), (-2, 3, w_), (5, 1, a)]:
            P(dx, dy, p)
    elif kind == 'charge_big':           # V4: a denser charge ball for ultimates (two rings of motes)
        for (dx, dy, p) in [(0, 0, w_), (1, 0, w_), (0, 1, w_), (1, 1, w_), (-1, 0, b), (2, 0, b), (0, -1, b), (1, 2, b),
                            (3, -2, a), (-3, -1, a), (2, 3, a), (-2, 3, b), (5, 1, a), (-4, 2, a), (4, -4, b), (-3, -4, a)]:
            P(dx, dy, p)
    elif kind == 'shock':                # ground shock wave streaks
        for k in range(6):
            P(k * 2, 0, w_)
            P(-k * 2, 0, w_)
            if k in (1, 3):
                P(k * 2, -1, b)
                P(-k * 2, -1, b)
    elif kind == 'speedlines':           # V4: horizontal dash streaks behind a zipping fighter
        for k, (dx, dy) in enumerate([(-4, -6), (-6, -2), (-5, 2), (-7, 6)]):
            for i in range(4 + (k % 2) * 2):
                P(dx - i, dy, w_ if i < 2 else c)
    # ---- V7 in-cell missiles (they fly inside the 64 px cell, which reaches past the opponent's front edge)
    elif kind == 'arrow':                # an arrow in flight: shaft, head, fletching and a short speed tail
        for i in range(7):
            P(-i, 0, b if i < 5 else a)
        P(1, 0, w_)
        P(0, -1, w_)
        P(0, 1, w_)
        P(-6, -1, a)
        P(-6, 1, a)
        for i in range(3):
            P(-9 - i * 2, 0, c)
    elif kind == 'kunai':                # a thrown kunai: blade, ring and a speed tail
        P(1, 0, w_)
        P(0, 0, w_)
        P(-1, -1, b)
        P(-1, 0, w_)
        P(-1, 1, b)
        P(-2, 0, b)
        P(-3, 0, a)
        for i in range(4):
            P(-5 - i * 2, 0, c)
    elif kind == 'chain':                # a chain from the anchor forward, `extra` px long, a kunai head at the end
        n = max(2, int(extra))
        for i in range(0, n, 2):
            P(i, 0, b if (i // 2) % 2 else a)
        P(n, 0, w_)
        P(n + 1, 0, w_)
        P(n, -1, b)
        P(n, 1, b)
    elif kind == 'gust':                 # a fan's wind gust: three nested arcs opening forward
        for r in (2, 4, 6):
            for dy in range(-r, r + 1):
                dx = int(round((r * r - dy * dy) ** 0.5 * 0.6))
                P(dx + r, dy, w_ if r == 2 else (b if r == 4 else c))




def draw_doc(d, x, y):
    x, y = rnd(x), rnd(y)
    S = RES
    d.rectangle([x, y, x + 6 * S - 1, y + 8 * S - 1], fill=PID['doc'])
    for yy in (2, 4, 6):
        d.rectangle([x + S, y + yy * S, x + 5 * S - 1, y + yy * S + S - 1], fill=PID['doc_line'])


# ---------------------------------------------------------------- headgear (head-local design coordinates)
HAIR = {
    'short': [(-5.4, 1.8), (-5.9, -1.5), (-4.8, -4.4), (-2.0, -5.9), (1.6, -5.9), (4.4, -4.4), (5.3, -2.6), (3.8, -2.9),
              (1.4, -3.3), (-1.4, -2.5), (-2.6, 0.2), (-3.4, 2.8)],
    'wild': [(-4.0, 5.6), (-7.6, 3.0), (-8.6, -1.0), (-7.6, -5.0), (-5.0, -7.4), (-1.0, -8.0), (3.0, -7.2), (5.6, -4.8),
             (6.0, -2.6), (3.8, -3.0), (1.0, -3.6), (-1.6, -2.8), (-2.8, 1.0), (-2.6, 4.6)],
}
SPIKES = [(-5.0, -2.6), (-8.8, -4.2), (-5.8, -5.2), (-7.0, -8.6), (-3.2, -6.4), (-2.4, -9.4), (0.0, -6.6), (2.4, -8.8),
          (2.8, -5.9), (5.8, -6.4), (4.6, -3.8)]
GEAR = {
    'kasa': [(-10.8, -2.6), (-9.4, -4.0), (-4.5, -6.9), (-1.0, -8.6), (2.5, -7.2), (8.4, -4.4), (10.6, -3.0), (10.2, -2.0),
             (-10.2, -1.7)],
    'cowl': [(-3.8, 5.8), (-6.0, 3.0), (-6.4, -1.5), (-6.0, -4.8), (-8.8, -9.0), (-3.6, -6.9), (0.5, -6.6), (4.2, -5.4),
             (6.1, -2.8), (6.3, -1.6), (3.0, -1.9), (0.0, -1.6), (-1.4, 1.2), (-1.2, 4.4), (-2.2, 6.4)],
    'visor': [(-5.9, 2.4), (-6.3, -1.5), (-5.0, -4.9), (-1.6, -6.5), (2.6, -6.3), (5.4, -4.2), (6.3, -1.8), (6.4, 1.2),
              (4.8, 1.4), (0.8, 1.0), (-1.6, 0.8), (-2.8, 3.4)],
    'horned': [(-6.0, 0.8), (-6.2, -2.4), (-4.6, -5.2), (-1.0, -6.4), (2.8, -6.0), (5.4, -3.8), (6.1, -1.8), (3.6, -2.2),
               (0.0, -2.4), (-2.6, -1.6), (-3.6, 1.4)],
    'kabuto': [(-6.0, -0.2), (-6.0, -3.4), (-4.0, -5.9), (-0.2, -6.8), (3.8, -6.0), (5.9, -3.6), (6.4, -2.0), (3.4, -2.4),
               (0.4, -2.6), (-2.4, -1.8)],
    'hood': [(-4.0, 6.0), (-6.4, 3.0), (-6.8, -1.6), (-6.2, -4.8), (-9.8, -6.0), (-5.0, -7.0), (-0.6, -7.0), (3.6, -5.8),
             (5.9, -3.2), (6.3, -2.0), (3.0, -2.3), (0.0, -2.0), (-1.6, 1.0), (-1.6, 4.2), (-2.8, 6.4)],
    'greathelm': [(-5.9, 4.6), (-6.3, 0.0), (-6.0, -4.2), (-4.0, -6.3), (1.0, -6.7), (5.0, -5.5), (6.5, -2.6), (6.7, 2.6),
                  (5.4, 5.4), (1.5, 6.4), (-3.6, 6.0)],
    'turban': [(-6.2, 0.8), (-6.8, -3.0), (-5.4, -6.4), (-1.6, -7.8), (2.6, -7.4), (5.7, -5.0), (6.3, -2.6), (3.4, -2.7),
               (0.2, -2.9), (-2.6, -1.9), (-3.4, 1.0)],
}
MASK = [(-1.3, 0.9), (6.5, 0.5), (6.1, 3.6), (3.6, 5.9), (-0.9, 6.0)]


def draw_head(pen, body, pose, sk):
    S = RES
    hc, tilt = sk['head'], sk['tilt']

    def L(p):
        r_ = rot(p, tilt)
        return (hc[0] + r_[0], hc[1] + r_[1])

    def LP(pts):
        return [L(p) for p in pts]
    gear = body.headgear
    # neck, then the head itself
    u = sk['u']
    pen.line((sk['S'][0] - u[0] * 0.5, sk['S'][1] - u[1] * 0.5), (sk['S'][0] + u[0] * (body.neck + 1.5), sk['S'][1] + u[1] * (body.neck + 1.5)), 3.4, 'head')
    hw, hh = rnd(sk['head_w'] * S), rnd(sk['head_h'] * S)
    x0, y0 = rnd(hc[0] * S - hw / 2 + 0.5), rnd(hc[1] * S - hh / 2 + 0.5)
    pen.d.ellipse([x0, y0, x0 + hw - 1, y0 + hh - 1], fill=PID['head'])
    pen.poly(LP([(4.6, -0.4), (6.3, 0.9), (4.8, 1.8)]), 'head')                  # nose
    if pose.face != 'back':
        pen.poly(LP([(5.2, 3.0), (5.0, 4.6), (3.0, 5.4)]), 'head')               # jaw / chin
    if body.hair not in ('bald', 'none') and gear not in ('greathelm', 'cowl', 'hood'):
        pen.poly(LP(HAIR['wild' if body.hair == 'wild' else 'short']), 'hair')
        if body.hair == 'spiky':
            pen.poly(LP(SPIKES), 'hair')
        if body.hair == 'bun':
            pen.disc(L((-3.6, -5.4)), 2.7, 'hair')
            pen.line(L((-2.4, -4.0)), L((-4.6, -3.6)), 1.0, 'band')
        if body.hair == 'topknot':
            pen.disc(L((-1.6, -6.4)), 1.7, 'hair')
            pen.line(L((-1.8, -5.6)), L((-0.6, -5.8)), 1.0, 'band')
        if body.hair == 'pony':
            pen.disc(L((-4.6, -4.4)), 1.6, 'hair')
            pen.line(L((-4.0, -3.4)), L((-5.4, -5.2)), 1.0, 'band')
        if body.hair == 'wild':
            pen.poly(LP([(-6.0, 4.0), (-9.6, 6.2), (-7.8, 2.0)]), 'hair')
    if gear not in ('greathelm', 'cowl', 'hood', 'turban'):
        pen.poly(LP([(-1.6, -0.6), (0.2, -0.8), (0.4, 1.8), (-1.4, 2.0)]), 'ear')
    if body.beard:
        pen.poly(LP([(0.0, 2.2), (5.8, 2.0), (5.6, 4.8), (3.4, 7.6), (0.6, 6.0), (-0.6, 3.6)]), 'beard')
    if body.face == 'mask':
        pen.poly(LP(MASK), 'mask')
    # ---- headgear
    if gear in GEAR:
        pen.poly(LP(GEAR[gear]), 'helm')
    if gear == 'kasa':
        pen.poly(LP([(-5.8, -3.6), (5.8, -3.9), (5.6, -2.5), (-5.8, -2.3)]), 'helm2')
        if S > 1:
            for x_ in (-6.5, -2.8, 3.0, 6.6):
                pen.hdline(L((-1.0 + (x_ + 1.0) * 0.18, -8.0)), L((x_, -2.6)), 'seam')
    elif gear == 'cowl':
        if S > 1:
            pen.hdline(L((-6.6, -6.0)), L((-3.0, -6.6)), 'seam')
    elif gear in ('crest', 'band', 'rag'):
        pen.poly(LP([(-5.8, -2.9), (5.7, -3.3), (5.8, -1.8), (-5.8, -1.4)]), 'helm2')
        if gear == 'crest':
            c = L((4.0, -2.6))
            r = 1.0 if S == 1 else 1.5
            for dx_, dy_ in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
                pen.dot((c[0] + dx_, c[1] + dy_), 'glow')
            if S > 1:
                for dx_, dy_ in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
                    pen.dot((c[0] + dx_ * 0.5, c[1] + dy_ * 0.5), 'glow')
        elif gear == 'band':
            pen.poly(LP([(2.0, -3.2), (5.6, -3.4), (5.7, -1.8), (2.0, -1.6)]), 'helm')   # forehead plate
    elif gear == 'visor':
        pen.poly(LP([(0.6, -1.7), (6.6, -2.0), (6.7, 0.6), (0.8, 0.9)]), 'lens')
        pen.poly(LP([(-2.2, -6.0), (-8.6, -8.6), (-6.8, -6.2), (-5.2, -3.8)]), 'helm2')
        if S > 1:
            pen.hdline(L((-5.6, -1.6)), L((-1.0, -5.6)), 'seam')
    elif gear == 'horned':
        for ex in (-3.4, 1.6):
            pen.poly(LP([(ex - 1.4, -4.8), (ex - 1.9, -7.6), (ex - 1.2, -9.8), (ex + 0.1, -10.2), (ex + 0.9, -8.8), (ex + 1.3, -5.0)]), 'horn')
            pen.line(L((ex - 0.4, -6.0)), L((ex - 0.5, -8.6)), 0.9 if S > 1 else 1.0, 'glow')
        pen.poly(LP([(-6.2, -0.4), (6.0, -2.6), (6.1, -1.4), (-6.0, 1.0)]), 'helm2')
    elif gear == 'kabuto':
        pen.poly(LP([(-6.4, -1.6), (-9.2, 0.8), (-8.8, 3.0), (-5.6, 3.4), (-3.2, 1.2), (-3.0, -1.0)]), 'helm')
        pen.poly(LP([(2.4, -5.8), (4.4, -7.6), (7.8, -11.0), (5.2, -7.0), (3.8, -5.2)]), 'glow')
        pen.poly(LP([(1.0, -6.3), (-0.4, -8.6), (-2.6, -11.0), (-0.2, -7.4), (2.2, -6.0)]), 'glow')
        pen.disc(L((2.0, -6.0)), 1.3, 'helm2')
        if S > 1:
            pen.hdline(L((-5.8, -2.4)), L((5.6, -3.0)), 'seam')
            pen.hdline(L((-8.4, 1.4)), L((-4.4, 1.8)), 'seam')
            pen.hdline(L((-7.4, -0.6)), L((-4.0, 0.0)), 'seam')
    elif gear == 'hood':
        for a_, b_ in zip([(6.0, -2.4), (3.0, -2.2), (0.0, -1.9), (-1.5, 1.0), (-1.5, 4.2)], [(3.0, -2.2), (0.0, -1.9), (-1.5, 1.0), (-1.5, 4.2), (-2.6, 6.2)]):
            pen.line(L(a_), L(b_), 0.8 if S > 1 else 1.0, 'band')
    elif gear == 'greathelm':
        pen.line(L((1.8, -0.9)), L((6.8, -1.1)), 1.0, 'mouth')
        pen.poly(LP([(0.2, -6.6), (1.8, -6.7), (2.0, 6.0), (0.4, 6.2)]), 'helm2')        # the riveted centre ridge
        if S > 1:
            for yy in (2.0, 3.6):
                for xx in (3.4, 5.0):
                    pen.dot(L((xx, yy)), 'mouth')
    elif gear == 'turban':
        if S > 1:
            for k in range(3):
                pen.hdline(L((-6.2 + k * 1.2, -0.6 - k * 1.6)), L((5.6, -3.4 - k * 1.2)), 'seam')
        else:
            pen.line(L((-5.4, -2.6)), L((5.6, -3.8)), 1.0, 'helm2')
    elif gear == 'oni':
        pen.poly(LP([(2.0, -4.8), (3.0, -8.6), (3.8, -9.6), (4.2, -8.4), (3.9, -4.6)]), 'horn')
        pen.poly(LP([(-2.8, -5.4), (-3.0, -9.4), (-2.2, -10.2), (-1.6, -9.0), (-0.8, -5.6)]), 'horn')
    if body.face == 'mask' and gear == 'turban':
        pass
    draw_face(pen, body, pose, L)
    return L


def _face_hd(pen, body, pose, L, fc):
    """V7 HD face (RES 2+): a real eye (white, iris, upper lid), a brow that carries the mood and a mouth that opens,
    grits or smiles.  Pixel offsets are HD pixels from the eye / mouth anchors; the profile faces right."""
    d = pen.d
    f = pose.face
    eye_part = 'lens' if body.face == 'glow' else 'eye'
    covered = body.face in ('slit', 'visor') or body.headgear in ('greathelm', 'visor')

    def P(x, y, part):
        d.point((x, y), fill=PID[part])

    def R(x0, y0, x1, y1, part):
        d.rectangle([x0, y0, x1, y1], fill=PID[part])
    base = FACES['n']['eye']
    c = L(((base[0][0] + base[1][0]) / 2, (base[0][1] + base[1][1]) / 2 - 0.2))
    x, y = rnd(c[0] * RES), rnd(c[1] * RES)
    if not covered and f != 'back':
        glow = eye_part == 'lens'
        if f in ('x',):
            for dx, dy in ((-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)):
                P(x + dx, y + dy, 'eye')
        elif f == 'w':                                   # happy: a closed upward arc
            P(x - 1, y + 1, eye_part); P(x, y, eye_part); P(x + 1, y + 1, eye_part)
        elif f == 'z':                                   # closed / bowing
            R(x - 1, y + 1, x + 1, y + 1, eye_part)
        elif f == 'h':                                   # hurt: squeezed shut, a ">" pointing back
            P(x - 1, y - 1, eye_part); P(x, y, eye_part); P(x + 1, y, eye_part); P(x - 1, y + 1, eye_part)
        else:
            wide = f == 'o'
            if not glow:
                R(x - 1, y - (1 if wide else 0), x, y + 1, 'eyew')          # the white
            R(x + 1, y - (1 if wide else 0) + (1 if f == 'b' else 0), x + 1, y + 1, eye_part)   # iris toward the front
            if f in ('g', 'f'):                          # determined: the lid slants down toward the nose
                P(x - 1, y - 1, 'brow'); P(x, y - 1, 'brow'); P(x + 1, y - 1, 'brow'); P(x - 2, y - 1, 'brow')
            elif f == 'b':                               # half-lid, glancing down
                R(x - 1, y, x + 1, y, 'brow')
            elif not wide:
                R(x - 1, y - 1, x + 1, y - 1, 'brow')
        # the brow carries the mood
        if f in ('g', 'f'):
            P(x - 2, y - 4, 'brow'); P(x - 1, y - 3, 'brow'); P(x, y - 3, 'brow'); P(x + 1, y - 2, 'brow')
        elif f == 'o':
            P(x - 2, y - 3, 'brow'); P(x - 1, y - 4, 'brow'); P(x, y - 4, 'brow'); P(x + 1, y - 4, 'brow')
        elif f == 'h':
            P(x - 2, y - 2, 'brow'); P(x - 1, y - 3, 'brow'); P(x, y - 3, 'brow'); P(x + 1, y - 4, 'brow')
        elif f in ('n', 'b', 'w'):
            R(x - 1, y - 3, x + 1, y - 3, 'brow')
    if body.face == 'mask' or body.headgear == 'greathelm' or f == 'back':
        return
    mp = fc['mouth'] or FACES['n']['mouth']
    m = L((sum(q[0] for q in mp) / len(mp), sum(q[1] for q in mp) / len(mp)))
    mx, my = rnd(m[0] * RES), rnd(m[1] * RES) + 1
    if f == 'o':                                         # a shout: open, a row of teeth on top
        R(mx - 1, my - 1, mx + 1, my + 2, 'mouth'); R(mx - 1, my - 1, mx + 1, my - 1, 'eyew')
    elif f in ('g', 'h'):                                # gritted teeth
        R(mx - 2, my - 1, mx + 1, my + 1, 'mouth'); R(mx - 1, my, mx + 1, my, 'eyew')
    elif f == 'w':                                       # a grin
        P(mx - 2, my - 1, 'mouth'); R(mx - 1, my, mx + 1, my, 'mouth'); P(mx + 2, my - 1, 'mouth'); P(mx, my + 1, 'mouth')
    elif f == 'x':                                       # a wobbly line
        P(mx - 2, my, 'mouth'); P(mx - 1, my - 1, 'mouth'); P(mx, my, 'mouth'); P(mx + 1, my - 1, 'mouth')
    elif f == 'z':
        R(mx - 1, my, mx, my, 'mouth')
    else:
        R(mx - 1, my, mx + 1, my, 'mouth')


def draw_face(pen, body, pose, L):
    S = RES
    if S > 1:
        _face_hd(pen, body, pose, L, FACES.get(pose.face, FACES['n']))
        return
    fc = FACES.get(pose.face, FACES['n'])
    covered = body.face in ('slit', 'visor') or body.headgear in ('greathelm', 'visor')
    eye_part = 'lens' if body.face == 'glow' else 'eye'
    if not covered and fc['eye']:
        if S == 1:
            for p in fc['eye']:
                pen.dot(L(p), eye_part)
        elif len(fc['eye']) == 2:
            (ax, ay), (bx, by) = fc['eye']
            c = L(((ax + bx) / 2, (ay + by) / 2 - 0.2))
            x, y = rnd(c[0] * S), rnd(c[1] * S)
            pen.d.rectangle([x, y, x + 1, y + 1], fill=PID[eye_part])                 # 2x2 HD eye
            if eye_part == 'eye':
                pen.d.rectangle([x - 1, y, x - 1, y + 1], fill=PID['eyew'])              # the white behind the iris
        else:
            for p in fc['eye']:
                pen.dot(L(p), eye_part)
    if not covered:
        for p in fc['brow']:
            c = L(p)
            if S == 1:
                pen.dot(c, 'brow')
            else:
                x, y = rnd(c[0] * S), rnd(c[1] * S)
                pen.d.rectangle([x, y, x + S - 1, y], fill=PID['brow'])
    if body.face != 'mask' and body.headgear != 'greathelm':
        for p in fc['mouth']:
            c = L(p)
            if S == 1 or pose.face in ('o', 'h', 'w', 'x'):
                pen.dot(c, 'mouth')
            else:
                x, y = rnd(c[0] * S), rnd(c[1] * S)
                pen.d.rectangle([x, y + 1, x + S - 1, y + 1], fill=PID['mouth'])


# ---------------------------------------------------------------- the body
def render_parts(body: Body, pose: Pose, scarf_pts=None, prev: Pose = None, hist=()):
    """Returns (part buffer 'L', meta dict).  Facing right.  `prev` (the previous frame's pose) drives the swing crescent
    on smear frames and the one-frame lag of the hanging bits; `hist` = (pose two frames back, prev) draws the speed
    streak on the frame after a smear.  Pose and body are design units; the buffer is RES x."""
    S = RES
    cw = W * S
    img = Image.new('L', (cw, cw), 0)
    d = ImageDraw.Draw(img)
    pen = Pen(d)
    sk = skeleton(body, pose)
    hip, Sh, u, v = sk['hip'], sk['S'], sk['u'], sk['v']
    tl = sk['torso']
    limb, wide, thin = body.limb, body.limb + body.leg_add, max(2, body.limb - 1)

    def T(a, b):
        return (hip[0] + v[0] * a + u[0] * b, hip[1] + v[1] * a + u[1] * b)

    def lerp(a, b, k):
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)

    def P(p):
        return (p[0] * S, p[1] * S)
    meta = {'hip': P(hip), 'head': P(sk['head']), 'sigil': None}

    # ---- swing smears behind everything: the crescent on the smear frame, a speed streak on the frame after it
    if prev is not None and is_smear(pose):
        psk = skeleton(body, prev)
        for side in ('f', 'b'):
            if getattr(pose, 'smear_' + side):
                w, pw = sk['w' + side], psk['w' + side]
                if w is not None and pw is not None and UNARMED:
                    pass                                 # the forged weapon draws its own swing
                elif w is not None and pw is not None:
                    draw_swoosh(pen, sk['sh_' + side], weapon_point(pw, 0.96), weapon_point(w, 0.96), max(4.0, w['spec'].length * 0.5))
                else:
                    draw_swoosh(pen, sk['sh_' + side], psk['h' + side], sk['h' + side], 3.6)
            if getattr(pose, 'smear_f' + side):
                draw_swoosh(pen, sk['hp_' + side], psk['f' + side], sk['f' + side], 7.0)
    elif len(hist) >= 2 and hist[-1] is not None and hist[-2] is not None and is_smear(hist[-1]):
        a_sk, b_sk = skeleton(body, hist[-2]), skeleton(body, hist[-1])
        for side in ('f', 'b'):
            if getattr(hist[-1], 'smear_' + side):
                w0, w1 = a_sk['w' + side], b_sk['w' + side]
                if w0 is not None and w1 is not None and UNARMED:
                    pass
                elif w0 is not None and w1 is not None:
                    draw_streak(pen, b_sk['sh_' + side], weapon_point(w0, 0.96), weapon_point(w1, 0.96))
                else:
                    draw_streak(pen, b_sk['sh_' + side], a_sk['h' + side], b_sk['h' + side])
            if getattr(hist[-1], 'smear_f' + side):
                draw_streak(pen, b_sk['hp_' + side], a_sk['f' + side], b_sk['f' + side])

    # ---- things worn on the back, hanging bits
    if body.quiver:
        q0, q1 = T(-body.torso_w * 0.42, 2.0), T(-body.torso_w * 0.70, tl + 3.4)
        pen.line(q0, q1, 3.2, 'back_b')
        qd = (q1[0] - q0[0], q1[1] - q0[1])
        n_ = math.hypot(*qd)
        qd = (qd[0] / n_, qd[1] / n_)
        for k_, off in enumerate((-1.0, 0.2, 1.3)):
            a_ = (q1[0] + qd[1] * off, q1[1] - qd[0] * off)
            pen.line(a_, (a_[0] + qd[0] * 2.6, a_[1] + qd[1] * 2.6), 1.0, 'arrow')
    for bit in body.bits:
        draw_bit(pen, bit_points(body, pose, bit, prev), bit)

    # ---- legs
    def shoe(side, ank, ang):
        fl = body.foot_len * S
        ax, ay = ank[0] * S, ank[1] * S
        cx_, cy_ = ax + (fl - 4 * S) / 2.0, ay
        hw, hh = fl / 2.0, 1.5 * S
        local = [(-hw, -hh + S), (-hw + S, -hh), (hw - 1.5 * S, -hh), (hw, -hh + S), (hw, hh), (-hw, hh)]
        poly(d, [(cx_ + rot(p_, ang)[0], cy_ + rot(p_, ang)[1]) for p_ in local], PID[f'shoe_{side}'])
        poly(d, rot_rect((cx_, ay + 1.5 * S), fl, 1.2 * S, ang), PID[f'sole_{side}'])

    def leg(side, ang):
        hp, knee, ank = sk['hp_' + side], sk['kn_' + side], sk['f' + side]
        pen.disc(hp, wide / 2.0 + 0.4, f'leg_{side}_th')
        pen.taper(hp, knee, wide + (1.0 if body.skirt == 'hakama' else 0.0), limb + 0.4, f'leg_{side}_th')
        if body.skirt == 'hakama':
            pen.taper(knee, ank, limb + 0.8, limb + 2.6, f'leg_{side}_sh')
        else:
            pen.taper(knee, ank, limb + 0.2, thin, f'leg_{side}_sh')
        if body.boots:
            pen.taper(lerp(knee, ank, 0.42), ank, limb + 1.0, limb + 0.6, f'boot_{side}')
        shoe(side, ank, ang)
        if S > 1 and body.skirt not in ('robe',):          # V7 HD: the cloth folds behind a bent knee, a crease down the thigh
            _crease_bend(pen, hp, knee, ank, 1.6)

    def arm(side, open_):
        base, el, hand = sk['sh_' + side], sk['el_' + side], sk['h' + side]
        up, fo, cuff = f'arm_{side}_up', f'arm_{side}_fo', f'cuff_{side}'
        loose = body.sleeves == 'loose'
        pen.disc(base, (limb + 1.2) / 2.0 + 0.3, up)
        pen.taper(base, el, limb + (1.8 if loose else 0.7), limb + (2.4 if loose else 0.1), up)
        dx_, dy_ = hand[0] - el[0], hand[1] - el[1]
        n_ = max(1e-6, math.hypot(dx_, dy_))
        dir_ = (dx_ / n_, dy_ / n_)
        if body.gauntlet:
            pen.taper(el, hand, limb + 0.4, limb + 0.6, cuff)
        else:
            pen.taper(el, hand, limb + (1.4 if loose else 0.0), thin, fo)
            pen.line(_add(hand, dir_, -2.0), _add(hand, dir_, -0.9), limb, cuff)
        w = sk['w' + side]
        if w is not None and not UNARMED:
            draw_weapon(pen, w, side, sk['hb'] if (pose.nock and side == 'f') else None)
        if S > 1:                                        # V7 HD: a crease where a bent elbow folds the sleeve
            _crease_bend(pen, base, el, hand, 1.4)
        hx, hy = hand[0] + dir_[0] * 1.2, hand[1] + dir_[1] * 1.2
        fist = pose.fist_f if side == 'f' else pose.fist_b
        if open_ and w is None:
            pen.poly([(hx - 1, hy - 2), (hx + 1, hy - 2), (hx + 1, hy + 1), (hx - 1, hy + 1)], f'hand_{side}')
            px_, py_ = -dir_[1], dir_[0]
            for k_ in (-1, 0, 1):
                pen.dot((hx + dir_[0] * 2.2 + px_ * k_ * 1.1, hy + dir_[1] * 2.2 + py_ * k_ * 1.1), f'hand_{side}')
        else:
            stamp(d, hx * S, hy * S, max(3, fist) * S if w is None else 3 * S, PID[f'hand_{side}'])
            if S > 1 and w is not None and side == 'f':  # V7 HD: knuckles across the fist that wraps the grip
                k0 = (hx + dir_[0] * 0.9, hy + dir_[1] * 0.9)
                pen.hdline((k0[0] - dir_[1] * 0.9, k0[1] + dir_[0] * 0.9), (k0[0] + dir_[1] * 0.9, k0[1] - dir_[0] * 0.9), 'crease')
        if body.pads:
            draw_pad(pen, body, side, base, el)
        return hand

    leg('b', pose.ang_b)
    arm('b', False)
    # ---- torso
    ws = pose.turn * pose.chest
    tw = body.torso_w
    hs, hw_, hh_ = tw * 0.5 * ws, tw * body.waist * 0.5 * pose.turn, tw * body.hip_w * 0.5 * pose.turn
    pen.poly([T(-hh_, 0), T(hh_, 0), T(hw_, tl * 0.42), T(hs, tl - 2.0), T(hs * 0.72, tl + 0.3), T(-hs * 0.72, tl + 0.3),
              T(-hs, tl - 2.0), T(-hw_, tl * 0.42)], 'torso')
    ch = body.chest
    if ch in ('robe', 'gi', 'wrap'):
        pen.line(T(hs * 0.72, tl - 0.2), T(-0.6, tl * 0.30), 1.7, 'lapel')
        pen.line(T(-hs * 0.55, tl - 0.4), T(0.4, tl * 0.38), 1.0, 'lapel')
    if ch == 'plate':
        pen.poly([T(-hs * 0.8, tl * 0.40), T(hs * 1.02, tl * 0.40), T(hs * 1.02, tl - 1.4), T(hs * 0.55, tl + 0.2),
                  T(-hs * 0.55, tl + 0.2), T(-hs * 0.86, tl - 1.6)], 'chest')
        if S > 1:
            pen.hdline(T(-hs * 0.7, tl * 0.62), T(hs * 0.95, tl * 0.62), 'seam')
            pen.hdline(T(0.6, tl * 0.42), T(0.6, tl - 0.6), 'seam')
    if ch == 'bare':
        pen.line(T(hs * 0.75, tl - 0.4), T(-hs * 0.7, tl * 0.32), 1.6, 'lapel')
        if S > 1:
            pen.hdline(T(0.8, tl * 0.70), T(hs * 0.8, tl * 0.64), 'seam')
            pen.hdline(T(1.4, tl * 0.25), T(1.4, tl * 0.48), 'seam')
    if ch == 'vest':
        pen.poly([T(-hs * 0.95, tl * 0.25), T(hs * 0.1, tl * 0.25), T(hs * 0.15, tl - 0.6), T(-hs * 0.9, tl - 0.6)], 'vest')
        pen.poly([T(hs * 0.45, tl * 0.25), T(hs * 0.95, tl * 0.25), T(hs * 0.95, tl - 1.2), T(hs * 0.55, tl - 0.8)], 'vest')
    if body.beads:
        for k_ in range(9):
            a_ = math.pi * (0.15 + 0.7 * k_ / 8)
            p_ = T(math.cos(a_) * hs * 0.75, tl - 0.5 - math.sin(a_) * 3.6)
            pen.dot(p_, 'beads')
            if S > 1:
                pen.dot((p_[0] + 0.5, p_[1]), 'beads')
    if S > 1 and ch in ('robe', 'gi', 'wrap', ''):
        pen.hdline(T(-hs * 0.6, tl * 0.55), T(-hs * 0.2, tl * 0.18), 'seam')        # a cloth fold
    # ---- front leg, skirt, belt
    leg('f', pose.ang_f)
    sk_len = {'hakama': 0.55, 'tassets': 0.50, 'loin': 0.55, 'robe': 0.95, 'kilt': 0.60}.get(body.skirt)
    if sk_len:
        kf, kb = (sk['kn_f'], sk['kn_b'])
        hf_, hb_ = (sk['hp_f'], sk['hp_b'])
        fr = lerp(hf_, kf, sk_len)
        bk = lerp(hb_, kb, sk_len)
        if fr[0] < bk[0]:
            fr, bk = bk, fr
        flare = 1.8 if body.skirt in ('robe', 'hakama') else 1.2
        top_f, top_b = T(hh_ + 0.6, 2.8), T(-hh_ - 0.6, 2.8)
        mid = ((fr[0] + bk[0]) / 2, max(fr[1], bk[1]) + (1.2 if body.skirt != 'hakama' else -1.0))
        pen.poly([top_b, top_f, (fr[0] + flare, fr[1]), mid, (bk[0] - flare, bk[1])], 'skirt')
        if S > 1 and body.skirt in ('tassets', 'kilt', 'loin'):
            for k_ in (0.33, 0.66):
                pen.hdline(lerp(top_b, top_f, k_), lerp((bk[0] - flare, bk[1]), (fr[0] + flare, fr[1]), k_), 'seam')
    pen.line(T(-hh_ - 0.3, 1.8), T(hh_ + 0.3, 1.8), 2.2 if body.sash else 1.3, 'belt')
    if body.sash:
        pen.disc(T(hh_ * 0.4, 1.6), 1.4, 'belt')

    # ---- head, then the front arm on top of everything
    draw_head(pen, body, pose, sk)
    arm('f', pose.open_f)
    hf_px, hb_px = P(sk['hf']), P(sk['hb'])
    meta.update(hf=hf_px, hb=hb_px, ff=P(sk['ff']), fb=P(sk['fb']), S=P(Sh))
    if sk['wf'] is not None:
        meta['wtip'] = P(weapon_point(sk['wf'], 0.9))

    # ---- effects
    if pose.doc:
        ax_, ay_ = hf_px if pose.doc == 'hf' else hb_px
        draw_doc(d, ax_ + 0.5 * S, ay_ - 5 * S)
    anchors = {'hf': hf_px, 'hb': hb_px, 'ff': P(sk['ff']), 'fb': P(sk['fb']), 'head': P(sk['head']), 'hip': P(hip),
               'S': P(Sh), 'abs': (0, 0)}
    text = []
    for f in pose.fx:
        kind, anc, ox, oy = f[0], f[1], f[2], f[3]
        extra = f[4] if len(f) > 4 else 0
        ax, ay = anchors[anc]
        if kind in ('spark', 'spark_s', 'block') and anc in ('hf', 'hb') and sk['w' + anc[1]] is not None:
            ax, ay = P(weapon_point(sk['w' + anc[1]], 0.9))      # a weapon hit sparks at the blade, not the fist
            ox, oy = ox * 0.4, oy * 0.4
        if kind in TEXT_FX:
            tx, ty = ax + ox * S, ay + oy * S
            bb = text_fx_bbox(kind, tx, ty, extra, body.sigil)
            if bb and bb[1] < TOP_CLEAR * S:            # letters above the head never leave the cell
                ty += TOP_CLEAR * S - bb[1]
            text.append((kind, tx, ty, extra))
        else:
            fx_draw(d, kind, ax + ox * S, ay + oy * S, extra, body.sigil)
    d.rectangle([0, 0, cw - 1, TOP_CLEAR * S - 1], fill=0)
    d.rectangle([0, (GROUND + 2) * S, cw - 1, cw - 1], fill=0)        # nothing sinks into the taskbar (outline row 59 max)
    if text:
        meta['pre_text'] = img.copy()
        meta['text_fx'] = text
        for kind, x, y, extra in text:
            fx_draw(d, kind, x, y, extra, body.sigil)
    return img, meta


def _crease_bend(pen, a, joint, b, length):
    """V7 HD: a short fold line on the inside of a bent joint (elbow, knee): from the joint back along the upper segment,
    offset toward the inside of the bend.  Nothing on a straight limb."""
    ux, uy = a[0] - joint[0], a[1] - joint[1]
    vx, vy = b[0] - joint[0], b[1] - joint[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if nu < 1e-6 or nv < 1e-6:
        return
    cosang = (ux * vx + uy * vy) / (nu * nv)
    if cosang < -0.80:                                   # nearly straight (> ~143 deg): no fold
        return
    ux, uy, vx, vy = ux / nu, uy / nu, vx / nv, vy / nv
    ix, iy = ux + vx, uy + vy                            # toward the inside of the bend
    ni = math.hypot(ix, iy) or 1.0
    ix, iy = ix / ni * 0.7, iy / ni * 0.7
    p0 = (joint[0] + ix + ux * 0.6, joint[1] + iy + uy * 0.6)
    p1 = (p0[0] + ux * length, p0[1] + uy * length)
    pen.hdline(p0, p1, 'crease')


def draw_pad(pen, body, side, base, el):
    part = 'pad_' + side
    du = (el[0] - base[0], el[1] - base[1])
    n_ = max(1e-6, math.hypot(*du))
    du = (du[0] / n_, du[1] / n_)
    nn = (-du[1], du[0])
    k = body.pads
    if k == 'sode':
        pen.poly([_add(_add(base, du, -1.2), nn, 3.0), _add(_add(base, du, -1.2), nn, -2.8),
                  _add(_add(base, du, 5.2), nn, -3.2), _add(_add(base, du, 5.2), nn, 3.4)], part)
        if RES > 1:
            for t in (1.4, 3.4):
                pen.hdline(_add(_add(base, du, t), nn, -3.0), _add(_add(base, du, t), nn, 3.2), 'seam')
    elif k == 'angled':
        pen.poly([_add(base, (-3.0, -0.4)), _add(base, (1.8, -1.2)), _add(base, (2.4, 1.4)), _add(base, (0.0, 3.0)), _add(base, (-3.2, 2.0))], part)
        if RES > 1:
            pen.hdline(_add(base, (-2.6, 0.6)), _add(base, (1.8, 0.0)), 'seam')
    elif k == 'round':
        pen.disc(_add(base, (0.0, -0.4)), 3.6, part)
        pen.disc(_add(base, (0.2, 2.4)), 2.6, part)
        if RES > 1:
            pen.hdline(_add(base, (-2.8, 1.4)), _add(base, (3.0, 1.2)), 'seam')
    elif k == 'fur':
        pen.poly([_add(base, p) for p in ((-3.6, 1.4), (-4.2, -1.4), (-2.6, -3.6), (0.0, -4.2), (2.8, -3.4), (4.4, -0.8),
                                          (3.4, 1.0), (2.2, 2.4), (0.6, 1.4), (-1.0, 2.8))], part)


def sigil_box_l(meta: dict, body: Body):
    """Top-left of the sigil's (3*RES x 5*RES) box in the LEFT-facing (mirrored) cell, or None (no sigil drawn)."""
    if not meta.get('sigil'):
        return None
    gx0, gy0 = meta['sigil']
    return W * RES - len(GLYPH[body.sigil][0]) * RES - gx0, gy0


def _glyph_cells(sym):
    """Every pixel of the sigil box at the current RES -> True where the glyph is inked."""
    S = RES
    gl = GLYPH[sym]
    return [((xx, yy), gl[yy // S][xx // S] == '#') for yy in range(len(gl) * S) for xx in range(len(gl[0]) * S)]


def mirror_parts(buf: Image.Image, meta: dict, body: Body):
    """Left-facing: mirror the buffer, then redraw any sigil un-mirrored and every letter effect un-mirrored."""
    m = meta.get('pre_text', buf).transpose(Image.FLIP_LEFT_RIGHT)
    cw = W * RES
    box = sigil_box_l(meta, body)
    if box:
        mx0, gy0 = box
        px = m.load()
        ok = (PID['cap'], PID['sigil'], PID['helm'])
        for (xx, yy), on in _glyph_cells(body.sigil):
            x, y = mx0 + xx, gy0 + yy
            if 0 <= x < cw and 0 <= y < cw and px[x, y] in ok:
                px[x, y] = PID['sigil'] if on else PID['helm']
    d = ImageDraw.Draw(m)
    for kind, x, y, extra in meta.get('text_fx', ()):
        bb = text_fx_bbox(kind, x, y, extra, body.sigil)
        if bb:
            shift = (cw - 1 - bb[2]) - bb[0]
            fx_draw(d, kind, x + shift, y, extra, body.sigil)
    return m


def text_fx_bbox(kind, x, y, extra, sigil):
    """Inclusive (x0, y0, x1, y1) of one effect's pixels as drawn at (x, y)."""
    cw = W * RES
    tmp = Image.new('L', (cw, cw), 0)
    fx_draw(ImageDraw.Draw(tmp), kind, x, y, extra, sigil)
    bb = tmp.getbbox()
    return (bb[0], bb[1], bb[2] - 1, bb[3] - 1) if bb else None


def mirror_rgba(im: Image.Image, meta: dict, body: Body):
    """Left-facing version of a finished RGBA frame (hand-polished override): flip it, then redraw any sigil
    un-mirrored at the generator's sigil position, only over pixels that are headgear or sigil colour."""
    m = im.convert('RGBA').transpose(Image.FLIP_LEFT_RIGHT)
    box = sigil_box_l(meta, body)
    if not box:
        return m
    cw = W * RES
    pal = body.palette
    sig = pal['trim']['hi']
    cap = {pal['helm'][t] for t in ('base', 'hi', 'sh')} | {rim_tone(pal['helm']), deep_tone(pal['helm'])}
    mx0, gy0 = box
    px = m.load()
    for (xx, yy), on in _glyph_cells(body.sigil):
        x, y = mx0 + xx, gy0 + yy
        if 0 <= x < cw and 0 <= y < cw and px[x, y][3] and (px[x, y][:3] in cap or px[x, y][:3] == sig):
            px[x, y] = (sig if on else pal['helm']['base']) + (255,)
    return m


def lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


_DOWN = {'hi2': 'hi', 'hi': 'base', 'base': 'sh', 'sh': 'sh2', 'sh2': 'sh2'}


def finish(buf: Image.Image, body: Body, pose: Pose, hip_y=None):
    """Part buffer -> RGBA: edge-based shading, tinted inner lines and a selective one-pixel outline.

    RES 1: three tones (highlight on the top-left edges, shadow on the bottom-right edges and under occluders).
    RES 2+: five tones - a one-pixel rim (hi2) where the material meets empty space top-left, a 2 px highlight band, the
    base, a 2 px shadow band, and a deep shadow (sh2) on the last pixel before a bottom-right edge or along a tinted inner
    line where another material crosses in front.  The outline is one pixel at every RES, tinted by the darkest
    neighbouring material (ink under a planted sole)."""
    S = RES
    cw = W * S
    px = buf.load()
    out = Image.new('RGBA', (cw, cw), (0, 0, 0, 0))
    op = out.load()
    pal = body.palette

    def part(x, y):
        return px[x, y] if 0 <= x < cw and 0 <= y < cw else 0

    def is_flat(n):
        return NAME[n] in FLAT

    def occluder(n, a):
        return n != 0 and n != a and not is_flat(n) and Z[n] > Z[a]

    def opens_hi(n, a):
        return n == 0 or (n != a and Z[n] < Z[a] and not is_flat(n))
    gcache = {}

    def grp_name(n):
        g = gcache.get(n)
        if g is None:
            g = gcache[n] = group_of(body, NAME[n])
        return g

    for y in range(cw):
        for x in range(cw):
            a = px[x, y]
            if not a:
                continue
            nm = NAME[a]
            if pose.flash and nm not in NOLINE:
                op[x, y] = pal['flash']['fill'] + (255,)
                continue
            if nm == 'crease':                           # V7 HD: a fold / knuckle line = the deep shadow of the material it crosses
                under = next((n for n in (part(x, y - 1), part(x - 1, y), part(x + 1, y), part(x, y + 1), part(x - 1, y - 1),
                                          part(x + 1, y + 1)) if n and NAME[n] not in FLAT), None)
                op[x, y] = (deep_tone(pal[grp_name(under)]) if under else pal['ink']['base']) + (255,)
                continue
            if nm in FLAT:
                g, tone = flat_of(body, nm)
                if g == 'fx':
                    op[x, y] = pal['fx'][tone] + (255,)
                else:
                    gg = pal[g]
                    t = tone or 'base'
                    op[x, y] = (rim_tone(gg) if t == 'hi2' else deep_tone(gg) if t == 'sh2' else gg[t]) + (255,)
                continue
            gname = grp_name(a)
            grp = pal[gname]
            up, lf, dn, rt = part(x, y - 1), part(x - 1, y), part(x, y + 1), part(x + 1, y)
            if nm == 'head' and rt == 0:                 # a profile face is lit from the front: no shadow stripe down it
                rt = a
            if S == 1:
                hi = opens_hi(up, a) or opens_hi(lf, a)
                sh = dn == 0 or rt == 0 or occluder(dn, a) or occluder(rt, a)
                tone = 'base' if (hi and sh) or (not hi and not sh) else ('hi' if hi else 'sh')
                if nm in DARK:
                    tone = {'hi': 'base', 'base': 'sh', 'sh': 'sh'}[tone]
                op[x, y] = grp[tone] + (255,)
                continue
            inner = any(occluder(n, a) and grp_name(n) != gname for n in (up, lf, dn, rt))
            rim = up == 0 or lf == 0
            edge_dr = dn == 0 or rt == 0
            near_hi = rim or opens_hi(up, a) or opens_hi(lf, a) or opens_hi(part(x, y - 2), a) or opens_hi(part(x - 2, y), a)
            near_sh = edge_dr or occluder(dn, a) or occluder(rt, a) or part(x, y + 2) == 0 or part(x + 2, y) == 0 \
                or occluder(part(x, y + 2), a) or occluder(part(x + 2, y), a)
            if inner:
                tone = 'sh2'
            elif edge_dr and not rim:
                tone = 'sh2'
            elif rim and not edge_dr:
                tone = 'hi2' if gname in RIM_GROUPS else 'hi'
            elif near_hi and not near_sh:
                tone = 'hi'
            elif near_sh and not near_hi:
                tone = 'sh'
            else:
                tone = 'base'
            if nm in DARK:
                tone = _DOWN[tone]
            col = rim_tone(grp) if tone == 'hi2' else deep_tone(grp) if tone == 'sh2' else grp[tone]
            op[x, y] = col + (255,)

    # selective outline, one pixel at every RES: tinted by the darkest neighbouring material, ink under a planted sole
    ol_pixels = {}
    for y in range(cw):
        for x in range(cw):
            if px[x, y]:
                continue
            best = None
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                n = part(x + dx, y + dy)
                if not n or NAME[n] in NOLINE:
                    continue
                nm = NAME[n]
                if pose.flash:
                    c = pal['flash']['ol']
                elif nm in FLAT:
                    g, _t = flat_of(body, nm)
                    c = pal['ink']['base'] if g in ('ink', 'paper', 'fx') else pal[g]['ol']
                else:
                    c = pal[grp_name(n)]['ol']
                    if dy < 0 and nm in ('sole_f', 'sole_b'):
                        c = pal['ink']['base']
                if best is None or lum(c) < lum(best):
                    best = c
            if best is not None:
                ol_pixels[(x, y)] = best
    for (x, y), c in ol_pixels.items():
        op[x, y] = c + (255,)

    if pose.aura:                                    # flickering flame ring (rage / power-up)
        import random
        rng = random.Random(pose.aura * 7919)
        ys = hip_y if hip_y is not None else body.hip_y0 * S
        cols = [pal['fx']['a'], pal['fx']['b'], pal['fx']['a']]
        cand = []
        r = 2 * S
        for y in range(max(r, TOP_CLEAR * S), cw - r):
            for x in range(r, cw - r):
                if op[x, y][3] or y > ys + 8 * S:
                    continue
                near = any(px[x + dx, y + dy] and NAME[px[x + dx, y + dy]] not in NOLINE
                           for dx in range(-r, r + 1, S) for dy in range(-r, r + 1, S) if 0 <= x + dx < cw and 0 <= y + dy < cw)
                if near:
                    cand.append((x, y))
        rng.shuffle(cand)
        for (x, y) in cand[:max(10 * S * S, len(cand) // 5)]:
            op[x, y] = cols[(x * 3 + y) % 3] + (255,)
    return out


def palette_of(frames):
    cols = set()
    for im in frames:
        for _, p in im.getcolors(1 << 20):
            if p[3]:
                cols.add(p[:3])
    return cols
