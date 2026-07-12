"""Bomberboy: single-player-vs-AI (or local 2-player) port of the 2014
Java original.

See README.md at the repo root for the source game, target hardware
(Fri3d Camp 2026 Badge), and scope notes.

Local 2-player uses the original's key split (arrows+Enter for player 1,
WASD+F for player 2) on whatever full keyboard is available -- the
desktop simulator's keyboard, or a Fri3d Communicator add-on's keyboard
on real hardware. Either way it's the same raw key events arriving
through the same LVGL input group, so this Activity doesn't need to
know or care which one is actually plugged in.
"""

import random

import lvgl as lv
from mpos import Activity, AudioManager, DisplayMetrics, TaskManager

import ai
import dj_addon
import led_indicator
from curtain import Curtain
from levels import LEVELS
from model import DOWN, Game, LEFT, RIGHT, UP
from network_play import (
    BROADCAST_MAC,
    FrameSynchronizer,
    EspNowLink,
    ack_packet,
    hello_packet,
    parse_packet,
    start_packet,
)
from render import BoardRenderer

HUD_HEIGHT = 20
AI_THINK_MS = 350
TICK_MS = 100

_P2_KEYS = {
    ord("w"): UP,
    ord("s"): DOWN,
    ord("a"): LEFT,
    ord("d"): RIGHT,
}
_P2_BOMB_KEY = ord("f")

# Shared with _on_dj_tick(): in remote mode, every local input source queues
# a network action instead of touching self.game directly, so both peers
# apply it on the same synchronized frame.
_DIRECTION_TO_NETWORK_ACTION = {UP: "U", DOWN: "D", LEFT: "L", RIGHT: "R"}

_APP_DIR = "/".join(__file__.replace("\\", "/").split("/")[:-1])


class Bomberboy(Activity):
    def onCreate(self):
        self.game = None
        self.renderer = None
        self.hud = None
        self.result_label = None
        self.tick_timer = None
        self.ai_timer = None
        self.dj_timer = None
        self.curtain = None
        self.two_player = False
        self.mode = "bot"
        self.level_index = None
        self.result_shown = False
        self.dj_input = dj_addon.DJInput.probe()
        self.network_link = None
        self.network_peer = None
        self.network_seed = None
        self.network_player_id = None
        self.network_sync = None
        self.network_running = False
        self.network_pairing = False
        self.network_time = 0
        self.network_silence = 0
        # Tracks whether the currently-shown screen is the main menu, so
        # onBackPressed() can always route back to it from any other screen
        # this Activity owns (pairing search, pairing error, in-game, result)
        # without having to infer "am I on the menu" from a combination of
        # other state -- that inference previously missed the case where
        # ESP-NOW fails to open during pairing (see _start_pairing()).
        self._on_menu = True
        self._show_menu()

    def _start_game_timers(self):
        if self.tick_timer is not None:
            return
        self.tick_timer = lv.timer_create(self._on_tick, TICK_MS, None)
        self.ai_timer = lv.timer_create(self._on_ai_tick, AI_THINK_MS, None)
        if self.dj_input is not None:
            self.dj_timer = lv.timer_create(self._on_dj_tick, dj_addon.REFRESH_MS, None)

    def _stop_game_timers(self):
        for attr in ("tick_timer", "ai_timer", "dj_timer"):
            timer = getattr(self, attr)
            if timer is not None:
                timer.delete()
                setattr(self, attr, None)

    def _show_menu(self):
        # Reaching the menu -- whether at startup, after backing out of a
        # match, or via the result screen's "Menu" button -- always means no
        # game should be ticking anymore, and no leftover curtain-wipe timer
        # should be able to fire against the screen this is about to
        # replace (its 30ms timer runs for ~300ms after a level starts, so
        # backing out fast enough used to leave it running past teardown).
        self._stop_game_timers()
        self._clear_curtain()
        self._on_menu = True
        screen = lv.obj()
        title = lv.label(screen)
        titles = {"bot": "Bomberboy - vs Bot", "local": "Bomberboy - Local", "remote": "Bomberboy - Remote"}
        title.set_text(titles[self.mode])
        title.align(lv.ALIGN.TOP_MID, 0, 8)

        bot_btn = lv.button(screen)
        lv.label(bot_btn).set_text("vs Bot")
        bot_btn.align(lv.ALIGN.TOP_MID, -92, 32)
        bot_btn.add_event_cb(lambda e: self._set_mode("bot"), lv.EVENT.CLICKED, None)

        two_p_btn = lv.button(screen)
        lv.label(two_p_btn).set_text("Local")
        two_p_btn.align(lv.ALIGN.TOP_MID, 0, 32)
        two_p_btn.add_event_cb(lambda e: self._set_mode("local"), lv.EVENT.CLICKED, None)

        remote_btn = lv.button(screen)
        lv.label(remote_btn).set_text("Remote")
        remote_btn.align(lv.ALIGN.TOP_MID, 92, 32)
        remote_btn.add_event_cb(lambda e: self._set_mode("remote"), lv.EVENT.CLICKED, None)

        # Mode buttons otherwise gave no feedback for which mode is active
        # beyond the title text up top -- mark the current one CHECKED so it
        # reads as visibly pressed/selected, matching the theme's built-in
        # checked-button style.
        mode_buttons = {"bot": bot_btn, "local": two_p_btn, "remote": remote_btn}
        for button in mode_buttons.values():
            button.add_flag(lv.obj.FLAG.CHECKABLE)
        mode_buttons[self.mode].add_state(lv.STATE.CHECKED)

        level_list = lv.list(screen)
        level_list.set_size(lv.pct(90), lv.pct(60))
        level_list.align(lv.ALIGN.BOTTOM_MID, 0, -4)
        for index, level_cls in enumerate(LEVELS):
            button = level_list.add_button(None, level_cls.name)
            button.add_event_cb(lambda e, i=index: self._start_level(i), lv.EVENT.CLICKED, None)

        self.setContentView(screen)

    def _set_mode(self, mode):
        self.mode = mode
        self.two_player = mode != "bot"
        self._show_menu()

    def _start_level(self, level_index):
        self._play("Select.wav")
        self.level_index = level_index
        if self.mode == "remote":
            self._start_pairing()
            return
        self._begin_game()

    def _begin_game(self, seed=None):
        # A fresh game may be starting while a previous one's timers are
        # still running (e.g. "Play Again" calls straight into this method
        # without going through _show_menu() first), so always stop-then-
        # start rather than assuming a clean slate.
        self._stop_game_timers()
        self._on_menu = False
        self.result_shown = False
        if self.mode == "remote":
            self.network_time = 0
            self.game = Game(LEVELS[self.level_index](), seed=seed, clock=lambda: self.network_time)
        else:
            self.game = Game(LEVELS[self.level_index]())

        screen = lv.obj()
        screen.set_style_pad_all(0, 0)

        self.hud = lv.label(screen)
        self.hud.align(lv.ALIGN.TOP_LEFT, 4, 2)

        self.renderer = BoardRenderer(screen, self.game)
        self.renderer.canvas.align(lv.ALIGN.TOP_MID, 0, HUD_HEIGHT)
        self.renderer.render(force=True)
        self._update_hud()

        self.game_screen = screen

        self.result_label = lv.label(screen)
        self.result_label.align(lv.ALIGN.CENTER, 0, -10)
        self.result_label.add_flag(lv.obj.FLAG.HIDDEN)

        lv.group_get_default().add_obj(screen)
        screen.add_event_cb(self._on_key, lv.EVENT.KEY, None)

        self.setContentView(screen)
        self._play("GameStart.wav")
        self._start_game_timers()

        # Curtain-wipe reveal, ported from the Qt attempt's curtain.cpp --
        # the only fully-working piece of UI polish in that repo.
        self.curtain = Curtain(screen, DisplayMetrics.width(), DisplayMetrics.height())
        self.curtain.open(on_done=self._clear_curtain)

        if self.mode == "remote":
            self.network_pairing = False
            self.network_running = True
            self.network_sync = FrameSynchronizer(self.network_player_id)
            self.network_silence = 0
            TaskManager.create_task(self._network_game_loop())

    def _start_pairing(self):
        self._close_network()
        self._on_menu = False
        screen = lv.obj()
        label = lv.label(screen)
        label.set_text("Looking for another badge...")
        label.center()
        self.network_status = label
        self.setContentView(screen)
        try:
            self.network_link = EspNowLink()
            self.network_link.open()
        except Exception as error:
            label.set_text("ESP-NOW unavailable\n%s" % error)
            return
        self.network_pairing = True
        self.network_peer = None
        self.network_seed = None
        TaskManager.create_task(self.network_link.receive_loop(self._on_network_message))
        TaskManager.create_task(self._pairing_loop())

    async def _pairing_loop(self):
        attempts = 0
        while self.network_pairing and self.network_link is not None:
            try:
                await self.network_link.send(BROADCAST_MAC, hello_packet(self.level_index))
                if self.network_peer is not None and self.network_player_id == 1:
                    await self.network_link.send(
                        self.network_peer, start_packet(self.level_index, self.network_seed)
                    )
            except Exception:
                pass
            attempts += 1
            if attempts == 30 and self.network_peer is None and self.has_foreground():
                self.network_status.set_text("No badge found. Still looking...")
            await TaskManager.sleep_ms(500)

    def _on_network_message(self, mac, message):
        # This callback can fire from receive_loop() at any time, including
        # right after the OS backgrounds the whole Activity but before that
        # loop has noticed network_running/network_pairing went False --
        # don't touch UI or start a game on a screen that isn't showing.
        if not self.has_foreground():
            return
        if mac is None:
            self._network_failed("ESP-NOW receive failed")
            return
        parsed = parse_packet(message)
        if parsed is None:
            return
        if self.network_pairing:
            self._handle_pairing_message(mac, parsed)
        elif self.network_running and mac == self.network_peer and parsed[0] == "S":
            if parsed[2] == self.network_seed:
                TaskManager.create_task(self.network_link.send(mac, ack_packet(self.network_seed)))
        elif self.network_running and mac == self.network_peer and parsed[0] == "F":
            if self.network_sync.receive(message):
                self.network_silence = 0

    def _handle_pairing_message(self, mac, parsed):
        kind = parsed[0]
        if kind == "H":
            if mac == self.network_link.local_mac:
                return
            if self.network_peer is None or mac < self.network_peer:
                self.network_peer = mac
            if mac != self.network_peer:
                return
            self.network_link.add_peer(mac)
            if self.network_link.local_mac < mac:
                self.network_player_id = 1
                if self.network_seed is None:
                    self.network_seed = random.getrandbits(32)
                self.network_status.set_text("Found peer. Starting match...")
            else:
                self.network_player_id = 2
                self.network_status.set_text("Found peer. Waiting for host...")
        elif kind == "S" and self.network_player_id == 2 and mac == self.network_peer:
            _, level_index, seed = parsed
            self.level_index = level_index
            self.network_seed = seed
            self.network_pairing = False
            TaskManager.create_task(self._ack_and_start())
        elif kind == "A" and self.network_player_id == 1 and mac == self.network_peer:
            if parsed[1] == self.network_seed:
                self._begin_game(seed=self.network_seed)

    async def _ack_and_start(self):
        try:
            await self.network_link.send(self.network_peer, ack_packet(self.network_seed))
            if self.has_foreground():
                self._begin_game(seed=self.network_seed)
        except Exception:
            self._network_failed("Could not start remote match")

    async def _network_game_loop(self):
        while self.network_running and self.game is not None and not self.game.game_over:
            try:
                await self.network_link.send(self.network_peer, self.network_sync.frame_packet())
            except Exception:
                self.network_silence += 1
            if not self.has_foreground():
                break
            actions = self.network_sync.pop_ready()
            if actions is not None:
                self._apply_network_action(self.game.players[0], actions[0])
                self._apply_network_action(self.game.players[1], actions[1])
                self.network_time += TICK_MS
                self.game.tick()
                self._refresh()
                if self.game.game_over:
                    self._show_result()
                    break
            else:
                self.network_silence += 1
                if self.network_silence >= 100:
                    self._network_failed("Peer disconnected")
                    break
            await TaskManager.sleep_ms(50)

    def _apply_network_action(self, player, action):
        directions = {"U": UP, "D": DOWN, "L": LEFT, "R": RIGHT}
        if action in directions:
            self.game.move_player(player, directions[action])
        elif action == "B" and self.game.place_bomb(player):
            self._play("BombDrop.wav")

    def _network_failed(self, text):
        self.network_running = False
        self.network_pairing = False
        if not self.has_foreground():
            return
        if self.game is not None and self.result_label is not None:
            self.result_label.set_text(text)
            self.result_label.remove_flag(lv.obj.FLAG.HIDDEN)
        elif hasattr(self, "network_status"):
            self.network_status.set_text(text)

    def _close_network(self):
        self.network_running = False
        self.network_pairing = False
        if self.network_link is not None:
            self.network_link.close()
        self.network_link = None

    def _clear_curtain(self):
        if self.curtain is not None:
            self.curtain.delete()
            self.curtain = None

    def onResume(self, screen):
        super().onResume(screen)
        # Only relevant when the whole Activity was backgrounded by the OS
        # mid-game (onPause already tore the timers down in that case) and
        # is now regaining focus -- _begin_game() itself starts the timers
        # for a normal game start, so this would otherwise be a no-op.
        if self.game is not None:
            self._start_game_timers()

    def onPause(self, screen):
        super().onPause(screen)
        self._stop_game_timers()
        self._clear_curtain()
        led_indicator.clear()
        self._close_network()

    def onBackPressed(self, screen):
        # Any screen this Activity shows other than the main menu -- pairing
        # search, pairing failure, mid-game, or the post-game-over result
        # screen -- backs out to the menu the same way. Only the menu itself
        # falls through to the default (exit/background) behavior. This used
        # to be inferred from network_pairing/game state instead of tracked
        # explicitly, which missed the case where ESP-NOW fails to even open
        # during pairing: network_pairing was never set True and game was
        # never set, so back silently did nothing useful on that screen.
        if self._on_menu:
            return super().onBackPressed(screen)
        self.game = None
        self._close_network()
        led_indicator.clear()
        self._show_menu()
        return True

    def _on_key(self, event):
        if self.game is None or self.game.game_over:
            return
        key = event.get_key()
        if self.mode == "remote":
            actions = {
                lv.KEY.LEFT: "L",
                lv.KEY.RIGHT: "R",
                lv.KEY.UP: "U",
                lv.KEY.DOWN: "D",
                lv.KEY.ENTER: "B",
                0x20: "B",
            }
            action = actions.get(key)
            if action is not None:
                self.network_sync.queue(action)
            return
        if key == lv.KEY.LEFT:
            self._apply_player_action(0, "move", LEFT)
        elif key == lv.KEY.RIGHT:
            self._apply_player_action(0, "move", RIGHT)
        elif key == lv.KEY.UP:
            self._apply_player_action(0, "move", UP)
        elif key == lv.KEY.DOWN:
            self._apply_player_action(0, "move", DOWN)
        elif key in (lv.KEY.ENTER, 0x20):
            self._apply_player_action(0, "bomb")
        elif self.two_player and key in _P2_KEYS:
            self._apply_player_action(1, "move", _P2_KEYS[key])
        elif self.two_player and key == _P2_BOMB_KEY:
            self._apply_player_action(1, "bomb")

    def _apply_player_action(self, player_index, kind, direction=None):
        if self.game is None or self.game.game_over:
            return
        if player_index >= len(self.game.players):
            return
        if player_index == 1 and not self.two_player:
            return
        player = self.game.players[player_index]
        if kind == "move" and direction is not None:
            if self.game.move_player(player, direction):
                self._refresh()
        elif kind == "bomb":
            if self.game.place_bomb(player):
                self._play("BombDrop.wav")
                self._refresh()

    def _on_dj_tick(self, timer):
        if self.dj_input is None or self.game is None or self.game.game_over:
            return
        for player_index, kind, direction in self.dj_input.read_actions():
            if self.mode == "remote":
                # Route through the same synchronized-frame protocol as
                # keyboard input in _on_key() -- calling
                # _apply_player_action() here would mutate self.game
                # immediately and desync the two peers' simulations, since
                # remote mode is only supposed to advance via
                # _network_game_loop() applying actions both sides agreed on.
                action = "B" if kind == "bomb" else _DIRECTION_TO_NETWORK_ACTION.get(direction)
                if action is not None:
                    self.network_sync.queue(action)
            else:
                self._apply_player_action(player_index, kind, direction)

    def _on_tick(self, timer):
        if self.game is None or self.mode == "remote":
            return
        bombs_before = len(self.game.bombs)
        lives_before = {p.player_id: p.lives for p in self.game.players}
        self.game.tick()
        if len(self.game.bombs) < bombs_before:
            self._play("BombeExplode.wav")
        for player in self.game.players:
            if player.lives < lives_before[player.player_id]:
                self._play("Die.wav" if player.is_dead else "Warning.wav")
        self._refresh()
        if self.game.game_over:
            self._show_result()

    def _on_ai_tick(self, timer):
        if self.game is None or self.game.game_over or self.two_player:
            return
        bot, opponent = self.game.players[1], self.game.players[0]
        action = ai.choose_action(self.game, bot, opponent)
        if action is None:
            return
        if action[0] == "move":
            self.game.move_player(bot, action[1])
        elif action[0] == "bomb" and self.game.place_bomb(bot):
            self._play("BombDrop.wav")
        self._refresh()

    def _refresh(self):
        self.renderer.render()
        self._update_hud()

    def _update_hud(self):
        p1, p2 = self.game.players
        led_indicator.update(p1.lives, p1.MAX_LIVES, p2.lives, p2.MAX_LIVES)
        if self.mode == "remote":
            p1_label = "You" if self.network_player_id == 1 else "Peer"
            p2_label = "You" if self.network_player_id == 2 else "Peer"
        else:
            p1_label = "P1" if self.two_player else "You"
            p2_label = "P2" if self.two_player else "Bot"
        self.hud.set_text(
            "%s: %d lives, %d bombs, flame %d   %s: %d lives, %d bombs, flame %d"
            % (p1_label, p1.lives, p1.bombs_available, p1.flame_range, p2_label, p2.lives, p2.bombs_available, p2.flame_range)
        )

    def _show_result(self):
        # The tick timer keeps running until the whole Activity pauses, not
        # just until the match ends, so _on_tick() calls this every 100ms
        # for as long as the result screen is showing -- guard against
        # rebuilding the buttons below every time.
        if self.result_shown:
            return
        self.result_shown = True

        p1, p2 = self.game.players
        if self.mode == "remote":
            local_player = self.game.players[self.network_player_id - 1]
            if self.game.winner is None:
                text = "Draw."
            else:
                text = "You win!" if self.game.winner is local_player else "Peer wins."
        elif self.game.winner is p1:
            text = "Player 1 wins!" if self.two_player else "You win!"
            self._play("Life.wav")
        elif self.game.winner is p2:
            text = "Player 2 wins!" if self.two_player else "The bot wins."
        else:
            text = "Draw."
        self.result_label.set_text(text)
        self.result_label.remove_flag(lv.obj.FLAG.HIDDEN)

        restart_btn = lv.button(self.game_screen)
        # In remote mode, _start_level() below re-triggers _start_pairing()
        # -- a fresh ESP-NOW discovery, not an instant rematch, and it only
        # succeeds if the peer badge also backs out to pairing around the
        # same time. "Play Again" reads as "instantly restart," which isn't
        # what happens here, so label it to set the right expectation.
        restart_btn_label = "Rematch" if self.mode == "remote" else "Play Again"
        lv.label(restart_btn).set_text(restart_btn_label)
        restart_btn.align(lv.ALIGN.CENTER, 0, 30)
        restart_btn.add_event_cb(lambda e: self._start_level(self.level_index), lv.EVENT.CLICKED, None)

        menu_btn = lv.button(self.game_screen)
        lv.label(menu_btn).set_text("Menu")
        menu_btn.align(lv.ALIGN.CENTER, 0, 74)
        menu_btn.add_event_cb(lambda e: (self._close_network(), self._show_menu()), lv.EVENT.CLICKED, None)

        if self.mode == "remote":
            self._close_network()

    def _play(self, filename):
        try:
            player = AudioManager.player(
                file_path=_APP_DIR + "/sounds/" + filename,
                stream_type=AudioManager.STREAM_NOTIFICATION,
            )
            player.start()
        except Exception:
            pass
