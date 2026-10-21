# Community skin packs

A skin pack is a new look any program can wear: a folder (or a zip of it) with a small `pack.json` and the same sprite
sheets the built-in fighters use. Packs are **data only**. Taskbar Fighters reads their JSON with `json` and their PNGs with
Pillow; nothing in a pack is ever run, imported or opened by another program.

```
python minis.py packs list                        installed packs (and why an invalid one is refused)
python minis.py packs check <folder>              validate a pack you are making, without installing it
python minis.py packs install <pack.zip|folder>   validate, then copy into the packs folder   [--replace]
python minis.py packs remove <name>               delete an installed pack (only a folder holding a pack.json)
python minis.py skin <program> <pack>             wear it, e.g.  skin claude pack-shadow-ronin  (or its display name)
```

An installed pack also shows up in the fighter-select screen's LOOK grid and in a fighter's right-click *Look* menu.

**Where packs live:** `%LOCALAPPDATA%\minis\packs\<name>\` on Windows, `~/Library/Application Support/minis/packs/<name>/`
on macOS. A pack named `shadow-ronin` is the character `pack-shadow-ronin`.

## The format (version 1)

```
shadow-ronin/
  pack.json
  64/                          required: the 64 px set (RES 1)
    anim.json
    sheet.png                  right-facing frames
    sheet_l.png                left-facing frames
    sheet_unarmed.png          optional: the same frames without the held weapon (arena desktop weapons)
    sheet_unarmed_l.png        optional (both unarmed sheets or neither)
    proj.png                   optional: the special move's projectile strip
  128/                         optional: the same files at 128 px (RES 2); without it the 64 px art is scaled 2x
  LICENSE / LICENSE.txt / LICENSE.md     optional, recommended
  README.md                    optional
  preview.png                  optional
```

Nothing else is allowed: no other file, no other folder, no link. Any malformed shape (a move that is `null`, frames
that are not a list, ...) is refused with one plain reason; `packs check` / `install` never show a traceback.

### pack.json

```json
{
  "format": 1,
  "name": "shadow-ronin",
  "display": "Shadow Ronin",
  "author": "Your Name",
  "license": "CC-BY-4.0",
  "version": "1.0",
  "description": "A one-line description."
}
```

| key | rule |
| --- | --- |
| `format` | `1` |
| `name` | 2-32 characters, `a-z 0-9 _ -`, starting with a letter or digit; it must not be a built-in character's id, and the installed folder takes this name |
| `display` | up to 24 characters: the name in the select screen and the menus |
| `author`, `license` | required, up to 64 characters each. Use an SPDX id (`CC0-1.0`, `CC-BY-4.0`, `MIT`) and only art you have the right to share |
| `version`, `description` | optional, up to 16 / 200 characters |

### anim.json

The same schema as the built-in `assets/<character>/anim.json` (read `minis_core/atlas.py`, and the `schema_notes` block
inside any built-in anim.json). The validator checks:

- `res` is 1 in `64/` and 2 in `128/`; `cell` is `[64, 64]` / `[128, 128]`; `cols` is 1-12; `anchor` has `R` and `L` inside
  the cell; `ground_y` is inside the cell.
- `sheets` is exactly `{"R": "sheet.png", "L": "sheet_l.png"}`; `sheets_unarmed`, if present, exactly
  `{"R": "sheet_unarmed.png", "L": "sheet_unarmed_l.png"}`; `projectile.file`, if present, is `proj.png` and the strip is
  `w * frames` x `h`.
- Every move has a `row` (0-79) and 1-`cols` frames, each with `ms` 1-5000; move names are `a-z 0-9 _`; `signature` names
  only moves the pack has.
- **Every move of the shared move set is present** (the choreography may ask any fighter for them):
  air_hit, air_slash, backdash, block, block_hit, bow, clash, console, cross, crouch, crouch_block, dash, dizzy, facepalm,
  fistbump, getup, guard_break, guard_crush, handoff_give, handoff_take, highfive, hit, hit_back, hit_heavy, hit_high,
  hit_low, idle, idle_flourish, jab, jump, knockdown, ko, launched, low_kick, parry, powerup, pulled, rage, review, riposte,
  roundhouse, shrug, sleep, spike, spiked, taunt, taunt2, throw, thrown, thumbs_up, turn, type, uppercut, victory,
  victory2, wait, wake, walk, walk_back, wave, work. (The list is computed from the built-in fighters, so it grows if they do.)
- No top-level `fx` key: per-pack effect sheets are not part of version 1. A pack's moves use the shared effects (`fx`
  entries inside a move name shared effects; an unknown name falls back to a drawn placeholder).
- `64/` and `128/` have the same moves.

### Sheets

- PNG only (checked by signature and by Pillow), each file at most 4 MB, the whole pack at most 16 MB on disk.
- **Decoded size, checked from each PNG's header before anything is decoded:** a sheet at most 12 x 80 cells (1536 x
  10240 px at 128 px), `preview.png` at most 1200 x 1200 px, and every PNG of the pack together at most 256 MiB as RGBA
  (a pack with the built-in fighters' sizes at 64 and 128 px is about 180 MiB). A tiny file that would unpack into a huge
  image is refused without being opened.
- `sheet.png` and `sheet_l.png` (and the unarmed pair) are exactly `cols x cell` wide and `rows x cell` high, where `rows`
  is the highest `row` + 1.
- **At most 64 colours per sheet** (counting alpha), 32 for `proj.png`: these are pixel-art fighters. The built-in sheets
  use 24-42.
- Frame `i` of a move sits at column `i`, row `row`. The left sheet is the mirror image of the right one about the anchor.

### Zips

`packs install` accepts a zip of the pack folder (or of its contents). Every entry is checked before anything is written:
no absolute path, no drive letter, no `..`, no backslash, no link, no duplicate name, no encrypted entry, at most 48
entries, at most 16 MB unpacked, at most 4 MB and a compression ratio of 200:1 per entry. It is unpacked into a temporary
folder inside `packs/`, validated as above, and only then moved into place. A refused zip leaves nothing behind.

## A worked example

`tools/make_example_pack.py` builds a complete, valid pack from a built-in fighter by rotating the hue of its colours:

```
python tools/make_example_pack.py --from claude --name shadow-ronin --display "Shadow Ronin" --hue 200
python minis.py packs install qa/local/packs/shadow-ronin.zip
python minis.py skin claude "Shadow Ronin"
```

It writes `qa/local/packs/shadow-ronin/` and `shadow-ronin.zip` (about 4.3 MB with both sizes; `--no-hd` for the 64 px set
only), drops the `fx` key and the built-in palette notes from anim.json, writes `pack.json` and copies this repository's
licence (the art is the project's own, MIT), then runs the validator. Read its output files as the reference layout; to
make your own art, keep the cells, rows and frame counts and redraw the pixels.

## Codex pets

Importing a Codex pet (`python minis.py packs import-codex <path>`) is **not built**. Its pack format is not documented
anywhere this project can read offline, and converting a format we would have to guess could mis-read your files. The
command explains that and does nothing; it never looks in `~/.codex`. If the format gets a public description, an
importer would convert the pet's sheet into a pack folder as above and go through the same validator.
