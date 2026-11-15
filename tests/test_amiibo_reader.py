import importlib.util
import ctypes
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from amiibo_catalog import PRESETS
from memory import NotReady


class Calls:
    def __init__(self):
        self.pending = False
        self.requests = []
        self.result = None

    def begin(self, game, address, argument=b''):
        if self.pending:
            raise NotReady('Reader busy')
        self.requests.append((address, argument))
        self.pending = True

    def poll(self):
        if self.result is None:
            return None
        value, self.result, self.pending = self.result, None, False
        return value


class AmiiboReaderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('amiibo_reader'))
        import amiibo_reader
        self.api = amiibo_reader
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = SimpleNamespace(state=lambda: (1, 'HyruleField_Child', (0, 0, 0)),
                                    alive=lambda: True,
                                    executable=Path(self.temp.name) / 'game/ocarina.exe')
        self.calls = Calls()
        self.reader = amiibo_reader.AmiiboReader(PRESETS, self.calls)
        self.layout = SimpleNamespace(reader=100, scan=200, remove=300)
        self.guard = patch('amiibo_reader.reader_layout', return_value=self.layout)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_send_queries_first_and_sends_only_one_selected_identity(self):
        choice = PRESETS[2]
        self.reader.begin_send(self.game, choice)
        self.assertEqual(self.calls.requests, [(100, b'')])
        self.assertIsNone(self.reader.poll())
        self.calls.result = 1
        self.assertIsNone(self.reader.poll())
        self.assertEqual(len(self.calls.requests), 2)
        address, raw_path = self.calls.requests[1]
        self.assertEqual(address, 200)
        path = Path(raw_path[:-1].decode('utf-8'))
        self.assertEqual(path.parent, self.game.executable.parent / 'amiibo/NaviScout')
        self.assertEqual(path.read_bytes()[0x54:0x5c], bytes.fromhex(choice.tag_id))
        self.calls.result = 0x123401
        self.assertEqual(self.reader.poll(), 'sent')
        self.assertFalse(self.reader.pending)

    def test_not_searching_never_loads_or_taps_a_tag(self):
        for state in (0, 2, 3, 4, 5):
            with self.subTest(state=state):
                self.reader.begin_send(self.game, PRESETS[0])
                self.calls.result = state
                self.assertEqual(self.reader.poll(), 'not-ready')
        self.assertTrue(all(address == 100 for address, _ in self.calls.requests))
        self.assertFalse((Path(self.temp.name) / 'media').exists())

    def test_repeat_click_does_not_queue_a_second_scan(self):
        self.reader.begin_send(self.game, PRESETS[0])
        with self.assertRaises(NotReady):
            self.reader.begin_send(self.game, PRESETS[1])
        self.assertEqual(len(self.calls.requests), 1)

    def test_close_during_query_waits_then_cancels_without_sending(self):
        self.reader.begin_send(self.game, PRESETS[0])
        with self.assertRaises(NotReady):
            self.reader.restore(self.game)
        self.calls.result = 1
        self.reader.restore(self.game)
        self.assertEqual(len(self.calls.requests), 1)
        self.assertFalse(self.reader.pending)

    def test_remove_is_one_native_request(self):
        self.reader.begin_remove(self.game)
        self.assertEqual(self.calls.requests, [(300, b'')])
        self.calls.result = 12345
        self.assertEqual(self.reader.poll(), 'removed')

    def test_code_validation_failure_does_not_make_a_native_request(self):
        self.guard.stop()
        with patch('amiibo_reader.reader_layout', side_effect=ValueError('Unknown code')):
            with self.assertRaises(ValueError):
                self.reader.begin_send(self.game, PRESETS[0])
        self.assertEqual(self.calls.requests, [])

    def test_current_game_is_revalidated_before_the_actual_tap(self):
        self.reader.begin_send(self.game, PRESETS[0])
        self.calls.result = 1
        self.game.state = lambda: (_ for _ in ()).throw(NotReady('Scene changing'))
        with self.assertRaises(NotReady):
            self.reader.poll()
        self.assertEqual(len(self.calls.requests), 1)
        self.assertFalse(self.reader.pending)


class NativeCallLifetimeTests(unittest.TestCase):
    def setUp(self):
        from amiibo_reader import NativeCalls
        self.calls = NativeCalls()
        self.calls.game = SimpleNamespace(alive=lambda: True)
        self.calls.process, self.calls.thread, self.calls.argument = 10, 20, 30

    def test_waiting_thread_keeps_its_argument_and_handles(self):
        with patch('amiibo_reader.K.WaitForSingleObject', return_value=258), \
             patch('amiibo_reader.K.VirtualFreeEx') as free, \
             patch('amiibo_reader.K.CloseHandle') as close:
            self.assertIsNone(self.calls.poll())
            free.assert_not_called()
            close.assert_not_called()
        self.assertTrue(self.calls.pending)
        self.assertEqual(self.calls.argument, 30)

    def test_completed_thread_is_read_before_its_argument_is_freed(self):
        order = []
        def result(_handle, value):
            order.append('result')
            ctypes.cast(value, ctypes.POINTER(ctypes.c_ulong))[0] = 1
            return 1
        with patch('amiibo_reader.K.WaitForSingleObject', return_value=0), \
             patch('amiibo_reader.K.GetExitCodeThread', side_effect=result), \
             patch('amiibo_reader.K.VirtualFreeEx', side_effect=lambda *_: order.append('free') or 1), \
             patch('amiibo_reader.K.CloseHandle') as close:
            self.assertEqual(self.calls.poll(), 1)
            self.assertEqual(order, ['result', 'free'])
            self.assertEqual(close.call_count, 2)
        self.assertFalse(self.calls.pending)

    def test_failed_wait_retains_resources_for_retry(self):
        with patch('amiibo_reader.K.WaitForSingleObject', return_value=0xFFFFFFFF), \
             patch('amiibo_reader.K.VirtualFreeEx') as free, \
             patch('amiibo_reader.K.CloseHandle') as close:
            with self.assertRaises(OSError):
                self.calls.poll()
            free.assert_not_called()
            close.assert_not_called()
        self.assertTrue(self.calls.pending)

    def test_finished_request_for_exited_game_only_closes_handles(self):
        self.calls.game.alive = lambda: False
        with patch('amiibo_reader.K.WaitForSingleObject', return_value=0), \
             patch('amiibo_reader.K.GetExitCodeThread', return_value=1), \
             patch('amiibo_reader.K.VirtualFreeEx') as free, \
             patch('amiibo_reader.K.CloseHandle') as close:
            self.calls.poll()
            free.assert_not_called()
            self.assertEqual(close.call_count, 2)


if __name__ == '__main__':
    unittest.main()
