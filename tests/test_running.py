import ctypes as C
import hashlib
import struct
import unittest
from unittest.mock import patch

from memory import K, NotReady
from running import CALL_RVA, ORIGINAL_CALL, RunSpeed, RunLayout, ThreadEntry, relative_call, run_stub, select_layout


class RunSpeedTests(unittest.TestCase):
    def test_layout_selection_validates_callback_call_and_velocity_helper(self):
        from types import SimpleNamespace
        base = 0x100000
        call = relative_call(base + 0x108, base + 0x400)
        function = bytes(8) + call + bytes(3)
        helper = b'verified velocity helper'
        layout = RunLayout(0x100, len(function), hashlib.sha256(function).hexdigest(),
                           0x108, 0x400, call, len(helper), hashlib.sha256(helper).hexdigest())
        old = RunLayout(0x200, 16, 'unrecognized', 0x208, 0x300, b'other')
        data = {base + 0x100: function, base + 0x108: call, base + 0x400: helper}
        game = SimpleNamespace(read=lambda address, size: data.get(address, bytes(size)))
        with patch('running.RUN_LAYOUTS', (old, layout)):
            self.assertIs(select_layout(game, base, 0x1000), layout)
            data[base + 0x400] = b'changed velocity helper!'
            with self.assertRaises(ValueError):
                select_layout(game, base, 0x1000)
            data[base + 0x400] = helper
            data[base + 0x108] = b'other'
            with self.assertRaises(ValueError):
                select_layout(game, base, 0x1000)

    def test_layout_selection_never_reads_beyond_module_bounds(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        read = Mock()
        with self.assertRaises(ValueError):
            select_layout(SimpleNamespace(read=read), 0x1000, 1)
        read.assert_not_called()

    def test_relative_call_reaches_its_target_and_rejects_overflow(self):
        for target in (0x2000, 0x7000):
            instruction = relative_call(0x4000, target)
            self.assertEqual(0x4005 + struct.unpack('<i', instruction[1:])[0], target)
        with self.assertRaises(ValueError):
            relative_call(0, 1 << 40)

    def test_native_stub_doubles_only_translation_magnitude(self):
        observed = []
        callback_type = C.CFUNCTYPE(None, C.c_void_p)
        callback = callback_type(lambda cpu: observed.append(C.string_at(cpu, 1088)))
        raw = run_stub(C.cast(callback, C.c_void_p).value)
        process = C.c_void_p(-1)
        address = K.VirtualAllocEx(process, None, 4096, 0x3000, 0x40)
        self.assertTrue(address)
        try:
            C.memmove(address, raw, len(raw))
            self.assertTrue(K.FlushInstructionCache(process, address, len(raw)))
            function = callback_type(address)
            for speed in (0.0, 0.01, 3.3, 5.0):
                layout = bytearray([0x35] * 1088)
                struct.pack_into('<Q', layout, 0, 0x1739EFD18)
                struct.pack_into('<4f', layout, 512, speed, 7, 8, 9)
                cpu = C.create_string_buffer(bytes(layout))
                function(C.addressof(cpu))
                values = struct.unpack_from('<4f', observed[-1], 512)
                self.assertAlmostEqual(values[0], speed * 2, places=5)
                self.assertEqual(values[1:], (7, 8, 9))
                self.assertEqual(observed[-1][:512], layout[:512])
                self.assertEqual(observed[-1][516:], layout[516:])
        finally:
            self.assertTrue(K.VirtualFreeEx(process, address, 0, 0x8000))

    def test_off_never_touches_the_process(self):
        control = RunSpeed()
        control.update(None, False)

    def exercise_pause_failure(self, context_failure):
        from contextlib import ExitStack
        from types import SimpleNamespace
        resumed, closed = [], []
        position = [0]

        def entry(pointer, first=False):
            position[0] = 0 if first else position[0] + 1
            if position[0] >= 2:
                return 0
            value = C.cast(pointer, C.POINTER(ThreadEntry)).contents
            value.pid, value.tid = 123, position[0] + 1
            return 1

        def context(handle, address):
            if context_failure and handle == 102:
                C.set_last_error(5)
                return 0
            C.c_uint64.from_address(address + 248).value = 0x3000
            return 1

        replacements = dict(CreateToolhelp32Snapshot=lambda *_: 50,
                            Thread32First=lambda _, pointer: entry(pointer, True),
                            Thread32Next=lambda _, pointer: entry(pointer),
                            OpenThread=lambda _, __, tid: 100 + tid,
                            SuspendThread=lambda _: 0, GetThreadContext=context,
                            ResumeThread=lambda handle: resumed.append(handle) or 0,
                            CloseHandle=lambda handle: closed.append(handle) or 1)
        with ExitStack() as stack:
            for name, replacement in replacements.items():
                stack.enter_context(patch.object(K, name, replacement))
            with self.assertRaises(OSError):
                with RunSpeed().paused(SimpleNamespace(pid=123), [(0x4000, 0x4005)]):
                    raise OSError('Simulated code replacement failure')
        self.assertEqual(resumed, [102, 101])
        self.assertIn(101, closed)
        self.assertIn(102, closed)

    def test_context_failure_resumes_every_suspended_thread(self):
        self.exercise_pause_failure(True)

    def test_write_failure_resumes_every_suspended_thread(self):
        self.exercise_pause_failure(False)

    def test_failed_instruction_verification_rolls_back_before_returning(self):
        from types import SimpleNamespace
        current, writes = [ORIGINAL_CALL], []

        def write(_address, raw, _name):
            current[0] = raw
            writes.append(raw)
            if len(writes) == 1:
                raise OSError('Injected verification failure after write')

        game = SimpleNamespace(handle=4, read=lambda *_: current[0], write_verified=write)
        with patch.object(K, 'VirtualProtectEx', return_value=1), \
             patch.object(K, 'FlushInstructionCache', return_value=1):
            with self.assertRaisesRegex(OSError, 'Injected verification'):
                RunSpeed().code_write(game, 0x1000, ORIGINAL_CALL, b'12345')
        self.assertEqual(writes, [b'12345', ORIGINAL_CALL])
        self.assertEqual(current[0], ORIGINAL_CALL)

    def test_old_process_override_is_never_written_into_a_new_process(self):
        from types import SimpleNamespace
        control = RunSpeed()
        control.base, control.stub = 0x1000, 0x9000
        control.owner = SimpleNamespace(alive=lambda: False)
        control.restore(SimpleNamespace())
        self.assertIsNone(control.stub)

    def test_restore_preserves_an_external_code_change(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        control = RunSpeed()
        control.base, control.stub, control.replacement = 0x1000, 0x9000, b'12345'
        game = SimpleNamespace(read=lambda *_: b'other', handle=123)
        control.owner = game
        with patch.object(control, 'paused', return_value=nullcontext()), patch.object(K, 'VirtualFreeEx') as free:
            with self.assertRaises(NotReady):
                control.restore(game)
            free.assert_not_called()
        self.assertEqual(control.stub, 0x9000)

    def test_restore_reverts_call_before_freeing_the_stub(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        control = RunSpeed()
        control.base, control.stub, control.replacement = 0x1000, 0x9000, b'12345'
        calls = []
        game = SimpleNamespace(read=lambda *_: b'12345', handle=123)
        control.owner = game
        with patch.object(control, 'paused', return_value=nullcontext()), \
             patch.object(control, 'code_write', side_effect=lambda *args: calls.append(args[1:])), \
             patch.object(K, 'VirtualFreeEx', side_effect=lambda *_: calls.append('free') or 1):
            control.restore(game)
        self.assertEqual(calls, [(0x1000 + CALL_RVA, b'12345', ORIGINAL_CALL), 'free'])
        self.assertIsNone(control.stub)

    def test_restore_uses_the_installed_layout_after_a_port_update(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from running import RUN_LAYOUTS
        control = RunSpeed()
        control.base, control.stub, control.replacement = 0x1000, 0x9000, b'12345'
        control.layout = RUN_LAYOUTS[1]
        game = SimpleNamespace(read=lambda *_: b'12345', handle=123)
        control.owner = game
        with patch.object(control, 'paused', return_value=nullcontext()), \
             patch.object(control, 'code_write') as write, patch.object(K, 'VirtualFreeEx', return_value=1):
            control.restore(game)
        write.assert_called_once_with(game, 0x1000 + control.layout.call_rva, b'12345', control.layout.original_call)


if __name__ == '__main__':
    unittest.main()
