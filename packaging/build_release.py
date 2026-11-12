"""Build a clean binary/source release from an explicit source whitelist."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from settings import APP_ID, VERSION

BUILD = ROOT / 'build'
RELEASE = ROOT / 'release' / f'NaviScout-{VERSION}-Windows-x64'


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def zip_tree(folder, output, prefix=''):
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, prefix + path.relative_to(folder).as_posix())


def source_files():
    files = [ROOT / name for name in ('README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.txt', 'requirements-build.txt', '.gitignore')]
    for folder in ('app', 'tests', 'packaging'):
        files.extend(sorted((ROOT / folder).glob('*.py')))
    files.extend(sorted((ROOT / 'docs').rglob('*.html')))
    files.extend(sorted((ROOT / 'docs/screenshots').glob('*.png')))
    files.extend(sorted((ROOT / 'third_party').glob('*.txt')))
    return files


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'third_party').glob('*.txt'):
        shutil.copy2(source, destination / source.name)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    shutil.copy2(python_license, destination / 'Python-LICENSE.txt')
    for name in ('pyinstaller', 'zstandard'):
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            if any(word in str(entry).lower() for word in ('license', 'copying', 'notice')) and str(entry).lower().endswith(('.txt', '.md', 'license', 'copying')):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    output = destination / name / str(entry).replace('..', '_').replace('/', '_')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, output)
    for toolkit in ('tcl8.6', 'tk8.6'):
        source = Path(sys.base_prefix) / 'tcl' / toolkit / 'license.terms'
        if source.is_file():
            shutil.copy2(source, destination / f'{toolkit}-license.terms.txt')


def main():
    RELEASE.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    for name in ('radar-preview.png', 'edge-arrow-demo.png', 'connect-your-game.png'):
        if not (ROOT / 'docs/screenshots' / name).is_file():
            raise ValueError(f'Missing required release screenshot: {name}')
    run('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir', '--name', 'NaviScout',
        '--paths', ROOT / 'app', '--distpath', BUILD / 'app-dist', '--workpath', BUILD / 'pyi-app',
        '--specpath', BUILD, ROOT / 'app/companion.py')
    application = BUILD / 'app-dist/NaviScout'
    shutil.copytree(ROOT / 'docs', application / 'docs', dirs_exist_ok=True)
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.txt'):
        shutil.copy2(ROOT / name, application / name)
    collect_licenses(application / 'licenses')
    manifest = dict(app_id=APP_ID, version=VERSION, files=[])
    for path in sorted(application.rglob('*')):
        if path.is_file() and path.name != 'payload-manifest.json':
            manifest['files'].append(dict(path=path.relative_to(application).as_posix(),
                                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (application / 'payload-manifest.json').write_text(json.dumps(manifest, indent=2))
    payload = BUILD / 'payload.zip'
    zip_tree(application, payload)
    zip_tree(application, RELEASE / f'NaviScout-Portable-{VERSION}.zip', 'NaviScout/')
    run('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onefile', '--name', f'NaviScout-Setup-{VERSION}',
        '--paths', ROOT / 'app', '--paths', ROOT / 'packaging', '--add-data', f'{payload};.',
        '--add-data', f'{ROOT / "docs"};docs', '--distpath', RELEASE, '--workpath', BUILD / 'pyi-setup',
        '--specpath', BUILD, ROOT / 'packaging/setup.py')
    shutil.copy2(ROOT / 'docs/START-HERE.html', RELEASE / 'START-HERE.html')
    shutil.copytree(ROOT / 'docs/screenshots', RELEASE / 'screenshots', dirs_exist_ok=True)
    shutil.copytree(application / 'licenses', RELEASE / 'licenses', dirs_exist_ok=True)
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.txt'):
        shutil.copy2(ROOT / name, RELEASE / name)
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    readme = readme.replace('(docs/START-HERE.html)', '(START-HERE.html)').replace('(docs/screenshots/', '(screenshots/')
    (RELEASE / 'README.md').write_text(readme, encoding='utf-8')
    with zipfile.ZipFile(RELEASE / f'NaviScout-Source-{VERSION}.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, 'NaviScout-source/' + path.relative_to(ROOT).as_posix())
    report = dict(version=VERSION, built_utc=datetime.now(timezone.utc).isoformat(), platform='Windows x64',
                  python=sys.version.split()[0], pyinstaller=importlib.metadata.version('pyinstaller'),
                  zstandard=importlib.metadata.version('zstandard'), payload_files=len(manifest['files']),
                  source_files=len(source_files()), personal_game_data_included=False,
                  game_derived_catalog_included=False, signed=False)
    (RELEASE / 'BUILD-INFO.json').write_text(json.dumps(report, indent=2))
    refresh_release()
    print(RELEASE)


def refresh_release():
    checksums = []
    for path in sorted(RELEASE.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS.txt':
            checksums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(RELEASE).as_posix())
    (RELEASE / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n')
    zip_tree(RELEASE, ROOT / 'release' / f'NaviScout-{VERSION}-Windows-x64.zip', RELEASE.name + '/')


if __name__ == '__main__':
    main()
