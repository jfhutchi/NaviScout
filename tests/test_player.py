import struct
import unittest

from player import PlayerModifiers
from memory import NotReady, StaleParameter


class ParameterGame:
    def __init__(self):
        self.context = (100, 200, b'parameter identity')
        self.values = {'roll': (1.0, 0, 0.55), 'jump': (0.73, 0, 0.7),
                       'swim': (3.3, 1, 3.3), 'swim_heavy': (1.0, 0, 1.5),
                       'swim_dash': (5.0, 0, 5.0), 'swim_dash_heavy': (2.0, 1, 2.0)}
        self.writes = []
        self.valid = True

    def player_parameter_context(self):
        return self.context

    def parameter_snapshot(self, context, name):
        value, flag, effective = self.values[name]
        return struct.pack('<f', value), flag, effective

    def parameter_replace(self, context, name, expected, value, flag):
        if not self.valid:
            raise NotReady('Parameter changed')
        old, old_flag, effective = self.parameter_snapshot(context, name)
        if (old, old_flag) != expected:
            raise NotReady('Another writer changed parameter')
        self.values[name] = (struct.unpack('<f', value)[0], flag, effective)
        self.writes.append((name, value, flag))


class PlayerModifierTests(unittest.TestCase):
    def test_off_never_writes(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, False, False)
        self.assertEqual(game.writes, [])

    def test_doubles_effective_inherited_values_without_compounding(self):
        game, control = ParameterGame(), PlayerModifiers()
        for _ in range(3):
            control.update(game, jump=True, roll=True)
        self.assertAlmostEqual(game.values['roll'][0], 1.1)
        self.assertAlmostEqual(game.values['jump'][0], 1.4)
        self.assertEqual(len(game.writes), 2)

    def test_off_restores_original_bytes_and_inheritance_flags(self):
        game, control = ParameterGame(), PlayerModifiers()
        originals = {name: game.parameter_snapshot(game.context, name)[:2] for name in game.values}
        control.update(game, jump=True, roll=True)
        control.update(game, False, False)
        for name in game.values:
            self.assertEqual(game.parameter_snapshot(game.context, name)[:2], originals[name])
        self.assertFalse(control.patches)

    def test_independent_switches_and_close_restore(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, roll=True)
        self.assertEqual(game.values['jump'][1], 0)
        control.update(game, jump=True)
        self.assertEqual(game.values['roll'][1], 0)
        control.restore(game)
        self.assertEqual(game.values['jump'][1], 0)

    def test_run_switch_doubles_all_swimming_modes_independently_of_roll(self):
        game, control = ParameterGame(), PlayerModifiers()
        originals = {name: game.parameter_snapshot(game.context, name)[:2] for name in game.values}
        control.update(game, run=True)
        for name, expected in [('swim', 6.6), ('swim_heavy', 3.0),
                               ('swim_dash', 10.0), ('swim_dash_heavy', 4.0)]:
            self.assertAlmostEqual(game.values[name][0], expected, places=5)
        self.assertEqual(game.values['roll'][1], 0)
        self.assertEqual(game.values['jump'][1], 0)
        control.update(game)
        for name in game.values:
            self.assertEqual(game.parameter_snapshot(game.context, name)[:2], originals[name])

    def test_changed_resource_is_rejected_without_writes(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, roll=True)
        game.valid = False
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertEqual(len(game.writes), 1)

    def test_external_writer_is_preserved(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, roll=True)
        game.values['roll'] = (1.8, 1, 0.55)
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertEqual(game.values['roll'][0], 1.8)

    def test_freed_resource_does_not_block_a_new_scene(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, roll=True)
        old = game.context
        game.context = (100, 300, b'new parameter identity')
        snapshot = game.parameter_snapshot

        def current(context, name):
            if context == old:
                raise StaleParameter('Freed resource')
            return snapshot(context, name)

        game.parameter_snapshot = current
        game.values['roll'] = (1.0, 0, 0.55)
        control.update(game, roll=True)
        self.assertEqual(control.patches['roll'].context, game.context)
        self.assertEqual(len(game.writes), 2)

    def test_conflicting_roll_does_not_prevent_jump_restoration(self):
        game, control = ParameterGame(), PlayerModifiers()
        control.update(game, jump=True, roll=True)
        game.values['roll'] = (1.8, 1, 0.55)
        with self.assertRaises(NotReady):
            control.restore(game)
        self.assertAlmostEqual(game.values['jump'][0], 0.73)
        self.assertEqual(game.values['jump'][1], 0)
        self.assertEqual(game.values['roll'][0], 1.8)


if __name__ == '__main__':
    unittest.main()
