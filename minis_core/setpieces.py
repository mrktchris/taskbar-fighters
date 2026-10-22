"""Hand-authored set pieces: choreographed joint exchanges for BOTH fighters that a match plays at its dramatic moments.

Why: procedural exchanges (choreo.py) give variety, but the best moments of a fight are directed - a blade lock that
breaks into a riposte, a chain pull into a juggle, a dash-through where both stand frozen until the cut lands.  A set
piece is data: an ordered list of beats in the same grammar plan_exchange produces (rounds.Bout plays them with the same
positions, sync, HP, hitstop and effects), written against weapon-family *slots* instead of move names, so any pairing
plays it.  Each slot names a move `type` (anim.json, V7) or a short list of fallbacks; a piece whose slots a fighter
cannot fill is simply not eligible for that pairing.

Beat fields on top of the plan_exchange grammar (rounds.py reads them):
  pause    seconds both fighters stand still before this beat (a stand-off)
  freeze   hitstop override in ms on this beat's contact (the frozen beat before a cut lands)
  slow     [seconds, k]: after the contact freeze, the animation clock runs at k for that long (both fighters)
  piece    the set piece's name (logged; the move list and previews read it)
Damage stays on the V4 table (12 / 24 / 36 per landed move), so HP pacing and the record are unchanged.

Determinism: which piece plays, and when, is drawn from the bout's seeded rng (rounds.make_match), so both slot processes
derive the identical exchange from the shared plan.  Preview any piece with `python tools/setpiece_preview.py`.
"""
from __future__ import annotations

from . import choreo

# slot -> candidates, in order: a move `type`, '=name' for a literal shared move, '@sig:<role>' for a signature move
SLOTS = {
    'string': ('string',),
    'heavy': ('=cleave', '=overhead_slam', '=cross_cut', '=scissor_cut', '=tonfa_crush', '=fan_cut', '=ring_slash',
              '=pole_spin', '=arrow_volley', '=guard_break', '=roundhouse'),
    'riposte': ('riposte', '=cross'),
    'pull': ('pull', 'through'),
    'launcher': ('=uppercut',),
    'air': ('air',),
    'spike': ('spike',),
    'through': ('through',),
    'vault': ('=pole_vault', '=vault_kick', '=leap_shot', 'spike'),
    'guard_break': ('guard_break',),
    'throw': ('throw',),
    'strike': ('=jab', '=cross', 'string'),
}

# A piece: title, when it may play, who lands the decisive blow (`lander`, default 'att'), and its beats.  'who' is 'att'
# (the fighter the match chose to attack) or 'dfn'.
PIECES = {
    'blade_lock': dict(
        title='Blade lock', when=('opener', 'mid'), lander='dfn',
        desc='The weapons meet and lock; a straining push, both skid apart, a stand-off, then the defender ripostes.',
        beats=[dict(who='att', slot='string', outcome='clash'),
               dict(who='dfn', slot='riposte', outcome='hit', react='hit_high', pause=0.35, freeze=180)]),
    'pull_launch': dict(
        title='Pull and launch', when=('mid', 'opener'),
        desc='Yanked in (or closed down), popped into the air, cut in mid-air, spiked into the floor.',
        beats=[dict(who='att', slot='pull', outcome='hit', react='pulled'),
               dict(who='att', slot='launcher', outcome='hit', react='launched', juggle=True, launch=True),
               dict(who='att', slot='air', outcome='hit', react='air_hit', juggle=True),
               dict(who='att', slot='spike', outcome='hit', react='spiked', juggle=True, spike=True, down=True)]),
    'crosscut_freeze': dict(
        title='Cross-cut freeze', when=('mid', 'finisher'),
        desc='A dash THROUGH the opponent; both stand frozen, back to back, then the cut lands in slow motion.',
        beats=[dict(who='att', slot='through', outcome='hit', react='hit_back', through=True, freeze=420, slow=(0.45, 0.4))]),
    'vault_overhead': dict(
        title='Vault overhead', when=('opener', 'mid'),
        desc='A vaulting attack from range, then the heavy follow-up while the opponent is still reeling.',
        beats=[dict(who='att', slot='vault', outcome='hit', react='hit_high'),
               dict(who='att', slot='heavy', outcome='hit', react='hit_heavy', chain=True)]),
    'parry_riposte': dict(
        title='Parry, riposte', when=('comeback', 'mid'), lander='dfn',
        desc='The big swing is swatted aside with a flash; the riposte answers before the swing has finished.',
        beats=[dict(who='att', slot='heavy', outcome='parry', react='parry'),
               dict(who='dfn', slot='riposte', outcome='hit', react='hit_high', freeze=200, riposte=True)]),
    'guard_crush_combo': dict(
        title='Guard crush', when=('mid', 'opener'),
        desc='The guard is broken open, and the 3-hit string goes straight through the opening.',
        beats=[dict(who='att', slot='guard_break', outcome='guard_break', react='guard_crush', guard_break=True, pre='block'),
               dict(who='att', slot='string', outcome='hit', react='hit', string=True),
               dict(who='att', slot='heavy', outcome='hit', react='hit_heavy', string=True)]),
    'comeback_reversal': dict(
        title='Reversal', when=('comeback',),
        desc='Two attacks blocked under pressure, then the grab out of nowhere: a throw that turns the round.',
        beats=[dict(who='dfn', slot='strike', outcome='block', react='block_hit', pre='block'),
               dict(who='dfn', slot='string', outcome='block', react='block_hit', pre='block'),
               dict(who='att', slot='throw', outcome='hit', react='thrown', throw=True, down=True)]),
    'aerial_finish': dict(
        title='Aerial finish', when=('finisher', 'mid'),
        desc='Launched, juggled, and spiked, the last blow in slow motion.',
        beats=[dict(who='att', slot='launcher', outcome='hit', react='launched', juggle=True, launch=True),
               dict(who='att', slot='air', outcome='hit', react='air_hit', juggle=True),
               dict(who='att', slot='spike', outcome='hit', react='spiked', juggle=True, spike=True, down=True, slow=(0.5, 0.4))]),
}

ORDER = tuple(PIECES)
P_OPENER, P_MID = 0.6, 0.25            # chance a round's second exchange / a later exchange is a set piece
MAX_PER_MATCH = 3


def fill(atlas, slot):
    """The move that fills `slot` for this atlas, or None."""
    for c in SLOTS[slot]:
        if c.startswith('='):
            if c[1:] in atlas.anim:
                return c[1:]
        else:
            m = choreo.first_of_type(atlas, c)
            if m:
                return m
    return None


def eligible(name, A, D, friendly=False):
    """Every slot of the piece can be filled by the fighter that plays it, and the defender has every reaction row."""
    pc = PIECES[name]
    for b in pc['beats']:
        X, Y = (A, D) if b['who'] == 'att' else (D, A)
        if fill(X, b['slot']) is None:
            return False
        if b.get('react') and b['react'] not in Y.anim:
            return False
        if b.get('pre') and b['pre'] not in Y.anim:
            return False
        if friendly and (b.get('down') or b.get('throw') or b.get('juggle')):
            return False
    return True


def choose(rng, A, D, when, friendly=False):
    """One draw: a piece that may play at `when` ('opener' | 'mid' | 'comeback' | 'finisher') for this pairing, or None."""
    names = [n for n in ORDER if when in PIECES[n]['when'] and eligible(n, A, D, friendly)]
    if not names:
        return None
    return names[rng.randrange(len(names))]


def resolve(name, att, dfn, friendly=False):
    """-> a plan_exchange-shaped dict (kind, beats, range_after, air, opener, boost, comeback, piece) for Pickers `att` /
    `dfn`, with concrete move names, damage and hitstop read from the atlases.  The Pickers note every move, so the
    no-repeat rule still sees what the set piece used."""
    A, D = att.atlas, dfn.atlas
    beats = []
    for spec in PIECES[name]['beats']:
        X, P = (A, att) if spec['who'] == 'att' else (D, dfn)
        move = fill(X, spec['slot'])
        P.note(move)
        out = spec.get('outcome', 'hit')
        kind = 'counter' if spec['who'] == 'dfn' and out == 'hit' else 'strike'
        dmg = choreo.damage_of(X, move, 'strike') if out == 'hit' else (choreo.GUARD_CHIP if out == 'guard_break' else 0)
        hs = choreo.hitstop_ms(X, move, kind)
        if out in ('block', 'clash'):
            hs = choreo.block_hitstop(hs)
        if spec.get('freeze'):
            hs = max(hs, int(spec['freeze']))
        react = spec.get('react')
        if friendly and spec.get('down'):
            react = 'hit_heavy'
        b = dict(who=spec['who'], kind=kind, anim=move, dmg=dmg, outcome=out, pre=spec.get('pre'), react=react,
                 hitstop=hs if out != 'whiff' else 0, knock=choreo.KNOCK_PX.get(react, choreo.KNOCK_PX['hit']) if react else 0,
                 down=bool(spec.get('down')) and not friendly, piece=name)
        for k in ('juggle', 'launch', 'spike', 'through', 'throw', 'pull', 'string', 'chain', 'guard_break', 'riposte',
                  'pause', 'slow'):
            if spec.get(k):
                b[k] = list(spec[k]) if isinstance(spec[k], tuple) else spec[k]
        if out == 'parry':
            b['react'] = 'parry'
        if out == 'clash':
            b['react'], b['knock'] = 'clash', choreo.CLASH_PUSH
        if spec['slot'] == 'pull' and choreo.first_of_type(A, 'pull') is None:
            b.pop('pull', None)                          # no chain: the slot fell back to a dash-through or a dash-in
            if (A.anim.get(move) or {}).get('type') == 'through':
                b['through'] = True
                b['react'] = 'hit_back' if 'hit_back' in D.anim else 'hit_heavy'
            else:
                b['react'] = 'hit'
            b['knock'] = choreo.KNOCK_PX.get(b['react'], 6)
        beats.append(b)
    return dict(kind='strike', beats=beats, range_after='close', air=False, opener=None, boost=False, comeback=False, piece=name)
