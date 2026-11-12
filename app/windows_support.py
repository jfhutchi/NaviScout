"""Windows process matching and per-user shortcut creation."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import uuid


def executable_running(executable):
    from memory import K, ProcessEntry
    expected = Path(executable).resolve()
    snapshot = K.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        entry = ProcessEntry()
        entry.size = C.sizeof(entry)
        found = K.Process32FirstW(snapshot, C.byref(entry))
        while found:
            if entry.exe.lower() == expected.name.lower():
                handle = K.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    raise OSError('Cannot inspect the running game. Run both applications as the same user.')
                try:
                    path, length = C.create_unicode_buffer(32768), W.DWORD(32768)
                    if not K.QueryFullProcessImageNameW(handle, 0, path, C.byref(length)):
                        raise C.WinError(C.get_last_error())
                    if Path(path.value).resolve() == expected:
                        return True
                finally:
                    K.CloseHandle(handle)
            found = K.Process32NextW(snapshot, C.byref(entry))
    finally:
        K.CloseHandle(snapshot)
    return False


class GUID(C.Structure):
    _fields_ = [('bytes', C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def shell_shortcut(destination, target, arguments='', description='Navi Scout'):
    ole = C.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [C.c_void_p, W.DWORD]
    ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, W.DWORD, C.POINTER(GUID), C.POINTER(C.c_void_p)]
    initialized = ole.CoInitializeEx(None, 2)
    link, persist = C.c_void_p(), C.c_void_p()

    def call(pointer, index, types, *args):
        table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
        method = C.WINFUNCTYPE(C.c_long, C.c_void_p, *types)(table[index])
        result = method(pointer, *args)
        if result < 0:
            raise OSError(f'Windows shortcut operation failed: {result & 0xFFFFFFFF:08X}')

    try:
        clsid = GUID.parse('00021401-0000-0000-c000-000000000046')
        iid = GUID.parse('000214f9-0000-0000-c000-000000000046')
        result = ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(link))
        if result < 0:
            raise OSError('Windows could not create the Navi Scout shortcut.')
        call(link, 20, [W.LPCWSTR], str(Path(target).resolve()))
        call(link, 9, [W.LPCWSTR], str(Path(target).resolve().parent))
        call(link, 7, [W.LPCWSTR], description)
        call(link, 11, [W.LPCWSTR], arguments)
        iid = GUID.parse('0000010b-0000-0000-c000-000000000046')
        call(link, 0, [C.POINTER(GUID), C.POINTER(C.c_void_p)], C.byref(iid), C.byref(persist))
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        call(persist, 6, [W.LPCWSTR, W.BOOL], str(destination.resolve()), True)
    finally:
        for pointer in (persist, link):
            if pointer.value:
                table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
                C.WINFUNCTYPE(W.ULONG, C.c_void_p)(table[2])(pointer)
        if initialized >= 0:
            ole.CoUninitialize()
