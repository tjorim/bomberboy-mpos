"""Bot opponent for single-player games.

The original Java game had no AI (it was always local 2-player), so this is
new code, not a port. Priority order each think-tick: avoid danger > attack
the other player when there's a clear, safe shot > break a reachable crate >
wander toward the opponent. Pathfinding is a small breadth-first search over
the grid -- at most WIDTH*HEIGHT (165) cells, cheap even on an ESP32-S3, so
no need for a fancier algorithm.
"""

import model
from model import Bomb, Crate, DELTA, Gunpowder, Player, Portal

THINK_MS = 350

# DELTA.values()/.items() were being re-evaluated on every call inside
# BFS's per-node neighbor expansion and a few other per-cell checks below
# -- each call builds a fresh dict-view object. Precomputed once here
# instead (docs.micropython.org/en/latest/reference/speed_python.html:
# cache frequently accessed values rather than repeated lookups), since
# DELTA itself never changes after model.py defines it.
_DELTA_VALUES = tuple(DELTA.values())
_DELTA_ITEMS = tuple(DELTA.items())


def _gunpowder_network(game):
    # x, y are always in bounds by construction here, so grid[x][y]
    # directly avoids tile_at()'s bounds check and method-call overhead
    # for what's otherwise a 165-cell scan -- this runs on every bomb
    # blast_cells()/_hypothetical_blast() computes, up to a few times per
    # 350ms AI think-tick.
    return {
        (x, y)
        for x in range(game.width)
        for y in range(game.height)
        if isinstance(game.grid[x][y], Gunpowder)
    }


def blast_cells(game, bomb, occupied_portal=None):
    """Cells a bomb's explosion would reach if it went off right now.

    Reaching any Gunpowder tile ignites the *entire* connected network in
    one instant (Game._ignite_gunpowder_network), not just the tiles within
    normal flame range -- without this, danger/escape checks below would
    treat far-away gunpowder tiles as safe even though a blast anywhere in
    the network would ignite them too.
    """
    tile_at = game.tile_at
    cells = {(bomb.x, bomb.y)}
    ignites_gunpowder = isinstance(bomb.under, Gunpowder)
    for dx, dy in _DELTA_VALUES:
        x, y = bomb.x, bomb.y
        for _ in range(bomb.owner.flame_range):
            x, y = x + dx, y + dy
            tile = tile_at(x, y)
            if tile is None:
                break
            # An empty portal stops flame, but a player standing on that
            # portal replaces it in the grid and no longer does. Portal-aware
            # pathfinding uses this option to evaluate the destination as it
            # will exist immediately after teleporting.
            if tile.stops_flame() and (x, y) != occupied_portal:
                break
            cells.add((x, y))
            if isinstance(tile, Gunpowder):
                ignites_gunpowder = True
            if tile.is_breakable():
                break
    if ignites_gunpowder:
        cells |= _gunpowder_network(game)
    return cells


def danger_cells(game):
    danger = set()
    for bomb in game.bombs:
        danger |= blast_cells(game, bomb)
    danger |= game.burning_tile_positions()
    for pair in game.upcoming_shrink_positions(2):
        danger.update(pair)
    return danger


def _portal_destination_is_dangerous(game, portal):
    dest = portal.other
    if dest is None or dest.occupied or game.player_at(dest.x, dest.y) is not None:
        return True
    pos = (dest.x, dest.y)
    if pos in game.burning_tile_positions():
        return True
    return any(pos in blast_cells(game, bomb, occupied_portal=pos) for bomb in game.bombs)


def _hypothetical_blast(game, x, y, flame_range, under=None):
    tile_at = game.tile_at
    cells = {(x, y)}
    ignites_gunpowder = isinstance(under, Gunpowder)
    for dx, dy in _DELTA_VALUES:
        cx, cy = x, y
        for _ in range(flame_range):
            cx, cy = cx + dx, cy + dy
            tile = tile_at(cx, cy)
            if tile is None or tile.stops_flame():
                break
            cells.add((cx, cy))
            if isinstance(tile, Gunpowder):
                ignites_gunpowder = True
            if tile.is_breakable():
                break
    if ignites_gunpowder:
        cells |= _gunpowder_network(game)
    return cells


def _is_walkable(tile):
    return tile is not None and tile.is_walkable() and not isinstance(tile, (Bomb, Player))


def _bfs_nearest(game, start, is_goal, avoid, with_states=False):
    """Shortest input path from start to the nearest matching game state.

    Returned coordinates are adjacent input targets; for a portal move that
    target is the entrance while the corresponding optional state is the far
    endpoint. Returns [] if start already satisfies is_goal and None if no
    path exists.
    """
    if is_goal(start):
        return ([], []) if with_states else []
    tile_at = game.tile_at
    visited = {start}
    queue = [start]
    # queue.pop(0) is O(len(queue)) -- it shifts every remaining element --
    # so a full BFS was O(cells^2) instead of O(cells). An index-based read
    # pointer keeps FIFO order (same traversal, same result) in O(1) per
    # dequeue without adding a collections.deque dependency this can't
    # verify against MicroPython's implementation.
    head = 0
    came_from = {}
    while head < len(queue):
        current = queue[head]
        head += 1
        cx, cy = current
        for dx, dy in _DELTA_VALUES:
            step_target = (cx + dx, cy + dy)
            if step_target in avoid:
                continue
            tile = tile_at(*step_target)
            if not _is_walkable(tile):
                continue
            resulting_pos = step_target
            if isinstance(tile, Portal):
                if _portal_destination_is_dangerous(game, tile):
                    continue
                resulting_pos = (tile.other.x, tile.other.y)
                if resulting_pos in avoid:
                    continue
            if resulting_pos in visited:
                continue
            visited.add(resulting_pos)
            came_from[resulting_pos] = (current, step_target)
            if is_goal(resulting_pos):
                actions = []
                states = []
                node = resulting_pos
                while node != start:
                    previous, action_target = came_from[node]
                    actions.append(action_target)
                    states.append(node)
                    node = previous
                actions.reverse()
                states.reverse()
                return (actions, states) if with_states else actions
            queue.append(resulting_pos)
    return None


def _path_clears_threats_in_time(start, states, threats, first_move_delay_ms):
    """Whether a path leaves every intersecting blast before it detonates.

    `states` are the actual player positions after each move (which can
    differ from the adjacent input target when a portal is used). The first
    move is immediate while re-planning an existing escape, but happens one
    AI interval after deciding to plant a hypothetical bomb.
    """
    positions = [start] + states
    for cells, remaining_ms in threats:
        dangerous = [index for index, pos in enumerate(positions) if pos in cells]
        if not dangerous:
            continue
        last_dangerous = dangerous[-1]
        if last_dangerous == len(states):
            return False
        exit_delay = first_move_delay_ms + last_dangerous * THINK_MS
        if exit_delay >= remaining_ms:
            return False
    return True


def _live_bomb_threats(game):
    """Current blast cells paired with chain-reaction-aware deadlines."""
    bombs = list(game.bombs)
    blasts = [blast_cells(game, bomb) for bomb in bombs]
    now = game.now()
    deadlines = [bomb.remaining_fuse_ms(now) for bomb in bombs]
    # If an earlier bomb reaches another bomb, the latter detonates at the
    # earlier deadline and can in turn trigger more bombs. Relax until the
    # chain graph reaches a fixed point (the board has only a few bombs).
    changed = True
    while changed:
        changed = False
        for source_index, source_cells in enumerate(blasts):
            source_deadline = deadlines[source_index]
            for target_index, target in enumerate(bombs):
                if (target.x, target.y) in source_cells and source_deadline < deadlines[target_index]:
                    deadlines[target_index] = source_deadline
                    changed = True
    return list(zip(blasts, deadlines))


def _adjacent_to_crate(game, pos):
    # Called as _bfs_nearest()'s goal predicate when pathing to a crate --
    # once per newly-visited node, so up to ~165 times per BFS call.
    x, y = pos
    tile_at = game.tile_at
    for dx, dy in _DELTA_VALUES:
        tile = tile_at(x + dx, y + dy)
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
    blast = _hypothetical_blast(game, bot.x, bot.y, bot.flame_range, under=bot.standing_on)
    combined = danger | blast
    result = _bfs_nearest(
        game,
        (bot.x, bot.y),
        lambda pos: pos not in combined,
        avoid=danger,
        with_states=True,
    )
    if result is None:
        return False
    actions, states = result
    if not actions:
        return False
    return _path_clears_threats_in_time(
        (bot.x, bot.y),
        states,
        [(blast, model.BOMB_FUSE_MS)],
        first_move_delay_ms=THINK_MS,
    )


def _direction_towards(bot, target):
    tx, ty = target
    for direction, (dx, dy) in _DELTA_ITEMS:
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
        if escape is None:
            # No path that stays clear of every pending blast. That's the
            # normal state right after planting our own bomb: we're at the
            # blast center, so every first step is a blast cell and the
            # strict search above can't expand at all -- the bot would
            # freeze on its own bomb and die. Pending-blast cells are fine
            # to travel *through* before the fuse runs out (the same rule
            # _has_escape_after_bombing used to approve planting it), so
            # retry treating only tiles actually on fire as impassable.
            burning = game.burning_tile_positions()
            result = _bfs_nearest(
                game,
                here,
                lambda pos: pos not in danger,
                avoid=burning - {here},
                with_states=True,
            )
            if result is not None:
                escape, states = result
                threats = _live_bomb_threats(game)
                if not _path_clears_threats_in_time(here, states, threats, first_move_delay_ms=0):
                    escape = None
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

    if game.is_shrinking():
        center = (game.width // 2, game.height // 2)
        current_radius = max(abs(here[0] - center[0]), abs(here[1] - center[1]))
        if current_radius > 0:
            center_path = _bfs_nearest(
                game,
                here,
                lambda pos: max(abs(pos[0] - center[0]), abs(pos[1] - center[1])) < current_radius,
                avoid=danger,
            )
            if center_path:
                direction = _direction_towards(bot, center_path[0])
                if direction:
                    return ("move", direction)

    opponent_pos = (opponent.x, opponent.y)
    path = _bfs_nearest(game, here, lambda pos: _adjacent_to(pos, opponent_pos), avoid=danger)
    if path:
        direction = _direction_towards(bot, path[0])
        if direction:
            return ("move", direction)
    return None
