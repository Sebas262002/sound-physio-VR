"""Combina los 3 archivos de una sesión (sensor cardíaco + audio + estímulos) en un CSV unificado.

Una sesión completa genera tres registros independientes, cada uno con su
propio reloj:

    1. CSV cardíaco       (capturar_sesion.py)        → timestamp relativo a
       cuando arrancó ESE script (columna "timestamp", empieza en ~0).
    2. WAV + JSON de audio (capturar_respiracion.py)   → timestamp_inicio/fin
       en time.monotonic() ABSOLUTO (el reloj del sistema, no relativo a nada).
    3. JSON de estímulos   (reproductor_estimulos.py)  → t_inicio/t_fin
       relativos a cuando arrancó ESE script (empieza en ~0).

¿Por qué hay que alinear los timestamps? Porque el investigador ejecuta
estos tres scripts por separado (uno arranca el sensor, luego el
reproductor de estímulos, luego a veces la grabación de audio), así que
cada uno mide "segundos desde que YO arranqué", no "segundos desde que
empezó la sesión". Sin alinearlos, comparar "HR a los 60s" del CSV con
"estímulo activo a los 60s" del JSON de eventos sería comparar
segundo-60-de-una-cosa con segundo-60-de-otra-cosa-distinta.

Este módulo asume que, en la práctica, el investigador arranca los tres
sistemas en sucesión rápida al iniciar la sesión (en cuestión de segundos),
y re-ancla el inicio de cada archivo a un mismo punto de referencia (el
primer timestamp del CSV cardíaco). Esto NO es sincronización perfecta —
el margen de error real depende de cuántos segundos pasan entre arrancar
cada script — pero es la mejor aproximación posible sin un pulso de
sincronización externo (ej. un beep audible al inicio capturado por los
tres sistemas a la vez), que queda como mejora futura si se necesita
mayor precisión.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Tesis_Kevin\python\audio")
from detectar_respiraciones import DetectorRespiracion  # noqa: E402

CARPETA_PROCESADOS = Path(r"C:\Tesis_Kevin\datos\procesados")


class SincronizadorSesion:
    """Alinea y combina los 3 registros de una sesión en una tabla unificada.

    Attributes:
        csv_cardiaco (Path): CSV generado por capturar_sesion.py.
        wav_audio (Optional[Path]): WAV generado por capturar_respiracion.py
            (debe tener un .json hermano con su metadata). None = sin audio.
        json_estimulos (Path): JSON de eventos generado por reproductor_estimulos.py.
        ventana_analisis_seg (int): Tamaño de ventana para las métricas
            respiratorias rolling, en segundos.
    """

    def __init__(
        self,
        csv_cardiaco: Path,
        wav_audio: Optional[Path],
        json_estimulos: Path,
        ventana_analisis_seg: int = 10,
    ) -> None:
        """Inicializa el sincronizador con las rutas de los 3 archivos de la sesión.

        Args:
            csv_cardiaco: Ruta al CSV del sensor cardíaco.
            wav_audio: Ruta al WAV de respiración, o None para omitir el
                análisis respiratorio.
            json_estimulos: Ruta al JSON de eventos de estímulos.
            ventana_analisis_seg: Tamaño de ventana (s) para las métricas
                respiratorias rolling (default 10s).
        """
        self.csv_cardiaco = Path(csv_cardiaco)
        self.wav_audio = Path(wav_audio) if wav_audio is not None else None
        self.json_estimulos = Path(json_estimulos)
        self.ventana_analisis_seg = ventana_analisis_seg

        self.df_cardiaco: Optional[pd.DataFrame] = None
        self.metadata_audio: Optional[dict] = None
        self.eventos_estimulos: Optional[list] = None
        self.metadata_estimulos: Optional[dict] = None

        self.t0_referencia: Optional[float] = None
        self.eventos_estimulos_alineados: Optional[list] = None
        self.metadata_audio_alineada: Optional[dict] = None

        self.df_respiraciones_ventanas: Optional[pd.DataFrame] = None
        self.tabla_unificada: Optional[pd.DataFrame] = None

    def cargar_todo(self) -> None:
        """Carga el CSV cardíaco, la metadata de audio y el JSON de estímulos.

        La metadata de audio se busca en el .json hermano del WAV (mismo
        nombre, distinta extensión — el formato que guarda
        capturar_respiracion.py). Si wav_audio es None, o su JSON hermano
        no existe, se continúa sin datos de audio (self.metadata_audio queda
        en None) y el análisis respiratorio se omite más adelante.
        """
        self.df_cardiaco = pd.read_csv(self.csv_cardiaco)

        self.metadata_audio = None
        if self.wav_audio is not None:
            ruta_json_audio = self.wav_audio.with_suffix(".json")
            if ruta_json_audio.exists():
                with open(ruta_json_audio, "r", encoding="utf-8") as archivo:
                    self.metadata_audio = json.load(archivo)
            else:
                print(
                    f"Advertencia: no se encontró metadata JSON para {self.wav_audio.name}; "
                    "se continúa sin ella (afecta el anclaje temporal del audio, no lo impide)"
                )

        with open(self.json_estimulos, "r", encoding="utf-8") as archivo:
            contenido = json.load(archivo)

        # ReproductorEstimulos.guardar_eventos() guarda una lista bare (formato
        # original) o, si se le pasó metadata (ver python/sesion_completa.py, período
        # de estabilización), un objeto {"metadata": {...}, "eventos": [...]} — se
        # aceptan ambos formatos para no romper JSON generados antes de ese cambio
        if isinstance(contenido, dict) and "eventos" in contenido:
            self.eventos_estimulos = contenido["eventos"]
            self.metadata_estimulos = contenido.get("metadata")
        else:
            self.eventos_estimulos = contenido
            self.metadata_estimulos = None

    def alinear_temporalmente(self) -> None:
        """Re-ancla los timestamps del JSON de estímulos y la metadata de audio al CSV cardíaco.

        Ver la explicación completa en el docstring del módulo. En resumen:
        se toma el primer timestamp del CSV cardíaco como self.t0_referencia,
        y se desplazan los otros dos registros para que SU PROPIO inicio
        también caiga en ese mismo punto.
        """
        self.t0_referencia = float(self.df_cardiaco["timestamp"].iloc[0])

        # Eventos de estímulos: ya son relativos a su propio arranque (t_inicio del
        # primer bloque suele ser 0.0); se re-ancla ese primer instante a t0_referencia
        offset_eventos = self.eventos_estimulos[0]["t_inicio"] if self.eventos_estimulos else 0.0
        self.eventos_estimulos_alineados = []
        for evento in self.eventos_estimulos:
            evento_ajustado = dict(evento)
            evento_ajustado["t_inicio"] = evento["t_inicio"] - offset_eventos + self.t0_referencia
            evento_ajustado["t_fin"] = evento["t_fin"] - offset_eventos + self.t0_referencia
            self.eventos_estimulos_alineados.append(evento_ajustado)

        # Metadata de audio: timestamp_inicio/fin son monotonic ABSOLUTO (no relativos a
        # nada), porque así los guarda capturar_respiracion.py. Se normalizan restando su
        # propio timestamp_inicio (con lo que "0" pasa a significar "empezó a grabar
        # audio"), y ese cero se ancla también a t0_referencia.
        self.metadata_audio_alineada = None
        if self.metadata_audio is not None:
            inicio_absoluto = self.metadata_audio["timestamp_inicio"]
            self.metadata_audio_alineada = dict(self.metadata_audio)
            self.metadata_audio_alineada["timestamp_inicio_relativo"] = self.t0_referencia
            self.metadata_audio_alineada["timestamp_fin_relativo"] = (
                self.metadata_audio["timestamp_fin"] - inicio_absoluto + self.t0_referencia
            )

    def detectar_respiraciones_por_ventana(self) -> pd.DataFrame:
        """Calcula frecuencia respiratoria en ventanas deslizantes con 50% de solapamiento.

        Reutiliza DetectorRespiracion (detectar_respiraciones.py) para cada
        ventana, evitando duplicar la lógica de detección de picos: se le
        asignan directamente los arreglos de audio/samplerate de cada
        tramo, sin releer el archivo del disco por ventana.

        ¿Por qué solapar las ventanas al 50%? Cada ventana necesita ser lo
        bastante larga (ventana_analisis_seg, default 10s) para contener
        varias respiraciones y así estimar una frecuencia confiable — una
        ventana más corta podría tener 0 o 1 respiración, insuficiente para
        calcular un intervalo. Pero si las ventanas fueran consecutivas sin
        solapar, solo tendríamos un valor de frecuencia respiratoria nuevo
        cada 10s (resolución temporal pobre). Solapando al 50% (paso =
        ventana/2 = 5s), se obtiene un punto nuevo cada 5s, DUPLICANDO la
        resolución temporal de la curva sin sacrificar la duración de
        ventana que necesita cada estimación individual para ser confiable.

        Returns:
            pd.DataFrame: Columnas t_centro_ventana (s, ya en la escala de
                la sesión alineada), respiraciones_min (bpm) y
                variabilidad_respiratoria_seg. Vacío si no hay audio.
        """
        if self.wav_audio is None:
            self.df_respiraciones_ventanas = pd.DataFrame(
                columns=["t_centro_ventana", "respiraciones_min", "variabilidad_respiratoria_seg"]
            )
            return self.df_respiraciones_ventanas

        detector = DetectorRespiracion(self.wav_audio)
        detector.cargar()

        # Offset para pasar de "segundos desde que empezó a grabar el audio" a la
        # escala de tiempo de la sesión alineada (ver alinear_temporalmente())
        if self.metadata_audio_alineada is not None:
            offset_audio = self.metadata_audio_alineada["timestamp_inicio_relativo"]
        else:
            offset_audio = self.t0_referencia if self.t0_referencia is not None else 0.0

        paso_seg = self.ventana_analisis_seg / 2  # 50% de solapamiento
        num_ventanas = max(
            0, int((detector.duracion_seg - self.ventana_analisis_seg) / paso_seg) + 1
        )

        filas = []
        for i in range(num_ventanas):
            t_inicio_ventana = i * paso_seg
            t_fin_ventana = t_inicio_ventana + self.ventana_analisis_seg
            muestra_inicio = int(t_inicio_ventana * detector.sr)
            muestra_fin = int(t_fin_ventana * detector.sr)

            # "Sub-detector" que reutiliza toda la lógica de DetectorRespiracion pero
            # operando solo sobre el tramo de audio de esta ventana (sin releer el WAV)
            detector_ventana = DetectorRespiracion(self.wav_audio)
            detector_ventana.audio = detector.audio[muestra_inicio:muestra_fin]
            detector_ventana.sr = detector.sr
            detector_ventana.duracion_seg = self.ventana_analisis_seg

            resultado = detector_ventana.detectar_picos()

            variabilidad_seg = (
                resultado["variabilidad_respiratoria_ms"] / 1000
                if not np.isnan(resultado["variabilidad_respiratoria_ms"])
                else np.nan
            )

            filas.append(
                {
                    "t_centro_ventana": round((t_inicio_ventana + t_fin_ventana) / 2 + offset_audio, 3),
                    "respiraciones_min": resultado["frecuencia_respiratoria_bpm"],
                    "variabilidad_respiratoria_seg": variabilidad_seg,
                }
            )

        self.df_respiraciones_ventanas = pd.DataFrame(filas)
        return self.df_respiraciones_ventanas

    def asignar_estimulo_a_lecturas(self) -> pd.DataFrame:
        """Agrega a df_cardiaco qué bloque de estímulo cubría cada lectura.

        Usa un IntervalIndex (cerrado a la izquierda: [t_inicio, t_fin))
        para ubicar en qué bloque cae cada timestamp cardíaco de forma
        vectorizada, en vez de comparar fila por fila contra cada evento.

        Returns:
            pd.DataFrame: self.df_cardiaco con las columnas nuevas
                nombre_estimulo y tipo_estimulo agregadas.
        """
        eventos = self.eventos_estimulos_alineados
        intervalos = pd.IntervalIndex.from_arrays(
            [evento["t_inicio"] for evento in eventos],
            [evento["t_fin"] for evento in eventos],
            closed="left",
        )
        indices = intervalos.get_indexer(self.df_cardiaco["timestamp"])

        nombres_por_bloque = [evento["nombre"] for evento in eventos]
        tipos_por_bloque = [evento["tipo"] for evento in eventos]

        # get_indexer devuelve -1 para timestamps que no caen en ningún bloque conocido
        self.df_cardiaco["nombre_estimulo"] = [
            nombres_por_bloque[i] if i != -1 else None for i in indices
        ]
        self.df_cardiaco["tipo_estimulo"] = [
            tipos_por_bloque[i] if i != -1 else None for i in indices
        ]

        return self.df_cardiaco

    def crear_tabla_unificada(self) -> pd.DataFrame:
        """Combina cardíaco + estímulo + respiración en una sola tabla, alineados en el tiempo.

        La respiración se calcula en ventanas dispersas (un punto cada
        ventana_analisis_seg/2 segundos), mientras que el sensor cardíaco
        entrega lecturas mucho más densas y regulares (~1/seg). Para poder
        agregar "respiraciones_min" como una columna más de la tabla
        cardíaca, se interpola linealmente con np.interp: para cada
        timestamp cardíaco, busca los dos puntos de ventana respiratoria
        más cercanos (uno antes, uno después) y calcula el valor
        intermedio proporcional a qué tan cerca está de cada uno — el
        mismo principio que "unir los puntos con una recta" en un gráfico.
        Fuera del rango cubierto por las ventanas respiratorias, np.interp
        mantiene el valor del extremo más cercano (no extrapola), para no
        inventar datos donde no hay información real.

        Si asignar_estimulo_a_lecturas() o detectar_respiraciones_por_ventana()
        no se llamaron antes, se ejecutan aquí automáticamente.

        Returns:
            pd.DataFrame: timestamp, hr_bpm, rr_ms, condicion,
                nombre_estimulo, tipo_estimulo, respiraciones_min.
        """
        if "nombre_estimulo" not in self.df_cardiaco.columns:
            self.asignar_estimulo_a_lecturas()
        if self.df_respiraciones_ventanas is None:
            self.detectar_respiraciones_por_ventana()

        tabla = self.df_cardiaco[
            ["timestamp", "hr_bpm", "rr_ms", "condicion", "nombre_estimulo", "tipo_estimulo"]
        ].copy()

        df_resp_valido = self.df_respiraciones_ventanas.dropna(subset=["respiraciones_min"])
        if len(df_resp_valido) >= 2:
            tabla["respiraciones_min"] = np.interp(
                tabla["timestamp"],
                df_resp_valido["t_centro_ventana"],
                df_resp_valido["respiraciones_min"],
            )
        else:
            # Sin audio, o sin suficientes ventanas válidas para interpolar
            tabla["respiraciones_min"] = np.nan

        self.tabla_unificada = tabla
        return tabla

    def guardar_tabla_unificada(self, ruta_csv: Optional[Path] = None) -> Path:
        """Guarda la tabla unificada como CSV en datos/procesados/.

        Args:
            ruta_csv: Ruta destino. Si es None, se arma automáticamente
                como {participante_id}_unificado_{fecha}.csv dentro de
                C:\\Tesis_Kevin\\datos\\procesados\\. Si es un nombre
                relativo, se guarda dentro de esa misma carpeta oficial.

        Returns:
            Path: Ruta donde quedó guardado el CSV.
        """
        if ruta_csv is None:
            participante_id = self.csv_cardiaco.stem.split("_")[0]
            fecha = datetime.now().strftime("%Y%m%d_%H%M")
            ruta_csv = CARPETA_PROCESADOS / f"{participante_id}_unificado_{fecha}.csv"
        else:
            ruta_csv = Path(ruta_csv)
            if not ruta_csv.is_absolute():
                ruta_csv = CARPETA_PROCESADOS / ruta_csv

        ruta_csv.parent.mkdir(parents=True, exist_ok=True)
        self.tabla_unificada.to_csv(ruta_csv, index=False)

        return ruta_csv


if __name__ == "__main__":
    CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")
    CARPETA_AUDIO_SESIONES = CARPETA_SESIONES / "audio"

    csvs_disponibles = list(CARPETA_SESIONES.glob("*.csv"))
    if not csvs_disponibles:
        raise FileNotFoundError(f"No hay CSV cardíacos en {CARPETA_SESIONES}")
    csv_cardiaco = max(csvs_disponibles, key=lambda ruta: ruta.stat().st_mtime)

    wavs_disponibles = (
        list(CARPETA_AUDIO_SESIONES.glob("*.wav")) if CARPETA_AUDIO_SESIONES.exists() else []
    )
    wav_audio = max(wavs_disponibles, key=lambda ruta: ruta.stat().st_mtime) if wavs_disponibles else None

    jsons_disponibles = list(CARPETA_SESIONES.glob("*.json"))
    if not jsons_disponibles:
        raise FileNotFoundError(f"No hay JSON de estímulos en {CARPETA_SESIONES}")
    json_estimulos = max(jsons_disponibles, key=lambda ruta: ruta.stat().st_mtime)

    print(f"CSV cardíaco:   {csv_cardiaco.name}")
    print(f"WAV audio:      {wav_audio.name if wav_audio else '(no disponible, se omite respiración)'}")
    print(f"JSON estímulos: {json_estimulos.name}\n")

    sincronizador = SincronizadorSesion(csv_cardiaco, wav_audio, json_estimulos)

    print("=== Cargando archivos ===")
    sincronizador.cargar_todo()

    print("=== Alineando timestamps ===")
    sincronizador.alinear_temporalmente()

    print("=== Analizando respiración por ventana ===")
    sincronizador.detectar_respiraciones_por_ventana()

    print("=== Asignando estímulo a cada lectura cardíaca ===")
    sincronizador.asignar_estimulo_a_lecturas()

    print("=== Construyendo tabla unificada ===")
    tabla = sincronizador.crear_tabla_unificada()

    ruta_guardada = sincronizador.guardar_tabla_unificada()

    print("\n=== Resumen ===")
    print(f"Filas: {len(tabla)}")
    print(f"Columnas: {list(tabla.columns)}")
    print(f"Rango temporal: {tabla['timestamp'].min():.1f}s - {tabla['timestamp'].max():.1f}s")
    print(f"Estímulos únicos: {tabla['nombre_estimulo'].nunique()}")
    print(f"Guardado en: {ruta_guardada}")
