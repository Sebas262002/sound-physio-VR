"""Detección de respiraciones a partir de un WAV grabado con capturar_respiracion.py.

Estrategia general: la respiración no se detecta buscando un tono
específico, sino midiendo cuándo hay más "energía" (más actividad sonora)
en la grabación — cada inhalación/exhalación produce un incremento de
energía acústica por la turbulencia del aire, seguido de un silencio
relativo entre respiraciones. Por eso el pipeline es:

    audio crudo → envolvente de energía RMS → detección de picos de esa
    envolvente → cada pico = una respiración.

RMS (Root Mean Square) es la métrica estándar de "energía" de una señal de
audio: eleva al cuadrado cada muestra (para que amplitudes negativas y
positivas sumen, no se cancelen), promedia, y saca raíz para volver a la
escala original de amplitud. Un tramo de audio con más actividad (más
turbulencia de aire pasando por la garganta/nariz) tiene mayor RMS que un
tramo de silencio o respiración muy suave.

Rangos de referencia de frecuencia respiratoria en adultos (literatura
clínica): 12-20 respiraciones/min en reposo normal, 6-10 respiraciones/min
en estados de relajación profunda / meditación.

CONFIGURACIÓN VALIDADA CON EL MICRÓFONO F15-2 WIRELESS (16/08/2026):
Con el mic debajo de la clavícula, la respiración quedaba indistinguible
del piso de ruido (relación señal/ruido < 1) — no era un problema de
parámetros de este módulo, sino de posición/ganancia de grabación (ver
capturar_respiracion.py). Se validó experimentalmente que la siguiente
combinación SÍ separa la respiración del ruido de fondo:

    - Posición del micrófono: CERCA DEL CUELLO (no debajo de la clavícula).
    - Ganancia de entrada de Windows ("mic boost") al máximo disponible
      para el dispositivo.
    - Parámetros de análisis: altura_relativa=0.15, amplificar_senal=2.5,
      aplicar_filtro_pasa_banda=True (los defaults de analizar(), sin
      necesidad de ajustarlos más).

Con esa combinación, una grabación de validación (aplauso + respiración +
voz) dio: piso de ruido RMS≈0.000015, respiración RMS≈0.000111 promedio
(hasta 0.000361 en los picos) — una relación señal/ruido de ~7-24×, muy
por encima del mínimo de 3× necesario para que find_peaks() distinga
respiración real de ruido de forma confiable. Dato curioso encontrado en
esa misma validación: con el mic tan cerca del cuello, la VOZ generó una
señal ~5× más fuerte que un aplauso a distancia de brazo (la garganta
transmite la voz casi directamente al mic) — si se necesita distinguir
respiración de habla en una sesión real, conviene tenerlo en cuenta (la
voz podría dominar la envolvente si el participante habla).
"""

from pathlib import Path
from typing import Optional, Union

import librosa
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

CARPETA_AUDIO = Path(r"C:\Tesis_Kevin\datos\sesiones\audio")
CARPETA_GRAFICAS = Path(r"C:\Tesis_Kevin\resultados\graficas")


class DetectorRespiracion:
    """Detecta respiraciones individuales en una grabación de audio.

    Attributes:
        ruta_wav (Path): Ruta al archivo WAV a analizar.
        audio (np.ndarray): Señal de audio cargada (mono, 1D). Si se llamó
            a filtrar_pasa_banda(), esta es la versión FILTRADA.
        audio_crudo (np.ndarray): Copia de la señal tal como se cargó,
            antes de cualquier filtrado (None si nunca se filtró).
        sr (int): Frecuencia de muestreo del audio, en Hz.
        duracion_seg (float): Duración total del audio, en segundos.
        envolvente (np.ndarray): Última envolvente RMS calculada.
        tiempos_envolvente (np.ndarray): Tiempos (s) de cada punto de la envolvente.
        ventana_ms (int): Tamaño de ventana usado para la última envolvente.
    """

    def __init__(self, ruta_wav: Union[str, Path]) -> None:
        """Inicializa el detector a partir de la ruta del WAV.

        Args:
            ruta_wav: Ruta al archivo .wav grabado por CapturaAudio.
        """
        self.ruta_wav = Path(ruta_wav)
        self.audio: Optional[np.ndarray] = None
        self.audio_crudo: Optional[np.ndarray] = None
        self.sr: Optional[int] = None
        self.duracion_seg: Optional[float] = None
        self.envolvente: Optional[np.ndarray] = None
        self.tiempos_envolvente: Optional[np.ndarray] = None
        self.ventana_ms: Optional[int] = None

    def cargar(self) -> np.ndarray:
        """Carga el audio con librosa, manteniendo su samplerate original.

        sr=None le indica a librosa que NO remuestree el audio (por
        default, librosa.load remuestrea a 22050 Hz); así se respeta
        exactamente el samplerate con el que se grabó la sesión.

        Returns:
            np.ndarray: Señal de audio mono, 1D.

        Raises:
            FileNotFoundError: Si ruta_wav no existe.
        """
        if not self.ruta_wav.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {self.ruta_wav}")

        self.audio, self.sr = librosa.load(self.ruta_wav, sr=None, mono=True)
        self.duracion_seg = len(self.audio) / self.sr

        return self.audio

    def calcular_envolvente(
        self, ventana_ms: int = 100, amplificar_senal: float = 1.0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Calcula la envolvente de energía RMS del audio, por ventanas de tiempo fijo.

        Divide el audio en ventanas no solapadas de ventana_ms milisegundos
        y calcula, para cada una:

            rms_ventana = sqrt(mean(audio_ventana ** 2))

        (vectorizado con reshape + np.mean(axis=1), equivalente a calcularlo
        ventana por ventana en un loop, pero mucho más rápido en numpy).

        Una ventana de 100 ms es un buen balance para respiración: lo
        bastante corta para no promediar dos respiraciones distintas en un
        mismo punto, y lo bastante larga para suavizar el ruido de alta
        frecuencia de cada muestra individual de audio.

        Args:
            ventana_ms: Tamaño de cada ventana de análisis, en milisegundos.
            amplificar_senal: Factor multiplicativo aplicado a la señal
                ANTES de calcular el RMS (default 1.0 = sin cambios).
                Justificación de amplificar por software vs. cambiar el
                hardware: con un micrófono ya instalado y una grabación ya
                hecha (ej. sesiones ya capturadas con el F15-2 wireless),
                no se puede "subir la ganancia" retroactivamente — pero si
                la señal es débil de forma CONSISTENTE (no hay saturación
                ni clipping), multiplicarla amplifica por igual la señal
                real y su ruido de fondo, preservando la relación
                señal/ruido; lo que cambia es que ahora las respiraciones
                suaves (que antes quedaban por debajo de cualquier umbral
                razonable) se despliegan en un rango de RMS donde
                altura_relativa o el umbral adaptativo sí las puede
                distinguir del silencio. No "inventa" información nueva:
                solo hace visible, para el detector de picos, un contraste
                que ya estaba en la señal pero era demasiado pequeño en
                magnitud absoluta.

        Returns:
            tuple[np.ndarray, np.ndarray]: (envolvente, tiempos), donde
                tiempos[i] es el instante (s) del centro de la ventana i.
        """
        audio_para_analizar = self.audio
        if amplificar_senal != 1.0:
            # np.clip evita "saturación" tras amplificar: sin este recorte, valores que
            # superen el rango normalizado de audio [-1, 1] no representarían amplitud
            # real, e inflarían artificialmente el RMS de los tramos ya fuertes (los que
            # de por sí se detectaban bien) sin mejorar el contraste de los suaves
            audio_para_analizar = np.clip(self.audio * amplificar_senal, -1.0, 1.0)

        muestras_por_ventana = max(1, int(self.sr * ventana_ms / 1000))
        num_ventanas = len(audio_para_analizar) // muestras_por_ventana

        # Se recorta el audio a un múltiplo exacto de muestras_por_ventana para poder
        # reorganizarlo en una matriz (num_ventanas x muestras_por_ventana) y vectorizar el RMS
        audio_recortado = audio_para_analizar[: num_ventanas * muestras_por_ventana]
        matriz_ventanas = audio_recortado.reshape(num_ventanas, muestras_por_ventana)

        envolvente = np.sqrt(np.mean(matriz_ventanas**2, axis=1))
        tiempos = (np.arange(num_ventanas) + 0.5) * muestras_por_ventana / self.sr

        self.envolvente = envolvente
        self.tiempos_envolvente = tiempos
        self.ventana_ms = ventana_ms

        return envolvente, tiempos

    def _picos_desde_umbral(self, altura_minima: float, distancia_min_seg: float) -> dict:
        """Lógica común de detección de picos, dado un umbral ya calculado.

        Compartida por detectar_picos() (umbral relativo al máximo) y
        detectar_picos_adaptativo() (umbral anclado al piso de ruido) —
        ambos solo difieren en CÓMO calculan altura_minima, no en qué
        hacen con ella.

        Args:
            altura_minima: Umbral de RMS que debe superar un punto de la
                envolvente para contar como respiración.
            distancia_min_seg: Separación mínima entre picos consecutivos,
                en segundos. Se usa 1.5s por defecto porque fisiológicamente
                nadie respira más de ~40 veces por minuto incluso
                hiperventilando (40 resp/min = 1 cada 1.5s); exigir esa
                distancia mínima evita que un solo ciclo respiratorio
                "ruidoso" se cuente como dos.

        Returns:
            dict: indices_picos, tiempos_picos, numero_respiraciones,
                frecuencia_respiratoria_bpm, intervalos_entre_respiraciones
                (s), variabilidad_respiratoria_ms, altura_minima.
        """
        # La envolvente tiene un punto cada ventana_ms; convertimos la distancia
        # mínima en segundos a "muestras de envolvente" (no muestras de audio)
        muestras_envolvente_por_seg = 1000 / self.ventana_ms
        distancia_muestras = max(1, int(round(distancia_min_seg * muestras_envolvente_por_seg)))

        indices_picos, _ = find_peaks(
            self.envolvente, height=altura_minima, distance=distancia_muestras
        )
        tiempos_picos = self.tiempos_envolvente[indices_picos]
        numero_respiraciones = len(indices_picos)

        intervalos = np.diff(tiempos_picos)  # segundos entre respiraciones consecutivas

        if numero_respiraciones >= 2:
            frecuencia_respiratoria_bpm = 60.0 / intervalos.mean()
            # Análogo respiratorio de la variabilidad de HRV (ver analizar_sesion.py):
            # qué tan regular o irregular es el ritmo respiratorio, en ms
            variabilidad_respiratoria_ms = np.std(intervalos, ddof=1) * 1000
        else:
            frecuencia_respiratoria_bpm = np.nan
            variabilidad_respiratoria_ms = np.nan

        return {
            "indices_picos": indices_picos,
            "tiempos_picos": tiempos_picos,
            "numero_respiraciones": numero_respiraciones,
            "frecuencia_respiratoria_bpm": frecuencia_respiratoria_bpm,
            "intervalos_entre_respiraciones": intervalos,
            "variabilidad_respiratoria_ms": variabilidad_respiratoria_ms,
            "altura_minima": altura_minima,  # se guarda para poder graficar el umbral
        }

    def detectar_picos(
        self, altura_relativa: float = 0.15, distancia_min_seg: float = 1.5
    ) -> dict:
        """Detecta picos de la envolvente RMS: cada pico = una respiración.

        Args:
            altura_relativa: Fracción del pico máximo de la envolvente que
                debe superar un punto para considerarse respiración (0-1).
                Default 0.15 (bajado desde 0.3): con micrófonos de
                sensibilidad limitada (ej. F15-2 wireless), las
                respiraciones suaves —justo las de interés en estados de
                relajación profunda— generan picos de RMS mucho más bajos
                que una respiración fuerte; un umbral del 30% del máximo
                las descarta directamente. 0.15 es más sensible, a costa
                de aceptar más riesgo de falsos positivos por ruido —
                para grabaciones con ruido de fondo variable, usar mejor
                detectar_picos_adaptativo().
                Se usa un umbral RELATIVO (no un valor RMS absoluto en
                unidades fijas) porque el volumen de grabación varía mucho
                según la distancia del micrófono lavalier a la boca/nariz
                de cada participante y la ganancia del dispositivo; un
                umbral relativo al máximo de CADA sesión se adapta
                automáticamente sin necesitar calibración manual por persona.
            distancia_min_seg: Separación mínima entre picos consecutivos,
                en segundos (ver _picos_desde_umbral()).

        Returns:
            dict: indices_picos, tiempos_picos, numero_respiraciones,
                frecuencia_respiratoria_bpm, intervalos_entre_respiraciones
                (s), variabilidad_respiratoria_ms.
        """
        if self.envolvente is None:
            self.calcular_envolvente()

        altura_minima = altura_relativa * self.envolvente.max()
        return self._picos_desde_umbral(altura_minima, distancia_min_seg)

    def detectar_picos_adaptativo(self, factor: float = 0.2, distancia_min_seg: float = 1.5) -> dict:
        """Detecta picos con un umbral ADAPTATIVO anclado al piso de ruido de la grabación.

        ¿Por qué es mejor que el umbral relativo simple (detectar_picos())
        cuando el micrófono tiene ruido de fondo variable? detectar_picos()
        fija el umbral como una fracción del MÁXIMO de la envolvente (ej.
        15-30% del pico más alto). Eso asume que el "piso" (silencio entre
        respiraciones) está cerca de cero — razonable con poco ruido de
        fondo, pero no con un micrófono de sensibilidad limitada como el
        F15-2 wireless, donde el ruido ambiente puede tener una energía
        RMS considerable y VARIABLE. Con un umbral relativo al máximo, ese
        ruido puede:
          - quedar por ENCIMA del umbral en tramos ruidosos (falsos
            positivos: se detecta "respiración" donde solo hay ruido), o
          - obligar a subir tanto el umbral que las respiraciones suaves
            reales, en tramos más silenciosos, queden por DEBAJO (falsos
            negativos).

        El umbral adaptativo, en cambio, se ancla al PISO DE RUIDO real de
        ESTA grabación (percentil 20 de la envolvente — se usa percentil,
        no el mínimo absoluto, porque el mínimo podría ser un silencio
        atípicamente profundo y no representativo) y sube solo una
        fracción (factor) de la distancia hasta el máximo:

            umbral = piso_ruido + factor * (máximo - piso_ruido)

        Esto separa mejor "actividad respiratoria real" de "ruido de
        fondo" incluso cuando ese ruido de fondo no es despreciable ni
        constante, porque el umbral se recalcula a partir de dónde está
        REALMENTE el silencio en esta grabación específica, no de una
        fracción arbitraria del pico más alto.

        Args:
            factor: Fracción de la distancia entre el piso de ruido y el
                máximo que debe superar un punto para considerarse
                respiración (default 0.2 = 20% por encima del piso).
            distancia_min_seg: Separación mínima entre picos consecutivos,
                en segundos (ver _picos_desde_umbral()).

        Returns:
            dict: mismo formato que detectar_picos(), más "piso_ruido"
                (el percentil 20 de la envolvente usado como referencia).
        """
        if self.envolvente is None:
            self.calcular_envolvente()

        piso_ruido = np.percentile(self.envolvente, 20)
        maximo = self.envolvente.max()
        altura_minima = piso_ruido + factor * (maximo - piso_ruido)

        resultado = self._picos_desde_umbral(altura_minima, distancia_min_seg)
        resultado["piso_ruido"] = piso_ruido
        return resultado

    def filtrar_pasa_banda(
        self, freq_min: float = 100, freq_max: float = 2000, orden: int = 4
    ) -> np.ndarray:
        """Filtra self.audio con un pasa-banda Butterworth (deja solo freq_min-freq_max Hz).

        Rango de frecuencias típicas de la respiración humana: la energía
        acústica de la turbulencia del aire al respirar se concentra
        aproximadamente entre 100 Hz y 2000 Hz. Por fuera de ese rango hay
        sobre todo RUIDO, no información respiratoria:
          - Por debajo de 100 Hz ("rumble"): vibraciones de manejo del
            micrófono, zumbido eléctrico de la red (50/60 Hz), ruido
            ambiental grave (tráfico, HVAC).
          - Por encima de 2000 Hz (siseo/hiss): ruido electrónico propio
            del micrófono, sibilancias no respiratorias.

        ¿Por qué mejora la detección? Al eliminar ambos extremos, la
        energía RMS que queda en la envolvente representa más fielmente la
        respiración real — mejora el contraste entre "respiración suave" y
        "ruido de fondo", que es justo lo que necesitan tanto
        altura_relativa (un pico relativo más limpio) como el umbral
        adaptativo (un piso de ruido más bajo y estable).

        Se usa un filtro Butterworth (scipy.signal.butter) por su
        respuesta plana dentro de la banda de paso (no distorsiona las
        amplitudes relativas entre respiraciones dentro del rango de
        interés), aplicado con filtfilt (filtra hacia adelante Y hacia
        atrás) para que el resultado no quede desfasado en el tiempo
        respecto al original — importante porque después se usan los
        TIEMPOS de los picos detectados para calcular la frecuencia
        respiratoria.

        Args:
            freq_min: Frecuencia de corte inferior, en Hz (default 100).
            freq_max: Frecuencia de corte superior, en Hz (default 2000).
            orden: Orden del filtro Butterworth (default 4; más alto =
                transición más abrupta entre bandas, pero más riesgo de
                artefactos en los bordes de la señal).

        Returns:
            np.ndarray: La señal filtrada (también queda guardada en self.audio).

        Raises:
            RuntimeError: Si aún no se llamó a cargar().
        """
        if self.audio is None:
            raise RuntimeError("Llama a cargar() antes de filtrar_pasa_banda().")

        nyquist = self.sr / 2
        # Nyquist es la frecuencia máxima representable a este samplerate; si freq_max
        # la supera (ej. un WAV grabado a un sr bajo), se recorta para no romper butter()
        freq_max_valida = min(freq_max, nyquist * 0.99)

        b, a = butter(orden, [freq_min / nyquist, freq_max_valida / nyquist], btype="band")

        if self.audio_crudo is None:
            self.audio_crudo = self.audio.copy()  # conserva el original sin filtrar

        self.audio = filtfilt(b, a, self.audio_crudo)

        # El filtrado cambia la señal de la que depende todo lo demás: se invalida
        # cualquier envolvente ya calculada, para forzar a recalcularla con el audio filtrado
        self.envolvente = None
        self.tiempos_envolvente = None

        return self.audio

    def analizar(
        self,
        altura_relativa: float = 0.15,
        amplificar_senal: float = 2.5,
        aplicar_filtro_pasa_banda: bool = True,
    ) -> dict:
        """Ejecuta el pipeline completo y arma un resumen interpretado.

        Los defaults (altura_relativa=0.15, amplificar_senal=2.5,
        aplicar_filtro_pasa_banda=True) están calibrados para micrófonos
        de sensibilidad limitada grabando respiraciones suaves (ej. F15-2
        wireless, ver detectar_picos() y calcular_envolvente() para el
        detalle de cada parámetro) — más sensibles que los defaults
        "genéricos" de los métodos individuales.

        Args:
            altura_relativa: Ver detectar_picos().
            amplificar_senal: Ver calcular_envolvente().
            aplicar_filtro_pasa_banda: Si True, llama filtrar_pasa_banda()
                (con sus valores default, 100-2000 Hz) antes de calcular
                la envolvente.

        Returns:
            dict: duracion_analizada_seg, numero_respiraciones,
                frecuencia_respiratoria_bpm, intervalo_medio_seg,
                variabilidad_respiratoria_seg, interpretacion.
        """
        if aplicar_filtro_pasa_banda:
            self.filtrar_pasa_banda()

        self.calcular_envolvente(amplificar_senal=amplificar_senal)
        resultado = self.detectar_picos(altura_relativa=altura_relativa)
        bpm = resultado["frecuencia_respiratoria_bpm"]
        intervalos = resultado["intervalos_entre_respiraciones"]

        if resultado["numero_respiraciones"] < 2:
            interpretacion = (
                "No se detectaron suficientes respiraciones para estimar la frecuencia "
                "(revisar volumen de grabación o altura_relativa)"
            )
            intervalo_medio_seg = np.nan
            variabilidad_respiratoria_seg = np.nan
        else:
            intervalo_medio_seg = intervalos.mean()
            variabilidad_respiratoria_seg = resultado["variabilidad_respiratoria_ms"] / 1000
            # Umbrales de interpretación pedidos para la tesis; los rangos de referencia
            # clínica completos (12-20 reposo, 6-10 relajación profunda) están documentados
            # en el docstring del módulo
            if bpm < 8:
                interpretacion = "Respiración muy lenta (posible relajación profunda)"
            elif bpm <= 16:
                interpretacion = "Respiración normal en reposo"
            else:
                interpretacion = "Respiración acelerada (posible activación)"

        return {
            "duracion_analizada_seg": round(self.duracion_seg, 1),
            "numero_respiraciones": resultado["numero_respiraciones"],
            "frecuencia_respiratoria_bpm": round(bpm, 2) if not np.isnan(bpm) else np.nan,
            "intervalo_medio_seg": (
                round(intervalo_medio_seg, 2) if not np.isnan(intervalo_medio_seg) else np.nan
            ),
            "variabilidad_respiratoria_seg": (
                round(variabilidad_respiratoria_seg, 3)
                if not np.isnan(variabilidad_respiratoria_seg)
                else np.nan
            ),
            "interpretacion": interpretacion,
        }

    def graficar(
        self,
        guardar_en: Optional[Union[str, Path]] = None,
        altura_relativa: float = 0.15,
        amplificar_senal: float = 1.0,
        aplicar_filtro_pasa_banda: bool = False,
    ) -> plt.Figure:
        """Genera una figura de 3 subplots resumiendo la detección de respiraciones.

        Subplots:
            1. Waveform del audio (cruda, o filtrada si aplicar_filtro_pasa_banda=True).
            2. Envolvente RMS, con los picos detectados marcados en rojo y
               una línea horizontal en el umbral usado.
            3. Histograma de los intervalos entre respiraciones consecutivas.

        Args:
            guardar_en: Si se indica (nombre de archivo o ruta), guarda la
                figura como PNG a 300 DPI. Si es un nombre relativo, se
                guarda dentro de la carpeta oficial de resultados
                (C:\\Tesis_Kevin\\resultados\\graficas\\). La figura siempre
                se muestra con plt.show() además de guardarse.
            altura_relativa: Ver detectar_picos(). Se recalcula la
                envolvente/picos con este valor (no reutiliza un análisis
                previo), para poder generar gráficas "antes/después"
                comparables cambiando solo estos argumentos.
            amplificar_senal: Ver calcular_envolvente().
            aplicar_filtro_pasa_banda: Ver filtrar_pasa_banda(); si True,
                se aplica (con sus valores default) antes de graficar.

        Returns:
            plt.Figure: La figura generada.
        """
        if aplicar_filtro_pasa_banda:
            self.filtrar_pasa_banda()
        self.calcular_envolvente(amplificar_senal=amplificar_senal)
        resultado = self.detectar_picos(altura_relativa=altura_relativa)
        tiempos_audio = np.arange(len(self.audio)) / self.sr

        fig, (ax_wave, ax_env, ax_hist) = plt.subplots(3, 1, figsize=(12, 10))

        # --- Subplot 1: waveform (cruda o filtrada, según aplicar_filtro_pasa_banda) ---
        ax_wave.plot(tiempos_audio, self.audio, color="steelblue", linewidth=0.4)
        titulo_waveform = (
            "Señal de audio (pasa-banda 100-2000 Hz)" if aplicar_filtro_pasa_banda else "Señal de audio (waveform)"
        )
        ax_wave.set_title(titulo_waveform)
        ax_wave.set_xlabel("Tiempo (s)")
        ax_wave.set_ylabel("Amplitud")

        # --- Subplot 2: envolvente RMS + picos + umbral ---
        ax_env.plot(self.tiempos_envolvente, self.envolvente, color="darkorange", label="Envolvente RMS")
        ax_env.scatter(
            resultado["tiempos_picos"],
            self.envolvente[resultado["indices_picos"]],
            color="red",
            zorder=3,
            label="Respiración detectada",
        )
        ax_env.axhline(
            resultado["altura_minima"], color="gray", linestyle="--", label="Umbral (altura_relativa)"
        )
        ax_env.set_title("Envolvente RMS y respiraciones detectadas")
        ax_env.set_xlabel("Tiempo (s)")
        ax_env.set_ylabel("RMS")
        ax_env.legend(loc="upper right", fontsize=8)

        # --- Subplot 3: histograma de intervalos entre respiraciones ---
        intervalos = resultado["intervalos_entre_respiraciones"]
        if len(intervalos) > 0:
            ax_hist.hist(intervalos, bins=min(10, max(3, len(intervalos))), color="seagreen", edgecolor="black")
        ax_hist.set_title("Distribución de intervalos entre respiraciones")
        ax_hist.set_xlabel("Intervalo (s)")
        ax_hist.set_ylabel("Frecuencia")

        fig.suptitle(f"Análisis respiratorio - {self.ruta_wav.name}", fontsize=14)
        fig.tight_layout()

        if guardar_en is not None:
            CARPETA_GRAFICAS.mkdir(parents=True, exist_ok=True)
            ruta_destino = Path(guardar_en)
            if not ruta_destino.is_absolute():
                ruta_destino = CARPETA_GRAFICAS / ruta_destino
            fig.savefig(ruta_destino, dpi=300, bbox_inches="tight")
            print(f"Gráfica guardada en: {ruta_destino}")

        plt.show()

        return fig


if __name__ == "__main__":
    wavs_disponibles = list(CARPETA_AUDIO.glob("*.wav"))
    if not wavs_disponibles:
        raise FileNotFoundError(
            f"No hay archivos WAV en {CARPETA_AUDIO}. "
            "Corre primero capturar_respiracion.py para generar una grabación."
        )
    wav_mas_reciente = max(wavs_disponibles, key=lambda ruta: ruta.stat().st_mtime)
    print(f"Analizando el WAV más reciente: {wav_mas_reciente.name}\n")

    # Dos instancias separadas (no una sola reutilizada) para comparar ANTES/DESPUÉS sin
    # que el filtrado o la amplificación de una corrida contamine el estado de la otra
    def _texto_bpm(bpm: float) -> str:
        return f"{bpm:.2f}" if not np.isnan(bpm) else "NaN"

    print("=== ANTES (defaults originales: altura_relativa=0.3, sin amplificar, sin filtro) ===")
    detector_antes = DetectorRespiracion(wav_mas_reciente)
    detector_antes.cargar()
    detector_antes.calcular_envolvente()  # amplificar_senal=1.0 (default)
    resultado_antes = detector_antes.detectar_picos(altura_relativa=0.3)
    print(f"  numero_respiraciones: {resultado_antes['numero_respiraciones']}")
    print(f"  frecuencia_respiratoria_bpm: {_texto_bpm(resultado_antes['frecuencia_respiratoria_bpm'])}")

    print("\n=== DESPUÉS (nuevos defaults: altura_relativa=0.15, amplificar x2.5, pasa-banda 100-2000Hz) ===")
    detector_despues = DetectorRespiracion(wav_mas_reciente)
    detector_despues.cargar()
    resultados = detector_despues.analizar()
    for clave, valor in resultados.items():
        print(f"  {clave}: {valor}")

    print("\n=== Comparación ANTES vs. DESPUÉS ===")
    resultado_despues_picos = detector_despues.detectar_picos(altura_relativa=0.15)
    print(
        f"  Respiraciones detectadas: {resultado_antes['numero_respiraciones']} -> "
        f"{resultado_despues_picos['numero_respiraciones']}"
    )
    print(
        f"  Frecuencia respiratoria (bpm): {_texto_bpm(resultado_antes['frecuencia_respiratoria_bpm'])} -> "
        f"{_texto_bpm(resultado_despues_picos['frecuencia_respiratoria_bpm'])}"
    )

    print("\n=== Generando gráfica DESPUÉS (con los nuevos parámetros) ===")
    detector_grafica = DetectorRespiracion(wav_mas_reciente)
    detector_grafica.cargar()
    detector_grafica.graficar(
        guardar_en=f"{detector_grafica.ruta_wav.stem}_respiracion.png",
        altura_relativa=0.15,
        amplificar_senal=2.5,
        aplicar_filtro_pasa_banda=True,
    )
