#!/usr/bin/env python3
"""Build a personally signed Android APK with an installed Android SDK/JDK."""
from pathlib import Path
import argparse, os, secrets, shutil, subprocess, tempfile, zipfile

root=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--sdk',default=os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT'))
p.add_argument('--platform',default='android-35')
p.add_argument('--build-tools',help='SDK build-tools version (default: highest installed)')
a=p.parse_args()
if not a.sdk:p.error('Set ANDROID_HOME or pass --sdk')
sdk=Path(a.sdk).expanduser();platform=sdk/'platforms'/a.platform/'android.jar'
versions=list((sdk/'build-tools').glob('*'))
if not versions:p.error('Install Android SDK build-tools')
bt=sdk/'build-tools'/a.build_tools if a.build_tools else max(versions,key=lambda v:tuple(int(x) if x.isdigit() else 0 for x in v.name.split('.')))
if not platform.exists():p.error('Install SDK platform '+a.platform)
if not shutil.which('javac'):p.error('Install JDK 17+ and put javac on PATH')
private=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'bose-control';private.mkdir(parents=True,exist_ok=True,mode=0o700)
password=private/'signing-password';key=private/'signing.p12'
def run(args):subprocess.run([str(x) for x in args],check=True)
if not password.exists():password.write_text(secrets.token_urlsafe(32));password.chmod(0o600)
if not key.exists():
 run(['keytool','-genkeypair','-keystore',key,'-storepass:file',password,'-keypass:file',password,'-alias','bose','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Bose Connections']);key.chmod(0o600)
with tempfile.TemporaryDirectory(prefix='bose-build-') as folder:
 out=Path(folder);classes=out/'classes';classes.mkdir();dex=out/'dex';dex.mkdir()
 run([bt/'aapt2','compile','--dir',root/'android/res','-o',out/'resources.zip'])
 run([bt/'aapt2','link','-o',out/'unsigned.apk','-I',platform,'--manifest',root/'android/AndroidManifest.xml',out/'resources.zip'])
 run(['javac','--release','8','-classpath',platform,'-d',classes,*sorted((root/'android').glob('*.java'))])
 run([bt/'d8','--lib',platform,'--min-api','26','--output',dex,*classes.rglob('*.class')])
 with zipfile.ZipFile(out/'unsigned.apk','a') as archive:
  for f in dex.glob('*.dex'):archive.write(f,f.name)
  for f in (root/'web').iterdir():archive.write(f,'assets/web/'+f.name)
 run([bt/'zipalign','-f','4',out/'unsigned.apk',out/'aligned.apk'])
 (root/'dist').mkdir(exist_ok=True)
 apk=root/'dist/bose-connections.apk'
 run([bt/'apksigner','sign','--ks',key,'--ks-key-alias','bose','--ks-pass','file:'+str(password),'--out',apk,out/'aligned.apk'])
 run([bt/'apksigner','verify',apk])
print('Built and signature-verified dist/bose-connections.apk')
