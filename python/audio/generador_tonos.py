"""Generador de estímulos sonoros terapéuticos: Solfeggio, binaurales, isocrónicos y paisajes biofílicos.

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
from scipy.signal import butter, sosfilt, square

# Frecuencias Solfeggio tradicionales y su descripción asociada. Se agrega
# 432 Hz (no es una de las 9 frecuencias "clásicas" de la escala, pero es la
# que el Estado del Arte de la tesis cita explícitamente junto con 528 Hz
# como receta de Saldırım & Şerbetçioğlu, 2025). Ya NO se usa en
# generar_biblioteca_completa() (ver Fase 2 en ese docstring: /solfeggio/
# genérico se retiró de la biblioteca real) — queda como referencia/datos
# para generar_solfeggio() puntual si hiciera falta.
SOLFEGGIO = [
    (174, "alivio_del_dolor"),
    (285, "regeneracion_celular"),
    (396, "liberacion_del_miedo"),
    (417, "cambio_positivo"),
    (432, "armonia_universal"),
    (528, "transformacion_y_milagros"),
    (639, "conexion_y_relaciones"),
    (741, "despertar_intuicion"),
    (852, "retorno_al_orden_espiritual"),
    (963, "activacion_glandula_pineal"),
]

# Beats binaurales por rango de onda cerebral: (rango, freq_base_hz, freq_diferencia_hz, descripcion)
# El rango "theta" usa base=429 Hz (no 200) para replicar EXACTAMENTE la
# receta citada en el Estado del Arte (Saldırım & Şerbetçioğlu, 2025a:
# 429 Hz oído izquierdo, 435 Hz oído derecho, beat percibido de 6 Hz). Los
# otros tres rangos no tienen una cita con portadora específica, así que
# mantienen la base 200 Hz original.
BINAURALES = [
    ("delta", 200, 3, "sueno_profundo"),
    ("theta", 429, 6, "meditacion"),
    ("alpha", 200, 10, "relajacion_consciente"),
    ("beta", 200, 20, "concentracion"),
]

# Tonos isocrónicos "genéricos" (portadora neutra 200 Hz) para los mismos
# rangos: (rango, freq_portadora_hz, freq_pulso_hz). Ya NO se usa en
# generar_biblioteca_completa() (ver Fase 2 ahí: /isocronicos/ genérico se
# retiró de la biblioteca real) — queda como referencia/datos para
# generar_isocronico() puntual si hiciera falta.
ISOCRONICOS = [
    ("alpha", 200, 10),
    ("theta", 200, 6),
    ("delta", 200, 3),
]

# Combinación Solfeggio + isocrónico: la MISMA frecuencia Solfeggio citada en
# el Estado del Arte, pulsada isocrónicamente en Theta (6 Hz, rango de
# relajación/meditación). Es lo que el texto agrupa como "Frecuencias
# Solfeggio y Tonos Isocrónicos" — un solo estímulo que combina ambas
# técnicas en vez de tratarlas como dos tipos separados.
SOLFEGGIO_ISOCRONICO = [
    (432, 6, "armonia_universal_theta"),
    (528, 6, "transformacion_theta"),
]


class GeneradorTonos:
    """Genera archivos WAV de tonos Solfeggio, binaurales e isocrónicos.

    Attributes:
        samplerate (int): Frecuencia de muestreo de los WAV generados, en Hz.
        duracion_seg (int): Duración de cada estímulo, en segundos.
        amplitud (float): Amplitud pico de la señal (0-1), fija en 0.3 para no saturar.
    """

    def __init__(self, samplerate: int = 44100, duracion_seg: int = 300) -> None:
        """Inicializa el generador.

        Args:
            samplerate: Frecuencia de muestreo en Hz (default 44100, calidad CD,
                apropiada aquí porque es audio para REPRODUCIR, no para analizar
                — a diferencia de la grabación de respiración en 22050 Hz).
            duracion_seg: Duración de cada estímulo generado, en segundos.
                Default 300 (5 minutos): es la ventana que el Estado del Arte
                exige para que RMSSD/SDNN sean confiables (Task Force ESC/NASPE
                1996, mínimo 3-5 min) y que Jin et al. (2026) y Liu & Li (2026)
                validaron como duración óptima de inmersión sin fatiga.
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

    def generar_solfeggio_isocronico(
        self, frecuencia_solfeggio_hz: float, frecuencia_pulso_hz: float, ruta_salida: Path
    ) -> Path:
        """Genera un tono Solfeggio pulsado isocrónicamente (portadora + pulso).

        Combina en un solo estímulo las dos técnicas que el Estado del Arte
        agrupa bajo "Frecuencias Solfeggio y Tonos Isocrónicos": la
        portadora es una frecuencia Solfeggio citada en el texto (432 o
        528 Hz) y esa portadora se pulsa en onda cuadrada a la frecuencia
        de entrainment objetivo — mecánicamente es exactamente
        generar_isocronico() con una portadora Solfeggio en vez de la
        portadora neutra (200 Hz) de ISOCRONICOS.

        Args:
            frecuencia_solfeggio_hz: Frecuencia Solfeggio portadora, en Hz.
            frecuencia_pulso_hz: Frecuencia de pulso (encendido/apagado), en Hz.
            ruta_salida: Ruta donde guardar el WAV mono resultante.

        Returns:
            Path: ruta_salida.
        """
        return self.generar_isocronico(frecuencia_solfeggio_hz, frecuencia_pulso_hz, ruta_salida)

    def generar_paisaje_biofilico(self, ruta_salida: Path, semilla: Optional[int] = None) -> Path:
        """Genera un paisaje sonoro biofílico sintético (agua, brisa y aves).

        A diferencia de los estímulos anteriores (señales deterministas de
        frecuencia fija), este se sintetiza por capas de ruido filtrado más
        eventos aleatorios, aproximando en espíritu los paisajes sonoros
        naturales documentados en el Estado del Arte (agua en movimiento,
        brisa y cantos de aves; Jin et al., 2026; Kawai et al., 2025; Long
        et al., 2023, 2024) sin depender de grabaciones de campo con
        licencia incierta. Es una aproximación sintética, no una
        recreación fiel de una grabación real — lo declarado así en el
        Marco Teórico/Conceptual.

        Capas:
            - Agua: ruido blanco filtrado en banda (200-2000 Hz) con
              modulación lenta de amplitud, simulando el fluir irregular.
            - Brisa: ruido filtrado paso-bajo (<500 Hz) con modulación
              lenta, simulando ráfagas de viento.
            - Aves: barridos de frecuencia (chirps) breves en el rango
              2-4.5 kHz, espaciados de forma irregular en el tiempo.

        Args:
            ruta_salida: Ruta donde guardar el WAV estéreo resultante.
            semilla: Semilla del generador aleatorio, para reproducibilidad
                (ej. documentar en la tesis con qué semilla se generó el
                estímulo usado). None = resultado distinto en cada llamada.

        Returns:
            Path: ruta_salida.
        """
        rng = np.random.default_rng(semilla)
        tiempos = self._generar_tiempos()
        num_muestras = len(tiempos)

        # --- Agua: ruido filtrado en banda + modulación lenta de amplitud ---
        ruido_agua = rng.normal(0, 1, num_muestras)
        sos_agua = butter(4, [200, 2000], btype="band", fs=self.samplerate, output="sos")
        agua = sosfilt(sos_agua, ruido_agua)
        agua = agua / (np.max(np.abs(agua)) + 1e-9)
        modulacion_agua = 0.7 + 0.3 * np.sin(2 * np.pi * 0.15 * tiempos + rng.uniform(0, 2 * np.pi))
        agua *= modulacion_agua

        # --- Brisa: ruido paso-bajo + modulación lenta de amplitud ---
        ruido_brisa = rng.normal(0, 1, num_muestras)
        sos_brisa = butter(4, 500, btype="low", fs=self.samplerate, output="sos")
        brisa = sosfilt(sos_brisa, ruido_brisa)
        brisa = brisa / (np.max(np.abs(brisa)) + 1e-9)
        modulacion_brisa = 0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * tiempos + rng.uniform(0, 2 * np.pi))
        brisa *= modulacion_brisa

        # --- Aves: chirps breves, espaciados de forma irregular ---
        aves = np.zeros(num_muestras)
        t_actual = rng.uniform(1.0, 4.0)
        while t_actual < self.duracion_seg - 0.5:
            duracion_chirp = rng.uniform(0.08, 0.2)
            n_muestras_chirp = int(duracion_chirp * self.samplerate)
            t_chirp = np.linspace(0, duracion_chirp, n_muestras_chirp, endpoint=False)
            f_inicio = rng.uniform(2000, 3000)
            f_fin = rng.uniform(3500, 4500)
            # Barrido de frecuencia lineal: fase = 2*pi*(f0*t + (f1-f0)*t^2/(2*T))
            fase = 2 * np.pi * (
                f_inicio * t_chirp + (f_fin - f_inicio) * t_chirp**2 / (2 * duracion_chirp)
            )
            chirp = np.sin(fase) * np.sin(np.pi * np.linspace(0, 1, n_muestras_chirp))  # envolvente en arco

            inicio_muestra = int(t_actual * self.samplerate)
            fin_muestra = inicio_muestra + n_muestras_chirp
            if fin_muestra <= num_muestras:
                aves[inicio_muestra:fin_muestra] += chirp * rng.uniform(0.5, 1.0)

            t_actual += rng.uniform(2.5, 7.0)

        # --- Mezcla de capas y normalización ---
        señal = 0.5 * agua + 0.35 * brisa + 0.4 * aves
        señal = señal / (np.max(np.abs(señal)) + 1e-9)
        señal = self.amplitud * señal
        # Fade más largo que en los tonos puros (2s en vez de 0.5s): un
        # paisaje ambiental que entra/sale de golpe rompe la sensación de
        # continuidad natural que se busca en este estímulo específicamente.
        señal = self._aplicar_fade(señal, duracion_fade_seg=2.0)

        señal_estereo = np.column_stack([señal, señal])
        return self._guardar_wav(ruta_salida, señal_estereo)

    def generar_biblioteca_completa(self, carpeta_destino: Path) -> list[Path]:
        """Genera todos los estímulos OFICIALES del protocolo de la tesis en sus
        subcarpetas correspondientes.

        Crea (si no existen) carpeta_destino/binaurales/, /solfeggio_isocronico/
        y /paisajes/, y genera ahí los 4 binaurales + 2 Solfeggio-isocrónico + 1
        paisaje biofílico definidos como constantes/métodos del módulo
        (BINAURALES, SOLFEGGIO_ISOCRONICO, generar_paisaje_biofilico()).

        Los 3 tipos que realmente entran al sorteo del protocolo de la tesis
        (Día 1/Día 3, ver TIPOS_ESTANDARIZADOS en sesion_completa.py) son
        binaural/theta (429/435 Hz), solfeggio_isocronico y paisajes.

        RETIRADO (limpieza de Fase 2): antes esto también generaba /solfeggio/
        e /isocronicos/ "genéricos" — WAV de referencia que NUNCA formaron
        parte del protocolo oficial de 3 días (el sorteo solo elige entre los 3
        tipos de arriba) y que solo usaba el protocolo de ejemplo viejo
        (construir_protocolo_ejemplo() con la biblioteca real, ya retirado de
        ejecutar_sesion_completa() — ver ese docstring). Se sacaron para no
        seguir regenerando carpetas que ningún protocolo real vuelve a leer.
        GeneradorTonos.generar_solfeggio()/generar_isocronico() (los MÉTODOS)
        siguen existiendo tal cual: protocolo_corto=True en
        ejecutar_sesion_completa() todavía los llama, pero apuntando a una
        carpeta TEMPORAL propia (ver ese código), nunca a audio_estimulos/.

        Args:
            carpeta_destino: Carpeta raíz de audio_estimulos/.

        Returns:
            list[Path]: Rutas de todos los WAV generados.
        """
        carpeta_destino = Path(carpeta_destino)
        rutas_generadas: list[Path] = []

        carpeta_binaurales = carpeta_destino / "binaurales"
        for rango, freq_base_hz, freq_diferencia_hz, descripcion in BINAURALES:
            nombre_archivo = f"binaural_{freq_diferencia_hz:g}Hz_{rango}_{descripcion}.wav"
            ruta = carpeta_binaurales / nombre_archivo
            self.generar_binaural(freq_base_hz, freq_diferencia_hz, ruta)
            print(f"  Generado: {ruta.name}")
            rutas_generadas.append(ruta)

        carpeta_solfeggio_isocronico = carpeta_destino / "solfeggio_isocronico"
        for frecuencia_solfeggio_hz, freq_pulso_hz, descripcion in SOLFEGGIO_ISOCRONICO:
            nombre_archivo = f"solfeggio_isocronico_{frecuencia_solfeggio_hz:g}Hz_{descripcion}.wav"
            ruta = carpeta_solfeggio_isocronico / nombre_archivo
            self.generar_solfeggio_isocronico(frecuencia_solfeggio_hz, freq_pulso_hz, ruta)
            print(f"  Generado: {ruta.name}")
            rutas_generadas.append(ruta)

        carpeta_paisajes = carpeta_destino / "paisajes"
        ruta_paisaje = carpeta_paisajes / "paisaje_biofilico_agua_brisa_aves.wav"
        self.generar_paisaje_biofilico(ruta_paisaje, semilla=42)
        print(f"  Generado: {ruta_paisaje.name}")
        rutas_generadas.append(ruta_paisaje)

        return rutas_generadas


if __name__ == "__main__":
    generador = GeneradorTonos()  # duracion_seg=300 (5 min) por default
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
