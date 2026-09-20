"""Contraste intrasujeto de la Hipótesis (H1/H0): ΔFC con frecuencias terapéuticas
comunes vs. ΔFC con sonidos de preferencia personal.

Hipótesis que contrasta (Capítulo I del documento):
    H1: existen diferencias significativas en el cambio de la frecuencia cardíaca
        media respecto a la línea base entre las sesiones con frecuencias
        terapéuticas comunes (Días 1 y 3) y las sesiones con sonidos de
        preferencia personal (Días 2 y 4), dentro de cada participante.
    H0: no existen tales diferencias.

Definiciones (ver también "Variables y operacionalización" en el Capítulo III):
    ΔFC (bpm) = FC media durante el estímulo (300 s) - FC media de la línea base
                de ESA MISMA sesión (120 s). Negativo = la FC bajó respecto al reposo.
    Dato por participante y condición = media de sus sesiones de esa condición
                (2 terapéuticas, 2 de preferencia).
    Diferencia = ΔFC(preferencia) - ΔFC(terapéutica). Negativa = la preferencia
                bajó MÁS la FC que las frecuencias terapéuticas.

Diseño: intrasujeto (cada participante pasa por ambas condiciones), así que la
comparación es PAREADA. No se usa ANOVA: solo hay 2 condiciones. Ver
comparar_condiciones() para la lógica de elección entre t pareada y Wilcoxon.

¿Por qué no usa Recomendador.comparar_grupos_terapeutica_vs_preferencia()? Ese
método promedia hr_media CRUDA entre sesiones (cada una con baseline distinto);
sirve como detalle por participante en la app, pero no contrasta H1/H0. Este
módulo lee directamente las tablas 'sesiones' y 'pruebas' de SQL Server (no los
CSV, que son uno por sesión y no sirven para agregar a varios participantes).

Uso:
    python analisis/analisis_intrasujeto.py                      # datos reales (SQL Server)
    python analisis/analisis_intrasujeto.py --simulado           # datos sintéticos de prueba
    python analisis/analisis_intrasujeto.py --excluir P001 P002  # p. ej., sesiones piloto
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

CARPETA_GRAFICAS = Path(r"C:\Tesis_Kevin\resultados\graficas")
CARPETA_EXPORTADOS = Path(r"C:\Tesis_Kevin\resultados\exportados")

ALFA = 0.05
SESIONES_POR_CONDICION = 2  # protocolo: 2 terapéuticas (Días 1 y 3) + 2 de preferencia (Días 2 y 4)

METRICA_PRIMARIA = "delta_fc"
METRICAS_SECUNDARIAS = ["delta_rmssd", "delta_sdnn", "likert_relajacion", "likert_confort"]
ETIQUETAS_METRICAS = {
    "delta_fc": "ΔFC (bpm)",
    "delta_rmssd": "ΔRMSSD (ms)",
    "delta_sdnn": "ΔSDNN (ms)",
    "likert_relajacion": "Likert relajación (1-5)",
    "likert_confort": "Likert confort (1-5)",
}


# ---------------------------------------------------------------------------
# Preparación de datos
# ---------------------------------------------------------------------------
def preparar_sesiones(
    sesiones: pd.DataFrame,
    pruebas: pd.DataFrame,
    solo_validas: bool = True,
    excluir_participantes: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Une 'sesiones' y 'pruebas' y calcula los cambios respecto a la línea base.

    Cada fila del resultado es una prueba (un bloque de estímulo) con su
    baseline de la sesión a la que pertenece. Nunca se mezclan baselines de
    sesiones distintas: el reposo puede variar de un día a otro.

    Args:
        sesiones: Tabla 'sesiones' (id_sesion, id_participante, fecha_hora,
            hr_baseline, rmssd_baseline, sdnn_baseline y, si la base ya fue
            migrada, dia_sesion y valida).
        pruebas: Tabla 'pruebas' (id_sesion, tipo_estimulo, hr_promedio,
            rmssd, sdnn, likert_relajacion, likert_confort).
        solo_validas: Si True y existe la columna 'valida', descarta las
            sesiones marcadas como inválidas (valida = 0).
        excluir_participantes: IDs a dejar fuera (p. ej. sesiones piloto).

    Returns:
        pd.DataFrame: Columnas id_participante, id_sesion, dia_sesion,
            condicion ("terapeutica" | "preferencia"), tipo_estimulo,
            delta_fc, delta_rmssd, delta_sdnn, likert_relajacion, likert_confort.
    """
    columnas = [
        "id_participante", "id_sesion", "dia_sesion", "condicion", "tipo_estimulo",
        "delta_fc", "delta_rmssd", "delta_sdnn", "likert_relajacion", "likert_confort",
    ]
    if sesiones.empty or pruebas.empty:  # base recién limpia: sin columnas que consultar
        return pd.DataFrame(columns=columnas)

    ses = sesiones.copy()
    pru = pruebas.copy()

    if solo_validas and "valida" in ses.columns:
        ses = ses[ses["valida"].fillna(True).astype(bool)]
    if excluir_participantes:
        ses = ses[~ses["id_participante"].isin(excluir_participantes)]

    # Día de la sesión: el registrado si existe; si no (base sin migrar o sesiones
    # antiguas), el orden cronológico de las sesiones de ese participante.
    ses = ses.sort_values("fecha_hora")
    orden = ses.groupby("id_participante").cumcount() + 1
    if "dia_sesion" in ses.columns:
        ses["dia_sesion"] = ses["dia_sesion"].fillna(orden)
    else:
        ses["dia_sesion"] = orden

    pru = pru.drop(columns=[c for c in ("id_participante", "fecha_hora", "duracion_seg") if c in pru.columns])
    for columna in ("likert_relajacion", "likert_confort"):
        if columna not in pru.columns:
            pru[columna] = np.nan

    datos = ses.merge(pru, on="id_sesion", how="inner")
    datos["condicion"] = np.where(datos["tipo_estimulo"] == "preferencia", "preferencia", "terapeutica")
    datos["delta_fc"] = datos["hr_promedio"] - datos["hr_baseline"]
    datos["delta_rmssd"] = datos["rmssd"] - datos["rmssd_baseline"]
    datos["delta_sdnn"] = datos["sdnn"] - datos["sdnn_baseline"]

    return datos[columnas].sort_values(["id_participante", "dia_sesion"]).reset_index(drop=True)


def tabla_por_participante(
    datos: pd.DataFrame, metrica: str, min_sesiones: int = SESIONES_POR_CONDICION
) -> tuple[pd.DataFrame, list[str]]:
    """Arma la tabla maestra: una fila por participante con su media en cada condición.

    Args:
        datos: Salida de preparar_sesiones().
        metrica: Columna a promediar (p. ej. "delta_fc").
        min_sesiones: Sesiones válidas mínimas con dato en CADA condición para
            incluir al participante (default 2, el protocolo completo). Quien no
            llegue queda fuera del contraste y se reporta aparte.

    Returns:
        tuple[pd.DataFrame, list[str]]: (tabla con índice id_participante y
            columnas terapeutica, preferencia, n_terapeutica, n_preferencia;
            lista de participantes excluidos por datos incompletos).
    """
    validos = datos.dropna(subset=[metrica])
    agregado = validos.groupby(["id_participante", "condicion"])[metrica].agg(["mean", "count"]).unstack("condicion")

    tabla = pd.DataFrame(index=sorted(datos["id_participante"].unique()))
    for condicion in ("terapeutica", "preferencia"):
        if ("mean", condicion) in agregado.columns:
            tabla[condicion] = agregado[("mean", condicion)]
            tabla[f"n_{condicion}"] = agregado[("count", condicion)]
        else:
            tabla[condicion] = np.nan
            tabla[f"n_{condicion}"] = 0
    tabla[["n_terapeutica", "n_preferencia"]] = tabla[["n_terapeutica", "n_preferencia"]].fillna(0).astype(int)
    tabla.index.name = "id_participante"

    completo = (tabla["n_terapeutica"] >= min_sesiones) & (tabla["n_preferencia"] >= min_sesiones)
    excluidos = list(tabla.index[~completo])
    return tabla[completo], excluidos


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------
def comparar_condiciones(
    tabla: pd.DataFrame, alfa: float = ALFA, prueba: str = "auto"
) -> dict:
    """Contrasta preferencia vs. terapéutica con pruebas PAREADAS.

    Se calculan siempre ambas pruebas (t pareada y Wilcoxon de rangos con signo)
    y Shapiro-Wilk sobre las diferencias. La prueba "principal" es la que se
    declara a priori:
        "auto":       t pareada si Shapiro-Wilk no rechaza normalidad de las
                      diferencias (p >= alfa); si la rechaza, Wilcoxon.
        "wilcoxon":   siempre Wilcoxon (más segura con N pequeño).
        "t_pareada":  siempre t pareada.

    Tamaño del efecto: d de Cohen pareado (dz = media de diferencias / DE de las
    diferencias) y correlación biserial por rangos (r_rb, asociada a Wilcoxon).

    Args:
        tabla: Salida de tabla_por_participante() (columnas terapeutica y preferencia).
        alfa: Nivel de significancia (default 0.05).
        prueba: "auto", "wilcoxon" o "t_pareada".

    Returns:
        dict: n, media_terapeutica, media_preferencia, diferencia_media
            (preferencia - terapéutica), ic95 (tuple), sd_diferencias, dz, r_rb,
            shapiro_p, normal, t, p_t, w, p_wilcoxon, prueba_principal, p_principal,
            significativo, diferencias (np.ndarray).

    Raises:
        ValueError: Si hay menos de 3 participantes con ambas condiciones
            (Shapiro-Wilk no se puede calcular) o si 'prueba' no es válida.
    """
    if prueba not in ("auto", "wilcoxon", "t_pareada"):
        raise ValueError(f"prueba '{prueba}' no válida; usar 'auto', 'wilcoxon' o 't_pareada'.")

    datos = tabla[["terapeutica", "preferencia"]].dropna()
    n = len(datos)
    if n < 3:
        raise ValueError(f"Se necesitan al menos 3 participantes con ambas condiciones; hay {n}.")

    ter = datos["terapeutica"].to_numpy(dtype=float)
    pref = datos["preferencia"].to_numpy(dtype=float)
    dif = pref - ter

    media = float(dif.mean())
    sd = float(dif.std(ddof=1))
    error_estandar = sd / np.sqrt(n)
    t_critico = stats.t.ppf(1 - alfa / 2, n - 1)
    ic95 = (media - t_critico * error_estandar, media + t_critico * error_estandar)
    dz = media / sd if sd > 0 else float("nan")

    # Todas las diferencias iguales (sd == 0) hacen que Shapiro/t no estén definidas.
    if sd > 0:
        shapiro_p = float(stats.shapiro(dif).pvalue)
        t_estadistico, p_t = stats.ttest_rel(pref, ter)
        t_estadistico, p_t = float(t_estadistico), float(p_t)
    else:
        shapiro_p, t_estadistico, p_t = float("nan"), float("nan"), float("nan")

    distintas_de_cero = dif[dif != 0]
    if len(distintas_de_cero) > 0:
        wilcoxon = stats.wilcoxon(dif, zero_method="wilcox", alternative="two-sided")
        w, p_wilcoxon = float(wilcoxon.statistic), float(wilcoxon.pvalue)
        rangos = stats.rankdata(np.abs(distintas_de_cero))
        suma_pos = rangos[distintas_de_cero > 0].sum()
        suma_neg = rangos[distintas_de_cero < 0].sum()
        r_rb = float((suma_pos - suma_neg) / (suma_pos + suma_neg))
    else:
        w, p_wilcoxon, r_rb = float("nan"), float("nan"), float("nan")

    normal = bool(shapiro_p >= alfa) if not np.isnan(shapiro_p) else False
    if prueba == "auto":
        prueba_principal = "t_pareada" if normal else "wilcoxon"
    else:
        prueba_principal = prueba
    p_principal = p_t if prueba_principal == "t_pareada" else p_wilcoxon

    return {
        "n": n,
        "media_terapeutica": float(ter.mean()),
        "media_preferencia": float(pref.mean()),
        "diferencia_media": media,
        "ic95": ic95,
        "sd_diferencias": sd,
        "dz": dz,
        "r_rb": r_rb,
        "shapiro_p": shapiro_p,
        "normal": normal,
        "t": t_estadistico,
        "p_t": p_t,
        "w": w,
        "p_wilcoxon": p_wilcoxon,
        "prueba_principal": prueba_principal,
        "p_principal": p_principal,
        "significativo": bool(p_principal < alfa) if not np.isnan(p_principal) else False,
        "diferencias": dif,
    }


def corregir_holm(p_valores: dict[str, float]) -> dict[str, float]:
    """Corrección de Holm (step-down) para una familia de comparaciones.

    Args:
        p_valores: {nombre_de_métrica: p sin corregir}. Los NaN se ignoran y se
            devuelven como NaN.

    Returns:
        dict[str, float]: {nombre_de_métrica: p ajustado}, en el mismo orden de
            entrada.
    """
    validos = {k: v for k, v in p_valores.items() if not np.isnan(v)}
    ordenados = sorted(validos.items(), key=lambda kv: kv[1])
    m = len(ordenados)
    ajustados: dict[str, float] = {}
    maximo_previo = 0.0
    for posicion, (nombre, p) in enumerate(ordenados):
        ajustado = min(1.0, (m - posicion) * p)
        maximo_previo = max(maximo_previo, ajustado)  # monotonía: nunca baja respecto al anterior
        ajustados[nombre] = maximo_previo
    return {k: ajustados.get(k, float("nan")) for k in p_valores}


def analisis_completo(
    datos: pd.DataFrame,
    min_sesiones: int = SESIONES_POR_CONDICION,
    prueba: str = "auto",
    alfa: float = ALFA,
) -> dict:
    """Contraste principal (ΔFC) + métricas secundarias con corrección de Holm.

    Solo ΔFC responde H1/H0. Las secundarias (ΔRMSSD, ΔSDNN, Likert) son
    exploratorias y se corrigen entre sí con Holm; ΔFC se reporta sin corregir
    por ser la única hipótesis confirmatoria.

    Args:
        datos: Salida de preparar_sesiones().
        min_sesiones: Sesiones mínimas por condición para incluir a un participante.
        prueba: "auto", "wilcoxon" o "t_pareada" (ver comparar_condiciones()).
        alfa: Nivel de significancia.

    Returns:
        dict: "primaria" (resultado de comparar_condiciones para ΔFC),
            "secundarias" ({métrica: resultado + p_holm}), "tablas"
            ({métrica: tabla por participante}), "excluidos" (participantes sin
            las sesiones mínimas en ΔFC), "n_participantes_total" (int).

    Raises:
        ValueError: Si no hay suficientes participantes completos para ΔFC.
    """
    tablas: dict[str, pd.DataFrame] = {}
    tabla_fc, excluidos = tabla_por_participante(datos, METRICA_PRIMARIA, min_sesiones)
    tablas[METRICA_PRIMARIA] = tabla_fc
    primaria = comparar_condiciones(tabla_fc, alfa, prueba)

    secundarias: dict[str, dict] = {}
    for metrica in METRICAS_SECUNDARIAS:
        tabla, _ = tabla_por_participante(datos, metrica, min_sesiones)
        tablas[metrica] = tabla
        try:
            secundarias[metrica] = comparar_condiciones(tabla, alfa, prueba)
        except ValueError:
            continue  # métrica sin datos suficientes (p. ej. Likert aún sin capturar)

    ajustados = corregir_holm({m: r["p_principal"] for m, r in secundarias.items()})
    for metrica, p_holm in ajustados.items():
        secundarias[metrica]["p_holm"] = p_holm

    return {
        "primaria": primaria,
        "secundarias": secundarias,
        "tablas": tablas,
        "excluidos": excluidos,
        "n_participantes_total": int(datos["id_participante"].nunique()),
    }


# ---------------------------------------------------------------------------
# Reporte y gráfica
# ---------------------------------------------------------------------------
def _fmt_p(p: float) -> str:
    """Formatea un valor p (NaN -> 'n/d', muy chico -> '<0.001')."""
    if np.isnan(p):
        return "n/d"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def interpretar_primaria(res: dict, alfa: float = ALFA) -> str:
    """Frase de resultado para ΔFC, con la advertencia de no confundir 'sin diferencia' con 'equivalentes'.

    Args:
        res: Resultado de comparar_condiciones() para ΔFC.
        alfa: Nivel de significancia usado.

    Returns:
        str: Interpretación en español lista para pegar en el borrador del Capítulo IV.
    """
    dif = res["diferencia_media"]
    ic_bajo, ic_alto = res["ic95"]
    resumen = (
        f"Diferencia media de ΔFC (preferencia - terapéutica) = {dif:+.2f} bpm, "
        f"IC 95 % [{ic_bajo:+.2f}, {ic_alto:+.2f}], "
        f"p = {_fmt_p(res['p_principal'])} ({'t pareada' if res['prueba_principal'] == 't_pareada' else 'Wilcoxon'}), "
        f"dz = {res['dz']:.2f}, n = {res['n']}."
    )
    if res["significativo"]:
        mayor = "preferencia personal" if dif < 0 else "frecuencias terapéuticas"
        return (
            f"{resumen} Se rechaza H0: la FC descendió más con {mayor} "
            f"(mayor descenso respecto a la línea base)."
        )
    return (
        f"{resumen} No se rechaza H0 (p ≥ {alfa}): no se detectó diferencia entre "
        "condiciones. Esto NO demuestra que sean equivalentes; solo que con este n no "
        "se observó una diferencia. El IC 95 % indica el rango de diferencias compatibles con los datos."
    )


def formatear_reporte(resultado: dict) -> str:
    """Arma el reporte de texto completo para consola.

    Args:
        resultado: Salida de analisis_completo().

    Returns:
        str: Reporte multilínea.
    """
    p = resultado["primaria"]
    lineas = [
        "=" * 72,
        "CONTRASTE INTRASUJETO H1/H0 — ΔFC terapéutica vs. preferencia",
        "=" * 72,
        f"Participantes con datos: {resultado['n_participantes_total']} | incluidos en el contraste: {p['n']}",
    ]
    if resultado["excluidos"]:
        lineas.append(f"Excluidos por sesiones incompletas: {', '.join(resultado['excluidos'])}")
    lineas += [
        "",
        f"ΔFC media terapéutica : {p['media_terapeutica']:+.2f} bpm",
        f"ΔFC media preferencia : {p['media_preferencia']:+.2f} bpm",
        f"Shapiro-Wilk (diferencias): p = {_fmt_p(p['shapiro_p'])} -> "
        f"{'normales' if p['normal'] else 'NO normales'}",
        f"t pareada: t = {p['t']:.3f}, p = {_fmt_p(p['p_t'])}",
        f"Wilcoxon : W = {p['w']:.1f}, p = {_fmt_p(p['p_wilcoxon'])}, r_rb = {p['r_rb']:+.2f}",
        "",
        interpretar_primaria(p),
    ]
    if resultado["secundarias"]:
        lineas += ["", "Métricas secundarias (exploratorias, corrección de Holm):",
                   f"{'métrica':<26}{'n':>3}{'dif. media':>12}{'p':>9}{'p Holm':>9}"]
        for metrica, r in resultado["secundarias"].items():
            lineas.append(
                f"{ETIQUETAS_METRICAS[metrica]:<26}{r['n']:>3}{r['diferencia_media']:>+12.2f}"
                f"{_fmt_p(r['p_principal']):>9}{_fmt_p(r['p_holm']):>9}"
            )
    return "\n".join(lineas)


def graficar_pares(resultado: dict, ruta: Path) -> Path:
    """Gráfica de pares: una línea por participante, de su ΔFC terapéutica a su ΔFC de preferencia.

    Args:
        resultado: Salida de analisis_completo().
        ruta: Archivo PNG de salida.

    Returns:
        Path: Ruta del PNG guardado.
    """
    plt.switch_backend("Agg")  # sin ventana: se guarda directo a archivo
    tabla = resultado["tablas"][METRICA_PRIMARIA][["terapeutica", "preferencia"]].dropna()
    p = resultado["primaria"]

    figura, eje = plt.subplots(figsize=(5.5, 5))
    for _, fila in tabla.iterrows():
        eje.plot([0, 1], [fila["terapeutica"], fila["preferencia"]], color="#9aa5b1", marker="o", linewidth=1, markersize=4)
    eje.plot([0, 1], [p["media_terapeutica"], p["media_preferencia"]], color="#c0392b", marker="D", linewidth=2.5, label="Media")
    eje.axhline(0, color="black", linewidth=0.8, linestyle="--")
    eje.set_xticks([0, 1])
    eje.set_xticklabels(["Terapéutica\n(Días 1 y 3)", "Preferencia\n(Días 2 y 4)"])
    eje.set_ylabel("ΔFC respecto a la línea base (bpm)")
    eje.set_title(f"ΔFC por participante (n = {p['n']}), p = {_fmt_p(p['p_principal'])}")
    eje.legend()
    figura.tight_layout()

    ruta.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(ruta, dpi=200)
    plt.close(figura)
    return ruta


# ---------------------------------------------------------------------------
# Origen de los datos
# ---------------------------------------------------------------------------
def cargar_desde_sql() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee las tablas 'sesiones' y 'pruebas' de SQL Server.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: (sesiones, pruebas).

    Raises:
        ConnectionError: Si no se puede conectar a SQL Server.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "database"))
    from bd_sqlserver import BaseDatosTesis  # noqa: E402

    bd = BaseDatosTesis()
    if not bd.conectar():
        raise ConnectionError("No se pudo conectar a SQL Server — revisa el contenedor Docker y C:\\Tesis_Kevin\\.env.")
    try:
        sesiones = pd.DataFrame(bd.ejecutar_query("SELECT * FROM sesiones") or [])
        pruebas = pd.DataFrame(bd.ejecutar_query("SELECT * FROM pruebas") or [])
    finally:
        bd.desconectar()
    return sesiones, pruebas


def generar_datos_simulados(
    n_participantes: int = 18,
    efecto_bpm: float = 0.0,
    semilla: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Genera datos sintéticos con el MISMO esquema que las tablas de SQL Server.

    Solo para probar el pipeline: cada participante tiene 4 sesiones (Días 1 a 4),
    baseline propio, un ΔFC terapéutico medio de -2 bpm y un efecto adicional de
    'efecto_bpm' en las sesiones de preferencia. NO son datos reales.

    Args:
        n_participantes: Cantidad de participantes simulados.
        efecto_bpm: Cambio extra de ΔFC en preferencia frente a terapéutica
            (negativo = la preferencia baja más la FC; 0 = sin efecto real).
        semilla: Semilla del generador (resultados reproducibles).

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: (sesiones, pruebas).
    """
    rng = np.random.default_rng(semilla)
    tipos = ["binaural_theta", "solfeggio_isocronico", "paisaje"]
    filas_sesion, filas_prueba = [], []
    id_sesion = 0
    for i in range(1, n_participantes + 1):
        pid = f"P{i:03d}"
        base_persona = rng.normal(72, 8)
        sensibilidad = rng.normal(0, 1.5)  # cuánto responde esta persona en general
        for dia in (1, 2, 3, 4):
            id_sesion += 1
            es_preferencia = dia in (2, 4)
            baseline = base_persona + rng.normal(0, 2)
            delta = -2.0 + sensibilidad + (efecto_bpm if es_preferencia else 0.0) + rng.normal(0, 1.5)
            filas_sesion.append({
                "id_sesion": id_sesion, "id_participante": pid,
                "fecha_hora": pd.Timestamp("2026-09-01") + pd.Timedelta(days=dia + i * 5),
                "hr_baseline": baseline, "rmssd_baseline": rng.normal(45, 8), "sdnn_baseline": rng.normal(55, 9),
                "dia_sesion": dia, "valida": True,
            })
            filas_prueba.append({
                "id_sesion": id_sesion, "id_participante": pid,
                "tipo_estimulo": "preferencia" if es_preferencia else tipos[(i + dia) % 3],
                "hr_promedio": baseline + delta,
                "rmssd": rng.normal(48, 8), "sdnn": rng.normal(57, 9),
                "likert_relajacion": int(np.clip(round(rng.normal(3.6, 0.9)), 1, 5)),
                "likert_confort": int(np.clip(round(rng.normal(3.8, 0.9)), 1, 5)),
            })
    return pd.DataFrame(filas_sesion), pd.DataFrame(filas_prueba)


def main() -> None:
    """Punto de entrada por línea de comandos (ver docstring del módulo)."""
    parser = argparse.ArgumentParser(description="Contraste intrasujeto ΔFC terapéutica vs. preferencia.")
    parser.add_argument("--simulado", action="store_true", help="usa datos sintéticos en vez de SQL Server")
    parser.add_argument("--efecto", type=float, default=-3.0, help="efecto simulado de preferencia en bpm (solo con --simulado)")
    parser.add_argument("--excluir", nargs="*", default=[], help="IDs de participantes a excluir (p. ej. pilotos)")
    parser.add_argument("--prueba", choices=["auto", "wilcoxon", "t_pareada"], default="auto")
    parser.add_argument("--min-sesiones", type=int, default=SESIONES_POR_CONDICION, help="sesiones válidas mínimas por condición")
    argumentos = parser.parse_args()

    if argumentos.simulado:
        sesiones, pruebas = generar_datos_simulados(efecto_bpm=argumentos.efecto)
        print(f"[DATOS SIMULADOS — efecto de preferencia {argumentos.efecto:+.1f} bpm; NO usar en la tesis]")
    else:
        sesiones, pruebas = cargar_desde_sql()

    datos = preparar_sesiones(sesiones, pruebas, excluir_participantes=argumentos.excluir)
    try:
        resultado = analisis_completo(datos, min_sesiones=argumentos.min_sesiones, prueba=argumentos.prueba)
    except ValueError as error:
        resumen = datos.groupby(["id_participante", "condicion"]).size().unstack(fill_value=0)
        print(f"Todavía no hay datos suficientes para el contraste: {error}")
        print(f"Sesiones con estímulo por participante y condición (mínimo {argumentos.min_sesiones} de cada una):")
        print(resumen.to_string() if not resumen.empty else "  (sin sesiones registradas)")
        return
    print(formatear_reporte(resultado))

    sufijo = "simulado" if argumentos.simulado else "real"
    CARPETA_EXPORTADOS.mkdir(parents=True, exist_ok=True)
    ruta_csv = CARPETA_EXPORTADOS / f"tabla_maestra_dfc_{sufijo}.csv"
    resultado["tablas"][METRICA_PRIMARIA].to_csv(ruta_csv, encoding="utf-8-sig")
    ruta_png = graficar_pares(resultado, CARPETA_GRAFICAS / f"dfc_pares_{sufijo}.png")
    print(f"\nTabla maestra: {ruta_csv}\nGráfica: {ruta_png}")


if __name__ == "__main__":
    main()
