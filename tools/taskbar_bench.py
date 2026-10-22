"""Taskbar fight cost, headless: python tools/taskbar_bench.py [--size 128] [--fps 60] [--secs 60] [--chars claude,knight]

Plays a demo match between two real Brains (the shared timeline, the replayed opponent, 30 or 60 redraws a second) and
times, per redraw of slot a during the fight script, everything the slot process does to draw a frame except the window
upload: Brain.view + the HD scaling of the view + render.compose of the tight frame.  Prints ms per frame and the CPU it
implies at that redraw rate (one process).  No window, no screen.
"""
import argparse, os, random, statistics, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('MINIS_TESTING', '1')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=128)
    ap.add_argument('--fps', type=int, default=60)
    ap.add_argument('--secs', type=float, default=60.0)
    ap.add_argument('--chars', default='claude,knight')
    a = ap.parse_args(argv)
    import minis
    from minis_core import config as cfgmod, render, sim
    from minis_core.atlas import Library
    from minis_core.brain import LEFT, RIGHT, Brain
    lib = Library()
    hd = Library(hd=True) if a.size > 64 else None
    cfg = dict(cfgmod.DEFAULTS)
    k = a.size / 64.0
    z0, z1 = cfgmod.fight_zone(cfg, a.size)
    zone = (z0 / k, z1 / k)
    c1, c2 = a.chars.split(',')
    br = {w: Brain(w, lib[c], lib, cfg, random.Random(i), 1000.0, run=f'b{w}', zone=zone, record=sim.no_record)
          for i, (w, c) in enumerate(((LEFT, c1), (RIGHT, c2)))}
    for b in br.values():
        b.flashes = True
    tele = {w: sim.FakeTelemetry(w, [(0, 'idle', 30)]) for w in br}
    bus = {}
    if hd is not None:
        hd[c1]                                          # the slot decodes its HD sheets at start-up (resolve_size), not in a fight
    br[LEFT].request_demo('match', 1000.0, wait_s=30)
    ts = []
    for i in range(int(a.secs * a.fps)):
        now = 1000.0 + i / a.fps
        sim.step(br, tele, now, bus)
        b = br[LEFT]
        if b.mode != 'script':
            continue
        t0 = time.perf_counter()
        v = b.view(now)
        if hd is not None:
            h = hd[b.character]
            render.compose(h, h, minis.hd_view(v, h, b.atlas), b.snap, now, cfg, show_plate=False)
        else:
            render.compose(b.atlas, b.atlas, v, b.snap, now, cfg, show_plate=False)
        ts.append((time.perf_counter() - t0) * 1000.0)
        if ts[-1] > 1000.0 / a.fps:                     # a frame that missed its slot: which one, and in what move
            print(f'  slow frame #{len(ts)} t={now - 1000.0:.2f}s {ts[-1]:.1f} ms ({v.get("anim") if isinstance(v, dict) else ""})')
    ts.sort()
    m = statistics.mean(ts)
    print(f'size {a.size} fps {a.fps}: {len(ts)} fight frames, mean {m:.2f} ms, p95 {ts[int(len(ts) * 0.95)]:.2f} ms, '
          f'max {ts[-1]:.1f} ms -> {m * a.fps / 10.0:.1f} % of one core (compose only, no window upload)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
