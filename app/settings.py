"""Per-user locations and installation validation for the standalone companion."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from datetime import datetime

VERSION = '1.0.1'
BUILD_ID = 'E0F3CCFAF50065AE'
APP_ID = 'NaviScout.Standalone'


def user_data():
    return Path(os.environ['LOCALAPPDATA']) / 'NaviScout'


def validate_game(selected):
    path = Path(selected).expanduser().resolve()
    if path.is_file():
        path = path.parent
    candidates = (path, path / 'game', path / 'updates/nx2navi-original/game')
    for candidate in candidates:
        if not (candidate / 'ocarina.exe').is_file():
            continue
        header_path = candidate / 'exefs/main'
        if not header_path.is_file():
            raise ValueError('This game folder is missing exefs/main. Complete NX2navi setup first.')
        with header_path.open('rb') as stream:
            header = stream.read(0x48)
        if header[:4] != b'NSO0' or header[0x40:0x48].hex().upper() != BUILD_ID:
            raise ValueError(f'Unsupported game build. Navi Scout 1.0 supports {BUILD_ID} only.')
        if not (candidate / 'romfs').is_dir():
            raise ValueError('This game folder is missing its extracted romfs directory.')
        return candidate.resolve()
    raise ValueError('Choose ocarina.exe or the NX2navi folder containing it.')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)


def backup_profile(game, destination):
    profile = Path(game) / 'profile'
    if not profile.is_dir():
        return None
    target = Path(destination) / ('before-navi-scout-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    target.mkdir(parents=True)
    manifest = []
    for source in sorted(profile.rglob('*')):
        if source.is_symlink() or not source.resolve().is_relative_to(profile.resolve()):
            raise ValueError('The game profile contains a link outside its folder; backup stopped.')
        if source.is_file():
            relative = source.relative_to(profile)
            output = target / 'profile' / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                raise OSError(f'Backup verification failed: {relative}')
            manifest.append(dict(path=relative.as_posix(), sha256=digest))
    atomic_json(target / 'verification.json', dict(version=VERSION, files=manifest))
    return target
