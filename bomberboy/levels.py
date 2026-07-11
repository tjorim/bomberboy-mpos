"""Level layouts for Bomberboy.

Redesigned to a 15x11 board (see the port plan) instead of the original's
21x15, but generated with the same even-coordinate pillar algorithm from
Model.java, parametrized by width/height, so the classic Bomberman "brick
pillar" look carries over unchanged.
"""

import random

from model import Crate, Floor, Gunpowder, Player, PowerUp, Portal, Wall, ALL_POWERS, HEIGHT, WIDTH


def _base_grid(width, height):
    grid = [[Floor() for _y in range(height)] for _x in range(width)]
    for x in range(width):
        grid[x][0] = Wall()
        grid[x][height - 1] = Wall()
    for y in range(1, height - 1):
        grid[0][y] = Wall()
        grid[width - 1][y] = Wall()
    for x in range(2, width - 2, 2):
        for y in range(2, height - 2, 2):
            grid[x][y] = Wall()
    return grid


def _spawn_positions(width, height):
    return (1, 1), (width - 2, height - 2)


def _clear_spawn_pocket(grid, x, y, dx, dy):
    grid[x][y] = Floor()
    grid[x + dx][y] = Floor()
    grid[x][y + dy] = Floor()


def _fill_crates(grid, width, height):
    for x in range(1, width - 1):
        for y in range(1, height - 1):
            if isinstance(grid[x][y], Floor) and (x % 2 == 1 or y % 2 == 1):
                grid[x][y] = Crate()


def _coerce_rng(seed):
    return random if seed is None else random.Random(seed)


def _sprinkle_powerups(grid, width, height, count, rng):
    candidates = [(x, y) for x in range(width) for y in range(height) if isinstance(grid[x][y], Crate)]
    rng.shuffle(candidates)
    for x, y in candidates[:count]:
        grid[x][y] = PowerUp(rng.choice(ALL_POWERS))


class Level:
    name = "Level"
    width = WIDTH
    height = HEIGHT
    max_flame = (HEIGHT - 3) // 2
    give_max_stats = False

    def __init__(self):
        self.portals = []

    def build_grid(self, seed=None):
        raise NotImplementedError

    def place_players(self, grid):
        (p1x, p1y), (p2x, p2y) = _spawn_positions(self.width, self.height)
        players = [
            Player(1, p1x, p1y, self.max_flame),
            Player(2, p2x, p2y, self.max_flame),
        ]
        for player in players:
            player.standing_on = Floor()
            grid[player.x][player.y] = player
            if self.give_max_stats:
                player.bombs_available = player.MAX_BOMBS
                player.flame_range = player.max_flame
                player.speed = player.MAX_SPEED
                player.can_shift = True
        return players


class MazeLevel(Level):
    """Dense crate maze, sprinkled with powerups. The classic layout."""

    name = "Maze"
    powerup_count = 18

    def build_grid(self, seed=None):
        rng = _coerce_rng(seed)
        self.portals = []
        grid = _base_grid(self.width, self.height)
        _fill_crates(grid, self.width, self.height)
        (p1x, p1y), (p2x, p2y) = _spawn_positions(self.width, self.height)
        _clear_spawn_pocket(grid, p1x, p1y, 1, 1)
        _clear_spawn_pocket(grid, p2x, p2y, -1, -1)
        _sprinkle_powerups(grid, self.width, self.height, self.powerup_count, rng)
        return grid


class GunpowderCrossLevel(Level):
    """Sparse level with a gunpowder cross through the middle. No powerups."""

    name = "Fire Everywhere"

    def build_grid(self, seed=None):
        grid = _base_grid(self.width, self.height)
        mid_x, mid_y = self.width // 2, self.height // 2
        for x in range(2, self.width - 2):
            if isinstance(grid[x][mid_y], Floor):
                grid[x][mid_y] = Gunpowder()
        for y in range(2, self.height - 2):
            if isinstance(grid[mid_x][y], Floor):
                grid[mid_x][y] = Gunpowder()
        for cx, cy in ((self.width - 3, 1), (1, self.height - 3)):
            for dx, dy in ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2)):
                x, y = cx + dx, cy + dy
                if isinstance(grid[x][y], Floor):
                    grid[x][y] = Crate()
        return grid


class PortalMazeLevel(Level):
    """Dense crate maze with two independent linked portal pairs -- one in
    each pair of opposite corners. The Java original's own Portaal class
    already had a portaalNr (which pair) field alongside poortNr (which
    end), it just never got wired up (constructor bug, fixed upstream in
    tjorim/bomberboy-java#3) and Model.java only ever instantiated one pair.
    This layout -- four portals, two pairs, one per corner-pair -- is
    cross-pollinated from the abandoned Qt attempt's level 3
    (github.com/tjorim/bomberboy-qt), which placed them the same way but
    never got the teleport-on-walk-into logic itself working, in either
    version."""

    name = "Portals"
    powerup_count = 14

    def _add_portal_pair(self, grid, a_pos, b_pos, pair_index):
        a = Portal(a_pos[0], a_pos[1], portal_id=pair_index * 2)
        b = Portal(b_pos[0], b_pos[1], portal_id=pair_index * 2 + 1)
        a.other, b.other = b, a
        grid[a.x][a.y] = a
        grid[b.x][b.y] = b
        self.portals.extend((a, b))

    def build_grid(self, seed=None):
        rng = _coerce_rng(seed)
        self.portals = []
        grid = _base_grid(self.width, self.height)
        _fill_crates(grid, self.width, self.height)
        (p1x, p1y), (p2x, p2y) = _spawn_positions(self.width, self.height)
        _clear_spawn_pocket(grid, p1x, p1y, 1, 1)
        _clear_spawn_pocket(grid, p2x, p2y, -1, -1)

        self._add_portal_pair(grid, (3, 3), (self.width - 4, self.height - 4), 0)
        self._add_portal_pair(grid, (self.width - 4, 3), (3, self.height - 4), 1)

        _sprinkle_powerups(grid, self.width, self.height, self.powerup_count, rng)
        return grid


class OpenArenaLevel(Level):
    """Just plain open floor. Both players start fully powered up."""

    name = "Showdown"
    give_max_stats = True

    def build_grid(self, seed=None):
        return _base_grid(self.width, self.height)


LEVELS = (MazeLevel, GunpowderCrossLevel, PortalMazeLevel, OpenArenaLevel)
