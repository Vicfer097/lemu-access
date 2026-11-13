import argparse
from core import Store

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Ejecutar en la laptop con el servidor detenido')
    p.add_argument('uid')
    p.add_argument('name')
    p.add_argument('--camera', type=int, default=0)
    p.add_argument('--microphone', type=int)
    a = p.parse_args()
    from biometrics import Biometrics
    bio = Biometrics(a.camera, a.microphone)
    input('Mira la cámara y presiona Enter: ')
    face = bio.face()
    input('Coloca el micrófono y presiona Enter: ')
    voice = bio.voice()
    Store().enroll(a.uid, a.name, face, voice)
    print('Usuario registrado. Las capturas originales no se guardaron.')
