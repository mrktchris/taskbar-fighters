"""V4 ultimates: signature finishers (original art, no copied sprites), one per roster character.

Each template returns a move with cat='ultimate' plus `fx`: which effect in fx.json plays on which frames of this row
({'name', 'from', 'to'} spans or {'name', 'at'} one-shots; indices into this row).  `proj_frame` is the release frame
(the engine spawns the main effect there, anchored per fx.json), `hit_frame` the contact frame for dash-in hits.
Codex's spiral_orb carries a support row (`mirror_images`) referenced from its anim entry as `support`.

V5 keying (modelled on the archer's 11-frame draw-and-release, docs/ANIMATION-NOTES.md): a long charge that builds
in readable increments (aura 1 -> 4, the chest swelling, the stance sinking), ONE smear frame (40 ms) where both arms
are drawn as the arc they swept, a release hold that carries `hitstop_ms` and a `shake`, then an overshoot and a
heavy recovery.  Eight frames each, the sheet's column budget.
"""
from __future__ import annotations
from dataclasses import replace
from moves import M, p, push_dust

ULT_HITSTOP = 300


def _wa(move, angles):
    """V6: point the held weapon where each key of the ultimate needs it ({frame index: screen angle})."""
    fr = move['frames']
    for i, a in angles.items():
        ps, ms = fr[i]
        fr[i] = (replace(ps, wa=a, wb=a), ms)
    return move


def ult_radiant_beam(desc, **_):
    """Two-hand charge at the hip for 1.2 s with a growing glow, then a horizontal beam."""
    def ch(i):
        return (('charge_big', 'hb', -1, -1),) if i < 2 else (('charge_big', 'hb', -1, -1), ('spark_s', 'hf', -2, 1))
    return _wa(M([
        (p(dy=3, lean=-4, hf=(-5, 4), hb=(-6, 5), ff=(8, 0), fb=(-7, 0), face='g', fx=ch(0)), 200),
        (p(dy=4, lean=-6, chest=1.03, hf=(-5, 5), hb=(-6, 6), ff=(8, 0), fb=(-7, 0), face='g', aura=1, fx=ch(1)), 220),
        (p(dy=4, lean=-6, sq=0.97, chest=1.05, hf=(-6, 5), hb=(-7, 6), ff=(8, 0), fb=(-7, 0), face='g', aura=2, fx=ch(2)), 240),
        (p(dy=5, lean=-8, sq=0.95, chest=1.07, hf=(-6, 6), hb=(-7, 7), ff=(9, 0), fb=(-8, 0), face='o', aura=3, fx=ch(3)), 260),
        (p(dy=6, lean=-10, sq=0.92, chest=1.10, hf=(-7, 6), hb=(-8, 7), ff=(9, 0), fb=(-8, 0), face='o', aura=4, fx=ch(4)), 240),
        (p(dy=1, lean=22, dx=2, sq=1.06, hf=(12, -3), hb=(11, -2), fist_f=4, fist_b=4, ff=(10, 0), fb=(-9, 0), face='o',
           smear_f=(-7, 6), smear_b=(-8, 7)), 40),
        (p(dy=2, lean=26, hf=(12, -3), hb=(11, -2), fist_f=4, fist_b=4, ff=(11, 0), fb=(-9, 0), face='o', chest=1.06,
           fx=(('spark', 'hf', 4, 0),)), 600),
        (p(dy=3, lean=8, sq=0.96, hf=(8, 0), hb=(5, 1), face='b'), 260)],
        cat='ultimate', desc=desc, proj_frame=6, hit_frame=6, hitstop_ms=ULT_HITSTOP, shake=dict(frames=8, amp=3),
        fx=[{'name': 'radiant_beam_charge', 'from': 0, 'to': 4}, {'name': 'radiant_beam', 'at': 6}]), {0: 150, 1: 150, 2: 152, 3: 154, 4: 156, 5: -6, 6: -4})


def ult_spiral_orb(desc, **_):
    """A spinning sphere forms in the open hand, dash in with afterimages, thrust it home, spiral burst."""
    return _wa(M([
        (p(dy=2, lean=4, hf=(6, -3), hb=(3, -2), open_f=True, face='g', fx=(('charge', 'hf', 1, -4),)), 200),
        (p(dy=2, lean=4, chest=1.03, hf=(6, -3), hb=(3, -2), open_f=True, face='g', aura=1, fx=(('charge_big', 'hf', 1, -5),)), 210),
        (p(dy=3, lean=8, sq=0.95, chest=1.06, hf=(7, -4), hb=(3, -2), open_f=True, face='g', aura=2, fx=(('charge_big', 'hf', 1, -5), ('spark_s', 'hf', 1, -9))), 220),
        (p(dx=14, dy=0, lean=28, sq=1.08, hf=(7, -2), hb=(-4, 2), open_f=True, ff=(10, 2), fb=(-8, 3), ghost=(8, 16, 24), face='g',
           fx=(('charge_big', 'hf', 2, -4), ('speedlines', 'hip', -10, -6))), 70),
        (p(dx=14, dy=-1, lean=30, sq=1.04, hf=(7, -2), hb=(-4, 2), open_f=True, ff=(10, 2), fb=(-8, 3), ghost=(8, 16, 24), face='g',
           fx=(('charge_big', 'hf', 2, -4), ('speedlines', 'hip', -10, -6))), 60),
        (p(dx=4, dy=2, lean=26, hf=(12, -2), hb=(4, 0), open_f=True, ff=(11, 0), fb=(-9, 0), face='o', smear_f=(7, -2)), 40),
        (p(dy=2, lean=28, hf=(13, -2), hb=(4, 0), open_f=True, ff=(11, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 5, -1),)), 260),
        (p(dy=3, lean=10, sq=0.96, hf=(8, 0), hb=(5, 1), face='g'), 220)],
        cat='ultimate', desc=desc, proj_frame=6, hit_frame=6, hitstop_ms=ULT_HITSTOP, shake=dict(frames=6, amp=3),
        fx=[{'name': 'spiral_orb_core', 'from': 0, 'to': 5}, {'name': 'spiral_orb_burst', 'at': 6}]), {5: -4, 6: -2})


def sup_mirror_images(desc, **_):
    """Support: cross-finger hand sign, poof, three dithered clones rush out (the clones are the effect)."""
    return M([
        (p(dy=2, lean=4, sq=0.96, hf=(4, -5), hb=(4, -5), fist_f=4, fist_b=4, face='g'), 160),
        (p(dy=2, lean=4, chest=1.06, hf=(4, -5), hb=(4, -5), fist_f=4, fist_b=4, face='g',
           fx=(('spark_s', 'hf', 0, -1), ('dust', 'hip', -10, 2), ('dust', 'hip', 6, 3))), 120),
        (p(dy=2, lean=2, hf=(4, -5), hb=(4, -5), fist_f=4, fist_b=4, flash=True), 50),
        (p(dy=1, lean=8, hf=(10, -2), hb=(7, -1), face='g', fx=(('dust', 'hip', -9, 1), ('dust', 'hip', 8, 1))), 200),
        (p(dy=2, lean=10, hf=(9, -1), hb=(5, 0), face='g'), 160)],
        cat='support', desc=desc, proj_frame=2,
        fx=[{'name': 'clone_poof', 'at': 2}, {'name': 'mirror_images', 'at': 2}])


def ult_crescent_fang(desc, **_):
    """Arm raised overhead, energy gathers, a huge crescent slash wave is swung down and released."""
    return _wa(M([
        (p(dy=2, lean=-8, hf=(2, -11), hb=(-2, -3), eb_f='up', face='g', fx=(('charge', 'hf', 1, -3),)), 200),
        (p(dy=2, lean=-12, chest=1.03, hf=(0, -12), hb=(-3, -4), eb_f='up', face='g', aura=1, fx=(('charge_big', 'hf', 1, -4),)), 220),
        (p(dy=1, lean=-10, sq=1.04, chest=1.05, hf=(1, -12), hb=(-3, -4), eb_f='up', face='o', aura=2,
           fx=(('charge_big', 'hf', 0, -5), ('spark_s', 'hf', 3, -9))), 240),
        (p(dy=0, lean=-14, sq=1.06, chest=1.08, hf=(1, -13), hb=(-4, -4), eb_f='up', face='o', aura=3,
           fx=(('charge_big', 'hf', 0, -6),)), 180),
        (p(dy=2, lean=18, dx=3, hf=(12, 2), hb=(3, 3), fist_f=4, ff=(10, 0), fb=(-8, 0), ghost=(5,), face='o', smear_f=(1, -13)), 40),
        (p(dy=2, lean=26, dx=2, hf=(12, 2), hb=(3, 3), fist_f=4, ff=(11, 0), fb=(-9, 0), face='o', fx=(('spark', 'hf', 4, 0),)), 260),
        (p(dy=2, lean=28, hf=(12, 4), hb=(3, 3), fist_f=4, ff=(11, 0), fb=(-9, 0), face='o'), 80),
        (p(dy=3, lean=10, sq=0.96, hf=(8, 0), hb=(5, 1), face='g'), 220)],
        cat='ultimate', desc=desc, proj_frame=5, hit_frame=5, hitstop_ms=280, shake=dict(frames=6, amp=3),
        fx=[{'name': 'crescent_fang_charge', 'from': 0, 'to': 3}, {'name': 'crescent_fang', 'at': 5}]), {0: -100, 1: -104, 2: -104, 3: -108, 4: 30, 5: 36, 6: 52})


def ult_grapple(desc, **_):
    """Two grapple lines shoot out, the fighter zips along them and finishes with a spinning cross slash."""
    return _wa(M([
        (p(dy=2, lean=6, hf=(10, -5), hb=(9, -4), fist_f=4, fist_b=4, face='g'), 180),
        (p(dy=2, lean=4, chest=1.04, hf=(12, -6), hb=(11, -5), fist_f=4, fist_b=4, face='g',
           fx=(('spark_s', 'hf', 3, 0), ('spark_s', 'hb', 3, 0))), 200),
        (p(dy=3, lean=24, sq=0.90, hf=(11, -4), hb=(10, -3), fist_f=4, fist_b=4, ff=(8, 0), fb=(-5, 0), face='g'), 80),
        (p(dx=16, dy=-1, lean=75, sq=1.10, hf=(10, -2), hb=(8, -1), fist_f=4, fist_b=4, ff=(-2, 8), fb=(-6, 8), ghost=(10, 20, 30), face='g',
           fx=(('speedlines', 'hip', -8, -4),) + push_dust()), 70),
        (p(dx=16, dy=-1, lean=80, sq=1.06, hf=(10, -2), hb=(8, -1), fist_f=4, fist_b=4, ff=(-3, 9), fb=(-7, 9), ghost=(10, 20, 30), face='g',
           fx=(('speedlines', 'hip', -8, -4),)), 60),
        (p(dx=6, dy=-1, lean=10, turn=0.4, face='back', hf=(-8, -6), hb=(10, -6), fist_f=4, fist_b=4, ff=(4, 4), fb=(-4, 4),
           smear_b=(8, -1), smear_f=(10, -2)), 50),
        (p(dy=-1, lean=-6, turn=0.8, hf=(10, -8), hb=(-6, -4), fist_f=4, ff=(7, 4), fb=(-6, 3), face='g', fx=(('spark', 'hf', 3, -1), ('spark_s', 'hb', 2, -1))), 150),
        (p(dy=6, lean=14, sq=0.86, head=(2, 2), hf=(6, 2), hb=(2, 2), face='g', fx=(('dust', 'ff', 4, 1), ('dust', 'fb', -5, 1))), 220)],
        cat='ultimate', desc=desc, proj_frame=1, hit_frame=6, hitstop_ms=260, shake=dict(frames=5, amp=2),
        fx=[{'name': 'grapple_lines', 'at': 1}, {'name': 'grapple_slash', 'at': 6}],
        # V9: the zip is a real flight (the engine lifts it along `air`), not a 4 px rise inside the cell: off the floor on
        # the first zip key, highest through the spin, the cross slash lands on the way down, touchdown on the squash
        air_spec=[(3, 0, 0), (4, 0.5, 10, 'o'), (5, 1, 11, 'h'), (6, 0.4, 10, 'h'), (7, 0, 0, 'i')]), {5: -150, 6: 30})


def ult_gale_rend(desc, **_):
    """Both arms raised, power builds, a downward slam rips three energy claws along the ground."""
    return _wa(M([
        (p(dy=1, lean=-6, hf=(3, -12), hb=(1, -12), eb_f='up', eb_b='up', fist_f=4, fist_b=4, face='g', fx=(('charge', 'hf', 1, -3),)), 200),
        (p(dy=1, lean=-10, chest=1.03, hf=(2, -12), hb=(0, -12), eb_f='up', eb_b='up', fist_f=4, fist_b=4, face='g', aura=1,
           fx=(('charge_big', 'hf', 1, -4), ('spark_s', 'hb', -2, -3))), 220),
        (p(dy=0, lean=-12, sq=1.03, chest=1.06, hf=(2, -12), hb=(0, -12), eb_f='up', eb_b='up', fist_f=4, fist_b=4, face='o', aura=2,
           fx=(('charge_big', 'hf', 0, -5), ('spark_s', 'hb', -2, -4))), 240),
        (p(dy=0, lean=-14, sq=1.05, chest=1.08, hf=(2, -13), hb=(0, -13), eb_f='up', eb_b='up', fist_f=4, fist_b=4, face='o', aura=3,
           fx=(('charge_big', 'hf', 0, -5), ('charge', 'hb', -1, -5))), 200),
        (p(dy=6, lean=40, dx=2, sq=0.96, head=(2, 2), hf=(9, 8), hb=(7, 9), fist_f=4, fist_b=4, ff=(10, 0), fb=(-7, 0), face='o',
           smear_f=(2, -13), smear_b=(0, -13)), 40),
        (p(dy=7, lean=42, sq=0.88, head=(2, 2), hf=(9, 8), hb=(7, 9), fist_f=4, fist_b=4, ff=(10, 0), fb=(-7, 0), face='o',
           fx=(('shock', 'abs', 38, 56), ('dust', 'ff', 4, -1), ('dust', 'fb', -5, -1), ('spark', 'hf', 5, 1))), 300),
        (p(dy=4, lean=20, sq=0.95, hf=(6, 4), hb=(3, 5), face='g'), 180),
        (p(dy=2, lean=10, hf=(8, 0), hb=(5, 1), face='b'), 160)],
        cat='ultimate', desc=desc, proj_frame=5, hit_frame=5, hitstop_ms=ULT_HITSTOP, shake=dict(frames=6, amp=3),
        fx=[{'name': 'gale_rend_charge', 'from': 0, 'to': 3}, {'name': 'gale_rend', 'at': 5}]), {0: -96, 1: -98, 2: -100, 3: -102, 4: 60, 5: 66})


def ult_awakening(desc, **_):
    """Arms down, head back, a pillar of aura bursts up, then three flash-step strikes with holographic afterimages."""
    return _wa(M([
        (p(dy=2, lean=0, hf=(-2, 7), hb=(-4, 7), eb_f='back', eb_b='back', face='g'), 200),
        (p(dy=2, lean=-6, chest=1.04, head=(-1, -1), tilt=-10, hf=(-3, 8), hb=(-5, 8), eb_f='back', eb_b='back', face='o', aura=1), 220),
        (p(dy=1, lean=-8, sq=1.06, head=(-1, -1), tilt=-10, hf=(4, -6), hb=(0, -7), flash=True, aura=3), 100),
        (p(dy=1, lean=-6, chest=1.10, hf=(6, -8), hb=(2, -9), fist_f=4, fist_b=4, face='g', aura=4, fx=(('spark', 'hf', 1, -3),)), 240),
        (p(dx=18, dy=-1, lean=22, sq=1.04, hf=(12, -3), hb=(2, 2), fist_f=4, ff=(10, 1), fb=(-9, 1), ghost=(6, 12, 18), face='g', smear_f=(6, -8),
           fx=(('spark', 'hf', 4, 0), ('speedlines', 'hip', -9, -5))), 70),
        (p(dx=10, dy=-3, lean=20, hf=(12, -6), hb=(4, -2), fist_f=4, ff=(10, 2), fb=(-8, 2), ghost=(6, 12, 18), face='g', smear_f=(12, -3),
           fx=(('spark', 'hf', 4, -1), ('speedlines', 'hip', -9, -5))), 60),
        (p(dx=12, dy=1, lean=24, hf=(12, 0), hb=(3, 2), fist_f=4, ff=(11, 0), fb=(-9, 0), ghost=(6, 12, 18), face='g', smear_f=(12, -6),
           fx=(('spark', 'hf', 4, 0), ('speedlines', 'hip', -9, -5))), 80),
        (p(dy=3, lean=8, sq=0.95, hf=(8, -1), hb=(4, 1), face='g', aura=1), 300)],
        cat='ultimate', desc=desc, proj_frame=2, hit_frame=4, hitstop_ms=200, shake=dict(frames=4, amp=2),
        fx=[{'name': 'awakening_aura', 'at': 2}, {'name': 'awakening_slash', 'from': 4, 'to': 6}]), {0: 120, 1: 124, 3: -80, 4: 10, 5: -30, 6: 24})


def ult_star_core(desc, **_):
    """Both hands raised, a huge ball gathers overhead, then it is thrown with both arms."""
    return _wa(M([
        (p(dy=2, lean=-4, hf=(2, -12), hb=(-1, -12), eb_f='up', eb_b='up', open_f=True, face='g', fx=(('charge', 'hf', 0, -4),)), 240),
        (p(dy=2, lean=-4, chest=1.03, hf=(2, -12), hb=(-1, -12), eb_f='up', eb_b='up', open_f=True, face='g', aura=1,
           fx=(('charge_big', 'hf', 0, -5),)), 260),
        (p(dy=3, lean=-6, sq=1.03, chest=1.05, hf=(2, -12), hb=(-1, -12), eb_f='up', eb_b='up', open_f=True, face='o', aura=2,
           fx=(('charge_big', 'hf', 0, -6), ('spark_s', 'hb', -2, -5))), 300),
        (p(dy=3, lean=-8, sq=1.05, chest=1.08, hf=(2, -13), hb=(-1, -13), eb_f='up', eb_b='up', open_f=True, face='o', aura=3,
           fx=(('charge_big', 'hf', 0, -7), ('charge', 'hb', -1, -6))), 320),
        (p(dy=1, lean=24, dx=3, hf=(12, -4), hb=(11, -3), fist_f=4, fist_b=4, ff=(10, 0), fb=(-9, 0), face='o',
           smear_f=(2, -13), smear_b=(-1, -13)), 40),
        (p(dy=2, lean=22, hf=(12, -3), hb=(11, -2), fist_f=4, fist_b=4, ff=(10, 0), fb=(-9, 0), face='o', fx=(('spark_s', 'hf', 3, -1),)), 300),
        (p(dy=2, lean=26, hf=(13, -3), hb=(12, -2), fist_f=4, fist_b=4, ff=(10, 0), fb=(-9, 0), face='o'), 80),
        (p(dy=3, lean=10, sq=0.96, hf=(8, 0), hb=(5, 1), face='b'), 220)],
        cat='ultimate', desc=desc, proj_frame=5, hit_frame=5, hitstop_ms=280, shake=dict(frames=8, amp=3),
        fx=[{'name': 'star_core_orb', 'from': 0, 'to': 3}, {'name': 'star_core', 'at': 5}]), {0: -90, 1: -92, 2: -92, 3: -94, 4: -6, 5: 0, 6: 10})


ULTIMATES = {'radiant_beam': ult_radiant_beam, 'spiral_orb': ult_spiral_orb, 'crescent_fang': ult_crescent_fang, 'grapple_strike': ult_grapple,
             'gale_rend': ult_gale_rend, 'awakening': ult_awakening, 'star_core': ult_star_core}
SUPPORTS = {'mirror_images': sup_mirror_images}


def add_ultimate(mv, ch):
    """Append the character's ultimate (and its support move, if any) AFTER every existing row, so V3 row indices
    never move."""
    name = ch.signature.get('ultimate')
    if not name:
        return mv
    tpl, desc, opts = ch.sig_moves[name]
    mv[name] = ULTIMATES[tpl](desc, **opts)
    sup = opts.get('support')
    if sup:
        tpl2, desc2, opts2 = ch.sig_moves[sup]
        mv[sup] = SUPPORTS[tpl2](desc2, **opts2)
        mv[name]['support'] = sup
    return mv
