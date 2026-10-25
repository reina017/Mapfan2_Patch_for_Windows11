"""Uninstaller tests use isolated files and an in-memory HKCU adapter only."""
import contextlib
import copy
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import winreg
import uninstall as u


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.keys = set()

    def read(self, path, name='', view=32):
        value = self.values.get((path, name, view))
        return {'exists': True, 'value': value[0], 'type': value[1], 'key_existed': True} if value else {
            'exists': False, 'key_existed': (path, view) in self.keys}

    def write(self, path, name, value, kind, view=32):
        self.values[path, name, view] = copy.deepcopy(value), kind
        parts = path.split('\\')
        for n in range(1, len(parts) + 1):
            self.keys.add(('\\'.join(parts[:n]), view))

    def remove_value(self, path, name='', view=32):
        self.values.pop((path, name, view), None)

    def remove_empty_key(self, path, view=32):
        if any(p == path and v == view for p, _, v in self.values):
            return
        if any(p.startswith(path + '\\') and v == view for p, v in self.keys):
            return
        self.keys.discard((path, view))


@contextlib.contextmanager
def fixture(old_profiles=False):
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='mapfan-uninstall-test-') as directory:
        base = Path(directory).resolve()
        assert base.parent == Path(tempfile.gettempdir()).resolve()
        assert base.name.startswith('mapfan-uninstall-test-')
        appdata, root = base / 'appdata', base / 'installed'
        root.mkdir()
        profiles = appdata / 'VirtualStore/Windows'
        profiles.mkdir(parents=True)
        if old_profiles:
            (profiles / 'MAPFAN2.INI').write_bytes(b'[old]\r\nvalue=previous\r\n')
            (profiles / 'EXTRAFAN.INI').write_bytes(b'previous-extra')
        (root / 'MapFan2.exe').write_bytes(b'test application')
        (root / 'SYSTEM.SPF').write_bytes(b'original product spot file')
        (root / 'MAPFAN2.INI').write_text('[MapFan2 Preferences]\nExeFilePath=' + str(root) + '\n', encoding='cp932')
        (root / 'EXTRAFAN.INI').write_bytes(b'installed-extra')
        (root / 'SPOTFAN.INI').write_bytes(b'installed-spot')
        registry = FakeRegistry()
        inventory = {p.name: u.digest(p) for p in root.iterdir()}
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(appdata)}), mock.patch.object(u, 'running_apps', return_value=[]):
            try:
                yield base, root, profiles, registry, inventory
            finally:
                os.chdir(original_cwd)


class UninstallTests(unittest.TestCase):
    def test_readonly_cd_files_and_profiles_are_supported(self):
        with fixture(old_profiles=True) as (_, root, profiles, registry, inventory):
            old = profiles / 'EXTRAFAN.INI'
            old.chmod(stat.S_IREAD)
            (root / 'EXTRAFAN.INI').chmod(stat.S_IREAD)
            doc = root / 'README.DOC'
            doc.write_bytes(b'readonly CD file')
            doc.chmod(stat.S_IREAD)
            inventory[doc.name] = u.digest(doc)
            u.activate_install(root, inventory, registry)
            self.assertFalse((profiles / 'EXTRAFAN.INI').stat().st_file_attributes & 1)
            u.execute(u.plan(root), registry)
            self.assertFalse(root.exists())
            self.assertEqual(old.read_bytes(), b'previous-extra')
            self.assertTrue(old.stat().st_file_attributes & 1)

    def test_profile_registry_restore_and_userdata_survives(self):
        with fixture(old_profiles=True) as (_, root, profiles, registry, inventory):
            registry.write(u.CLSID, '', 'original registry value', winreg.REG_SZ)
            original_values = copy.deepcopy(registry.values)
            u.activate_install(root, inventory, registry)
            self.assertEqual(registry.read(u.ARP, 'InstallLocation', 64)['value'], str(root))
            (root / 'USERFILE.SPF').write_bytes(b'my saved spots')
            (root / 'notes.txt').write_bytes(b'my notes')
            (profiles / 'EXTRAFAN.INI').write_bytes(b'my changed options')
            report = u.execute(u.plan(root), registry)
            backup = Path(report['backup'])
            self.assertEqual((backup / 'files/USERFILE.SPF').read_bytes(), b'my saved spots')
            self.assertEqual((backup / 'files/notes.txt').read_bytes(), b'my notes')
            self.assertEqual((backup / 'profiles/EXTRAFAN.INI').read_bytes(), b'my changed options')
            self.assertEqual((profiles / 'MAPFAN2.INI').read_bytes(), b'[old]\r\nvalue=previous\r\n')
            self.assertEqual((profiles / 'EXTRAFAN.INI').read_bytes(), b'previous-extra')
            self.assertFalse((profiles / 'SPOTFAN.INI').exists())
            self.assertFalse(root.exists())
            self.assertEqual(registry.values, original_values)

    def test_preview_changes_nothing(self):
        with fixture() as (_, root, profiles, registry, inventory):
            u.activate_install(root, inventory, registry)
            before = copy.deepcopy(registry.values)
            state = (root / u.STATE).read_bytes()
            current_ini = (profiles / 'MAPFAN2.INI').read_bytes()
            for _ in range(2):
                info = u.plan(root)
                self.assertIn('MapFan2.exe', info['remove'])
                self.assertIn('SYSTEM.SPF', info['preserve'])
            self.assertEqual(registry.values, before)
            self.assertEqual((root / u.STATE).read_bytes(), state)
            self.assertEqual((profiles / 'MAPFAN2.INI').read_bytes(), current_ini)

    def test_gui_cancel_does_not_execute(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            before = copy.deepcopy(registry.values)
            with mock.patch.object(u.sys, 'argv', ['uninstall.py', '--target', str(root), '--gui', '--mode', 'keep']), \
                 mock.patch.object(u.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
                 mock.patch.object(u, 'gui_message', return_value=False), \
                 mock.patch.object(u, 'execute') as execute:
                u.main()
                execute.assert_not_called()
            self.assertEqual(before, registry.values)
            self.assertTrue((root / 'MapFan2.exe').exists())

    def test_mode_picker_cancel_changes_nothing(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            with mock.patch.object(u.sys, 'argv', ['uninstall.py', '--target', str(root), '--gui']), \
                 mock.patch.object(u.ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
                 mock.patch.object(u, 'choose_removal_mode', return_value=None), \
                 mock.patch.object(u, 'execute') as execute:
                u.main()
                execute.assert_not_called()
            self.assertTrue((root / 'MapFan2.exe').exists())

    def test_full_removes_userdata_without_backup_restores_baseline(self):
        with fixture(old_profiles=True) as (base, root, profiles, registry, inventory):
            registry.write(u.CLSID, '', 'original', winreg.REG_SZ)
            before = copy.deepcopy(registry.values)
            u.activate_install(root, inventory, registry)
            (root / 'USERFILE.SPF').write_bytes(b'saved spots')
            (root / 'extra').mkdir()
            (root / 'extra/notes.txt').write_bytes(b'notes')
            report = u.execute(u.plan(root, 'full'), registry)
            self.assertFalse(root.exists())
            self.assertIsNone(report['backup'])
            self.assertFalse((base / 'appdata/MapFanII-UninstallBackups').exists())
            self.assertEqual(registry.values, before)
            self.assertEqual((profiles / 'MAPFAN2.INI').read_bytes(), b'[old]\r\nvalue=previous\r\n')
            self.assertFalse((profiles / 'SPOTFAN.INI').exists())

    def test_full_history_only_matches_exact_original_location(self):
        with fixture() as (base, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            state = u.load_state(root)
            parent = base / 'appdata/MapFanII-UninstallBackups'
            own = parent / 'own'
            other = parent / 'other'
            unmarked = parent / 'unmarked'
            archive = root.with_name(root.name + '.uninstalled-own')
            for folder in (own, other, unmarked, archive):
                folder.mkdir(parents=True)
                (folder / 'data.spf').write_bytes(b'data')
            for folder in (own, archive):
                u.save_state(folder, state)
            wrong = copy.deepcopy(state)
            wrong['root'] = str(base / 'other-install')
            u.save_state(other, wrong)
            snapshot = (root / u.STATE).read_bytes()
            info = u.plan(root, 'full')
            self.assertEqual(set(info['history']), {own, archive})
            self.assertEqual((root / u.STATE).read_bytes(), snapshot)
            u.execute(info, registry)
            self.assertFalse(own.exists())
            self.assertFalse(archive.exists())
            self.assertTrue((other / 'data.spf').exists())
            self.assertTrue((unmarked / 'data.spf').exists())

    def test_full_legacy_deletes_instead_of_archiving(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            state = u.load_state(root)
            state['legacy'], state['files'] = True, {}
            u.save_state(root, state)
            u.execute(u.plan(root, 'full'), registry)
            self.assertFalse(root.exists())
            self.assertEqual(list(root.parent.glob(root.name + '.uninstalled-*')), [])

    def test_full_running_app_blocks_changes(self):
        with fixture() as (base, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            before = copy.deepcopy(registry.values)
            info = u.plan(root, 'full')
            with mock.patch.object(u, 'running_apps', return_value=['mapfan2.exe']):
                with self.assertRaises(ValueError):
                    u.execute(info, registry)
            self.assertTrue(root.exists())
            self.assertEqual(before, registry.values)
            self.assertFalse((base / 'appdata/MapFanII-UninstallBackups').exists())

    def test_updating_tools_preserves_original_snapshots(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            before = u.load_state(root)
            u.attach_existing(root, Path(u.__file__).parent.resolve(), registry)
            after = u.load_state(root)
            self.assertEqual(before['profiles'], after['profiles'])
            self.assertEqual(before['registry'], after['registry'])
            self.assertEqual([r['old'] for r in before['arp']], [r['old'] for r in after['arp']])
            for name in u.TOOLS:
                self.assertEqual(after['files'][name], u.digest(root / name))
            u.execute(u.plan(root, 'full'), registry)
            self.assertEqual(registry.values, {})

    def test_native_confirmation_defaults_to_no(self):
        with mock.patch.object(u.ctypes.windll.user32, 'MessageBoxW', return_value=7) as box:
            self.assertFalse(u.gui_message('title', 'text', confirm=True))
            box.assert_called_once()
            self.assertTrue(box.call_args.args[3] & 0x100)

    def test_later_registry_changes_are_preserved(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            registry.write(u.CLSID + '\\ProgID', '', 'ThirdParty.Document', winreg.REG_SZ)
            report = u.execute(u.plan(root), registry)
            self.assertEqual(registry.read(u.CLSID + '\\ProgID')['value'], 'ThirdParty.Document')
            self.assertTrue(any('後から変更' in warning for warning in report['warnings']))

    def test_other_installation_owns_profiles_and_registry(self):
        with fixture() as (_, root, profiles, registry, inventory):
            u.activate_install(root, inventory, registry)
            new_ini = '[MapFan2 Preferences]\nExeFilePath=C:\\OtherMapFan\n'
            (profiles / 'MAPFAN2.INI').write_text(new_ini, encoding='cp932')
            registry.write(u.CLSID + '\\LocalServer32', '', 'C:\\OtherMapFan\\SDBOLE32.exe', winreg.REG_SZ)
            u.execute(u.plan(root), registry)
            self.assertEqual((profiles / 'MAPFAN2.INI').read_text(encoding='cp932'), new_ini)
            self.assertEqual(registry.read(u.CLSID + '\\LocalServer32')['value'], 'C:\\OtherMapFan\\SDBOLE32.exe')

    def test_running_app_aborts_before_backup_or_changes(self):
        with fixture() as (base, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            before = copy.deepcopy(registry.values)
            info = u.plan(root)
            with mock.patch.object(u, 'running_apps', return_value=['mapfan2.exe']):
                with self.assertRaises(ValueError):
                    u.execute(info, registry)
            self.assertTrue((root / 'MapFan2.exe').exists())
            self.assertEqual(before, registry.values)
            self.assertFalse((base / 'appdata/MapFanII-UninstallBackups').exists())

    def test_manifest_cannot_remove_parent_files(self):
        with fixture() as (base, root, _, registry, inventory):
            outside = base / 'outside.txt'
            outside.write_bytes(b'keep')
            u.activate_install(root, inventory, registry)
            state = u.load_state(root)
            state['files']['../outside.txt'] = u.digest(outside)
            u.save_state(root, state)
            with self.assertRaises(ValueError):
                u.plan(root)
            self.assertEqual(outside.read_bytes(), b'keep')

    def test_unrelated_registry_path_is_rejected(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            state = u.load_state(root)
            state['registry'][0]['path'] = r'Software\UnrelatedProduct'
            u.save_state(root, state)
            with self.assertRaises(ValueError):
                u.plan(root)

    def test_modified_binary_is_backed_up(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            (root / 'MapFan2.exe').write_bytes(b'user modified binary')
            report = u.execute(u.plan(root), registry)
            self.assertEqual((Path(report['backup']) / 'files/MapFan2.exe').read_bytes(), b'user modified binary')

    def test_backup_failure_does_not_change_registry_or_remove_files(self):
        with fixture() as (_, root, _, registry, inventory):
            u.activate_install(root, inventory, registry)
            (root / 'USERFILE.SPF').write_bytes(b'keep')
            before = copy.deepcopy(registry.values)
            info = u.plan(root)
            with mock.patch.object(u.shutil, 'copy2', side_effect=OSError('copy failed')):
                with self.assertRaises(OSError):
                    u.execute(info, registry)
            self.assertEqual((root / 'USERFILE.SPF').read_bytes(), b'keep')
            self.assertTrue((root / 'MapFan2.exe').exists())
            self.assertEqual(registry.values, before)

    def test_registry_binary_old_value_roundtrip(self):
        with fixture() as (_, root, _, registry, inventory):
            registry.write(u.CLSID, '', u.pack(b'original binary'), winreg.REG_BINARY)
            before = copy.deepcopy(registry.values)
            u.activate_install(root, inventory, registry)
            u.execute(u.plan(root), registry)
            self.assertEqual(before, registry.values)

    def test_legacy_installation_is_archived_not_deleted(self):
        with fixture() as (_, root, profiles, registry, _):
            (profiles / 'MAPFAN2.INI').write_bytes((root / 'MAPFAN2.INI').read_bytes())
            (profiles / 'MAPFAN2.INI.before-mapfan2-win11').write_bytes(b'previous legacy INI')
            marker = {'dll': 'MFCO30.DLL', 'original_sha256': '4d0257b67901e55bb857fa19924dfb8b1d9dd59e0fed411489f1b52f86b4cfc5'}
            (root / 'win11-patch.json').write_text(json.dumps(marker), encoding='utf-8')
            server = '"' + str(root / 'SDBOLE32.exe') + '"'
            registry.write(u.CLSID + '\\LocalServer32', '', server, winreg.REG_SZ)
            old = [{'path': u.CLSID + '\\LocalServer32', 'old': None, 'new': server}]
            (root / 'registration-backup.json').write_text(json.dumps(old), encoding='utf-8')
            original_digest = u.digest
            def fixture_digest(path):
                return '3f258db77f08fc7f970baf1cb67aa9e926c43d6c5fdc7a90062b0050f4e8a905' if path.name == 'MapFan2.exe' else original_digest(path)
            with mock.patch.object(u, 'digest', side_effect=fixture_digest):
                u.attach_existing(root, Path(u.__file__).resolve().parent, registry)
            self.assertTrue(u.load_state(root)['legacy'])
            self.assertTrue((root / 'Uninstall.cmd').exists())
            report = u.execute(u.plan(root), registry)
            archive = next(root.parent.glob(root.name + '.uninstalled-*'))
            self.assertFalse(root.exists())
            self.assertEqual((archive / 'MapFan2.exe').read_bytes(), b'test application')
            self.assertEqual((archive / 'SYSTEM.SPF').read_bytes(), b'original product spot file')
            self.assertEqual((profiles / 'MAPFAN2.INI').read_bytes(), b'previous legacy INI')
            self.assertFalse(registry.read(u.CLSID + '\\LocalServer32')['exists'])
            self.assertFalse(registry.read(u.ARP, 'InstallLocation', 64)['exists'])
            self.assertTrue(report['legacy'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
