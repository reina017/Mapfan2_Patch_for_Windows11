"""Public tests contain no original product files. Optional local-CD integration."""
import argparse
import configparser
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile
import os
import build_release
import install
import patch_mapfan
import uninstall
from test_uninstall import FakeRegistry, fixture


class PublicTests(unittest.TestCase):
    def test_target_selection_accepts_a_new_folder_without_creating_it(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-target-test-') as work:
            target = Path(work) / 'new location' / 'MapFanII'
            self.assertEqual(install.validate_install_target(target), target.resolve())
            self.assertFalse(target.exists())

    def test_target_selection_preserves_an_unrelated_nonempty_folder(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-target-test-') as work:
            target = Path(work)
            user_file = target / 'important.txt'
            user_file.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                install.validate_install_target(target)
            self.assertEqual(user_file.read_bytes(), b'keep')

    def test_target_selection_refuses_switching_an_active_installation(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-target-test-') as work:
            target = Path(work) / 'new'
            with self.assertRaises(ValueError):
                install.validate_install_target(target, str(Path(work) / 'installed'))
            self.assertFalse(target.exists())

    def prepare_owned_fixture(self, root, inventory):
        for name in ['MFCO30.DLL', 'SDBOLE32.exe', 'MapFanII-Win11.exe'] + list(uninstall.TOOLS):
            (root / name).write_bytes(b'fixture ' + name.encode())
            inventory[name] = uninstall.digest(root / name)

    def test_repair_restores_registration_without_resetting_user_data_or_backups(self):
        with fixture(old_profiles=True) as (_, root, profiles, registry, inventory):
            self.prepare_owned_fixture(root, inventory)
            uninstall.activate_install(root, inventory, registry)
            before = uninstall.load_state(root)
            old_profile_snapshots = before['profiles']
            old_registry_snapshots = [r['old'] for r in before['registry'] + before['arp']]
            saved = root / 'USERFILE.SPF'
            saved.write_bytes(b'saved user data')
            user_ini = (profiles / 'MAPFAN2.INI').read_bytes() + b'UserOption=keep\r\n'
            (profiles / 'MAPFAN2.INI').write_bytes(user_ini)
            registry.values.clear()
            install.repair_installation(root, registry)
            after = uninstall.load_state(root)
            self.assertEqual(after['profiles'], old_profile_snapshots)
            self.assertEqual([r['old'] for r in after['registry'] + after['arp']], old_registry_snapshots)
            self.assertEqual(saved.read_bytes(), b'saved user data')
            self.assertEqual((profiles / 'MAPFAN2.INI').read_bytes(), user_ini)
            self.assertEqual(registry.read(uninstall.ARP, 'InstallLocation', 64)['value'], str(root))
            self.assertTrue((root / 'uninstall-state.before-repair.json').exists())

    def test_repair_refuses_another_registered_installation(self):
        with fixture() as (_, root, _, registry, inventory):
            self.prepare_owned_fixture(root, inventory)
            uninstall.activate_install(root, inventory, registry)
            registry.write(uninstall.ARP, 'InstallLocation', r'C:\OtherMapFan', 1, 64)
            state = (root / uninstall.STATE).read_bytes()
            with self.assertRaises(ValueError):
                install.repair_installation(root, registry)
            self.assertEqual((root / uninstall.STATE).read_bytes(), state)
            self.assertFalse((root / 'uninstall-state.before-repair.json').exists())

    def test_unknown_dll_is_never_modified(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-public-test-') as work:
            dll = Path(work) / 'MFCO30.DLL'
            dll.write_bytes(b'unsupported version')
            with self.assertRaises(ValueError):
                patch_mapfan.patch_dll(dll)
            self.assertEqual(dll.read_bytes(), b'unsupported version')
            self.assertFalse(dll.with_name(dll.name + '.original').exists())

    def test_invalid_media_does_not_create_target(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-public-test-') as work:
            source, target = Path(work), Path(work) / 'target'
            with self.assertRaises(ValueError):
                install.install_from_media(source, target)
            self.assertFalse(target.exists())

    def test_existing_target_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='mapfan-public-test-') as work:
            target = Path(work) / 'target'
            target.mkdir()
            user_data = target / 'USERFILE.SPF'
            user_data.write_bytes(b'user data')
            with self.assertRaises(ValueError):
                install.install_from_media(Path(work), target)
            self.assertEqual(user_data.read_bytes(), b'user data')

    def test_source_allowlist(self):
        build_release.audit()


def integration(media):
    """Full install to a temp folder, with registry and real profiles untouched."""
    install.validate_media(media)
    with zipfile.ZipFile(build_release.ROOT / 'dist' / f'mapfan2-win11-patch-{build_release.VERSION}.zip') as archive:
        with tempfile.TemporaryDirectory(prefix='mapfan-integration-') as work:
            work = Path(work)
            assets = work / 'assets'
            assets.mkdir()
            launcher = next(n for n in archive.namelist() if n.endswith('/MapFanII-Win11.exe'))
            (assets / 'MapFanII-Win11.exe').write_bytes(archive.read(launcher))
            for name in uninstall.TOOLS:
                (assets / name).write_bytes((build_release.ROOT / name).read_bytes())
            target = work / 'installed'
            appdata = work / 'appdata'
            registry = FakeRegistry()
            with mock.patch.object(install, 'ASSETS', assets), \
                 mock.patch.object(uninstall, 'Registry', return_value=registry), \
                 mock.patch.dict('os.environ', {'LOCALAPPDATA': str(appdata)}):
                install.install_from_media(media, target)
                assert registry.read(uninstall.ARP, 'InstallLocation', 64)['value'] == str(target.resolve())
            dll = target / 'MFCO30.DLL'
            original = dll.with_name(dll.name + '.original').read_bytes()
            assert patch_mapfan.sha(dll.read_bytes()) == patch_mapfan.PATCHED
            assert patch_mapfan.patch_dll(dll) == 'already patched'
            assert patch_mapfan.patch_dll(dll, restore=True) == 'restored'
            assert dll.read_bytes() == original
            assert patch_mapfan.patch_dll(dll) == 'patched'
            cfg = configparser.RawConfigParser()
            cfg.read(appdata / 'VirtualStore/Windows/MAPFAN2.INI', encoding='cp932')
            assert cfg['MapFan2 Preferences']['MapDisc'] == str(target / 'CD-ROM')
            assert install.digest(target / 'CD-ROM/MAPFAN.DAT') == install.MANIFEST['files']['MAPFAN.DAT']
            assert len(list((target / 'CD-ROM/ADDRESS').iterdir())) == 12
            with mock.patch.dict('os.environ', {'LOCALAPPDATA': str(appdata)}), \
                 mock.patch.object(uninstall, 'running_apps', return_value=[]):
                original_cwd = Path.cwd()
                try:
                    (target / 'USERFILE.SPF').write_bytes(b'saved user spots')
                    report = uninstall.execute(uninstall.plan(target), registry)
                finally:
                    os.chdir(original_cwd)
                assert not target.exists()
                assert (Path(report['backup']) / 'files/USERFILE.SPF').read_bytes() == b'saved user spots'
                assert not registry.values
            print('PASS: CD install -> app-list registration -> uninstall -> user-data preservation; registry mocked')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.media:
        integration(args.media.resolve())
