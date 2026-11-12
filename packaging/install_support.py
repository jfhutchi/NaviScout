"""Offline per-user installation, payload validation and Windows app registration."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import time
import winreg
import zipfile

from settings import APP_ID, VERSION, atomic_json
from windows_support import executable_running, shell_shortcut

UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NaviScout'


def install_dir():
    return Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'NaviScout'


def shortcut_paths():
    # The Known Folder API honors redirected and OneDrive-backed desktops.
    import ctypes as C
    from ctypes import wintypes as W
    from windows_support import GUID
    shell = C.OleDLL('shell32')
    shell.SHGetKnownFolderPath.argtypes = [C.POINTER(GUID), W.DWORD, W.HANDLE, C.POINTER(C.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = C.c_long
    ole = C.OleDLL('ole32')
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    folder = C.c_wchar_p()
    guid = GUID.parse('b4bfcc3a-db2c-424c-b029-7fe99a87c641')
    result = shell.SHGetKnownFolderPath(C.byref(guid), 0, None, C.byref(folder))
    if result < 0:
        raise OSError('Windows could not locate your Desktop folder.')
    try:
        desktop = Path(folder.value)
    finally:
        ole.CoTaskMemFree(C.cast(folder, C.c_void_p))
    menu = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Navi Scout'
    return desktop / 'Navi Scout.lnk', menu


def extract_payload(payload, target):
    target = Path(target).resolve()
    with zipfile.ZipFile(payload) as archive:
        total = 0
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if (name.is_absolute() or '..' in name.parts or '\\' in member.orig_filename or ':' in member.filename
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('The installation payload contains an unsafe path.')
            destination = (target / member.filename).resolve()
            if not destination.is_relative_to(target):
                raise ValueError('The installation payload escapes its destination.')
            total += member.file_size
            if total > 250 * 1024 * 1024:
                raise ValueError('The installation payload exceeds its size limit.')
        archive.extractall(target)
    manifest_path = target / 'payload-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['app_id'] != APP_ID:
        raise ValueError('The installation payload is for another application.')
    expected = set()
    for row in manifest['files']:
        path = (target / row['path']).resolve()
        if not path.is_relative_to(target) or not path.is_file():
            raise ValueError('Invalid file in the installation manifest.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'Installation payload checksum failed: {row["path"]}')
        expected.add(path)
    actual = {p.resolve() for p in target.rglob('*') if p.is_file() and p != manifest_path}
    if expected != actual:
        raise ValueError('The installation payload file list does not match its manifest.')
    return manifest


def install(payload, setup_executable, desktop=True):
    if install_dir().is_symlink() or install_dir().is_junction():
        raise ValueError('The installation directory is a filesystem link; installation stopped.')
    target = install_dir().resolve()
    marker = target / 'install-manifest.json'
    if target.exists():
        if not marker.is_file() or json.loads(marker.read_text())['app_id'] != APP_ID:
            raise ValueError('The NaviScout installation folder already contains unrecognized files.')
        if executable_running(target / 'NaviScout.exe'):
            raise ValueError('Close the installed Navi Scout application before updating it.')
    with tempfile.TemporaryDirectory(prefix='NaviScout-install-') as stage:
        manifest = extract_payload(payload, stage)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(stage, target, dirs_exist_ok=True)
    shutil.copy2(setup_executable, target / 'Uninstall Navi Scout.exe')
    atomic_json(marker, dict(app_id=APP_ID, version=VERSION, files=len(manifest['files'])))
    desktop_link, menu = shortcut_paths()
    shell_shortcut(menu / 'Navi Scout.lnk', target / 'NaviScout.exe')
    shell_shortcut(menu / 'Connect a different game.lnk', target / 'NaviScout.exe', '--setup')
    shell_shortcut(menu / 'Preview and instructions.lnk', target / 'docs/START-HERE.html')
    shell_shortcut(menu / 'Uninstall Navi Scout.lnk', target / 'Uninstall Navi Scout.exe', '--uninstall')
    if desktop:
        shell_shortcut(desktop_link, target / 'NaviScout.exe')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in {
            'DisplayName': 'Navi Scout', 'DisplayVersion': VERSION, 'Publisher': 'Navi Scout contributors',
            'InstallLocation': str(target), 'DisplayIcon': str(target / 'NaviScout.exe'),
            'UninstallString': f'"{target / "Uninstall Navi Scout.exe"}" --uninstall',
            'URLInfoAbout': 'https://github.com/jfhutchi/NaviScout',
        }.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)
    return target


def remove_installed():
    if install_dir().is_symlink() or install_dir().is_junction():
        raise ValueError('The installation directory is a filesystem link; no files were removed.')
    target = install_dir().resolve()
    marker = target / 'install-manifest.json'
    if not marker.is_file() or json.loads(marker.read_text())['app_id'] != APP_ID:
        raise ValueError('Navi Scout installation marker is missing; no files were removed.')
    if executable_running(target / 'NaviScout.exe'):
        raise ValueError('Close Navi Scout before uninstalling it.')
    desktop, menu = shortcut_paths()
    # Only this app's validated installation and named shortcuts are removed. User data/backups remain.
    deadline = time.monotonic() + 6
    while True:
        try:
            shutil.rmtree(target)
            break
        except PermissionError:
            # A one-file uninstaller's bootloader can release its executable after its child exits.
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    desktop.unlink(missing_ok=True)
    if menu.exists():
        for name in ('Navi Scout.lnk', 'Connect a different game.lnk', 'Preview and instructions.lnk', 'Uninstall Navi Scout.lnk'):
            (menu / name).unlink(missing_ok=True)
        if not any(menu.iterdir()):
            menu.rmdir()
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
