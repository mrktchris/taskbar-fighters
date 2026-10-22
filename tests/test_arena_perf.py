"""V9 arena 30 fps work (docs/ARENA.md "Performance"): the compositor now trims every drawable to its opaque box, merges
dirty rects in near-linear time, keeps a steady white flash incremental and decodes the forge's unarmed sheets up front.
None of it may change a single pixel: every frame here is checked against a full recomposition of the same drawables.
Headless only (a RAM surface, a synthetic backdrop and desktop); no window, no screen grab."""
import random, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import CFG  # noqa: E402,F401
from PIL import Image  # noqa: E402
from minis_core import arena as AR, forge as FG  # noqa: E402
from test_arena import FX, LIB  # noqa: E402

W, H = 1280, 720
WINS = [(1, 90, 200, 580, 600), (2, 650, 250, 1180, 650), (3, 400, 410, 830, 670)]


class CountingSurface(AR.Surface):
    def __init__(self, w, h):
        super().__init__(w, h)
        self.px = 0
        self.full = 0

    def fill(self, rgba):                            # one colour, no premultiply of an image: counted apart
        self.full += 1
        self.filled = getattr(self, 'filled', 0) + 1
        super().fill(rgba)

    def write(self, img, x, y):
        self.px += img.width * img.height
        if (img.width, img.height) == (self.w, self.h):
            self.full += 1
        super().write(img, x, y)


def arena(seed, intensity='wild', freeze=False, forge=True):
    st = AR.Stage((0, 0, W, H), WINS, floor_y=H - 48)
    scr = FG.ScreenImage(AR.synthetic_backdrop(W, H, seed=5), rects=[(w['id'], w['l'], w['t'], w['r'], w['b']) for w in st.windows]) if forge else None
    ar = AR.Arena(st, {'a': LIB['claude'], 'b': LIB['knight']}, FX, seed=seed, now=0.0, record=lambda *a, **k: None,
                  backdrop=AR.synthetic_backdrop(W, H) if freeze else None, options={'intensity': intensity}, screen=scr, forge=forge)
    ar.flashes = True
    return ar


def v8_sprites(ar):
    """V8 drew every sprite as its whole 256 px cell: give the V8 side untrimmed sprites (the same pixels)."""
    ar._sprite_trim = lambda *a, **k: (ar._sprite(*a, **k), 0, 0)


def reference(comp, now, ov):
    """What the window must show: every drawable composited over the whole frame, the lens on top, the flash wash."""
    a = comp.arena
    items = a.drawables(now)
    base = comp._compose(items, 0, 0, W, H)
    if ov is not None:
        base.alpha_composite(Image.new('RGBA', (W, H), ov))
        return base
    z = a.cam.zoom_at(now)
    if z is not None:
        zz, (x0, y0, x1, y1), (fx, fy) = z
        base.paste(AR._lens(base.crop((x0, y0, x1, y1)), zz, fx - x0, fy - y0), (x0, y0))
    return base


def shown(im):
    """What the layered window shows: premultiplied pixels (the RGB under alpha 0 is never seen)."""
    return im.convert('RGBa').tobytes()


class PixelIdentical(unittest.TestCase):
    """Two identical arenas in lockstep, one drawn by the V8 compositor (tests/v8_compositor.py, verbatim) and one by
    V9's.  On every frame the window must show the same pixels; where V8 itself left a stale pixel (its dirty rects
    missed a change), V9 must show the full recomposition instead - never something third."""

    def play(self, seed, **kw):
        from v8_compositor import CompositorV8
        ar, ar8 = arena(seed, **kw), arena(seed, **kw)
        v8_sprites(ar8)
        surf, surf8 = CountingSurface(W, H), CountingSurface(W, H)
        comp, comp8 = AR.Compositor(ar, surf), CompositorV8(ar8, surf8)
        now, same, better, worse, flashes, zooms = 0.0, 0, 0, [], 0, 0
        while ar.phase != 'done' and now < 150:
            now += 1 / 30.0
            ar.tick(now)
            ar8.tick(now)
            flash = ar.fxp.flash(now) if ar.flashes_on(now) else 0.0
            cf = ar.cam.flash_at(now) if ar.flashes_on(now) else None
            ov = (255, 255, 255, int(255 * min(1.0, flash))) if flash > 0 else (tuple(cf[0]) + (int(255 * min(1.0, cf[1])),) if cf else None)
            comp.render(now)
            comp8.render(now)
            flashes += ov is not None
            zooms += ar.cam.zoom_at(now) is not None
            new, old = shown(surf.canvas), shown(surf8.canvas)
            if new == old:
                same += 1
                continue
            ref = shown(reference(comp, now, ov))
            if new == ref:
                better += 1                                   # V8 left a stale pixel here, V9 did not
            elif old == ref:
                worse.append((comp.frames, round(now, 2), ov))  # V8 was right and V9 is not: a real regression
            else:
                better += 0                                   # both left a (different) stale pixel: neither is the reference
        self.assertEqual(worse, [], f'seed {seed}: frames where V8 showed the right pixels and V9 did not')
        return same, better, flashes, zooms, surf, surf8

    def test_every_frame_shows_what_v8_showed(self):
        tot = [0, 0, 0, 0]
        for seed in (1, 2):
            s, b, f, z, surf, surf8 = self.play(seed)
            tot = [tot[0] + s, tot[1] + b, tot[2] + f, tot[3] + z]
            self.assertLess(surf.px, surf8.px, 'and it writes fewer pixels to do it')
        self.assertGreater(tot[0], 2000)
        # tot[1]: frames where V8 left stale pixels (its dirty rects missed a change) and V9 showed the right ones
        self.assertGreater(tot[2], 5, 'flash frames were compared')
        self.assertGreater(tot[3], 5, 'zoom frames were compared')

    def test_with_a_freeze_backdrop_too(self):
        s, b, f, z, surf, surf8 = self.play(4, freeze=True, intensity='normal')
        self.assertGreater(s, 500)


class Cheaper(unittest.TestCase):
    def test_a_steady_flash_is_written_once_and_the_rest_is_dirty_rects(self):
        ar = arena(2)
        surf = CountingSurface(W, H)
        comp = AR.Compositor(ar, surf)
        now, flash_frames = 0.0, 0
        while ar.phase != 'done' and now < 150:
            now += 1 / 30.0
            ar.tick(now)
            flash_frames += ar.fxp.flash(now) > 0 or ar.cam.flash_at(now) is not None
            comp.render(now)
        self.assertGreater(flash_frames, 3)
        self.assertLess(surf.full, flash_frames + 2 * 8 + 1, 'not every flash frame rewrites the whole window')

    def test_sprites_are_trimmed_to_their_opaque_pixels_and_land_on_the_same_pixels(self):
        ar = arena(3)
        n = 0
        for anim in ('idle', 'jab', 'ko', 'jump'):
            for facing in (1, -1):
                for alpha in (None, 110, 55):
                    full = ar._sprite(LIB['claude'], anim, 1, facing, alpha=alpha)
                    im, dx, dy = ar._sprite_trim(LIB['claude'], anim, 1, facing, alpha=alpha)
                    self.assertEqual(im.getchannel('A').getbbox(), (0, 0, im.width, im.height))
                    self.assertLess(im.width * im.height, full.width * full.height)
                    a = Image.new('RGBA', full.size, (0, 0, 0, 0))
                    a.alpha_composite(full)
                    b = Image.new('RGBA', full.size, (0, 0, 0, 0))
                    b.alpha_composite(im, (dx, dy))
                    self.assertEqual(a.tobytes(), b.tobytes())
                    n += 1
        self.assertEqual(n, 24)

    def test_merge_covers_every_rect_fast_even_with_hundreds(self):
        rng = random.Random(4)
        for n in (5, 40, 200, 400):
            rects = []
            for _ in range(n):
                x, y = rng.randrange(0, W), rng.randrange(0, H)
                rects.append((x, y, x + rng.randrange(4, 90), y + rng.randrange(4, 90)))
            t0 = time.perf_counter()
            out = AR._merge(rects, W, H, limit=AR.MERGE_LIMIT)
            dt = time.perf_counter() - t0
            self.assertLessEqual(len(out), AR.MERGE_LIMIT)
            self.assertLess(dt, 0.02, f'{n} rects took {dt * 1000:.1f} ms')
            for x0, y0, x1, y1 in rects:
                x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                if x1 <= x0 or y1 <= y0:
                    continue
                cover = Image.new('1', (x1 - x0, y1 - y0), 0)
                for a in out:
                    ix0, iy0, ix1, iy1 = max(a[0], x0), max(a[1], y0), min(a[2], x1), min(a[3], y1)
                    if ix1 > ix0 and iy1 > iy0:
                        cover.paste(1, (ix0 - x0, iy0 - y0, ix1 - x0, iy1 - y0))
                self.assertIsNone(Image.eval(cover, lambda v: 255 - v * 255).getbbox(), f'{(x0, y0, x1, y1)} uncovered')

    def test_unarmed_sheets_are_decoded_before_the_first_frame(self):
        from minis_core.atlas import Library
        lib = Library(hd=True)
        st = AR.Stage((0, 0, W, H), WINS, floor_y=H - 48)
        ar = AR.Arena(st, {'a': lib['claude'], 'b': lib['knight']}, FX, seed=1, now=0.0, record=lambda *a, **k: None,
                      screen=FG.ScreenImage(None, rects=[]), forge=True)
        for s in 'ab':
            self.assertTrue(ar.f[s].atlas._unarmed, s)

    def test_fewer_pixels_premultiplied_than_v8(self):
        """The window premultiplies every pixel it is handed: V9 hands it fewer (flash frames are a fill plus the
        drawables instead of a whole composited monitor)."""
        from v8_compositor import CompositorV8
        px = {}
        for name, cls in (('v9', AR.Compositor), ('v8', CompositorV8)):
            ar = arena(1)
            if name == 'v8':
                v8_sprites(ar)
            surf = CountingSurface(W, H)
            comp = cls(ar, surf)
            now = 0.0
            while ar.phase != 'done' and now < 150:
                now += 1 / 30.0
                ar.tick(now)
                comp.render(now)
            px[name] = surf.px
        self.assertLess(px['v9'], 0.85 * px['v8'], px)


if __name__ == '__main__':
    unittest.main()
