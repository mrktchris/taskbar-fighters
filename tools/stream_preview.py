"""Streamer-mode preview from SYNTHETIC window dumps (DEMO numbers, a temp data folder) - for docs and visual QA.

    python tools/stream_preview.py [--out qa/local/stream-demo.png] [--window SECONDS] [--chroma #00FF00]

It writes fake dump records the way the fighter, plate and scoreboard processes do (our own art: atlas frames,
render.plate, scoreboard.render; nothing from the screen), then runs them through minis_core/stream.py's Feed, Strip and
fit - the exact path the stream window uses - and saves the frame.  --window S also opens the real stream window for S
seconds (without taking the focus) and saves the last frame it presented.
"""
from __future__ import annotations
import argparse, json, os, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def write_demo_dump(folder, t, pose_a='idle', fa=0, pose_b='idle', fb=0, hp=None):
    """One record per role at a 2560 x 1440 layout (zone 40..900, 48 px taskbar at y 1392)."""
    from minis_core import render, scoreboard as SB
    from minis_core.atlas import Library
    from minis_core.telemetry import Snapshot
    lib = Library(hd=True)
    a, b = lib['claude'], lib['codex']
    folder.mkdir(parents=True, exist_ok=True)
    ms = int(t * 1000)
    head = 60
    roles = {
        'a': (a.frame_image(pose_a, fa, 1), 420, 1392 + 48 - 128 - head - 6, head),
        'b': (b.frame_image(pose_b, fb, -1), 520, 1392 + 48 - 128 - head - 6, head),
        'a-plate': (render.plate(a, Snapshot('claude', 'working', 41.0, 12.0, 'wk', '2d 4h'), t), 40, 1392 + 11, 0),
        'b-plate': (render.plate(b, Snapshot('codex', 'idle', 18.0), t), 172, 1392 + 11, 0),
        'scoreboard': (SB.render(dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (34, 29), 'b': (29, 34)}, mode='taskbar',
                                      hp=hp, wins={'a': 1, 'b': 0} if hp else {}, spark=[40, 55, 62, 48, 71, 66, 41])), 746, 1394, 0),
    }
    for role, (im, x, y, extra) in roles.items():
        if role in ('a', 'b'):                                  # a fighter window is the cell plus the jump headroom above it
            from PIL import Image
            win = Image.new('RGBA', (im.width, im.height + extra), (0, 0, 0, 0))
            win.paste(im, (0, extra))
            im = win
        stem = f'{role}-{ms}'
        im.save(folder / f'{stem}.png')
        (folder / f'{stem}.json').write_text(json.dumps({'role': role, 'id': 'stream', 'wall': t, 'x': x, 'y': y, 'w': im.width,
                                                         'h': im.height, 'scale': 1, 'density': 1, 'visible': True,
                                                         'png': f'{stem}.png'}), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'qa' / 'local' / 'stream-demo.png'))
    ap.add_argument('--window', type=float, default=0.0)
    ap.add_argument('--chroma', default='#00FF00')
    a = ap.parse_args(argv)
    os.environ['MINIS_DATA_BASE'] = tempfile.mkdtemp(prefix='minis-stream-')
    from minis_core import dump, stream
    bg = stream.parse_color(a.chroma)
    feed, strip = stream.Feed(), stream.Strip()
    rid = feed.ensure_request()
    folder = dump.dump_root() / rid
    t = time.time()
    write_demo_dump(folder, t, 'jab', 2, 'block', 1, hp={'a': 76, 'b': 40})
    recs = feed.records(rid)
    img = strip.compose(recs, lambda r: feed.image(rid, r))
    frame, k = stream.fit(img, img.width * 2 + 32, img.height * 2 + 32, bg)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out)
    print('strip', img.size, 'frame', frame.size, 'x', k, '->', out)
    if a.window > 0:
        from minis_win import stream_window as W
        win = W.StreamWindow(stream.TITLE, frame.width, frame.height, bg=bg, show_cmd=4)
        end = time.time() + a.window
        n, last = 0, None
        poses = [('idle', i % 6, 'idle', (i + 3) % 6) for i in range(6)] + [('jab', i % 4, 'block', i % 3) for i in range(6)]
        while time.time() < end and win.pump():
            pa, fa, pb, fb = poses[n % len(poses)]
            write_demo_dump(folder, time.time(), pa, fa, pb, fb, hp={'a': 76, 'b': 40})
            recs = feed.records(rid)
            img = strip.compose(recs, lambda r: feed.image(rid, r))
            cw, ch = win.client_size()
            last, _ = stream.fit(img, cw, ch, bg)
            win.present(last)
            n += 1
            win.wait(1 / 8)
        files = len(list(folder.glob('*')))
        win.close()
        feed.release()
        wp = out.with_name(out.stem + '-window.png')
        if last is not None:
            last.save(wp)
        print(f'window: {n} frames presented, client {win_size(last)}, {files} files left in the dump folder -> {wp}')
    return 0


def win_size(im):
    return None if im is None else im.size


if __name__ == '__main__':
    sys.exit(main())
