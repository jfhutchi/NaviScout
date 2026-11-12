import struct
import unittest
from unittest.mock import patch

from memory import Game, NotReady
from timers import TimerHold


class TimerArena(Game):
    def __init__(self):
        self.addresses = {}
        self.data = {}
        self.writes = []
        self.running = True
        self.countdown = True
        self.changed = False
        self.hold = TimerHold()
        for i, key in enumerate((0xA4ED3902, 0xE73DAF62, 0xD601EE20, 0x3E7D10C0, 0xF6EB33A1,
                                 0x9D350590, 0xFCD114C3)):
            self.addresses[key] = 0x1000 + i * 0x100
            self.data[self.addresses[key] + 28] = struct.pack('<I', 1471695344)
        self.stage(0xA4ED3902, 3949112793)
        self.value(10000)
        self.limit(0)

    def stage(self, key, value):
        self.data[self.addresses[key] + 28] = struct.pack('<I', value)

    def value(self, value):
        self.data[self.addresses[0x9D350590] + 28] = struct.pack('<ff', value, value)

    def limit(self, value):
        self.data[self.addresses[0xFCD114C3] + 28] = struct.pack('<f', value)

    def manager(self):
        return 999 if self.changed else 100

    def entry(self, manager, key, kind, stride, expected=None):
        return self.addresses[key]

    def boolean(self, manager, key, expected=None):
        return self.running if key == 0xF0312188 else self.countdown

    def read(self, address, size):
        return self.data[address][:size]

    def write_verified(self, target, raw, name):
        self.data[target] = raw
        self.writes.append((target, raw))

    def run(self, enabled=True, area='ZoraDomain_Child'):
        return self.freeze_minigame_timer(100, area, self.hold, enabled)


class TimerTests(unittest.TestCase):
    def test_disabled_option_observes_without_writing(self):
        game = TimerArena()
        result = game.run(False)
        self.assertFalse(result['frozen'])
        self.assertEqual(game.writes, [])
        self.assertIsNone(game.hold.value)

    def test_countdown_returns_to_captured_remaining_time(self):
        game = TimerArena()
        game.run()
        game.value(9850)
        result = game.run()
        self.assertEqual(result['milliseconds'], 10000)
        self.assertTrue(result['frozen'])
        self.assertEqual(game.data[game.addresses[0x9D350590] + 28], struct.pack('<ff', 10000, 10000))

    def test_elapsed_race_clock_is_held_too(self):
        game = TimerArena()
        game.countdown = False
        game.limit(600000)
        game.run()
        game.value(10150)
        self.assertEqual(game.run()['milliseconds'], 10000)

    def test_stopped_or_expired_timer_never_writes(self):
        for stopped, countdown, value, limit in ((True, True, 1000, 0),
                                                 (False, True, 0, 0), (False, False, 1000, 1000)):
            game = TimerArena()
            game.running = not stopped
            game.countdown = countdown
            game.value(value)
            game.limit(limit)
            self.assertIsNone(game.run())
            self.assertEqual(game.writes, [])

    def test_non_minigame_timer_is_untouched(self):
        game = TimerArena()
        game.stage(0xA4ED3902, 1471695344)
        self.assertIsNone(game.run())
        self.assertEqual(game.writes, [])

    def test_all_supported_games_require_their_playing_stage(self):
        for key, stage, name in ((0xA4ED3902, 3949112793, 'Diving'),
                                  (0xE73DAF62, 4289256035, "Dampe's race"),
                                  (0xD601EE20, 4289256035, 'Horse race'),
                                  (0x3E7D10C0, 4289256035, 'Cucco search'),
                                  (0xF6EB33A1, 4289256035, 'Running race')):
            game = TimerArena()
            game.stage(0xA4ED3902, 1471695344)
            game.stage(key, stage)
            self.assertEqual(game.run()['game'], name)

    def test_ambiguous_active_games_are_not_modified(self):
        game = TimerArena()
        game.stage(0xD601EE20, 4289256035)
        self.assertIsNone(game.run())
        self.assertEqual(game.writes, [])

    def test_new_round_or_area_captures_a_new_time(self):
        game = TimerArena()
        game.run()
        game.value(30000)
        self.assertEqual(game.run()['milliseconds'], 30000)
        game.value(20000)
        self.assertEqual(game.run(area='AnotherArea')['milliseconds'], 20000)

    def test_disabling_releases_timer_and_reenabling_captures_current(self):
        game = TimerArena()
        game.run()
        game.value(9000)
        count = len(game.writes)
        self.assertEqual(game.run(False)['milliseconds'], 9000)
        self.assertEqual(len(game.writes), count)
        self.assertEqual(game.run()['milliseconds'], 9000)

    def test_invalid_time_is_rejected(self):
        for value in (float('nan'), float('inf'), -1, 3600001):
            game = TimerArena()
            game.value(value)
            with self.assertRaises(NotReady):
                game.run()
            self.assertEqual(game.writes, [])

    def test_ending_round_or_changed_save_cancels_write(self):
        game = TimerArena()
        context = game.timer_context(100)
        with patch.object(game, 'timer_context', side_effect=[context, None]):
            with self.assertRaises(NotReady):
                game.run()
        self.assertEqual(game.writes, [])
        game.changed = True
        with self.assertRaises(NotReady):
            game.run()
        self.assertEqual(game.writes, [])

    def test_only_timer_value_is_written(self):
        game = TimerArena()
        before = dict(game.data)
        game.run()
        timer = game.addresses[0x9D350590] + 28
        self.assertTrue(all(address == timer for address, _ in game.writes))
        self.assertEqual({k: v for k, v in game.data.items() if k != timer},
                         {k: v for k, v in before.items() if k != timer})


if __name__ == '__main__':
    unittest.main()
