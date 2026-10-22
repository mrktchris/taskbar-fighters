"""Render the stats card from a SYNTHETIC record (DEMO numbers, a temp data folder) for docs and visual QA.

    python tools/card_preview.py [--out qa/local/card-demo.png] [--empty]

Never reads the real record.json: MINIS_DATA_BASE points at a fresh temp folder before anything is imported.
"""
from __future__ import annotations
import argparse, os, random, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


PIECES = ['blade_lock', 'pull_launch', 'crosscut_freeze', 'vault_overhead', 'parry_riposte', 'aerial_finish']


def demo_record(seed=7, n=180, t0=1_760_000_000.0):
    """Feed n synthetic matches through records.record (the real writer) -> the record dict."""
    from minis_core import records
    rng = random.Random(seed)
    progs = ['claude', 'codex', 'gemini', 'cursor', 'ollama']
    weight = {'claude': 1.25, 'codex': 1.15, 'gemini': 0.9, 'cursor': 0.8, 'ollama': 0.7}
    moves = {'claude': ['spin_kick', 'iai_slash', 'cross_cut', 'riposte'], 'codex': ['ground_pound', 'chain_pull', 'deploy'],
             'gemini': ['star_shot', 'twin_flash', 'spin_kick'], 'cursor': ['tab_bolt', 'ground_pound'], 'ollama': ['pull_shot', 'serve']}
    t = t0
    for i in range(n):
        a, b = rng.sample(progs[:2] * 3 + progs, 2) if rng.random() < 0.6 else rng.sample(progs, 2)
        if a == b:
            continue
        w, l = (a, b) if rng.random() < weight[a] / (weight[a] + weight[b]) else (b, a)
        sweep = rng.random() < 0.4
        facts = dict(ko=rng.random() < 0.7, flawless=1 if rng.random() < 0.15 else 0, perfect=False, comeback=not sweep and rng.random() < 0.5,
                     ult=[w] if rng.random() < 0.3 else [], moves={w: {m: rng.randint(1, 4) for m in moves[w]}, l: {moves[l][0]: 1}},
                     boost=[w] if rng.random() < 0.08 else [], pieces=rng.sample(PIECES, 1) if rng.random() < 0.4 else [],
                     replay=dict(v=1, seed=rng.randint(1, 9999), kind='match', left='a', right='b', chars={'a': w, 'b': l}))
        if i == 150:
            facts.update(flawless=2, perfect=True)
            sweep = True
        t += rng.uniform(600, 5400)
        records.record(w, l, now=t, where='arena' if rng.random() < 0.05 else 'taskbar', score=(2, 0 if sweep else 1), facts=facts)
    return records.read()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'qa' / 'local' / 'card-demo.png'))
    ap.add_argument('--empty', action='store_true')
    a = ap.parse_args(argv)
    os.environ['MINIS_DATA_BASE'] = tempfile.mkdtemp(prefix='minis-card-')
    from minis_core import achievements, history, stats_card
    rec = {} if a.empty else demo_record()
    hist = {'days': {'2026-10-20': {'ctx_max': 93.0, 'plan_max': None, 'samples': 4}}}
    achievements.update(rec, hist)                      # seeds the temp achievements.json
    img = stats_card.render(rec, hist, now=1_761_000_000.0)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    print(out, img.size)
    return 0


if __name__ == '__main__':
    sys.exit(main())
