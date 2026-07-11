# Bomberboy

A MicroPythonOS port of [Bomberboy](https://github.com/tjorim/bomberboy-java),
a 2-player Bomberman clone originally written in Java (AWT/BlueJ) in 2014 by
Willem Vansimpsen and Jorim Tielemans (that repo was originally just
`bomberboy`, renamed to `bomberboy-java` for consistency once `-qt`, `-gba`,
and `-mpos` ports existed alongside it). The pixel art is reused from a later,
semi-working [Game Boy Advance port](https://github.com/tjorim/bomberboy-gba)
of the same game (2019, in a repo similarly renamed from `gba-sprite-engine`
to `bomberboy-gba`) — see "Where the art comes from" below.

This port targets the [Fri3d Camp 2026 Badge](https://fri3dcamp.github.io/badge_2026/)
running [MicroPythonOS](https://github.com/MicroPythonOS/MicroPythonOS), and
runs identically on MicroPythonOS's desktop simulator (same 320x240
resolution).

## What changed from the original

The original was real-time local 2-player on one keyboard (arrow keys +
space vs. the numpad). A bare badge only has a single joystick, so the
default mode is **single-player vs. a bot** instead — see `ai.py` for the
opponent, which didn't exist in the original.

Real local 2-player is back, though, whenever a full keyboard is available:
pick "2 Player" from the main menu to use the original's key split (arrows +
Enter for player 1, WASD + F for player 2). This works on the desktop
simulator out of the box, and on real hardware if a
[Communicator add-on](https://fri3dcamp.github.io/badge_2026/en/communicator/)
is attached — MicroPythonOS auto-detects it at boot and registers its
keyboard as just another input source, so `bomberboy.py` doesn't need to
know or care which keyboard the key events are actually coming from.

The board is also redesigned smaller (15x11 tiles at 20px instead of the
original's 21x15 at 40px) to fit the badge's 320x240 screen, though it's
built from the same even-coordinate "pillar" maze algorithm as the original.

The arena-shrink mechanic is in: 2 minutes after a game starts, walls spiral
in from the border every 400ms, same as `Animator.java`'s
`horizontaleMuur()`/`verticaleMuur()` -- a player caught by the closing
arena dies instantly, no wall placed that step (`Game._shrink_place_or_kill`
in `model.py`). The AWT level-picker GUI is still a simple list rather than
a literal port (that was a deliberate simplification, not a gap), but the
one real functional loss from dropping it -- the always-available restart
button -- is back: "Play Again"/"Menu" on the result screen
(`Bomberboy._show_result`).

`KICKER` turned out not to be dead after all, just disconnected: the
original set a `magKicken`/`kanKicken` flag that nothing ever read for
behavior distinct from `SHIFTER` (bomb-pushing), so the first pass of this
port merged the two. They're split again now, with an actual distinct
mechanic: `SHIFTER` pushes a bomb one tile and the player follows, `KICKER`
sends it rolling continuously in that direction until it hits something
(wall, crate, another bomb, a player, a portal) -- classic Bomberman kick,
new code, not something the original ever had working. If a player has
both, kick takes priority. The roster is back to all 7 original powerups.

## Where the art comes from

The tile/character art isn't hand-drawn for this port — it's decoded from
the grit-exported GBA sprite headers in
[tjorim/bomberboy-gba](https://github.com/tjorim/bomberboy-gba)'s
`bomberboy/sprites/` directory (walls, crates, gunpowder, bombs, both
portals, all 7 powerups, and both players in all 4 facings + a death pose),
which itself was the Java original's art run through Cearn's GBA Image
Transmogrifier. `scripts/convert_gba_sprites.py` decodes the 8bpp
tiles + shared palette into `bomberboy/original_sprites.py`
(native 8x8/8x16 resolution, baked in as plain data — no image decoding
needed on-device); `sprites.py` nearest-neighbor upscales it to this port's
20x20 tile size at draw time. Floor and the fire/explosion overlay have no
equivalent in that source (that port never got around to converting them),
so those two stay procedurally generated.

The GBA port happens to have exactly 2 distinct portal sprites, which is
exactly what's needed to give each linked *pair* its own color in this
port's two-portal-pair level (see below) — both ends of the same pair look
identical, a different pair gets a different look
(`sprites.portal_sprite`, keyed by pair).

To regenerate `original_sprites.py` from a fresh checkout of that repo:

```sh
python scripts/convert_gba_sprites.py /path/to/bomberboy-gba
```

## Also cross-pollinated from a third attempt

There's a third, even-less-finished Bomberboy attempt,
[tjorim/bomberboy-qt](https://github.com/tjorim/bomberboy-qt) (C++/Qt,
never got explosions to actually apply damage or portals to actually
teleport). Two things from it were worth carrying over on their own merits:

- **The level-start curtain-wipe** (`curtain.py`): two panels slide apart to
  reveal the board. Ported from `curtain/curtain.cpp`, the one piece of that
  repo that was actually complete and working — simplified from 4 small
  rects per side down to 1, which reads fine at this screen size.
- **A second portal pair in the Portals level** (`levels.PortalMazeLevel`):
  this port's Portals level now has two independent linked pairs, one in
  each pair of opposite corners, matching `bomberboy-qt`'s
  `ThingBoard::level3()` (which placed four portals the same way, but —
  like most of that repo — never wired up what happens when you actually
  walk into one). The concept itself, though, turns out to already have
  been sketched into the *Java original's* `Portaal` class: it has always
  had both a `portaalNr` (which pair) and a `poortNr` (which end of a
  pair) field. `portaalNr` was just never actually wired up -- its
  constructor took no `portaalNr` parameter, so `this.portaalNr =
  portaalNr` was a silent self-assignment that left it at `0` forever
  (fixed upstream in
  [tjorim/bomberboy-java#3](https://github.com/tjorim/bomberboy-java/pull/3)), and
  `Model.java` only ever instantiated one pair regardless. So: the
  original already had the data model for this, `bomberboy-qt` is where a
  concrete second-pair *level layout* using it was found, and this port is
  what actually finishes wiring it end to end. Portal color identifies
  the *pair* (`sprites.portal_sprite`, keyed by `portal_id // 2`), not
  which end of it you're standing at — both ends of one pair look
  identical, matching the same fix applied upstream. The source art
  happens to have exactly 2 distinct portal sprites, which is exactly
  enough for 2 pairs with no extra work.

## Layout

- `bomberboy/` — the MicroPythonOS app itself.
  - `model.py`, `levels.py`, `ai.py` — pure Python game logic, no `lv`/`mpos`
    imports, runnable and testable under plain CPython.
  - `original_sprites.py` — decoded GBA pixel art data (see above).
  - `sprites.py`, `render.py`, `curtain.py`, `bomberboy.py` — the LVGL-facing
    UI, the Activity entrypoint, input handling, audio, and the game/AI loop
    timers.
  - `sounds/` — original `.wav` sound effects, reused as-is.
- `tests/` — `unittest`-based tests for the game logic (see below).
- `scripts/dev-setup.md` — how to run this app against a MicroPythonOS
  checkout for manual testing.
- `scripts/convert_gba_sprites.py` — regenerates `original_sprites.py`.

## Running the tests

```sh
python -m unittest discover tests
```

No LVGL, MicroPython, or hardware required — `model.py`/`levels.py`/`ai.py`
are plain Python.

## Trying it out

See `scripts/dev-setup.md` for running the actual app (with LVGL UI, input,
and audio) against MicroPythonOS's desktop simulator.
