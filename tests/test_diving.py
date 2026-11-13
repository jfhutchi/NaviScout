import unittest

from diving import DiveLimit
from memory import NotReady
from test_parameters import ParameterMemory


class DiveGame:
    def __init__(self):
        self.context = dict(identity=(1, 2), phase=2, depth=6.0)
        self.writes = []

    def dive_context(self):
        return dict(self.context) if self.context else None

    def set_dive_depth(self, context, expected, value):
        if context['identity'] != self.context['identity'] or expected != self.context['depth']:
            raise NotReady('Dive changed')
        self.context['depth'] = value
        self.writes.append(value)


class DiveTests(unittest.TestCase):
    def test_off_does_not_write(self):
        game, control = DiveGame(), DiveLimit()
        control.update(game, 'Off')
        self.assertEqual(game.writes, [])

    def test_double_uses_current_scale_and_does_not_compound(self):
        for base in (3.0, 6.0, 9.0):
            game, control = DiveGame(), DiveLimit()
            game.context['depth'] = base
            for _ in range(3):
                control.update(game, '2x')
            self.assertEqual(game.context['depth'], base * 2)
            self.assertEqual(len(game.writes), 1)

    def test_unlimited_then_off_restores_native_limit(self):
        game, control = DiveGame(), DiveLimit()
        control.update(game, 'Unlimited')
        self.assertEqual(game.context['depth'], 100000.0)
        control.update(game, 'Off')
        self.assertEqual(game.context['depth'], 6)

    def test_new_dive_and_new_scale_are_recaptured(self):
        game, control = DiveGame(), DiveLimit()
        game.context['depth'] = 3
        control.update(game, '2x')
        game.context['phase'] = 7
        control.update(game, '2x')
        game.context.update(phase=2, depth=6)
        control.update(game, '2x')
        self.assertEqual(game.context['depth'], 12)

    def test_new_actor_never_receives_old_restore(self):
        game, control = DiveGame(), DiveLimit()
        control.update(game, 'Unlimited')
        game.context = dict(identity=(3, 4), phase=0, depth=9)
        control.update(game, 'Off')
        self.assertEqual(game.context['depth'], 9)
        self.assertEqual(len(game.writes), 1)

    def test_written_value_can_be_restored_after_verification_failure(self):
        game, control = DiveGame(), DiveLimit()
        setter = game.set_dive_depth
        def fail_after_write(*args):
            setter(*args)
            raise OSError('Read-back failed')
        game.set_dive_depth = fail_after_write
        with self.assertRaises(OSError):
            control.update(game, 'Unlimited')
        game.set_dive_depth = setter
        control.update(game, 'Off')
        self.assertEqual(game.context['depth'], 6)

    def test_failed_mode_change_can_restore_the_previous_owned_value(self):
        game, control = DiveGame(), DiveLimit()
        control.update(game, '2x')
        setter = game.set_dive_depth
        def fail_before_write(*_):
            raise OSError('Write failed')
        game.set_dive_depth = fail_before_write
        with self.assertRaises(OSError):
            control.update(game, 'Unlimited')
        game.set_dive_depth = setter
        control.update(game, 'Off')
        self.assertEqual(game.context['depth'], 6)


class DiveMemory(ParameterMemory):
    def __init__(self):
        super().__init__()
        import struct
        for address, fmt, values in [
            (0x2008, '<Q', (0x10000,)), (0x10000, '<Q', (self.BASE + 0x4BF78E0,)),
            (0x10518, '<Q', (0x11000,)), (0x11000, '<Q', (self.BASE + 0x4B47190,)),
            (0x11018, '<Q', (0x2000,)), (0x11440, '<Q', (0x12000,)),
            (0x12000, '<I', (1,)), (0x12008, '<Q', (0x13000,)),
            (0x13000, '<Q', (0x14000,)), (0x14018, '<Q', (0x15000,)),
            (0x15000, '<Q', (self.BASE + 0x4B479E8,)), (0x151F0, '<Q', (0x2000,)),
            (0x15018, '<I', (1,)), (0x15020, '<Q', (0x16000,)),
            (0x16000, '<Q', (0x17000,)), (0x17000, '<Q', (self.BASE + 0x4C26670,)),
            (0x17008, '<Q', (0x15000,)), (0x17060, '<I', (1,)),
            (0x17068, '<Q', (0x18000,)), (0x18000, '<Q', (0x19000,)),
            (0x19000, '<Q', (self.BASE + 0x49CAC00,)), (0x19008, '<Q', (0x17000,)),
            (0x19020, '<I', (2,)), (0x19030, '<f', (6,)),
        ]:
            self.put(address, struct.pack(fmt, *values))


class DiveMemoryTests(unittest.TestCase):
    def test_discovers_only_links_dive_node_without_writes(self):
        game = DiveMemory()
        context = game.dive_context()
        self.assertEqual(context['depth'], 6)
        self.assertEqual(context['phase'], 2)
        self.assertEqual(game.writes, [])

    def test_writes_only_depth_after_rechecking_context(self):
        import struct
        game = DiveMemory()
        context = game.dive_context()
        game.set_dive_depth(context, 6, 12)
        self.assertEqual(game.writes, [(0x19030, struct.pack('<f', 12))])

    def test_foreign_owner_or_changed_phase_never_writes(self):
        import struct
        game = DiveMemory()
        context = game.dive_context()
        game.put(0x19020, struct.pack('<I', 7))
        with self.assertRaises(NotReady):
            game.set_dive_depth(context, 6, 12)
        game.put(0x151F0, struct.pack('<Q', 0xBAD))
        self.assertIsNone(game.dive_context())
        self.assertEqual(game.writes, [])

    def test_replaced_arrays_or_removed_module_invalidate_cached_slots(self):
        import struct
        for address in (0x15020, 0x17068, 0x13000):
            game = DiveMemory()
            context = game.dive_context()
            game.put(address, struct.pack('<Q', 0x99900 if address != 0x13000 else 0))
            self.assertFalse(game.validate_dive_identity(context['identity']))
            self.assertEqual(game.writes, [])


if __name__ == '__main__':
    unittest.main()
