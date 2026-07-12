"""Core Bomberboy game rules: grid, entities, movement, bombs, explosions.

Pure Python, no lv/mpos imports, so it can run under plain CPython (tests)
and MicroPython (on device) unchanged.

Ported from the original Java game (Model.java / Voorwerp hierarchy) at
github.com/tjorim/bomberboy-java, with two deliberate rule fixes made during
the port (see BOMB_BURN_MS docstring and Game._ignite_gunpowder_network):
the original decremented every player's life once per lit gunpowder tile
in a chain rather than once per hit, and applied damage on the same frame
the flame appeared rather than after it burns out.
"""

import time

WIDTH = 15
HEIGHT = 11

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
DELTA = {UP: (0, -1), DOWN: (0, 1), LEFT: (-1, 0), RIGHT: (1, 0)}

EXTRA_BOMB, MORE_FLAME, GOLDEN_FLAME, EXTRA_LIFE, SHIFTER, SPEED_UP, KICKER = range(7)
ALL_POWERS = (EXTRA_BOMB, MORE_FLAME, GOLDEN_FLAME, EXTRA_LIFE, SHIFTER, SPEED_UP, KICKER)

BOMB_FUSE_MS = 2000
# How long a bomb/crate/gunpowder/player stays "on fire" before the
# extinguish pass resolves it (crate destroyed, player damaged, etc).
BOMB_BURN_MS = 1000
# How often a kicked bomb advances one tile while it's rolling.
BOMB_ROLL_STEP_MS = 120

# The arena starts closing in with walls, spiraling inward from the
# border, this long after a game starts.
ARENA_SHRINK_START_MS = 120000
# ...one step of the spiral every this many ms.
ARENA_SHRINK_STEP_MS = 400


def _now_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _elapsed_ms(start, now=None):
    if now is None:
        now = _now_ms()
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(now, start)
    return now - start


class Floor:
    def is_walkable(self):
        return True

    def stops_flame(self):
        return False

    def is_breakable(self):
        return False


class Wall:
    def is_walkable(self):
        return False

    def stops_flame(self):
        return True

    def is_breakable(self):
        return False


class Crate:
    def is_walkable(self):
        return False

    def stops_flame(self):
        return True

    def is_breakable(self):
        return True


class Gunpowder:
    def is_walkable(self):
        return True

    def stops_flame(self):
        return False

    def is_breakable(self):
        return False


class Bomb:
    def __init__(self, owner, x, y, under, placed_at=None):
        self.owner = owner
        self.x = x
        self.y = y
        self.under = under
        self.placed_at = _now_ms() if placed_at is None else placed_at
        self.exploded = False
        # Direction (dx, dy) while a kicked bomb is rolling, else None.
        self.rolling = None
        self.last_roll_at = 0

    def is_walkable(self):
        return False

    def stops_flame(self):
        return False

    def is_breakable(self):
        return False


class PowerUp:
    def __init__(self, kind):
        self.kind = kind
        self.revealed = False

    def is_walkable(self):
        return self.revealed

    def stops_flame(self):
        return True

    def is_breakable(self):
        return True


class Portal:
    def __init__(self, x, y, portal_id=0):
        self.x = x
        self.y = y
        self.portal_id = portal_id
        self.other = None
        self.occupied = False

    def is_walkable(self):
        return not self.occupied

    def stops_flame(self):
        return True

    def is_breakable(self):
        return False


class Player:
    MAX_BOMBS = 6
    MAX_LIVES = 3
    MAX_SPEED = 6

    def __init__(self, player_id, x, y, max_flame):
        self.player_id = player_id
        self.x = x
        self.y = y
        self.facing = DOWN
        self.lives = self.MAX_LIVES
        self.bombs_available = 1
        self.flame_range = 1
        self.max_flame = max_flame
        self.speed = 1
        self.can_shift = False
        self.can_kick = False
        self.on_fire = False
        self.standing_on = None

    def is_walkable(self):
        return True

    def stops_flame(self):
        return False

    def is_breakable(self):
        return False

    @property
    def is_dead(self):
        return self.lives <= 0

    def hit(self):
        self.lives = max(0, self.lives - 1)

    def add_life(self):
        self.lives = min(self.MAX_LIVES, self.lives + 1)

    def add_bomb(self):
        self.bombs_available = min(self.MAX_BOMBS, self.bombs_available + 1)

    def add_flame(self, amount=1):
        self.flame_range = min(self.max_flame, self.flame_range + amount)

    def add_speed(self):
        self.speed = min(self.MAX_SPEED, self.speed + 1)


class Game:
    def __init__(self, level, seed=None, clock=None):
        self.width = level.width
        self.height = level.height
        self.seed = seed
        self.grid = level.build_grid(seed=seed)
        self.players = level.place_players(self.grid)
        self.portals = level.portals
        self.bombs = []
        self._burning = []  # list of dicts: {"x","y","expire_at"}
        self.game_over = False
        self.winner = None
        self._clock = clock or _now_ms
        self._start_time = self._clock()
        self._shrink_started = False
        self._shrink_last_step = 0
        self._shrink_i = 1
        self._shrink_j = 1
        self._shrink_k = 2
        self._shrink_horizontal = True

    def tile_at(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.grid[x][y]
        return None

    def is_burning(self, x, y):
        for entry in self._burning:
            if entry["kind"] == "tile" and entry["x"] == x and entry["y"] == y:
                return True
        return False

    def burning_tile_positions(self):
        return {(entry["x"], entry["y"]) for entry in self._burning if entry["kind"] == "tile"}

    def set_tile(self, x, y, tile):
        self.grid[x][y] = tile

    def other_players(self, player):
        return [p for p in self.players if p is not player]

    def player_at(self, x, y, exclude=None):
        for p in self.players:
            if p is not exclude and p.x == x and p.y == y and not p.is_dead:
                return p
        return None

    # -- movement -----------------------------------------------------

    def move_player(self, player, direction):
        if player.is_dead or player.on_fire or self.game_over:
            return False
        player.facing = direction
        dx, dy = DELTA[direction]
        tx, ty = player.x + dx, player.y + dy
        target = self.tile_at(tx, ty)
        if target is None:
            return False

        if isinstance(target, Bomb):
            # Kick (classic Bomberman): the bomb rolls away on its own,
            # the player stays put. Shift: a single push, and the player
            # follows into the tile the bomb just vacated -- which may not
            # be plain floor (e.g. gunpowder), so use whatever
            # _move_bomb_one_tile actually restored there rather than
            # assuming. Kick takes priority if the player has both.
            if player.can_kick and self._kick_bomb(target, dx, dy):
                return True
            if player.can_shift:
                restored = self._move_bomb_one_tile(target, dx, dy)
                if restored is not None:
                    self._enter_tile(player, tx, ty, restored)
                    return True
            return False

        occupant = self.player_at(tx, ty, exclude=player)
        if occupant is not None:
            return self._swap_players(player, occupant)

        if not target.is_walkable():
            return False

        if isinstance(target, PowerUp):
            self._apply_powerup(player, target.kind)
            self._enter_tile(player, tx, ty, Floor())
            return True
        if isinstance(target, Portal):
            self._use_portal(player, target)
            return True

        self._enter_tile(player, tx, ty, target)
        return True

    def _enter_tile(self, player, x, y, tile_left_behind):
        self.set_tile(player.x, player.y, player.standing_on or Floor())
        player.standing_on = tile_left_behind
        player.x, player.y = x, y
        self.set_tile(x, y, player)

    def _swap_players(self, player, occupant):
        px, py = player.x, player.y
        ox, oy = occupant.x, occupant.y
        p_under, o_under = player.standing_on or Floor(), occupant.standing_on or Floor()
        self.set_tile(px, py, occupant)
        self.set_tile(ox, oy, player)
        player.x, player.y = ox, oy
        occupant.x, occupant.y = px, py
        player.standing_on, occupant.standing_on = o_under, p_under
        return True

    def _move_bomb_one_tile(self, bomb, dx, dy):
        """Try to move bomb by (dx, dy). Returns the tile that was restored
        at its old position (e.g. gunpowder, not necessarily plain floor)
        on success, or None if blocked."""
        nx, ny = bomb.x + dx, bomb.y + dy
        beyond = self.tile_at(nx, ny)
        if beyond is None or not beyond.is_walkable() or isinstance(beyond, Player):
            return None
        restored = bomb.under
        self.set_tile(bomb.x, bomb.y, restored)
        bomb.under = beyond
        bomb.x, bomb.y = nx, ny
        self.set_tile(nx, ny, bomb)
        return restored

    def _kick_bomb(self, bomb, dx, dy):
        if self._move_bomb_one_tile(bomb, dx, dy) is None:
            return False
        bomb.rolling = (dx, dy)
        bomb.last_roll_at = self._clock()
        return True

    def _advance_rolling_bombs(self, now):
        for bomb in list(self.bombs):
            if bomb.rolling is None:
                continue
            if _elapsed_ms(bomb.last_roll_at, now) < BOMB_ROLL_STEP_MS:
                continue
            dx, dy = bomb.rolling
            if self._move_bomb_one_tile(bomb, dx, dy) is None:
                bomb.rolling = None
                continue
            bomb.last_roll_at = now

    def _use_portal(self, player, portal):
        dest = portal.other
        if dest is None or dest.occupied:
            return
        portal.occupied = False
        self.set_tile(player.x, player.y, player.standing_on or Floor())
        player.standing_on = dest
        player.x, player.y = dest.x, dest.y
        dest.occupied = True
        self.set_tile(dest.x, dest.y, player)

    def _apply_powerup(self, player, kind):
        if kind == EXTRA_BOMB:
            player.add_bomb()
        elif kind == MORE_FLAME:
            player.add_flame(1)
        elif kind == GOLDEN_FLAME:
            player.flame_range = player.max_flame
        elif kind == EXTRA_LIFE:
            player.add_life()
        elif kind == SHIFTER:
            player.can_shift = True
        elif kind == SPEED_UP:
            player.add_speed()
        elif kind == KICKER:
            player.can_kick = True

    # -- bombs ----------------------------------------------------------

    def place_bomb(self, player):
        if player.is_dead or player.on_fire or self.game_over:
            return False
        if player.bombs_available <= 0:
            return False
        under = player.standing_on
        if not isinstance(under, (Floor, Gunpowder)):
            return False
        bomb = Bomb(player, player.x, player.y, under, self._clock())
        player.standing_on = bomb
        self.set_tile(player.x, player.y, bomb)
        player.bombs_available -= 1
        self.bombs.append(bomb)
        return True

    def tick(self):
        if self.game_over:
            return
        now = self._clock()
        for bomb in list(self.bombs):
            if not bomb.exploded and _elapsed_ms(bomb.placed_at, now) >= BOMB_FUSE_MS:
                bomb.exploded = True
                self._explode(bomb)
        self._advance_rolling_bombs(now)
        self._resolve_burning(now)
        self._update_shrink(now)
        self._check_game_over()

    def _check_game_over(self):
        alive = [p for p in self.players if not p.is_dead]
        if len(self.players) > 1 and len(alive) <= 1:
            self.game_over = True
            self.winner = alive[0] if alive else None

    # -- shrinking arena ----------------------------------------------------

    def _update_shrink(self, now):
        if not self._shrink_started:
            if _elapsed_ms(self._start_time, now) >= ARENA_SHRINK_START_MS:
                self._shrink_started = True
                self._shrink_last_step = now
            return
        if _elapsed_ms(self._shrink_last_step, now) < ARENA_SHRINK_STEP_MS:
            return
        self._shrink_last_step = now
        if self._shrink_horizontal:
            self._shrink_horizontal_step()
        else:
            self._shrink_vertical_step()

    def _shrink_horizontal_step(self):
        i, j = self._shrink_i, self._shrink_j
        if j < self.width - i:
            self._shrink_place_or_kill((j, i), (self.width - (j + 1), self.height - (i + 1)))
            self._shrink_j += 1
        else:
            self._shrink_horizontal = False

    def _shrink_vertical_step(self):
        i, k = self._shrink_i, self._shrink_k
        if k < self.height - (i + 1):
            self._shrink_place_or_kill((self.width - (i + 1), k), (i, self.height - (k + 1)))
            self._shrink_k += 1
        else:
            self._shrink_horizontal = True
        if self._shrink_j == self.width - self._shrink_i and self._shrink_k == self.height - (self._shrink_i + 1):
            self._shrink_i += 1
            self._shrink_j = self._shrink_i
            self._shrink_k = self._shrink_i + 1
            self._shrink_horizontal = True

    def _shrink_place_or_kill(self, pos1, pos2):
        # Mirrors the original exactly: check the first spot, then the
        # second: a player caught by the closing arena dies instantly and
        # no wall gets placed that step at all (neither spot). Only when
        # neither spot has a player do both become walls.
        for x, y in (pos1, pos2):
            tile = self.tile_at(x, y)
            if isinstance(tile, Player) and not tile.is_dead:
                tile.lives = 0
                return
        for x, y in (pos1, pos2):
            self.set_tile(x, y, Wall())

    # -- explosions -------------------------------------------------------

    def _explode(self, bomb):
        owner = bomb.owner
        owner.bombs_available += 1
        self.set_tile(bomb.x, bomb.y, bomb.under)
        if owner.standing_on is bomb:
            owner.standing_on = bomb.under
        if bomb in self.bombs:
            self.bombs.remove(bomb)
        self._ignite(bomb.x, bomb.y)
        for direction in (UP, DOWN, LEFT, RIGHT):
            dx, dy = DELTA[direction]
            x, y = bomb.x, bomb.y
            for _ in range(owner.flame_range):
                x, y = x + dx, y + dy
                if not self._ignite(x, y):
                    break

    def _ignite(self, x, y):
        """Ignite tile (x, y). Returns True if the flame keeps propagating past it."""
        tile = self.tile_at(x, y)
        if tile is None:
            return False
        if isinstance(tile, Bomb):
            if not tile.exploded:
                tile.exploded = True
                self._explode(tile)
            return True
        if isinstance(tile, (Crate, PowerUp)):
            # Breakable: catches fire and absorbs the blast, same as the
            # original (a crate or powerup always stops the flame).
            self._mark_burning(x, y)
            return False
        if tile.stops_flame():
            return False
        if isinstance(tile, Gunpowder):
            self._ignite_gunpowder_network()
            return True
        if isinstance(tile, Player):
            self._hit_player(tile)
            return True
        # Floor
        self._mark_burning(x, y)
        return True

    def _ignite_gunpowder_network(self):
        # Fixed from the original: ignite each gunpowder tile and hit each
        # standing player exactly once, instead of re-scanning and
        # re-damaging every player once per lit gunpowder tile.
        for x in range(self.width):
            for y in range(self.height):
                tile = self.grid[x][y]
                if isinstance(tile, Gunpowder):
                    self._mark_burning(x, y)
        for player in self.players:
            if isinstance(player.standing_on, Gunpowder) and not player.on_fire:
                self._hit_player(player)

    def _hit_player(self, player):
        if player.on_fire or player.is_dead:
            return
        player.on_fire = True
        self._burning.append({"kind": "player", "player": player, "started_at": self._clock()})

    def _mark_burning(self, x, y):
        for entry in self._burning:
            if entry.get("kind") == "tile" and entry["x"] == x and entry["y"] == y:
                return
        self._burning.append({"kind": "tile", "x": x, "y": y, "started_at": self._clock()})

    def _resolve_burning(self, now):
        remaining = []
        for entry in self._burning:
            if _elapsed_ms(entry["started_at"], now) < BOMB_BURN_MS:
                remaining.append(entry)
                continue
            if entry["kind"] == "player":
                self._extinguish_player(entry["player"])
            else:
                self._extinguish_tile(entry["x"], entry["y"])
        self._burning = remaining

    def _extinguish_tile(self, x, y):
        tile = self.tile_at(x, y)
        if isinstance(tile, Crate):
            self.set_tile(x, y, Floor())
        elif isinstance(tile, PowerUp):
            tile.revealed = True
        # Floor and Gunpowder tiles simply stop being drawn as on-fire;
        # the renderer derives that purely from the _burning list, so
        # nothing else to do here.

    def _extinguish_player(self, player):
        player.on_fire = False
        player.hit()
