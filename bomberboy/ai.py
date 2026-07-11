"""Bot opponent for single-player games.

The original Java game had no AI (it was always local 2-player), so this is
new code, not a port. Priority order each think-tick: avoid danger > attack
the other player when there's a clear, safe shot > break a reachable crate >
wander toward the opponent. Pathfinding is a small breadth-first search over
the grid -- at most WIDTH*HEIGHT (165) cells, cheap even on an ESP32-S3, so
no need for a fancier algorithm.
"""

from model import Bomb, Crate, DELTA, Player


def blast_cells(game, bomb):
    """Cells a bomb's explosion would reach if it went off right now."""
    cells = {(bomb.x, bomb.y)}
    for dx, dy in DELTA.values():
        x, y = bomb.x, bomb.y
        for _ in range(bomb.owner.flame_range):
            x, y = x + dx, y + dy
            tile = game.tile_at(x, y)
            if tile is None or tile.stops_flame():
                break
            cells.add((x, y))
            if tile.is_breakable():
                break
    return cells


def danger_cells(game):
    danger = set()
    for bomb in game.bombs:
        danger |= blast_cells(game, bomb)
    danger |= game.burning_tile_positions()
    return danger


def _hypothetical_blast(game, x, y, flame_range):
    cells = {(x, y)}
    for dx, dy in DELTA.values():
        cx, cy = x, y
        for _ in range(flame_range):
            cx, cy = cx + dx, cy + dy
            tile = game.tile_at(cx, cy)
            if tile is None or tile.stops_flame():
                break
            cells.add((cx, cy))
            if tile.is_breakable():
                break
    return cells


def _is_walkable(tile):
    return tile is not None and tile.is_walkable() and not isinstance(tile, (Bomb, Player))


def _bfs_nearest(game, start, is_goal, avoid):
    """Shortest path (list of (x,y), excluding start) from start to the
    nearest tile satisfying is_goal, only stepping on walkable tiles not in
    avoid. Returns [] if start already satisfies is_goal, None if no path
    exists."""
    if is_goal(start):
        return []
    visited = {start}
    queue = [start]
    came_from = {}
    while queue:
        current = queue.pop(0)
        cx, cy = current
        for dx, dy in DELTA.values():
            nxt = (cx + dx, cy + dy)
            if nxt in visited or nxt in avoid:
                continue
            tile = game.tile_at(*nxt)
            if not _is_walkable(tile):
                continue
            visited.add(nxt)
            came_from[nxt] = current
            if is_goal(nxt):
                path = [nxt]
                node = current
                while node != start:
                    path.append(node)
                    node = came_from[node]
                path.reverse()
                return path
            queue.append(nxt)
    return None


def _adjacent_to_crate(game, pos):
    x, y = pos
    for dx, dy in DELTA.values():
        tile = game.tile_at(x + dx, y + dy)
        if isinstance(tile, Crate):
            return True
    return False


def _adjacent_to(pos, target):
    x, y = pos
    tx, ty = target
    return abs(x - tx) + abs(y - ty) == 1


def _has_clear_shot(game, bot, opponent):
    if opponent.is_dead:
        return False
    if bot.x != opponent.x and bot.y != opponent.y:
        return False
    dist = abs(bot.x - opponent.x) + abs(bot.y - opponent.y)
    if dist > bot.flame_range or dist == 0:
        return False
    dx = 0 if bot.x == opponent.x else (1 if opponent.x > bot.x else -1)
    dy = 0 if bot.y == opponent.y else (1 if opponent.y > bot.y else -1)
    x, y = bot.x, bot.y
    for _ in range(dist - 1):
        x, y = x + dx, y + dy
        tile = game.tile_at(x, y)
        if tile is None or tile.stops_flame():
            return False
    return True


def _has_escape_after_bombing(game, bot, danger):
    # The bomb has a couple of seconds to go off, so the bot can walk
    # *through* tiles that are about to be in the blast on its way to
    # actual safety -- it only needs to not be on one of them by the time
    # it explodes. Only pre-existing danger (from other live bombs/fire)
    # is treated as impassable during the search.
    blast = _hypothetical_blast(game, bot.x, bot.y, bot.flame_range)
    combined = danger | blast
    escape = _bfs_nearest(game, (bot.x, bot.y), lambda pos: pos not in combined, avoid=danger)
    return bool(escape)


def _direction_towards(bot, target):
    tx, ty = target
    for direction, (dx, dy) in DELTA.items():
        if bot.x + dx == tx and bot.y + dy == ty:
            return direction
    return None


def choose_action(game, bot, opponent):
    """Decide what the bot should do this think-tick.

    Returns ("move", direction), ("bomb",), or None.
    """
    if bot.is_dead or bot.on_fire or game.game_over:
        return None

    danger = danger_cells(game)
    here = (bot.x, bot.y)

    if here in danger:
        escape = _bfs_nearest(game, here, lambda pos: pos not in danger, avoid=danger - {here})
        if escape:
            direction = _direction_towards(bot, escape[0])
            if direction:
                return ("move", direction)
        return None

    if bot.bombs_available > 0 and _has_clear_shot(game, bot, opponent) and _has_escape_after_bombing(game, bot, danger):
        return ("bomb",)

    if bot.bombs_available > 0:
        crate_path = _bfs_nearest(game, here, lambda pos: _adjacent_to_crate(game, pos), avoid=danger)
        if crate_path == [] and _has_escape_after_bombing(game, bot, danger):
            return ("bomb",)
        if crate_path:
            direction = _direction_towards(bot, crate_path[0])
            if direction:
                return ("move", direction)

    opponent_pos = (opponent.x, opponent.y)
    path = _bfs_nearest(game, here, lambda pos: _adjacent_to(pos, opponent_pos), avoid=danger)
    if path:
        direction = _direction_towards(bot, path[0])
        if direction:
            return ("move", direction)
    return None
