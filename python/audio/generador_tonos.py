"""Generador de estímulos sonoros terapéuticos: Solfeggio, binaurales e isocrónicos.

Produce los archivos WAV base que se reproducen durante la sesión
experimental (ver unity_projects/ y python/sensor/capturar_sesion.py, que
etiqueta cada bloque con el nombre de estos estímulos).

Diferencia teórica entre binaural e isocrónico (ambos buscan "arrastrar"
las ondas cerebrales hacia una frecuencia objetivo, fenómeno conocido como
"brainwave entrainment", pero por mecanismos distintos):

- BINAURAL: se presentan dos tonos puros ligeramente distintos, uno por
  oído (ej. 200 Hz al izquierdo, 210 Hz al derecho). Ninguno de los dos
  tonos contiene realmente una onda de 10 Hz — esa frecuencia no existe en
  el aire ni en el archivo de audio de cada canal por separado. El "beat"
  de 10 Hz es una ILUSIÓN PERCEPTUAL: el complejo olivar superior del
  tronco encefálico, al recibir señales ligeramente desfasadas en cada
  oído, genera una señal neural oscilante a la frecuencia de la
  diferencia. Por eso el binaural EXIGE audífonos estéreo (si ambos tonos
  llegan a ambos oídos, como con parlantes, el efecto no ocurre).

- ISOCRÓNICO: un solo tono se enciende y apaga (modulación de amplitud en
  onda cuadrada) literalmente a la frecuencia objetivo (ej. 10 veces por
  segundo). Esa pulsación SÍ es una señal acústica real presente en el
  audio. La corteza auditiva la sigue de forma directa, sin necesitar
  procesar una diferencia interaural. Por eso funciona en mono, con un
  solo oído, o con parlantes — no requiere audífonos.

¿Por qué fade in/out de 0.5s? Un tono que empieza o termina de golpe a
volumen completo genera un "click" audible (un salto abrupto de amplitud
que el oído percibe como un chasquido) y puede resultar molesto o
sobresaltar al participante que lleva audífonos puestos. Una rampa lineal
de entrada/salida de 0.5s elimina ese salto y protege la experiencia del
participante.

¿Por qué int16 y no float32? WAV en int16 (PCM de 16 bits) es el formato
estándar de facto: lo reproduce cualquier software/hardware sin
conversión, tiene ~96 dB de rango dinámico (más que suficiente para
reproducir un tono terapéutico sin pérdida audible), y pesa la mitad que
guardar en float32 — relevante aquí porque se generan decenas de archivos
de 60 segundos cada uno.
"""

from pathlib import Path
from typing import Optional

import numpy as np
from scipy.io import wavfile
from scipy.signal import square

# Frecuencias Solfeggio tradicionales y su descripción asociada
SOLFEGGIO = [
    (174, "alivio_del_dolor"),
    (285, "regeneracion_celular"),
    (396, "liberacion_del_miedo"),
    (417, "cambio_positivo"),
    (528, "transformacion_y_milagros"),
    (639, "conexion_y_relaciones"),
    (741, "despertar_intuicion"),
    (852, "retorno_al_orden_espiritual"),
    (963, "activacion_glandula_pineal"),
]

# Beats binaurales por rango de onda cerebral: (rango, freq_base_hz, freq_diferencia_hz, descripcion)
BINAURALES = [
    ("delta", 200, 3, "sueno_profundo"),
    ("theta", 200, 6, "meditacion"),
    ("alpha", 200, 10, "relajacion_consciente"),
    ("beta", 200, 20, "concentracion"),
]

# Tonos isocrónicos para los mismos rangos: (rango, freq_portadora_hz, freq_pulso_hz)
ISOCRONICOS = [
    ("alpha", 200, 10),
    ("theta", 200, 6),
    ("delta", 200, 3),
]


class GeneradorTonos:
    """Genera archivos WAV de tonos Solfeggio, binaurales e isocrónicos.

    Attributes:
        samplerate (int): Frecuencia de muestreo de los WAV generados, en Hz.
        duracion_seg (int): Duración de cada estímulo, en segundos.
        amplitud (float): Amplitud pico de la señal (0-1), fija en 0.3 para no saturar.
    """

    def __init__(self, samplerate: int = 44100, duracion_seg: int = 60) -> None:
        """Inicializa el generador.

        Args:
            samplerate: Frecuencia de muestreo en Hz (default 44100, calidad CD,
                apropiada aquí porque es audio para REPRODUCIR, no para analizar
                — a diferencia de la grabación de respiración en 22050 Hz).
            duracion_seg: Duración de cada estímulo generado, en segundos.
        """
        self.samplerate = samplerate
        self.duracion_seg = duracion_seg
        self.amplitud = 0.3

    def _generar_tiempos(self) -> np.ndarray:
        """Vector de tiempos (s) para una señal de duracion_seg a este samplerate."""
        num_muestras = int(self.samplerate * self.duracion_seg)
        return np.linspace(0, self.duracion_seg, num_muestras, endpoint=False)

    def _aplicar_fade(self, señal: np.ndarray, duracion_fade_seg: float = 0.5) -> np.ndarray:
        """Aplica una rampa lineal de fade in/out a los extremos de la señal.

        Args:
            señal: Señal 1D a la que aplicar el fade.
            duracion_fade_seg: Duración del fade en cada extremo, en segundos.

        Returns:
            np.ndarray: Copia de la señal con fade in/out aplicado.
        """
        muestras_fade = int(duracion_fade_seg * self.samplerate)
        muestras_fade = min(muestras_fade, len(señal) // 2)  # protege señales muy cortas

        señal = señal.copy()
        señal[:muestras_fade] *= np.linspace(0, 1, muestras_fade)
        señal[-muestras_fade:] *= np.linspace(1, 0, muestras_fade)
        return señal

    def _guardar_wav(self, ruta_salida: Path, señal: np.ndarray) -> Path:
        """Convierte la señal float [-1, 1] a int16 y la guarda como WAV.

        Args:
            ruta_salida: Ruta destino del archivo .wav (se crean las carpetas padre).
            señal: Señal en float, mono (1D) o estéreo (2D, forma [muestras, 2]).

        Returns:
            Path: La misma ruta_salida, para encadenar llamadas.
        """
        ruta_salida = Path(ruta_salida)
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)

        # Recorte de seguridad por si algún tono se pasó de amplitud 1.0, luego
        # escalado a int16: rango WAV estándar de -32768 a 32767
        señal_recortada = np.clip(señal, -1.0, 1.0)
        señal_int16 = (señal_recortada * 32767).astype(np.int16)

        wavfile.write(str(ruta_salida), self.samplerate, señal_int16)
        return ruta_salida

    def generar_solfeggio(self, frecuencia_hz: float, ruta_salida: Path) -> Path:
        """Genera un tono puro sinusoidal a la frecuencia Solfeggio dada.

        Args:
            frecuencia_hz: Frecuencia del tono, en Hz (ej. 528 para "milagros").
            ruta_salida: Ruta donde guardar el WAV mono resultante.

        Returns:
            Path: ruta_salida.
        """
        tiempos = self._generar_tiempos()
        señal = self.amplitud * np.sin(2 * np.pi * frecuencia_hz * tiempos)
        señal = self._aplicar_fade(señal)

        return self._guardar_wav(ruta_salida, señal)

    def generar_binaural(
        self, freq_base_hz: float, freq_diferencia_hz: float, ruta_salida: Path
    ) -> Path:
        """Genera un beat binaural: un tono distinto por canal (ver docstring del módulo).

        Canal izquierdo a freq_base_hz, canal derecho a freq_base_hz +
        freq_diferencia_hz. El cerebro, al recibir ambos por separado (uno
        por oído, requiere audífonos), percibe una tercera frecuencia
        "fantasma" igual a freq_diferencia_hz.

        Args:
            freq_base_hz: Frecuencia portadora del canal izquierdo, en Hz.
            freq_diferencia_hz: Diferencia de frecuencia del canal derecho
                respecto al izquierdo, en Hz — es el "beat" que se percibe.
            ruta_salida: Ruta donde guardar el WAV estéreo resultante.

        Returns:
            Path: ruta_salida.
        """
        tiempos = self._generar_tiempos()

        canal_izquierdo = self.amplitud * np.sin(2 * np.pi * freq_base_hz * tiempos)
        canal_derecho = self.amplitud * np.sin(
            2 * np.pi * (freq_base_hz + freq_diferencia_hz) * tiempos
        )

        canal_izquierdo = self._aplicar_fade(canal_izquierdo)
        canal_derecho = self._aplicar_fade(canal_derecho)

        señal_estereo = np.column_stack([canal_izquierdo, canal_derecho])

        return self._guardar_wav(ruta_salida, señal_estereo)

    def generar_isocronico(
        self, frecuencia_portadora_hz: float, frecuencia_pulso_hz: float, ruta_salida: Path
    ) -> Path:
        """Genera un tono isocrónico: portadora pulsada en onda cuadrada (ver docstring del módulo).

        Args:
            frecuencia_portadora_hz: Frecuencia del tono base, en Hz.
            frecuencia_pulso_hz: Cuántas veces por segundo se enciende/apaga
                la portadora — es la frecuencia objetivo de entrainment.
            ruta_salida: Ruta donde guardar el WAV mono resultante.

        Returns:
            Path: ruta_salida.
        """
        tiempos = self._generar_tiempos()

        portadora = np.sin(2 * np.pi * frecuencia_portadora_hz * tiempos)
        # scipy.signal.square da una onda cuadrada en {-1, 1}; se reescala a {0, 1}
        # para que sea una envolvente de "encendido/apagado" (no invierte la fase)
        envolvente_pulso = (square(2 * np.pi * frecuencia_pulso_hz * tiempos) + 1) / 2

        señal = self.amplitud * portadora * envolvente_pulso
        señal = self._aplicar_fade(señal)

        return self._guardar_wav(ruta_salida, señal)

    def generar_biblioteca_completa(self, carpeta_destino: Path) -> list[Path]:
        """Genera todos los estímulos base de la tesis en sus subcarpetas correspondientes.

        Crea (si no existen) carpeta_destino/solfeggio/, /binaurales/ e
        /isocronicos/, y genera ahí los 9 Solfeggio + 4 binaurales + 3
        isocrónicos definidos como constantes del módulo (SOLFEGGIO,
        BINAURALES, ISOCRONICOS).

        Args:
            carpeta_destino: Carpeta raíz de audio_estimulos/.

        Returns:
            list[Path]: Rutas de todos los WAV generados.
        """
        carpeta_destino = Path(carpeta_destino)
        rutas_generadas: list[Path] = []

        carpeta_solfeggio = carpeta_destino / "solfeggio"
        for frecuencia_hz, descripcion in SOLFEGGIO:
            nombre_archivo = f"solfeggio_{frecuencia_hz:g}Hz_{descripcion}.wav"
            ruta = carpeta_solfeggio / nombre_archivo
            self.generar_solfeggio(frecuencia_hz, ruta)
            print(f"  Generado: {ruta.name}")
            rutas_generadas.append(ruta)

        carpeta_binaurales = carpeta_destino / "binaurales"
        for rango, freq_base_hz, freq_diferencia_hz, descripcion in BINAURALES:
            nombre_archivo = f"binaural_{freq_diferencia_hz:g}Hz_{rango}_{descripcion}.wav"
            ruta = carpeta_binaurales / nombre_archivo
            self.generar_binaural(freq_base_hz, freq_diferencia_hz, ruta)
            print(f"  Generado: {ruta.name}")
            rutas_generadas.append(ruta)

        carpeta_isocronicos = carpeta_destino / "isocronicos"
        for rango, freq_portadora_hz, freq_pulso_hz in ISOCRONICOS:
            nombre_archivo = f"isocronico_{freq_pulso_hz:g}Hz_{rango}.wav"
            ruta = carpeta_isocronicos / nombre_archivo
            self.generar_isocronico(freq_portadora_hz, freq_pulso_hz, ruta)
            print(f"  Generado: {ruta.name}")
            rutas_generadas.append(ruta)

        return rutas_generadas


if __name__ == "__main__":
    generador = GeneradorTonos(duracion_seg=60)
    carpeta_destino = Path(r"C:\Tesis_Kevin\audio_estimulos")

    print("=== Generando biblioteca completa de estímulos ===\n")
    rutas_generadas = generador.generar_biblioteca_completa(carpeta_destino)

    print("\n=== Archivos generados ===")
    tamano_total_bytes = 0
    for ruta in rutas_generadas:
        tamano_bytes = ruta.stat().st_size
        tamano_total_bytes += tamano_bytes
        print(f"  {ruta.relative_to(carpeta_destino)}  ({tamano_bytes / 1024:.1f} KB)")

    print(
        f"\nTotal: {len(rutas_generadas)} archivos, "
        f"{tamano_total_bytes / (1024 * 1024):.2f} MB en disco"
    )
