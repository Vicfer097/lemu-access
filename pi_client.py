import argparse
import json
import os
import queue
import threading
import time
import urllib.request
from urllib.parse import urlparse

def request(server, token, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(server.rstrip('/')+path, data=data,
        headers={'Authorization': 'Bearer '+token, 'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

class Door:
    def __init__(self, hardware=False, lock_pin=17, door_pin=27):
        self.hardware = hardware
        if hardware:
            from gpiozero import AngularServo
            self.lock = AngularServo(lock_pin, initial_angle=None)
            self.door = AngularServo(door_pin, initial_angle=None)
            self.door.angle = -60
            time.sleep(.8)
            self.lock.angle = -60
            time.sleep(.8)

    def cycle(self):
        if not self.hardware:
            print('[SIMULADO] Retirar seguro → abrir → cerrar → poner seguro', flush=True)
            return
        self.lock.angle = 60
        time.sleep(.8)
        self.door.angle = 60
        time.sleep(4)
        self.door.angle = -60
        time.sleep(1)
        self.lock.angle = -60
        time.sleep(.8)

    def close(self):
        if self.hardware:
            self.lock.close()
            self.door.close()

def cards(reader, pending):
    if reader == 'rc522':
        from mfrc522 import SimpleMFRC522
        device = SimpleMFRC522()
        last_uid, last_time = None, 0
        while True:
            uid, _ = device.read()
            if uid != last_uid or time.monotonic()-last_time > 5:
                pending.put(str(uid))
                last_uid, last_time = uid, time.monotonic()
            time.sleep(.2)
    else:
        while True:
            try:
                uid = input('UID de tarjeta (o lector USB tipo teclado): ').strip()
                if uid:
                    pending.put(uid)
            except EOFError:
                return

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--server', default='http://127.0.0.1:8080')
    p.add_argument('--hardware', action='store_true')
    p.add_argument('--reader', choices=['none','keyboard','rc522'], default='none')
    p.add_argument('--lock-pin', type=int, default=17)
    p.add_argument('--door-pin', type=int, default=27)
    a = p.parse_args()
    if urlparse(a.server).scheme not in ('http', 'https'):
        p.error('URL inválida')
    token = os.environ.get('DEVICE_TOKEN')
    if not token:
        p.error('Define DEVICE_TOKEN con el valor de data/config.json de la laptop')
    pending = queue.Queue(maxsize=10)
    if a.reader != 'none':
        threading.Thread(target=cards, args=(a.reader,pending), daemon=True).start()
    door = Door(a.hardware, a.lock_pin, a.door_pin)
    seen = set()
    try:
        while True:
            try:
                response = request(a.server, token, '/api/device/command')
                command = response['command']
                if command and command['id'] not in seen and command['expires'] > response['server_time']:
                    seen.add(command['id'])
                    success = False
                    try:
                        door.cycle()
                        success = True
                    finally:
                        request(a.server, token, '/api/device/ack', {'id':command['id'], 'success':success})
                try:
                    uid = pending.get_nowait()
                except queue.Empty:
                    uid = None
                if uid:
                    request(a.server, token, '/api/device/card', {'uid':uid})
            except Exception as exc:
                print('Comunicación/hardware:', exc, flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        door.close()

if __name__ == '__main__':
    main()
