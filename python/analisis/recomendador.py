"""Algoritmo de recomendación post-sesión: cómo reaccionó cada participante ante
frecuencias terapéuticas comunes vs. sonidos de preferencia personal.

Objetivo central de la tesis (ver Hipótesis H1/H0, Capítulo I del documento):
comparar la respuesta fisiológica de relajación entre DOS GRUPOS — "frecuencias
terapéuticas comunes" (binaural/solfeggio-isocrónico/paisaje, sorteados en Día 1
y Día 3) y "sonidos de preferencia personal" (Día 2 y Día 4, dos canciones
distintas) — no un ranking de cuál tipo específico individual "ganó". Ver
comparar_grupos_terapeutica_vs_preferencia() para esa comparación de 2 grupos, que
es el resultado descriptivo por participante. El contraste ESTADÍSTICO de
H1/H0 entre participantes (ΔFC respecto al baseline, prueba pareada) está en
analisis_intrasujeto.py.

calcular_score_relajacion() sigue existiendo tal cual y sigue siendo útil como
detalle de respaldo por sesión (ver _tab_recomendacion() en app_investigador.py y
reporte_pdf.py: se muestra como "detalle por sesión", no como el resultado
principal) — comparar_grupos_terapeutica_vs_preferencia() se construye ENCIMA de
ese ranking ya calculado, agrupando y promediando, nunca mezclando HR crudo de
sesiones con baselines distintos.

Reutiliza AnalisisGrupal.calcular_metricas_participante() (ver
analisis_grupal.py) para no duplicar las fórmulas de HR/HRV — este módulo
se enfoca solo en la parte nueva: normalizar esas métricas contra el
baseline de cada participante y combinarlas en un score de relajación.
"""

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analisis_grupal import AnalisisGrupal

CARPETA_GRAFICAS = Path(r"C:\Tesis_Kevin\resultados\graficas")

# Pesos por default: HR es la métrica más directa y confiable (0.35), SDNN y RMSSD
# aportan el mismo peso entre sí (0.25 cada una, ambas HRV pero de mecanismos algo
# distintos — ver analizar_sesion.py), y respiración pesa menos (0.15) porque no
# siempre está disponible (ver manejo de NaN en calcular_score_relajacion)
PESOS_DEFAULT = {"hr_media": 0.35, "sdnn": 0.25, "rmssd": 0.25, "respiraciones_min": 0.15}


class Recomendador:
    """Calcula, para cada participante, qué condición le generó mejor relajación.

    Attributes:
        pesos (dict): Peso de cada métrica en el score de relajación (deben
            sumar 1.0, aunque no se fuerza — ver calcular_score_relajacion()
            para cómo se manejan pesos faltantes).
        excluir_condiciones (list[str]): Condiciones que nunca se recomiendan
            (default ["reposo"]: no tiene sentido "recomendar" no hacer nada
            — obviamente reposar reduce la activación fisiológica más que
            cualquier estímulo activo, así que incluirlo como candidato no
            aporta información útil sobre CUÁL estímulo prefiere el
            participante).

    ¿Por qué pesos ajustables en vez de una fórmula fija? Distintas
    hipótesis de la tesis pueden priorizar distinto qué significa "mejor
    respuesta" — un investigador centrado en el sistema simpático/parasimpático
    podría querer pesar RMSSD más fuerte, mientras uno centrado en el efecto
    subjetivo inmediato podría preferir pesar solo HR. Exponer los pesos como
    parámetro permite explorar esas hipótesis sin tocar el código.
    """

    def __init__(
        self,
        pesos: Optional[dict] = None,
        excluir_condiciones: Optional[list] = None,
    ) -> None:
        """Inicializa el recomendador.

        Args:
            pesos: Peso de cada métrica en el score (default PESOS_DEFAULT).
            excluir_condiciones: Condiciones a excluir de la recomendación
                (default ["reposo"]).
        """
        self.pesos = pesos if pesos is not None else dict(PESOS_DEFAULT)
        self.excluir_condiciones = (
            excluir_condiciones if excluir_condiciones is not None else ["reposo"]
        )

    def calcular_score_relajacion(
        self, metricas_por_condicion: pd.DataFrame, baseline_reposo: dict
    ) -> pd.DataFrame:
        """Normaliza las métricas de cada condición contra el baseline y arma el score.

        ¿Por qué normalizar contra el baseline del MISMO participante (y no
        comparar valores absolutos entre participantes)? Por la variabilidad
        interindividual: un HR de 70 bpm puede ser "relajado" para alguien
        con baseline de 82 (P04, "Estresado") pero "activado" para alguien
        con baseline de 65 (P01, "Relajado natural"). Normalizar como
        fracción de cambio respecto al PROPIO reposo hace que el score sea
        comparable entre participantes con fisiologías de partida distintas.

        Fórmulas de normalización (positivo siempre = "más relajado"):
            hr_media:           (baseline - condicion) / baseline
            sdnn, rmssd:        (condicion - baseline) / baseline
            respiraciones_min:  (baseline - condicion) / baseline

        Interpretación del score_relajacion resultante: es un promedio
        ponderado de esas fracciones. Un score positivo significa que, en
        conjunto, esa condición dejó al participante MÁS relajado que su
        reposo basal (HR más baja y/o HRV más alta y/o respiración más
        lenta); un score negativo significa que lo dejó MÁS ACTIVADO que en
        reposo — no necesariamente "malo" (podría ser el efecto esperado de
        un estímulo de activación), pero sí indica que no es el estímulo
        relajante recomendado.

        Manejo de NaN: si a un participante le falta respiraciones_min (lo
        más común, ya que requiere haber grabado y analizado audio), esa
        métrica se excluye del promedio y su peso se REDISTRIBUYE
        proporcionalmente entre las métricas restantes que sí están
        disponibles — así el score sigue siendo comparable en escala (0-1
        relativo) en vez de simplemente valer menos por tener un término
        faltante.

        Args:
            metricas_por_condicion: DataFrame con una fila por condición
                (columnas condicion, hr_media, sdnn, rmssd y opcionalmente
                respiraciones_min — ver AnalisisGrupal.calcular_metricas_participante()).
            baseline_reposo: dict con los valores de referencia (típicamente
                la fila "reposo" de metricas_por_condicion).

        Returns:
            pd.DataFrame: condicion, hr_media, sdnn, rmssd,
                respiraciones_min, score_relajacion — ordenado por
                score_relajacion descendente. OJO: las columnas de métricas
                (hr_media, sdnn, rmssd, respiraciones_min) conservan los
                valores CRUDOS (bpm, ms); solo score_relajacion está
                normalizado contra el baseline. Para el contraste de H1/H0
                (ΔFC en bpm respecto al baseline de cada sesión) NO usar
                estas columnas: usar analisis_intrasujeto.py.
        """
        resultado = metricas_por_condicion.copy()
        columnas_metricas = ["hr_media", "sdnn", "rmssd", "respiraciones_min"]

        # Asegura que las 4 columnas existan (respiraciones_min suele faltar en un
        # CSV puramente cardíaco; se completa con NaN para poder reportarla igual)
        for columna in columnas_metricas:
            if columna not in resultado.columns:
                resultado[columna] = np.nan

        normalizado = pd.DataFrame(index=resultado.index)
        for metrica in columnas_metricas:
            base = baseline_reposo.get(metrica)
            if base is None or pd.isna(base) or base == 0:
                normalizado[metrica] = np.nan
                continue
            if metrica in ("hr_media", "respiraciones_min"):
                normalizado[metrica] = (base - resultado[metrica]) / base
            else:  # sdnn, rmssd: subir es bueno
                normalizado[metrica] = (resultado[metrica] - base) / base

        scores = []
        for _, fila in normalizado.iterrows():
            pesos_disponibles = {
                metrica: self.pesos[metrica]
                for metrica in columnas_metricas
                if metrica in self.pesos and not pd.isna(fila[metrica])
            }
            if not pesos_disponibles:
                scores.append(np.nan)
                continue
            suma_pesos = sum(pesos_disponibles.values())
            score = sum(
                fila[metrica] * (peso / suma_pesos) for metrica, peso in pesos_disponibles.items()
            )
            scores.append(score)

        resultado["score_relajacion"] = scores

        columnas_finales = ["condicion"] + columnas_metricas + ["score_relajacion"]
        resultado = resultado[columnas_finales].sort_values(
            "score_relajacion", ascending=False
        ).reset_index(drop=True)

        return resultado

    def comparar_grupos_terapeutica_vs_preferencia(self, ranking: pd.DataFrame) -> dict:
        """Agrupa un ranking YA calculado por calcular_score_relajacion() (una fila
        por sesión, cada una normalizada contra el baseline de SU PROPIO día) en los
        2 grupos que compara la Hipótesis de la tesis (H1/H0): "terapéuticas"
        (cualquier condición que no sea "preferencia" — los 3 tipos estandarizados
        sorteados en Día 1/Día 3, ver TIPOS_ESTANDARIZADOS en sesion_completa.py) vs
        "preferencia" (Día 2 y Día 4 — dos canciones distintas, pero UNA sola
        categoría para esta comparación: no importa cuál canción específica, lo que
        se evalúa es "cómo reacciona ante su música preferida").

        Promedia las métricas de cada sesión DENTRO de su grupo. Solo
        score_relajacion está normalizado contra el baseline de cada sesión
        (fracción relativa al propio reposo, así que promediarlo entre sesiones
        es válido). hr_media, sdnn, rmssd y respiraciones_min quedan en valores
        CRUDOS (bpm, ms): su promedio por grupo es descriptivo para la tarjeta de
        la app y NO es el contraste de H1/H0, porque mezcla sesiones con
        baselines distintos. El contraste estadístico (ΔFC = FC del estímulo -
        FC del baseline de la misma sesión, prueba pareada entre participantes)
        vive en analisis_intrasujeto.py.

        Args:
            ranking: DataFrame devuelto por calcular_score_relajacion() — una fila
                por sesión/condición, columnas condicion/hr_media/sdnn/rmssd/
                respiraciones_min/score_relajacion.

        Returns:
            dict: {"terapeuticas": {...} | None, "preferencia": {...} | None}.
                Cada sub-dict trae n_sesiones (int) y el promedio de hr_media/sdnn/
                rmssd/respiraciones_min/score_relajacion sobre las sesiones válidas
                de ese grupo. None si ese grupo no tiene ninguna sesión con
                score_relajacion válido todavía (ej. solo se corrió Día 1 hasta
                ahora, sin ningún día de preferencia).
        """
        if ranking.empty:
            return {"terapeuticas": None, "preferencia": None}

        columnas_metricas = ["hr_media", "sdnn", "rmssd", "respiraciones_min", "score_relajacion"]
        validas = ranking[ranking["score_relajacion"].notna()]

        def _resumen(subconjunto: pd.DataFrame) -> Optional[dict]:
            if subconjunto.empty:
                return None
            resumen = {"n_sesiones": int(len(subconjunto))}
            for columna in columnas_metricas:
                resumen[columna] = float(subconjunto[columna].mean(skipna=True))
            return resumen

        grupo_preferencia = validas[validas["condicion"] == "preferencia"]
        grupo_terapeuticas = validas[validas["condicion"] != "preferencia"]

        return {
            "terapeuticas": _resumen(grupo_terapeuticas),
            "preferencia": _resumen(grupo_preferencia),
        }

    def recomendar_para_participante(self, df_sesion: pd.DataFrame, participante_id: str) -> dict:
        """Calcula la recomendación de estímulo para UN participante.

        Args:
            df_sesion: CSV completo de la sesión (timestamp, hr_bpm, rr_ms,
                condicion, estimulo).
            participante_id: Identificador del participante, ej. "P01".

        Returns:
            dict: participante_id, estimulo_recomendado, score_recomendado,
                ranking_completo (DataFrame), justificacion (str).

        Raises:
            ValueError: Si la sesión no tiene condición "reposo" (no hay
                baseline con qué normalizar), o si no queda ninguna
                condición candidata tras aplicar excluir_condiciones.
        """
        metricas = AnalisisGrupal().calcular_metricas_participante(df_sesion)

        fila_baseline = metricas.loc[metricas["condicion"] == "reposo"]
        if fila_baseline.empty:
            raise ValueError(
                f"El participante {participante_id} no tiene condición 'reposo' en su "
                "sesión; no se puede calcular un baseline para normalizar el score."
            )
        baseline_reposo = fila_baseline.iloc[0].to_dict()

        ranking_completo = self.calcular_score_relajacion(metricas, baseline_reposo)

        # Se excluyen candidatos (típicamente "reposo") ANTES de elegir el recomendado:
        # no tiene sentido recomendarle a alguien "quédate en reposo", eso no es una
        # elección entre estímulos, es la ausencia de uno
        candidatos = ranking_completo[~ranking_completo["condicion"].isin(self.excluir_condiciones)]
        if candidatos.empty:
            raise ValueError(
                f"No quedan condiciones candidatas para {participante_id} tras excluir "
                f"{self.excluir_condiciones}."
            )
        mejor = candidatos.iloc[0]  # ya viene ordenado desc por score_relajacion

        hr_baseline = baseline_reposo.get("hr_media", np.nan)
        estado = "más relajado" if mejor["score_relajacion"] > 0 else "más activado"
        justificacion = (
            f"Se recomienda '{mejor['condicion']}' para {participante_id}: HR promedio "
            f"{mejor['hr_media']:.1f} bpm (baseline reposo {hr_baseline:.1f} bpm), "
            f"SDNN {mejor['sdnn']:.1f} ms, RMSSD {mejor['rmssd']:.1f} ms — "
            f"score de relajación {mejor['score_relajacion']:.3f} ({estado} que el reposo basal)."
        )

        return {
            "participante_id": participante_id,
            "estimulo_recomendado": mejor["condicion"],
            "score_recomendado": round(float(mejor["score_relajacion"]), 4),
            "ranking_completo": ranking_completo,
            "justificacion": justificacion,
        }

    def recomendar_para_todos(
        self, carpeta_sesiones: Path, patron_fecha: Optional[str] = None
    ) -> pd.DataFrame:
        """Aplica recomendar_para_participante a todos los CSV que cumplan patron_fecha.

        Args:
            carpeta_sesiones: Carpeta donde buscar los CSV de sesiones.
            patron_fecha: Substring para filtrar por sufijo de fecha/hora
                (ver AnalisisGrupal).

        Returns:
            pd.DataFrame: participante_id, estimulo_recomendado, score,
                hr_baseline, hr_recomendado, diferencia_hr.
        """
        analisis = AnalisisGrupal(carpeta_sesiones=carpeta_sesiones, patron_fecha=patron_fecha)
        sesiones = analisis.cargar_todas_sesiones()

        filas = []
        for participante_id, df_sesion in sesiones.items():
            resultado = self.recomendar_para_participante(df_sesion, participante_id)
            ranking = resultado["ranking_completo"]

            hr_baseline_serie = ranking.loc[ranking["condicion"] == "reposo", "hr_media"]
            hr_baseline = float(hr_baseline_serie.iloc[0]) if not hr_baseline_serie.empty else np.nan

            hr_recomendado_serie = ranking.loc[
                ranking["condicion"] == resultado["estimulo_recomendado"], "hr_media"
            ]
            hr_recomendado = (
                float(hr_recomendado_serie.iloc[0]) if not hr_recomendado_serie.empty else np.nan
            )

            filas.append(
                {
                    "participante_id": participante_id,
                    "estimulo_recomendado": resultado["estimulo_recomendado"],
                    "score": resultado["score_recomendado"],
                    "hr_baseline": round(hr_baseline, 2),
                    "hr_recomendado": round(hr_recomendado, 2),
                    "diferencia_hr": round(hr_recomendado - hr_baseline, 2),
                }
            )

            print(
                f"  {participante_id}: recomendado '{resultado['estimulo_recomendado']}' "
                f"(score={resultado['score_recomendado']:.3f})"
            )

        return pd.DataFrame(filas)

    def reporte_grupal(self, df_recomendaciones: pd.DataFrame) -> dict:
        """Resume el conjunto de recomendaciones a nivel de grupo.

        Args:
            df_recomendaciones: DataFrame devuelto por recomendar_para_todos().

        Returns:
            dict: estimulo_mas_recomendado, distribucion (dict conteo por
                estímulo), efectividad_promedio (diferencia_hr media),
                hay_consenso (bool, True si >50% de los participantes
                recibieron la misma recomendación).
        """
        distribucion = df_recomendaciones["estimulo_recomendado"].value_counts().to_dict()
        estimulo_mas_recomendado = max(distribucion, key=distribucion.get)
        proporcion_mas_recomendado = distribucion[estimulo_mas_recomendado] / len(df_recomendaciones)

        return {
            "estimulo_mas_recomendado": estimulo_mas_recomendado,
            "distribucion": distribucion,
            "efectividad_promedio": round(df_recomendaciones["diferencia_hr"].mean(), 2),
            "hay_consenso": proporcion_mas_recomendado > 0.5,
        }

    def graficar_recomendaciones(
        self, df_recomendaciones: pd.DataFrame, guardar_en: Optional[Path] = None
    ) -> plt.Figure:
        """Genera y guarda una figura de 2 subplots resumiendo las recomendaciones.

        Subplots:
            1. Barras horizontales: cuántos participantes recibieron cada
               estímulo recomendado.
            2. Scatter de diferencia_hr (recomendado - baseline) por
               participante, coloreado por el estímulo recomendado.

        Args:
            df_recomendaciones: DataFrame devuelto por recomendar_para_todos().
            guardar_en: Nombre de archivo o ruta. Si es None, se guarda
                automáticamente en resultados/graficas/ con nombre
                "recomendaciones_{fecha}.png".

        Returns:
            plt.Figure: La figura generada.
        """
        from datetime import datetime

        fig, (ax_barras, ax_scatter) = plt.subplots(1, 2, figsize=(14, 6))

        # --- Subplot 1: distribución de recomendaciones ---
        distribucion = df_recomendaciones["estimulo_recomendado"].value_counts()
        ax_barras.barh(distribucion.index, distribucion.values, color="steelblue")
        ax_barras.invert_yaxis()  # el más recomendado arriba
        ax_barras.set_xlabel("Participantes")
        ax_barras.set_title("Distribución de estímulos recomendados")
        ax_barras.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

        # --- Subplot 2: efectividad (diferencia HR) por participante, coloreado por estímulo ---
        estimulos_unicos = df_recomendaciones["estimulo_recomendado"].unique()
        colores = plt.get_cmap("tab10").colors
        mapa_color = {estimulo: colores[i % len(colores)] for i, estimulo in enumerate(estimulos_unicos)}

        for estimulo in estimulos_unicos:
            subconjunto = df_recomendaciones[df_recomendaciones["estimulo_recomendado"] == estimulo]
            ax_scatter.scatter(
                subconjunto["participante_id"],
                subconjunto["diferencia_hr"],
                label=estimulo,
                color=mapa_color[estimulo],
                s=90,
                edgecolor="black",
            )

        ax_scatter.axhline(0, color="gray", linestyle="--", linewidth=1)
        ax_scatter.set_xlabel("Participante")
        ax_scatter.set_ylabel("Diferencia HR (recomendado − baseline, bpm)")
        ax_scatter.set_title("Efectividad del estímulo recomendado por participante")
        ax_scatter.legend(title="Estímulo", fontsize=8)
        ax_scatter.tick_params(axis="x", rotation=30)

        fig.suptitle("Recomendaciones post-sesión", fontsize=14)
        fig.tight_layout()

        if guardar_en is None:
            fecha = datetime.now().strftime("%Y%m%d_%H%M")
            ruta_destino = CARPETA_GRAFICAS / f"recomendaciones_{fecha}.png"
        else:
            ruta_destino = Path(guardar_en)
            if not ruta_destino.is_absolute():
                ruta_destino = CARPETA_GRAFICAS / ruta_destino

        CARPETA_GRAFICAS.mkdir(parents=True, exist_ok=True)
        fig.savefig(ruta_destino, dpi=300, bbox_inches="tight")
        print(f"Gráfica guardada en: {ruta_destino}")

        return fig


if __name__ == "__main__":
    from analisis_grupal import CARPETA_SESIONES_DEFAULT

    recomendador = Recomendador()

    print("=== Calculando recomendaciones por participante ===")
    df_recomendaciones = recomendador.recomendar_para_todos(
        CARPETA_SESIONES_DEFAULT, patron_fecha="20260812_2047"
    )

    print("\n=== Tabla de recomendaciones ===")
    print(df_recomendaciones.to_string(index=False))

    print("\n=== Reporte grupal ===")
    reporte = recomendador.reporte_grupal(df_recomendaciones)
    for clave, valor in reporte.items():
        print(f"  {clave}: {valor}")

    print("\n=== Generando gráfica de recomendaciones ===")
    recomendador.graficar_recomendaciones(df_recomendaciones)
