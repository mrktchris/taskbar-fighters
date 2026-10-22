"""Runs ONE real arena process headless for tests/test_integration_processes.py (not a test itself), or benchmarks the arena.

    LOCALAPPDATA=<temp> python tests/arena_harness.py
    python tests/arena_harness.py bench [--intensity normal] [--seeds 6] [--forge on|off] [--tile 128|256] [--size 2560x1440]
                                        [--backend win|winblit|mac|none] [--json out.json]

Everything is real (minis.run_arena, Arena, Compositor, control / arena.json heartbeats, the monotonic clock) except:
- the monitor is a synthetic rect from <data>/harness.json {"arena": {"rect": [l, t, r, b], "windows": [[id, l, t, r, b], ...],
  "seconds": S, "freeze": bool}}; the window list is that fixed list (no EnumWindows)
- the surface is minis_core.arena.Surface (RAM) instead of the layered window; a synthetic backdrop stands in for a screen grab
- V7: an optional "options" dict ({"rounds", "intensity", "seconds", "endless", "intro", "outro"}) reaches the arena the way
  minis.json does (cfg["arena"]), so the real option path is exercised
- V8: "forge_screen": true hands run_arena a SYNTHETIC desktop as the desktop-weapons grab (a headless run never grabs the
  real screen); without it the arena forges from window shapes

`bench` (V8, FOUND-2) plays seeded headless matches at 1920x1080 / 30 fps and reports ms per frame for tick + render plus
what each backend adds: the Windows premultiply of every dirty rect, and the macOS tile upload (RGBa conversion + bytes of
every touched tile, empty tiles skipped as minis_mac/arena_window.py does), with V7's 256-pt tiles or V8's 128.  It never
opens a window and never grabs the screen.
V9 `winblit`: everything minis_win/arena_window.ArenaWindow.write does except the window itself - the premultiplied BGRA
conversion AND the row-by-row memmove into a monitor-sized ctypes buffer (the DIB), plus the dirty-rect merge of flush;
only UpdateLayeredWindowIndirect (the compositor's own upload) is left out.  `--json` writes the per-frame times too.
"""
import argparse, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import minis  # noqa: E402
from minis_core import arena as AR, config as cfgmod  # noqa: E402


class HeadlessShell:
    def __init__(self, real):
        self.real = real

    def make_mutex(self, name):
        return self.real.make_mutex(name)

    def monitors(self):
        return []

    def window_rects(self, exclude=()):
        return []


def main():
    from minis_win import shell as real_shell
    h = json.loads((cfgmod.data_dir() / 'harness.json').read_text(encoding='utf-8'))
    a = h['arena']
    rect = tuple(a['rect'])
    cfg = cfgmod.load()
    cfg.update(h.get('cfg', {}))
    if isinstance(a.get('options'), dict):
        cfg['arena'] = dict(a['options'])
    surface = AR.Surface(rect[2] - rect[0], rect[3] - rect[1])
    bd = AR.synthetic_backdrop(surface.w, surface.h) if a.get('freeze') else None
    scr = AR.synthetic_backdrop(surface.w, surface.h, seed=5) if a.get('forge_screen') else None
    windows = [tuple(w) for w in a.get('windows', [])]
    return minis.run_arena(dict(monitor=a.get('monitor', 9), freeze=bool(a.get('freeze')), seconds=a.get('seconds')), HeadlessShell(real_shell), cfg,
                           monitor_rect=rect, windows_fn=lambda: windows, backdrop=bd, surface=surface, seed=a.get('seed', 1), screen=scr)


# ---------------------------------------------------------------- bench (FOUND-2)
BENCH_WINS = [(1, 140, 300, 860, 900), (2, 980, 380, 1760, 980), (3, 600, 620, 1240, 1000)]


def premultiply(img):
    from PIL import Image, ImageChops
    r, g, b, a = img.split()
    return Image.merge('RGBA', (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a)).tobytes()


class BenchSurface(AR.Surface):
    """A RAM surface that also pays what a real backend pays per write: 'win' = the premultiplied BGRA copy of each rect,
    'mac' = the RGBa conversion of every touched tile (skipping tiles that are fully transparent), 'none' = nothing."""

    def __init__(self, w, h, mode, tile=128, tint=False):
        super().__init__(w, h)
        self.mode, self.tile = mode, tile
        self.dirty = []
        self.backend_s = 0.0
        self.tiles_up = self.tiles_skip = 0
        self.px_written = 0
        self.empty = set()
        if tint:
            self.tint = lambda rgb, a: None
        if mode == 'winblit':
            import ctypes
            self._buf = ctypes.create_string_buffer(w * h * 4)
            self._base = ctypes.addressof(self._buf)

    def write(self, img, x, y):
        if self.mode != 'winblit':                       # winblit: the DIB is the only copy, as in the real window
            super().write(img, x, y)
        else:
            self.writes += 1
        t0 = time.perf_counter()
        self.px_written += img.width * img.height
        if self.mode == 'win':
            premultiply(img)
        elif self.mode == 'winblit':
            self._blit(img, int(x), int(y))
        elif self.mode == 'mac':
            self.dirty.append((int(x), int(y), int(x) + img.width, int(y) + img.height))
        self.backend_s += time.perf_counter() - t0

    def fill(self, rgba):
        """minis_win/arena_window.ArenaWindow.fill (V9), minus the window."""
        from PIL import Image
        t0 = time.perf_counter()
        self.px_written += self.w * self.h
        if self.mode == 'winblit':
            import ctypes
            px = premultiply(Image.new('RGBA', (1, 1), tuple(rgba)))
            ctypes.memmove(self._base, px * (self.w * self.h), self.w * self.h * 4)
            self.dirty.append((0, 0, self.w, self.h))
        else:
            super().fill(rgba)
        self.backend_s += time.perf_counter() - t0

    def _blit(self, img, x, y):
        """minis_win/arena_window.ArenaWindow.write, minus the window: clip, premultiply to BGRA, memmove each row."""
        import ctypes
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + img.width), min(self.h, y + img.height)
        if x1 <= x0 or y1 <= y0:
            return
        if (x0, y0, x1, y1) != (x, y, x + img.width, y + img.height):
            img = img.crop((x0 - x, y0 - y, x1 - x, y1 - y))
        data = premultiply(img)
        row = img.width * 4
        base = self._base + (y0 * self.w + x0) * 4
        stride = self.w * 4
        if img.width == self.w and x0 == 0:
            ctypes.memmove(base, data, len(data))
        else:
            for j in range(img.height):
                ctypes.memmove(base + j * stride, data[j * row:(j + 1) * row], row)
        self.dirty.append((x0, y0, x1, y1))

    def flush(self, full=False):
        if self.mode == 'winblit':
            from minis_platform.rects import merge_rects
            t0 = time.perf_counter()
            merge_rects(self.dirty)
            self.dirty = []
            self.backend_s += time.perf_counter() - t0
        if self.mode == 'mac':
            from minis_platform.rects import tile_keys
            t0 = time.perf_counter()
            for k in tile_keys(self.dirty, self.w, self.h, self.tile):
                crop = self.canvas.crop((k[0], k[1], min(self.w, k[0] + self.tile), min(self.h, k[1] + self.tile)))
                if self.tile < 256 and crop.getchannel('A').getbbox() is None:    # V8: an empty tile is not uploaded
                    if k in self.empty:
                        self.tiles_skip += 1
                        continue
                    self.empty.add(k)
                    self.tiles_skip += 1
                    continue
                self.empty.discard(k)
                crop.convert('RGBa').tobytes()
                self.tiles_up += 1
            self.dirty = []
            self.backend_s += time.perf_counter() - t0
        return super().flush(full)


def bench(argv):
    from minis_core import forge as FG, fx
    from minis_core.atlas import Library
    ap = argparse.ArgumentParser(prog='arena_harness.py bench')
    ap.add_argument('--intensity', default='normal', choices=AR.INTENSITIES)
    ap.add_argument('--seeds', type=int, default=6)
    ap.add_argument('--forge', default='on', choices=('on', 'off'))
    ap.add_argument('--backend', default='win', choices=('win', 'winblit', 'mac', 'none'))
    ap.add_argument('--size', default='1920x1080')
    ap.add_argument('--json', default=None)
    ap.add_argument('--tile', type=int, default=128)
    ap.add_argument('--tint', action='store_true', help='mac: flashes through the GPU layer instead of full frames (V8)')
    a = ap.parse_args(argv)
    lib, fxd = Library(hd=True), fx.default()
    W, H = (int(v) for v in a.size.lower().split('x'))
    kx, ky = W / 1920.0, H / 1080.0
    wins = [(i, int(l * kx), int(t * ky), int(r * kx), int(b * ky)) for i, l, t, r, b in BENCH_WINS]
    per, tiles, pxw = [], [], []
    for seed in range(a.seeds):
        st = AR.Stage((0, 0, W, H), wins, floor_y=H - 48)
        scr = None
        if a.forge == 'on':
            scr = FG.ScreenImage(AR.synthetic_backdrop(W, H, seed=5), rects=[(w['id'], w['l'], w['t'], w['r'], w['b']) for w in st.windows])
        ar = AR.Arena(st, {'a': lib['claude'], 'b': lib['knight']}, fxd, seed=seed, now=0.0, record=lambda *x, **k: None,
                      options={'intensity': a.intensity}, screen=scr, forge=a.forge == 'on')
        ar.flashes = True
        surf = BenchSurface(W, H, a.backend, a.tile, tint=a.tint)
        comp = AR.Compositor(ar, surf)
        now, n = 0.0, 0
        while ar.phase != 'done' and now < 240:
            now += 1 / 30.0
            surf.backend_s = 0.0
            t0 = time.perf_counter()
            ar.tick(now)
            comp.render(now)
            per.append((time.perf_counter() - t0) * 1000.0)
            n += 1
        pxw.append(surf.px_written / max(1, n))
        tiles.append((surf.tiles_up / max(1, n), surf.tiles_skip / max(1, n)))
    raw = list(per)
    per.sort()
    q = lambda p: per[min(len(per) - 1, int(p * len(per)))]
    out = dict(intensity=a.intensity, forge=a.forge, backend=a.backend, size=a.size, tile=a.tile, tint=a.tint, frames=len(per),
               mean=round(statistics.mean(per), 2), p50=round(q(0.5), 2), p95=round(q(0.95), 2), p99=round(q(0.99), 2),
               max=round(per[-1], 1), over_33ms=sum(1 for v in per if v > 33.3),
               cpu_pct_at_30fps=round(statistics.mean(per) * 30 / 10.0, 1),
               px_written_per_frame=int(statistics.mean(pxw)))
    if a.backend == 'mac':
        out['tiles_up_per_frame'] = round(statistics.mean(t[0] for t in tiles), 1)
        out['tiles_skipped_per_frame'] = round(statistics.mean(t[1] for t in tiles), 1)
    print(json.dumps(out))
    if a.json:
        Path(a.json).write_text(json.dumps(dict(out, per_frame_ms=[round(v, 3) for v in raw])), encoding='utf-8')
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'bench':
        sys.exit(bench(sys.argv[2:]))
    sys.exit(main())
