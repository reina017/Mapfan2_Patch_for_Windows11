"""Version-checked MapFan II (1996) compatibility patch. No vendor files bundled."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import os

ORIGINAL = '4d0257b67901e55bb857fa19924dfb8b1d9dd59e0fed411489f1b52f86b4cfc5'
PATCHED = '09031f365470155f1f03a74035531e68d1205bd96661564fc23d2059a51c2feb'
DEFAULT_TARGET = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MapFanII'

def sha(b):
    return hashlib.sha256(b).hexdigest()

def patch_dll(path,restore=False):
    b=path.read_bytes()
    digest=sha(b)
    backup=path.with_name(path.name+'.original')
    if restore:
        if digest==ORIGINAL:
            return 'already original'
        if digest!=PATCHED or not backup.exists() or sha(backup.read_bytes())!=ORIGINAL:
            raise ValueError('Original backup missing or DLL version is not supported')
        path.write_bytes(backup.read_bytes())
        return 'restored'
    if digest==PATCHED:
        return 'already patched'
    if digest!=ORIGINAL:
        raise ValueError('Unsupported MFCO30.DLL version; no changes made')
    old=b'MFCUIA32.dll\0'
    new=b'OLEDLG.dll'.ljust(len(old),b'\0')
    assert b.count(old)==1
    changed=b.replace(old,new)
    assert len(changed)==len(b) and sha(changed)==PATCHED
    if backup.exists() and sha(backup.read_bytes())!=ORIGINAL:
        raise ValueError('A different backup already exists; no changes made')
    if not backup.exists():
        backup.write_bytes(b)
    path.write_bytes(changed)
    assert sha(path.read_bytes())==PATCHED
    return 'patched'

def apply(target,assets):
    launcher=assets/'MapFanII-Win11.exe'
    if not launcher.exists():
        raise FileNotFoundError(launcher)
    print('MFCO30.DLL:',patch_dll(target/'MFCO30.DLL'))
    installed=target/launcher.name
    if launcher.resolve()!=installed.resolve() and (not installed.exists() or sha(launcher.read_bytes())!=sha(installed.read_bytes())):
        shutil.copy2(launcher,installed)
    report={'patch_version':'1.1.0-beta.5','original_sha256':ORIGINAL,
            'patched_sha256':PATCHED,'dll':'MFCO30.DLL',
            'launcher':'MapFanII-Win11.exe',
            'change':'MFCUIA32.dll import -> OLEDLG.dll; ordinals 1,3,4,5,6,7,8,9 retained',
            'launch_order':['SDBOLE32.exe -Embedding','MapFan2.exe']}
    (target/'win11-patch.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Start:',installed)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,default=DEFAULT_TARGET)
    parser.add_argument('--restore-dll',action='store_true')
    args=parser.parse_args()
    if args.restore_dll:
        print(patch_dll(args.target/'MFCO30.DLL',restore=True))
    else:
        apply(args.target,Path(__file__).resolve().parent)
