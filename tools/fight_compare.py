"""Before / after fight reels, headless: render taskbar matches and arena matches from ONE source tree, then put two trees'
reels side by side.

  python tools/fight_compare.py taskbar <out_dir> [--seeds 3,7,11] [--secs 70] [--fps 20]
      For each seed: a best-of-3 taskbar match at 128 px on the synthetic strip (tools/doc_images.taskbar_strip_frames, the
      real planner and renderer, DEMO numbers), cropped to the fight, saved as <out_dir>/taskbar-<seed>-1x.gif and -2x.gif.
  python tools/fight_compare.py arena <out_dir> [--seeds 2,5] [--secs 75] [--fps 15]
      A headless arena match (RAM surface, synthetic desktop, forge off) at 1280x720, saved at half size as
      <out_dir>/arena-<seed>.gif.
  python tools/fight_compare.py side <before_dir> <after_dir> <out_dir>
      Every reel present in both: one GIF with BEFORE on the left and AFTER on the right (frame by frame, the shorter one
      holds its last frame), labelled.

Run the first two from each tree (an old checkout and this one) into separate folders, then `side`.  No screen capture.
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
os.environ.setdefault('MINIS_TESTING', '1')
from PIL import Image, ImageDraw  # noqa: E402

ARENA_W, ARENA_H = 1280, 720
CROP_X = (300, 760)                       # the fight zone of the 940 px strip
PAIRS = {3: ('claude', 'codex'), 7: ('cursor', 'oni'), 11: ('gemini', 'knight')}   # the strip's bout ignores the seed: vary the pair


def save_gif(frames, path, fps):
    pal = [f.convert('RGB').quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 / fps), loop=0, optimize=False, disposal=1)
    return path


def taskbar(out, seeds, secs, fps):
    import doc_images
    os.makedirs(out, exist_ok=True)
    for seed in seeds:
        frames, meta, cfg = doc_images.taskbar_strip_frames(seconds=secs, fps=fps, seed=seed, chars=PAIRS.get(seed, ('claude', 'codex')), size=128)
        idx = [i for i, m in enumerate(meta) if m['script']]
        a, b = (max(0, idx[0] - fps), min(len(frames) - 1, idx[-1] + 2 * fps)) if idx else (0, len(frames) - 1)
        clip = [f.crop((CROP_X[0], 0, CROP_X[1], f.height)) for f in frames[a:b + 1]]
        print(save_gif(clip, os.path.join(out, f'taskbar-{seed}-1x.gif'), fps))
        print(save_gif([f.resize((f.width * 2, f.height * 2), Image.NEAREST) for f in clip], os.path.join(out, f'taskbar-{seed}-2x.gif'), fps))


def arena(out, seeds, secs, fps):
    from minis_core import arena as AR, fx
    from minis_core.atlas import Library
    os.makedirs(out, exist_ok=True)
    lib = Library(hd=True)
    wins = [(1, 90, 200, 580, 600), (2, 650, 250, 1180, 650), (3, 400, 410, 830, 670)]
    for seed in seeds:
        st = AR.Stage((0, 0, ARENA_W, ARENA_H), wins, floor_y=ARENA_H - 48)
        bd = AR.synthetic_backdrop(ARENA_W, ARENA_H, seed=3)
        ar = AR.Arena(st, {'a': lib['claude'], 'b': lib['knight']}, fx.default(), seed=seed, now=0.0, record=lambda *a, **k: None,
                      backdrop=bd, forge=False)
        ar.flashes = True
        surf = AR.Surface(ARENA_W, ARENA_H)
        comp = AR.Compositor(ar, surf)
        frames, now, n = [], 0.0, 0
        step = max(1, int(round(30 / fps)))
        while ar.phase != 'done' and now < secs:
            now += 1 / 30.0
            ar.tick(now)
            comp.render(now)
            n += 1
            if n % step == 0:
                frames.append(surf.canvas.resize((ARENA_W // 2, ARENA_H // 2), Image.NEAREST))
        print(save_gif(frames, os.path.join(out, f'arena-{seed}.gif'), fps))


def frames_of(path):
    im = Image.open(path)
    out = []
    try:
        while True:
            out.append(im.convert('RGB'))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    return out, im.info.get('duration', 50)


def side(before, after, out):
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(after)):
        if not name.endswith('.gif') or not os.path.exists(os.path.join(before, name)):
            continue
        fa, dur = frames_of(os.path.join(before, name))
        fb, _ = frames_of(os.path.join(after, name))
        n = max(len(fa), len(fb))
        w, h = fa[0].width + fb[0].width + 12, max(fa[0].height, fb[0].height) + 20
        res = []
        for i in range(n):
            im = Image.new('RGB', (w, h), (16, 16, 20))
            d = ImageDraw.Draw(im)
            d.text((4, 3), 'BEFORE (v1.0.0)', fill=(255, 170, 150))
            d.text((fa[0].width + 16, 3), 'AFTER (V9)', fill=(160, 255, 170))
            im.paste(fa[min(i, len(fa) - 1)], (0, 20))
            im.paste(fb[min(i, len(fb) - 1)], (fa[0].width + 12, 20))
            res.append(im)
        print(save_gif(res, os.path.join(out, 'side-' + name), 1000.0 / dur))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('taskbar', 'arena', 'side'))
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('--seeds', default=None)
    ap.add_argument('--secs', type=float, default=None)
    ap.add_argument('--fps', type=int, default=None)
    a = ap.parse_args()
    if a.cmd == 'taskbar':
        taskbar(a.dirs[0], [int(s) for s in (a.seeds or '3,7,11').split(',')], a.secs or 70, a.fps or 20)
    elif a.cmd == 'arena':
        arena(a.dirs[0], [int(s) for s in (a.seeds or '2,5').split(',')], a.secs or 75, a.fps or 15)
    else:
        side(a.dirs[0], a.dirs[1], a.dirs[2])
