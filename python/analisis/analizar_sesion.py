"""Análisis de una sesión experimental capturada por capturar_sesion.py.

Carga el CSV de una sesión (columnas: timestamp, hr_bpm, rr_ms, condicion,
estimulo), calcula métricas de HR y de variabilidad de la frecuencia
cardíaca (HRV) por bloque de estímulo, compara condiciones con un t-test
pareado y genera una gráfica resumen de la sesión.

Nota metodológica importante sobre el agrupamiento:
Un mismo protocolo puede repetir la misma condición en bloques no
contiguos (ej. "reposo" aparece como baseline, descanso1 y cierre, en
momentos distintos de la sesión). Las métricas de HRV (SDNN, RMSSD, pNN50)
dependen de diferencias sucesivas entre intervalos R-R consecutivos reales:
si se mezclaran R-R de bloques no contiguos, la "diferencia sucesiva" entre
el último R-R de un bloque y el primero del otro sería artificial (no
corresponde a dos latidos reales consecutivos) y contaminaría el cálculo.
Por eso metricas_por_condicion() agrupa por BLOQUE CONTIGUO (detectado por
cambios de estimulo/condicion en el tiempo), no por la etiqueta de
condición cruda. Esto puede producir varias filas con la misma condición
(ej. 3 filas "reposo"), lo cual es correcto y esperado.
comparar_condiciones(), en cambio, sí puede mezclar bloques no contiguos
porque solo usa valores de HR independientes por lectura (no diferencias
sucesivas), donde esa mezcla no introduce ningún artefacto.
"""

from pathlib import Path
from typing import Optional, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# Carpeta oficial donde se guardan las gráficas de resultados
CARPETA_GRAFICAS = Path(r"C:\Tesis_Kevin\resultados\graficas")

# Columnas que debe tener cualquier CSV generado por capturar_sesion.py
COLUMNAS_REQUERIDAS = ["timestamp", "hr_bpm", "rr_ms", "condicion", "estimulo"]


class AnalisisSesion:
    """Analiza el CSV de una sesión: resumen, métricas de HRV y gráficas.

    Attributes:
        ruta_csv (Path): Ruta al CSV de la sesión.
        participante_id (str): Extraído del nombre de archivo (ej. "P01"
            desde "P01_20260812_1445.csv").
        df (pd.DataFrame): Datos crudos cargados con cargar().
    """

    def __init__(self, ruta_csv: Union[str, Path]) -> None:
        """Inicializa el análisis a partir de la ruta del CSV.

        Args:
            ruta_csv: Ruta al CSV generado por CapturaSesion.
        """
        self.ruta_csv = Path(ruta_csv)
        self.participante_id: Optional[str] = None
        self.df: Optional[pd.DataFrame] = None

    def cargar(self) -> pd.DataFrame:
        """Carga el CSV y valida que tenga las columnas requeridas.

        Returns:
            pd.DataFrame: Los datos crudos de la sesión.

        Raises:
            FileNotFoundError: Si ruta_csv no existe.
            ValueError: Si faltan columnas requeridas en el CSV.
        """
        if not self.ruta_csv.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {self.ruta_csv}")

        df = pd.read_csv(self.ruta_csv)

        faltantes = set(COLUMNAS_REQUERIDAS) - set(df.columns)
        if faltantes:
            raise ValueError(
                f"El CSV '{self.ruta_csv.name}' no tiene las columnas requeridas: "
                f"{sorted(faltantes)}"
            )

        self.df = df
        # El nombre de archivo sigue el formato {P##}_{fecha}_{hora}.csv (ver capturar_sesion.py)
        self.participante_id = self.ruta_csv.stem.split("_")[0]

        return self.df

    def _bloques_contiguos(self) -> list[dict]:
        """Detecta los bloques contiguos de estímulo dentro de la sesión.

        Un bloque contiguo es un tramo de filas consecutivas donde la
        columna 'estimulo' no cambia. Se usa como base para calcular HRV
        sin mezclar R-R de tramos no consecutivos en el tiempo (ver
        docstring del módulo).

        Returns:
            list[dict]: Uno por bloque, con condicion, estimulo,
                duracion_seg y el sub-DataFrame de ese bloque ("datos").
        """
        df = self.df
        # cumsum() de un cambio booleano genera un id que aumenta cada vez que
        # 'estimulo' cambia respecto a la fila anterior => agrupa tramos contiguos
        id_bloque = (df["estimulo"] != df["estimulo"].shift()).cumsum()

        bloques = []
        for _, datos_bloque in df.groupby(id_bloque):
            t_inicio = datos_bloque["timestamp"].iloc[0]
            t_fin = datos_bloque["timestamp"].iloc[-1]
            bloques.append(
                {
                    "condicion": datos_bloque["condicion"].iloc[0],
                    "estimulo": datos_bloque["estimulo"].iloc[0],
                    "t_inicio": t_inicio,
                    "t_fin": t_fin,
                    "duracion_seg": t_fin - t_inicio,
                    "datos": datos_bloque,
                }
            )
        return bloques

    def _mascara_lecturas_validas(self) -> pd.Series:
        """Máscara booleana de lecturas SIN artefacto de conexión BLE inicial.

        Un sensor real (ver SensorWahoo.leer() en python/sensor/sensor_wahoo.py)
        devuelve hr_bpm=0 y rr_ms=0 mientras todavía no llegó ninguna
        notificación BLE real — normalmente solo la primera fila de la
        sesión, mientras se establece la conexión. Si esa fila se mezcla con
        lecturas reales, genera un salto artificial (de 0 a la HR real) que
        infla muchísimo SDNN/RMSSD, porque ambas dependen de diferencias
        SUCESIVAS entre R-R consecutivos.

        Returns:
            pd.Series: True en las filas válidas (hr_bpm != 0 y rr_ms != 0).
        """
        return (self.df["hr_bpm"] != 0) & (self.df["rr_ms"] != 0)

    def resumen_general(self) -> dict:
        """Calcula un resumen general de toda la sesión.

        hr_promedio_global/hr_min/hr_max se calculan sobre lecturas válidas
        únicamente (ver _mascara_lecturas_validas()) — total_lecturas y
        duracion_total_seg, en cambio, cuentan TODAS las filas del CSV
        (incluidas las descartadas), porque describen la sesión completa
        tal como se capturó, no el subconjunto usado para las métricas.

        Returns:
            dict: participante_id, duracion_total_seg, total_lecturas,
                hr_promedio_global, hr_min, hr_max, condiciones_evaluadas,
                lecturas_descartadas_hr0 (cuántas filas se excluyeron por
                ser artefacto de conexión BLE inicial).
        """
        df = self.df
        mascara_valida = self._mascara_lecturas_validas()
        df_valido = df[mascara_valida]
        descartadas = int((~mascara_valida).sum())

        return {
            "participante_id": self.participante_id,
            "duracion_total_seg": round(df["timestamp"].max() - df["timestamp"].min(), 1),
            "total_lecturas": len(df),
            "hr_promedio_global": round(df_valido["hr_bpm"].mean(), 1) if len(df_valido) else np.nan,
            "hr_min": round(df_valido["hr_bpm"].min(), 1) if len(df_valido) else np.nan,
            "hr_max": round(df_valido["hr_bpm"].max(), 1) if len(df_valido) else np.nan,
            "condiciones_evaluadas": list(df["condicion"].unique()),
            "lecturas_descartadas_hr0": descartadas,
        }

    def metricas_por_condicion(self) -> pd.DataFrame:
        """Calcula métricas de HR y HRV por bloque contiguo de estímulo.

        Métricas de variabilidad de la frecuencia cardíaca (HRV) calculadas
        sobre los intervalos R-R (rr_ms) de cada bloque:

        - SDNN (Standard Deviation of NN intervals): desviación estándar de
          los R-R del bloque. Refleja la variabilidad GLOBAL de la HR
          (influencia simpática + parasimpática combinadas). Mayor SDNN =
          mejor tono autónomo general.
          Fórmula: np.std(rr, ddof=1)

        - RMSSD (Root Mean Square of Successive Differences): raíz de la
          media de las diferencias sucesivas de R-R al cuadrado. Refleja
          principalmente actividad PARASIMPÁTICA (sistema de "descanso y
          digestión"). Mayor RMSSD = participante más relajado.
          Fórmula: np.sqrt(np.mean(np.diff(rr)**2))

        - pNN50: porcentaje de pares de R-R consecutivos que difieren en
          más de 50 ms entre sí. Métrica clásica de variabilidad de
          referencia en literatura de HRV; mayor pNN50 = mejor función
          autónoma / mayor variabilidad latido a latido.
          Fórmula: np.sum(np.abs(np.diff(rr)) > 50) / len(np.diff(rr)) * 100

        Antes de calcular cualquier métrica, se descartan (por bloque) las
        lecturas con hr_bpm == 0 o rr_ms == 0 — artefactos de conexión BLE
        inicial, ver _mascara_lecturas_validas(). duracion_seg se calcula
        sobre TODAS las lecturas del bloque (sin filtrar), porque describe
        cuánto duró el bloque en tiempo real, no cuántas lecturas fueron
        válidas.

        Returns:
            pd.DataFrame: Una fila por bloque contiguo, con columnas
                condicion, estimulo, duracion_seg, hr_promedio, hr_std,
                hr_min, hr_max, sdnn, rmssd, pnn50.
        """
        filas = []
        for bloque in self._bloques_contiguos():
            datos = bloque["datos"]

            # Filtramos lecturas con HR=0 que suelen ser artefactos de conexión BLE inicial
            datos_validos = datos[(datos["hr_bpm"] != 0) & (datos["rr_ms"] != 0)]
            descartadas = len(datos) - len(datos_validos)

            if len(datos_validos) == 0:
                print(
                    f"Advertencia: el bloque '{bloque['estimulo']}' ({bloque['condicion']}) "
                    "quedó sin lecturas válidas tras filtrar HR=0; sus métricas se marcan NaN."
                )
                filas.append(
                    {
                        "condicion": bloque["condicion"],
                        "estimulo": bloque["estimulo"],
                        "duracion_seg": round(bloque["duracion_seg"], 1),
                        "hr_promedio": np.nan,
                        "hr_std": np.nan,
                        "hr_min": np.nan,
                        "hr_max": np.nan,
                        "sdnn": np.nan,
                        "rmssd": np.nan,
                        "pnn50": np.nan,
                    }
                )
                continue

            if descartadas > 0:
                print(
                    f"  Bloque '{bloque['estimulo']}' ({bloque['condicion']}): se descartaron "
                    f"{descartadas} lectura(s) con HR=0 antes de calcular HRV."
                )

            hr = datos_validos["hr_bpm"].to_numpy()
            rr = datos_validos["rr_ms"].to_numpy()
            diferencias_rr = np.diff(rr)

            # Con un solo latido no hay diferencias sucesivas que calcular
            if len(rr) >= 2:
                sdnn = np.std(rr, ddof=1)
                rmssd = np.sqrt(np.mean(diferencias_rr**2))
                pnn50 = np.sum(np.abs(diferencias_rr) > 50) / len(diferencias_rr) * 100
            else:
                sdnn = rmssd = pnn50 = np.nan

            filas.append(
                {
                    "condicion": bloque["condicion"],
                    "estimulo": bloque["estimulo"],
                    "duracion_seg": round(bloque["duracion_seg"], 1),
                    "hr_promedio": round(hr.mean(), 1),
                    "hr_std": round(np.std(hr, ddof=1), 2) if len(hr) >= 2 else np.nan,
                    "hr_min": round(hr.min(), 1),
                    "hr_max": round(hr.max(), 1),
                    "sdnn": round(sdnn, 2) if not np.isnan(sdnn) else np.nan,
                    "rmssd": round(rmssd, 2) if not np.isnan(rmssd) else np.nan,
                    "pnn50": round(pnn50, 1) if not np.isnan(pnn50) else np.nan,
                }
            )

        return pd.DataFrame(filas)

    def comparar_condiciones(self, condicion_a: str, condicion_b: str) -> dict:
        """Compara la HR entre dos condiciones con un t-test pareado y Cohen's d.

        A diferencia de metricas_por_condicion(), aquí se agrupan TODAS las
        lecturas de HR de cada condición (aunque provengan de bloques no
        contiguos), porque la HR es un valor independiente por lectura y no
        depende de diferencias sucesivas entre R-R consecutivos.

        El t-test pareado (scipy.stats.ttest_rel) exige dos series del
        mismo largo, apareadas 1 a 1. Aquí se aparea por orden temporal
        dentro de cada condición (lectura i de A con lectura i de B), como
        aproximación exploratoria a nivel de una sola sesión. El análisis
        confirmatorio real de la tesis se hace entre participantes (media
        de cada participante en A vs. en B, N=15-20), no dentro de una sola
        sesión.

        Args:
            condicion_a: Nombre de la primera condición a comparar.
            condicion_b: Nombre de la segunda condición a comparar.

        Returns:
            dict: t_statistic, p_value, diferencia_media_hr, cohen_d,
                interpretacion.

        Raises:
            ValueError: Si alguna condición no existe en los datos, o si no
                hay suficientes lecturas (mínimo 2) para comparar.
        """
        df = self.df
        condiciones_disponibles = set(df["condicion"].unique())
        for condicion in (condicion_a, condicion_b):
            if condicion not in condiciones_disponibles:
                raise ValueError(
                    f"Condición '{condicion}' no está en la sesión. "
                    f"Disponibles: {sorted(condiciones_disponibles)}"
                )

        hr_a = df.loc[df["condicion"] == condicion_a, "hr_bpm"].to_numpy()
        hr_b = df.loc[df["condicion"] == condicion_b, "hr_bpm"].to_numpy()

        n_pareado = min(len(hr_a), len(hr_b))
        if n_pareado < 2:
            raise ValueError(
                "Se necesitan al menos 2 lecturas por condición para el t-test pareado."
            )

        # t-test pareado: requiere series de igual largo, se recortan al mínimo común
        t_statistic, p_value = stats.ttest_rel(hr_a[:n_pareado], hr_b[:n_pareado])

        # La diferencia de medias y Cohen's d usan TODAS las lecturas disponibles
        # (no recortadas), para no descartar datos reales al estimar el efecto
        media_a, media_b = hr_a.mean(), hr_b.mean()
        n_a, n_b = len(hr_a), len(hr_b)
        var_a, var_b = hr_a.var(ddof=1), hr_b.var(ddof=1)

        # Desviación estándar combinada (pooled) de ambos grupos
        desviacion_pooled = np.sqrt(
            ((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)
        )
        cohen_d = (media_a - media_b) / desviacion_pooled

        diferencia_media_hr = media_a - media_b
        interpretacion = self._interpretar_comparacion(
            condicion_a, condicion_b, diferencia_media_hr, p_value, cohen_d
        )

        return {
            "t_statistic": round(t_statistic, 3),
            "p_value": round(p_value, 4),
            "diferencia_media_hr": round(diferencia_media_hr, 2),
            "cohen_d": round(cohen_d, 3),
            "interpretacion": interpretacion,
        }

    @staticmethod
    def _interpretar_comparacion(
        condicion_a: str,
        condicion_b: str,
        diferencia_media_hr: float,
        p_value: float,
        cohen_d: float,
    ) -> str:
        """Arma una frase legible con el resultado de comparar_condiciones().

        Umbrales de tamaño de efecto de Cohen's d (Cohen, 1988):
        <0.2 pequeño, ~0.5 mediano, >0.8 grande.
        """
        if p_value >= 0.05:
            return (
                f"Sin diferencia significativa en HR entre {condicion_a} y "
                f"{condicion_b} (p={p_value:.3f})"
            )

        direccion = "menor" if diferencia_media_hr < 0 else "mayor"
        d_abs = abs(cohen_d)
        if d_abs < 0.2:
            tamano_efecto = "pequeño"
        elif d_abs < 0.5:
            tamano_efecto = "pequeño-mediano"
        elif d_abs < 0.8:
            tamano_efecto = "mediano"
        else:
            tamano_efecto = "grande"

        return (
            f"HR significativamente {direccion} en {condicion_a} respecto a "
            f"{condicion_b} (p={p_value:.3f}, Cohen's d={cohen_d:.2f}, "
            f"efecto {tamano_efecto})"
        )

    def graficar_sesion(self, guardar_en: Optional[Union[str, Path]] = None) -> plt.Figure:
        """Genera una figura de 4 subplots resumiendo la sesión.

        Subplots:
            1. HR a lo largo del tiempo, con bandas de color por condición.
            2. R-R a lo largo del tiempo.
            3. Boxplot de HR por condición.
            4. Barras agrupadas de SDNN y RMSSD por bloque de estímulo.

        Args:
            guardar_en: Si es None, solo muestra la figura (plt.show()) sin
                guardarla. Si se indica un nombre de archivo, se guarda como
                PNG a 300 DPI dentro de la carpeta oficial de resultados
                (C:\\Tesis_Kevin\\resultados\\graficas\\); si se indica una
                ruta absoluta, se respeta esa ruta.

        Returns:
            plt.Figure: La figura generada (además de mostrarla/guardarla).
        """
        df = self.df
        df_valido = df[self._mascara_lecturas_validas()]
        bloques = self._bloques_contiguos()
        metricas = self.metricas_por_condicion()

        condiciones_unicas = list(df["condicion"].unique())
        colores = plt.get_cmap("tab10").colors
        mapa_color_condicion = {
            condicion: colores[i % len(colores)] for i, condicion in enumerate(condiciones_unicas)
        }

        fig, ejes = plt.subplots(2, 2, figsize=(14, 9))
        ((ax_hr, ax_rr), (ax_box, ax_barras)) = ejes

        # --- Subplot 1: HR en el tiempo con bandas de color por condición ---
        # Se grafica df_valido (sin los artefactos HR=0 de conexión BLE inicial, ver
        # _mascara_lecturas_validas()) para no mostrar el salto artificial 0 -> HR real
        ax_hr.plot(df_valido["timestamp"], df_valido["hr_bpm"], color="black", linewidth=1)
        condiciones_ya_etiquetadas = set()
        for bloque in bloques:
            condicion = bloque["condicion"]
            etiqueta = condicion if condicion not in condiciones_ya_etiquetadas else None
            ax_hr.axvspan(
                bloque["t_inicio"],
                bloque["t_fin"],
                color=mapa_color_condicion[condicion],
                alpha=0.25,
                label=etiqueta,
            )
            condiciones_ya_etiquetadas.add(condicion)
        ax_hr.set_title("Frecuencia cardíaca en el tiempo")
        ax_hr.set_xlabel("Tiempo (s)")
        ax_hr.set_ylabel("HR (bpm)")
        ax_hr.legend(loc="upper right", fontsize=8)

        # --- Subplot 2: R-R en el tiempo ---
        ax_rr.plot(df_valido["timestamp"], df_valido["rr_ms"], color="firebrick", linewidth=1)
        ax_rr.set_title("Intervalos R-R en el tiempo")
        ax_rr.set_xlabel("Tiempo (s)")
        ax_rr.set_ylabel("R-R (ms)")

        # --- Subplot 3: Boxplot de HR por condición ---
        datos_por_condicion = [
            df_valido.loc[df_valido["condicion"] == condicion, "hr_bpm"].to_numpy()
            for condicion in condiciones_unicas
        ]
        # matplotlib >= 3.11 renombró el parámetro 'labels' a 'tick_labels'
        ax_box.boxplot(datos_por_condicion, tick_labels=condiciones_unicas)
        ax_box.set_title("Distribución de HR por condición")
        ax_box.set_ylabel("HR (bpm)")
        ax_box.tick_params(axis="x", rotation=30)

        # --- Subplot 4: SDNN y RMSSD por bloque de estímulo ---
        posiciones = np.arange(len(metricas))
        ancho_barra = 0.35
        ax_barras.bar(posiciones - ancho_barra / 2, metricas["sdnn"], ancho_barra, label="SDNN")
        ax_barras.bar(posiciones + ancho_barra / 2, metricas["rmssd"], ancho_barra, label="RMSSD")
        ax_barras.set_xticks(posiciones)
        ax_barras.set_xticklabels(metricas["estimulo"], rotation=30, ha="right")
        ax_barras.set_title("HRV (SDNN y RMSSD) por bloque de estímulo")
        ax_barras.set_ylabel("ms")
        ax_barras.legend()

        fig.suptitle(f"Análisis Sesión {self.participante_id}", fontsize=14)
        fig.tight_layout()

        if guardar_en is not None:
            CARPETA_GRAFICAS.mkdir(parents=True, exist_ok=True)
            ruta_destino = Path(guardar_en)
            if not ruta_destino.is_absolute():
                ruta_destino = CARPETA_GRAFICAS / ruta_destino
            fig.savefig(ruta_destino, dpi=300, bbox_inches="tight")
            print(f"Gráfica guardada en: {ruta_destino}")
        else:
            plt.show()

        return fig


if __name__ == "__main__":
    CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")

    csvs_disponibles = list(CARPETA_SESIONES.glob("*.csv"))
    if not csvs_disponibles:
        raise FileNotFoundError(
            f"No hay archivos CSV en {CARPETA_SESIONES}. "
            "Corre primero capturar_sesion.py para generar una sesión."
        )
    csv_mas_reciente = max(csvs_disponibles, key=lambda ruta: ruta.stat().st_mtime)
    print(f"Analizando el CSV más reciente: {csv_mas_reciente.name}\n")

    analisis = AnalisisSesion(csv_mas_reciente)
    analisis.cargar()

    print("=== Resumen general ===")
    for clave, valor in analisis.resumen_general().items():
        print(f"  {clave}: {valor}")

    print("\n=== Métricas por bloque de estímulo ===")
    tabla_metricas = analisis.metricas_por_condicion()
    print(tabla_metricas.to_string(index=False))

    condiciones_presentes = set(analisis.df["condicion"].unique())
    if {"reposo", "preferencia"}.issubset(condiciones_presentes):
        print("\n=== Comparación reposo vs. preferencia ===")
        comparacion = analisis.comparar_condiciones("reposo", "preferencia")
        for clave, valor in comparacion.items():
            print(f"  {clave}: {valor}")
    else:
        print(
            "\n(Se omite la comparación reposo vs. preferencia: "
            "la sesión no tiene ambas condiciones)"
        )

    print("\n=== Generando gráfica de la sesión ===")
    analisis.graficar_sesion(guardar_en=f"{analisis.participante_id}_analisis.png")
