"""Captura de audio respiratorio con micrófono lavalier externo.

Graba audio desde un micrófono para su posterior análisis acústico de la
respiración (ver los demás módulos de python/audio/). Guarda cada
grabación como WAV, y opcionalmente un JSON hermano con metadata de
temporización, pensado para poder sincronizar después esta grabación con
las lecturas del sensor cardíaco de la misma sesión (ver
python/sensor/capturar_sesion.py, que usa el mismo esquema de timestamps
con time.monotonic()).

¿Por qué 22050 Hz de samplerate y no 44100 Hz (calidad CD)?
La frecuencia respiratoria en reposo es de ~12-20 respiraciones/min
(~0.2-0.33 Hz) — extremadamente baja. Pero lo que se graba aquí no es "la
frecuencia" en sí, sino el SONIDO de la respiración (turbulencia del aire
al entrar/salir, fricativas), cuya energía acústica se concentra en
general por debajo de unos pocos kHz. Por el teorema de Nyquist, un
samplerate de 22050 Hz captura sin aliasing todo el contenido hasta
22050/2 = 11025 Hz — de sobra para el contenido acústico de la
respiración. 44100 Hz está pensado para música con contenido audible hasta
~20 kHz, algo que la respiración no necesita, y que solo duplicaría el
tamaño de archivo y el costo de procesamiento sin aportar información
extra para este análisis.

¿Por qué sd.InputStream explícito y NO sd.rec()/sd.wait()? (Fix aplicado
16/08/2026, ver bug de respiración en ceros durante reproducción de
estímulos en P01/P09). sd.rec() y sd.play() son funciones de conveniencia
de sounddevice que comparten un único "stream activo" a nivel de módulo.
Cuando python/audio/reproductor_estimulos.py llamaba a sd.play() para el
estímulo mientras esta grabación estaba en curso con sd.rec(), sd.play()
cerraba internamente la grabación (sounddevice hace stop() del stream
anterior al iniciar uno nuevo) — el micrófono dejaba de recibir audio
real y el resto del buffer quedaba en ceros/basura sin inicializar.
sd.InputStream es un objeto de stream independiente con su propio
callback: no toca ese estado global, así que puede grabar en paralelo
con un sd.OutputStream de reproducción sin que uno interrumpa al otro
(ver la misma nota, con más detalle, en reproductor_estimulos.py).
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

# Carpeta donde se guardan las grabaciones de audio de cada sesión
CARPETA_AUDIO = Path(r"C:\Tesis_Kevin\datos\sesiones\audio")


class CapturaAudio:
    """Graba audio desde un micrófono y lo guarda en WAV (+ metadata opcional).

    Attributes:
        device_id (Optional[int]): Índice del dispositivo de entrada a usar.
            None = usar el dispositivo de entrada por defecto del sistema.
        samplerate (int): Frecuencia de muestreo en Hz.
        channels (int): Número de canales a grabar (1 = mono).
    """

    def __init__(
        self,
        device_id: Optional[int] = None,
        samplerate: int = 22050,
        channels: int = 1,
    ) -> None:
        """Inicializa la captura de audio.

        Args:
            device_id: Índice del dispositivo de entrada (ver
                listar_dispositivos_audio.py). None usa el default del sistema.
            samplerate: Frecuencia de muestreo en Hz (default 22050, ver
                explicación en el docstring del módulo).
            channels: Número de canales (default 1 = mono; la respiración
                no necesita estéreo).
        """
        self.device_id = device_id
        self.samplerate = samplerate
        self.channels = channels

    def get_dispositivo_info(self) -> dict:
        """Devuelve información del dispositivo de entrada que se está usando.

        Returns:
            dict: nombre, canales_entrada, samplerate_default, device_id.
        """
        if self.device_id is not None:
            dispositivo = sd.query_devices(self.device_id)
        else:
            dispositivo = sd.query_devices(kind="input")

        return {
            "nombre": dispositivo["name"],
            "canales_entrada": dispositivo["max_input_channels"],
            "samplerate_default": dispositivo["default_samplerate"],
            "device_id": self.device_id if self.device_id is not None else sd.default.device[0],
        }

    def grabar(
        self,
        duracion_seg: float,
        participante_id: str,
        condicion: str = "test",
        fecha_hora: Optional[str] = None,
    ) -> Path:
        """Graba audio durante duracion_seg segundos y lo guarda como WAV.

        Usa un sd.InputStream explícito (no sd.rec()/sd.wait()): un
        callback en segundo plano va acumulando los bloques de audio en
        una lista mientras el hilo principal muestra una barra de
        progreso, y al salir del "with" el stream se detiene y se cierra.
        Este patrón es seguro para grabar en simultáneo con reproducción
        de audio en otro stream (ver el porqué en el docstring del
        módulo).

        Args:
            duracion_seg: Duración de la grabación, en segundos.
            participante_id: Identificador del participante, ej. "P01".
            condicion: Condición experimental de esta grabación (default "test").
            fecha_hora: Sufijo de fecha/hora para el nombre del archivo
                (formato "%Y%m%d_%H%M"). None = usa la hora actual. Se
                expone para que una sesión coordinada (ver
                python/sesion_completa.py) pueda forzar el mismo sufijo
                que el CSV cardíaco y el JSON de estímulos de la misma sesión.

        Returns:
            Path: Ruta del archivo WAV guardado.
        """
        CARPETA_AUDIO.mkdir(parents=True, exist_ok=True)

        print(f"Grabando {duracion_seg}s (device={self.device_id or 'default'})...")

        bloques_grabados = []

        def _callback_entrada(indata, frames, time_info, status):
            bloques_grabados.append(indata.copy())

        tiempo_inicio = time.monotonic()
        with sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            device=self.device_id,
            callback=_callback_entrada,
        ):
            while (transcurrido := time.monotonic() - tiempo_inicio) < duracion_seg:
                self._mostrar_progreso(transcurrido, duracion_seg)
                time.sleep(0.1)
            self._mostrar_progreso(duracion_seg, duracion_seg)
            print()
        # Salir del "with" detiene y cierra el InputStream

        grabacion = np.concatenate(bloques_grabados, axis=0)

        fecha_hora = fecha_hora or datetime.now().strftime("%Y%m%d_%H%M")
        nombre_archivo = f"{participante_id}_{condicion}_{fecha_hora}.wav"
        ruta_wav = CARPETA_AUDIO / nombre_archivo

        sf.write(ruta_wav, grabacion, self.samplerate)
        print(f"Audio guardado en: {ruta_wav}")

        return ruta_wav

    def grabar_con_metadata(
        self,
        duracion_seg: float,
        participante_id: str,
        condicion: str = "test",
        t0_externo: Optional[float] = None,
        fecha_hora: Optional[str] = None,
    ) -> dict:
        """Igual que grabar(), pero además guarda un JSON con metadata de temporización.

        El JSON queda junto al WAV con el mismo nombre (distinta extensión),
        y sirve para alinear en el tiempo esta grabación de audio con las
        lecturas del sensor cardíaco de la misma sesión.

        Args:
            duracion_seg: Duración de la grabación, en segundos.
            participante_id: Identificador del participante, ej. "P01".
            condicion: Condición experimental de esta grabación (default "test").
            t0_externo: Referencia de tiempo (time.monotonic()) compartida
                con otros hilos/procesos de la misma sesión (ver
                python/sesion_completa.py). Si se indica, timestamp_inicio
                y timestamp_fin quedan relativos a esa referencia común (en
                vez de ser un time.monotonic() absoluto sin relación con
                los otros archivos de la sesión) — así los tres registros
                de la sesión quedan en la MISMA escala de tiempo. None =
                comportamiento normal (guarda el monotonic absoluto, como
                al correr este módulo solo).
            fecha_hora: Sufijo de fecha/hora para el nombre del archivo.
                None = usa la hora actual.

        Returns:
            dict: timestamp_inicio, timestamp_fin, samplerate, device_used,
                duracion_real_seg, ruta_wav, ruta_json, participante_id, condicion.
        """
        timestamp_inicio = time.monotonic()
        ruta_wav = self.grabar(duracion_seg, participante_id, condicion, fecha_hora=fecha_hora)
        timestamp_fin = time.monotonic()

        if t0_externo is not None:
            timestamp_inicio -= t0_externo
            timestamp_fin -= t0_externo

        device_used = self.device_id if self.device_id is not None else sd.default.device[0]

        metadata = {
            "timestamp_inicio": round(timestamp_inicio, 3),
            "timestamp_fin": round(timestamp_fin, 3),
            "samplerate": self.samplerate,
            "device_used": device_used,
            "duracion_real_seg": round(timestamp_fin - timestamp_inicio, 3),
            "participante_id": participante_id,
            "condicion": condicion,
            "ruta_wav": str(ruta_wav),
        }

        ruta_json = ruta_wav.with_suffix(".json")
        with open(ruta_json, "w", encoding="utf-8") as archivo_json:
            json.dump(metadata, archivo_json, indent=2, ensure_ascii=False)

        metadata["ruta_json"] = str(ruta_json)
        return metadata

    @staticmethod
    def _mostrar_progreso(transcurrido: float, total: float) -> None:
        """Imprime una barra de progreso de una línea en la consola.

        Args:
            transcurrido: Segundos transcurridos de grabación.
            total: Duración total esperada, en segundos.
        """
        ancho_barra = 30
        progreso = min(transcurrido / total, 1.0)
        llenado = int(ancho_barra * progreso)
        barra = "#" * llenado + "-" * (ancho_barra - llenado)
        print(f"\r  [{barra}] {progreso * 100:5.1f}%  {transcurrido:4.1f}/{total:.1f}s", end="", flush=True)


if __name__ == "__main__":
    captura = CapturaAudio()  # dispositivo por defecto, 22050 Hz, mono

    print("=== Info del dispositivo de entrada ===")
    info = captura.get_dispositivo_info()
    for clave, valor in info.items():
        print(f"  {clave}: {valor}")

    print("\n=== Grabación de validación (20 segundos) ===")
    print("Protocolo: 0-3s aplauso, 3-10s respiración audible, 10-13s 'hola prueba', 13-20s respiración audible.")
    input("Presiona Enter para empezar a grabar.")

    metadata = captura.grabar_con_metadata(
        duracion_seg=20.0, participante_id="P01", condicion="validacion_respiracion"
    )

    print("\n=== Resumen ===")
    print(f"WAV guardado en: {metadata['ruta_wav']}")
    print(f"JSON de metadata en: {metadata['ruta_json']}")
    print(f"Duración real: {metadata['duracion_real_seg']}s")
    print(f"Samplerate: {metadata['samplerate']} Hz")
    print(f"Dispositivo usado: {metadata['device_used']}")
