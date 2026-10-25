"""Per-user uninstaller with a preview, data preservation and ownership checks."""
from pathlib import Path, PureWindowsPath
import argparse
import base64
import configparser
import csv
import ctypes
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
import winreg
from register_mapfan import registry_entries

VERSION = '1.1.0-beta.5'
PRODUCT = 'MapFanII-Win11-Compat'
ARP = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\MapFanII-Win11-Compat'
STATE = 'uninstall-state.json'
PROFILES = ('MAPFAN2.INI', 'EXTRAFAN.INI', 'SPOTFAN.INI')
TOOLS = ('uninstall.py', 'register_mapfan.py', 'Uninstall.cmd')
CLSID = r'Software\Classes\CLSID\{95BEBF80-3B8C-11CF-B858-444553540000}'
PROGID = r'Software\Classes\MapFan.Document.1'


def gui_message(title, text, *, confirm=False, error=False):
    """Native top-level dialog; no hidden Tk owner when started by Settings."""
    box = ctypes.windll.user32.MessageBoxW
    box.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    box.restype = ctypes.c_int
    flags = 0x10000 | (0x4 | 0x100 | 0x20 if confirm else 0x10 if error else 0x40)
    result = box(None, text, title, flags)
    return result == 6 if confirm else result


def choose_folder():
    import tkinter as tk
    from tkinter import filedialog
    owner = tk.Tk()
    owner.title('MapFan II アンインストーラー')
    owner.geometry('400x80')
    tk.Label(owner, text='MapFan IIのインストール先を選択してください。').pack(padx=15, pady=25)
    owner.update()
    try:
        return filedialog.askdirectory(parent=owner, title='MapFan IIのインストール先を選択')
    finally:
        owner.destroy()


def choose_removal_mode(root):
    import tkinter as tk
    window = tk.Tk()
    window.title('MapFan II アンインストール方法の選択')
    window.geometry('720x290')
    window.resizable(False, False)
    mode = tk.StringVar(value='keep')
    result = {'mode': None}
    tk.Label(window, text='対象: ' + str(root), anchor='w', wraplength=680).pack(fill='x', padx=18, pady=(16, 12))
    tk.Radiobutton(window, text='データを退避して残す', variable=mode, value='keep', anchor='w').pack(fill='x', padx=18)
    tk.Label(window, text='保存スポット・変更済みファイル・現在の設定を退避してから解除します。', anchor='w').pack(fill='x', padx=40, pady=(0, 12))
    tk.Radiobutton(window, text='完全削除（退避を作らない）', variable=mode, value='full', anchor='w').pack(fill='x', padx=18)
    tk.Label(window, text='本体・保存データと、この導入先に対応する過去の退避データを削除します。\n'
                         '削除した保存データは元に戻せません。次の画面で対象と件数を確認します。',
             anchor='w', justify='left').pack(fill='x', padx=40)
    row = tk.Frame(window)
    row.pack(side='bottom', fill='x', padx=18, pady=18)
    def accept():
        result['mode'] = mode.get()
        window.destroy()
    tk.Button(row, text='次へ', command=accept, width=14).pack(side='right')
    tk.Button(row, text='キャンセル', command=window.destroy, width=14).pack(side='right', padx=10)
    window.mainloop()
    return result['mode']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def make_writable(path):
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IREAD | stat.S_IWRITE)


def profile_path(directory, name):
    base = Path(os.environ['LOCALAPPDATA']).resolve()
    directory = Path(directory)
    if not directory.resolve().is_relative_to(base):
        raise ValueError('ユーザー設定フォルダーの範囲を確認できません')
    for path in [directory, directory.parent, directory / name]:
        if path.exists() and path.lstat().st_file_attributes & 0x400:
            raise ValueError('ユーザー設定にリンクまたはジャンクションがあります')
    path = directory / name
    if path.exists() and not path.is_file():
        raise ValueError('INIの場所が通常のファイルではありません')
    return path


def pack(value):
    return {'binary': base64.b64encode(value).decode('ascii')} if isinstance(value, bytes) else value


def unpack(value):
    return base64.b64decode(value['binary'], validate=True) if isinstance(value, dict) else value


class Registry:
    """Only HKCU is accessible through this adapter."""
    def read(self, path, name='', view=32):
        flag = winreg.KEY_WOW64_32KEY if view == 32 else winreg.KEY_WOW64_64KEY
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | flag) as key:
                try:
                    value, kind = winreg.QueryValueEx(key, name)
                    return {'exists': True, 'value': pack(value), 'type': kind, 'key_existed': True}
                except FileNotFoundError:
                    return {'exists': False, 'key_existed': True}
        except FileNotFoundError:
            return {'exists': False, 'key_existed': False}

    def write(self, path, name, value, kind, view=32):
        flag = winreg.KEY_WOW64_32KEY if view == 32 else winreg.KEY_WOW64_64KEY
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | flag) as key:
            winreg.SetValueEx(key, name, 0, kind, unpack(value))

    def remove_value(self, path, name='', view=32):
        flag = winreg.KEY_WOW64_32KEY if view == 32 else winreg.KEY_WOW64_64KEY
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE | flag) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def remove_empty_key(self, path, view=32):
        flag = winreg.KEY_WOW64_32KEY if view == 32 else winreg.KEY_WOW64_64KEY
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | flag) as key:
                children, values, _ = winreg.QueryInfoKey(key)
                if children or values:
                    return
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, flag, 0)
        except FileNotFoundError:
            pass


def save_state(root, state):
    temporary = root / (STATE + '.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(root / STATE)


def same_value(a, b):
    return a.get('exists') == b.get('exists') and (
        not a.get('exists') or (a.get('value'), a.get('type')) == (b.get('value'), b.get('type')))


def add_record(records, registry, path, name, value, kind=winreg.REG_SZ, view=32):
    records.append({'path': path, 'name': name, 'view': view,
                    'old': registry.read(path, name, view),
                    'new': {'exists': True, 'value': pack(value), 'type': kind}})


def arp_records(root, registry):
    current = registry.read(ARP, 'InstallLocation', 64)
    if current.get('exists') and os.path.normcase(current['value']) != os.path.normcase(str(root)):
        raise ValueError('別の導入先がアプリ一覧に登録されています。先にそちらを解除してください。')
    python = Path(sys.executable)
    pythonw = python.with_name('pythonw.exe')
    python = pythonw if pythonw.is_file() else python
    command = subprocess.list2cmdline([str(python), str(root / 'uninstall.py'), '--target', str(root), '--gui'])
    records = []
    for name, value in {
        'DisplayName': 'MapFan II（Windows 11互換版）',
        'DisplayVersion': VERSION, 'Publisher': 'MapFan II Win11 patch contributors（非公式）',
        'InstallLocation': str(root), 'DisplayIcon': str(root / 'MapFan2.exe'),
        'UninstallString': command, 'InstallDate': datetime.date.today().strftime('%Y%m%d'),
    }.items():
        add_record(records, registry, ARP, name, value, view=64)
    add_record(records, registry, ARP, 'NoModify', 1, winreg.REG_DWORD, 64)
    add_record(records, registry, ARP, 'NoRepair', 1, winreg.REG_DWORD, 64)
    return records


def activate_install(root, inventory, registry=None):
    """Snapshot all old values durably BEFORE modifying profiles or registry."""
    registry = registry or Registry()
    root = root.resolve()
    profile_dir = Path(os.environ['LOCALAPPDATA']).resolve() / 'VirtualStore/Windows'
    state = {'schema': 2, 'product': PRODUCT, 'root': str(root), 'legacy': False,
             'profile_dir': str(profile_dir), 'files': inventory, 'profiles': [],
             'registry': [], 'arp': arp_records(root, registry), 'phase': 'prepared'}
    for name in PROFILES:
        path = profile_path(profile_dir, name)
        old = path.read_bytes() if path.exists() else None
        state['profiles'].append({'name': name, 'old_exists': old is not None,
                                  'old_b64': base64.b64encode(old).decode('ascii') if old is not None else None,
                                  'old_readonly': bool(path.exists() and path.stat().st_file_attributes & 1),
                                  'new_sha256': digest(root / name)})
    for path, value in registry_entries(root).items():
        add_record(state['registry'], registry, 'Software\\Classes\\' + path, '', value)
    state['created_keys'] = missing_keys(state['registry'] + state['arp'], registry)
    save_state(root, state)
    profile_dir.mkdir(parents=True, exist_ok=True)
    for record in state['profiles']:
        source = root / record['name']
        target = profile_path(profile_dir, record['name'])
        make_writable(source)
        make_writable(target)
        shutil.copy2(source, target)
        make_writable(target)
    for record in state['registry'] + state['arp']:
        registry.write(record['path'], record['name'], record['new']['value'], record['new']['type'], record['view'])
    state['phase'] = 'installed'
    save_state(root, state)


def missing_keys(records, registry):
    result = set()
    for record in records:
        path = record['path']
        base = ARP if path.startswith(ARP) else CLSID if path.startswith(CLSID) else PROGID
        while len(path) >= len(base):
            if not registry.read(path, '', record['view']).get('key_existed'):
                result.add((path, record['view']))
            if path == base:
                break
            path = path.rsplit('\\', 1)[0]
    return sorted(result, key=lambda item: len(item[0]), reverse=True)


def safe_path(root, relative):
    path = PureWindowsPath(relative)
    if path.is_absolute() or path.drive or '..' in path.parts or ':' in relative:
        raise ValueError('対象外のパスが記録されています: ' + relative)
    result = (root / Path(*path.parts)).resolve()
    if result == root or not result.is_relative_to(root):
        raise ValueError('インストール先の範囲外です')
    return result


def tree_files(root):
    """Refuse junctions/reparse points instead of following them during removal."""
    result = []
    pending = [root]
    while pending:
        folder = pending.pop()
        if folder.lstat().st_file_attributes & 0x400:
            raise ValueError('ジャンクションまたはシンボリックリンクが含まれています')
        for path in folder.iterdir():
            if path.lstat().st_file_attributes & 0x400:
                raise ValueError('ジャンクションまたはシンボリックリンクが含まれています: ' + str(path))
            if not path.resolve().is_relative_to(root):
                raise ValueError('インストール先の範囲を確認できません')
            if path.is_dir():
                pending.append(path)
            else:
                result.append(path)
    return result


def validate_root(root):
    root = root.absolute()
    if root.is_symlink() or (root.exists() and root.lstat().st_file_attributes & 0x400):
        raise ValueError('リンクをインストール先として扱うことはできません')
    root = root.resolve()
    protected = [Path(root.anchor), Path.home().resolve(), Path(os.environ['LOCALAPPDATA']).resolve(),
                 Path(os.environ.get('WINDIR', r'C:\Windows')).resolve()]
    if root in protected or not root.is_dir():
        raise ValueError('有効なMapFanのインストール先ではありません')
    return root


def validate_records(state):
    allowed = {'Software\\Classes\\' + p for p in registry_entries(Path(state['root']))}
    if state.get('legacy'):
        allowed |= {r'Software\Classes\.SPF', r'Software\Classes\.SPG'}
    for record in state['registry'] + state['arp']:
        if record['path'] not in allowed | {ARP} or record['view'] not in (32, 64):
            raise ValueError('想定外のレジストリ項目が記録されています')
        if record['path'] != ARP and record['name'] != '':
            raise ValueError('想定外のレジストリ値名です')
        if record['path'] == ARP and record['name'] not in {
            'DisplayName', 'DisplayVersion', 'Publisher', 'InstallLocation', 'DisplayIcon',
            'UninstallString', 'InstallDate', 'NoModify', 'NoRepair'}:
            raise ValueError('想定外のアプリ登録項目です')
    allowed_keys = allowed | {ARP}
    for path, view in state.get('created_keys', []):
        if view not in (32, 64) or not any(p == path or p.startswith(path + '\\') for p in allowed_keys):
            raise ValueError('想定外のキー削除が記録されています')
        if not any(path == b or path.startswith(b + '\\') for b in (ARP, CLSID, PROGID)):
            raise ValueError('対象外のレジストリキーです')


def load_state(root):
    state = json.loads((root / STATE).read_text(encoding='utf-8'))
    if state.get('schema') != 2 or state.get('product') != PRODUCT or Path(state['root']).resolve() != root:
        raise ValueError('アンインストール情報の製品・導入先が一致しません')
    expected_profile = Path(os.environ['LOCALAPPDATA']).resolve() / 'VirtualStore/Windows'
    if Path(state['profile_dir']).resolve() != expected_profile.resolve():
        raise ValueError('導入したWindowsユーザーと異なります')
    if state.get('phase') == 'uninstalled':
        raise ValueError('この導入先は既にアンインストールされています')
    for name in state['files']:
        safe_path(root, name)
    for record in state['profiles']:
        if record['name'] not in PROFILES:
            raise ValueError('想定外のINIが記録されています')
        if record['old_exists']:
            base64.b64decode(record['old_b64'], validate=True)
        profile_path(state['profile_dir'], record['name'])
    validate_records(state)
    return state


def running_apps():
    result = subprocess.run([str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/tasklist.exe'),
                             '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                            encoding='oem', errors='replace', check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    names = {row[0].casefold() for row in csv.reader(result.stdout.splitlines()) if row}
    return sorted(names & {'mapfan2.exe', 'sdbole32.exe', 'spotfan.exe', 'mapfanii-win11.exe', 'extrafan.exe', 'inetfan.exe'})


def profile_owner(state):
    path = profile_path(state['profile_dir'], 'MAPFAN2.INI')
    if not path.exists():
        return False
    cfg = configparser.RawConfigParser()
    cfg.read(path, encoding='cp932')
    value = cfg.get('MapFan2 Preferences', 'ExeFilePath', fallback='').rstrip('\\/')
    return os.path.normcase(value) == os.path.normcase(state['root'].rstrip('\\/'))


def matching_history(root):
    """Only directories proven to belong to this exact installation path."""
    parent = Path(os.environ['LOCALAPPDATA']).resolve() / 'MapFanII-UninstallBackups'
    if parent.exists() and (parent.is_symlink() or parent.lstat().st_file_attributes & 0x400
                            or parent.resolve().parent != Path(os.environ['LOCALAPPDATA']).resolve()):
        raise ValueError('退避先の親フォルダーにリンクがあるため処理できません')
    candidates = list(parent.iterdir()) if parent.is_dir() else []
    candidates += list(root.parent.glob(root.name + '.uninstalled-*'))
    matches = []
    for folder in candidates:
        if not folder.is_dir() or folder.is_symlink() or folder.lstat().st_file_attributes & 0x400:
            continue
        allowed_parent = parent if folder.parent == parent else root.parent
        if folder.resolve().parent != allowed_parent.resolve():
            continue
        marker = folder / STATE
        if not marker.is_file() or marker.lstat().st_file_attributes & 0x400:
            continue
        try:
            recorded = json.loads(marker.read_text(encoding='utf-8'))
            if recorded.get('product') != PRODUCT or Path(recorded.get('root', '')).resolve() != root:
                continue
            if recorded.get('schema') != 2:
                continue
        except (OSError, ValueError, TypeError):
            continue
        tree_files(folder.resolve())
        matches.append(folder.resolve())
    return matches


def plan(root, mode='keep'):
    if mode not in ('keep', 'full'):
        raise ValueError('アンインストール方法が不正です')
    root = validate_root(root)
    state = load_state(root)
    files = tree_files(root)
    preserve, remove = [], []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if relative == STATE and mode != 'full':
            continue
        known = state['files'].get(relative)
        if mode == 'full':
            remove.append(relative)
        elif state['legacy'] or path.suffix.lower() in ('.spf', '.spg', '.ini') or not known or digest(path) != known:
            preserve.append(relative)
        else:
            remove.append(relative)
    return {'root': root, 'state': state, 'preserve': preserve, 'remove': remove, 'mode': mode,
            'history': matching_history(root) if mode == 'full' else [],
            'running': running_apps(), 'profile_owned': profile_owner(state)}


def restore_records(records, registry, warnings):
    for record in reversed(records):
        current = registry.read(record['path'], record['name'], record['view'])
        if same_value(current, record['old']):
            continue
        if not same_value(current, record['new']):
            warnings.append('後から変更された登録を保持: ' + record['path'] + ' / ' + record['name'])
            continue
        if record['old'].get('exists'):
            registry.write(record['path'], record['name'], record['old']['value'], record['old']['type'], record['view'])
        else:
            registry.remove_value(record['path'], record['name'], record['view'])


def execute(plan_info, registry=None):
    if plan_info.get('mode') == 'full':
        return execute_full(plan_info, registry)
    registry = registry or Registry()
    root, state = plan_info['root'], plan_info['state']
    # Recheck on execution; a preview is not a permission to use stale file state.
    current_plan = plan(root)
    if current_plan['running']:
        raise ValueError('MapFan関連アプリを終了してください: ' + ', '.join(current_plan['running']))
    backup_parent = Path(os.environ['LOCALAPPDATA']).resolve() / 'MapFanII-UninstallBackups'
    backup = backup_parent / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    if backup.resolve().parent != backup_parent or backup.exists() or backup.is_relative_to(root) or root.is_relative_to(backup):
        raise ValueError('退避先の範囲を確認できません')
    backup.mkdir(parents=True)
    warnings = []
    # First copy all user/changed/unknown files and settings; no removal before
    # all backups succeed. Verify byte-for-byte hashes of retained user files.
    for relative in ([] if state['legacy'] else current_plan['preserve']):
        src, dst = safe_path(root, relative), safe_path(backup / 'files', relative)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if digest(src) != digest(dst):
            raise IOError('ユーザーデータの退避確認に失敗しました')
    shutil.copy2(root / STATE, backup / STATE)
    profile_dir = Path(state['profile_dir'])
    for record in state['profiles']:
        path = profile_path(profile_dir, record['name'])
        if path.exists():
            output = backup / 'profiles' / record['name']
            output.parent.mkdir(exist_ok=True)
            shutil.copy2(path, output)
    owner = registry.read(CLSID + '\\LocalServer32', '', 32)
    expected = next((r['new'] for r in state['registry'] if r['path'] == CLSID + '\\LocalServer32' and r['view'] == 32), None)
    if expected and (same_value(owner, expected) or not owner.get('exists')):
        restore_records(state['registry'], registry, warnings)
    elif state['registry']:
        warnings.append('別の導入先が使用するOLE登録は保持しました')
    if current_plan['profile_owned'] and profile_owner(state):
        for record in state['profiles']:
            path = profile_path(profile_dir, record['name'])
            retained = backup / 'profiles' / record['name']
            if (path.exists() != retained.exists()) or (path.exists() and digest(path) != digest(retained)):
                warnings.append('処理中に変更されたINIを保持: ' + record['name'])
                continue
            if record['old_exists']:
                make_writable(path)
                path.write_bytes(base64.b64decode(record['old_b64'], validate=True))
                if record.get('old_readonly'):
                    path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
            elif path.exists():
                make_writable(path)
                path.unlink()
    else:
        warnings.append('別の導入先または変更済みのINIは保持しました')
    if state['legacy']:
        # Legacy metadata cannot distinguish all user files. Keep the complete
        # installation as an adjacent archive, with checked absolute paths.
        archive = root.with_name(root.name + '.uninstalled-' + uuid.uuid4().hex[:8])
        if archive.parent.resolve() != root.parent.resolve() or archive.exists():
            raise ValueError('旧版の保管先を確認できません')
        os.chdir(backup)
        state['phase'] = 'uninstalled'
        save_state(root, state)
        root.rename(archive)
        warnings.append('旧版の本体と全データを保管: ' + str(archive))
    else:
        # Each pathname is resolved inside the verified installation root.
        # No recursive deletion is used: retain the root if anything unexpected
        # appears or a file is locked, so a later retry remains possible.
        removal_order = sorted(current_plan['remove'] + current_plan['preserve'], key=lambda n: (n in TOOLS, n))
        for relative in removal_order:
            path = safe_path(root, relative)
            if path.exists():
                # Files may have changed while backup was running. Refuse to
                # discard unbacked changes, even in otherwise-owned files.
                retained = safe_path(backup / 'files', relative)
                expected_hash = digest(retained) if retained.exists() else state['files'].get(relative)
                if digest(path) != expected_hash:
                    raise IOError('処理中にファイルが変更されました。削除を止めました: ' + relative)
                make_writable(path)
                path.unlink()
        state['phase'] = 'uninstalled'
        save_state(root, state)
        (root / STATE).unlink()
        tree_files(root)
        directories = sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
        for folder in directories:
            if folder.resolve().is_relative_to(root) and not any(folder.iterdir()):
                folder.rmdir()
        if not any(root.iterdir()):
            os.chdir(backup)
            try:
                root.rmdir()
            except PermissionError:
                warnings.append('空の導入先フォルダーは使用中のため残しました: ' + str(root))
    location = registry.read(ARP, 'InstallLocation', 64)
    if location.get('exists') and os.path.normcase(location.get('value', '')) == os.path.normcase(str(root)):
        restore_records(state['arp'], registry, warnings)
    for path, view in state.get('created_keys', []):
        registry.remove_empty_key(path, view)
    report = {'target': str(root), 'backup': str(backup), 'legacy': state['legacy'], 'warnings': warnings}
    (backup / 'uninstall-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def remove_scoped_tree(folder, parent):
    """Delete files individually, after checking absolute paths and reparse points."""
    folder, parent = folder.absolute(), parent.resolve()
    if folder.resolve().parent != parent or folder == parent:
        raise ValueError('削除対象の親フォルダーが一致しません')
    files = tree_files(folder.resolve())
    # Keep the local recovery information and scripts until other files succeed.
    files.sort(key=lambda p: (p.name == STATE, p.name in TOOLS, str(p)))
    os.chdir(parent)
    for path in files:
        checked = safe_path(folder.resolve(), path.relative_to(folder).as_posix())
        make_writable(checked)
        checked.unlink()
    tree_files(folder.resolve())
    directories = sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for path in directories:
        if path.resolve().is_relative_to(folder.resolve()) and not any(path.iterdir()):
            path.rmdir()
    folder.rmdir()


def execute_full(plan_info, registry=None):
    registry = registry or Registry()
    root = plan_info['root']
    current = plan(root, 'full')
    state, warnings = current['state'], []
    if current['running']:
        raise ValueError('MapFan関連アプリを終了してください: ' + ', '.join(current['running']))
    owner = registry.read(CLSID + '\\LocalServer32', '', 32)
    expected = next((r['new'] for r in state['registry'] if r['path'] == CLSID + '\\LocalServer32' and r['view'] == 32), None)
    if expected and (same_value(owner, expected) or not owner.get('exists')):
        restore_records(state['registry'], registry, warnings)
    elif state['registry']:
        warnings.append('別の導入先が使用するOLE登録は保持しました')
    if current['profile_owned'] and profile_owner(state):
        for record in state['profiles']:
            path = profile_path(state['profile_dir'], record['name'])
            if record['old_exists']:
                make_writable(path)
                path.write_bytes(base64.b64decode(record['old_b64'], validate=True))
                if record.get('old_readonly'):
                    path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
            elif path.exists():
                make_writable(path)
                path.unlink()
    else:
        warnings.append('別の導入先または変更済みのINIは保持しました')
    # Prior snapshots are removed only when their product marker and original
    # installation root match this exact target. Other users/locations remain.
    for folder in current['history']:
        remove_scoped_tree(folder, folder.parent)
    remove_scoped_tree(root, root.parent)
    location = registry.read(ARP, 'InstallLocation', 64)
    if location.get('exists') and os.path.normcase(location.get('value', '')) == os.path.normcase(str(root)):
        restore_records(state['arp'], registry, warnings)
    for path, view in state.get('created_keys', []):
        registry.remove_empty_key(path, view)
    if state['legacy']:
        warnings.append('旧版のため、元の記録がない外部設定は推測で削除していません')
    # No new backup/report directory is created in full-removal mode.
    return {'target': str(root), 'backup': None, 'legacy': state['legacy'], 'mode': 'full',
            'removed_history': [str(p) for p in current['history']], 'warnings': warnings}


def legacy_state(root, registry):
    marker = json.loads((root / 'win11-patch.json').read_text(encoding='utf-8'))
    if marker.get('dll') != 'MFCO30.DLL' or marker.get('original_sha256') != '4d0257b67901e55bb857fa19924dfb8b1d9dd59e0fed411489f1b52f86b4cfc5':
        raise ValueError('対応する旧パッチの導入先ではありません')
    if digest(root / 'MapFan2.exe') != '3f258db77f08fc7f970baf1cb67aa9e926c43d6c5fdc7a90062b0050f4e8a905':
        raise ValueError('対応するMapFan本体を確認できません')
    state = {'schema': 2, 'product': PRODUCT, 'root': str(root), 'legacy': True,
             'profile_dir': str(Path(os.environ['LOCALAPPDATA']).resolve() / 'VirtualStore/Windows'),
             'files': {}, 'profiles': [], 'registry': [], 'arp': arp_records(root, registry),
             'created_keys': [], 'phase': 'installed'}
    # Only recorded old values may be restored. Never guess the original state
    # of EXTRAFAN/SPOTFAN or historical, unrecorded file associations.
    path = profile_path(state['profile_dir'], 'MAPFAN2.INI.before-mapfan2-win11')
    if path.exists():
        state['profiles'].append({'name': 'MAPFAN2.INI', 'old_exists': True,
                                  'old_b64': base64.b64encode(path.read_bytes()).decode('ascii')})
    for name, default_view in [('registration-backup.json', 32), ('registration-backup-64.json', 64)]:
        path = root / name
        if path.exists():
            for item in json.loads(path.read_text(encoding='utf-8')):
                old = item['old']
                state['registry'].append({'path': item['path'], 'name': '', 'view': item.get('view', default_view),
                                          'old': {'exists': old is not None, **({'value': old[0], 'type': old[1]} if old is not None else {})},
                                          'new': {'exists': True, 'value': item['new'], 'type': winreg.REG_SZ}})
    state['created_keys'] = missing_keys(state['arp'], registry)
    validate_records(state)
    return state


def attach_existing(root, assets, registry=None):
    registry = registry or Registry()
    root = validate_root(root)
    tree_files(root)
    if (root / STATE).exists():
        state = load_state(root)
    else:
        state = legacy_state(root, registry)
    refreshed = arp_records(root, registry)
    previous = {r['name']: r for r in state['arp']}
    for record in refreshed:
        if record['name'] in previous:
            original = previous[record['name']]
            current = registry.read(record['path'], record['name'], record['view'])
            if not same_value(current, original['new']) and not same_value(current, original['old']):
                raise ValueError('アプリ一覧の登録が後から変更されています: ' + record['name'])
            record['old'] = original['old']
    for name in TOOLS:
        if (assets / name).resolve() != (root / name).resolve():
            if not state['legacy'] and (root / name).exists() and state['files'].get(name) != digest(root / name):
                raise ValueError('変更されたアンインストーラーを上書きできません: ' + name)
    for name in TOOLS:
        if (assets / name).resolve() != (root / name).resolve():
            make_writable(root / name)
            shutil.copy2(assets / name, root / name)
        if not state['legacy']:
            state['files'][name] = digest(root / name)
    state['arp'] = refreshed
    save_state(root, state)
    for record in state['arp']:
        registry.write(record['path'], record['name'], record['new']['value'], record['new']['type'], record['view'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true', help='CLIの確認を省略する（対話テスト用）')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--register-only', action='store_true', help='既存版に追加し、アプリ一覧へ登録する。削除しない')
    parser.add_argument('--mode', choices=['keep', 'full'], help='keep: データ退避 / full: 退避せず完全削除')
    args = parser.parse_args()
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise ValueError('管理者として実行せず、導入したユーザーの通常権限で実行してください')
        target = args.target
        assets = Path(__file__).resolve().parent
        if target is None and (assets / STATE).exists():
            target = assets
        if target is None and args.gui:
            selected = choose_folder()
            if not selected:
                return
            target = Path(selected)
        if target is None:
            raise ValueError('--targetでインストール先を指定してください')
        if args.register_only:
            if args.dry_run:
                root = validate_root(target)
                tree_files(root)
                load_state(root) if (root / STATE).exists() else legacy_state(root, Registry())
                print('アプリ一覧への登録予定: ' + str(root) + '（変更なし）')
                return
            attach_existing(target, assets)
            message = 'アンインストーラーを追加し、Windowsのアプリ一覧に登録しました。本体は削除していません。'
            if args.gui:
                gui_message('MapFan II', message)
            else:
                print(message)
            return
        if not (target / STATE).exists():
            raise ValueError('旧版は先にRegister-Uninstaller.cmdで追加してください。対応版はUNINSTALL.mdを参照してください。')
        mode = args.mode
        if mode is None and args.gui and not args.dry_run:
            mode = choose_removal_mode(target)
            if mode is None:
                return
        info = plan(target, mode or 'keep')
        message = (f'対象: {info["root"]}\n\n削除する本体ファイル: {len(info["remove"])} 個\n'
                   f'退避するユーザー・変更済みファイル: {len(info["preserve"])} 個\n'
                   f'退避先: {Path(os.environ["LOCALAPPDATA"]) / "MapFanII-UninstallBackups"}\n\n'
                   'INIとOLE登録は記録した導入前の状態へ戻します。後から他の導入先が変更した登録は保持します。')
        if info['mode'] == 'full':
            message = (f'完全削除\n対象: {info["root"]}\n\n本体・保存データ等: {len(info["remove"])} ファイル\n'
                       f'この導入先に対応する過去の退避・保管: {len(info["history"])} フォルダー\n\n'
                       '退避は作成しません。保存データは元に戻せません。\n'
                       'この導入で追加した設定と登録を解除し、導入前からあった値は復元します。\n'
                       '別の導入先の設定・退避データは削除しません。')
        if info['state']['legacy'] and info['mode'] != 'full':
            message += '\n\n旧版の保守モード: 本体フォルダー全体を隣接する保管フォルダーへ移動します。復元情報のない設定は保持します。'
        if info['running']:
            message += '\n\n実行前に終了してください: ' + ', '.join(info['running'])
        if args.dry_run:
            if args.gui:
                gui_message('MapFan II アンインストールのプレビュー', message)
            else:
                print(message)
            return
        if info['running']:
            raise ValueError('MapFan関連アプリを終了してから実行してください: ' + ', '.join(info['running']))
        if args.gui:
            confirmed = gui_message('MapFan II アンインストール', message + '\n\n実行しますか？', confirm=True)
        else:
            print(message)
            word = 'DELETE' if info['mode'] == 'full' else 'UNINSTALL'
            confirmed = args.yes or input(f'実行する場合は {word} と入力してください: ') == word
        if not confirmed:
            return
        report = execute(info)
        message = ('完全削除しました。退避データは作成していません。' if report.get('mode') == 'full'
                   else 'アンインストールしました。\n退避先: ' + report['backup'])
        if report['warnings']:
            message += '\n\n保持・確認が必要な項目:\n' + '\n'.join(report['warnings'])
        if args.gui:
            gui_message('MapFan II', message)
        else:
            print(message)
    except Exception as error:
        if args.gui:
            gui_message('MapFan II アンインストール', str(error), error=True)
        else:
            print('エラー:', error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
