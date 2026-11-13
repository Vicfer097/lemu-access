"""Captura local en la laptop. No descarga ni activa sensores al importar."""
from pathlib import Path
import urllib.request

MODELS = {
    'yunet.onnx': 'face_detection_yunet/face_detection_yunet_2023mar.onnx',
    'sface.onnx': 'face_recognition_sface/face_recognition_sface_2021dec.onnx',
}

def download_models():
    Path('models').mkdir(exist_ok=True)
    for name, remote in MODELS.items():
        target = Path('models') / name
        if not target.exists():
            temporary = target.with_suffix('.partial')
            urllib.request.urlretrieve('https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/' + remote, temporary)
            if temporary.stat().st_size < 10000:
                raise RuntimeError('Descarga del modelo incompleta')
            temporary.replace(target)

class Biometrics:
    def __init__(self, camera=0, microphone=None):
        import cv2
        from resemblyzer import VoiceEncoder
        self.cv = cv2
        self.camera = camera
        self.microphone = microphone
        self.detector = cv2.FaceDetectorYN.create('models/yunet.onnx', '', (320, 320))
        self.recognizer = cv2.FaceRecognizerSF.create('models/sface.onnx', '')
        self.encoder = VoiceEncoder(device='cpu')

    def face(self):
        import time
        cv = self.cv
        cap = cv.VideoCapture(self.camera)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('No se puede leer la webcam')
                frame = cv.resize(frame, (640, 480))
                self.detector.setInputSize((640, 480))
                _, faces = self.detector.detect(frame)
                if faces is not None and len(faces) == 1:
                    aligned = self.recognizer.alignCrop(frame, faces[0])
                    return self.recognizer.feature(aligned).flatten().tolist()
            raise RuntimeError('Debe aparecer exactamente un rostro visible')
        finally:
            cap.release()

    def voice(self):
        import numpy as np
        import sounddevice as sd
        from resemblyzer import preprocess_wav
        print('Habla durante 6 segundos: Mi voz confirma mi acceso a esta maqueta.', flush=True)
        samples = sd.rec(6 * 16000, samplerate=16000, channels=1, dtype='float32', device=self.microphone)
        sd.wait()
        audio = preprocess_wav(samples.flatten(), source_sr=16000)
        if len(audio) < 16000 or np.sqrt(np.mean(audio ** 2)) < .005:
            raise RuntimeError('Audio insuficiente o demasiado silencioso')
        return self.encoder.embed_utterance(audio).tolist()

def similarity(a, b):
    import math
    if len(a) != len(b) or not a:
        return -1
    denom = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denom if denom else -1
