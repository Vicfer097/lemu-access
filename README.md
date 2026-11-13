# Lemu Access — maqueta de acceso con tres comprobaciones

Versión de prueba: RFID → rostro → voz → servo de seguro → servo de puerta.
La laptop procesa biometría, aloja el panel web y guarda SQLite. La Raspberry Pi 4
de 1 GB consulta órdenes y mueve la maqueta. Descargar únicamente en la Pi NO
reemplaza la instalación en la laptop: ambos equipos ejecutan una parte.

## Qué incluye

- Panel adaptable a celular, login, usuarios de prueba, activar/suspender usuarios.
- Historial de las últimas 200 verificaciones, filtros y aviso de tres fallos en un minuto.
- Registro persistente en SQLite; no se guardan fotografías ni audio original.
- Verificación facial YuNet + SFace y verificación del hablante con Resemblyzer.
- Modo simulado sin dependencias externas, separado del modo real.
- Cliente de Raspberry con servos opcionales y lector manual, USB tipo teclado o RC522.
- Órdenes de un solo consumo, vencimiento de 10 segundos y confirmación del ciclo.
- Seis pruebas automatizadas y configuración de GitHub Actions.

## 1. Prueba inmediata, sin sensores ni instalar librerías

Usa Python 3.10 o 3.11. Abre una terminal dentro de esta carpeta:

```powershell
python server.py --mode simulation
```

El primer arranque crea `data/config.json`, con contraseña aleatoria del panel y
`device_token`. No compartas ni subas este archivo. Abre `http://127.0.0.1:8080`.
En otra terminal de PowerShell, dentro de la misma carpeta:

```powershell
$env:DEVICE_TOKEN = (Get-Content data/config.json | ConvertFrom-Json).device_token
python pi_client.py
```

Entra al panel con `admin_password`, registra un nombre y tarjeta (ejemplo `123`),
y usa esa tarjeta en la prueba. Marca/desmarca rostro y voz. Solo al aprobar ambos
verás en la segunda terminal el ciclo simulado. Prueba una tarjeta desconocida,
una persona suspendida y fallos biométricos. No se reutilizan aprobaciones anteriores.

El modo simulado NO reconoce personas ni mueve servos por defecto.

## 2. Panel y Raspberry en la misma red

Detén el servidor anterior y ejecútalo en la laptop:

```powershell
python server.py --mode simulation --host 0.0.0.0
ipconfig
```

Busca la IPv4 del adaptador de tu red, por ejemplo `192.168.1.50`. Desde el celular
abre `http://192.168.1.50:8080`. Reserva esa IP en el router. Permite Python/puerto
8080 únicamente en el perfil privado del firewall; no abras puertos del router.
`0.0.0.0` es una dirección de escucha, no la URL para el celular.

En Raspberry Pi OS, copia o clona esta carpeta y ejecuta:

```bash
cd lemu-access
python3 -m venv .venv
source .venv/bin/activate
export DEVICE_TOKEN='COPIAR_device_token_DE_LA_LAPTOP'
python pi_client.py --server http://192.168.1.50:8080
```

No necesitas instalar PyTorch, OpenCV ni Resemblyzer en la Pi. Ambos equipos deben
estar encendidos. Si el cliente está desconectado no se inicia un nuevo intento.
El panel consulta cambios cada tres segundos y avisa mientras está abierto;
no hay notificaciones push, correo ni monitoreo de personas que no presenten tarjeta.

## 3. Webcam y micrófono reales en la laptop

Instala dependencias en un entorno virtual de la LAPTOP, no en la Pi:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-laptop.txt
python -c "from biometrics import download_models; download_models()"
```

La instalación y la primera carga de Resemblyzer necesitan internet para descargar
dependencias/pesos. Una vez disponibles, las verificaciones funcionan localmente.
En Windows, si `webrtcvad` requiere compilar, instala las herramientas C++ de
Microsoft Build Tools. En Linux puede requerir `build-essential`, `python3-dev`
y `libportaudio2`. Las versiones admitidas no constituyen un entorno biométrico
validado en este equipo; si un paquete falla, conserva el error para ajustar la instalación.

Con el servidor DETENIDO, enrola una persona mirando a la cámara y usando el
micrófono de los audífonos:

```powershell
python enroll.py 123 "Fernando"
python server.py --mode real --host 0.0.0.0
```

La cámara predeterminada es índice `0`; usa `--camera 1` en ambos comandos si hace
falta. Para elegir micrófono:

```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
python enroll.py 123 "Fernando" --microphone 2
python server.py --mode real --host 0.0.0.0 --microphone 2
```

Repite enrolamiento por persona. No uses una tarjeta real ya asignada para otra
persona. La lectura debe tener EXACTAMENTE el mismo UID que se registró, incluidos
ceros iniciales si el lector los entrega. La webcam busca un único rostro hasta
10 segundos; después se graban seis segundos de voz. Mira el estado del panel
y escucha/lee el aviso en la terminal de la laptop antes de hablar.

Los umbrales de ejemplo están en `server.py`: rostro `0.45`, voz `0.80`.
Se comparan embeddings contra el usuario de la tarjeta, nunca contra otro usuario.
Debes calibrarlos con muestras genuinas y de otras personas antes de presentar
resultados de precisión. No se ha medido rendimiento ni tasa de errores aquí.

## 4. Tarjetas: primero identificar el módulo

RFID es la tecnología, no el modelo. El modo `keyboard` sirve para escribir un
UID o para un lector USB que se comporte como teclado y envíe Enter:

```bash
python pi_client.py --server http://192.168.1.50:8080 --reader keyboard
```

También puedes ingresar el UID desde una segunda terminal en la laptop con ese
mismo comando y token. La biometría siempre se captura en la laptop.

SOLO si el módulo dice **RC522/MFRC522**, habilita SPI con `sudo raspi-config`
(Interface Options → SPI), reinicia e instala:

```bash
python -m pip install mfrc522 spidev
python pi_client.py --server http://192.168.1.50:8080 --reader rc522
```

| RC522 | GPIO BCM de Raspberry | Pin físico |
|---|---|---|
| SDA/SS | GPIO8 / CE0 | 24 |
| SCK | GPIO11 | 23 |
| MOSI | GPIO10 | 19 |
| MISO | GPIO9 | 21 |
| RST | GPIO25 | 22 |
| 3.3V | 3.3V | 1 |
| GND | Tierra | 6 |
| IRQ | Sin conectar | — |

Nunca alimentes un RC522 de 3.3 V con 5 V. Para PN532 u otro lector se necesita
otro controlador: no conectes este cableado por suposición. Usar solo el UID es
una identificación básica de maqueta; no protege contra tarjetas clonadas.

## 5. Servos de maqueta

Prueba inicialmente con los brazos de los servos desacoplados del mecanismo.
Verifica voltaje/corriente de tus servos y usa fuente externa adecuada, con tierra
común con la Raspberry. NO alimentes los servos desde GPIO ni conectes la salida
de 5 V de la fuente a una señal GPIO.

| Conexión | Pin físico de Raspberry |
|---|---|
| Señal servo del seguro, GPIO17 | 11 |
| Señal servo de puerta, GPIO27 | 13 |
| Tierra común | 6, u otro GND |
| Alimentación de ambos servos | Fuente externa, según su especificación |

```bash
python -m pip install -r requirements-pi.txt
python pi_client.py --server http://192.168.1.50:8080 --hardware --reader rc522
```

`--hardware` activa movimiento real, incluso si el servidor está en simulación
para probar la mecánica. Al arrancar establece puerta cerrada y seguro colocado.
Revisa primero posiciones: `-60` cerrado/seguro y `60` abierto/liberado en
`pi_client.py`. Los pines usan numeración BCM, modificable por `--lock-pin` y
`--door-pin`. Los ángulos son ejemplos y pueden forzar un mecanismo mal calibrado.

Secuencia: retirar seguro, esperar 0.8 s, abrir, mantener 4 s, cerrar, esperar 1 s,
colocar seguro. El GPIO usa pulsos predeterminados de gpiozero; si tu servo tiene
otro rango, ajústalo conforme a su ficha. Puede existir vibración según el backend.

No hay sensores de posición en esta versión: `ciclo_ejecutado` significa que el
programa terminó los movimientos, NO que la puerta físicamente abrió/cerró.
Al terminar por Ctrl+C se liberan recursos; no se garantiza una posición final
ante pérdida de energía, desconexión o atasco. Diseñado exclusivamente para maqueta.

## Límites y protección de datos

- No hay prueba de vida facial ni protección contra voz grabada/sintética.
- La frase es fija y solo se compara el hablante; no se comprueba su transcripción.
- No llamar a un rechazo “intruso confirmado”: puede ser ruido o mala iluminación.
- Panel y cliente usan tokens; la conexión HTTP local no cifra tráfico. Úsalo en
  una red de confianza, sin exponerlo a internet. Para otra etapa agrega HTTPS.
- Las plantillas de rostro/voz están en SQLite sin cifrado propio; protege la
  cuenta y el disco de la laptop, enrola con consentimiento y borra al terminar.
- No subir `data/`, tokens ni plantillas a GitHub. `.gitignore` los excluye.
- Los intentos de una misma tarjeta tienen pausa de cinco segundos y bloqueo
  al acumular tres fallos en un minuto. No sustituye un sistema de producción.
- Las órdenes se reclaman antes de mover el servo: si se pierde la conexión no
  se reenvían automáticamente. Se prioriza evitar movimientos repetidos.
- No hay cola local de RFID sin conexión; un intento sin servidor no abre ni se
  registra en el servidor. Los eventos ya guardados sobreviven reinicios.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Las seis pruebas cubren flujo correcto, fallos, tarjeta desconocida/suspendida,
vencimiento, error de cámara, consumo único de órdenes, autenticación y rechazo
de simulación en modo real. La prueba HTTP usa un transporte en memoria; no
valida firewall ni conexión de red real. Biometría y hardware requieren pruebas
físicas en tus equipos.

## Publicar y descargar desde GitHub

Este código se entrega preparado para un repositorio independiente `lemu-access`.
No incluye un remoto inventado. Si GitHub CLI está instalado y autenticado, desde
esta carpeta ya inicializada como repositorio:

```bash
gh repo create lemu-access --private --source . --remote origin --push
```

Luego, en la Raspberry, usa la URL real que devuelva GitHub:

```bash
git clone URL_REAL_DEL_REPOSITORIO
cd lemu-access
```

Un repositorio privado requiere autenticación para clonar. Conserva también una
copia en la laptop. La configuración de cada equipo se hace después de descargar.

## Referencias de los adaptadores

- OpenCV: https://docs.opencv.org/4.13.0/d0/dd4/tutorial_dnn_face.html
- Modelos: https://github.com/opencv/opencv_zoo
- Resemblyzer: https://github.com/resemble-ai/Resemblyzer
- Servos: https://gpiozero.readthedocs.io/en/stable/api_output.html

Los modelos y dependencias mantienen sus propias licencias; no están incluidos
en el repositorio. No redistribuir sin revisar sus condiciones.
