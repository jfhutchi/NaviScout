import importlib.util
from contextlib import contextmanager
import struct
import unittest

from memory import Game, NotReady, StaleParameter


class HorseMemory(Game):
    def __init__(self):
        self.data, self.writes = {}, []
        self.paused = False
        self.before_pause = None
        for address, fmt, values in [
                (self.BASE + 0x4E371D0, '<Q', (0x1000,)), (0x1480, '<Q', (0x2000,)),
                (0x2020, '<Q', (0x3000,)), (0x2270, '<Q', (0x4000,)),
                (0x43A8, '<Q', (0x5000,)), (0x5018, '<Q', (0x2000,)),
                (0x5028, '<Q', (0x6000,)), (0x5030, '<I', (12,)), (0x5038, '<I', (1,)),
                (0x6040, '<Q', (0x7000,)), (0x6048, '<I', (12,)),
                (0x7020, '<Q', (0x8000,)), (0x7270, '<Q', (0x9000,)),
                (0x92A0, '<Q', (0xA000,)), (0xA000, '<Q', (self.BASE + 0x4B4C0C8,)),
                (0xA018, '<Q', (0x7000,)), (0xA4CC, '<4f', (3, 6, 10, 14)),
                (0xA4DC, '<4f', (0.1, 0.2, 0.3, 0.4))]:
            self.put(address, struct.pack(fmt, *values))
        self.put(0x3000, b'Player\0')
        self.put(0x8000, b'Animal_Epona_Adult\0')

    def put(self, address, raw):
        self.data.update({address + i: value for i, value in enumerate(raw)})

    def read(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))

    def write_verified(self, address, raw, name):
        assert self.paused, 'Horse writes must pause game threads before validation'
        self.writes.append((address, raw))
        self.put(address, raw)

    @contextmanager
    def horse_write_guard(self):
        if self.before_pause:
            self.before_pause()
        self.paused = True
        try:
            yield
        finally:
            self.paused = False

    def alive(self):
        return True


class HorseMemoryTests(unittest.TestCase):
    def context(self, game):
        self.assertTrue(hasattr(game, 'horse_context'), 'Mounted Epona needs a validated context')
        return game.horse_context()

    def test_current_player_must_be_riding_epona(self):
        game = HorseMemory()
        self.assertIsNotNone(self.context(game))
        self.assertEqual(game.writes, [])
        for address, raw in [(0x5038, struct.pack('<I', 0)), (0x5030, struct.pack('<I', 0xFFFFFFFF)),
                             (0x6048, struct.pack('<I', 13)), (0x6040, bytes(8)),
                             (0x702C, struct.pack('<I', 8)), (0x43A8, bytes(8)),
                             (0x8000, b'Animal_Horse\0'), (0x8000, b'Animal_Epona_Child\0')]:
            with self.subTest(address=address, raw=raw):
                game = HorseMemory()
                game.put(address, raw)
                self.assertIsNone(self.context(game))
                self.assertEqual(game.writes, [])

    def test_wrong_component_owner_or_type_is_rejected(self):
        for address, raw in [(0x5018, bytes(8)), (0xA018, bytes(8)), (0xA000, bytes(8))]:
            game = HorseMemory()
            game.put(address, raw)
            with self.assertRaises(NotReady):
                self.context(game)
            self.assertEqual(game.writes, [])

    def test_apply_rechecks_mount_and_preserves_acceleration(self):
        game = HorseMemory()
        context = self.context(game)
        original = game.horse_speed_snapshot(context)
        acceleration = game.read(0xA4DC, 16)
        game.horse_speed_replace(context, original, struct.pack('<4f', 6, 12, 20, 28), riding=True)
        self.assertEqual(game.read(0xA4DC, 16), acceleration)
        game.put(0x5038, struct.pack('<I', 0))
        with self.assertRaises(NotReady):
            game.horse_speed_replace(context, game.read(0xA4CC, 16), original, riding=True)
        game.horse_speed_replace(context, game.read(0xA4CC, 16), original, riding=False)
        self.assertEqual(game.read(0xA4CC, 16), original)

    def test_recycled_horse_slot_prevents_restoration_to_a_new_actor(self):
        game = HorseMemory()
        context = self.context(game)
        game.put(0x6048, struct.pack('<I', 13))
        with self.assertRaises(StaleParameter):
            game.horse_speed_snapshot(context)
        self.assertEqual(game.writes, [])

    def test_write_validates_actor_again_after_pausing_threads(self):
        game = HorseMemory()
        context = self.context(game)
        original = game.horse_speed_snapshot(context)
        game.before_pause = lambda: game.put(0x6048, struct.pack('<I', 13))
        with self.assertRaises(StaleParameter):
            game.horse_speed_replace(context, original, struct.pack('<4f', 6, 12, 20, 28), riding=True)
        self.assertEqual(game.writes, [])
        self.assertFalse(game.paused)

    def test_uninitialized_or_unsafe_speed_cache_is_rejected(self):
        for speed in (-1, float('nan'), float('inf'), 1000):
            game = HorseMemory()
            context = self.context(game)
            game.put(0xA4CC, struct.pack('<f', speed))
            with self.assertRaises(NotReady):
                game.horse_speed_snapshot(context)
            self.assertEqual(game.writes, [])


class HorseSpeedTests(unittest.TestCase):
    def control(self):
        self.assertIsNotNone(importlib.util.find_spec('horse'), 'Epona needs an independent riding-speed controller')
        from horse import HorseSpeed
        return HorseSpeed()

    def test_off_and_unmounted_never_write(self):
        game, control = HorseMemory(), self.control()
        control.update(game, False)
        game.put(0x5038, struct.pack('<I', 0))
        self.assertIn('mount Epona', control.update(game, True))
        self.assertEqual(game.writes, [])

    def test_doubles_all_riding_gears_once_and_restores_on_dismount(self):
        game, control = HorseMemory(), self.control()
        original = game.read(0xA4CC, 16)
        for _ in range(3):
            self.assertIn('active', control.update(game, True))
        self.assertEqual(struct.unpack('<4f', game.read(0xA4CC, 16)), (6, 12, 20, 28))
        self.assertEqual(len(game.writes), 1)
        game.put(0x5038, struct.pack('<I', 0))
        control.update(game, True)
        self.assertEqual(game.read(0xA4CC, 16), original)
        self.assertEqual(len(game.writes), 2)

    def test_off_and_close_restore_exact_original_bytes(self):
        for close in (False, True):
            game, control = HorseMemory(), self.control()
            original = game.read(0xA4CC, 16)
            control.update(game, True)
            if close:
                control.restore(game)
            else:
                control.update(game, False)
            self.assertEqual(game.read(0xA4CC, 16), original)

    def test_stale_horse_is_discarded_without_a_write(self):
        game, control = HorseMemory(), self.control()
        control.update(game, True)
        game.put(0x6048, struct.pack('<I', 13))
        control.restore(game)
        self.assertEqual(len(game.writes), 1)

    def test_external_speed_change_is_preserved(self):
        game, control = HorseMemory(), self.control()
        control.update(game, True)
        changed = struct.pack('<4f', 4, 7, 11, 16)
        game.put(0xA4CC, changed)
        with self.assertRaises(NotReady):
            control.update(game, True)
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertEqual(game.read(0xA4CC, 16), changed)
        self.assertEqual(len(game.writes), 1)

    def test_horsepower_refresh_waits_for_remount_without_restoring_old_cache(self):
        game, control = HorseMemory(), self.control()
        control.update(game, True)
        changed = struct.pack('<4f', 4, 7, 11, 16)
        game.put(0xA03C, struct.pack('<I', 1))
        game.put(0xA4CC, changed)
        self.assertIn('remount', control.update(game, True))
        self.assertEqual(len(game.writes), 1)
        control.restore(game)
        self.assertEqual(game.read(0xA4CC, 16), changed)
        game.put(0x5038, struct.pack('<I', 0))
        control.update(game, True)
        game.put(0x5038, struct.pack('<I', 1))
        control.update(game, True)
        self.assertEqual(struct.unpack('<4f', game.read(0xA4CC, 16)), (8, 14, 22, 32))
        control.restore(game)
        self.assertEqual(game.read(0xA4CC, 16), changed)

    def test_power_change_before_native_cache_refresh_cannot_compound_on_retoggle(self):
        for observed_on in (False, True):
            game, control = HorseMemory(), self.control()
            control.update(game, True)
            game.put(0xA03C, struct.pack('<I', 1))
            control.update(game, observed_on)
            control.update(game, False)
            self.assertIn('remount', control.update(game, True))
            self.assertEqual(struct.unpack('<4f', game.read(0xA4CC, 16)), (6, 12, 20, 28))
            self.assertEqual(len(game.writes), 1)

    def test_remount_reapplies_without_compounding(self):
        game, control = HorseMemory(), self.control()
        control.update(game, True)
        game.put(0x5038, struct.pack('<I', 0))
        control.update(game, True)
        game.put(0x5038, struct.pack('<I', 1))
        control.update(game, True)
        self.assertEqual(struct.unpack('<4f', game.read(0xA4CC, 16)), (6, 12, 20, 28))
