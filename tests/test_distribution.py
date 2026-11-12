import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import zstandard

from catalog import GameFiles
from install_support import extract_payload, remove_installed
from settings import APP_ID, BUILD_ID, backup_profile, validate_game
from windows_support import shell_shortcut


class DistributionTests(unittest.TestCase):
    def fake_game(self, root):
        game = root / 'game'
        (game / 'exefs').mkdir(parents=True)
        (game / 'romfs').mkdir()
        (game / 'ocarina.exe').write_bytes(b'fixture')
        header = bytearray(0x48)
        header[:4] = b'NSO0'
        header[0x40:0x48] = bytes.fromhex(BUILD_ID)
        (game / 'exefs/main').write_bytes(header)
        return game

    def test_setup_accepts_game_folder_or_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            game = self.fake_game(Path(temp))
            self.assertEqual(validate_game(game), game.resolve())
            self.assertEqual(validate_game(game / 'ocarina.exe'), game.resolve())

    def test_setup_rejects_other_build_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            game = self.fake_game(Path(temp))
            original = bytearray((game / 'exefs/main').read_bytes())
            original[0x40] ^= 1
            (game / 'exefs/main').write_bytes(original)
            with self.assertRaises(ValueError):
                validate_game(game)
            self.assertEqual((game / 'exefs/main').read_bytes(), original)

    def test_profile_backup_includes_journal_and_verifies_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = self.fake_game(root)
            profile = game / 'profile/save/slot_0'
            profile.mkdir(parents=True)
            (profile / 'progress.sav').write_bytes(b'sample-save')
            (profile / 'journal').write_bytes(b'sample-journal')
            target = backup_profile(game, root / 'backups')
            rows = json.loads((target / 'verification.json').read_text())['files']
            self.assertEqual(len(rows), 2)
            for row in rows:
                data = (target / 'profile' / row['path']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])

    def test_romfs_reader_supports_indexed_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = zstandard.ZstdCompressor().compress(b'recipient-owned-test-data')
            (root / 'romfs.bin').write_bytes(b'prefix' + data)
            (root / 'index.json').write_text(json.dumps(dict(status='pass', files=[dict(path='test.zs', offset=6, size=len(data))])))
            self.assertEqual(GameFiles(root).load('test.zs'), b'recipient-owned-test-data')

    def test_unverified_romfs_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.json').write_text('{"status":"fail","files":[]}')
            with self.assertRaises(ValueError):
                GameFiles(root)

    def test_corrupt_compressed_resource_reports_setup_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'bad.zs').write_bytes(b'broken-compressed-data')
            with self.assertRaisesRegex(ValueError, 'compressed game resource'):
                GameFiles(root).load('bad.zs')

    def payload(self, root, content=b'owned-code', digest=None, name='NaviScout.exe'):
        payload = root / 'payload.zip'
        manifest = dict(app_id=APP_ID, files=[dict(path=name, sha256=digest or hashlib.sha256(content).hexdigest())])
        with zipfile.ZipFile(payload, 'w') as archive:
            entry = zipfile.ZipInfo(name)
            entry.filename = name
            archive.writestr(entry, content)
            archive.writestr('payload-manifest.json', json.dumps(manifest))
        return payload

    def test_installer_payload_checksums_all_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = extract_payload(self.payload(root), root / 'out')
            self.assertEqual(manifest['app_id'], APP_ID)
            self.assertEqual((root / 'out/NaviScout.exe').read_bytes(), b'owned-code')

    def test_installer_rejects_corrupted_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                extract_payload(self.payload(root, digest='0' * 64), root / 'out')

    def test_installer_rejects_archive_path_traversal(self):
        for name in ('../escape.exe', '/escape.exe', 'C:/escape.exe', 'folder\\escape.exe'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaises(ValueError):
                    extract_payload(self.payload(root, name=name), root / 'out')

    def test_windows_shortcut_is_created_without_launching_target(self):
        with tempfile.TemporaryDirectory() as temp:
            link = Path(temp) / 'Navi Scout test.lnk'
            shell_shortcut(link, sys.executable, '--version')
            self.assertEqual(link.read_bytes()[:4], struct.pack('<I', 76))

    def test_uninstall_removes_only_app_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / 'Programs/NaviScout'
            target.mkdir(parents=True)
            (target / 'install-manifest.json').write_text(json.dumps(dict(app_id=APP_ID)))
            private = base / 'NaviScout/backups'
            private.mkdir(parents=True)
            (private / 'keep.sav').write_bytes(b'recipient-save')
            with patch.dict(os.environ, LOCALAPPDATA=str(base)), \
                    patch('install_support.executable_running', return_value=False), \
                    patch('install_support.shortcut_paths', return_value=(base / 'scout.lnk', base / 'menu')), \
                    patch('install_support.winreg.DeleteKey'):
                remove_installed()
            self.assertFalse(target.exists())
            self.assertEqual((private / 'keep.sav').read_bytes(), b'recipient-save')

    def test_uninstall_refuses_unrecognized_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / 'Programs/NaviScout'
            target.mkdir(parents=True)
            (target / 'unrelated.txt').write_text('keep')
            with patch.dict(os.environ, LOCALAPPDATA=str(base)), self.assertRaises(ValueError):
                remove_installed()
            self.assertEqual((target / 'unrelated.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
