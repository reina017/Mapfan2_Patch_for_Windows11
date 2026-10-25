from pathlib import Path
import winreg
import json

def registry_entries(dest):
    clsid='{95BEBF80-3B8C-11CF-B858-444553540000}'
    base='CLSID\\'+clsid
    server=str(dest/'SDBOLE32.exe')
    return {
        'MapFan.Document.1':'MapFan Document',
        'MapFan.Document.1\\CLSID':clsid,
        base:'MapFan Document',
        base+'\\LocalServer32':'"'+server+'"',
        base+'\\DefaultIcon':server+',1',
        base+'\\ProgID':'MapFan.Document.1',
        base+'\\InprocHandler32':'ole32.dll',
        base+'\\MiscStatus':'32',
        base+'\\AuxUserType\\2':'MFSPOT',
        base+'\\AuxUserType\\3':'SDBOLE32',
        base+'\\Insertable':'',
        base+'\\verb\\0':'&Edit,0,2',
        base+'\\verb\\1':'&Open,0,2',
    }
def register(dest):
    entries=registry_entries(dest)
    changes=[]
    backup=dest/'registration-backup.json'
    prior=json.loads(backup.read_text(encoding='utf-8')) if backup.exists() else []
    recorded={entry['path'] for entry in prior}
    for p,v in entries.items():
        path='Software\\Classes\\'+p
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as key:
                try: old=winreg.QueryValueEx(key,'')
                except FileNotFoundError: old=None
        except FileNotFoundError:
            old=None
        changes.append({'path':path,'old':old,'new':v})
        if path not in recorded:
            prior.append(changes[-1])
            backup.write_text(json.dumps(prior,ensure_ascii=False,indent=2),encoding='utf-8')
            recorded.add(path)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_WRITE|winreg.KEY_WOW64_32KEY) as key:
            winreg.SetValueEx(key,'',0,winreg.REG_SZ,v)
    print('Registered MapFan OLE server for current user (32-bit view).')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,required=True)
    register(parser.parse_args().target.resolve())
