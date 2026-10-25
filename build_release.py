"""Build an allowlisted patch-only GitHub Release asset on Windows."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = '1.1.0-beta.5'
PUBLIC_FILES = (
    '.gitignore', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'LICENSE-setup30.txt', 'CHANGELOG.md', 'RELEASING.md',
    'Install.cmd', 'Apply-Patch.cmd', 'install.py', 'patch_mapfan.py',
    'register_mapfan.py', 'setup30.py', 'MapFanII-Win11.cs',
    'media_manifest.json', 'build_release.py', 'test_public.py',
    'uninstall.py', 'Uninstall.cmd', 'Register-Uninstaller.cmd', 'UNINSTALL.md',
    'test_uninstall.py',
)


def audit():
    unexpected = []
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in ('.git', '__pycache__', 'build', 'dist'):
            continue
        if path.is_file() and relative.as_posix() not in PUBLIC_FILES:
            unexpected.append(relative.as_posix())
    if unexpected:
        raise ValueError('公開対象外のファイルがあります: ' + ', '.join(unexpected))
    if (ROOT / '.git').exists():
        result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], check=True, capture_output=True)
        tracked = result.stdout.decode('utf-8').split('\0')
        invalid = [p for p in tracked if p and p not in PUBLIC_FILES]
        if invalid:
            raise ValueError('Gitに公開対象外ファイルがあります: ' + ', '.join(invalid))
    for name in PUBLIC_FILES:
        path = ROOT / name
        if not path.is_file():
            raise ValueError('公開に必要なファイルがありません: ' + name)
        if path.stat().st_size > 100_000:
            raise ValueError('想定外のサイズです: ' + name)
    print('PASS: repository contains allowlisted source/docs only')


def build():
    audit()
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise FileNotFoundError('Windows付属の.NET Framework C#コンパイラが見つかりません')
    build_dir = ROOT / 'build'
    release_dir = ROOT / 'dist'
    build_dir.mkdir(exist_ok=True)
    release_dir.mkdir(exist_ok=True)
    launcher = build_dir / 'MapFanII-Win11.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x86',
                    '/optimize+', '/r:System.Windows.Forms.dll', '/out:' + str(launcher),
                    str(ROOT / 'MapFanII-Win11.cs')], check=True)
    output = release_dir / f'mapfan2-win11-patch-{VERSION}.zip'
    release_files = [n for n in PUBLIC_FILES if n != '.gitignore']
    prefix = f'mapfan2-win11-patch-{VERSION}/'
    checksums = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in release_files}
    checksums[launcher.name] = hashlib.sha256(launcher.read_bytes()).hexdigest()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in release_files:
            archive.write(ROOT / name, prefix + name)
        archive.write(launcher, prefix + launcher.name)
        archive.writestr(prefix + 'SHA256SUMS.json', json.dumps(checksums, indent=2) + '\n')
    with zipfile.ZipFile(output) as archive:
        expected = {prefix + n for n in release_files + [launcher.name, 'SHA256SUMS.json']}
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise RuntimeError('頒布ZIPの検証に失敗しました')
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(checksum + '  ' + output.name + '\n', encoding='ascii')
    print('Built:', output)
    print('SHA256:', checksum)
    standalone = release_dir / f'mapfan2-win11-uninstaller-{VERSION}.zip'
    names = ('uninstall.py', 'register_mapfan.py', 'Uninstall.cmd', 'Register-Uninstaller.cmd',
             'UNINSTALL.md', 'LICENSE')
    with zipfile.ZipFile(standalone, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, f'mapfan2-win11-uninstaller-{VERSION}/' + name)
    standalone.with_suffix('.zip.sha256').write_text(
        hashlib.sha256(standalone.read_bytes()).hexdigest() + '  ' + standalone.name + '\n', encoding='ascii')
    with zipfile.ZipFile(standalone) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('単独アンインストーラーZIPの検証に失敗しました')
    print('Built standalone uninstaller:', standalone)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    audit() if args.audit else build()
