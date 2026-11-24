import os
import queue
import threading
import shutil
import time
from datetime import datetime

import cv2
import keyboard
import mss
import numpy as np

CARPETA = "capturas"
INTERVALO = 0.05          # segundos entre capturas
CALIDAD_JPG = 70          # 0-100: menor = menos espacio
MONITOR = 1               # 1 = pantalla principal
INTERVALO_STATS = 20      # número de capturas entre cada mensaje de stats en la consola.

# --- Descarte de frames repetidos ---
DESCARTAR_REPETIDOS = True
TAM_COMPARACION = (320, 180)   # se compara una versión reducida (más rápido)
UMBRAL_PIXEL = 10              # diferencia (0-255) para considerar que un píxel cambió
UMBRAL_CAMBIO = 0.010          # porcentaje (0.000-1.000) fracción de píxeles que deben cambiar

salir = threading.Event()
pausado = threading.Event()
cola = queue.Queue(maxsize=200)


def alternar_pausa():
    if pausado.is_set():
        pausado.clear()
        print("\n[REANUDADO] Capturando de nuevo...")
    else:
        pausado.set()
        print("\n[PAUSADO] Pulsa F8 para continuar...")


def guardar_frames():
    """Hilo que codifica y guarda los frames mientras el principal sigue capturando."""
    while True:
        item = cola.get()
        if item is None:
            break
        ruta, img = item
        cv2.imwrite(ruta, img, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPG])


def miniatura(img):
    """Versión pequeña en gris, solo para comparar."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gris, TAM_COMPARACION, interpolation=cv2.INTER_AREA)


def hay_cambio(ref, actual):
    """True si la fracción de píxeles distintos supera el umbral."""
    diff = cv2.absdiff(ref, actual)
    cambiados = np.count_nonzero(diff > UMBRAL_PIXEL)
    return cambiados / diff.size > UMBRAL_CAMBIO


def preguntar_conservar():
    """Pregunta en consola si se conservan las capturas. Ante duda, se conservan."""
    while True:
        try:
            r = input("\n¿Quieres conservar las capturas? [s/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return True
        if r in ("s", "si", "sí"):
            return True
        if r in ("n", "no"):
            return False
        print("ERROR: Debes responder 's' o 'n'.")


def main():
    sesion = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta_sesion = os.path.join(CARPETA, sesion)
    os.makedirs(carpeta_sesion, exist_ok=True)

    keyboard.add_hotkey("f8", alternar_pausa)
    keyboard.add_hotkey("esc", salir.set)

    print("=== CAPTURADOR AUTOMÁTICO ===")
    print("• [F8] pausa/continúa. • [Esc] o Ctrl+C para salir.")
    if DESCARTAR_REPETIDOS:
        print("• Descarte de frames repetidos: ACTIVADO")
    print("Empezando en 3 segundos...\n")
    time.sleep(1)
    print("Empezando en 2 segundos...\n")
    time.sleep(1)
    print("Empezando en 1 segundo...\n")
    time.sleep(1)
    print("Capturando pantalla...\n")

    hilo = threading.Thread(target=guardar_frames, daemon=True)
    hilo.start()

    contador = 0
    repetidos = 0
    descartados = 0
    referencia = None
    siguiente = time.perf_counter()

    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[MONITOR]
            while not salir.is_set():
                if pausado.is_set():
                    time.sleep(0.1)
                    siguiente = time.perf_counter()
                    continue

                img = cv2.cvtColor(np.array(sct.grab(monitor)), cv2.COLOR_BGRA2BGR)

                guardar = True
                if DESCARTAR_REPETIDOS:
                    mini = miniatura(img)
                    if referencia is not None and not hay_cambio(referencia, mini):
                        guardar = False
                        repetidos += 1
                    else:
                        referencia = mini

                if guardar:
                    ruta = os.path.join(carpeta_sesion, f"{contador:06d}.jpg")
                    try:
                        cola.put_nowait((ruta, img))
                        contador += 1
                        if contador % INTERVALO_STATS == 0:
                            print(f"{contador} guardadas, {repetidos} repetidas omitidas...")
                    except queue.Full:
                        descartados += 1

                siguiente += INTERVALO
                espera = siguiente - time.perf_counter()
                if espera > 0:
                    time.sleep(espera)
                else:
                    siguiente = time.perf_counter()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nTerminando de guardar...")
        cola.put(None)
        hilo.join()          # espera a que se escriban todos los frames pendientes
        keyboard.unhook_all()  # ya no hacen falta F8 ni Esc

    print(f"Se han capturado {contador} imágenes "
          f"({repetidos} repetidas omitidas, {descartados} perdidas por disco lento).")

    if contador > 0 and not preguntar_conservar():
        shutil.rmtree(carpeta_sesion, ignore_errors=True)
        print("Capturas eliminadas.")
    else:
        print(f"Capturas guardadas en '{carpeta_sesion}'.")


if __name__ == "__main__":
    main()