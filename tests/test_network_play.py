import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bomberboy"))

from network_play import (
    FrameSynchronizer,
    ack_packet,
    hello_packet,
    parse_packet,
    start_packet,
    _packet,
)


class PacketTests(unittest.TestCase):
    def test_pairing_packets_round_trip(self):
        self.assertEqual(parse_packet(hello_packet(2)), ("H", 2))
        self.assertEqual(parse_packet(start_packet(3, 123456)), ("S", 3, 123456))
        self.assertEqual(parse_packet(ack_packet(123456)), ("A", 123456))

    def test_foreign_and_malformed_packets_are_ignored(self):
        for packet in (b"other", b"BB1|F|bad|U|-1|-", b"BB1|F|0|X|-1|-"):
            self.assertIsNone(parse_packet(packet))


class FrameSynchronizerTests(unittest.TestCase):
    def test_peers_release_identical_actions_in_player_order(self):
        first = FrameSynchronizer(1)
        second = FrameSynchronizer(2)
        first.queue("R")
        second.queue("B")
        first_packet = first.frame_packet()
        second_packet = second.frame_packet()
        self.assertTrue(first.receive(second_packet))
        self.assertTrue(second.receive(first_packet))
        self.assertEqual(first.pop_ready(), ("R", "B"))
        self.assertEqual(second.pop_ready(), ("R", "B"))

    def test_next_packet_recovers_a_lost_previous_frame(self):
        first = FrameSynchronizer(1)
        second = FrameSynchronizer(2)
        first_frame = first.frame_packet()
        second.receive(first_frame)
        second_frame = second.frame_packet()
        first.receive(second_frame)
        self.assertEqual(first.pop_ready(), ("-", "-"))
        self.assertEqual(second.pop_ready(), ("-", "-"))

        # Drop player 1's frame-1 packet. Player 1 can advance after receiving
        # player 2, and its frame-2 packet carries frame 1 for recovery.
        second_frame = second.frame_packet()
        first.receive(second_frame)
        first.frame_packet()
        self.assertEqual(first.pop_ready(), ("-", "-"))
        recovery_packet = first.frame_packet()
        second.receive(recovery_packet)
        self.assertEqual(second.pop_ready(), ("-", "-"))

    def test_receive_does_not_resurrect_already_consumed_frames(self):
        # Every packet repeats the sender's previous-frame action too (loss
        # recovery), so once a frame has already been popped locally, a
        # packet still carrying that old frame as "previous" must not
        # resurrect a dict entry for it -- that entry would never be read
        # (frame numbers only move forward) or cleaned up again, leaking
        # memory for the rest of a long match.
        sync = FrameSynchronizer(2)
        sync.frame = 5  # frames 0-4 already popped and cleared
        packet = _packet("F", 5, "L", 4, "R")
        self.assertTrue(sync.receive(packet))
        self.assertEqual(sync._actions, {(5, 1): "L"})


if __name__ == "__main__":
    unittest.main()
