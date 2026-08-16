"""Agrega sesiones de varios participantes y ejecuta estadística inferencial grupal.

Combina los CSV individuales generados por capturar_sesion.py (o por
simulador_multiparticipante.py, para datasets sintéticos) en una "tabla
maestra" con una fila por (participante, condición), y sobre esa tabla
aplica las comparaciones estadísticas del diseño intra-sujeto de la tesis:
t-test pareado entre pares de condiciones, un ANOVA exploratorio entre
todas las condiciones, correlación entre métricas, y una gráfica resumen
publicable.

Nota metodológica sobre el agrupamiento por condición:
calcular_metricas_participante() agrupa las lecturas de cada participante
por la etiqueta 'condicion' TAL CUAL viene en el CSV (no por bloque
contiguo, a diferencia de python/analisis/analizar_sesion.py). Si una
condición como "reposo" aparece en varios tramos no contiguos de la sesión
(baseline + descansos + cierre), SDNN es una medida válida sobre el pool
completo, pero RMSSD y pNN50 —que dependen de diferencias SUCESIVAS entre
R-R— terminan incluyendo "diferencias" en los bordes entre tramos que no
corresponden a latidos reales consecutivos. Se acepta esta simplificación
aquí porque agregar por condición cruda es la convención estándar para
comparar HRV ENTRE participantes en la literatura; para el análisis más
riguroso de una sesión individual, usar AnalisisSesion.metricas_por_condicion().
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

CARPETA_SESIONES_DEFAULT = Path(r"C:\Tesis_Kevin\datos\sesiones")
CARPETA_GRAFICAS = Path(r"C:\Tesis_Kevin\resultados\graficas")


class AnalisisGrupal:
    """Agrega y compara estadísticamente sesiones de varios participantes.

    Attributes:
        carpeta_sesiones (Path): Carpeta donde buscar los CSV de sesiones.
        patron_fecha (Optional[str]): Substring para filtrar CSV por sufijo
            de fecha/hora (ej. "20260812_2047"), útil cuando hay sesiones
            de distintas corridas mezcladas en la misma carpeta.
        sesiones (dict[str, pd.DataFrame]): Cargadas por cargar_todas_sesiones().
        tabla (Optional[pd.DataFrame]): Construida por tabla_maestra().
    """

    def __init__(
        self,
        carpeta_sesiones: Path = CARPETA_SESIONES_DEFAULT,
        patron_fecha: Optional[str] = None,
    ) -> None:
        """Inicializa el análisis grupal.

        Args:
            carpeta_sesiones: Carpeta donde están los CSV de sesiones.
            patron_fecha: Si se indica, solo se cargan CSV cuyo nombre
                contenga este substring (ej. "20260812_2047" para tomar
                solo las sesiones de esa corrida específica).
        """
        self.carpeta_sesiones = Path(carpeta_sesiones)
        self.patron_fecha = patron_fecha
        self.sesiones: dict[str, pd.DataFrame] = {}
        self.tabla: Optional[pd.DataFrame] = None

    def cargar_todas_sesiones(self) -> dict:
        """Busca y carga todos los CSV de sesión que cumplan patron_fecha.

        Al cargar cada CSV se descartan las lecturas con hr_bpm == 0 o
        rr_ms == 0 — artefactos de conexión BLE inicial (ver
        SensorWahoo.leer() en python/sensor/sensor_wahoo.py, que devuelve
        HR=0/rr_ms=0 mientras aún no llega la primera notificación real
        del sensor). Sin filtrarlas, contaminan SDNN/RMSSD con un salto
        artificial de 0 a la HR real (ambas dependen de diferencias
        sucesivas entre R-R consecutivos). El archivo CSV en disco NO se
        modifica — el filtro aplica solo a la copia en memoria
        (self.sesiones) que usa este análisis.

        Returns:
            dict[str, pd.DataFrame]: {participante_id: DataFrame de la
                sesión, ya sin lecturas HR=0/RR=0}.
        """
        patron = f"*{self.patron_fecha}*.csv" if self.patron_fecha else "*.csv"
        archivos = sorted(self.carpeta_sesiones.glob(patron))

        self.sesiones = {}
        self.lecturas_descartadas_por_participante: dict[str, int] = {}

        for archivo in archivos:
            # El nombre de archivo sigue {P##}_{fecha}_{hora}.csv (ver capturar_sesion.py)
            participante_id = archivo.stem.split("_")[0]
            if participante_id in self.sesiones:
                print(
                    f"Advertencia: ya había una sesión cargada para {participante_id}; "
                    f"'{archivo.name}' la reemplaza. Usa patron_fecha para evitar esta ambigüedad."
                )

            df = pd.read_csv(archivo)

            # Filtramos lecturas con HR=0 que suelen ser artefactos de conexión BLE inicial
            mascara_valida = (df["hr_bpm"] != 0) & (df["rr_ms"] != 0)
            descartadas = int((~mascara_valida).sum())
            self.lecturas_descartadas_por_participante[participante_id] = descartadas
            if descartadas > 0:
                print(f"  {participante_id}: se descartaron {descartadas} lectura(s) con HR=0/RR=0")

            self.sesiones[participante_id] = df[mascara_valida].reset_index(drop=True)

        print(
            f"Sesiones cargadas: {len(self.sesiones)} participantes -> "
            f"{sorted(self.sesiones.keys())}"
        )
        total_descartadas = sum(self.lecturas_descartadas_por_participante.values())
        if total_descartadas > 0:
            print(f"Total de lecturas descartadas por HR=0/RR=0 (todos los participantes): {total_descartadas}")

        return self.sesiones

    def calcular_metricas_participante(self, df_sesion: pd.DataFrame) -> pd.DataFrame:
        """Calcula métricas de HR y HRV por condición para UN participante.

        Fórmulas de HRV (ver también python/analisis/analizar_sesion.py,
        donde están explicadas con más detalle):
        - SDNN = np.std(rr, ddof=1): variabilidad global de la HR.
        - RMSSD = np.sqrt(np.mean(np.diff(rr)**2)): actividad parasimpática.
        - pNN50 = % de pares R-R consecutivos que difieren >50ms.

        Args:
            df_sesion: DataFrame de una sesión (columnas timestamp, hr_bpm,
                rr_ms, condicion, estimulo).

        Returns:
            pd.DataFrame: Una fila por condición, con condicion, hr_media,
                hr_std, hr_min, hr_max, sdnn, rmssd, pnn50, duracion_seg.
        """
        # Intervalo de muestreo típico de esta sesión (ej. ~1s si frecuencia_hz=1.0),
        # usado para estimar cuántos segundos representa cada grupo de lecturas
        intervalo_muestreo = df_sesion["timestamp"].diff().median()

        filas = []
        for condicion, grupo in df_sesion.groupby("condicion"):
            grupo = grupo.dropna(subset=["hr_bpm", "rr_ms"])

            # Filtramos lecturas con HR=0 que suelen ser artefactos de conexión BLE
            # inicial. Se repite aquí (además de en cargar_todas_sesiones()) porque
            # este método también se llama directamente sobre un df_sesion crudo desde
            # fuera de esta clase (ver Recomendador.recomendar_para_participante() en
            # recomendador.py) — sin este filtro defensivo, esa otra ruta quedaría
            # desprotegida. duracion_seg se calcula sobre el grupo SIN filtrar, porque
            # describe cuánto duró la condición en tiempo real, no cuántas lecturas
            # fueron válidas.
            duracion_seg = (
                round(len(grupo) * intervalo_muestreo, 1) if not np.isnan(intervalo_muestreo) else np.nan
            )
            grupo_valido = grupo[(grupo["hr_bpm"] != 0) & (grupo["rr_ms"] != 0)]
            descartadas = len(grupo) - len(grupo_valido)

            if len(grupo_valido) == 0:
                print(
                    f"Advertencia: la condición '{condicion}' quedó sin lecturas válidas "
                    "tras filtrar HR=0; sus métricas se marcan NaN."
                )
                filas.append(
                    {
                        "condicion": condicion,
                        "hr_media": np.nan,
                        "hr_std": np.nan,
                        "hr_min": np.nan,
                        "hr_max": np.nan,
                        "sdnn": np.nan,
                        "rmssd": np.nan,
                        "pnn50": np.nan,
                        "duracion_seg": duracion_seg,
                    }
                )
                continue

            if descartadas > 0:
                print(f"  Condición '{condicion}': se descartaron {descartadas} lectura(s) con HR=0.")

            hr = grupo_valido["hr_bpm"].to_numpy()
            rr = grupo_valido["rr_ms"].to_numpy()
            diferencias_rr = np.diff(rr)

            if len(rr) >= 2:
                sdnn = np.std(rr, ddof=1)
                rmssd = np.sqrt(np.mean(diferencias_rr**2))
                pnn50 = (np.sum(np.abs(diferencias_rr) > 50) / len(diferencias_rr)) * 100
            else:
                sdnn = rmssd = pnn50 = np.nan

            filas.append(
                {
                    "condicion": condicion,
                    "hr_media": round(hr.mean(), 2) if len(hr) else np.nan,
                    "hr_std": round(np.std(hr, ddof=1), 2) if len(hr) >= 2 else np.nan,
                    "hr_min": round(hr.min(), 2) if len(hr) else np.nan,
                    "hr_max": round(hr.max(), 2) if len(hr) else np.nan,
                    "sdnn": round(sdnn, 2) if not np.isnan(sdnn) else np.nan,
                    "rmssd": round(rmssd, 2) if not np.isnan(rmssd) else np.nan,
                    "pnn50": round(pnn50, 2) if not np.isnan(pnn50) else np.nan,
                    "duracion_seg": duracion_seg,
                }
            )

        return pd.DataFrame(filas)

    def tabla_maestra(self) -> pd.DataFrame:
        """Aplica calcular_metricas_participante a todos los participantes cargados.

        Si aún no se llamó cargar_todas_sesiones(), lo hace primero.

        Returns:
            pd.DataFrame: Una fila por (participante, condición), columnas
                ['participante_id', 'condicion', 'hr_media', 'hr_std',
                'sdnn', 'rmssd', 'pnn50', 'duracion_seg'].
        """
        if not self.sesiones:
            self.cargar_todas_sesiones()

        columnas_finales = [
            "participante_id",
            "condicion",
            "hr_media",
            "hr_std",
            "sdnn",
            "rmssd",
            "pnn50",
            "duracion_seg",
        ]

        tablas_por_participante = []
        for participante_id, df_sesion in self.sesiones.items():
            metricas = self.calcular_metricas_participante(df_sesion)
            metricas.insert(0, "participante_id", participante_id)
            tablas_por_participante.append(metricas[columnas_finales])

        self.tabla = pd.concat(tablas_por_participante, ignore_index=True)
        return self.tabla

    def comparar_condiciones_pareado(
        self, tabla: pd.DataFrame, cond_a: str, cond_b: str, metrica: str = "hr_media"
    ) -> dict:
        """Compara una métrica entre dos condiciones con t-test PAREADO entre participantes.

        ¿Por qué pareado? Cada participante aporta una medición en cond_a Y
        otra en cond_b (diseño intra-sujeto de la tesis: todos escuchan
        todas las condiciones). Un t-test pareado compara las DIFERENCIAS
        individuales (cond_a - cond_b, participante por participante)
        contra cero, en vez de tratar cond_a y cond_b como dos grupos
        independientes — así se elimina la variabilidad ENTRE personas
        (cada quien es su propio control), dando mucha más potencia
        estadística que un t-test independiente con el mismo N. Es
        exactamente el test que corresponde a este diseño experimental.

        Args:
            tabla: Tabla maestra (ver tabla_maestra()).
            cond_a: Primera condición a comparar.
            cond_b: Segunda condición a comparar.
            metrica: Columna de la tabla a comparar (default "hr_media").

        Returns:
            dict: t_statistic, p_value, cohen_d, n_participantes,
                interpretacion, media_a, media_b, diferencia_media.

        Raises:
            ValueError: Si alguna condición no está en la tabla, o si hay
                menos de 2 participantes con datos en ambas condiciones.
        """
        pivote = tabla.pivot_table(index="participante_id", columns="condicion", values=metrica)
        if cond_a not in pivote.columns or cond_b not in pivote.columns:
            raise ValueError(
                f"'{cond_a}' o '{cond_b}' no están en la tabla. Disponibles: {list(pivote.columns)}"
            )

        datos = pivote[[cond_a, cond_b]].dropna()
        if len(datos) < 2:
            raise ValueError(
                f"Se necesitan al menos 2 participantes con ambas condiciones; hay {len(datos)}."
            )

        valores_a = datos[cond_a].to_numpy()
        valores_b = datos[cond_b].to_numpy()

        t_statistic, p_value = stats.ttest_rel(valores_a, valores_b)

        diferencias = valores_a - valores_b
        # Cohen's d PAREADO: media de las diferencias individuales sobre la desviación
        # estándar de esas mismas diferencias (no la "pooled" de dos grupos independientes)
        cohen_d = diferencias.mean() / diferencias.std(ddof=1)

        interpretacion = self._interpretar_comparacion(
            cond_a, cond_b, diferencias.mean(), p_value, cohen_d, metrica
        )

        return {
            "t_statistic": round(t_statistic, 3),
            "p_value": round(p_value, 4),
            "cohen_d": round(cohen_d, 3),
            "n_participantes": len(datos),
            "interpretacion": interpretacion,
            "media_a": round(valores_a.mean(), 2),
            "media_b": round(valores_b.mean(), 2),
            "diferencia_media": round(diferencias.mean(), 2),
        }

    @staticmethod
    def _interpretar_comparacion(
        cond_a: str, cond_b: str, diferencia_media: float, p_value: float, cohen_d: float, metrica: str
    ) -> str:
        """Arma una frase legible con el resultado de comparar_condiciones_pareado().

        Cohen's d en el contexto de HR (bpm): la frecuencia cardíaca en
        reposo de una misma persona varía relativamente poco entre
        sesiones, así que incluso una diferencia de pocos bpm entre
        condiciones puede corresponder a un d grande y ser fisiológicamente
        relevante. Umbrales estándar (Cohen, 1988): <0.2 pequeño, ~0.5
        mediano, >0.8 grande.
        """
        if p_value >= 0.05:
            return f"Sin diferencia significativa en {metrica} entre {cond_a} y {cond_b} (p={p_value:.3f})"

        direccion = "menor" if diferencia_media < 0 else "mayor"
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
            f"{metrica} significativamente {direccion} en {cond_a} respecto a {cond_b} "
            f"(p={p_value:.3f}, Cohen's d={cohen_d:.2f}, efecto {tamano_efecto})"
        )

    def anova_condiciones(self, tabla: pd.DataFrame, metrica: str = "hr_media") -> dict:
        """ANOVA exploratorio de una métrica entre TODAS las condiciones.

        Ojo: scipy.stats.f_oneway hace un ANOVA de una vía ESTÁNDAR, que
        trata cada condición como un grupo de muestras INDEPENDIENTES —
        ignora que en realidad el MISMO participante aparece en las 5
        condiciones (medidas repetidas). Una ANOVA de medidas repetidas de
        verdad modela explícitamente esa correlación intra-sujeto
        (normalmente con statsmodels.stats.anova.AnovaRM), lo que suele dar
        MÁS potencia estadística porque remueve la varianza entre-sujetos
        antes de evaluar el efecto de la condición. f_oneway se usa aquí
        como aproximación exploratoria rápida (sin agregar statsmodels como
        dependencia nueva del proyecto) para una primera mirada ómnibus a
        si ALGUNA condición difiere de las demás — el resultado confirmatorio
        de la tesis debería recalcularse con AnovaRM antes de publicarse.

        Args:
            tabla: Tabla maestra (ver tabla_maestra()).
            metrica: Columna de la tabla a comparar (default "hr_media").

        Returns:
            dict: f_statistic, p_value, condiciones_comparadas,
                n_participantes, interpretacion.
        """
        pivote = tabla.pivot_table(index="participante_id", columns="condicion", values=metrica)
        pivote = pivote.dropna()  # solo participantes con TODAS las condiciones completas

        condiciones = list(pivote.columns)
        grupos = [pivote[condicion].to_numpy() for condicion in condiciones]

        f_statistic, p_value = stats.f_oneway(*grupos)

        if p_value < 0.05:
            interpretacion = (
                f"Al menos una condición difiere significativamente en {metrica} entre "
                f"las {len(condiciones)} condiciones (p={p_value:.3f}) — aproximación "
                "exploratoria, ver nota sobre f_oneway vs. medidas repetidas en el código."
            )
        else:
            interpretacion = (
                f"Sin diferencias significativas en {metrica} entre las {len(condiciones)} "
                f"condiciones (p={p_value:.3f})"
            )

        return {
            "f_statistic": round(f_statistic, 3),
            "p_value": round(p_value, 4),
            "condiciones_comparadas": condiciones,
            "n_participantes": len(pivote),
            "interpretacion": interpretacion,
        }

    def correlacion_entre_metricas(
        self, tabla: pd.DataFrame, metrica_x: str, metrica_y: str
    ) -> dict:
        """Correlación de Pearson entre dos métricas, a nivel de fila (participante-condición).

        Args:
            tabla: Tabla maestra (ver tabla_maestra()).
            metrica_x: Primera columna numérica.
            metrica_y: Segunda columna numérica.

        Returns:
            dict: r, p_value, n, interpretacion.
        """
        datos = tabla[[metrica_x, metrica_y]].dropna()
        r, p_value = stats.pearsonr(datos[metrica_x], datos[metrica_y])
        n = len(datos)

        direccion = "positiva" if r > 0 else "negativa"
        r_abs = abs(r)
        if r_abs < 0.3:
            magnitud = "débil"
        elif r_abs < 0.7:
            magnitud = "moderada"
        else:
            magnitud = "fuerte"
        significativo = "significativa" if p_value < 0.05 else "no significativa"

        interpretacion = (
            f"Correlación {direccion} {magnitud} entre {metrica_x} y {metrica_y} "
            f"(r={r:.3f}, p={p_value:.3f}, {significativo}, n={n})"
        )

        return {"r": round(r, 3), "p_value": round(p_value, 4), "n": n, "interpretacion": interpretacion}

    def graficar_comparacion_grupal(
        self, tabla: pd.DataFrame, guardar_en: Optional[Path] = None
    ) -> plt.Figure:
        """Genera y guarda una figura de 4 subplots resumiendo el análisis grupal.

        Subplots:
            1. Boxplot de HR media por condición (un punto por participante).
            2. Barras de SDNN por condición (media ± SEM).
            3. Barras de RMSSD por condición (media ± SEM).
            4. Scatter HR media vs. SDNN (por fila participante-condición),
               con línea de regresión y (r, p) en el título.

        ¿Por qué SEM (error estándar de la media) y no desviación estándar
        en las barras? Con N=6 participantes, el SEM (= std / sqrt(n))
        refleja qué tan precisa es la ESTIMACIÓN del promedio grupal (se
        reduce cuantos más participantes se agreguen), mientras que la
        desviación estándar solo describe cuánto varían los individuos
        entre sí. Para comparar promedios grupales entre condiciones, el
        SEM es la barra de error convencional en la literatura.

        Args:
            tabla: Tabla maestra (ver tabla_maestra()).
            guardar_en: Nombre de archivo o ruta. Si es None, se guarda
                automáticamente en C:\\Tesis_Kevin\\resultados\\graficas\\
                con nombre "analisis_grupal_{fecha}.png".

        Returns:
            plt.Figure: La figura generada.
        """
        num_participantes = tabla["participante_id"].nunique()
        condiciones = list(dict.fromkeys(tabla["condicion"]))  # orden de aparición, sin duplicados

        fig, ((ax_box, ax_sdnn), (ax_rmssd, ax_scatter)) = plt.subplots(2, 2, figsize=(14, 10))

        # --- Subplot 1: Boxplot de HR por condición ---
        datos_hr = [tabla.loc[tabla["condicion"] == c, "hr_media"].dropna().to_numpy() for c in condiciones]
        ax_box.boxplot(datos_hr, tick_labels=condiciones)
        ax_box.set_title("HR media por condición (todos los participantes)")
        ax_box.set_ylabel("HR (bpm)")
        ax_box.tick_params(axis="x", rotation=30)

        # --- Subplots 2 y 3: barras de media ± SEM para SDNN y RMSSD ---
        for eje, columna, titulo in ((ax_sdnn, "sdnn", "SDNN"), (ax_rmssd, "rmssd", "RMSSD")):
            resumen = tabla.groupby("condicion")[columna].agg(["mean", "std", "count"]).reindex(condiciones)
            resumen["sem"] = resumen["std"] / np.sqrt(resumen["count"])
            eje.bar(resumen.index, resumen["mean"], yerr=resumen["sem"], capsize=4, color="steelblue")
            eje.set_title(f"{titulo} por condición (media ± SEM)")
            eje.set_ylabel("ms")
            eje.tick_params(axis="x", rotation=30)

        # --- Subplot 4: scatter HR vs SDNN con línea de regresión ---
        datos_scatter = tabla[["hr_media", "sdnn"]].dropna()
        ax_scatter.scatter(datos_scatter["hr_media"], datos_scatter["sdnn"], alpha=0.7, color="darkorange")
        if len(datos_scatter) >= 2:
            pendiente, intercepto = np.polyfit(datos_scatter["hr_media"], datos_scatter["sdnn"], 1)
            x_linea = np.array([datos_scatter["hr_media"].min(), datos_scatter["hr_media"].max()])
            ax_scatter.plot(x_linea, pendiente * x_linea + intercepto, color="black", linestyle="--")
            r, p_value = stats.pearsonr(datos_scatter["hr_media"], datos_scatter["sdnn"])
            ax_scatter.set_title(f"HR media vs. SDNN (r={r:.2f}, p={p_value:.3f})")
        else:
            ax_scatter.set_title("HR media vs. SDNN")
        ax_scatter.set_xlabel("HR media (bpm)")
        ax_scatter.set_ylabel("SDNN (ms)")

        fig.suptitle(f"Análisis grupal - N={num_participantes} participantes", fontsize=14)
        fig.tight_layout()

        if guardar_en is None:
            fecha = datetime.now().strftime("%Y%m%d_%H%M")
            ruta_destino = CARPETA_GRAFICAS / f"analisis_grupal_{fecha}.png"
        else:
            ruta_destino = Path(guardar_en)
            if not ruta_destino.is_absolute():
                ruta_destino = CARPETA_GRAFICAS / ruta_destino

        CARPETA_GRAFICAS.mkdir(parents=True, exist_ok=True)
        fig.savefig(ruta_destino, dpi=300, bbox_inches="tight")
        print(f"Gráfica guardada en: {ruta_destino}")

        return fig


if __name__ == "__main__":
    analisis = AnalisisGrupal(patron_fecha="20260812_2047")
    analisis.cargar_todas_sesiones()

    tabla = analisis.tabla_maestra()
    print("\n=== Tabla maestra (primeras filas) ===")
    print(tabla.head(10).to_string(index=False))

    print("\n=== Comparación pareada: HR reposo vs. preferencia ===")
    resultado = analisis.comparar_condiciones_pareado(tabla, "reposo", "preferencia", metrica="hr_media")
    for clave, valor in resultado.items():
        print(f"  {clave}: {valor}")

    print("\n=== Comparación pareada: HR solfeggio vs. preferencia ===")
    resultado = analisis.comparar_condiciones_pareado(tabla, "solfeggio", "preferencia", metrica="hr_media")
    for clave, valor in resultado.items():
        print(f"  {clave}: {valor}")

    print("\n=== Comparación pareada: RMSSD reposo vs. preferencia ===")
    resultado = analisis.comparar_condiciones_pareado(tabla, "reposo", "preferencia", metrica="rmssd")
    for clave, valor in resultado.items():
        print(f"  {clave}: {valor}")

    print("\n=== ANOVA exploratorio: HR entre todas las condiciones ===")
    resultado = analisis.anova_condiciones(tabla, metrica="hr_media")
    for clave, valor in resultado.items():
        print(f"  {clave}: {valor}")

    print("\n=== Correlación: HR media vs. SDNN ===")
    resultado = analisis.correlacion_entre_metricas(tabla, "hr_media", "sdnn")
    for clave, valor in resultado.items():
        print(f"  {clave}: {valor}")

    print("\n=== Generando gráfica grupal ===")
    analisis.graficar_comparacion_grupal(tabla)
