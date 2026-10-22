"""V9 fight-quality art fixes (docs/ANIMATION-NOTES.md section 11), asserted on the pose data and the built sheets:
real lift for the high-five, the grapple ultimate and the jumping victories; heavy weapons planted, never flipped, on the
spike landing; one-shots ending on the idle stance; no weapon flips between held keys; the hand-polish hook at 128 px."""
import json, math, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'art'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401
import rig  # noqa: E402
import roster  # noqa: E402
import moves as M  # noqa: E402
import build_fighters as BF  # noqa: E402
import qa_fight  # noqa: E402

_MV = {}


def mv_of(ch):
    if ch not in _MV:
        _MV[ch] = M.build_moves(ch)
    return _MV[ch]


def anim(ch, res=1):
    root = 'assets' if res == 1 else 'assets_hd'
    return json.loads((ROOT / root / ch / 'anim.json').read_text(encoding='utf-8'))['anims']


class RealLift(unittest.TestCase):
    """The rows that used to hop 2-4 px inside the cell now leave the floor on an `air` curve, hips at standing height."""

    def check_row(self, ch, name, apex_min):
        m = mv_of(ch)[name]
        self.assertIn('air', m, f'{ch}/{name}')
        hs = [k[1] for k in m['air']]
        self.assertGreaterEqual(max(hs), apex_min, f'{ch}/{name}')
        self.assertEqual(hs[0], 0, f'{ch}/{name}: starts on the floor')
        self.assertEqual(hs[-1], 0, f'{ch}/{name}: lands')
        self.assertGreaterEqual(min(ps.dy for ps, _ in m['frames']), -3, f'{ch}/{name}: no rise baked into the cell')
        for res in (1, 2):
            self.assertEqual(anim(ch, res)[name]['air'], m['air'], f'{ch}/{name} res {res}: built with the same keys')

    def test_highfive_is_a_real_hop_for_everyone(self):
        for ch in roster.NAMES:
            self.check_row(ch, 'highfive', 10)

    def test_grapple_ultimates_fly(self):
        for ch in roster.NAMES:
            ult = roster.get(ch).signature.get('ultimate')
            tpl = roster.get(ch).sig_moves[ult][0] if ult else None
            if tpl == 'grapple_strike':
                self.check_row(ch, ult, 10)
                m = mv_of(ch)[ult]
                t = sum(ms for _, ms in m['frames'][:m['hit_frame']])
                self.assertGreater(M.air_at(m['air'], t), 8, f'{ch}: the cross slash lands in the air')

    def test_jumping_victories_jump(self):
        n = 0
        for ch in roster.NAMES:
            style = roster.get(ch).style.get('victory', 'fistpump')
            if style in ('fistpump', 'brawler'):
                self.check_row(ch, 'victory', 12)
                n += 1
        self.assertGreater(n, 0)

    def test_no_row_hops_inside_the_cell_any_more(self):
        for ch in roster.NAMES:
            for name, m in mv_of(ch).items():
                if 'air' not in m:
                    self.assertGreater(min(ps.dy for ps, _ in m['frames']), -4, f'{ch}/{name}: a hop needs an air curve')


class SpikeLanding(unittest.TestCase):
    def test_the_weapon_is_planted_in_front_never_flipped_behind(self):
        for ch in roster.NAMES:
            c = roster.get(ch)
            m = mv_of(ch)['spike']
            a = [M._wangle(c.body, ps) for ps, _ in m['frames']]
            self.assertTrue(10 <= a[6] <= 100, f'{ch}: landing weapon angle {a[6]:.0f} (forward / down)')
            self.assertLess(abs(M._angdiff(a[6], a[5])), 60, f'{ch}: contact -> landing turns {a[5]:.0f} -> {a[6]:.0f}')
            self.assertLess(abs(M._angdiff(a[7], a[6])), 90, f'{ch}: landing -> recovery turns {a[6]:.0f} -> {a[7]:.0f}')
            g = anim(ch, 2)['spike']['grip']
            self.assertLess(abs(M._angdiff(g[6][2], g[5][2])), 60, f'{ch}: the built HD sheet agrees')


class Settles(unittest.TestCase):
    def test_one_shots_end_on_the_exact_idle_stance(self):
        for ch in ('claude', 'oni', 'knight', 'cursor'):
            mv = mv_of(ch)
            stance = mv['idle']['frames'][0][0]
            ends = [n for n, m in mv.items() if not m['loop'] and m['frames'][-1][0] == stance]
            self.assertGreater(len(ends), 25, ch)
            for n in ('jab', 'cross', 'throw', 'hit', 'uppercut'):
                self.assertIs(mv[n]['frames'][-1][0], stance, f'{ch}/{n}')

    def test_a_sleeper_s_weapon_lies_still(self):
        for ch in roster.NAMES:
            c = roster.get(ch)
            a = [M._wangle(c.body, ps) or 0 for ps, _ in mv_of(ch)['sleep']['frames']]
            spread = max(abs(M._angdiff(x, a[0])) for x in a)
            self.assertLess(spread, 15, f'{ch}: {a}')            # it was flipping 168-174 degrees with every breath

    def test_no_two_consecutive_frames_share_a_duration_on_settled_rows(self):
        for ch in ('claude', 'oni'):
            for n, m in mv_of(ch).items():
                ms = [x for _, x in m['frames']]
                if m.get('cat') == 'strike':
                    self.assertTrue(all(a != b for a, b in zip(ms, ms[1:])), f'{ch}/{n}: {ms}')


# measured 2026-10-21 for the V9 pass (art/qa_fight.py audit, 64 px): weapon flips (a turn of >= 100 degrees with >= 14 px of
# tip travel between two keys that are not smears) over all 13 fighters went 300 -> 45, and 250 -> 17 outside the rows that
# snap on purpose; rows hopping inside the cell 19 -> 0.  What is left is authored (the oni's kanabo dropping into its
# dragged stance, dash bursts, the start of a spin)
FLIP_CEILING = 22
ABRUPT_ROWS = ('thrown', 'spiked', 'launched', 'taunt2')     # hit reactions snap on purpose; the taunt twirl spins


class NoPops(unittest.TestCase):
    def test_weapon_flips_between_held_keys_stay_rare(self):
        rows = qa_fight.audit(None, 1, 14.0, 99.0)
        flips = [r for r in rows if r[5] == 'flip' and r[2] not in ABRUPT_ROWS]
        self.assertLessEqual(len(flips), FLIP_CEILING, '\n'.join(f'{r[1]}/{r[2]} f{r[3]}->f{r[4]}' for r in flips))
        hops = [r for r in rows if r[5] == 'cell-hop']
        self.assertEqual(hops, [])


class LandingSquash(unittest.TestCase):
    def test_every_aerial_lands_on_a_squash(self):
        n = 0
        for ch in roster.NAMES:
            for name, m in mv_of(ch).items():
                keys = m.get('air')
                if not keys or keys[-1][1] > 0:
                    continue
                ms = [x for _, x in m['frames']]
                st = [sum(ms[:i]) for i in range(len(ms))]
                up, land = False, None
                for k in keys:
                    if k[1] > 0:
                        up = True
                    elif up:
                        land = k[0]
                        break
                if land is None:
                    continue
                ps = m['frames'][max(j for j in range(len(ms)) if st[j] <= land + 1)][0]
                self.assertTrue(ps.sq < 0.97 or ps.dy >= 3 or ps.lean < -45, f'{ch}/{name}: lands without a squash')
                n += 1
        self.assertGreater(n, 100)


class Anchors(unittest.TestCase):
    """No anchor jitter: between two consecutive frames of a grounded row (no air curve, no authored travel, not a
    reaction) the lowest opaque row - the soles on the floor - moves by at most one pixel (RES 1 sheets, every fighter)."""

    def test_feet_stay_on_the_floor_between_frames(self):
        from minis_core.atlas import Library, available
        lib = Library()
        bad, pairs = [], 0
        for ch in available():
            a = lib[ch]
            for name, m in a.anim.items():
                if m.get('air') or m.get('cat') == 'reaction':
                    continue
                fr = m['frames']
                lows = []
                for i in range(len(fr)):
                    bb = a.frame_image(name, i, 1).getchannel('A').getbbox()
                    lows.append(bb[3] if bb else None)
                for i in range(len(fr) - 1):
                    if fr[i].get('dx') or fr[i + 1].get('dx') or lows[i] is None or lows[i + 1] is None:
                        continue
                    pairs += 1
                    if abs(lows[i] - lows[i + 1]) > 1:
                        bad.append((ch, name, i, lows[i], lows[i + 1]))
        self.assertGreater(pairs, 1500)
        self.assertEqual(bad, [])


class HandHookHD(unittest.TestCase):
    def test_a_128px_hand_frame_replaces_the_hd_frame_and_a_64px_one_never_does(self):
        c = roster.get('codex')
        rig.set_res(2)
        try:
            mv = M.build_moves(c)['idle']
            gen = BF.render_move(c, 'idle', mv)
            hand = gen[0]['r'].copy()
            hand.putpixel((4, 80), (255, 0, 255, 255))
            old = os.environ.get('MINIS_HAND_DIR')
            with tempfile.TemporaryDirectory() as tmp:
                os.makedirs(os.path.join(tmp, 'codex'))
                hand.save(os.path.join(tmp, 'codex', 'idle_0@2x.png'))
                small = gen[1]['r'].resize((64, 64))
                small.save(os.path.join(tmp, 'codex', 'idle_1.png'))           # a 64 px file: ignored at RES 2
                os.environ['MINIS_HAND_DIR'] = tmp
                try:
                    out = BF.render_move(c, 'idle', mv)
                finally:
                    if old is None:
                        os.environ.pop('MINIS_HAND_DIR', None)
                    else:
                        os.environ['MINIS_HAND_DIR'] = old
        finally:
            rig.set_res(1)
        self.assertEqual(out[0]['r'].tobytes(), hand.tobytes())
        self.assertEqual(out[0]['l'].getpixel((123, 80)), (255, 0, 255, 255))
        self.assertEqual(out[1]['r'].tobytes(), gen[1]['r'].tobytes())


if __name__ == '__main__':
    unittest.main()
