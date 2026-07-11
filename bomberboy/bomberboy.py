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

import lvgl as lv
from mpos import Activity, AudioManager, DisplayMetrics

import ai
import dj_addon
import led_indicator
from curtain import Curtain
from levels import LEVELS
from model import DOWN, Game, LEFT, RIGHT, UP
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
        self.level_index = None
        self.result_shown = False
        self.dj_input = dj_addon.DJInput.probe()
        self._show_menu()

    def _show_menu(self):
        screen = lv.obj()
        title = lv.label(screen)
        title.set_text("Bomberboy - 2 Player" if self.two_player else "Bomberboy - vs Bot")
        title.align(lv.ALIGN.TOP_MID, 0, 8)

        bot_btn = lv.button(screen)
        lv.label(bot_btn).set_text("vs Bot")
        bot_btn.align(lv.ALIGN.TOP_MID, -50, 32)
        bot_btn.add_event_cb(lambda e: self._set_mode(False), lv.EVENT.CLICKED, None)

        two_p_btn = lv.button(screen)
        lv.label(two_p_btn).set_text("2 Player")
        two_p_btn.align(lv.ALIGN.TOP_MID, 50, 32)
        two_p_btn.add_event_cb(lambda e: self._set_mode(True), lv.EVENT.CLICKED, None)

        level_list = lv.list(screen)
        level_list.set_size(lv.pct(90), lv.pct(60))
        level_list.align(lv.ALIGN.BOTTOM_MID, 0, -4)
        for index, level_cls in enumerate(LEVELS):
            button = level_list.add_button(None, level_cls.name)
            button.add_event_cb(lambda e, i=index: self._start_level(i), lv.EVENT.CLICKED, None)

        self.setContentView(screen)

    def _set_mode(self, two_player):
        self.two_player = two_player
        self._show_menu()

    def _start_level(self, level_index):
        self._play("Select.wav")
        self.level_index = level_index
        self.result_shown = False
        self.game = Game(LEVELS[level_index]())

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

        # Curtain-wipe reveal, ported from the Qt attempt's curtain.cpp --
        # the only fully-working piece of UI polish in that repo.
        self.curtain = Curtain(screen, DisplayMetrics.width(), DisplayMetrics.height())
        self.curtain.open(on_done=self._clear_curtain)

    def _clear_curtain(self):
        if self.curtain is not None:
            self.curtain.delete()
            self.curtain = None

    def onResume(self, screen):
        super().onResume(screen)
        if self.game is not None and self.tick_timer is None:
            self.tick_timer = lv.timer_create(self._on_tick, TICK_MS, None)
            self.ai_timer = lv.timer_create(self._on_ai_tick, AI_THINK_MS, None)
            if self.dj_input is not None:
                self.dj_timer = lv.timer_create(self._on_dj_tick, dj_addon.REFRESH_MS, None)

    def onPause(self, screen):
        super().onPause(screen)
        for attr in ("tick_timer", "ai_timer", "dj_timer"):
            timer = getattr(self, attr)
            if timer is not None:
                timer.delete()
                setattr(self, attr, None)
        self._clear_curtain()
        led_indicator.clear()

    def onBackPressed(self, screen):
        # Handles both mid-game (abandon the match) and the post-game-over
        # result screen (go pick something else) the same way.
        if self.game is not None:
            self.game = None
            led_indicator.clear()
            self._show_menu()
            return True
        return super().onBackPressed(screen)

    def _on_key(self, event):
        if self.game is None or self.game.game_over:
            return
        key = event.get_key()
        human = self.game.players[0]
        moved = False
        if key == lv.KEY.LEFT:
            moved = self.game.move_player(human, LEFT)
        elif key == lv.KEY.RIGHT:
            moved = self.game.move_player(human, RIGHT)
        elif key == lv.KEY.UP:
            moved = self.game.move_player(human, UP)
        elif key == lv.KEY.DOWN:
            moved = self.game.move_player(human, DOWN)
        elif key in (lv.KEY.ENTER, 0x20):
            self._apply_player_action(0, "bomb")
        elif self.two_player and key in _P2_KEYS:
            moved = self.game.move_player(self.game.players[1], _P2_KEYS[key])
        elif self.two_player and key == _P2_BOMB_KEY:
            self._apply_player_action(1, "bomb")
        if moved:
            self._refresh()

    def _apply_player_action(self, player_index, kind, direction=None):
        if self.game is None or self.game.game_over:
            return
        if player_index >= len(self.game.players):
            return
        if player_index == 1 and not self.two_player:
            return
        player = self.game.players[player_index]
        if kind == "move":
            if self.game.move_player(player, direction):
                self._refresh()
        elif kind == "bomb":
            if self.game.place_bomb(player):
                self._play("BombDrop.wav")
                self._refresh()

    def _on_dj_tick(self, timer):
        if self.dj_input is None or self.game is None or self.game.game_over:
            return
        for player_index, kind, direction in self.dj_input.read_actions(two_player=self.two_player):
            self._apply_player_action(player_index, kind, direction)

    def _on_tick(self, timer):
        if self.game is None:
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
        if self.game.winner is p1:
            text = "Player 1 wins!" if self.two_player else "You win!"
            self._play("Life.wav")
        elif self.game.winner is p2:
            text = "Player 2 wins!" if self.two_player else "The bot wins."
        else:
            text = "Draw."
        self.result_label.set_text(text)
        self.result_label.remove_flag(lv.obj.FLAG.HIDDEN)

        restart_btn = lv.button(self.game_screen)
        lv.label(restart_btn).set_text("Play Again")
        restart_btn.align(lv.ALIGN.CENTER, 0, 30)
        restart_btn.add_event_cb(lambda e: self._start_level(self.level_index), lv.EVENT.CLICKED, None)

        menu_btn = lv.button(self.game_screen)
        lv.label(menu_btn).set_text("Menu")
        menu_btn.align(lv.ALIGN.CENTER, 0, 74)
        menu_btn.add_event_cb(lambda e: self._show_menu(), lv.EVENT.CLICKED, None)

    def _play(self, filename):
        try:
            player = AudioManager.player(
                file_path=_APP_DIR + "/sounds/" + filename,
                stream_type=AudioManager.STREAM_NOTIFICATION,
            )
            player.start()
        except Exception:
            pass
