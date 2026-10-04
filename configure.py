#!/usr/bin/env python3
"""Create private controller config; no Bluetooth changes or secret output."""
import argparse,json,secrets,ipaddress
from pathlib import Path
from protocol import mac_bytes
from controller import save_config
p=argparse.ArgumentParser()
p.add_argument('--id',choices=['pc','mac','phone'],required=True)
p.add_argument('--name')
p.add_argument('--headset',required=True,help='Paired NC700 Bluetooth MAC address')
p.add_argument('--bind',help='This controller Tailscale IPv4 address; omit for local-only')
p.add_argument('--peer',action='append',default=[],metavar='ID=TAILSCALE_IP')
p.add_argument('--role',action='append',default=[],metavar='ID=BLUETOOTH_MAC')
p.add_argument('--token-from',type=Path,help='Existing private config to reuse the mesh token')
p.add_argument('--output',type=Path,default=Path.home()/'.local/state/bose-control/config.json')
a=p.parse_args()
def ip(value):
 address=ipaddress.ip_address(value)
 if address.version!=4 or address not in ipaddress.ip_network('100.64.0.0/10'):p.error('Use a Tailscale IPv4 address')
 return str(address)
def pair(value):
 parts=value.split('=',1)
 if len(parts)!=2 or parts[0] not in ('pc','mac','phone'):p.error('Use ID=value with pc, mac or phone')
 return parts
try:
 mac_bytes(a.headset);roles={};peers=[]
 for value in a.role:
  ident,address=pair(value);mac_bytes(address);roles[ident]=address.upper()
 for value in a.peer:
  ident,address=pair(value)
  if ident==a.id:p.error('A peer must be another controller')
  peers.append(dict(id=ident,name=ident.title(),url='http://'+ip(address)+':8848'))
 token=json.loads(a.token_from.read_text())['token'] if a.token_from else secrets.token_urlsafe(32)
 if len(token)<32:p.error('Shared token must be at least 32 characters')
 if a.output.exists():p.error('Output already exists; preserve it or choose another --output')
 config=dict(id=a.id,name=a.name or a.id.title(),headset=a.headset.upper(),channel=8,roles=roles,peers=peers,token=token)
 if a.bind:config['mesh_bind']=ip(a.bind)
 save_config(config,a.output)
except (ValueError,KeyError,OSError) as e:p.error(str(e))
print('Private configuration saved to '+str(a.output))
