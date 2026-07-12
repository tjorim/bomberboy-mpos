"""ESP-NOW transport and deterministic two-peer input synchronization."""

PROTOCOL = b"BB1"
BROADCAST_MAC = b"\xff\xff\xff\xff\xff\xff"
NO_ACTION = "-"
VALID_ACTIONS = (NO_ACTION, "U", "D", "L", "R", "B")


def _packet(*parts):
    return b"|".join((PROTOCOL,) + tuple(str(part).encode() for part in parts))


def hello_packet(level_index):
    return _packet("H", level_index)


def start_packet(level_index, seed):
    return _packet("S", level_index, seed)


def ack_packet(seed):
    return _packet("A", seed)


def parse_packet(message):
    try:
        parts = bytes(message).split(b"|")
        if len(parts) < 2 or parts[0] != PROTOCOL:
            return None
        kind = parts[1].decode()
        if kind == "H" and len(parts) == 3:
            return kind, int(parts[2])
        if kind == "S" and len(parts) == 4:
            return kind, int(parts[2]), int(parts[3])
        if kind == "A" and len(parts) == 3:
            return kind, int(parts[2])
        if kind == "F" and len(parts) == 6:
            action = parts[3].decode()
            previous = parts[5].decode()
            if action in VALID_ACTIONS and previous in VALID_ACTIONS:
                return kind, int(parts[2]), action, int(parts[4]), previous
    except (TypeError, ValueError, UnicodeError):
        pass
    return None


class FrameSynchronizer:
    """Collect one input per player and release complete frames in order."""

    def __init__(self, local_player_id):
        self.local_player_id = local_player_id
        self.remote_player_id = 3 - local_player_id
        self.frame = 0
        self._queued_action = NO_ACTION
        self._actions = {}
        self._previous_local = (-1, NO_ACTION)

    def queue(self, action):
        if action not in VALID_ACTIONS or action == NO_ACTION:
            raise ValueError("invalid player action")
        self._queued_action = action

    def frame_packet(self):
        key = (self.frame, self.local_player_id)
        if key not in self._actions:
            self._actions[key] = self._queued_action
            self._queued_action = NO_ACTION
        previous_frame, previous_action = self._previous_local
        return _packet("F", self.frame, self._actions[key], previous_frame, previous_action)

    def receive(self, message):
        parsed = parse_packet(message)
        if parsed is None or parsed[0] != "F":
            return False
        _, frame, action, previous_frame, previous_action = parsed
        # Every packet repeats the sender's previous-frame action too (loss
        # recovery), so by the time a few packets have gone by, that
        # "previous frame" has usually already been popped and its entries
        # deleted -- only insert entries for frames not yet consumed, or
        # every packet after the first would silently leave one orphaned
        # entry in _actions forever (frame numbers only ever increase, so
        # a stale entry is never read or deleted once left behind). Over a
        # long match this is an unbounded memory leak.
        if frame >= self.frame:
            self._actions[(frame, self.remote_player_id)] = action
        if previous_frame >= self.frame:
            self._actions[(previous_frame, self.remote_player_id)] = previous_action
        return True

    def pop_ready(self):
        local_key = (self.frame, self.local_player_id)
        remote_key = (self.frame, self.remote_player_id)
        if local_key not in self._actions or remote_key not in self._actions:
            return None
        actions = (self._actions[(self.frame, 1)], self._actions[(self.frame, 2)])
        self._previous_local = (self.frame, self._actions[local_key])
        del self._actions[local_key]
        del self._actions[remote_key]
        self.frame += 1
        return actions


class EspNowLink:
    """Thin async adapter around MicroPython's documented AIOESPNow API."""

    def __init__(self):
        self.wlan = None
        self.radio = None
        self.local_mac = None
        self.running = False
        self._peers = set()

    def open(self):
        import aioespnow
        import network

        station_interface = getattr(network.WLAN, "IF_STA", None)
        if station_interface is None:
            station_interface = network.STA_IF
        self.wlan = network.WLAN(station_interface)
        self.wlan.active(True)
        self.local_mac = bytes(self.wlan.config("mac"))
        self.radio = aioespnow.AIOESPNow()
        self.radio.active(True)
        self.add_peer(BROADCAST_MAC)
        self.running = True

    def add_peer(self, mac):
        mac = bytes(mac)
        if mac in self._peers:
            return
        try:
            self.radio.add_peer(mac)
        except OSError:
            pass
        self._peers.add(mac)

    async def send(self, mac, message):
        self.add_peer(mac)
        return await self.radio.asend(mac, message)

    async def receive_loop(self, callback):
        try:
            async for mac, message in self.radio:
                if not self.running:
                    break
                callback(bytes(mac), bytes(message))
        except Exception as error:
            if self.running:
                callback(None, error)

    def close(self):
        self.running = False
        if self.radio is not None:
            self.radio.active(False)
        self.radio = None
