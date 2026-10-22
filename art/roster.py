"""The fighter roster: one entry per character the director can assign to a slot.

Every character is a rig.Body variant (proportions, headgear, armour, weapon(s), short hanging bits, palette) plus plate identity
(`display`, `tag`, `accent`) and a `signature` naming its strike / special / super.  Every character gets the full shared
move set from moves.py; its three signature moves are built from parameterised templates in moves.py (`spin`, `pound`,
`throw`, `cast`, `rewind`, `raise`), so the planner can treat all characters the same way and never branch on a name.

V6: thirteen characters.  The seven program ids keep their names and signature moves with new bodies; the six extras
(kunoichi, knight, barbarian, monk, nomad, oni) reuse the templates under their own move names.  Every body is defined here.
`style` names the signature idle / victory template (moves.py IDLES / VICTORIES).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import rig
from rig import Body, _g, hexrgb

PAPER = _g('F4F4F2', 'FFFFFF', 'A9A9B4', '4A4A55')
FLASH = dict(fill=hexrgb('FFFFFF'), ol=hexrgb('B8BCD0'))


@dataclass(frozen=True)
class Character:
    name: str
    display: str
    tag: str                    # plate text
    accent: str                 # plate / HUD accent, '#RRGGBB'
    body: Body
    signature: dict             # {'strike': move, 'special': move, 'super': move}
    sig_moves: dict             # move -> (template, desc, opts)
    projectile: dict = field(default_factory=dict)   # style + colours for proj.png, `kind` for anim.json
    style: dict = field(default_factory=dict)        # {'idle': template, 'victory': template} (moves.py)


def _fx(a, b, w, c):
    return dict(a=hexrgb(a), b=hexrgb(b), w=hexrgb(w), c=hexrgb(c))


# ---------------------------------------------------------------- bodies (V6 roster)
# Every costume is original pixel art built by the rig from these flags (docs/CREDITS.md lists the packs that were
# studied for proportion and keying; nothing is copied).  ~4.5 heads tall, a weapon in hand, one silhouette feature each.
def pal(skin, hair, cloth, trim, pants, helm, metal, hilt, fx, shoe=None, paper=None, ink='1A1620'):
    """A character palette.  Each material is a hex base (ramped) or a ramp dict; a string naming another material
    reuses it (fewer colours at 64 px)."""
    raw = dict(skin=skin, hair=hair, cloth=cloth, trim=trim, pants=pants, helm=helm, metal=metal, hilt=hilt,
               shoe=shoe or 'pants')
    out = {}
    for k, v in raw.items():                       # materials first, then aliases (which may chain)
        if isinstance(v, dict):
            out[k] = v
        elif v not in raw:
            out[k] = rig.ramp(v)
    while len(out) < len(raw):
        for k, v in raw.items():
            if k not in out and isinstance(v, str) and v in out:
                out[k] = out[v]
    inkc = hexrgb(ink)
    out['ink'] = dict(base=inkc, hi=inkc, sh=inkc, ol=inkc)
    out['sole'] = dict(base=inkc, hi=out['pants']['sh'], sh=inkc, ol=inkc)
    out['paper'] = out[paper] if paper else dict(base=hexrgb('FFFFFF'), hi=hexrgb('FFFFFF'), sh=out['metal']['sh'], ol=inkc)
    out['fx'] = _fx(*fx)
    out['flash'] = FLASH
    return out


R = rig.ramp
W_ = rig.Weapon
B_ = rig.Bit

# Claude: ronin swordswoman.  Wide straw kasa, a short tied topknot tail, terracotta kimono, dark hakama, katana.
CLAUDE = Body('claude', sigil='/', torso_w=10.5, waist=0.70, hair='topknot', headgear='kasa', chest='robe', skirt='hakama', sash=True,
              sleeves='loose', weapon=W_('katana', 17, 3.5, rel=-62, width=1.8, grip2=2.4), ghost_group='cloth',
              bits=(B_('head', (-5.4, -1.0), n=3, seg=1.9, width=1.6, part='bitH', rest=108),
                    B_('hip', (-4.6, 1.6), n=2, seg=2.4, width=2.0, part='bitT', rest=112)),
              groups={'helm2': 'pants', 'hilt': 'pants'},
              palette=pal(skin='F6D2B0', hair='2A2230', cloth=R('BF5A3C', hi='D97757', sh='93412E'), trim=R('F2E6D8'), pants='hair', helm=R('FFB86B'),
                          metal=R('DDE0E8', hi2='FFFFFF'), hilt='hair', fx=('FFB86B', 'FFE27A', 'FFFFFF', 'F2E6D8'), paper='trim'))

# Codex: shadow ninja.  Pointed cowl, cloth mask, glowing violet eyes, violet arm wraps, twin reverse-grip kunai and a
# short chain hanging from the rear one.
CODEX = Body('codex', sigil='$', thigh=10.5, shin=10.5, torso=14, torso_w=10, waist=0.70, headgear='cowl', face='mask', chest='wrap',
             gauntlet=True, boots=True, weapon=W_('kunai', 8, 2.4, rel=148, width=2.0), weapon_b=W_('kunai', 8, 2.4, rel=148, width=2.0),
             bits=(B_('head', (-5.8, 0.6), n=2, seg=2.4, width=1.4, part='bitT', rest=122),
                   B_('hb', (0, 0), n=3, seg=1.7, width=1.0, part='bitM', rest=96)),
             groups={'helm': 'cloth', 'mask': 'pants', 'helm2': 'trim'}, flats={'lens': ('trim', 'hi')},
             ghost_group='trim', ghost_style='holo',
             palette=pal(skin='C68A5E', hair='cloth', cloth=R('1C1B26', hi='3A3550'), trim=R('7C6CFF', hi='E4E0FF'), pants=R('3A3550'),
                         helm='cloth', metal=R('C9C6E0', hi='E4E0FF'), hilt='pants', fx=('9B6BFF', 'FFE27A', 'FFFFFF', 'E4E0FF')))

# Gemini: twin-blade dancer.  Hair bun with gold tassels, a gold headband with a star crest, blue top, gold sash with
# short ends, two short swords.
GEMINI = Body('gemini', sigil='*', torso_w=9.6, waist=0.64, hip_w=0.80, limb=3, hair='bun', headgear='crest', chest='wrap', sash=True,
              boots=True, weapon=W_('short', 12, 3.0, rel=-38, width=1.7), weapon_b=W_('short', 12, 3.0, rel=-30, width=1.7),
              bits=(B_('head', (-5.4, -4.0), n=2, seg=2.0, width=1.2, part='bitT', rest=100),
                    B_('hip', (-4.4, 1.6), n=2, seg=2.4, width=2.0, part='bitT', rest=110)),
              flats={'glow': ('trim', 'hi')}, ghost_group='cloth', ghost_style='spark',
              palette=pal(skin='A86E4C', hair='pants', cloth=R('3F7BE0'), trim=R('E8C55A'), pants=R('1B1F30'), helm='trim',
                          metal=R('F4F4F2', sh='A9B0C4'), hilt='pants', fx=('E8718C', 'FFE27A', 'FFFFFF', 'F4F4F2')))

# Cursor: cyber lancer.  Black helmet with a cyan visor and a pink fin, angled pink shoulder plates, a long spear with an
# arrowhead tip held high.
CURSOR = Body('cursor', sigil='>', thigh=11.5, shin=11.5, torso_w=10.4, waist=0.68, headgear='visor', pads='angled', boots=True,
              gauntlet=True, weapon=W_('spear', 30, 13, rel=-30, slide=True, grip2=6),
              groups={'helm': 'cloth', 'helm2': 'helm', 'cuff_f': 'trim', 'cuff_b': 'trim'}, flats={'lens': ('trim', 'hi')},
              ghost_group='trim', ghost_style='streak',
              palette=pal(skin='F0C8A8', hair='cloth', cloth=R('16161C', hi='2C2C38'), trim=R('5FD3F3', hi='B8F1FF'), pants=R('26262F'),
                          helm=R('FF4FA3'), metal=R('B8F1FF'), hilt=R('3A3A48'), fx=('5FD3F3', 'FFE27A', 'FFFFFF', 'B8F1FF')))

# Ollama: mountain monk-brute.  Wide and heavy, a brown dome helmet with tall cream llama-ear horns, cream wool torso,
# brown robe skirt, a heavy staff with orange caps.
OLLAMA = Body('ollama', sigil='o', thigh=10, shin=10, torso=15, torso_w=16, waist=0.94, hip_w=0.96, limb=4, leg_add=2, upper=7.5, fore=7.5,
              head_w=11, head_h=11, foot_len=8, headgear='horned', skirt='robe', beads=True, boots=True, stance=1.35,
              weapon=W_('staff', 27, 12, rel=-82, width=2.3, slide=True, grip2=6),
              groups={'horn': 'cloth', 'helm2': 'metal', 'skirt': 'trim'}, flats={'glow': ('metal', 'base')}, ghost_group='cloth',
              palette=pal(skin='E2B48C', hair='pants', cloth=R('EEE6D4'), trim=R('8A5A38'), pants=R('3A2A20'), helm='trim',
                          metal=R('FFB347'), hilt=R('6A4428'), fx=('FFB347', 'FFE27A', 'FFFFFF', 'EEE6D4')))

# LM Studio: white cyber samurai (own design, white armour with neon edge light).  White kabuto with a
# glowing teal V crest, white sode / chest plate / tassets over a dark suit, an energy katana with a magenta hilt.
LMSTUDIO = Body('lmstudio', sigil='L', torso_w=10.6, headgear='kabuto', face='glow', chest='plate', pads='sode', skirt='tassets', boots=True,
                gauntlet=True, weapon=W_('energy', 18, 3.5, rel=-56, width=2.0, grip2=2.4),
                bits=(B_('hip', (-4.8, 2.2), n=2, seg=2.0, width=1.6, part='bitT', rest=112),),
                groups={'helm2': 'hilt', 'cuff_f': 'helm', 'cuff_b': 'helm', 'shoe_f': 'helm', 'shoe_b': 'helm', 'boot_f': 'helm', 'boot_b': 'helm'},
                flats={'glow': ('trim', 'hi'), 'lens': ('trim', 'hi')}, ghost_group='trim', ghost_style='holo',
                palette=pal(skin='C68B63', hair='pants', cloth='pants', trim=R('1FD6C4', hi='7CF8EA'), pants=R('262C40'),
                            helm=R('E4ECF4', sh='A9B8C8'), metal=R('7CF8EA', hi2='FFFFFF'), hilt=R('D9488F'), fx=('F59AC4', 'FFE27A', 'FFFFFF', '7CF8EA')))

# Agent: archer-ranger.  Olive hood with a gold edge, a quiver of orange-fletched arrows over the back, a leather vest, a
# bow in the lead hand (it also bashes) and a dagger in the rear hand for close range.
GENERIC = Body('generic', sigil='+', torso_w=10.4, waist=0.70, headgear='hood', chest='vest', quiver=True, boots=True,
               weapon=W_('bow', 17, 0, rel=0), weapon_b=W_('dagger', 8, 2.4, rel=-24, width=1.6),
               groups={'helm': 'cloth', 'vest': 'hilt', 'band': 'trim'}, flats={'arrow': ('fx', 'a')}, ghost_group='trim',
               palette=pal(skin='E0B090', hair='pants', cloth=R('5B6B4A'), trim=R('E0C46C'), pants=R('3A3A40'), helm='cloth',
                           metal=R('D8DCE4'), hilt=R('7A5234'), fx=('FF9C2C', 'FFE27A', 'FFFFFF', 'E0C46C')))

# ---------------------------------------------------------------- the six selectable extras (V6)
# Kunoichi: crimson kunoichi with twin tessen fans, a high ponytail and headband ribbons.
KUNOICHI = Body('kunoichi', thigh=10.5, shin=10.5, torso=14, torso_w=9.4, waist=0.62, hip_w=0.82, sigil='x', hair='pony',
                headgear='band', chest='wrap', sash=True, boots=True, skirt='loin',
                weapon=W_('fan', 7, 0, rel=-15), weapon_b=W_('fan', 7, 0, rel=-25),
                bits=(B_('head', (-5.0, -4.6), n=3, seg=2.0, width=1.8, part='bitH', rest=118),
                      B_('head', (-5.8, -2.2), n=2, seg=2.2, width=1.2, part='bitT', rest=128)),
                groups={'skirt': 'cloth'}, ghost_group='cloth', ghost_style='spark',
                palette=pal(skin='F3D0B5', hair='pants', cloth=R('C8324A'), trim=R('F0C060'), pants=R('241A22', hi='3E2C38'),
                            helm='metal', metal=R('F6E8E0', sh='D8B8A8'), hilt='pants', fx=('FF5A7A', 'FFE27A', 'FFFFFF', 'F6E8E0')))

# Knight: steel great helm with a blue plume, round pauldrons, tassets, a two-handed greatsword resting on the shoulder.
KNIGHT = Body('knight', torso_w=12.5, waist=0.86, hip_w=0.90, limb=4, sigil='T', headgear='greathelm', face='slit', chest='plate',
              pads='round', skirt='tassets', boots=True, gauntlet=True, stance=1.3,
              weapon=W_('greatsword', 22, 4.0, rel=-50, width=3.4, grip2=3.0),
              bits=(B_('head', (-1.2, -7.8), n=3, seg=2.0, width=2.4, part='bitC', rest=165, lag=0.4),),
              groups={'cuff_f': 'helm', 'cuff_b': 'helm', 'shoe_f': 'helm', 'shoe_b': 'helm', 'boot_f': 'helm', 'boot_b': 'helm',
                      'skirt': 'helm', 'helm2': 'trim'},
              ghost_group='cloth',
              palette=pal(skin='helm', hair='pants', cloth=R('2E4C8C'), trim=R('D8B040'), pants=R('3A3F4C'), helm=R('8E98A8'),
                          metal=R('E8EEF6', sh='9CB4D4', hi2='FFFFFF'), hilt='pants', fx=('7FA8FF', 'FFE27A', 'FFFFFF', 'D0D6E0')))

# Barbarian: bare-chested, ginger spiky hair and beard, a red rag headband, fur pauldron and kilt, a one-handed axe.
BARBARIAN = Body('barbarian', thigh=10.5, shin=10.5, torso_w=13.5, waist=0.82, hip_w=0.86, limb=4, leg_add=2, upper=7.5, fore=7.5,
                 sigil='V', hair='spiky', headgear='rag', beard=True, chest='bare', pads='fur', skirt='kilt', boots=True, stance=1.35,
                 weapon=W_('axe', 17, 4.0, rel=-70),
                 groups={'torso': 'skin', 'arm_f_up': 'skin', 'arm_f_fo': 'skin', 'arm_b_up': 'skin', 'arm_b_fo': 'skin',
                         'pad_f': 'trim', 'pad_b': 'trim', 'skirt': 'trim', 'helm2': 'cloth', 'boot_f': 'trim', 'boot_b': 'trim'},
                 flats={'seam': ('skin', 'sh')}, ghost_group='cloth',
                 palette=pal(skin='D9A07A', hair=R('B0502A'), cloth=R('2E2A30'), trim=R('6B4A30'), pants='cloth', helm='cloth',
                             metal=R('A8B0BA', hi2='EEF2F6'), hilt='trim', fx=('FF6A3A', 'FFE27A', 'FFFFFF', 'FFC08A')))

# Monk: bald warrior monk in an orange robe with a gold sash and prayer beads, wrapped forearms, twin tonfa.
MONK = Body('monk', thigh=10.5, shin=10.5, torso=14.5, torso_w=11, waist=0.78, sigil='O', hair='bald', chest='gi', beads=True,
            sash=True, skirt='loin', sleeves='loose', gauntlet=True,
            weapon=W_('tonfa', 9, 2.5, rel=180, width=1.8), weapon_b=W_('tonfa', 9, 2.5, rel=180, width=1.8),
            groups={'cuff_f': 'paper', 'cuff_b': 'paper', 'skirt': 'cloth'}, ghost_group='trim',
            palette=pal(skin='C88A60', hair='skin', cloth=R('E07A1F'), trim=R('F2C14E'), pants=R('8C2A1C'), helm='trim',
                        metal=R('C0C4CC'), hilt=R('5A3A24'), shoe='hilt', paper='trim', fx=('FF8A2A', 'FFE27A', 'FFFFFF', 'F2C14E')))

# Nomad: desert wanderer in a sand turban and veil with a short turban tail, teal coat, twin chakrams.
NOMAD = Body('nomad', torso=14.5, torso_w=10, waist=0.70, sigil='Y', headgear='turban', face='mask', chest='wrap', sash=True,
             skirt='loin', boots=True, sleeves='loose',
             weapon=W_('chakram', 8, 0, rel=0), weapon_b=W_('chakram', 8, 0, rel=0),
             bits=(B_('head', (-5.8, -1.8), n=3, seg=2.0, width=1.6, part='bitC', rest=118),),
             groups={'mask': 'helm', 'bitC': 'helm', 'skirt': 'cloth'}, ghost_group='trim', ghost_style='streak',
             palette=pal(skin='B07850', hair='pants', cloth=R('2A9D8F'), trim=R('E9C46A'), pants=R('264653'), helm=R('F0D9A0'),
                         metal=R('E76F51'), hilt='pants', fx=('E76F51', 'FFE27A', 'FFFFFF', 'F0D9A0')))

# Oni: red-skinned brute with a white mane, ivory horns, glowing eyes, a tiger-stripe loincloth and an iron kanabo.
ONI = Body('oni', thigh=10, shin=10, torso=16, torso_w=16, waist=0.90, hip_w=0.94, limb=5, leg_add=2, upper=8, fore=8, head_w=12,
           head_h=11, foot_len=8, sigil='H', hair='wild', headgear='oni', face='glow', chest='bare', skirt='loin', gauntlet=True,
           stance=1.35, weapon=W_('kanabo', 22, 4.0, rel=-75, width=5.0, grip2=3.0),
           groups={'torso': 'skin', 'arm_f_up': 'skin', 'arm_f_fo': 'skin', 'arm_b_up': 'skin', 'arm_b_fo': 'skin', 'horn': 'hilt',
                   'skirt': 'trim', 'cuff_f': 'metal', 'cuff_b': 'metal'},
           flats={'lens': ('trim', 'hi'), 'seam': ('pants', 'base')}, ghost_group='trim',
           palette=pal(skin=R('C83C32'), hair=R('F0ECE4', sh='B8B0A8'), cloth='pants', trim=R('F2C230'), pants=R('3A2A26'), helm='trim',
                       metal=R('4A4A56', hi='7A7A88'), hilt=R('E8DCC0'), fx=('FF5030', 'FFE27A', 'FFFFFF', 'F2C230')))


# signature idle / victory per character (templates in moves.py)
STYLE = {'claude': dict(idle='ronin', victory='monk'), 'codex': dict(idle='shadow', victory='hacker'),
         'gemini': dict(idle='dancer', victory='ronin'), 'cursor': dict(idle='lancer', victory='pointer'),
         'ollama': dict(idle='mountain', victory='brawler'), 'lmstudio': dict(idle='samurai', victory='fistpump'),
         'generic': dict(idle='ranger', victory='agent'), 'kunoichi': dict(idle='fans', victory='ronin'),
         'knight': dict(idle='knight', victory='agent'), 'barbarian': dict(idle='berserk', victory='brawler'),
         'monk': dict(idle='tonfa', victory='monk'), 'nomad': dict(idle='nomad', victory='pointer'),
         'oni': dict(idle='oni', victory='brawler')}


def _c(name, display, tag, accent, body, strike, special, sup, projectile, ult=None, support=None):
    """ult = (move, template, desc, opts); support = (move, template, desc) for a helper row the ultimate references."""
    sig = {'strike': strike[0], 'special': special[0], 'super': sup[0]}
    moves = {strike[0]: strike[1:], special[0]: special[1:], sup[0]: sup[1:]}
    if ult:
        sig['ultimate'] = ult[0]
        opts = dict(ult[3])
        if support:
            opts['support'] = support[0]
            moves[support[0]] = (support[1], support[2], {})
        moves[ult[0]] = (ult[1], ult[2], opts)
    return Character(name, display, tag, accent, body, sig, moves, projectile, STYLE.get(name, {}))


ROSTER = {c.name: c for c in [
    _c('claude', 'Claude', '/reverse', '#F0A184', CLAUDE,
       ('spin_kick', 'spin', "Claude's signature spinning kick.", {}),
       ('slash_wave', 'throw', 'Throws a "/" slash wave across the taskbar. Costs nothing; looks cool.', {}),
       ('reverse', 'rewind', '"/reverse": rewinds to where it stood a second ago, dodging everything. Afterimage trail.',
        {'glyph': 'rewind'}),
       dict(style='arc', kind='slash_wave', cols=('cloth.base', 'cloth.hi', 'trim.base'), spark='fx.b'),
       ult=('radiant_beam', 'radiant_beam', 'Cups both hands at the hip, charges for a full second, then fires a horizontal beam the width of the taskbar.', {})),
    _c('codex', 'Codex', '$reverse', '#A99DFF', CODEX,
       ('ground_pound', 'pound', "Codex's heavy leaping slam with a ground shockwave.", {}),
       ('deploy', 'cast', 'Types a command and hits ENTER: fires a ">_" bolt across the taskbar.', {}),
       ('sudo', 'raise', '"$reverse": raises a giant $ and powers up with elevated permissions.', {'glyph': 'bigsigil'}),
       dict(style='term', kind='deploy_bolt', glyph='>_', cols=('ink.base', 'trim.base', 'trim.sh'), mark='fx.w', trail='fx.c'),
       ult=('spiral_orb', 'spiral_orb', 'Spins a sphere of energy in one hand, dashes in with afterimages and drives it home in a spiral burst.', {}),
       support=('mirror_images', 'mirror_images', 'Cross-finger hand sign: three dithered clones rush the opponent.')),
    _c('gemini', 'Gemini', '*gemini', '#7FA8F2', GEMINI,
       ('spin_kick', 'spin', "Gemini's spinning kick, both blades whipping round.", {}),
       ('star_shot', 'throw', 'Two-handed push that fires a "*" sparkle along the taskbar.', {}),
       ('twin_flash', 'rewind', 'Flash-steps back a second in time, leaving a sparkle and an afterimage trail.', {'glyph': 'bigglyph'}),
       dict(style='star', kind='star_shot', cols=('trim.hi', 'cloth.hi', 'cloth.base'), spark='fx.a'),
       ult=('crescent_fang', 'crescent_fang', 'Raises an arm, gathers energy and swings down a giant crescent slash wave.', {})),
    _c('cursor', 'Cursor', '>cursor', '#5FD3F3', CURSOR,
       ('ground_pound', 'pound', "Cursor's leaping slam with a ground shockwave.", {}),
       ('tab_bolt', 'cast', 'Accepts a suggestion and hits TAB: fires a ">|" caret bolt across the taskbar.', {}),
       ('autocomplete', 'raise', 'Raises a giant ">" and powers up: the whole line completes itself.', {'glyph': 'bigglyph'}),
       dict(style='term', kind='tab_bolt', glyph='>|', cols=('ink.base', 'cloth.hi', 'cloth.base'), mark='fx.a', trail='trim.sh'),
       ult=('grapple_strike', 'grapple_strike', 'Fires two grapple lines, zips across them and finishes with a spinning cross slash.', {})),
    _c('ollama', 'Ollama', 'ollama', '#E9E2D2', OLLAMA,
       ('ground_pound', 'pound', "Ollama's llama stomp with a ground shockwave.", {}),
       ('pull_shot', 'cast', '"ollama pull": hurls a wool-white orb across the taskbar.', {}),
       ('serve', 'raise', '"ollama serve": raises a giant "o" and powers up, local and unstoppable.', {'glyph': 'bigglyph'}),
       dict(style='orb', kind='pull_shot', cols=('cloth.ol', 'cloth.base', 'cloth.hi'), trail='fx.a'),
       ult=('gale_rend', 'gale_rend', 'Raises both arms, then slams down and rips three claws of energy along the ground.', {})),
    _c('lmstudio', 'LM Studio', 'lmstudio', '#7CF8EA', LMSTUDIO,
       ('spin_kick', 'spin', "LM Studio's spinning kick, the energy blade trailing.", {}),
       ('load_wave', 'throw', 'Loads a model and throws it as a teal-and-magenta wave across the taskbar.', {}),
       ('hot_swap', 'rewind', 'Hot-swaps back to where it stood a second ago, afterimage trail and a giant "L".', {'glyph': 'bigglyph'}),
       dict(style='arc', kind='load_wave', cols=('cloth.base', 'cloth.hi', 'trim.hi'), spark='trim.base'),
       ult=('awakening', 'awakening', 'Releases a pillar of aura, then lands three flash-step strikes faster than the eye.', {})),
    _c('generic', 'Agent', 'agent', '#E0C46C', GENERIC,
       ('spin_kick', 'spin', 'A spinning kick: every agent learns this one.', {}),
       ('energy_bolt', 'cast', 'Types a command and fires an energy orb across the taskbar.', {}),
       ('overclock', 'raise', 'Raises a giant "+" and powers up: everything runs faster.', {'glyph': 'bigglyph'}),
       dict(style='orb', kind='energy_bolt', cols=('trim.ol', 'trim.base', 'trim.hi'), trail='fx.a'),
       ult=('star_core', 'star_core', 'Raises both hands, gathers a huge slow ball of energy overhead and hurls it.', {})),
    _c('kunoichi', 'Kunoichi', 'kunoichi', '#FF5A7A', KUNOICHI,
       ('fan_whirl', 'spin', 'A spinning kick with both fans snapping open.', {}),
       ('petal_shot', 'throw', 'Sweeps a fan and sends a spinning blade-petal across the taskbar.', {}),
       ('vanish', 'rewind', 'Vanishes back a second in a swirl of petals, a giant "x" where she stood.', {'glyph': 'bigglyph'}),
       dict(style='star', kind='petal_shot', cols=('metal.hi', 'cloth.hi', 'cloth.base'), spark='trim.base'),
       ult=('petal_dance', 'awakening', 'A burst of crimson aura, then three flash-step fan cuts faster than the eye.', {})),
    _c('knight', 'Knight', 'knight', '#7FA8FF', KNIGHT,
       ('crusher', 'pound', 'Leaps and brings the greatsword down with a ground-shaking crash.', {}),
       ('sword_wave', 'throw', 'A two-handed sweep that sends a steel wave across the taskbar.', {}),
       ('valor', 'raise', 'Raises the greatsword under a giant "T" and steels itself.', {'glyph': 'bigglyph'}),
       dict(style='arc', kind='sword_wave', cols=('metal.sh', 'metal.base', 'metal.hi'), spark='trim.hi'),
       ult=('holy_crescent', 'crescent_fang', 'Raises the greatsword, gathers light and cleaves a giant crescent down the taskbar.', {})),
    _c('barbarian', 'Barbarian', 'barbarian', '#FF8A4A', BARBARIAN,
       ('axe_spin', 'spin', 'A wild spinning kick, axe swinging round with it.', {}),
       ('axe_toss', 'cast', 'Hurls a spinning hand-axe across the taskbar.', {}),
       ('berserk', 'raise', 'Roars under a giant "V" and goes berserk.', {'glyph': 'bigglyph'}),
       dict(style='orb', kind='axe_toss', cols=('metal.ol', 'metal.base', 'metal.hi'), trail='fx.a'),
       ult=('earthsplitter', 'gale_rend', 'Raises the axe, then splits the ground with three tearing shock claws.', {})),
    _c('monk', 'Monk', 'monk', '#F2C14E', MONK,
       ('palm_crash', 'pound', 'Leaps and drives both tonfa into the ground.', {}),
       ('chi_bolt', 'cast', 'Thrusts a tonfa and fires a ball of chi across the taskbar.', {}),
       ('meditate', 'raise', 'Centres itself under a giant "O"; the aura flares.', {'glyph': 'bigglyph'}),
       dict(style='orb', kind='chi_bolt', cols=('trim.ol', 'trim.base', 'trim.hi'), trail='fx.a'),
       ult=('chi_sphere', 'star_core', 'Raises both tonfa, gathers a huge sphere of chi overhead and hurls it.', {})),
    _c('nomad', 'Nomad', 'nomad', '#2A9D8F', NOMAD,
       ('ring_spin', 'spin', 'A spinning kick, both chakrams whirling.', {}),
       ('chakram_throw', 'throw', 'Whips a chakram across the taskbar.', {}),
       ('mirage', 'rewind', 'Slips back a second like a heat mirage, a giant "Y" left behind.', {'glyph': 'bigglyph'}),
       dict(style='arc', kind='chakram_throw', cols=('metal.sh', 'metal.base', 'metal.hi'), spark='trim.hi'),
       ult=('ring_storm', 'grapple_strike', 'Throws two chakrams on lines, zips after them and finishes with a spinning cross cut.', {})),
    _c('oni', 'Oni', 'oni', '#E04A3A', ONI,
       ('club_slam', 'pound', 'Leaps and slams the kanabo into the ground.', {}),
       ('oni_fire', 'cast', 'Spits a ball of oni-fire across the taskbar.', {}),
       ('rampage', 'raise', 'Swells under a giant "H", eyes blazing.', {'glyph': 'bigglyph'}),
       dict(style='orb', kind='oni_fire', cols=('skin.ol', 'fx.a', 'fx.b'), trail='fx.a'),
       ult=('oni_roar', 'radiant_beam', 'Plants the kanabo, draws a breath for a full second and roars a beam of fire across the taskbar.', {})),
]}

NAMES = tuple(ROSTER)


def get(name) -> Character:
    """Character by name (a Character passes through)."""
    return name if isinstance(name, Character) else ROSTER[name]
