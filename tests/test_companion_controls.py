from pathlib import Path
import tempfile
import unittest

from companion import Companion, migrate_preferences


class CompanionControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Companion(Path(self.temp.name), Path(self.temp.name), demo=True)

    def tearDown(self):
        for job in self.app.root.tk.call('after', 'info'):
            self.app.root.after_cancel(job)
        self.app.root.destroy()
        self.temp.cleanup()

    def test_separate_assist_and_progress_sections(self):
        self.assertEqual([self.app.controls.tab(tab, 'text') for tab in self.app.controls.tabs()],
                         ['Items', 'Link', 'Minigames', 'Progress'])

    def test_new_movement_switches_default_off(self):
        self.assertFalse(self.app.run_speed.get())
        self.assertFalse(self.app.roll_speed.get())
        self.assertFalse(self.app.invisible.get())
        self.assertFalse(self.app.jump_height.get())
        self.assertFalse(self.app.damage_2x.get())
        self.assertEqual(self.app.dive_mode.get(), 'Off')

    def test_refill_buttons_are_independent(self):
        self.app.once = self.app.link_once = False
        self.app.refill_link_once()
        self.assertTrue(self.app.link_once)
        self.assertFalse(self.app.once)
        self.app.link_once = False
        self.app.refill_once()
        self.assertFalse(self.app.link_once)
        self.assertTrue(self.app.once)

    def test_new_controls_are_persisted_separately(self):
        preferences = self.app.preference_vars()
        self.assertIs(preferences['link_auto'], self.app.link_auto)
        self.assertIs(preferences['run_speed'], self.app.run_speed)
        self.assertIs(preferences['roll_speed'], self.app.roll_speed)
        self.assertIs(preferences['jump_height'], self.app.jump_height)
        self.assertIs(preferences['damage_2x'], self.app.damage_2x)
        self.assertIsNot(preferences['auto'], preferences['link_auto'])

    def test_run_signature_failure_does_not_disable_jump_or_roll(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.app.game = SimpleNamespace(alive=lambda: True, state=lambda: None)
        self.app.run_modifier = SimpleNamespace(update=Mock(side_effect=ValueError('Unrecognized running code')))
        update = Mock()
        self.app.player_modifiers = SimpleNamespace(update=update)
        self.app.run_speed.set(True)
        self.app.jump_height.set(True)
        self.app.roll_speed.set(True)
        with self.assertLogs(level='ERROR'):
            self.app.refresh_player()
        self.assertFalse(self.app.run_speed.get())
        self.assertTrue(self.app.jump_height.get())
        self.assertTrue(self.app.roll_speed.get())
        update.assert_called_once_with(self.app.game, False, True, True)

    def test_busy_running_update_does_not_delay_jump_or_roll(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from memory import NotReady
        self.app.game = SimpleNamespace(alive=lambda: True, state=lambda: None)
        self.app.run_modifier = SimpleNamespace(update=Mock(side_effect=NotReady('Running callback busy')))
        update = Mock()
        self.app.player_modifiers = SimpleNamespace(update=update)
        self.app.jump_height.set(True)
        self.app.refresh_player()
        self.assertTrue(self.app.jump_height.get())
        update.assert_called_once_with(self.app.game, False, True, False)

    def test_legacy_refills_off_do_not_enable_round_ammo(self):
        settings = migrate_preferences(dict(auto=False, minigames=True, refill_arrows=False))
        self.assertFalse(settings['minigames'])
        self.assertFalse(settings['link_auto'])
        self.assertFalse(settings['minigame_refill_arrows'])

    def test_migrated_round_switch_is_independent(self):
        settings = dict(auto=False, minigames=True, link_auto=False, minigame_refill_arrows=True)
        self.assertTrue(migrate_preferences(settings)['minigames'])

    def test_old_run_switch_preserves_roll_boost_without_enabling_new_hook(self):
        settings = migrate_preferences(dict(run_speed=True))
        self.assertTrue(settings['roll_speed'])
        self.assertFalse(settings['run_speed'])
        settings = migrate_preferences(dict(run_swim_v2=True, run_speed=True, roll_speed=False))
        self.assertTrue(settings['run_speed'])
        self.assertFalse(settings['roll_speed'])

    def test_close_keeps_helper_alive_until_enemy_stealth_cleanup_acknowledges(self):
        from types import SimpleNamespace
        from memory import NotReady

        def pending(_game):
            raise NotReady('Resume play briefly to restore enemy detection')

        self.app.game = SimpleNamespace(alive=lambda: True)
        self.app.enemy_stealth = SimpleNamespace(restore=pending)
        self.app.invisible.set(True)
        self.app.close()
        self.assertTrue(self.app.root.winfo_exists())
        self.assertTrue(self.app.stopped)
        self.assertFalse(self.app.invisible.get())
        self.assertIn('Resume play', self.app.status.get())

    def test_damage_cleanup_failure_does_not_skip_enemy_stealth_cleanup(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        restore = Mock()
        self.app.game = SimpleNamespace(alive=lambda: True, close=lambda: None)
        self.app.enemy_damage = SimpleNamespace(restore=Mock(side_effect=OSError('Damage restore failed')))
        self.app.enemy_stealth = SimpleNamespace(restore=restore)
        with patch('companion.messagebox.showwarning'), patch.object(self.app.root, 'destroy'), \
             self.assertLogs(level='ERROR'):
            self.app.close()
        restore.assert_called_once_with(self.app.game)


if __name__ == '__main__':
    unittest.main()
