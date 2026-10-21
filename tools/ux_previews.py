"""Offscreen previews of the UX layer as PNGs (and one GIF): Settings, the zone editor, the first-run guide and the legend,
hover cards, event signals, the results strip, the rival countdown plate, the replay window and the move book.  Rendered
from the same models and renderers the app uses, on a neutral backdrop with DEMO data: never a screen capture.

    python tools/ux_previews.py [out_dir] [--only settings,book,...]      (default out_dir: qa/ux)
    python tools/ux_previews.py docs/img --only docs                      the README's "Getting around" images
"""
from __future__ import annotations
import argparse, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix='minis-uxprev-'))
os.environ.setdefault('MINIS_TESTING', '1')
from minis_core import config as cfgmod  # noqa: E402
cfgmod.data_dir = lambda: _TMP           # never read or write the real data folder
from PIL import Image, ImageDraw  # noqa: E402

TASKBAR = (32, 32, 32, 255)
DESK = (26, 28, 36, 255)


def big(im, k):
    return im.resize((im.width * k, im.height * k), Image.NEAREST)


def on_desk(im, k=2, pad=12, band=False):
    """An element on a plain dark desktop (and a taskbar band under it when `band`)."""
    h = im.height + 2 * pad + (48 if band else 0)
    bg = Image.new('RGBA', (im.width + 2 * pad, h), DESK)
    if band:
        ImageDraw.Draw(bg).rectangle([0, h - 48, bg.width, h], fill=TASKBAR)
    bg.alpha_composite(im, (pad, pad))
    return big(bg, k)


def book(out):
    from minis_core import collection, lineup
    from minis_core.atlas import Library
    lib = Library()
    chars = lineup.characters()
    seen = {}
    for c in chars:
        ents = collection.entries(lib[c['id']])
        keys = {}
        for sid, lst in ents.items():
            for i, e in enumerate(lst):
                if (i * 7 + len(c['id'])) % 3 != 0:
                    keys[e['key']] = 1.0
        seen[c['id']] = keys
    b = collection.Book(chars, seen, lib, start='claude', now=0.0)
    paths = []
    b.cur = 3
    paths.append(out / 'book-attacks.png')
    big(b.render(0.4), 2).save(paths[-1])
    b.set_section(3)
    b.cur = 1
    paths.append(out / 'book-setpieces.png')
    big(b.render(0.9), 2).save(paths[-1])
    b.set_char(1)
    b.set_section(4)
    paths.append(out / 'book-finishers.png')
    big(b.render(1.3), 2).save(paths[-1])
    return paths


class _FakeStartup:
    def __init__(self, state='on'):
        self.state = state

    def status(self):
        return self.state, None

    def enable(self):
        return True, 'on'

    def disable(self):
        return True, 'off'


def settings(out):
    from minis_core import settings_ui as S
    cfg = dict(cfgmod.DEFAULTS)
    be = S.Backend(cfg, startup=None)
    be.startup_state = 'on'
    m = S.Model(be, now=0.0, is_mac=False)
    m.cur = 3
    paths = [out / 'settings.png']
    big(m.render(0.5), 2).save(paths[-1])
    m.cur = len(m.rows) - 1
    m.hover = ('zone', 'edit', len(m.rows) - 1)
    m.say('zone back to auto: applies at the next start', 0.0)
    paths.append(out / 'settings-zone-row.png')
    big(m.render(0.6), 2).save(paths[-1])
    mm = S.Model(be, now=0.0, is_mac=True)
    paths.append(out / 'settings-mac.png')
    big(mm.render(0.5), 2).save(paths[-1])
    return paths


def zone(out):
    from minis_core import settings_ui as S, scoreboard as SB
    z = S.ZoneEdit(1280, 48, (40, 900), board=(SB.W, 36))
    z.on_event('down', 900, 50)
    z.on_event('move', 960, 50)
    im = z.render(0.0)
    bg = Image.new('RGBA', (im.width, im.height + 60), DESK)
    ImageDraw.Draw(bg).rectangle([0, 60 + S.BAR_H, bg.width, bg.height], fill=TASKBAR)
    d = ImageDraw.Draw(bg)
    for i, x in enumerate(range(1000, 1240, 34)):                  # a few icon blocks on the mock taskbar (no real icons)
        d.rounded_rectangle([x, 60 + S.BAR_H + 9, x + 28, 60 + S.BAR_H + 38], 5, fill=(70, 74, 88, 255))
    bg.alpha_composite(im, (0, 60))
    p = out / 'zone-editor.png'
    big(bg.crop((0, 40, 1280, bg.height)), 1).save(p)
    return [p]


def guide(out):
    from minis_core import guide as G, scoreboard as SB
    span = (40, 940)
    targets = {'fighter': 520, 'plates': (40, 300), 'board': (746, 746 + SB.W)}
    paths = []
    for i in range(3):
        g = G.Guide('guide', span, targets, names={'a': 'Claude Code'}, now=0.0)
        g.i = i
        g.hover = 'next'
        paths.append(out / f'guide-{i + 1}.png')
        _strip(g.render(3.0), span).save(paths[-1])
    lg = G.Guide('legend', span, targets, names={'a': 'Claude Code'}, now=0.0)
    paths.append(out / 'legend.png')
    _strip(lg.render(3.0), span).save(paths[-1])
    return paths


def _strip(overlay, span, k=2):
    """The overlay above a mock taskbar strip with plates, two fighters and the scoreboard (from the real renderers)."""
    from minis_core import render, scoreboard as SB
    from minis_core.atlas import Library
    from minis_core.telemetry import Snapshot
    lib = Library()
    w = span[1] - span[0]
    bg = Image.new('RGBA', (w, overlay.height + 48), DESK)
    ImageDraw.Draw(bg).rectangle([0, overlay.height, w, bg.height], fill=TASKBAR)
    bg.alpha_composite(render.plate(lib['claude'], Snapshot('claude', 'working', 48.0), 0.0, name='Claude Code'), (0, overlay.height + 11))
    bg.alpha_composite(render.plate(lib['codex'], Snapshot('codex', 'waiting', 61.0), 0.0, name='Codex'), (132, overlay.height + 11))
    for ch, x, f in (('claude', 480, 1), ('codex', 560, -1)):
        fr = lib[ch].frame_image('idle', 0, f)
        bg.alpha_composite(fr, (x - span[0] - lib[ch].anchor(f), overlay.height + 48 - 64 + 7 - 0))
    st = dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (12, 7), 'b': (7, 12)}, mode='taskbar', arena=False, paused=False,
              hp=None, wins={}, spark=[20, 35, 60, 72, 91, 40, 48])
    bg.alpha_composite(SB.render(st), (746 - span[0], overlay.height + 2))
    bg.alpha_composite(overlay, (0, 0))
    return big(bg, k)


def cards(out):
    from minis_core import hovercard as HC
    infos = [dict(name='Claude Code', accent=(240, 161, 132), state='working', since_s=184, ctx=77.0, plan_pct=12.0, plan_label='wk',
                  resets_in='2d 4h', record=(12, 7), opponent='Codex', h2h=(5, 3)),
             dict(name='Codex', accent=(169, 157, 255), state='waiting', since_s=52, waiting_s=45, ctx=61.0, record=(7, 12), opponent='Claude',
                  h2h=(3, 5)),
             dict(name='Codex', accent=(169, 157, 255), state='limit', ctx=96.0, plan_pct=100.0, plan_label='5h', resets_in='1h 12m',
                  record=(7, 12), opponent='Claude'),
             dict(name='Grok', accent=(224, 196, 108), state='sleeping', since_s=5400, dormant=True, ctx=None, process=True,
                  rival_in=372, rival_kind='match', record=(2, 4), opponent='Claude'),
             dict(name='Sparring bot', accent=(224, 196, 108), state='sleeping', bot=True, record=None)]
    paths = []
    for i, info in enumerate(infos):
        paths.append(out / f'card-{i + 1}-{info["state"]}.png')
        on_desk(HC.render(info), 2, pad=8).save(paths[-1])
    return paths


def results(out):
    from minis_core import replay, results as R
    from minis_core.atlas import Library
    lib = Library()
    plan = dict(kind='match', left='a', right='b', pos={'a': 300.0, 'b': 332.0}, t0=0.0, seed=42, chars={'a': 'claude', 'b': 'codex'},
                mode='decided', scores={'a': 70.0, 'b': 90.0}, span=110.0)
    _, summ = replay.summarize(plan, lib)
    entry = dict(id='x', ts=0.0, plan=plan, programs={'a': 'claude', 'b': 'codex'}, labels={'a': 'Claude', 'b': 'Codex'},
                 winner=summ['winner'], loser=summ['loser'], wins=summ['wins'], stats=replay.stats_of(summ))
    from minis_core import scoreboard as SB
    st = dict(names={'a': 'Claude', 'b': 'Codex'}, records={'a': (12, 8), 'b': (8, 12)}, mode='taskbar', arena=False, paused=False,
              hp=None, wins={}, spark=None, result=R.headline(entry)[0])
    strip = R.render(entry, 1.2, lib)
    board = SB.render(st)
    w = max(strip.width, board.width) + 24
    bg = Image.new('RGBA', (w, strip.height + 48 + 22), DESK)
    ImageDraw.Draw(bg).rectangle([0, strip.height + 22, w, bg.height], fill=TASKBAR)
    bg.alpha_composite(strip, (w - 12 - strip.width, 18))
    bg.alpha_composite(board, (w - 12 - board.width, strip.height + 24))
    p = out / 'results-strip.png'
    big(bg, 2).save(p)
    return [p]


def _fighter_with(sig, now, char='claude', anim='idle', state=None, paused=False):
    """One 128 px fighter (HD art) with the signal overlays, composed the way the fighter window does it."""
    from minis_core import render, replay
    from minis_core.atlas import Library
    lib, hd = Library(), Library(hd=True)
    a = lib[char]
    view = dict(anim=anim, frame=0, x=60.0, facing=1, dim=False, proj=None, fx=[], banner=None, shake=(0, 0), busy=False, lift=0.0,
                headroom=cfgmod.JUMP_HEADROOM, clip=(0, 120), flash=0.0)
    ov, _ = sig.overlays(view, a, now, paused=paused)
    view['fx'] = ov
    h = hd[char]
    im = render.compose_full(h, h, replay._hd_view(view, h, a), None, now, 240, dict(cfgmod.DEFAULTS), win_x=0, show_plate=False)
    return im


def signals(out):
    from minis_core import signals as SG
    from minis_core.telemetry import Snapshot
    cards = []
    s = SG.Signals()
    s.on_snapshot(Snapshot('claude', 'idle', 40.0, events=['finished']), 1.0)
    cards.append(('task done: flag until hovered', _fighter_with(s, 1.2, anim='victory')))
    s = SG.Signals()
    s.on_snapshot(Snapshot('codex', 'waiting', 61.0), 1.0)
    cards.append(('needs you: amber halo pulse', _fighter_with(s, 1.35, 'codex', 'wait')))
    s = SG.Signals()
    s.on_snapshot(Snapshot('claude', 'working', 92.0), 1.0)
    s.on_snapshot(Snapshot('claude', 'working', 31.0), 2.0)
    cards.append(('second wind (compaction)', _fighter_with(s, 2.6, anim='powerup')))
    s = SG.Signals()
    s.on_snapshot(Snapshot('gemini', 'working', 87.0), 1.0)
    cards.append(('near the limit: DANGER', _fighter_with(s, 1.4, 'gemini', 'rage')))
    s = SG.Signals()
    s.on_snapshot(Snapshot('cursor', 'limit', 93.0, events=['limit']), 1.0)
    cards.append(('limit K.O.: FINISH!', _fighter_with(s, 1.3, 'cursor', 'dizzy')))
    from minis_core.render import font, text
    w = sum(im.width for _, im in cards) + 10 * (len(cards) + 1)
    h = max(im.height for _, im in cards) + 30
    bg = Image.new('RGBA', (w, h + 20), DESK)
    d = ImageDraw.Draw(bg)
    d.rectangle([0, h - 18, w, h + 20], fill=TASKBAR)
    x = 10
    for lab, im in cards:
        bg.alpha_composite(im, (x, h - im.height + 4))
        d.fontmode = '1'
        text(d, (x + 4, 4), lab, (230, 230, 240), 9, False)
        x += im.width + 10
    p = out / 'signals.png'
    big(bg, 2).save(p)
    return [p]


def plate(out):
    from minis_core import render, ux_runtime
    from minis_core.atlas import Library
    from minis_core.telemetry import Snapshot
    lib = Library()
    base = render.plate(lib['generic'], Snapshot('grok', 'sleeping'), 0.0, name='Grok')
    im = ux_runtime._rival_plate(base, (372, 'match'))
    bg = Image.new('RGBA', (base.width * 2 + 30, 40), TASKBAR)
    bg.alpha_composite(base, (10, 7))
    bg.alpha_composite(im, (base.width + 20, 7))
    p = out / 'plate-rival.png'
    big(bg, 3).save(p)
    return [p]


def replay_frames(out):
    from minis_core import replay
    plan = dict(kind='match', left='a', right='b', pos={'a': 300.0, 'b': 332.0}, t0=0.0, seed=42, chars={'a': 'claude', 'b': 'codex'},
                mode='decided', scores={'a': 70.0, 'b': 90.0}, span=110.0)
    _, s = replay.summarize(plan)
    code = replay.encode(replay.clean_plan(plan), s)
    fr = list(replay.frames(plan, 'final', fps=15, names={'a': 'Claude', 'b': 'Codex'}, code=code))
    paths = []
    for name, i in (('replay-window', len(fr) // 3), ('replay-ko', (2 * len(fr)) // 3)):
        paths.append(out / f'{name}.png')
        fr[i][0].save(paths[-1])
    paths.append(out / 'replay.gif')
    replay.save_gif(((im, ms) for im, ms in fr[::2]), paths[-1])
    return paths


def docs(out):
    """The README's "Getting around" images (docs/img/ux-*.png and ux-replay.gif), picked from the sections above."""
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix='minis-uxdocs-'))
    for fn in (settings, zone, guide, cards, results, signals, plate, book):
        fn(tmp)
    pick = {'settings.png': 'ux-settings.png', 'zone-editor.png': 'ux-zone.png', 'guide-1.png': 'ux-guide.png', 'legend.png': 'ux-legend.png',
            'results-strip.png': 'ux-results.png', 'signals.png': 'ux-signals.png', 'plate-rival.png': 'ux-rival.png',
            'book-attacks.png': 'ux-book.png'}
    paths = []
    for src, dst in pick.items():
        paths.append(out / dst)
        shutil.copyfile(tmp / src, paths[-1])
    a, b = Image.open(tmp / 'card-1-working.png'), Image.open(tmp / 'card-2-waiting.png')
    c = Image.open(tmp / 'card-4-sleeping.png')
    row = Image.new('RGBA', (a.width + b.width + c.width, max(a.height, b.height, c.height)), DESK)
    row.alpha_composite(a.convert('RGBA'), (0, 0))
    row.alpha_composite(b.convert('RGBA'), (a.width, 0))
    row.alpha_composite(c.convert('RGBA'), (a.width + b.width, 0))
    paths.append(out / 'ux-cards.png')
    row.save(paths[-1])
    from minis_core import replay
    plan = dict(kind='match', left='a', right='b', pos={'a': 300.0, 'b': 332.0}, t0=0.0, seed=42, chars={'a': 'claude', 'b': 'codex'},
                mode='decided', scores={'a': 70.0, 'b': 90.0}, span=110.0)
    _, s = replay.summarize(plan)
    paths.append(out / 'ux-replay.gif')
    replay.save_gif(replay.frames(plan, 'final', fps=12, names={'a': 'Claude', 'b': 'Codex'}, code=replay.encode(replay.clean_plan(plan), s)),
                    paths[-1], colors=64)
    for p in paths:
        if p.suffix == '.png':
            Image.open(p).convert('RGB').save(p, optimize=True)
    return paths


def text_fix(out):
    """Before / after of the small UI text: FreeType monochrome hinting (up to V8) vs render.text now, 1x and 2x."""
    from minis_core import render
    from minis_core.render import font
    lines = [('Claude Code', 10, True), ('rest the mouse on a fighter or plate: its state in words', 9, False),
             ('Every row is also a command: minis.py settings list', 9, False), ('arena: one screen picture held in RAM', 9, False),
             ('waiting for you · 1 min 37 s', 9, True), ('Codex 7-12   vs   Claude 12-7', 10, True)]
    rows = []
    for label, draw in (('before (fontmode 1)', 'mono'), ('after (render.text)', 'new')):
        im = Image.new('RGBA', (330, 14 * len(lines) + 18), (18, 18, 22, 255))
        d = ImageDraw.Draw(im)
        render.text(d, (6, 2), label, (255, 196, 80), 9, True)
        for i, (s, size, bold) in enumerate(lines):
            if draw == 'mono':
                d.fontmode = '1'
                d.text((6, 16 + 14 * i), s, fill=(230, 230, 240), font=font(size, bold))
            else:
                render.text(d, (6, 16 + 14 * i), s, (230, 230, 240), size, bold)
        rows.append(im)
    w = sum(r.width for r in rows) + 10
    one = Image.new('RGBA', (w, rows[0].height), (10, 10, 14, 255))
    one.alpha_composite(rows[0], (0, 0))
    one.alpha_composite(rows[1], (rows[0].width + 10, 0))
    p1, p2 = out / 'text-before-after.png', out / 'text-before-after-2x.png'
    one.save(p1)
    big(one, 2).save(p2)
    return [p1, p2]


SECTIONS = {'text': text_fix, 'book': book, 'settings': settings, 'zone': zone, 'guide': guide, 'cards': cards, 'results': results, 'signals': signals,
            'plate': plate, 'replay': replay_frames, 'docs': docs}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?', default=str(ROOT / 'qa' / 'ux'))
    ap.add_argument('--only', default='')
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    want = [s for s in a.only.split(',') if s] or [s for s in SECTIONS if s != 'docs']   # docs: `--only docs docs/img`
    for name in want:
        for p in SECTIONS[name](out):
            print(p)


if __name__ == '__main__':
    main()
