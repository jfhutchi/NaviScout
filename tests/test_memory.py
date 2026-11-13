import ctypes
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from core import RESOURCES
from memory import Game, NotReady


class Arena(Game):
    def __init__(self):
        self.handle = 1
        self.pid = 0
        self.data = {}
        self.addresses = {}
        self.writes = []
        self.changed = False
        self.owned = False
        for number, (name, row) in enumerate(RESOURCES.items()):
            key, index, cap_key, cap_index, caps = row
            target = 0x2000 + number * 0x100
            cap = target + 0x80
            self.addresses[key] = target - 28
            self.addresses[cap_key] = cap - 28
            self.data[target] = struct.pack('<ii', 2, 2)
            self.data[cap] = struct.pack('<i', caps[0])

    def manager(self):
        return 0x999 if self.changed else 0x1000

    def entry(self, manager, key, kind, stride, expected=None):
        return self.addresses[key]

    def read(self, address, size):
        return self.data[address][:size]

    def boolean(self, manager, key, expected=None):
        return self.owned

    def health_target(self, capacity):
        return self.addresses[RESOURCES['health'][0]] + 28

    def magic_target(self, capacity):
        self.data.setdefault(0xF000, struct.pack('<i', 2))
        return 0xF000

    def write(self, handle, address, data, size, done):
        value = ctypes.string_at(data, size)
        self.data[address] = value
        self.writes.append(address)
        ctypes.cast(done, ctypes.POINTER(ctypes.c_size_t))[0] = size
        return 1


class MemoryPolicyTests(unittest.TestCase):
    def test_magic_beans_stay_locked_until_obtained(self):
        self.assertIn('magic_beans', RESOURCES)
        game = Arena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['magic_beans'])
        self.assertFalse(result['magic_beans']['unlocked'])
        self.assertEqual(game.writes, [])

    def test_owned_magic_beans_refill_to_fixed_ten_only(self):
        self.assertIn('magic_beans', RESOURCES)
        game = Arena()
        game.owned = True
        target = game.addresses[RESOURCES['magic_beans'][0]] + 28
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['magic_beans'])
        self.assertEqual(result['magic_beans'], dict(current=10, capacity=10, unlocked=True))
        self.assertEqual(game.writes, [target])
        self.assertEqual(game.data[target], struct.pack('<ii', 10, 10))
        self.assertEqual(result['bombs']['current'], 2)

    def test_magic_bean_ownership_change_cancels_refill(self):
        self.assertIn('magic_beans', RESOURCES)
        game = Arena()
        with patch.object(game, 'boolean', side_effect=[False, True, False]), \
                patch('memory.K.WriteProcessMemory', side_effect=game.write):
            with self.assertRaises(NotReady):
                game.resources(0x1000, ['magic_beans'])
        self.assertEqual(game.writes, [])

    def test_scrub_seeds_locked_until_obtained_then_refill_to_thirty(self):
        self.assertIn('scrub_seeds', RESOURCES)
        game = Arena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['scrub_seeds'])
            self.assertFalse(result['scrub_seeds']['unlocked'])
            self.assertEqual(game.writes, [])
            game.owned = True
            result = game.resources(0x1000, ['scrub_seeds'])
        self.assertEqual(result['scrub_seeds']['current'], 30)
        self.assertEqual(game.writes, [game.addresses[RESOURCES['scrub_seeds'][0]] + 28])

    def test_magic_stays_locked_until_meter_obtained(self):
        self.assertIn('magic', RESOURCES)
        game = Arena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['magic'])
        self.assertFalse(result['magic']['unlocked'])
        self.assertEqual(game.writes, [])

    def test_magic_refill_follows_existing_meter_capacity(self):
        self.assertIn('magic', RESOURCES)
        for capacity in (240, 480):
            game = Arena()
            game.owned = True
            cap = game.addresses[RESOURCES['magic'][2]] + 28
            game.data[cap] = struct.pack('<i', capacity)
            with patch('memory.K.WriteProcessMemory', side_effect=game.write):
                result = game.resources(0x1000, ['magic'])
            self.assertEqual(result['magic']['current'], capacity)
            self.assertEqual(game.data[cap], struct.pack('<i', capacity))

    def test_health_refills_only_existing_hearts(self):
        self.assertIn('health', RESOURCES)
        game = Arena()
        cap = game.addresses[RESOURCES['health'][2]] + 28
        game.data[cap] = struct.pack('<i', 28)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['health'])
        self.assertEqual(result['health']['current'], 28)
        self.assertEqual(game.data[cap], struct.pack('<i', 28))
        self.assertEqual(len(game.writes), 2)

    def test_health_does_not_write_after_death(self):
        self.assertIn('health', RESOURCES)
        game = Arena()
        target = game.addresses[RESOURCES['health'][0]] + 28
        game.data[target] = bytes(8)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['health'])
        self.assertEqual(result['health']['current'], 0)
        self.assertEqual(game.writes, [])

    def test_bombchus_stay_locked_without_ownership(self):
        self.assertIn('bombchus', RESOURCES)
        game = Arena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['bombchus'])
        self.assertFalse(result['bombchus']['unlocked'])
        self.assertEqual(game.writes, [])

    def test_owned_bombchus_use_current_bomb_bag_capacity(self):
        self.assertIn('bombchus', RESOURCES)
        game = Arena()
        game.owned = True
        cap = game.addresses[RESOURCES['bombs'][2]] + 28
        game.data[cap] = struct.pack('<i', 30)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['bombchus'])
        self.assertEqual(result['bombchus']['current'], 30)
        self.assertEqual(result['bombchus']['capacity'], 30)
        self.assertEqual(result['bombs']['current'], 2)
        self.assertEqual(len(game.writes), 1)

    def test_only_selected_resource_changes_and_both_values_agree(self):
        game = Arena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['rupees'])
        self.assertEqual(result['rupees']['current'], 200)
        self.assertEqual(result['sticks']['current'], 2)
        self.assertEqual(len(game.writes), 1)
        self.assertEqual(game.data[game.addresses[RESOURCES['rupees'][0]] + 28], struct.pack('<ii', 200, 200))

    def test_locked_bag_never_writes(self):
        game = Arena()
        cap = game.addresses[RESOURCES['bombs'][2]] + 28
        target = game.addresses[RESOURCES['bombs'][0]] + 28
        game.data[cap] = struct.pack('<i', 0)
        game.data[target] = bytes(8)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['bombs'])
        self.assertFalse(result['bombs']['unlocked'])
        self.assertEqual(game.writes, [])

    def test_save_change_cancels_write(self):
        game = Arena()
        game.changed = True
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            with self.assertRaises(NotReady):
                game.resources(0x1000, ['rupees'])
        self.assertEqual(game.writes, [])


class MiniArena(Arena):
    def __init__(self, item=2565786591, equipped=9, current=3, capacity=10, active=True):
        super().__init__()
        self.addresses.update({0x76F85E6D: 0x7000, 0xC7324B14: 0x7100, 0x14C1A399: 0x7200})
        self.data[0x701C] = struct.pack('<I', item)
        self.data[0x711C] = struct.pack('<ii', current, current)
        self.data[0x721C] = struct.pack('<i', capacity)
        self.data[Game.BASE + 0x4E371D0] = struct.pack('<Q', 0x8000)
        self.data[0x8480] = struct.pack('<Q', 0x9000)
        self.data[0x9020] = struct.pack('<Q', 0xA000)
        self.data[0xA000] = b'Player\0'
        self.data[0x9270] = struct.pack('<Q', 0xB000)
        self.data[0xB358] = struct.pack('<Q', 0xC000)
        self.data[0xC000] = struct.pack('<Q', Game.BASE + 0x4B4DFC0)
        self.data[0xC7C1] = bytes([active])
        self.data[0xC7DC] = struct.pack('<i', equipped)


class MinigamePolicyTests(unittest.TestCase):
    def test_bowling_refills_temporary_count_to_round_allowance_only(self):
        game = MiniArena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.minigame_resources(0x1000, ['bombchus'])
        self.assertEqual(result, dict(resource='bombchus', current=10, capacity=10))
        self.assertEqual(game.writes, [0x711C])
        self.assertEqual(game.data[0x711C], struct.pack('<ii', 10, 10))
        self.assertEqual(game.data[0x721C], struct.pack('<i', 10))

    def test_rental_arrows_and_seeds_do_not_require_owned_bag(self):
        for item, equipped, resource, capacity in ((1399920009, 30, 'arrows', 20),
                                                   (3852308563, 4, 'seeds', 15)):
            with self.subTest(resource=resource):
                game = MiniArena(item, equipped, capacity=capacity)
                with patch('memory.K.WriteProcessMemory', side_effect=game.write):
                    result = game.minigame_resources(0x1000, [resource])
                self.assertEqual(result['current'], capacity)
                self.assertEqual(game.writes, [0x711C])

    def test_inactive_round_leaves_stale_counter_untouched(self):
        game = MiniArena(active=False)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            self.assertIsNone(game.minigame_resources(0x1000, ['bombchus']))
        self.assertEqual(game.writes, [])

    def test_unselected_ammo_is_read_only(self):
        game = MiniArena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.minigame_resources(0x1000, ['arrows'])
        self.assertEqual(result['current'], 3)
        self.assertEqual(game.writes, [])

    def test_invalid_allowance_or_equipment_cancels_write(self):
        for kwargs in ({'capacity': 0}, {'capacity': 101}, {'current': 11}, {'equipped': 30}):
            game = MiniArena(**kwargs)
            with self.subTest(kwargs=kwargs), patch('memory.K.WriteProcessMemory', side_effect=game.write):
                with self.assertRaises(NotReady):
                    game.minigame_resources(0x1000, ['bombchus'])
            self.assertEqual(game.writes, [])

    def test_unsupported_rental_item_does_not_write(self):
        game = MiniArena(item=2517083565, equipped=18)
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            self.assertIsNone(game.minigame_resources(0x1000, ['bombchus']))
        self.assertEqual(game.writes, [])

    def test_round_ending_before_write_cancels_refill(self):
        game = MiniArena()
        context = game.minigame_context(0x1000)
        with patch.object(game, 'minigame_context', side_effect=[context, None]), \
                patch('memory.K.WriteProcessMemory', side_effect=game.write):
            with self.assertRaises(NotReady):
                game.minigame_resources(0x1000, ['bombchus'])
        self.assertEqual(game.writes, [])


class HealthArena(MiniArena):
    health_target = Game.health_target

    def __init__(self):
        super().__init__()
        self.data[0xB198] = struct.pack('<Q', 0xD000)
        self.data[0xD000] = struct.pack('<Q', Game.BASE + 0x4B48300)
        self.data[0xD018] = struct.pack('<Q', 0x9000)
        self.data[0xD040] = struct.pack('<Q', 0xE000)
        self.data[0xE050] = struct.pack('<Q', Game.BASE + 0x4B486A0)
        self.data[0xE058] = struct.pack('<Q', 0x9000)
        self.data[0xE060] = struct.pack('<QiIQiI', Game.BASE + 0x4B63438, 18, 0x31AB5580,
                                     Game.BASE + 0x4B63438, 28, 0xFBE01DA1)
        self.data[0xE068] = struct.pack('<i', 18)
        cap = self.addresses[RESOURCES['health'][2]] + 28
        self.data[cap] = struct.pack('<i', 28)


class ActiveHealthTests(unittest.TestCase):
    def test_refill_updates_active_binding_and_save_counter(self):
        game = HealthArena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000, ['health'])
        self.assertEqual(result['health']['current'], 28)
        self.assertEqual(game.unpack(0xE068, '<i')[0], 28)
        self.assertEqual(game.writes, [0xE068, game.addresses[RESOURCES['health'][0]] + 28])

    def test_binding_hash_or_owner_mismatch_blocks_all_writes(self):
        for address, value in ((0xE058, struct.pack('<Q', 0x9999)),
                               (0xE060, struct.pack('<QiIQiI', Game.BASE + 0x4B63438, 18, 0,
                                                  Game.BASE + 0x4B63438, 28, 0xFBE01DA1))):
            game = HealthArena()
            game.data[address] = value
            with patch('memory.K.WriteProcessMemory', side_effect=game.write):
                with self.assertRaises(NotReady):
                    game.resources(0x1000, ['health'])
            self.assertEqual(game.writes, [])

    def test_display_uses_authoritative_health_without_writing(self):
        game = HealthArena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000)
        self.assertEqual(result['health']['current'], 18)
        self.assertEqual(game.writes, [])


class MagicArena(MiniArena):
    def magic_target(self, capacity):
        return Game.magic_target(self, capacity)

    def __init__(self, capacity=240):
        super().__init__()
        self.owned = True
        self.data[0xC018] = struct.pack('<Q', 0x9000)
        self.data[0xDB78] = struct.pack('<Q', Game.BASE + 0x4B633F0)
        self.data[0xDB80] = struct.pack('<Q', 0x9000)
        self.data[0xDB98] = struct.pack('<Q', Game.BASE + 0x4B648C8)
        self.data[0xDBAC] = struct.pack('<iIIIi', capacity, 0x76B18200, 0x12D63A97, 0x3AFA3349, 60)
        self.data[0xDBBC] = struct.pack('<i', 60)
        self.data[self.addresses[RESOURCES['magic'][0]] + 28] = struct.pack('<ii', capacity, capacity)
        self.data[self.addresses[RESOURCES['magic'][2]] + 28] = struct.pack('<i', capacity)


class ActiveMagicTests(unittest.TestCase):
    def test_refill_updates_casting_value_even_when_saved_meter_is_full(self):
        for capacity in (240, 480):
            with self.subTest(capacity=capacity):
                game = MagicArena(capacity)
                target = game.addresses[RESOURCES['magic'][0]] + 28
                with patch('memory.K.WriteProcessMemory', side_effect=game.write):
                    result = game.resources(0x1000, ['magic'])
                self.assertEqual(result['magic']['current'], capacity)
                self.assertEqual(game.unpack(0xDBBC, '<i')[0], capacity)
                self.assertEqual(game.writes, [0xDBBC, target])
                self.assertEqual(game.data[0xDBAC][:4], struct.pack('<i', capacity))

    def test_display_reads_casting_value_without_writing(self):
        game = MagicArena()
        with patch('memory.K.WriteProcessMemory', side_effect=game.write):
            result = game.resources(0x1000)
        self.assertEqual(result['magic']['current'], 60)
        self.assertEqual(game.writes, [])

    def test_magic_binding_owner_hash_capacity_and_value_are_validated(self):
        cases = ((0xC018, struct.pack('<Q', 0)), (0xDB78, struct.pack('<Q', 0)),
                 (0xDB80, struct.pack('<Q', 0)), (0xDB98, struct.pack('<Q', 0)),
                 (0xDBAC, struct.pack('<iIIIi', 480, 0x76B18200, 0x12D63A97, 0x3AFA3349, 60)),
                 (0xDBAC, struct.pack('<iIIIi', 240, 0, 0x12D63A97, 0x3AFA3349, 60)),
                 (0xDBAC, struct.pack('<iIIIi', 240, 0x76B18200, 0, 0x3AFA3349, 60)),
                 (0xDBAC, struct.pack('<iIIIi', 240, 0x76B18200, 0x12D63A97, 0, 60)),
                 (0xDBAC, struct.pack('<iIIIi', 240, 0x76B18200, 0x12D63A97, 0x3AFA3349, -1)))
        for address, raw in cases:
            with self.subTest(address=address, raw=raw):
                game = MagicArena()
                game.data[address] = raw
                with patch('memory.K.WriteProcessMemory', side_effect=game.write):
                    with self.assertRaises(NotReady):
                        game.resources(0x1000, ['magic'])
                self.assertEqual(game.writes, [])

    def test_player_change_cancels_magic_refill(self):
        game = MagicArena()
        with patch.object(game, 'magic_target', side_effect=[0xDBBC, 0xEBBC]), \
                patch('memory.K.WriteProcessMemory', side_effect=game.write):
            with self.assertRaises(NotReady):
                game.resources(0x1000, ['magic'])
        self.assertEqual(game.writes, [])


if __name__ == '__main__':
    unittest.main()
