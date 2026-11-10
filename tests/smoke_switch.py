#!/usr/bin/env python3
"""In-process smoke run (no hardware): the real HTTP server on a random loopback port over the simulated world
(tests/fakeworld.py), Mac + phone holding the slots. POST /api/switch, follow GET /api/state until done, print the
step timings (fake clock) and the final state. Run: python3 tests/smoke_switch.py"""
import json, logging, sys, threading
from pathlib import Path
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import controller
from fakeworld import World, PHONE, MAC

def call(port,path,body=None):
    req=Request(f'http://127.0.0.1:{port}{path}',data=None if body is None else json.dumps(body).encode(),method='GET' if body is None else 'POST',
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=30) as r:return json.loads(r.read())

def main():
    logging.basicConfig(level=logging.INFO,format='  log: %(message)s',stream=sys.stdout)
    world=World([PHONE,MAC])
    with world.running():
        server=controller.Server(('127.0.0.1',0),world.pc);port=server.server_address[1]
        threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.05),daemon=True).start()
        try:
            reply=call(port,'/api/switch',{'source':'desk','request_id':'smoke1'})
            print(f'POST /api/switch (port {port}) -> accepted={reply["accepted"]} id={reply["operation"]["id"]} seq={reply["seq"]}')
            seq=reply['seq'];phases=[]
            while True:
                state=call(port,f'/api/state?after={seq}&wait=5');seq=state['seq'];op=state['operation']
                if op and (not phases or phases[-1]!=op['phase']):phases.append(op['phase'])
                if op and op['phase'] in ('done','failed','choose'):break
            print('phases seen:',' -> '.join(phases))
            for step in op['steps']:print(f'  {step["name"]:<11} {step["label"]:<26} {step["state"]:<7} {step["seconds"]:.2f} s')
            print('result:',json.dumps(op['result'],ensure_ascii=False))
            print('final /api/state:');print(json.dumps(state,indent=2,ensure_ascii=False))
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
