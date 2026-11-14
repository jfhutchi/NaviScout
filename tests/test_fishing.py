from contextlib import contextmanager
import importlib.util
import struct
import unittest

from memory import Game, NotReady


class FishingMemory(Game):
    def __init__(self):
        self.data = dict.fromkeys(range(0x1000, 0x20000), 0)
        self.writes = []
        self.is_paused = False
        self.before_pause = None
        self.living = True
        values = {
            self.BASE + 0x4E371D0: 0x1000, 0x1480: 0x2000,
            0x2008: 0x3000, 0x2020: 0x2800, 0x2270: 0x4000,
            0x3000: self.BASE + 0x4BF78E0, 0x3518: 0x5000,
            0x5000: self.BASE + 0x4B47190, 0x5018: 0x2000, 0x5440: 0x6000,
            0x6008: 0x6100, 0x6100: 0x6200, 0x6218: 0x7000,
            0x7000: self.BASE + 0x4B479E8, 0x7020: 0x7100, 0x71F0: 0x2000,
            0x7100: 0x8000, 0x8000: self.BASE + 0x4C26670, 0x8008: 0x7000,
            0x8068: 0x8100, 0x8100: 0x9000, 0x9000: self.BASE + 0x49C3770,
            0x9008: 0x8000, 0x9020: 0xA000,
            0xA1B0: 0xAA00, 0xAA40: 0xA000,
            0x4358: 0xB000, 0xB000: self.BASE + 0x4B4DFC0, 0xB018: 0x2000,
            0xA020: 0xA800, 0xA270: 0xC000, 0xC2E0: 0xD000,
            0xD000: self.BASE + 0x4B4CA80, 0xD018: 0xA000,
            0xD0F0: 0xE000, 0xE040: 0xF000, 0xF020: 0xF800,
            0xF270: 0x10000, 0x10218: 0x11000,
            0x11000: self.BASE + 0x4B49B08, 0x11010: 0x12000,
            0x11018: 0xF000, 0x11020: 0x13000, 0x12150: 0x13000,
            0x13000: self.BASE + 0x4B3E548,
            0x130B8: 0x14000, 0x14000: 0x15000,
            0x15000: self.BASE + 0x4B5AED0,
            0x4110: 0x1B000, 0x1B000: self.BASE + 0x4B46870,
            0x1B018: 0x2000, 0x1B028: 0x1C000,
            0x1C018: 0x1C100, 0x1C038: 0x1C108,
            0x1C100: 0x1D000, 0x1C108: 0x1D040,
            0x1D000: self.BASE + 0x4B469A0, 0x1D030: 0x1E000,
            0x1D040: self.BASE + 0x4B469A0, 0x1D070: 0xAA00,
            0x1E040: 0xAB00, 0xAB20: 0xA900, 0xACB0: 0x1E000,
            0x1E0C0: 0x2000, 0x21B0: 0x1E080,
            0xD0A8: 0x1E080, 0xD0C0: 0x1E000,
            0xC2C0: 0x1F000, 0x1F000: self.BASE + 0x4B4C568,
            0x1F018: 0xA000, 0x1F0D0: 0xE000,
        }
        for address, value in values.items():
            self.put(address, '<Q', value)
        for address, value in ((0x6000, 1), (0x7018, 1), (0x8060, 1),
                               (0xBE58, 1 << 24), (0xB7D8, 18),
                               (0xA02C, 2), (0xF02C, 2), (0xA018, 6), (0xAA48, 6),
                               (0xD024, 4), (0xD0F8, 12), (0xE048, 12),
                               (0x130B0, 1)):
            self.put(address, '<I', value)
        for address, value in ((0x1B034, 4), (0x1C000, 0xEF1DF6C8),
                               (0x1C020, 0x27D2FDE5), (0x1C010, 1), (0x1C030, 1),
                               (0x1D038, 8), (0x1D078, 6), (0x1E048, 8),
                               (0xAB18, 8), (0xAB2C, 2), (0x2018, 9), (0x202C, 2),
                               (0x1E0C8, 9), (0xD0B0, 9), (0xD0C8, 8), (0x1F0D8, 12)):
            self.put(address, '<I', value)
        self.put(0x1D03D, '<B', 1)
        self.put(0x1D07D, '<B', 1)
        self.put(0xD020, '<B', 1)
        self.put(0x14008, '<B', 1)
        self.put(0x2800, b'Player\0')
        self.put(0xA800, b'Weapon_Lure\0')
        self.put(0xA900, b'Item_FishingRod\0')
        self.put(0xF800, b'Animal_Fish_Bass\0')
        for address, value in ((0x13224, 2.0), (0x13220, 1.0)):
            self.put(address, '<f', value)
        # One initialized local object in each situation parameter group.
        for offset, flag, target, vtable in ((0xB0, 0x12B, 0x17000, 0x4B5B1F0),
                                            (0x38, 0x12C, 0x18000, 0x4B5AF98),
                                            (0x60, 0x12D, 0x19000, 0x4B5B060)):
            self.put(0x15000 + flag, '<B', 1)
            self.put(0x15000 + offset + 8, '<I', 1)
            self.put(0x15000 + offset + 0x10, '<Q', target - 0x100)
            self.put(target - 0x100, '<Q', target)
            self.put(target, '<Q', self.BASE + vtable)
        for base, fields in ((0x17000, ((0x38, 180), (0x3C, 60), (0x48, 40))),
                             (0x18000, ((0x4C, 135), (0x40, 135), (0x38, 0.2), (0x3C, 3),
                                        (0x48, 3), (0x44, 3))),
                             (0x19000, ((0x48, 240), (0x40, 540), (0x60, 120),
                                        (0x3C, 300), (0x6C, 120), (0x64, 60)))):
            for offset, value in fields:
                self.put(base + offset, '<f', value)

    def put(self, address, fmt, *values):
        raw = fmt if isinstance(fmt, bytes) else struct.pack(fmt, *values)
        self.data.update({address + i: value for i, value in enumerate(raw)})

    def read(self, address, size):
        return bytes(self.data.get(address + i, 0) for i in range(size))

    def write_verified(self, address, raw, name):
        assert self.is_paused, 'Fishing writes must pause game threads'
        self.writes.append((address, raw))
        self.put(address, raw)

    @contextmanager
    def paused(self, game, ranges):
        if self.before_pause:
            self.before_pause()
        self.is_paused = True
        try:
            yield
        finally:
            self.is_paused = False

    def alive(self):
        return self.living


class FishingTests(unittest.TestCase):
    def control(self, game):
        self.assertIsNotNone(importlib.util.find_spec('fishing'),
                             'Fishing needs a guarded reversible controller')
        from fishing import FishingAssists
        control = FishingAssists()
        control.guard = game
        return control

    def test_off_does_not_even_read_player_memory(self):
        game = FishingMemory()
        control = self.control(game)
        game.read = lambda *args: self.fail('Off must not inspect live game memory')
        self.assertIn('Off', control.update(game, {}))

    def test_reel_changes_only_hooked_fish_parameters_once_then_restores(self):
        game = FishingMemory()
        control = self.control(game)
        original = dict(game.data)
        for _ in range(3):
            self.assertIn('Fishing assists active:', control.update(game, {'reel_speed': True}))
        self.assertEqual(game.unpack(0x13224, '<f')[0], 4)
        self.assertEqual(game.unpack(0x13220, '<f')[0], 2)
        self.assertEqual(len(game.writes), 4)
        control.restore(game)
        self.assertEqual(game.data, original)

    def test_each_nested_assist_changes_a_bounded_native_parameter(self):
        for key, address, minimum, maximum in (('hook_window', 0x17048, 120, 1200),
                                               ('escape_window', 0x18044, 60, 1200),
                                               ('quick_exhaust', 0x19048, 1, 60)):
            with self.subTest(key=key):
                game = FishingMemory()
                control = self.control(game)
                original = dict(game.data)
                self.assertIn('Fishing assists active:', control.update(game, {key: True}))
                self.assertTrue(minimum <= game.unpack(address, '<f')[0] <= maximum)
                control.update(game, {})
                self.assertEqual(game.data, original)

    def test_no_fishing_or_current_fish_never_writes(self):
        for address, fmt, value in ((0xB7D8, '<I', 0), (0xD0F8, '<I', 0xFFFFFFFF),
                                    (0xE048, '<I', 13), (0xE040, '<Q', 0),
                                    (0xF02C, '<I', 8), (0xD020, '<B', 0)):
            game = FishingMemory()
            game.put(address, fmt, value)
            control = self.control(game)
            self.assertIn('Waiting', control.update(game, {'reel_speed': True}))
            self.assertEqual(game.writes, [])

    def test_bad_owner_type_resource_and_unsafe_value_cancel_all_writes(self):
        for address, fmt, value in ((0x11018, '<Q', 1), (0xD018, '<Q', 1),
                                    (0x11000, '<Q', 1), (0x13000, '<Q', 1),
                                    (0x12150, '<Q', 1), (0x13224, '<f', float('nan')),
                                    (0x13224, '<f', 200), (0x132D4, '<B', 3)):
            game = FishingMemory()
            game.put(address, fmt, value)
            control = self.control(game)
            with self.assertRaises(NotReady):
                control.update(game, {'reel_speed': True})
            self.assertEqual(game.writes, [])

    def test_generation_change_after_pause_prevents_write(self):
        game = FishingMemory()
        control = self.control(game)
        game.before_pause = lambda: game.put(0xE048, '<I', 13)
        with self.assertRaises(NotReady):
            control.update(game, {'reel_speed': True})
        self.assertEqual(game.writes, [])
        self.assertFalse(game.is_paused)

    def test_session_end_restores_resource_while_it_is_still_owned(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        game.put(0xB7D8, '<I', 0)
        self.assertIn('Waiting', control.update(game, {'reel_speed': True}))
        self.assertEqual(game.unpack(0x13224, '<f')[0], 2)

    def test_released_resource_is_discarded_without_restoration_write(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        writes = len(game.writes)
        game.put(0x12150, '<Q', 0)
        control.restore(game)
        self.assertEqual(len(game.writes), writes)

    def test_external_change_is_preserved_and_blocks_other_restore_writes(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        game.put(0x13220, '<f', 1.5)
        writes = len(game.writes)
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertEqual(game.unpack(0x13220, '<f')[0], 1.5)
        self.assertEqual(len(game.writes), writes)

    def test_process_ownership_is_not_transferred_while_old_process_lives(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        other = FishingMemory()
        with self.assertRaises(NotReady):
            control.update(other, {'reel_speed': True})
        with self.assertRaises(NotReady):
            control.restore(other)
        self.assertEqual(other.writes, [])

    def test_unknown_option_is_rejected(self):
        game = FishingMemory()
        with self.assertRaises(ValueError):
            self.control(game).update(game, {'instant_reward': True})

    def test_recycled_rod_slot_is_rejected_before_writes(self):
        game = FishingMemory()
        game.put(0xAA48, '<I', 7)
        self.assertIn('Waiting', self.control(game).update(game, {'reel_speed': True}))
        self.assertEqual(game.writes, [])

    def test_external_reset_during_active_override_is_not_reported_active(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        game.put(0x13224, '<f', 2)
        with self.assertRaises(NotReady):
            control.update(game, {'reel_speed': True})

    def test_inherited_or_invalid_group_is_explicitly_unavailable_without_writes(self):
        for address, fmt, value in ((0x130C8, '<Q', 1), (0x14008, '<B', 0),
                                    (0x150C8, '<Q', 1), (0x150B8, '<I', 2),
                                    (0x17000, '<Q', 1), (0x1121C, '<I', 100)):
            with self.subTest(address=address):
                game = FishingMemory()
                game.put(address, fmt, value)
                with self.assertRaises(NotReady):
                    self.control(game).update(game, {'hook_window': True})
                self.assertEqual(game.writes, [])

    def test_one_invalid_option_cancels_the_entire_combined_transaction(self):
        game = FishingMemory()
        game.put(0x150C8, '<Q', 1)
        with self.assertRaises(NotReady):
            self.control(game).update(game, {'hook_window': True, 'reel_speed': True})
        self.assertEqual(game.writes, [])

    def test_partial_write_failure_retains_journal_for_exact_restoration(self):
        game = FishingMemory()
        control = self.control(game)
        original = dict(game.data)
        write = game.write_verified
        def failing_write(address, raw, name):
            write(address, raw, name)
            if len(game.writes) == 3:
                raise OSError('Synthetic read-back failure after a completed write')
        game.write_verified = failing_write
        with self.assertRaises(OSError):
            control.update(game, {'reel_speed': True})
        game.write_verified = write
        control.restore(game)
        self.assertEqual(game.data, original)

    def test_per_field_inheritance_uses_parent_value_and_restores_child_bytes(self):
        game = FishingMemory()
        control = self.control(game)
        game.put(0x13010, '<Q', 1)
        game.put(0x13018, '<Q', 0x16000)
        game.put(0x13020, '<I', 7)
        game.put(0x16000, '<Q', 0x1A000)
        game.put(0x1600C, '<I', 7)
        game.put(0x1A000, '<Q', game.BASE + 0x4B3E548)
        game.put(0x1A224, '<f', 3)
        game.put(0x1A220, '<f', 2)
        game.put(0x13224, '<f', 9)
        original = game.read(0x13224, 4)
        control.update(game, {'reel_speed': True})
        self.assertEqual(game.unpack(0x13224, '<f')[0], 6)
        control.restore(game)
        self.assertEqual(game.read(0x13224, 4), original)

    def test_replaced_nested_group_does_not_abandon_live_root_overrides(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True, 'hook_window': True})
        game.put(0x17010, '<Q', 123)
        control.restore(game)
        self.assertEqual(game.unpack(0x13224, '<f')[0], 2)
        self.assertEqual(game.unpack(0x13220, '<f')[0], 1)

    def test_inventory_resolution_ignores_ai_graph_but_rejects_replaced_item_array(self):
        game = FishingMemory()
        control = self.control(game)
        control.update(game, {'reel_speed': True})
        # An unrelated malformed wrapper would fail a full scan; the cached
        # slot still proves the action belongs to this player and module.
        game.put(0x7018, '<I', 2)
        game.put(0x7108, '<Q', 0x8200)
        game.put(0x8200, '<Q', game.BASE + 0x4C26670)
        game.put(0x8208, '<Q', 99)
        self.assertIn('active', control.update(game, {'reel_speed': True}))
        game.put(0x1C038, '<Q', 0)
        with self.assertRaises(NotReady):
            control.update(game, {'reel_speed': True})

    def test_long_original_windows_are_not_shortened_by_the_assist_cap(self):
        for key, address in (('hook_window', 0x17038), ('escape_window', 0x1804C)):
            game = FishingMemory()
            game.put(address, '<f', 2000)
            self.control(game).update(game, {key: True})
            self.assertGreaterEqual(game.unpack(address, '<f')[0], 2000)

    def test_owned_active_lure_does_not_require_a_player_ai_action_or_fishing_bit(self):
        game = FishingMemory()
        game.put(0xBE58, '<I', 0x400)
        game.put(0x5440, '<Q', 0)
        control = self.control(game)
        self.assertIn('active', control.update(game, {'reel_speed': True}))
        self.assertEqual(game.unpack(0x13224, '<f')[0], 4)

    def test_lure_owner_handles_and_current_actor_link_must_agree(self):
        for address, fmt, value in ((0x1B018, '<Q', 9), (0xD0B0, '<I', 10),
                                    (0xD0C8, '<I', 9), (0x1F018, '<Q', 9),
                                    (0x1F0D8, '<I', 13)):
            game = FishingMemory()
            game.put(address, fmt, value)
            with self.assertRaises(NotReady):
                self.control(game).update(game, {'reel_speed': True})
            self.assertEqual(game.writes, [])

    def test_escape_preserves_approach_ratio_and_stamina_preserves_exhaustion_duration(self):
        game = FishingMemory()
        ratio = game.read(0x18038, 4)
        exhaustion = game.read(0x1903C, 4)
        self.control(game).update(game, {'escape_window': True, 'quick_exhaust': True})
        self.assertEqual(game.read(0x18038, 4), ratio)
        self.assertEqual(game.read(0x1903C, 4), exhaustion)

    def test_stamina_assist_preserves_all_randomness_parameters(self):
        game = FishingMemory()
        fields = ((0x44, 0x72, 0.17), (0x68, 0x75, 0.29),
                  (0x4C, 0x79, 0.41), (0x58, 0x7C, 0.53))
        for offset, flag, value in fields:
            game.put(0x19000 + offset, '<f', value)
            game.put(0x19000 + flag, '<B', 1)
        originals = [(game.read(0x19000 + offset, 4), game.read(0x19000 + flag, 1))
                     for offset, flag, _ in fields]
        self.control(game).update(game, {'quick_exhaust': True})
        self.assertEqual([(game.read(0x19000 + offset, 4), game.read(0x19000 + flag, 1))
                          for offset, flag, _ in fields], originals)

    def test_optional_sinking_lure_with_zero_instances_does_not_block_standard_lure(self):
        game = FishingMemory()
        game.put(0x1C040, '<I', 0x791406DD)
        self.assertIn('active', self.control(game).update(game, {'reel_speed': True}))

    def test_stamina_reductions_shorten_subsequent_cycles_without_writing_active_timers(self):
        game = FishingMemory()
        game.put(0x112D0, '<2f', 350, 400)
        timers = game.read(0x112D0, 8)
        control = self.control(game)
        original = dict(game.data)
        control.update(game, {'quick_exhaust': True})
        self.assertGreaterEqual(game.unpack(0x1906C, '<f')[0], 540)
        self.assertGreaterEqual(game.unpack(0x19064, '<f')[0], 540)
        self.assertEqual(game.read(0x112D0, 8), timers)
        control.restore(game)
        self.assertEqual(game.data, original)


if __name__ == '__main__':
    unittest.main()
