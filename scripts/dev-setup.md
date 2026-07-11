# Running Bomberboy against MicroPythonOS

MicroPythonOS's native desktop build only runs on Linux, macOS, or WSL2 —
there's no native Windows build. On Windows, use WSL2.

## 1. Get MicroPythonOS

```sh
git clone --recurse-submodules https://github.com/MicroPythonOS/MicroPythonOS.git
cd MicroPythonOS
```

Download the prebuilt desktop binary from the project's GitHub releases and
place it at `lvgl_micropython/build/lvgl_micropy_unix` (Linux/WSL2) or
`lvgl_micropython/build/lvgl_micropy_macOS` (macOS), then:

```sh
chmod +x lvgl_micropython/build/lvgl_micropy_unix
```

## 2. Install this app

From this repo:

```sh
cp -r bomberboy /path/to/MicroPythonOS/internal_filesystem/apps/
```

`run_desktop.sh` runs directly against `internal_filesystem/`, so re-running
step 2 after edits (no rebuild) is all you need for the next iteration.

## 3. Run it

```sh
cd /path/to/MicroPythonOS
./scripts/run_desktop.sh bomberboy
```

Controls: arrow keys to move, Enter or Space to place a bomb (player 1,
always active). Pick "2 Player" on the main menu to also enable player 2:
WASD to move, F to place a bomb -- works immediately on desktop since a
regular keyboard has both key sets available at once.

## Things worth checking on first run

A few APIs in `bomberboy.py`/`render.py` were written from documentation and
example apps rather than run against a live MicroPythonOS instance, so
double-check these first:

- `lv.list.add_button(None, text)` — the `None` icon argument may need to be
  `""` or a `lv.SYMBOL.*` instead.
- The sound file path passed to `AudioManager.player(file_path=...)` —
  built from `__file__`'s directory; confirm it resolves correctly both on
  desktop and on-device.
- `lv.canvas` buffer size (300x220x4 bytes ~= 264KB) — fine on desktop and
  on ESP32-S3 with PSRAM, but worth confirming it doesn't blow LVGL's
  configured memory pool on your specific board.
- The mode-toggle buttons on the main menu, and the "Play Again"/"Menu"
  buttons on the result screen, use fixed pixel offsets (`.align(lv.ALIGN.
  CENTER, 0, 30)` etc.) rather than a layout container -- confirm they
  don't overlap the level list / result text or clip off narrower/
  differently-themed displays.
- Play a full match with the arena-shrink timer sped up (temporarily set
  `model.ARENA_SHRINK_START_MS` low in a REPL, or just wait 2 minutes) to
  confirm the spiral looks right and doesn't visually stutter at 100ms
  tick granularity.
- Pick up a KICKER powerup and kick a bomb into a wall, a crate, and
  another player to confirm the rolling animation reads clearly at 120ms/
  tile -- this is new gameplay feel that only really shows up with the
  actual renderer running, unlike the underlying logic (thoroughly unit
  tested in `tests/test_model.py`'s `ShiftAndKickTests`).

## On real hardware

Flash a Fri3d Camp 2026 Badge with MicroPythonOS, then install the app with
`mpremote.py` (bundled at
`MicroPythonOS/lvgl_micropython/lib/micropython/tools/mpremote/mpremote.py`):

```sh
mpremote.py mkdir :/apps
mpremote.py fs cp -r bomberboy/ :/apps/
```

The badge's joystick + A button already map to the arrow keys + Enter that
this app listens for (see `fri3d_2026_expander.py` in the MicroPythonOS
repo), so no extra input wiring should be needed for single-player.

For 2-player on real hardware, attach a
[Communicator add-on](https://fri3dcamp.github.io/badge_2026/en/communicator/).
MicroPythonOS's board init (`fri3d_2026.py`) auto-detects it over I2C at
boot and registers its keyboard (`fri3d_communicator_keyboard.py`) as a
regular LVGL indev in the same input group as the joystick -- no app-level
detection or wiring needed, it Just Works the same way the desktop
simulator's keyboard does.

As an accessibility alternative, the app also probes the Fri3d DJ Add-on at
startup and polls its eight large silicone buttons every 100ms when present.
The default mapping follows the existing DJ demo app's raw-to-pad order: the
left cluster acts as a player-1 D-pad, with large bomb buttons for player 1
and player 2 (the latter only in 2-player mode). Verify that this feels right
on a physical add-on before treating the mapping as final; it is isolated in
`bomberboy/dj_addon.py` for easy adjustment.
