"""Art gates, asserted on the real sheets (assets/<character>/) and the real pose data, for every roster character.

The sheets are read directly here (not through minis_core.atlas) so these gates test the art alone."""
import json, math, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'art'))
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
import rig  # noqa: E402
import moves as M  # noqa: E402
import roster  # noqa: E402
import build_fighters as BF  # noqa: E402

CHARS = roster.NAMES
CAP = 32          # Pixel Joint fighting-character challenge: 32 colours counting transparency
SKINLIKE = {rig.PID[n] for n in ('head', 'ear', 'hand_f', 'hand_b', 'eye', 'brow', 'mouth',
                                  'arm_f_up', 'arm_f_fo', 'arm_b_up', 'arm_b_fo', 'cuff_f', 'cuff_b')}
SKIN = {rig.PID[n] for n in ('head', 'ear', 'hand_f', 'hand_b')}    # colours that can never equal a sigil colour
FX_IDS = {rig.PID[n] for n in ('fx_a', 'fx_b', 'fx_w', 'fx_c')}


class Sheet:
    """<root>/<character>/ as built: metadata, right- and left-facing sheets, projectile strip and effects sheet."""
    _cache = {}

    def __new__(cls, ch, root='assets'):
        key = (ch, root)
        if key not in cls._cache:
            o = super().__new__(cls)
            d = ROOT / root / ch
            o.root = root
            o.meta = json.loads((d / 'anim.json').read_text(encoding='utf-8'))
            o.anim = o.meta['anims']
            o.cell = int(o.meta['cell'][0])
            o.res = int(o.meta.get('res', 1))
            o.sheets = {k: Image.open(d / v).convert('RGBA') for k, v in o.meta['sheets'].items()}
            o.proj = Image.open(d / o.meta['projectile']['file']).convert('RGBA')
            o.fx = json.loads((d / 'fx.json').read_text(encoding='utf-8')) if (d / 'fx.json').exists() else None
            o.fxs = Image.open(d / o.fx.get('sheet', 'fx.png')).convert('RGBA') if o.fx else None
            cls._cache[key] = o
        return cls._cache[key]

    def frame(self, name, i, facing=1):
        r = self.anim[name]['row']
        c = self.cell
        return self.sheets['R' if facing >= 0 else 'L'].crop((i * c, r * c, (i + 1) * c, (r + 1) * c))

    def frames(self, name, facing=1):
        return [self.frame(name, i, facing) for i in range(len(self.anim[name]['frames']))]


def bbox(im):
    return im.getchannel('A').getbbox()


def parts(ch, name, i, scarf=True):
    """(right-facing part buffer, meta, pose) exactly as the builder renders it (previous poses included: they drive the
    swing crescent, the speed streak and the lag of the hanging bits)."""
    c = roster.get(ch)
    mv = M.build_moves(c)[name]
    poses = [f[0] for f in mv['frames']]
    pose = poses[i]
    pts = None
    if scarf and c.body.has_tail:
        pts = tracks(ch)[name][i]
    prev, prev2 = BF.frame_history(poses, i, mv['loop'])
    buf, meta = rig.render_parts(c.body, pose, pts, prev=prev, hist=(prev2, prev))
    return buf, meta, pose


_tracks = {}


def tracks(ch):
    """Scarf / ponytail points per move, computed the way build() computes them."""
    if ch not in _tracks:
        c = roster.get(ch)
        idle_pts = BF.idle_scarf(c)
        out = {}
        for name, mv in M.build_moves(c).items():
            poses = [f[0] for f in mv['frames']]
            start = None if name == 'idle' else idle_pts
            out[name] = BF.scarf_track(c.body, poses, mv['loop'], mv.get('loop_range'), start=start)
        _tracks[ch] = out
    return _tracks[ch]


def glyph_cells(sym):
    return {(x, y) for y, row in enumerate(rig.GLYPH[sym]) for x, ch in enumerate(row) if ch == '#'}


class Roster(unittest.TestCase):
    def test_every_roster_character_is_built_with_its_identity(self):
        programs = {'claude', 'codex', 'gemini', 'cursor', 'ollama', 'lmstudio', 'generic'}     # the engine's default mapping
        self.assertTrue(programs <= set(CHARS), f'a program character is missing: {programs - set(CHARS)}')
        self.assertEqual(set(CHARS) - programs, {'kunoichi', 'knight', 'barbarian', 'monk', 'nomad', 'oni'})   # V6 extras
        for ch in CHARS:
            self.assertTrue((ROOT / 'assets' / ch / 'anim.json').exists(), f'{ch}: not built into assets/')
            self.assertTrue((ROOT / 'assets_hd' / ch / 'anim.json').exists(), f'{ch}: not built into assets_hd/')
        for ch in CHARS:
            c, s = roster.get(ch), Sheet(ch)
            for k in ('character', 'display', 'tag', 'accent', 'signature'):
                self.assertIn(k, s.meta, f'{ch}: anim.json lacks {k}')
            self.assertEqual(s.meta['character'], ch)
            self.assertEqual(s.meta['tag'], c.tag)
            self.assertRegex(s.meta['accent'], r'^#[0-9A-F]{6}$')
            self.assertEqual(set(s.meta['signature']), {'strike', 'special', 'super', 'ultimate'})
        self.assertEqual(Sheet('claude').meta['tag'], '/reverse')
        self.assertEqual(Sheet('codex').meta['tag'], '$reverse')

    def test_identities_are_distinct(self):
        for key in ('tag', 'accent'):
            vals = [Sheet(ch).meta[key] for ch in CHARS]
            self.assertEqual(len(vals), len(set(vals)), f'two characters share a {key}: {vals}')
        sig = [roster.get(ch).body.sigil for ch in CHARS]
        self.assertEqual(len(sig), len(set(sig)), f'two characters share a cap sigil: {sig}')


class Palette(unittest.TestCase):
    def test_at_most_32_colours_including_transparency_and_one_shared_palette(self):
        for ch in CHARS:
            s = Sheet(ch)
            meta_pal = set(s.meta['palette'])
            seen = set()
            for k, sheet in s.sheets.items():
                a = sheet.getchannel('A')
                self.assertTrue(set(a.getcolors()) and {v for _, v in a.getcolors()} <= {0, 255}, f'{ch}/{k}: partial alpha pixel')
                for _, p in sheet.getcolors(1 << 16):
                    if p[3]:
                        seen.add('#%02X%02X%02X' % p[:3])
            self.assertLessEqual(len(seen) + 1, CAP, f'{ch}: {len(seen)} colours + transparency')
            self.assertTrue(seen <= meta_pal, f'{ch}: a frame uses a colour outside the shared palette: {seen - meta_pal}')
            self.assertEqual(s.meta['colors'], len(seen))


class Placement(unittest.TestCase):
    def test_every_frame_fits_the_cell_with_a_margin(self):
        for ch in CHARS:
            s = Sheet(ch)
            for name in s.anim:
                for facing in (1, -1):
                    for i, im in enumerate(s.frames(name, facing)):
                        bb = bbox(im)
                        self.assertIsNotNone(bb, f'{ch}/{name}/{i} is empty')
                        self.assertGreaterEqual(bb[1], 1, f'{ch}/{name}/{i} touches the top edge')
                        self.assertGreaterEqual(bb[0], 0)
                        self.assertLessEqual(bb[2], 64)

    def test_planted_soles_sit_on_the_same_baseline(self):
        soles = {rig.PID['sole_f'], rig.PID['sole_b']}
        for ch in CHARS:
            body = roster.get(ch).body
            checked = 0
            for name, m in M.build_moves(ch).items():
                for i, (pose, _) in enumerate(m['frames']):
                    grounded = (pose.ff[1] == 0 or pose.fb[1] == 0) and pose.lean > -45 and 0 <= pose.dy < 12 and not pose.flash
                    if not grounded or name in ('knockdown', 'ko', 'getup', 'sleep', 'wake'):
                        continue
                    buf, _ = rig.render_parts(body, pose, None)
                    px = buf.load()
                    low = max(y for y in range(64) for x in range(64) if px[x, y] in soles)
                    self.assertEqual(low, 57, f'{ch}/{name}/{i}: lowest sole row {low}, expected 57')
                    checked += 1
            self.assertGreater(checked, 150, ch)

    def test_nothing_dips_more_than_a_pixel_below_the_outline_row(self):
        for ch in CHARS:
            s = Sheet(ch)
            for name in s.anim:
                for i, im in enumerate(s.frames(name)):
                    self.assertLessEqual(bbox(im)[3], 60, f'{ch}/{name}/{i} reaches row {bbox(im)[3] - 1}')


class Motion(unittest.TestCase):
    def test_walk_planted_foot_does_not_slide(self):
        for ch in CHARS:
            for name in ('walk', 'walk_back'):
                fr = M.build_moves(ch)[name]['frames']
                for slot in ('ff', 'fb'):
                    world, track = 0.0, []
                    for pose, _ in fr + fr:                      # two cycles to cover the wrap
                        world += pose.dx
                        track.append((world + getattr(pose, slot)[0], getattr(pose, slot)[1] == 0))
                    cur = []
                    for wx, planted in track + [(0, False)]:
                        if planted:
                            cur.append(wx)
                        else:
                            if len(cur) >= 2:
                                self.assertLessEqual(max(cur) - min(cur), 1.0, f'{ch}/{name}/{slot} slides {max(cur) - min(cur)} px')
                            cur = []

    def test_walk_speed_matches_the_planners_speed(self):
        for ch in CHARS:
            m = M.build_moves(ch)['walk']
            stride = sum(abs(p.dx) for p, _ in m['frames'])
            cycle = sum(ms for _, ms in m['frames']) / 1000.0
            self.assertAlmostEqual(stride / cycle, 40.0, delta=1.0)

    def test_looping_moves_close_without_a_pop(self):
        """Every looping move, over its loop_range when it has one: the wrap is no bigger than a normal step."""
        def diff(a, b):
            pa, pb = a.load(), b.load()
            return sum(1 for y in range(64) for x in range(64) if pa[x, y] != pb[x, y])
        for ch in CHARS:
            s = Sheet(ch)
            for name, a in s.anim.items():
                if not a['loop']:
                    continue
                lo, hi = a.get('loop_range') or (0, len(a['frames']) - 1)
                if hi == lo:
                    continue
                fr = s.frames(name)[lo:hi + 1]
                step = max(diff(fr[i], fr[i + 1]) for i in range(len(fr) - 1))
                self.assertLessEqual(diff(fr[-1], fr[0]), step * 1.5 + 40, f'{ch}/{name} pops at the loop point')

    def test_jump_actually_leaves_the_ground(self):
        """V8: the trajectory is anim.json `air` (the engine lifts the sprite); the neutral jump really goes up."""
        for ch in CHARS:
            a = Sheet(ch).anim['jump']
            self.assertGreaterEqual(max(k[1] for k in a['air']), 18, ch)


class AirV8(unittest.TestCase):
    """V8 air contract (docs/ANIMATION-NOTES.md section 9): every airborne row carries `air`, the frames carry the pose."""
    LEAPS = ('jump', 'air_slash', 'spike', 'vault_kick', 'pole_vault', 'leap_shot')   # + the pound signature
    REACT = ('launched', 'air_hit', 'spiked', 'thrown')

    @staticmethod
    def headroom():
        try:
            from minis_core.config import JUMP_HEADROOM
            return JUMP_HEADROOM
        except Exception:                                   # noqa: BLE001
            return 30

    def leaps(self, ch):
        s = Sheet(ch)
        out = [n for n in self.LEAPS if n in s.anim]
        out += [n for n, (tpl, _d, _o) in roster.get(ch).sig_moves.items() if tpl == 'pound']
        return out

    @staticmethod
    def starts(a):
        ms = [f['ms'] for f in a['frames']]
        return ms, [sum(ms[:i]) for i in range(len(ms))]

    def test_every_air_row_has_keys_inside_the_headroom_with_the_right_eases(self):
        top = self.headroom() - 4
        for ch in CHARS:
            s = Sheet(ch)
            for n in self.leaps(ch) + list(self.REACT):
                a = s.anim[n]
                keys = a.get('air')
                self.assertTrue(keys, (ch, n))
                ms, st = self.starts(a)
                self.assertEqual([k[0] for k in keys], sorted(k[0] for k in keys), (ch, n))
                self.assertLessEqual(keys[-1][0], sum(ms), (ch, n))
                for k in keys:
                    self.assertTrue(0 <= k[1] <= top, (ch, n, k))
                for k0, k1 in zip(keys, keys[1:]):
                    e = k1[2] if len(k1) > 2 else 'l'
                    if k0[1] == 0 and k1[1] > 0:
                        self.assertEqual(e, 'o', (ch, n, 'leaving the floor rises like a thrown body', k1))
                    elif k0[1] > 0 and k1[1] == 0:
                        self.assertEqual(e, 'i', (ch, n, 'reaching the floor falls', k1))
                    elif k1[1] > k0[1]:
                        self.assertIn(e, ('o', 'h'), (ch, n, k1))
                    elif k1[1] < k0[1]:
                        self.assertIn(e, ('i', 'h'), (ch, n, k1))

    def test_leaps_load_push_off_hang_and_land_with_weight(self):
        """2-3 squash frames before the push-off, the push-off still on the floor with dust, a hang ('h') of 12-40 % of
        the airtime, the frame at the apex held longer than the push-off, the fall landing at least as hard as the rise
        left, a squash + dust frame exactly at touchdown, and the row inside 1.1 s."""
        for ch in CHARS:
            s = Sheet(ch)
            mv = M.build_moves(ch)
            for n in self.leaps(ch):
                a = s.anim[n]
                keys = a['air']
                ms, st = self.starts(a)
                poses = [f[0] for f in mv[n]['frames']]
                up = next(k[0] for i, k in enumerate(keys) if k[1] == 0 and keys[i + 1][1] > 0)
                down = next(k[0] for k in keys if k[0] > up and k[1] == 0)
                self.assertIn(up, st, (ch, n, 'take-off is a frame boundary'))
                push = st.index(up) - 1                                  # the push-off frame ends where the air starts
                self.assertGreaterEqual(push, 2, (ch, n))
                squash = [i for i in range(push) if poses[i].sq < 0.97]
                self.assertGreaterEqual(len(squash), 2, (ch, n, 'anticipation squash frames'))
                self.assertGreater(poses[push].sq, 1.05, (ch, n, 'push-off stretch'))
                self.assertTrue(any(f[0] == 'dust' for f in poses[push].fx), (ch, n, 'dust on the push-off'))
                air = down - up
                hang = sum(k1[0] - k0[0] for k0, k1 in zip(keys, keys[1:]) if len(k1) > 2 and k1[2] == 'h')
                self.assertTrue(0.12 <= hang / air <= 0.40, (ch, n, hang, air))
                rise = next(k[0] for k in keys if len(k) > 2 and k[2] == 'o') - up
                apex_k = max(keys, key=lambda k: k[1])
                k0, k1 = [(k0, k1) for k0, k1 in zip(keys, keys[1:]) if k1[1] == 0 and k0[1] > 0][0]
                v_rise = 2.0 * apex_k[1] / rise
                v_fall = 2.0 * k0[1] / (k1[0] - k0[0])
                self.assertGreater(v_fall, v_rise * 0.95, (ch, n, 'the landing is as hard as the take-off', v_rise, v_fall))
                hs = [(k0[0], k1[0]) for k0, k1 in zip(keys, keys[1:]) if len(k1) > 2 and k1[2] == 'h']
                over = [i for i in range(len(st)) if st[i] < hs[-1][1] and st[i] + ms[i] > hs[0][0]]
                apex_f = max(over, key=lambda i: ms[i])                  # the longest frame drawn during the hang
                self.assertGreater(ms[apex_f], ms[push], (ch, n, 'the apex frame is held longer than the push-off'))
                self.assertIn(down, st, (ch, n, 'touchdown is a frame boundary'))
                land = st.index(down)
                self.assertLessEqual(poses[land].sq, 0.9, (ch, n, 'landing squash'))
                self.assertTrue(any(f[0] in ('dust', 'shock') for f in poses[land].fx), (ch, n, 'landing dust'))
                self.assertLessEqual(sum(ms), 1100, (ch, n, sum(ms)))
            j = s.anim['jump']['air']
            ground = [k[0] for k in j if k[1] == 0]
            self.assertTrue(450 <= ground[-1] - ground[0] <= 520, (ch, 'neutral jump airtime', ground))
            self.assertTrue(18 <= max(k[1] for k in j) <= 20, (ch, 'neutral jump apex'))

    def test_airborne_frames_keep_the_hips_at_standing_height_in_the_cell(self):
        """The trajectory is the engine's: a frame drawn while lifted more than 4 px keeps its hips within 2 px of the
        standing hips (spiked / thrown only until they start to flatten out for the floor)."""
        for ch in CHARS:
            body = roster.get(ch).body
            stand = body.hip_y0 + body.kl * M.S0.dy                   # the stance's hips (before a planted foot sinks them)
            mv = M.build_moves(ch)
            for n in self.leaps(ch) + list(self.REACT):
                keys = mv[n]['air']
                ms = [f[1] for f in mv[n]['frames']]
                st = [sum(ms[:i]) for i in range(len(ms))]
                last = {'spiked': 0, 'thrown': 2}.get(n, len(ms) - 1)
                for i, (ps, m) in enumerate(mv[n]['frames'][:last + 1]):
                    if M.air_at(keys, st[i] + m / 2.0) > 4:
                        hip = rig.body_frame(body, ps)['hip'][1]
                        # the key right before touchdown may start to sink into the slam (pound's diving smear)
                        lim = 4.0 if i + 1 < len(st) and any(k[1] == 0 and k[0] == st[i + 1] for k in keys) else 2.0
                        self.assertLessEqual(abs(hip - stand), lim, (ch, n, i, hip, stand))

    def test_the_juggle_chain_is_continuous_and_the_strikes_meet_it(self):
        for ch in CHARS:
            s = Sheet(ch)
            hang = s.anim['launched']['air'][-1][1]
            self.assertEqual(hang, 21, ch)
            self.assertEqual(s.anim['air_hit']['air'][0][1], hang, ch)
            self.assertEqual(s.anim['air_hit']['air'][-1][1], hang, ch)
            self.assertEqual(s.anim['spiked']['air'][0][1], hang, ch)
            ms, st = self.starts(s.anim['launched'])
            self.assertGreaterEqual(M.air_at(s.anim['launched']['air'], st[3]), 20, (ch, 'launched is up within 3 frames'))
            for n in ('air_slash', 'spike'):
                a = s.anim[n]
                ms, st = self.starts(a)
                h = M.air_at(a['air'], st[a['hit_frame']])
                self.assertLessEqual(abs(h - hang), 3, (ch, n, h))
            sp = s.anim['spiked']
            ms, st = self.starts(sp)
            flat = next(i for i, f in enumerate(M.build_moves(ch)['spiked']['frames']) if f[0].lean <= -89)
            self.assertEqual(M.air_at(sp['air'], st[flat]), 0, (ch, 'spiked is on the floor on its impact frame'))
            self.assertTrue(2 <= max(k[1] for k in sp['air'] if k[0] > st[flat]) <= 3, (ch, 'one small bounce'))
            th = s.anim['thrown']
            ms, st = self.starts(th)
            self.assertEqual(M.air_at(th['air'], st[th['hit_frame']]), 0, (ch, 'thrown is slammed onto the floor at hit_frame'))
            self.assertTrue(12 <= max(k[1] for k in th['air']) <= 16, ch)

    def test_both_resolutions_carry_identical_air_keys(self):
        for ch in CHARS:
            lo, hi = Sheet(ch), Sheet(ch, 'assets_hd')
            for n, a in lo.anim.items():
                self.assertEqual(a.get('air'), hi.anim[n].get('air'), (ch, n))
            self.assertIn('air', lo.meta['schema_notes'])


class Scarf(unittest.TestCase):
    TAILS = [ch for ch in CHARS if roster.get(ch).body.has_tail]

    def test_no_long_tails_only_short_hanging_bits(self):
        """Owner 2026-10-14: no long trailing scarf / cape on anyone.  Cloth, hair and chains are short gravity-hanging
        bits (2-3 segments, at most ~7 px long) that lag one frame."""
        self.assertEqual(self.TAILS, [])
        for ch in CHARS:
            for bit in roster.get(ch).body.bits:
                self.assertTrue(2 <= bit.n <= 3, f'{ch}: a hanging bit with {bit.n} segments')
                self.assertLessEqual(bit.n * bit.seg, 7.5, f'{ch}: a hanging bit {bit.n * bit.seg:.1f} px long')
        self.assertTrue(any(roster.get(ch).body.bits for ch in CHARS))

    def test_hanging_bits_lag_the_motion_by_one_frame(self):
        """A bit hangs at rest when nothing moved and swings away from the direction its anchor just moved."""
        body = roster.get('claude').body
        bit = body.bits[0]
        still = rig.bit_points(body, rig.Pose(), bit, rig.Pose())
        moved = rig.bit_points(body, rig.Pose(), bit, rig.Pose(head=(-4, 0)))      # the head came from further back
        self.assertGreater(still[-1][0] - still[0][0], moved[-1][0] - moved[0][0] - 1e-6)
        self.assertLess(moved[-1][0] - moved[0][0], still[-1][0] - still[0][0])

    def test_segment_lengths_stay_bounded_in_every_frame(self):
        """The pole bug: a fall moved the neck 10+ px and the first segment stretched into a stick (knockdown/1)."""
        for ch in self.TAILS:
            n_seg, seg = roster.get(ch).body.tail_seg
            for name, tr in tracks(ch).items():
                for i, pts in enumerate(tr):
                    self.assertEqual(len(pts), n_seg + 1)
                    for k in range(n_seg):
                        L = math.dist(pts[k], pts[k + 1])
                        self.assertGreaterEqual(L, seg * 0.69, f'{ch}/{name}/{i} segment {k} is {L:.1f} px')
                        self.assertLessEqual(L, seg * 1.51, f'{ch}/{name}/{i} segment {k} is {L:.1f} px')

    def test_scarf_never_sinks_into_the_taskbar(self):
        for ch in self.TAILS:
            for name, tr in tracks(ch).items():
                for i, pts in enumerate(tr):
                    self.assertLessEqual(max(p[1] for p in pts[1:]), BF.FLOOR + 1e-6, f'{ch}/{name}/{i}')   # [0] is the neck

    def test_scarf_loops_close_over_the_loop_range(self):
        for ch in self.TAILS:
            body = roster.get(ch).body
            for name, mv in M.build_moves(ch).items():
                if not mv['loop']:
                    continue
                lo, hi = mv.get('loop_range') or (0, len(mv['frames']) - 1)
                tr = tracks(ch)[name]
                nxt = BF.scarf_step(body, tr[hi], mv['frames'][lo][0])
                err = max(math.dist(a, b) for a, b in zip(nxt, tr[lo]))
                self.assertLess(err, 0.5, f'{ch}/{name}: scarf jumps {err:.2f} px at the loop point')

    def test_non_looping_moves_start_from_the_idle_scarf(self):
        """A move that starts in the idle stance starts with the idle scarf shape, not its own end state."""
        for ch in self.TAILS:
            body = roster.get(ch).body
            idle_end = BF.idle_scarf(ch)
            for name, mv in M.build_moves(ch).items():
                if mv['loop']:
                    continue
                pose0 = mv['frames'][0][0]
                a0 = BF.head_attach(body, pose0)
                shifted = [(x + a0[0] - idle_end[0][0], y + a0[1] - idle_end[0][1]) for x, y in idle_end]
                want = BF.scarf_step(body, shifted, pose0)
                err = max(math.dist(a, b) for a, b in zip(want, tracks(ch)[name][0]))
                self.assertLess(err, 1e-6, f'{ch}/{name}: frame 0 scarf does not continue from idle')


class Look(unittest.TestCase):
    @staticmethod
    def _iou(a, b):
        pa, pb = Sheet(a).frame('idle', 0).getchannel('A').load(), Sheet(b).frame('idle', 0).getchannel('A').load()
        inter = union = 0
        for y in range(64):
            for x in range(64):
                p, q = pa[x, y] > 0, pb[x, y] > 0
                inter += p and q
                union += p or q
        return inter / union

    def test_the_claude_and_codex_silhouettes_differ(self):
        self.assertLess(self._iou('claude', 'codex'), 0.8)

    def test_every_idle_silhouette_is_distinct(self):
        """The flat-black silhouette test (docs/ANIMATION-NOTES.md section 6): no two idles overlap more than 80%."""
        for i, a in enumerate(CHARS):
            for b in CHARS[i + 1:]:
                self.assertLess(self._iou(a, b), 0.8, f'{a} and {b} have near-identical silhouettes')

    def test_proportions_are_about_four_and_a_half_heads(self):
        for ch in CHARS:
            body = roster.get(ch).body
            self.assertTrue(10 <= body.head_h <= 12, f'{ch}: head {body.head_h} px')
            self.assertGreaterEqual(body.thigh + body.shin, 20, f'{ch}: legs {body.thigh + body.shin} px')
            bb = bbox(Sheet(ch).frame('idle', 0))
            self.assertTrue(46 <= bb[3] - bb[1] <= 58, f'{ch}: idle is {bb[3] - bb[1]} px tall')

    def test_every_character_holds_a_weapon_and_every_strike_swings_it(self):
        for ch in CHARS:
            body = roster.get(ch).body
            self.assertIsNotNone(body.weapon, f'{ch}: no weapon')
            for name, mv in M.build_moves(ch).items():
                sm = mv.get('smear_frames') or []
                kick = sm and all(not (mv['frames'][i][0].smear_f or mv['frames'][i][0].smear_b) for i in sm)
                if mv['cat'] not in ('strike', 'ultimate') or kick:          # kicks smear the leg, not the weapon
                    continue
                if mv.get('type') in ('guard_break', 'riposte') and not mv['frames'][sm[0]][0].smear_f:
                    continue                  # V7: a pommel / shoulder drive: the smear is the driving arm's band + speed lines
                hand_smears = [i for i in sm if mv['frames'][i][0].smear_f or mv['frames'][i][0].smear_b]
                self.assertTrue(hand_smears, f'{ch}/{name}: the weapon never swings')
                i = hand_smears[0]
                buf, _, _ = parts(ch, name, i)
                n = buf.tobytes().count(bytes([rig.PID['swoosh']]))
                self.assertGreater(n, 0, f'{ch}/{name}/{i}: no crescent')

    def test_every_character_looks_different_from_every_other(self):
        for i, a in enumerate(CHARS):
            for b in CHARS[i + 1:]:
                pa = {c for _, c in Sheet(a).frame('idle', 0).getcolors(4096) if c[3]}
                pb = {c for _, c in Sheet(b).frame('idle', 0).getcolors(4096) if c[3]}
                self.assertLess(len(pa & pb) / len(pa | pb), 0.5, f'{a} and {b} share most idle colours')

    def test_no_orphan_pixels_except_intended_effects(self):
        kern = ImageFilter.Kernel((3, 3), [1, 1, 1, 1, 0, 1, 1, 1, 1], scale=1)
        for ch in CHARS:
            s = Sheet(ch)
            for name, m in M.build_moves(ch).items():
                for i, (pose, _) in enumerate(m['frames']):
                    if pose.fx or pose.ghost or pose.aura or rig.is_smear(pose) or (i and rig.is_smear(m['frames'][i - 1][0])):
                        continue                           # effects, trails, smears and their speed streak are intended
                    mask = s.frame(name, i).getchannel('A').point(lambda a: 1 if a else 0)
                    nb = mask.filter(kern).load()
                    mp = mask.load()
                    for y in range(1, 63):
                        for x in range(1, 63):
                            if mp[x, y] and not nb[x, y]:
                                self.fail(f'{ch}/{name}/{i}: orphan pixel at {(x, y)}')

    def test_stamp_corners_are_really_softened(self):
        for t, want in ((3, 9), (4, 12), (5, 21)):
            im = Image.new('L', (16, 16), 0)
            rig.stamp(ImageDraw.Draw(im), 8, 8, t, 1)
            px = im.load()
            n = sum(1 for y in range(16) for x in range(16) if px[x, y])
            self.assertEqual(n, want, f'stamp {t}')
            bb = im.getbbox()
            corner = px[bb[0], bb[1]]
            self.assertEqual(bool(corner), t < 4, f'stamp {t}: corner pixel')

    def test_zzz_reads_as_a_z_not_an_i(self):
        for extra in (0, 1):
            im = Image.new('L', (64, 64), 0)
            rig.fx_draw(ImageDraw.Draw(im), 'zzz', 20, 20, extra)
            px = im.load()
            rows = {}
            for y in range(64):
                xs = [x for x in range(64) if px[x, y]]
                if xs:
                    rows[y] = xs
            ys = sorted(rows)
            widths = [max(v) - min(v) + 1 for v in rows.values()]
            mid = [sum(rows[y]) / len(rows[y]) for y in ys if max(rows[y]) - min(rows[y]) + 1 < max(widths)]
            mid = [m for j, m in enumerate(mid) if j == 0 or m != mid[j - 1]]     # 2x scale repeats each row
            self.assertGreaterEqual(len(mid), 2, 'no diagonal')
            self.assertTrue(all(a > b for a, b in zip(mid, mid[1:])), f'diagonal must run top-right to bottom-left: {mid}')


class Sigil(unittest.TestCase):
    """Left-facing frames are the mirrored part buffer with the cap sigil redrawn un-mirrored."""

    def _box_colours(self, im, x0, y0):
        px = im.load()
        return {(x, y) for y in range(5) for x in range(3) if px[x0 + x, y0 + y][:3]}

    def test_v6_bodies_draw_no_letter_sigil_so_left_facing_is_a_plain_mirror(self):
        for ch in CHARS:
            c = roster.get(ch)
            self.assertFalse(c.body.show_sigil, ch)
            for name in ('idle', 'jab', 'victory'):
                buf, meta, _ = parts(ch, name, 0)
                self.assertIsNone(rig.sigil_box_l(meta, c.body))
                if 'text_fx' not in meta:
                    self.assertEqual(rig.mirror_parts(buf, meta, c.body).tobytes(), buf.transpose(Image.FLIP_LEFT_RIGHT).tobytes())

    def test_sigil_reads_correctly_on_the_real_sheets_in_both_facings(self):
        for ch in [n for n in CHARS if roster.get(n).body.show_sigil]:
            c, s = roster.get(ch), Sheet(ch)
            sig = c.body.palette['trim']['hi']
            want = glyph_cells(c.body.sigil)
            checked = 0
            for name, mv in M.build_moves(ch).items():
                for i, (pose, _) in enumerate(mv['frames']):
                    if pose.flash or pose.ghost:
                        continue
                    buf, meta, _ = parts(ch, name, i)
                    gx0, gy0 = meta['sigil']
                    bp = buf.load()
                    box = [(gx0 + x, gy0 + y) for y in range(5) for x in range(3)]
                    if not all(0 <= x < 64 and 0 <= y < 64 and bp[x, y] in (rig.PID['cap'], rig.PID['sigil']) for x, y in box):
                        continue                                   # cap partly occluded or off the crown this frame
                    for facing, x0 in ((1, gx0), (-1, rig.sigil_box_l(meta, c.body)[0])):
                        px = s.frame(name, i, facing).load()
                        got = {(x, y) for y in range(5) for x in range(3) if px[x0 + x, gy0 + y][:3] == sig}
                        self.assertEqual(got, want, f'{ch}/{name}/{i} facing {facing}: sigil {sorted(got)}')
                    checked += 1
            self.assertGreater(checked, 120, f'{ch}: too few unoccluded frames checked')

    def test_left_facing_redraw_never_paints_over_skin_or_hands(self):
        # The committed sheets are built on Windows.  The rig's float rounding can land one edge pixel differently on
        # another OS (seen on the macOS runners: barbarian/ground_slam/1 at (31,13), a cuff pixel - trim highlight, the
        # sigil's colour - that rendered as hand there), so off Windows only skin pixels whose four neighbours are skin
        # too are compared with the committed sheet.
        exact = sys.platform == 'win32'
        for ch in CHARS:
            c, s = roster.get(ch), Sheet(ch)
            sig = c.body.palette['trim']['hi']
            for name, mv in M.build_moves(ch).items():
                for i in range(len(mv['frames'])):
                    buf, meta, pose = parts(ch, name, i)
                    flipped = meta.get('pre_text', buf).transpose(Image.FLIP_LEFT_RIGHT).load()
                    left = rig.mirror_parts(buf, meta, c.body).load()
                    real = s.frame(name, i, -1).load()
                    for y in range(64):
                        for x in range(64):
                            if flipped[x, y] in SKINLIKE:
                                self.assertIn(left[x, y], {flipped[x, y]} | FX_IDS,
                                              f'{ch}/{name}/{i}: ({x},{y}) was {rig.NAME[flipped[x, y]]}, now {rig.NAME.get(left[x, y])}')
                                if left[x, y] == flipped[x, y] and left[x, y] in SKIN and not pose.flash:
                                    if not exact and not all(0 <= x + dx < 64 and 0 <= y + dy < 64 and left[x + dx, y + dy] in SKIN
                                                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                                        continue                   # an edge pixel: this OS may round it differently
                                    self.assertNotEqual(real[x, y][:3], sig, f'{ch}/{name}/{i}: sigil colour on skin at ({x},{y})')

    def test_letters_in_effects_are_not_mirrored_on_left_facing_frames(self):
        """'$', '>', 'L', '?', 'z' read the same way in both facings."""
        checked = 0
        for ch in CHARS:
            body = roster.get(ch).body
            for name, mv in M.build_moves(ch).items():
                for i, (pose, _) in enumerate(mv['frames']):
                    if not any(f[0] in rig.TEXT_FX for f in pose.fx):
                        continue
                    buf, meta, _ = parts(ch, name, i)
                    left = rig.mirror_parts(buf, meta, body)
                    for kind, x, y, extra in meta['text_fx']:
                        bb = rig.text_fx_bbox(kind, x, y, extra, body.sigil)
                        ref = Image.new('L', (64, 64), 0)
                        rig.fx_draw(ImageDraw.Draw(ref), kind, x + (63 - bb[2]) - bb[0], y, extra, body.sigil)
                        rp, lp = ref.load(), left.load()
                        for yy in range(64):
                            for xx in range(64):
                                if rp[xx, yy]:
                                    self.assertEqual(lp[xx, yy], rp[xx, yy], f'{ch}/{name}/{i}: {kind} mirrored at ({xx},{yy})')
                        checked += 1
        self.assertGreater(checked, 20)

    def test_hand_polished_frames_get_the_sigil_redrawn_for_left_facing(self):
        ch = 'codex'
        c = roster.get(ch)
        mv = M.build_moves(c)['idle']
        old = os.environ.get('MINIS_HAND_DIR')
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['MINIS_HAND_DIR'] = tmp                    # V9: art/hand/ holds this loop; the baseline is the bare rig
            try:
                gen = BF.render_move(c, 'idle', mv)
                hand = gen[0]['r'].copy()
                hand.putpixel((2, 40), (255, 0, 255, 255))       # a marker only an artist's frame would have
                os.makedirs(os.path.join(tmp, ch))
                hand.save(os.path.join(tmp, ch, 'idle_0.png'))
                out = BF.render_move(c, 'idle', mv)
            finally:
                if old is None:
                    os.environ.pop('MINIS_HAND_DIR', None)
                else:
                    os.environ['MINIS_HAND_DIR'] = old
        self.assertEqual(out[0]['r'].tobytes(), hand.tobytes(), 'the hand frame replaces the generated right frame')
        self.assertEqual(out[0]['l'].getpixel((61, 40)), (255, 0, 255, 255), 'the left frame is the mirror of the hand frame')
        if rig.sigil_box_l(gen[0]['meta'], c.body) is None:     # V6: no sigil, the left frame is exactly the mirror
            self.assertEqual(out[0]['l'].tobytes(), hand.transpose(Image.FLIP_LEFT_RIGHT).tobytes())
        else:
            x0, y0 = rig.sigil_box_l(gen[0]['meta'], c.body)
            sig = c.body.palette['trim']['hi']
            px = out[0]['l'].load()
            got = {(x, y) for y in range(5) for x in range(3) if px[x0 + x, y0 + y][:3] == sig}
            self.assertEqual(got, glyph_cells(c.body.sigil))
        self.assertEqual(out[1]['l'].tobytes(), gen[1]['l'].tobytes(), 'frames without a hand file are untouched')


class Reach(unittest.TestCase):
    def test_reach_is_measured_from_the_striking_pixels_on_the_real_sheet(self):
        for ch in CHARS:
            s = Sheet(ch)
            for name, a in s.anim.items():
                if 'hit_frame' not in a:
                    continue
                self.assertIn('reach', a, f'{ch}/{name}')
                i = a['hit_frame']
                buf, _, pose = parts(ch, name, i)
                if any(f[0] in BF.MISSILE_FX for f in pose.fx):
                    continue                  # V7: an in-cell missile is what lands (WeaponMovesV7 checks its reach)
                anc = next((f[1] for f in pose.fx if f[0] in BF.IMPACT_FX and f[1] in BF.STRIKE_PARTS), None)
                if anc is None:
                    top = 34 if a.get('type') in ('through', 'throw') else 30      # V7: a dash-through's frozen pose, a throw
                    if a.get('type') and any(f[0] == 'shock' for f in pose.fx):
                        top = 36                                                    # V7: a ground slam's travelling wave
                    self.assertTrue(8 <= a['reach'] <= top, f'{ch}/{name}: reach {a["reach"]}')
                    continue
                twin = {'hf': 'hb', 'hb': 'hf', 'ff': 'fb', 'fb': 'ff'}[anc]
                bp, sp = buf.load(), s.frame(name, i).load()
                for limbs in (BF.STRIKE_PARTS[anc], BF.STRIKE_PARTS[anc] + BF.STRIKE_PARTS[twin]):
                    ids = {rig.PID[n] for n in limbs}
                    xs = [x for y in range(64) for x in range(64) if bp[x, y] in ids and sp[x, y][3]]
                    if xs:
                        break
                # the striking limb's outer outline pixel is opaque on the real sheet, one past the limb
                edge = max(xs) + 1
                rows = [y for y in range(64) if bp[max(xs), y] in ids]
                self.assertTrue(any(sp[edge, y][3] for y in rows), f'{ch}/{name}: no outline beyond the striking limb')
                self.assertEqual(a['reach'], edge + 1 - rig.HIP_X, f'{ch}/{name}')

    def test_a_jab_reaches_further_than_an_uppercut(self):
        for ch in CHARS:
            an = Sheet(ch).anim
            self.assertGreater(an['jab']['reach'], an['uppercut']['reach'], ch)


class Schema(unittest.TestCase):
    REQUIRED = ['idle', 'walk', 'walk_back', 'dash', 'backdash', 'jump', 'crouch', 'jab', 'cross', 'uppercut', 'low_kick', 'roundhouse',
                'block', 'block_hit', 'parry', 'hit', 'hit_heavy', 'knockdown', 'getup', 'dizzy', 'ko', 'victory', 'taunt', 'bow',
                'fistbump', 'highfive', 'wave', 'work', 'type', 'review', 'wait', 'sleep', 'wake', 'powerup', 'rage', 'handoff_give', 'handoff_take', 'console']

    def test_every_character_has_the_full_shared_move_set(self):
        shared = None
        for ch in CHARS:
            s = Sheet(ch)
            for n in self.REQUIRED:
                self.assertIn(n, s.anim, f'{ch} is missing {n}')
            own = set(s.anim) - set(s.meta['signature'].values())
            own -= {a['support'] for a in s.anim.values() if a.get('support')}     # an ultimate's helper row
            own -= {n for n, a in s.anim.items() if a.get('family')}                # V7: the weapon family's own moves
            shared = own if shared is None else shared
            self.assertEqual(own, shared, f'{ch}: shared move set differs')

    def test_signature_moves_exist_and_have_the_right_shape(self):
        legacy = {'claude': ('spin_kick', 'slash_wave', 'reverse', 'radiant_beam'), 'codex': ('ground_pound', 'deploy', 'sudo', 'spiral_orb')}
        for ch, (st, sp, su, ul) in legacy.items():
            self.assertEqual(Sheet(ch).meta['signature'], {'strike': st, 'special': sp, 'super': su, 'ultimate': ul})
        for ch in CHARS:
            s = Sheet(ch)
            sig = s.meta['signature']
            for role in ('strike', 'special', 'super', 'ultimate'):
                self.assertIn(sig[role], s.anim, f'{ch}: signature {role} {sig[role]} is not in its move set')
            st, sp, su = (s.anim[sig[k]] for k in ('strike', 'special', 'super'))
            self.assertEqual(st['cat'], 'strike')
            self.assertIn('hit_frame', st)
            self.assertIn('reach', st)
            self.assertEqual(sp['cat'], 'special')
            self.assertIn('proj_frame', sp)
            self.assertEqual(len(sp['proj_from']), 2)
            self.assertEqual(su['cat'], 'super')

    def test_anim_json_schema_and_projectile(self):
        for ch in CHARS:
            s = Sheet(ch)
            d = s.meta
            self.assertEqual(d['cell'], [64, 64])
            self.assertEqual(d['ground_y'], 57)
            self.assertEqual(d['anchor'], {'R': 30, 'L': 33})
            self.assertEqual(d.get('res'), 1)
            for name, m in d['anims'].items():
                self.assertIn('row', m)
                self.assertTrue(all({'i', 'ms', 'dx'} <= set(f) for f in m['frames']), name)
                self.assertTrue(all(f['ms'] > 0 for f in m['frames']), name)
                if 'loop_range' in m:
                    lo, hi = m['loop_range']
                    self.assertTrue(0 <= lo <= hi < len(m['frames']), name)
            p = d['projectile']
            self.assertEqual(p['move'], d['signature']['special'])
            self.assertEqual(s.proj.size, (p['w'] * p['frames'], p['h']))
            for k in range(p['frames']):
                self.assertIsNotNone(s.proj.crop((k * p['w'], 0, (k + 1) * p['w'], p['h'])).getbbox(), f'{ch}: empty projectile frame {k}')


# ====================================================================== V4: resolution, effects, ultimates
ROOTS = {'assets': 1, 'assets_hd': 2}
CAPS = {1: 32, 2: 64}
GENERIC_FX = ('hit_light', 'hit_heavy', 'block_spark', 'dust', 'ko_stars', 'crack_small', 'crack_big', 'shatter', 'explosion',
              'letters', 'ko_text', 'round_text')
BANNER_FX = ('round_1', 'round_2', 'round_3', 'fight', 'winner', 'ko')
ULTIMATES = {'claude': 'radiant_beam', 'codex': 'spiral_orb', 'gemini': 'crescent_fang', 'cursor': 'grapple_strike',
             'ollama': 'gale_rend', 'lmstudio': 'awakening', 'generic': 'star_core',
             'kunoichi': 'petal_dance', 'knight': 'holy_crescent', 'barbarian': 'earthsplitter', 'monk': 'chi_sphere',
             'nomad': 'ring_storm', 'oni': 'oni_roar'}
FX_KEYS = {'frames', 'anchor', 'offset', 'loop', 'layer', 'hit_frame', 'travel', 'shake', 'grow', 'flash'}


def sheet_colours(im):
    a = im.getchannel('A')
    assert {v for _, v in a.getcolors()} <= {0, 255}, 'partial alpha'
    return {p[:3] for _, p in im.getcolors(1 << 20) if p[3]}


class Resolution(unittest.TestCase):
    """RES 1 = the V3 sheets byte for byte; RES 2 = the same moves in 128 px cells under a 64-colour cap."""

    def test_rows_match_the_v5_visual_regression_fixture(self):
        """Every row of every character, both facings and both resolutions, hashes to the fixture regenerated when
        the V5 fluid pass was signed off by eye (python tests/test_art.py --regen-hashes).  A hash mismatch means the
        art changed: look at it (art/qa_fluid.py strip ...), and regenerate only when the change is wanted."""
        fix = json.loads((ROOT / 'tests' / 'fixtures' / 'v5_frame_hashes.json').read_text())
        got = frame_hashes()
        self.assertEqual(set(got), set(fix), 'character / root set changed')
        for key, e in fix.items():
            g = got[key]
            self.assertEqual(g['proj'], e['proj'], f'{key}: proj.png changed')
            self.assertEqual(g['palette'], e['palette'], f'{key}: palette changed')
            self.assertEqual(list(g['moves']), list(e['moves']), f'{key}: move order changed')
            for name, m in e['moves'].items():
                for facing in ('R', 'L'):
                    self.assertEqual(g['moves'][name][facing], m[facing], f'{key}/{name} facing {facing} changed')
                self.assertEqual(g['moves'][name]['frames'], m['frames'], f'{key}/{name} timing')
                self.assertEqual(g['moves'][name]['meta'], m['meta'], f'{key}/{name} metadata')

    def test_v5_timing_rules_on_every_strike(self):
        """The fluid-pass contract: a strike has a smear before its contact, the contact carries hitstop, no two
        consecutive frames share a duration, and every smear frame is short."""
        for ch in CHARS:
            s = Sheet(ch)
            for name, a in s.anim.items():
                if a['cat'] not in ('strike', 'ultimate'):
                    continue
                ms = [f['ms'] for f in a['frames']]
                self.assertTrue(all(x != y for x, y in zip(ms, ms[1:])), f'{ch}/{name}: even timing {ms}')
                self.assertIn('hitstop_ms', a, f'{ch}/{name}')
                self.assertGreaterEqual(a['hitstop_ms'], 150)
                sm = a.get('smear_frames') or []
                self.assertTrue(sm, f'{ch}/{name}: no smear frame')
                self.assertTrue(all(ms[i] <= 110 for i in sm), f'{ch}/{name}: a smear frame is held {[ms[i] for i in sm]}')
                self.assertTrue(any(i <= a['hit_frame'] for i in sm), f'{ch}/{name}: the smear comes after the contact')
            self.assertIn('credits', s.meta)
            self.assertIn('hitstop_ms', s.meta['schema_notes'])

    def test_afterimages_trail_behind_the_motion_and_thin_out(self):
        """A dash's ghosts sit on the side the fighter came from; copies further back are sparser."""
        for ch in CHARS:
            s = Sheet(ch)
            for name, a in s.anim.items():
                for i, (pose, _) in enumerate(M.build_moves(ch)[name]['frames']):
                    if not pose.ghost or pose.flash:
                        continue
                    buf, meta, _ = parts(ch, name, i)
                    body_px = buf.load()
                    body_cols = [x for y in range(64) for x in range(64) if body_px[x, y] and rig.NAME[body_px[x, y]] not in rig.NOLINE]
                    real = s.frame(name, i).load()
                    ghost_cols = [x for y in range(64) for x in range(64) if real[x, y][3] and not body_px[x, y]
                                  and x not in range(min(body_cols) - 1, max(body_cols) + 2)]
                    if not ghost_cols:
                        continue
                    behind = sum(1 for x in ghost_cols if (x < min(body_cols)) == (pose.dx >= 0))
                    self.assertGreater(behind / len(ghost_cols), 0.9, f'{ch}/{name}/{i}: afterimage on the wrong side')

    def test_ultimate_rows_come_after_every_v3_row(self):
        for ch in CHARS:
            s = Sheet(ch)
            ult = s.meta['signature']['ultimate']
            v7 = {n for n, a in s.anim.items() if a.get('type')}                       # V7 rows come after the ultimate
            v3 = max(a['row'] for n, a in s.anim.items() if n not in (ult, s.anim[ult].get('support')) and n not in v7)
            self.assertGreater(s.anim[ult]['row'], v3, ch)
            self.assertGreater(min(s.anim[n]['row'] for n in v7), max(s.anim[ult]['row'], s.anim.get(s.anim[ult].get('support'), {}).get('row', 0)), ch)

    def test_rig_res_factor_scales_the_cell_and_is_restored(self):
        self.assertEqual(rig.RES, 1)
        try:
            rig.set_res(2)
            self.assertEqual((rig.cell_px(), rig.ground_px(), rig.hip_x_px()), (128, 114, 60))
            buf, meta = rig.render_parts(rig.CLAUDE, rig.Pose(), None)
            self.assertEqual(buf.size, (128, 128))
            im = rig.finish(buf, rig.CLAUDE, rig.Pose(), meta['hip'][1])
            self.assertEqual(im.size, (128, 128))
            self.assertIn(rig.rim_tone(rig.CLAUDE.palette['cloth']), {p[:3] for _, p in im.getcolors(4096) if p[3]}, 'HD adds the rim tone')
        finally:
            rig.set_res(1)
        buf, _ = rig.render_parts(rig.CLAUDE, rig.Pose(), None)
        self.assertEqual(buf.size, (64, 64))

    def test_hd_atlas_schema_matches_res1_with_scaled_geometry(self):
        for ch in CHARS:
            lo, hd = Sheet(ch), Sheet(ch, 'assets_hd')
            self.assertEqual(hd.meta['res'], 2)
            self.assertEqual(hd.meta['cell'], [128, 128])
            self.assertEqual(hd.meta['ground_y'], 114)
            self.assertEqual(hd.meta['anchor'], {'R': 60, 'L': 67})
            self.assertEqual(hd.meta['signature'], lo.meta['signature'])
            self.assertEqual(list(hd.anim), list(lo.anim), f'{ch}: HD move order differs')
            for name, a in lo.anim.items():
                b = hd.anim[name]
                self.assertEqual(b['row'], a['row'], f'{ch}/{name}')
                self.assertEqual([f['ms'] for f in b['frames']], [f['ms'] for f in a['frames']], f'{ch}/{name}')
                self.assertEqual([f['dx'] for f in b['frames']], [f['dx'] * 2 for f in a['frames']], f'{ch}/{name}: dx scales')
                for k in ('loop', 'cat', 'hit_frame', 'proj_frame', 'loop_range', 'power', 'fx', 'support'):
                    self.assertEqual(b.get(k), a.get(k), f'{ch}/{name}/{k}')
                if 'stride' in a:
                    self.assertEqual(b['stride'], a['stride'] * 2)
                if 'reach' in a:
                    self.assertTrue(1.6 * a['reach'] <= b['reach'] <= 2.4 * a['reach'] + 2, f'{ch}/{name}: reach {a["reach"]} -> {b["reach"]}')
            p = hd.meta['projectile']
            self.assertEqual((p['w'], p['h'], p['speed']), (48, 40, 260))
            self.assertEqual(hd.proj.size, (p['w'] * p['frames'], p['h']))
            for k, sheet in hd.sheets.items():
                self.assertEqual(sheet.size, (8 * 128, len(hd.anim) * 128), f'{ch}/{k}')

    def test_palette_caps_per_resolution_for_sheets_and_effects(self):
        for root, res in ROOTS.items():
            cap = CAPS[res]
            for ch in CHARS:
                s = Sheet(ch, root)
                seen = set()
                for k, sheet in s.sheets.items():
                    seen |= sheet_colours(sheet)
                self.assertLessEqual(len(seen) + 1, cap, f'{root}/{ch}: {len(seen)} colours + transparency')
                self.assertEqual(s.meta['colors'], len(seen), f'{root}/{ch}')
                self.assertTrue({('#%02X%02X%02X' % c) for c in seen} <= set(s.meta['palette']), f'{root}/{ch}: colour outside the shared palette')
                self.assertIsNotNone(s.fxs, f'{root}/{ch}: no fx.png')
                fxc = sheet_colours(s.fxs)
                self.assertLessEqual(len(fxc) + 1, cap, f'{root}/{ch}: fx.png {len(fxc)} colours + transparency')
            shared = ROOT / root / 'fx' / 'fx.png'
            self.assertTrue(shared.exists(), f'{root}/fx/fx.png missing')
            self.assertLessEqual(len(sheet_colours(Image.open(shared).convert('RGBA'))) + 1, cap)

    def test_hd_frames_fit_the_cell_and_planted_soles_sit_on_row_114(self):
        soles = {rig.PID['sole_f'], rig.PID['sole_b']}
        for ch in CHARS:
            s = Sheet(ch, 'assets_hd')
            for name in s.anim:
                for facing in (1, -1):
                    for i, im in enumerate(s.frames(name, facing)):
                        bb = bbox(im)
                        self.assertIsNotNone(bb, f'{ch}/{name}/{i} is empty')
                        self.assertGreaterEqual(bb[1], 1, f'{ch}/{name}/{i} touches the top edge')
                        self.assertLessEqual(bb[3], 120, f'{ch}/{name}/{i} reaches row {bb[3] - 1}')
        try:
            rig.set_res(2)
            for ch in CHARS:
                body = roster.get(ch).body
                exact = total = 0
                for name, m in M.build_moves(ch).items():
                    if name in ('knockdown', 'ko', 'getup', 'sleep', 'wake'):
                        continue
                    for i, (pose, _) in enumerate(m['frames']):
                        grounded = (pose.ff[1] == 0 or pose.fb[1] == 0) and pose.lean > -45 and 0 <= pose.dy < 12 and not pose.flash
                        if not grounded or i % 3:                        # every third grounded pose: enough to catch a shifted floor
                            continue
                        buf, _ = rig.render_parts(body, pose, None)
                        px = buf.load()
                        low = max(y for y in range(128) for x in range(128) if px[x, y] in soles)
                        self.assertTrue(113 <= low <= 114, f'{ch}/{name}/{i}: lowest sole row {low}')
                        exact += low == 114
                        total += 1
                self.assertGreater(total, 40, ch)
                self.assertGreaterEqual(exact / total, 0.97, f'{ch}: planted soles off row 114 in {total - exact}/{total} poses')
        finally:
            rig.set_res(1)

    def test_hd_left_facing_frames_never_put_the_sigil_colour_on_skin(self):
        """The HD mirror redraws a 6x10 sigil box; it may only touch cap cloth / sigil pixels, never skin or hands."""
        try:
            rig.set_res(2)
            checked = 0
            for ch in CHARS:
                c, s = roster.get(ch), Sheet(ch, 'assets_hd')
                sig = c.body.palette['trim']['hi']
                for name, mv in M.build_moves(c).items():
                    for i, (pose, _) in enumerate(mv['frames']):
                        if i not in (0, mv.get('hit_frame'), mv.get('proj_frame')) or pose.flash:
                            continue
                        pts = tracks(ch)[name][i] if c.body.has_tail else None
                        poses = [f[0] for f in mv['frames']]
                        prev, prev2 = BF.frame_history(poses, i, mv['loop'])
                        buf, meta = rig.render_parts(c.body, pose, pts, prev=prev, hist=(prev2, prev))
                        flipped = meta.get('pre_text', buf).transpose(Image.FLIP_LEFT_RIGHT).load()
                        left = rig.mirror_parts(buf, meta, c.body).load()
                        real = s.frame(name, i, -1).load()
                        box = rig.sigil_box_l(meta, c.body)
                        if box is None:                    # V6: no sigil, nothing is redrawn - the whole mirror must match
                            self.assertEqual(rig.mirror_parts(buf, meta, c.body).tobytes(),
                                             meta.get('pre_text', buf).transpose(Image.FLIP_LEFT_RIGHT).tobytes() if 'text_fx' not in meta
                                             else rig.mirror_parts(buf, meta, c.body).tobytes())
                            checked += 1
                            continue
                        x0, y0 = box
                        for y in range(max(0, y0 - 2), min(128, y0 + 12)):
                            for x in range(max(0, x0 - 2), min(128, x0 + 8)):
                                if flipped[x, y] in SKINLIKE:
                                    self.assertEqual(left[x, y], flipped[x, y], f'{ch}/{name}/{i}: ({x},{y}) repainted')
                                    if flipped[x, y] in SKIN:
                                        self.assertNotEqual(real[x, y][:3], sig, f'{ch}/{name}/{i}: sigil colour on skin at ({x},{y})')
                        checked += 1
            self.assertGreater(checked, 300)
        finally:
            rig.set_res(1)


class Effects(unittest.TestCase):
    """fx.json follows the work-order schema exactly and every frame is a real crop of fx.png."""

    def _check(self, s, label):
        self.assertIsNotNone(s.fx, f'{label}: no fx.json')
        self.assertEqual(s.fx.get('res'), s.res, label)
        eff = s.fx['effects']
        self.assertIsInstance(eff, dict)
        W_, H_ = s.fxs.size
        for name, e in eff.items():
            self.assertEqual(set(e), FX_KEYS, f'{label}/{name}: keys {sorted(e)}')
            self.assertTrue(e['frames'], f'{label}/{name}: no frames')
            for f in e['frames']:
                self.assertEqual(set(f), {'x', 'y', 'w', 'h', 'ms'}, f'{label}/{name}')
                self.assertTrue(f['w'] > 0 and f['h'] > 0 and f['ms'] > 0, f'{label}/{name}: {f}')
                self.assertTrue(0 <= f['x'] and 0 <= f['y'] and f['x'] + f['w'] <= W_ and f['y'] + f['h'] <= H_, f'{label}/{name}: frame outside fx.png {f}')
                self.assertIsNotNone(s.fxs.crop((f['x'], f['y'], f['x'] + f['w'], f['y'] + f['h'])).getbbox(), f'{label}/{name}: empty frame {f}')
            self.assertIn(e['anchor'], ('hand', 'ground', 'center'), f'{label}/{name}')
            self.assertIn(e['layer'], ('front', 'back'), f'{label}/{name}')
            self.assertTrue(isinstance(e['offset'], list) and len(e['offset']) == 2 and all(isinstance(v, int) for v in e['offset']), f'{label}/{name}')
            self.assertIsInstance(e['loop'], bool, f'{label}/{name}')
            self.assertTrue(e['hit_frame'] is None or 0 <= e['hit_frame'] < len(e['frames']), f'{label}/{name}: hit_frame')
            self.assertTrue(e['travel'] is None or (set(e['travel']) == {'speed'} and e['travel']['speed'] > 0), f'{label}/{name}: travel')
            self.assertTrue(e['shake'] is None or (set(e['shake']) == {'frames', 'amp'} and e['shake']['frames'] > 0 and e['shake']['amp'] > 0), f'{label}/{name}: shake')
        return eff

    def test_schema_and_frame_bounds_in_every_sheet(self):
        for root in ROOTS:
            for ch in CHARS:
                self._check(Sheet(ch, root), f'{root}/{ch}')
            shared = ROOT / root / 'fx'
            meta = json.loads((shared / 'fx.json').read_text(encoding='utf-8'))
            self.assertTrue(set(GENERIC_FX) <= set(meta['effects']), f'{root}/fx: generic set incomplete')

    def test_every_character_has_the_generic_set_banners_and_its_ultimate(self):
        for root, res in ROOTS.items():
            for ch in CHARS:
                s = Sheet(ch, root)
                eff = s.fx['effects']
                for n in GENERIC_FX + BANNER_FX:
                    self.assertIn(n, eff, f'{root}/{ch}: missing {n}')
                self.assertEqual(len(eff['letters']['frames']), 52, f'{root}/{ch}: letters = 26 glyphs x 2 sizes')
                small, big = eff['letters']['frames'][:26], eff['letters']['frames'][26:]
                self.assertGreater(min(f['h'] for f in big), max(f['h'] for f in small))
                self.assertEqual(len(eff['round_text']['frames']), 5)
                self.assertGreaterEqual(len(eff['shatter']['frames']), 6)
                self.assertEqual(eff['ko_stars']['loop'], True)
                self.assertIsNotNone(eff['explosion']['shake'])
                sig = s.meta['signature']
                ult = sig['ultimate']
                self.assertEqual(ult, ULTIMATES[ch])
                a = s.anim[ult]
                self.assertEqual(a['cat'], 'ultimate')
                for k in ('proj_frame', 'hit_frame', 'hand', 'fx', 'reach'):
                    self.assertIn(k, a, f'{root}/{ch}/{ult}: no {k}')
                self.assertTrue(len(a['hand']) == 2 and a['hand'][1] < 0, f'{root}/{ch}: hand anchor should be above the ground row')
                self.assertIn(ult, eff, f'{root}/{ch}: no effect named after the ultimate (engine get(<ultimate>) would go procedural)')
                self.assertTrue(a['fx'], f'{ch}/{ult}: no fx list')
                for spec in a['fx']:
                    self.assertIn(spec['name'], eff, f'{root}/{ch}: {ult} references effect {spec["name"]} not in fx.json')
                    if 'at' in spec:
                        self.assertTrue(0 <= spec['at'] < len(a['frames']))
                    else:
                        self.assertTrue(0 <= spec['from'] <= spec['to'] < len(a['frames']))
                windup = max(a['proj_frame'], a['hit_frame'])
                self.assertGreaterEqual(sum(f['ms'] for f in a['frames'][:windup]), 500, f'{ch}: an ultimate winds up before it lands')
                main = eff[ult]
                self.assertTrue(main['shake'] or main['travel'] or main['hit_frame'] is not None, f'{ch}: {ult} has no impact metadata')
                self.assertIn(f'{sig["special"]}_proj', eff)
                self.assertIn(f'{sig["special"]}_impact', eff)
                self.assertIn(f'{sig["super"]}_burst', eff)
                if ch == 'codex':
                    self.assertEqual(a.get('support'), 'mirror_images')
                    self.assertEqual(s.anim['mirror_images']['cat'], 'support')
                    self.assertIn('mirror_images', eff)
                    self.assertIsNotNone(eff['mirror_images']['travel'])
                    self.assertEqual(len(eff['mirror_images']['frames']), 3)
                if res == 2:
                    lo = Sheet(ch).fx['effects']
                    self.assertEqual(set(lo), set(eff), f'{ch}: HD and RES 1 effect sets differ')
                    for n in ('radiant_beam', 'crescent_fang', 'gale_rend', 'explosion'):
                        if n in eff:
                            self.assertEqual(eff[n]['frames'][1]['w'], lo[n]['frames'][1]['w'] * 2, f'{ch}/{n}: HD frames are 2x')

    def test_generic_effects_are_identical_across_characters(self):
        """The engine merges per-character sheets by name, so the generic art must not differ per character."""
        for root in ROOTS:
            ref = Sheet(CHARS[0], root)
            for ch in CHARS[1:]:
                s = Sheet(ch, root)
                for n in GENERIC_FX:
                    a, b = ref.fx['effects'][n], s.fx['effects'][n]
                    self.assertEqual({k: v for k, v in a.items() if k != 'frames'}, {k: v for k, v in b.items() if k != 'frames'}, f'{root}/{ch}/{n}')
                    for fa, fb in zip(a['frames'], b['frames']):
                        ia = ref.fxs.crop((fa['x'], fa['y'], fa['x'] + fa['w'], fa['y'] + fa['h']))
                        ib = s.fxs.crop((fb['x'], fb['y'], fb['x'] + fb['w'], fb['y'] + fb['h']))
                        self.assertEqual(ia.tobytes(), ib.tobytes(), f'{root}/{ch}/{n}: generic art differs')

    def test_every_signature_effect_has_art(self):
        """Every effect a signature move asks for exists in the character's fx.json (a missing one silently became a
        procedural stand-in beam: all 13 supers did, 2026-10-15)."""
        for root in ROOTS:
            for ch in CHARS:
                s = Sheet(ch, root)
                for kind in ('super', 'ultimate'):
                    mv = s.meta['anims'][s.meta['signature'][kind]]
                    self.assertTrue(mv.get('fx'), f'{root}/{ch} {kind} names no effect')
                    for e in mv['fx']:
                        self.assertIn(e['name'], s.fx['effects'], f'{root}/{ch} {kind} -> {e["name"]}')

    def test_impact_frames_effect_for_heavy_hits_and_ultimates(self):
        """Dark silhouette with white rays + rim, the white inverse with speed lines, outline strokes, a white silhouette.
        Never an opaque cell: on the live strip a full white cell read as a glitch box (owner, 2026-10-15)."""
        for root, res in ROOTS.items():
            for ch in CHARS:
                s = Sheet(ch, root)
                e = s.fx['effects']['impact']
                self.assertEqual(len(e['frames']), 4, f'{root}/{ch}')
                self.assertTrue(100 <= sum(f['ms'] for f in e['frames']) <= 180)
                ims = [s.fxs.crop((f['x'], f['y'], f['x'] + f['w'], f['y'] + f['h'])).convert('RGBA') for f in e['frames']]
                self.assertTrue(all(im.size == (64 * res, 64 * res) for im in ims))
                for i, im in enumerate(ims):
                    clear = sum(1 for p in im.getdata() if p[3] == 0)
                    self.assertGreater(clear, 0.4 * im.size[0] * im.size[1], f'{root}/{ch} frame {i}: mostly transparent, no box')
                opaque = [[p[:3] for p in im.getdata() if p[3]] for im in ims]
                W_ = (255, 255, 255)
                dark0 = sum(1 for c in opaque[0] if sum(c) < 150)
                self.assertGreater(dark0, opaque[0].count(W_), 'frame 0: a dark silhouette')
                self.assertGreater(opaque[1].count(W_), len(opaque[1]) // 2, 'frame 1: the white inverse')
                self.assertEqual(set(opaque[3]), {W_}, 'frame 3: a white silhouette only')
                self.assertIn('impact', s.fx['schema_notes'])

    def test_beams_and_waves_are_wide_and_energy_has_a_white_core(self):
        s = Sheet('claude', 'assets_hd')
        beam = s.fx['effects']['radiant_beam']
        self.assertGreaterEqual(beam['frames'][2]['w'], 256)
        f = beam['frames'][3]
        im = s.fxs.crop((f['x'], f['y'], f['x'] + f['w'], f['y'] + f['h']))
        self.assertIn((255, 255, 255), {p[:3] for _, p in im.getcolors(1 << 16) if p[3]})
        self.assertEqual(beam['anchor'], 'hand')
        self.assertIsNotNone(beam['shake'])
        for ch, n in (('gemini', 'crescent_fang'), ('ollama', 'gale_rend'), ('generic', 'star_core')):
            e = Sheet(ch, 'assets_hd').fx['effects'][n]
            self.assertIsNotNone(e['travel'], f'{n} travels')
            self.assertGreaterEqual(e['frames'][0]['w'], 80, f'{n} is big')


class WeaponMovesV7(unittest.TestCase):
    """V7: every fighter fights like its weapon (docs/ANIMATION-NOTES.md section 8)."""
    ATTACK = ('string', 'riposte', 'air', 'spike', 'throw', 'through', 'guard_break', 'pull', 'gust', 'boomerang')
    REACT = ('launched', 'air_hit', 'spiked', 'thrown', 'pulled', 'guard_crush', 'hit_high', 'hit_low', 'hit_back', 'clash')

    def test_every_character_has_eight_plus_weapon_moves_a_taunt_variant_and_every_reaction(self):
        for ch in CHARS:
            s = Sheet(ch)
            mine = [n for n, a in s.anim.items() if a.get('type') in self.ATTACK]
            self.assertGreaterEqual(len(mine), 8, (ch, mine))
            fam = {s.anim[n]['family'] for n in mine}
            self.assertEqual(len(fam), 1, (ch, fam))                          # one weapon family per character
            self.assertEqual(s.anim['taunt2']['type'], 'taunt')
            for r in self.REACT:
                self.assertEqual(s.anim[r]['type'], r, ch)
            for n in mine:
                a = s.anim[n]
                self.assertIn('input', a, (ch, n))
                if 'hit_frame' in a:
                    self.assertIn(a['hit'], ('slash', 'blunt', 'pierce'), (ch, n))
                    self.assertIn(a['height'], ('high', 'mid', 'low', 'back'), (ch, n))

    def test_every_new_strike_winds_up_longer_than_it_strikes_and_holds_the_hit(self):
        """Section 6/7 keying on the real sheets: wind-up (frames before the first smear) >= 2 x the smear, the smear is
        <= 50 ms, the contact frame is held >= 140 ms, and the move ends in a recovery (frames after the hit)."""
        for ch in CHARS:
            s = Sheet(ch)
            for n, a in s.anim.items():
                if a.get('type') not in self.ATTACK or a['cat'] != 'strike':
                    continue
                ms = [f['ms'] for f in a['frames']]
                sm = a['smear_frames'][0]
                self.assertGreaterEqual(sum(ms[:sm]), 2 * ms[sm], (ch, n, ms))
                self.assertLessEqual(ms[sm], 50, (ch, n, ms))
                self.assertGreaterEqual(ms[a['hit_frame']], 140, (ch, n, ms))
                self.assertGreater(len(ms) - 1, a['hit_frame'], (ch, n))
                if a['family'] == 'heavy' and a['type'] == 'string':          # heavy weapons: a longer wind-up, armour
                    self.assertGreaterEqual(sum(ms[:sm]), 450, (ch, n, ms))

    def test_throw_and_thrown_share_one_clock(self):
        for ch in CHARS:
            a, t = Sheet(ch).anim['throw'], Sheet(ch).anim['thrown']
            ms_a = [f['ms'] for f in a['frames']]
            ms_t = [f['ms'] for f in t['frames']]
            self.assertEqual(sum(ms_a[a['grab_frame']:a['hit_frame']]), sum(ms_t[t['grab_frame']:t['hit_frame']]), ch)
            self.assertLess(a['grab_frame'], a['release_frame'], ch)
            self.assertLessEqual(a['release_frame'], a['hit_frame'], ch)

    def test_strings_cancel_and_special_frames_are_ordered(self):
        for ch in CHARS:
            s = Sheet(ch)
            combo = s.meta['combo']
            self.assertEqual(len(combo), 3, ch)
            for n in combo:
                self.assertEqual(s.anim[n]['cancel_frame'], s.anim[n]['hit_frame'] + 1, (ch, n))
            for n, a in s.anim.items():
                if a.get('type') == 'boomerang':
                    self.assertLess(a['proj_frame'], a['catch_frame'], (ch, n))
                if a.get('type') == 'pull':
                    self.assertGreater(a['pull_frame'], a['hit_frame'], (ch, n))
                if a.get('type') == 'clash':
                    self.assertEqual(a['lock_frame'], 0)

    def test_a_thrown_weapon_leaves_the_hand_and_comes_back(self):
        """The boomerang's empty-hand frames really draw no chakram; the catch frame draws it again."""
        for ch in CHARS:
            mv = M.build_moves(ch)
            for n, m in mv.items():
                if m.get('type') != 'boomerang':
                    continue
                for i, (pose, _) in enumerate(m['frames']):
                    buf, _, _ = parts(ch, n, i)
                    has = buf.tobytes().count(bytes([rig.PID['wpn_f']])) > 0
                    self.assertEqual(has, not pose.nowf, (ch, n, i))
                self.assertFalse(m['frames'][m['catch_frame']][0].nowf)

    def test_in_cell_missiles_reach_the_front_of_the_opponent(self):
        """An arrow / kunai / chain / gust that lands is measured from its own pixels and reaches past the defender's
        front edge at a normal bout distance (hips ~32 px apart, the front of the body ~9 px before the hip)."""
        for ch in CHARS:
            s = Sheet(ch)
            mv = M.build_moves(ch)
            for n, a in s.anim.items():
                if 'hit_frame' not in a:
                    continue
                pose = mv[n]['frames'][a['hit_frame']][0]
                if not any(f[0] in BF.MISSILE_FX for f in pose.fx):
                    continue
                self.assertGreaterEqual(a['reach'], 23, (ch, n, a['reach']))

    def test_the_bow_string_bends_back_to_the_drawing_hand(self):
        rig.set_res(1)
        c = roster.get('generic')
        pose = M.build_moves(c)['point_blank']['frames'][1][0]
        self.assertTrue(pose.nock)
        buf, meta = rig.render_parts(c.body, pose, None)
        px = buf.load()
        hb = meta['hb']
        near = [(x, y) for y in range(64) for x in range(64)
                if px[x, y] == rig.PID['string'] and abs(x - hb[0]) <= 2 and abs(y - hb[1]) <= 2]
        self.assertTrue(near, 'the string meets the rear hand')


class HD128(unittest.TestCase):
    """V7 part B: the 128 px build is the master - real faces, knuckles, folds - and the 64 px build is untouched by it."""

    def test_hd_faces_have_an_eye_white_a_brow_and_a_mouth_that_changes_with_the_mood(self):
        rig.set_res(2)
        try:
            c = roster.get('claude')
            mv = M.build_moves(c)
            got = {}
            for name, i in (('idle', 0), ('iai_slash', 3), ('hit_high', 1), ('thumbs_up', 1)):
                buf, meta = rig.render_parts(c.body, mv[name]['frames'][i][0], None)
                b = buf.tobytes()
                counts = {k: b.count(bytes([rig.PID[k]])) for k in ('eye', 'eyew', 'brow', 'mouth')}
                got[name] = counts
                self.assertGreater(counts['eye'] + counts['brow'], 0, (name, counts))
                self.assertGreater(counts['mouth'], 0, (name, counts))
            self.assertGreater(got['iai_slash']['mouth'], got['idle']['mouth'])     # the shout opens the mouth
            self.assertGreater(got['idle']['eyew'], 0)                             # a real eye white
        finally:
            rig.set_res(1)

    def test_hd_fists_show_knuckles_on_the_grip_and_bent_joints_fold(self):
        c = roster.get('knight')
        pose = M.build_moves(c)['cleave']['frames'][2][0]
        rig.set_res(2)
        try:
            buf, _ = rig.render_parts(c.body, pose, None)
            self.assertGreater(buf.tobytes().count(bytes([rig.PID['crease']])), 2)
        finally:
            rig.set_res(1)
        buf1, _ = rig.render_parts(c.body, pose, None)
        self.assertEqual(buf1.tobytes().count(bytes([rig.PID['crease']])), 0)      # nothing of it at 64 px



class ForgeV8(unittest.TestCase):
    """V8 forge: sheet_unarmed*.png (the same frames without the held weapon) and per-frame `grip` / `grip2`, so the
    arena can draw a forged weapon in the fighter's hand."""
    WEAPON_IDS = {rig.PID[n] for n in ('wpn_f', 'wpn_b', 'hilt_f', 'hilt_b', 'blade_hl', 'string')}

    @staticmethod
    def sample(a):
        """Frames worth checking in a row: the first, the contact (and the smear before it) and the last."""
        n = len(a['frames'])
        out = {0, n - 1}
        for k in ('hit_frame', 'proj_frame', 'grab_frame'):
            if k in a:
                out.add(a[k])
        out |= set(a.get('smear_frames') or [])
        return sorted(i for i in out if 0 <= i < n)

    _moves = {}                                              # build_moves per character (pose data; the same at any RES)

    @staticmethod
    def render(ch, name, i, res=1, unarmed=False, facing=1):
        c = roster.get(ch)
        if ch not in ForgeV8._moves:
            ForgeV8._moves[ch] = M.build_moves(c)
        mv = ForgeV8._moves[ch][name]
        poses = [f[0] for f in mv['frames']]
        prev, prev2 = BF.frame_history(poses, i, mv['loop'])
        rig.set_res(res)
        rig.UNARMED = unarmed
        try:
            buf, meta = rig.render_parts(c.body, poses[i], None, prev=prev, hist=(prev2, prev))
            if facing < 0:
                buf = rig.mirror_parts(buf, meta, c.body)
        finally:
            rig.UNARMED = False
            rig.set_res(1)
        return buf, poses[i]

    def test_unarmed_sheets_and_grip_lists_exist_for_every_row_at_both_resolutions(self):
        for root in ('assets', 'assets_hd'):
            for ch in CHARS:
                s = Sheet(ch, root)
                self.assertEqual(s.meta['sheets_unarmed'], {'R': 'sheet_unarmed.png', 'L': 'sheet_unarmed_l.png'})
                for side, fn in s.meta['sheets_unarmed'].items():
                    im = Image.open(ROOT / root / ch / fn)
                    self.assertEqual(im.size, s.sheets[side].size, (root, ch, fn))
                    self.assertLessEqual(len(im.convert('RGBA').getcolors(1 << 16) or []), CAP if root == 'assets' else 64)
                for n, a in s.anim.items():
                    self.assertEqual(len(a['grip']), len(a['frames']), (root, ch, n))
                    self.assertEqual(len(a['grip2']), len(a['frames']), (root, ch, n))
                    for g in a['grip'] + a['grip2']:
                        self.assertTrue(g is None or (len(g) == 4 and g[3] in ('f', 'b')), (root, ch, n, g))
                self.assertIn('grip', s.meta['schema_notes'])

    def test_unarmed_frames_draw_no_weapon(self):
        """No weapon part is rendered in unarmed mode, and on the real unarmed sheets every pixel where the armed frame
        has its weapon (away from the body) is empty, in both facings."""
        for ch in CHARS:
            s, u = Sheet(ch), {k: Image.open(ROOT / 'assets' / ch / v).convert('RGBA') for k, v in Sheet(ch).meta['sheets_unarmed'].items()}
            held = 0
            for n, a in s.anim.items():
                for i in self.sample(a):
                    for facing in (1, -1):
                        arm, _ = self.render(ch, n, i, facing=facing)
                        un, pose = self.render(ch, n, i, unarmed=True, facing=facing)
                        ap, up = arm.load(), un.load()
                        self.assertFalse(set(un.tobytes()) & self.WEAPON_IDS, (ch, n, i, facing))
                        if rig.is_smear(pose) or pose.ghost:
                            continue                             # a ghosted previous arm / an afterimage may lie there
                        side = 'R' if facing > 0 else 'L'
                        r = a['row']
                        px = u[side].crop((i * 64, r * 64, (i + 1) * 64, (r + 1) * 64)).load()
                        for y in range(64):
                            for x in range(64):
                                if ap[x, y] not in self.WEAPON_IDS:
                                    continue
                                if any(up[xx, yy] for xx in range(max(0, x - 2), min(64, x + 3))
                                       for yy in range(max(0, y - 2), min(64, y + 3))):
                                    continue                     # next to the body: the outline may sit here
                                held += 1
                                self.assertEqual(px[x, y][3], 0, (ch, n, i, side, x, y))
            self.assertGreater(held, 50, ch)

    def test_grips_sit_on_the_hand_and_follow_the_rendered_weapon(self):
        """The grip point is on (within 1 px of) the gripping hand's pixels, and the grip angle matches the axis of the
        weapon pixels actually drawn (5 degrees at RES 2, 7 at RES 1 where a 12-18 px blade is quantised; long weapons
        only, smear frames skipped), in both facings."""
        import re

        def where(buf, ids):                                 # (xs, ys) of the pixels whose part id is in ids (no numpy:
            w = buf.width                                    # a byte-class regex over the 'L' part buffer runs in C)
            pat = re.compile(b'[' + b''.join(re.escape(bytes([int(i)])) for i in ids) + b']')
            ks = [m.start() for m in pat.finditer(buf.tobytes())]
            return [k % w for k in ks], [k // w for k in ks]

        for res, root in ((1, 'assets'), (2, 'assets_hd')):
            for ch in CHARS:
                s = Sheet(ch, root)
                body = roster.get(ch).body
                cw = s.cell
                angled = 0
                for n, a in s.anim.items():
                    for i in self.sample(a)[:2 if res == 2 else None]:
                        for facing in (1, -1):
                            buf, pose = self.render(ch, n, i, res=res, facing=facing)
                            ax = s.meta['anchor']['R' if facing > 0 else 'L'] + 0.5
                            for key, hand_part, wpn in (('grip', 'hand_f', ('wpn_f', 'hilt_f')),
                                                        ('grip2', 'hand_b', ('wpn_b', 'hilt_b'))):
                                g = a[key][i]
                                if g is None:
                                    continue
                                gx = ax + (g[0] if facing > 0 else -g[0])
                                gy = s.meta['ground_y'] + g[1]
                                hid = rig.PID['hand_f' if g[3] == 'f' else 'hand_b']
                                xs, ys = where(buf, {hid})
                                r_ = int(math.ceil(1.5 * res))
                                win = {buf.getpixel((xx, yy)) for yy in range(max(0, int(gy) - r_), min(buf.height, int(gy) + r_ + 1))
                                       for xx in range(max(0, int(gx) - r_), min(buf.width, int(gx) + r_ + 1))}
                                covered = any(v and rig.Z[int(v)] > rig.Z[hid] for v in win)
                                if len(xs) and not covered:          # a hand behind the arm / weapon / body is not checked
                                    d = min(math.hypot(x + 0.5 - gx, y + 0.5 - gy) for x, y in zip(xs, ys))
                                    # on the hand: within one RES 1 px of a hand pixel's edge
                                    self.assertLessEqual(d, 0.5 * res + 1.0 * res, (root, ch, n, i, facing, key, g, d))
                                spec = body.weapon if key == 'grip' else (body.weapon_b or body.weapon)
                                # bows / rings / fans have no long axis; an axe head skews the pixel axis off the haft
                                if (rig.is_smear(pose) or spec.kind in ('bow', 'chakram', 'fan', 'axe') or spec.length < 12
                                        or key == 'grip2'):
                                    continue
                                ids = [rig.PID[w] for w in wpn]
                                xs, ys = where(buf, set(ids))
                                if len(xs) < 12 * res:
                                    continue
                                n_ = float(len(xs))                  # principal axis of the weapon pixels (2x2 covariance)
                                cx_, cy_ = sum(xs) / n_ + 0.5, sum(ys) / n_ + 0.5
                                sxx = sum((x + 0.5 - cx_) ** 2 for x in xs) / (n_ - 1)
                                syy = sum((y + 0.5 - cy_) ** 2 for y in ys) / (n_ - 1)
                                sxy = sum((x + 0.5 - cx_) * (y + 0.5 - cy_) for x, y in zip(xs, ys)) / (n_ - 1)
                                tr, det = sxx + syy, sxx * syy - sxy * sxy
                                disc = math.sqrt(max(0.0, tr * tr / 4 - det))
                                ev_hi, ev_lo = tr / 2 + disc, tr / 2 - disc
                                if ev_hi < 4 * ev_lo:
                                    continue                         # foreshortened to a blob: no axis to measure
                                th = 0.5 * math.atan2(2 * sxy, sxx - syy)
                                axis = (math.cos(th), math.sin(th))
                                if axis[0] * (cx_ - gx) + axis[1] * (cy_ - gy) < 0:
                                    axis = (-axis[0], -axis[1])
                                want = g[2] if facing > 0 else 180.0 - g[2]
                                got = math.degrees(math.atan2(axis[1], axis[0]))
                                err = abs((got - want + 180) % 360 - 180)
                                if spec.slide:                       # a pole held near its middle: the axis, either way
                                    err = min(err, 180.0 - err)
                                # 12-30 px of blade quantised to the pixel grid: 5 deg at 128 px, 7 at 64 px
                                self.assertLessEqual(err, 5.0 if res == 2 else 7.0, (root, ch, n, i, facing, want, got))
                                angled += 1
                if body.weapon.kind not in ('bow', 'chakram', 'fan', 'axe') and body.weapon.length >= 12:
                    self.assertGreater(angled, 20, (root, ch))


    def test_the_atlas_serves_unarmed_frames_and_mirrored_grips(self):
        from minis_core.atlas import Atlas
        a = Atlas('knight')
        s = Sheet('knight')
        r = s.anim['cross']['row']
        for facing, side in ((1, 'R'), (-1, 'L')):
            want = Image.open(ROOT / 'assets' / 'knight' / s.meta['sheets_unarmed'][side]).convert('RGBA').crop((128, r * 64, 192, (r + 1) * 64))
            self.assertEqual(a.unarmed_frame('cross', 2, facing).tobytes(), want.tobytes())
            self.assertNotEqual(a.unarmed_frame('cross', 2, facing).tobytes(), a.frame_image('cross', 2, facing).tobytes())
        g = s.anim['cross']['grip'][3]
        self.assertEqual(a.grip('cross', 3, 1), (g[0], g[1], g[2], 'f'))
        x, y, ang, hand = a.grip('cross', 3, -1)
        self.assertEqual((x, y), (-g[0], g[1]))
        self.assertAlmostEqual((ang - (180 - g[2]) + 180) % 360 - 180, 0.0)
        self.assertIsNotNone(a.grip2('cross', 3, 1))                    # the greatsword is two-handed
        up = Atlas('knight', ROOT / 'assets' / 'knight', hd=True)       # RES 1 standing in for HD: grips scale with it
        self.assertEqual(up.grip('cross', 3, 1)[:2], (g[0] * 2, g[1] * 2))
        self.assertEqual(up.unarmed_frame('cross', 2, 1).size, (128, 128))
        nm = Atlas('nomad')
        boom = next(n for n, v in nm.anim.items() if v.get('type') == 'boomerang')
        self.assertTrue(any(nm.grip(boom, i, 1) is None for i in range(len(nm.anim[boom]['frames']))))   # thrown: not held


def frame_hashes():
    """{'<root>/<char>': {proj, palette, moves: {name: {R, L, frames, meta}}}} for every built sheet."""
    import hashlib
    out = {}
    for root in ('assets', 'assets_hd'):
        for ch in CHARS:
            s = Sheet(ch, root)
            c = s.cell
            moves = {}
            for name, a in s.anim.items():
                r, n = a['row'], len(a['frames'])
                m = {}
                for key in ('R', 'L'):
                    row = s.sheets[key].crop((0, r * c, n * c, (r + 1) * c))
                    m[key] = hashlib.sha1(row.tobytes()).hexdigest()
                m['frames'] = [[f['ms'], f['dx']] for f in a['frames']]
                m['meta'] = {k: v for k, v in a.items() if k not in ('row', 'frames', 'hand')}
                moves[name] = m
            out[f'{root}/{ch}'] = dict(proj=hashlib.sha1(s.proj.tobytes()).hexdigest(), palette=s.meta['palette'], moves=moves)
    return out


if __name__ == '__main__':
    if '--regen-hashes' in sys.argv:
        (ROOT / 'tests' / 'fixtures' / 'v5_frame_hashes.json').write_text(json.dumps(frame_hashes(), indent=0), encoding='utf-8')
        print('wrote tests/fixtures/v5_frame_hashes.json (V6 art, signed off by eye)')
    else:
        unittest.main()
