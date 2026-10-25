"""Install the supported MapFan II edition from the user's physical CD or ISO."""
from pathlib import Path
import argparse
import configparser
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import setup30
from patch_mapfan import apply, DEFAULT_TARGET, ORIGINAL, sha
import uninstall

ASSETS = Path(__file__).resolve().parent
MANIFEST = json.loads((ASSETS / 'media_manifest.json').read_text(encoding='utf-8'))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_media(media):
    for name, expected in MANIFEST['files'].items():
        path = media / name
        if not path.is_file():
            raise ValueError(f'CDのルートを指定してください。必要なファイルがありません: {name}')
        if digest(path) != expected:
            raise ValueError(f'未対応の版、または読み取り不良です: {name}（インストール中止）')


def decode_payload(media):
    archive = media / 'DATA.Z'
    entries = setup30.parse_entries(archive, scan_tail_bytes=65536)
    if len(entries) != 44:
        raise ValueError('インストール書庫のファイル数が一致しません')
    data = archive.read_bytes()
    decoded = {}
    for item in entries:
        name = item['name']
        if Path(name).name != name or any(c in name for c in ('/', '\\', ':')):
            raise ValueError('書庫に不正なファイル名があります')
        if name.casefold() in {n.casefold() for n in decoded}:
            raise ValueError('書庫に重複するファイル名があります')
        start, size = item['data_offset'], item['compressed_size']
        if start < 0 or size < 0 or start + size > len(data):
            raise ValueError('書庫の範囲が不正です')
        decoded[name] = setup30.explode_ttcomp(
            data[start:start + size], expected_size=item['uncompressed_size'])
    dll = next(value for name, value in decoded.items() if name.lower() == 'mfco30.dll')
    if sha(dll) != ORIGINAL:
        raise ValueError('DLLが対応版ではありません')
    return decoded


def make_ini(media, dest):
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str
    cfg.read(media / 'MAPFAN2.INI', encoding='cp932')
    pref = cfg['MapFan2 Preferences']
    pref.update({'MapDisc': str(dest / 'CD-ROM'), 'ExeFilePath': str(dest),
                 'SystemSpotfile': str(dest / 'SPFILE/SYSTEM.SPF'),
                 'TrashSpotfile': str(dest / 'SPFILE/TRASH.SPG')})
    for n, name in enumerate(['SYSTEM.SPF', 'PLAYSPOT.SPF', 'URLSAMPL.SPF'], 1):
        pref[f'Spotfile{n}'] = str(dest / 'SPFILE' / name)
    address = cfg['Address Search']
    address['$ADRSYS'] = str(dest / 'CD-ROM/ADDRESS/ADDR00.SPF')
    for n in range(1, 12):
        address[f'$ADRSP{n:02}'] = str(dest / f'CD-ROM/ADDRESS/ADDR{n:02}.SPF')
    for n, name in enumerate(['AIRPORT', 'FERRY', 'ROAD_IC', 'ROAD_SA', 'TRAIN', 'TRAIN_JR', 'YAKUBA', 'YUUGIZYO'], 1):
        cfg['Guide Search'][f'$GUIDESPNAME{n}'] = str(dest / f'CD-ROM/GUIDE/{name}.SPF')
    return cfg


def activate_settings(dest):
    """Run only after all payload files have been validated and installed."""
    inventory = json.loads((dest / 'installation-manifest.json').read_text(encoding='utf-8'))
    uninstall.activate_install(dest, inventory)


def validate_install_target(target, registered=None):
    """Validate a chosen location without creating it or changing settings."""
    target = Path(os.path.expandvars(str(target))).expanduser()
    if not target.is_absolute():
        raise ValueError('ドライブから始まるフルパスを指定してください。例: E:\\MapFanII')
    target = target.resolve()
    if target == Path(target.anchor):
        raise ValueError('ドライブ直下ではなく、MapFan用のフォルダーを指定してください。')
    if target.exists() and not target.is_dir():
        raise ValueError('同名のファイルがあります。別のフォルダーを指定してください。')
    if target.exists() and any(target.iterdir()) and existing_installation(target) is None:
        raise ValueError(f'このフォルダーには既存ファイルがあります。空のフォルダーを選んでください。\n\n{target}')
    if registered and Path(registered).resolve() != target:
        raise ValueError(f'現在の導入先は次の場所です:\n{registered}\n\n別の場所へ新規導入する場合は、先に現在のMapFanをアンインストールしてください。')
    str(target).encode('cp932')
    return target


def registered_destination(registry=None):
    registry = registry or uninstall.Registry()
    record = registry.read(uninstall.ARP, 'InstallLocation', 64)
    return record.get('value') if record.get('exists') else None


def choose_install_target(initial):
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk()
    window.title('MapFan II インストール先の選択')
    window.geometry('700x230')
    window.resizable(False, False)
    selected = {'path': None}
    registered = registered_destination()
    value = tk.StringVar(value=str(registered or initial))
    tk.Label(window, text='MapFan IIをインストールするフォルダーを選んでください。', anchor='w').pack(fill='x', padx=18, pady=(18, 10))
    row = tk.Frame(window)
    row.pack(fill='x', padx=18)
    entry = tk.Entry(row, textvariable=value, width=68)
    entry.pack(side='left', fill='x', expand=True)

    def browse():
        start = Path(os.path.expandvars(value.get())).expanduser()
        while not start.is_dir() and start != start.parent:
            start = start.parent
        folder = filedialog.askdirectory(parent=window, title='インストール先フォルダーを選択',
                                         initialdir=str(start) if start.is_dir() else None, mustexist=False)
        if folder:
            value.set(folder)

    tk.Button(row, text='参照…', command=browse, width=9).pack(side='right', padx=(10, 0))
    tk.Label(window, text='別のドライブも指定できます。新しいフォルダー名を直接入力することもできます。\n'
                         '既存ファイルは上書きしません。導入済みの場所を選ぶと修復の確認に進みます。',
             anchor='w', justify='left').pack(fill='x', padx=18, pady=15)
    buttons = tk.Frame(window)
    buttons.pack(side='bottom', fill='x', padx=18, pady=16)

    def accept():
        try:
            if not value.get().strip():
                raise ValueError('インストール先を入力してください')
            selected['path'] = validate_install_target(value.get().strip(), registered)
        except (ValueError, OSError) as error:
            uninstall.gui_message('インストール先を確認してください', str(error), error=True)
            return
        window.destroy()

    tk.Button(buttons, text='この場所にインストール', command=accept, width=24).pack(side='right')
    tk.Button(buttons, text='キャンセル', command=window.destroy, width=12).pack(side='right', padx=10)
    window.protocol('WM_DELETE_WINDOW', window.destroy)
    entry.focus_set()
    window.mainloop()
    return selected['path']


def existing_installation(dest):
    """Recognize an owned installation without altering files or settings."""
    try:
        root = uninstall.validate_root(dest)
        state = uninstall.load_state(root)
        if state.get('legacy'):
            return None
        for name in ('MapFan2.exe', 'MFCO30.DLL', 'SDBOLE32.exe', 'MapFanII-Win11.exe'):
            if name not in state['files'] or digest(root / name) != state['files'][name]:
                return None
        return state
    except (OSError, ValueError, KeyError):
        return None


def repair_installation(dest, registry=None):
    """Restore activation using existing snapshots; never recapture old state."""
    dest = dest.resolve()
    state = existing_installation(dest)
    if state is None:
        raise ValueError('修復できる導入済みMapFanを確認できません。ファイルは変更していません。')
    uninstall.tree_files(dest)
    if uninstall.running_apps():
        raise ValueError('MapFan関連アプリを終了してから修復してください')
    registry = registry or uninstall.Registry()
    # Refuse to take over a different active installation.
    location = registry.read(uninstall.ARP, 'InstallLocation', 64)
    owner = registry.read(uninstall.CLSID + '\\LocalServer32', '', 32)
    expected_owner = next(r['new'] for r in state['registry'] if r['path'] == uninstall.CLSID + '\\LocalServer32')
    if location.get('exists') and os.path.normcase(location['value']) != os.path.normcase(str(dest)):
        raise ValueError('別の導入先がアプリ一覧に登録されています。変更しません。')
    if owner.get('exists') and not uninstall.same_value(owner, expected_owner):
        raise ValueError('別の導入先がOLE登録を使用しています。変更しません。')
    profile_dir = Path(state['profile_dir'])
    main = uninstall.profile_path(profile_dir, 'MAPFAN2.INI')
    own_profile = uninstall.profile_owner(state)
    main_record = next(r for r in state['profiles'] if r['name'] == 'MAPFAN2.INI')
    import base64
    if main.exists() and not own_profile:
        old = base64.b64decode(main_record['old_b64']) if main_record['old_exists'] else None
        if main.read_bytes() != old:
            raise ValueError('別の導入先または変更済みのINIを確認しました。上書きせず停止します。')
    for name in uninstall.TOOLS:
        current = dest / name
        if current.exists() and name in state['files'] and digest(current) != state['files'][name]:
            raise ValueError('アンインストール用ファイルが変更されています: ' + name)
        if not (ASSETS / name).is_file():
            raise FileNotFoundError('修復用ファイルがありません: ' + name)
    # Keep the original before-install snapshots, even after any repair.
    backup = dest / 'uninstall-state.before-repair.json'
    if not backup.exists():
        shutil.copy2(dest / uninstall.STATE, backup)
    for name in uninstall.TOOLS:
        current = dest / name
        uninstall.make_writable(current)
        if (ASSETS / name).resolve() != current.resolve():
            shutil.copy2(ASSETS / name, current)
        state['files'][name] = digest(current)
    # User preferences in an already-owned INI are retained; create only
    # missing files, or finish an interrupted initial main-profile activation.
    profile_dir.mkdir(parents=True, exist_ok=True)
    for record in state['profiles']:
        current = uninstall.profile_path(profile_dir, record['name'])
        uninstall.make_writable(dest / record['name'])
        if not current.exists() or (record['name'] == 'MAPFAN2.INI' and not own_profile):
            uninstall.make_writable(current)
            shutil.copy2(dest / record['name'], current)
        uninstall.make_writable(current)
    new_arp = uninstall.arp_records(dest, registry)
    replacements = {r['name']: r['new'] for r in new_arp}
    for record in state['arp']:
        record['new'] = replacements[record['name']]
    state['phase'] = 'prepared'
    uninstall.save_state(dest, state)
    for record in state['registry'] + state['arp']:
        registry.write(record['path'], record['name'], record['new']['value'], record['new']['type'], record['view'])
    inventory = dict(state['files'])
    (dest / 'installation-manifest.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    state['phase'] = 'installed'
    uninstall.save_state(dest, state)
    print('既存の本体とユーザーデータを残して、登録と起動設定を修復しました。')
    return dest / 'MapFanII-Win11.exe'


def install_from_media(media, dest, *, check_only=False):
    media, dest = media.resolve(), dest.resolve()
    if not check_only and dest.exists() and any(dest.iterdir()):
        if existing_installation(dest) is not None:
            raise ValueError(f'既にインストール済みです: {dest}\n起動: {dest / "MapFanII-Win11.exe"}\n登録を修復する場合は --repair --target "{dest}" を指定してください。')
        raise ValueError(f'インストール先にファイルがあります: {dest}\n--targetで空のフォルダーを指定してください。既存ファイルは上書きしません。')
    if not check_only:
        validate_install_target(dest, registered_destination())
    print('CDのファイルを確認しています…', flush=True)
    validate_media(media)
    print('旧インストーラの書庫を展開しています…', flush=True)
    decoded = decode_payload(media)
    if check_only:
        print('対応するCDです。44ファイルの展開とDLLの版確認に成功しました。')
        return
    if not (ASSETS / 'MapFanII-Win11.exe').is_file():
        raise ValueError('ランチャーがありません。ReleasesのZIPを使うか、build_release.pyでビルドしてください。')
    # The application uses legacy Japanese ANSI APIs. Fail before writing if the
    # path cannot be represented rather than installing a broken configuration.
    str(dest).encode('cp932')
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'SPFILE').mkdir()
    for name, value in decoded.items():
        output = dest / 'SPFILE' / name if Path(name).suffix.lower() in ('.spf', '.spg') else dest / name
        output.write_bytes(value)
    print('地図データをコピーしています…', flush=True)
    for name in ['MAPFAN.DAT', 'TABLES.DAT', 'ADDRESS', 'GUIDE']:
        source, target = media / name, dest / 'CD-ROM' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            target.mkdir()
            for rel in MANIFEST['files']:
                if rel.startswith(name + '/'):
                    shutil.copy2(media / rel, dest / 'CD-ROM' / rel)
        else:
            shutil.copy2(source, target)
    for name in ['EXTRAFAN.INI', 'SPOTFAN.INI', 'README.DOC']:
        shutil.copy2(media / name, dest / name)
    # A physical CD marks its files read-only. Do not carry that attribute into
    # installed preferences or into files the uninstaller must later remove.
    for path in dest.rglob('*'):
        if path.is_file():
            uninstall.make_writable(path)
    with (dest / 'MAPFAN2.INI').open('w', encoding='cp932', newline='\r\n') as stream:
        make_ini(media, dest).write(stream, space_around_delimiters=False)
    apply(dest, ASSETS)
    for name in uninstall.TOOLS:
        shutil.copy2(ASSETS / name, dest / name)
    inventory = {str(p.relative_to(dest)): digest(p) for p in dest.rglob('*') if p.is_file()}
    (dest / 'installation-manifest.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    # Profile and COM changes are last. Incomplete file copies do not change the
    # user's active installation. Preserve files for diagnosis if a copy fails.
    activate_settings(dest)
    print(f'完了: {dest / "MapFanII-Win11.exe"}\nこのランチャーを通常権限で起動してください。')


def find_sevenzip(explicit):
    candidates = [explicit, shutil.which('7z'),
                  str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / '7-Zip/7z.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise ValueError('ISOを使う場合は7-Zipが必要です。CDドライブを直接指定する場合は不要です。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--media', type=Path, help='CDのルート（例: D:\\）')
    source.add_argument('--iso', type=Path, help='所有するCDから作成したISO')
    parser.add_argument('--target', type=Path, help='インストール先。Install.cmdでは画面から選択可能')
    parser.add_argument('--sevenzip', help='ISO用の7z.exeの場所')
    parser.add_argument('--check', action='store_true', help='CDを検証するだけ。ファイル・INI・レジストリを変更しない')
    parser.add_argument('--repair', action='store_true', help='導入済み本体を再コピーせず、登録と起動設定を修復')
    args = parser.parse_args()
    target_explicit = args.target is not None
    args.target = args.target or DEFAULT_TARGET
    if os.name != 'nt':
        raise ValueError('Windowsで実行してください')
    if not args.check and ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError('管理者として実行せず、通常のユーザー権限で実行してください')
    if args.repair:
        if args.check:
            raise ValueError('--repairと--checkは同時に指定できません')
        repair_installation(args.target)
        return
    interactive = args.media is None and args.iso is None
    if args.media is None and args.iso is None:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk()
        window.title('MapFan II インストーラー')
        window.geometry('420x80')
        tk.Label(window, text='MapFan IIのCDドライブを選択してください。').pack(padx=15, pady=25)
        window.update()
        selected = filedialog.askdirectory(parent=window, title='MAPFAN IIのCDドライブ（DATA.Zがある場所）を選択')
        window.destroy()
        if not selected:
            print('キャンセルしました。変更はありません。')
            return
        args.media = Path(selected)
    if interactive and not target_explicit and not args.check:
        selected_target = choose_install_target(args.target)
        if selected_target is None:
            print('キャンセルしました。変更はありません。')
            return
        args.target = selected_target
    if not args.check and args.target.exists() and any(args.target.iterdir()) and existing_installation(args.target) is not None:
        launcher = args.target.resolve() / 'MapFanII-Win11.exe'
        if interactive:
            text = (f'この場所には既にMapFan IIがインストールされています。\n\n{args.target.resolve()}\n\n'
                    '本体や保存データは上書きせず、登録を修復して起動しますか？')
            if uninstall.gui_message('MapFan II インストール済み', text, confirm=True):
                repair_installation(args.target)
                subprocess.Popen([str(launcher)], cwd=str(args.target.resolve()))
            return
        raise ValueError(f'既にインストール済みです: {args.target.resolve()}\n起動用: {launcher}\n修復する場合は --repair を指定してください。')
    if args.iso:
        # Windows' temp directory is outside the public repository. Never put
        # proprietary extracted media under the repository or release tree.
        work = Path(tempfile.mkdtemp(prefix='mapfan2-media-')).resolve()
        try:
            subprocess.run([find_sevenzip(args.sevenzip), 'x', str(args.iso.resolve()), '-o' + str(work), '-y'], check=True)
            install_from_media(work, args.target, check_only=args.check)
        finally:
            expected_parent = Path(tempfile.gettempdir()).resolve()
            if work.parent != expected_parent or not work.name.startswith('mapfan2-media-'):
                raise RuntimeError('一時フォルダーの範囲を確認できません')
            shutil.rmtree(work)
    else:
        install_from_media(args.media, args.target, check_only=args.check)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('エラー:', error, file=sys.stderr)
        sys.exit(1)
