#!/usr/bin/env python3
"""Install the Mac controller using a separately provisioned private config."""
from pathlib import Path
import argparse,json,plistlib,subprocess,sys,shutil,os
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
if sys.platform!='darwin':raise SystemExit('Run this installer on macOS')
config=json.loads(Path(a.config).read_text())
if config.get('id')!='mac' or len(config.get('token',''))<32:raise SystemExit('A provisioned Mac config is required')
state=Path.home()/'.local/state/bose-control';state.mkdir(parents=True,exist_ok=True,mode=0o700)
f=state/'config.json';f.write_text(json.dumps(config,indent=2));f.chmod(0o600)
venv=state/'venv'
if not (venv/'bin/python3').exists():subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
if subprocess.run([str(venv/'bin/python3'),'-c','import objc, IOBluetooth, Foundation'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
    subprocess.run([str(venv/'bin/python3'),'-m','pip','install',str(root/'vendor/bosectl/python')],check=True)
app=Path.home()/'Applications/Bose Connections.app/Contents';(app/'MacOS').mkdir(parents=True,exist_ok=True)
exe=app/'MacOS/Bose Connections'
info=dict(CFBundleName='Bose Connections',CFBundleIdentifier='local.bose.connections.gui',CFBundleExecutable='Bose Connections',CFBundlePackageType='APPL',CFBundleVersion='1',CFBundleShortVersionString='0.1',LSUIElement=True,NSAppTransportSecurity=dict(NSAllowsLocalNetworking=True),NSBluetoothAlwaysUsageDescription='Choose which remembered devices connect to your Bose 700.',NSBluetoothPeripheralUsageDescription='Control the Bluetooth connections of your Bose 700.',BosePython=str(venv/'bin/python3'),BoseController=str(root/'controller.py'),BoseConfig=str(f))
(app/'Info.plist').write_bytes(plistlib.dumps(info))
subprocess.run(['xcrun','clang','-fobjc-arc','-framework','Cocoa','-framework','WebKit','-framework','CoreBluetooth',str(root/'mac/Launcher.m'),'-o',str(exe)],check=True)
subprocess.run(['codesign','--force','--sign','-',str(app.parent)],check=True)
plist=Path.home()/'Library/LaunchAgents/local.bose.connections.plist';plist.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}',str(plist)],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
plist.write_bytes(plistlib.dumps(dict(Label='local.bose.connections',ProgramArguments=[str(exe),'--background'],WorkingDirectory=str(root),RunAtLoad=True,KeepAlive=True,StandardOutPath=str(state/'launcher.log'),StandardErrorPath=str(state/'launcher-error.log'))))
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(plist)],check=True)
print('Installed Bose Connections. Open it from Applications and allow Bluetooth when macOS asks.')
