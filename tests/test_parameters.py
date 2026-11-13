import struct
import unittest

from memory import Game, NotReady, StaleParameter


class ParameterMemory(Game):
    def __init__(self):
        self.data, self.writes = {}, []
        for address, fmt, values in [
            (self.BASE + 0x4E371D0, '<Q', (0x1000,)), (0x1480, '<Q', (0x2000,)),
            (0x2020, '<Q', (0x3000,)), (0x2270, '<Q', (0x4000,)),
            (0x4358, '<Q', (0x5000,)), (0x5000, '<Q', (self.BASE + 0x4B4DFC0,)),
            (0x5018, '<Q', (0x2000,)), (0x40A8, '<Q', (0x7000,)),
            (0x7000, '<Q', (self.BASE + 0x4C60D70,)), (0x7030, '<I', (1,)),
            (0x7038, '<Q', (0x8000,)), (0x8000, '<Q', (0x9000,)),
            (0x9000, '<I', (0x6B7E094A,)), (0x9008, '<Q', (0xA000,)),
            (0xA000, '<Q', (self.BASE + 0x4BF9010,)), (0xA150, '<Q', (0xB000,)),
            (0xB000, '<Q', (self.BASE + 0x4B6D1A8,)),
            (0xB010, '<Q', (1,)), (0xB018, '<Q', (0xC000,)),
            (0xC000, '<Q', (0xD000,)), (0xD000, '<Q', (self.BASE + 0x4B6D1A8,)),
            (0xB2A0, '<f', (1.0,)), (0xB330, '<f', (0.55,)), (0xB334, '<f', (0.73,)),
            (0xD2A0, '<f', (0.9,)), (0xD330, '<f', (0.55,)), (0xD334, '<f', (0.7,)),
            (0xD561, '<BBB', (1, 1, 1)),
        ]:
            self.put(address, struct.pack(fmt, *values))
        self.put(0x3000, b'Player\0')

    def put(self, address, raw):
        self.data.update({address+i: value for i, value in enumerate(raw)})

    def read(self, address, size):
        return bytes(self.data.get(address+i, 0) for i in range(size))

    def write_verified(self, address, raw, name):
        self.writes.append((address, raw))
        self.put(address, raw)


class ParameterMemoryTests(unittest.TestCase):
    def test_follows_current_player_and_inherits_real_values(self):
        game = ParameterMemory()
        context = game.player_parameter_context()
        raw, flag, effective = game.parameter_snapshot(context, 'roll')
        self.assertEqual(raw, struct.pack('<f', 1))
        self.assertEqual(flag, 0)
        self.assertAlmostEqual(effective, 0.9)
        self.assertEqual(game.writes, [])

    def test_override_and_restore_preserve_parent_and_other_settings(self):
        game = ParameterMemory()
        context = game.player_parameter_context()
        snapshot = game.parameter_snapshot(context, 'roll')
        game.parameter_replace(context, 'roll', snapshot[:2], struct.pack('<f', 1.8), 1)
        self.assertAlmostEqual(game.parameter_snapshot(context, 'roll')[2], 1.8)
        self.assertEqual(game.read(0xD2A0, 4), struct.pack('<f', 0.9))
        self.assertEqual(game.read(0xB330, 4), struct.pack('<f', 0.55))
        self.assertEqual(game.read(0xB562, 1), b'\0')
        self.assertEqual(game.read(0xB334, 4), struct.pack('<f', 0.73))
        game.parameter_replace(context, 'roll', (struct.pack('<f', 1.8), 1), *snapshot[:2])
        self.assertEqual(game.read(0xB561, 1), b'\0')

    def test_rejects_unrelated_player_or_descriptor(self):
        for address, raw in [(0x5018, struct.pack('<Q', 0x3333)),
                             (0x7000, bytes(8)), (0xA000, bytes(8))]:
            game = ParameterMemory()
            game.put(address, raw)
            with self.assertRaises(NotReady):
                game.player_parameter_context()
            self.assertEqual(game.writes, [])

    def test_swim_offsets_preserve_each_original_value_and_override_flag(self):
        game = ParameterMemory()
        context = game.player_parameter_context()
        for name, offset, flag_offset, value in (
                ('swim', 0x4F4, 0x5BC, 3.3), ('swim_heavy', 0x4EC, 0x5BD, 1.5),
                ('swim_dash', 0x4C4, 0x5BE, 5.0), ('swim_dash_heavy', 0x4BC, 0x5BF, 1.8)):
            game.put(0xB000 + offset, struct.pack('<f', value))
            game.put(0xB000 + flag_offset, b'\1')
            original = game.parameter_snapshot(context, name)
            modified = struct.pack('<f', value * 2)
            game.parameter_replace(context, name, original[:2], modified, 1)
            self.assertAlmostEqual(game.parameter_snapshot(context, name)[2], value * 2, places=5)
            game.parameter_replace(context, name, (modified, 1), *original[:2])
            self.assertEqual(game.parameter_snapshot(context, name)[:2], original[:2])

    def test_reused_resource_cancels_write(self):
        game = ParameterMemory()
        context = game.player_parameter_context()
        game.put(0xA150, struct.pack('<Q', 0xE000))
        with self.assertRaises(NotReady):
            game.parameter_replace(context, 'jump', (struct.pack('<f', 0.73), 0), struct.pack('<f', 1.4), 1)
        self.assertEqual(game.writes, [])

    def test_stale_parent_generation_uses_local_default(self):
        game = ParameterMemory()
        game.put(0xC00C, struct.pack('<I', 8))
        self.assertAlmostEqual(game.parameter_snapshot(game.player_parameter_context(), 'jump')[2], 0.73)

    def test_unmapped_cached_resource_is_reported_as_stale(self):
        game = ParameterMemory()
        context = game.player_parameter_context()
        def unavailable(*_):
            raise NotReady('Unmapped allocation')
        game.read = unavailable
        with self.assertRaises(StaleParameter):
            game.validate_parameter_context(context)
        self.assertEqual(game.writes, [])


if __name__ == '__main__':
    unittest.main()
