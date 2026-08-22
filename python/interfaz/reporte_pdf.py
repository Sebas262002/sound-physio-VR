"""Reporte PDF de participante — nivel publicación académica.

Rediseño completo del reporte que antes vivía inline en
AppInvestigador._generar_reporte_pdf() (ese memo con datos sueltos y
gráficos apilados). Vive en su propio módulo porque no tiene nada que ver
con la construcción de la UI de Flet — es render puro a partir de datos ya
guardados en SQL Server.

FUENTE DE DATOS: exclusivamente SQL Server (BaseDatosTesis), igual que la
versión anterior — así el reporte también sirve para participantes
capturados solo por la app (sin CSV asociado). Consecuencia real de esto:
la tabla "pruebas" guarda AGREGADOS por bloque (hr_promedio, hr_min, hr_max,
sdnn, rmssd, ...), no una serie de tiempo continua — el "HR en el tiempo"
de la Página 2 es, honestamente, "HR promedio por bloque en orden
cronológico" (baseline + 4 estímulos), no un trazo continuo segundo a
segundo (eso solo existe en el CSV crudo de la sesión, que este reporte
deliberadamente no depende). Se documenta acá para que quede claro que es
una decisión de diseño consciente, no un dato que falta por descuido.

REUTILIZA, no reinventa:
    - El score de relajación y el ranking salen de
      Recomendador.calcular_score_relajacion() (ver analisis/recomendador.py)
      — misma fórmula que ya usa la pestaña "Recomendación" de la app.
    - La paleta de colores sale de design_system.py — la misma que usa
      toda la interfaz Flet (Colors.PRIMARY, etc. son strings hex simples,
      compatibles tal cual con reportlab.colors.HexColor() y con
      matplotlib color=).

LIMITACIÓN REAL DE REPORTLAB encontrada armando esto (ver _grafico_*
más abajo y la tabla de ranking): las fuentes base-14 (Helvetica) NO
traen glifos de emoji a color — un 🥇 se dibuja como un cuadrado negro
sólido (glifo .notdef), confirmado generando un PDF de prueba y
leyéndolo. Por eso el ranking usa badges de texto con fondo de color
("1º LUGAR" sobre fondo dorado) en vez de medallas emoji. Flechas simples
(↓ ↑) y símbolos comunes (★) sí funcionan bien con Helvetica.
"""

import re
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from PIL import Image as ImagenPIL

from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Tesis_Kevin\python\analisis")

from design_system import Colors  # noqa: E402
from recomendador import Recomendador  # noqa: E402

# ============================================================================
# Constantes — nada hardcodeado más abajo, todo sale de acá.
# ============================================================================

CARPETA_EXPORTS_DEFAULT = Path(r"C:\Tesis_Kevin\resultados\exportados")
UNIVERSIDAD = "Universidad de las Fuerzas Armadas ESPE"
INVESTIGADOR = "Kevin Sebastián Lechón Churuchumbi"
TITULO_SISTEMA = "Sistema Adaptativo de Frecuencias Terapéuticas y Preferencias Sonoras"

# Colores exclusivos de este reporte (medallero) — no forman parte de la
# paleta "Neural Wellness" de la app (esa no tiene tonos oro/plata/bronce,
# no hace falta para ninguna vista de Flet), así que se definen acá.
_ORO = "#D4AF37"
_PLATA = "#9CA3AF"
_BRONCE = "#B08D57"

_GENERO_LEGIBLE = {"M": "Masculino", "F": "Femenino", "O": "Otro", "N": "Prefiere no decir"}
_MANO_LEGIBLE = {"D": "Diestra", "I": "Zurda"}

_ORDEN_ESTIMULO = ["solfeggio", "binaural", "isocronico", "preferencia"]
_ETIQUETAS_ESTIMULO = {
    "solfeggio": "Solfeggio 528Hz",
    "binaural": "Binaural Alpha",
    "isocronico": "Isocrónico Alpha",
    "preferencia": "Preferencia personal",
}
_COLOR_POR_ESTIMULO = {
    "baseline": Colors.TEXT_SECONDARY,
    "solfeggio": Colors.PRIMARY,
    "binaural": Colors.SECONDARY,
    "isocronico": Colors.ACCENT,
    "preferencia": Colors.SUCCESS,
}
_PREFERENCIA_LEGIBLE = {
    "no_me_gusto": "No le gustó",
    "neutral": "Neutral",
    "me_gusta": "Le gustó",
    "me_gusta_mucho": "Le gustó mucho",
}
_PREFERENCIA_NUMERICA = {"no_me_gusto": 1, "neutral": 2, "me_gusta": 3, "me_gusta_mucho": 4}

_DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip

# Tipografía (pt) — ver docstring del pedido original para la jerarquía exacta.
PT_TITULO = 24
PT_SUBTITULO = 16
PT_CUERPO = 10
PT_ETIQUETA = 8
PT_KPI = 20
PT_NOTA = 7

_MARGEN_VERTICAL = 2.0 * cm
_MARGEN_HORIZONTAL = 1.5 * cm


def _fecha_larga_es(fecha: datetime) -> str:
    """"Jueves, 20 de agosto de 2026" — sin depender del locale del sistema."""
    return f"{_DIAS_ES[fecha.weekday()]}, {fecha.day} de {_MESES_ES[fecha.month - 1]} de {fecha.year}"


def _limites_eje_y(valores: list, colchon: float = 0.3, piso_minimo: float = 0.0) -> tuple:
    """(min, max) de eje Y con margen — evita el bug de "todas las barras se ven
    iguales" cuando arrancan en 0 (ver la misma función en app_investigador.py,
    duplicada acá a propósito para que este módulo no dependa de la clase Flet)."""
    if not valores:
        return (0.0, 100.0)
    minimo, maximo = min(valores), max(valores)
    rango = maximo - minimo
    if rango < 1e-6:
        rango = max(abs(maximo) * 0.1, 1.0)
    margen = rango * colchon
    return (max(piso_minimo, minimo - margen), maximo + margen)


def _ajustar_dimensiones(ruta_imagen, ancho_max: float, alto_max: float) -> tuple:
    """(ancho, alto) tipo "contain" que preserva la proporción real de la imagen."""
    with ImagenPIL.open(ruta_imagen) as imagen:
        ancho_px, alto_px = imagen.size
    proporcion = ancho_px / alto_px
    ancho, alto = ancho_max, ancho_max / proporcion
    if alto > alto_max:
        alto = alto_max
        ancho = alto_max * proporcion
    return ancho, alto


def _estilo_matplotlib() -> None:
    """Aplica el look consistente pedido: seaborn-v0_8-whitegrid, DejaVu Sans
    (el equivalente de Inter que trae matplotlib de fábrica, sin depender de
    que Inter esté instalado como fuente del sistema), sin ejes gruesos."""
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams["axes.edgecolor"] = Colors.BORDER
    plt.rcParams["axes.linewidth"] = 0.8
    plt.rcParams["grid.color"] = Colors.BORDER
    plt.rcParams["grid.linewidth"] = 0.6
    plt.rcParams["text.color"] = Colors.TEXT_PRIMARY
    plt.rcParams["axes.labelcolor"] = Colors.TEXT_SECONDARY
    plt.rcParams["xtick.color"] = Colors.TEXT_SECONDARY
    plt.rcParams["ytick.color"] = Colors.TEXT_SECONDARY


def _figura_a_buffer(fig) -> BytesIO:
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=200, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
    buffer.seek(0)
    return buffer


# ============================================================================
# Cálculo de métricas derivadas — reusa Recomendador, no reinventa la fórmula.
# ============================================================================


def _calcular_ranking(pruebas: list[dict], sesion: dict) -> pd.DataFrame:
    """Arma el ranking de score_relajacion — MISMO patrón que ya usa
    AppInvestigador._tab_recomendacion() en la app (ver "calcular()" ahí):
    una fila por tipo_estimulo con hr_media/sdnn/rmssd/respiraciones_min,
    normalizada contra el baseline de la sesión.

    Returns:
        pd.DataFrame: condicion, hr_media, sdnn, rmssd, respiraciones_min,
            score_relajacion — vacío si no hay pruebas.
    """
    if not pruebas:
        return pd.DataFrame()
    tabla = pd.DataFrame(
        [
            {
                "condicion": p["tipo_estimulo"],
                "hr_media": p.get("hr_promedio"),
                "sdnn": p.get("sdnn"),
                "rmssd": p.get("rmssd"),
                "respiraciones_min": p.get("resp_por_min"),
            }
            for p in pruebas
        ]
    )
    baseline_reposo = {
        "hr_media": sesion.get("hr_baseline"),
        "sdnn": sesion.get("sdnn_baseline"),
        "rmssd": sesion.get("rmssd_baseline"),
        "respiraciones_min": float("nan"),
    }
    return Recomendador().calcular_score_relajacion(tabla, baseline_reposo)


def _generar_insight(ranking: pd.DataFrame, pruebas_por_tipo: dict, sesion: dict) -> str:
    """Texto de interpretación automática — ej. "Este participante mostró mayor
    relajación con Solfeggio 528 Hz, con una reducción de 3.5 bpm respecto al
    baseline. La preferencia subjetiva (5/5) coincidió con la respuesta
    fisiológica." (formato pedido explícitamente).

    "Coincidencia con la preferencia": compara el estímulo con mejor score
    contra el que tuvo el likert_relajacion más alto (no "preferencia" —
    esa columna vino vacía en varias sesiones reales, ver docstring del
    módulo; likert_relajacion es el dato disponible de forma más consistente).
    """
    if ranking.empty or ranking["score_relajacion"].isna().all():
        return (
            "No hay suficientes datos de baseline o de las pruebas para calcular una "
            "interpretación automática de esta sesión."
        )

    mejor = ranking.iloc[0]
    hr_baseline = sesion.get("hr_baseline")
    delta_hr = (mejor["hr_media"] - hr_baseline) if hr_baseline is not None and pd.notna(mejor["hr_media"]) else None
    etiqueta_mejor = _ETIQUETAS_ESTIMULO.get(mejor["condicion"], mejor["condicion"])

    partes = [f"Este participante mostró mayor relajación con {etiqueta_mejor}"]
    if delta_hr is not None:
        direccion = "una reducción" if delta_hr < 0 else "un aumento"
        partes.append(f", con {direccion} de {abs(delta_hr):.1f} bpm respecto al baseline")
    partes.append(".")

    prueba_mejor = pruebas_por_tipo.get(mejor["condicion"])
    if prueba_mejor is not None and prueba_mejor.get("likert_relajacion") is not None:
        likerts = {
            tipo: p.get("likert_relajacion") for tipo, p in pruebas_por_tipo.items() if p.get("likert_relajacion") is not None
        }
        if likerts:
            mas_valorado = max(likerts, key=likerts.get)
            if mas_valorado == mejor["condicion"]:
                partes.append(
                    f" La autoevaluación de relajación ({prueba_mejor['likert_relajacion']}/5) coincidió con la "
                    "respuesta fisiológica: el mismo estímulo fue el mejor calificado y el de mejor score."
                )
            else:
                partes.append(
                    f" La autoevaluación de relajación más alta fue para "
                    f"{_ETIQUETAS_ESTIMULO.get(mas_valorado, mas_valorado)} "
                    f"({likerts[mas_valorado]}/5), lo que no coincide exactamente con la respuesta fisiológica — "
                    "una posible disociación entre percepción subjetiva y activación autonómica."
                )

    return "".join(partes)


def _score_global_0_100(ranking: pd.DataFrame) -> Optional[int]:
    """Traduce el score_relajacion del mejor estímulo (típicamente un valor chico,
    sin cota fija, alrededor de 0) a una escala 0-100 para la portada — puramente
    una ayuda visual de un vistazo, NO una escala psicométrica validada. Centrado
    en 50 (=score 0, "igual que el baseline"); +0.5 de score_relajacion (una
    mejora muy fuerte, ya inusual en la práctica — ver P013: un score de 0.462,
    con SDNN casi el doble del baseline, ya se sintió "alto") mapea a 100. El
    factor anterior (*150) saturaba en 100 con cualquier score moderadamente
    bueno (bug real: P013 daba 100/100 con un score de solo 0.462) — perdía
    toda granularidad para distinguir "bueno" de "excepcional"."""
    if ranking.empty or ranking["score_relajacion"].isna().all():
        return None
    mejor_score = float(ranking.iloc[0]["score_relajacion"])
    return int(round(max(0, min(100, 50 + mejor_score * 100))))


# ============================================================================
# Gráficos (matplotlib, backend Agg, devueltos como BytesIO PNG en memoria)
# ============================================================================


def _grafico_hr_bloques(sesion: dict, pruebas_por_tipo: dict) -> BytesIO:
    """Página 2 — barras de HR en orden cronológico: baseline + los 4 estímulos
    (ver docstring del módulo: SQL Server no guarda una serie de tiempo
    continua, solo agregados por bloque)."""
    import matplotlib.pyplot as plt

    _estilo_matplotlib()

    etiquetas = ["Baseline"] + [_ETIQUETAS_ESTIMULO[t] for t in _ORDEN_ESTIMULO]
    valores = [sesion.get("hr_baseline")]
    colores = [_COLOR_POR_ESTIMULO["baseline"]]
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        valores.append(prueba.get("hr_promedio") if prueba else None)
        colores.append(_COLOR_POR_ESTIMULO[tipo])

    etiquetas_validas = [e for e, v in zip(etiquetas, valores) if v is not None]
    valores_validos = [v for v in valores if v is not None]
    colores_validos = [c for c, v in zip(colores, valores) if v is not None]

    fig, ax = plt.subplots(figsize=(11, 4.6))
    if not valores_validos:
        ax.text(0.5, 0.5, "Sin datos de HR disponibles para esta sesión.", ha="center", va="center", fontsize=11, color=Colors.TEXT_SECONDARY)
        ax.axis("off")
        return _figura_a_buffer(fig)

    y_min, y_max = _limites_eje_y(valores_validos)
    barras = ax.bar(etiquetas_validas, valores_validos, color=colores_validos, width=0.6, zorder=3)
    ax.set_ylim(y_min, y_max)
    for barra, valor in zip(barras, valores_validos):
        ax.text(barra.get_x() + barra.get_width() / 2, valor + (y_max - y_min) * 0.02, f"{valor:.1f}", ha="center", fontsize=9, color=Colors.TEXT_PRIMARY, fontweight="bold")

    if sesion.get("hr_baseline") is not None:
        ax.axhline(sesion["hr_baseline"], color=Colors.TEXT_SECONDARY, linestyle="--", linewidth=1, alpha=0.6, zorder=2, label="Baseline")
        ax.legend(loc="upper right", frameon=False, fontsize=8)

    ax.set_title("Frecuencia cardíaca por bloque (orden cronológico)", loc="left", fontsize=12, fontweight="bold", color=Colors.TEXT_PRIMARY, pad=12)
    ax.set_ylabel("HR (bpm)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return _figura_a_buffer(fig)


def _grafico_comparacion_hr(sesion: dict, pruebas_por_tipo: dict) -> BytesIO:
    """Página 3, gráfico izquierdo — HR por estímulo (sin la barra de baseline,
    solo la línea de referencia), etiquetas con valor exacto, eje Y adaptativo."""
    import matplotlib.pyplot as plt

    _estilo_matplotlib()

    etiquetas, valores, colores = [], [], []
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        if prueba is None or prueba.get("hr_promedio") is None:
            continue
        etiquetas.append(_ETIQUETAS_ESTIMULO[tipo])
        valores.append(prueba["hr_promedio"])
        colores.append(_COLOR_POR_ESTIMULO[tipo])

    fig, ax = plt.subplots(figsize=(8, 5.5))
    if not valores:
        ax.text(0.5, 0.5, "Sin datos de HR por estímulo.", ha="center", va="center", color=Colors.TEXT_SECONDARY)
        ax.axis("off")
        return _figura_a_buffer(fig)

    y_min, y_max = _limites_eje_y(valores)
    barras = ax.bar(etiquetas, valores, color=colores, width=0.55, zorder=3)
    ax.set_ylim(y_min, y_max)
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2, valor + (y_max - y_min) * 0.02, f"{valor:.1f}", ha="center", fontsize=9, fontweight="bold")

    if sesion.get("hr_baseline") is not None:
        ax.axhline(sesion["hr_baseline"], color=Colors.TEXT_SECONDARY, linestyle="--", linewidth=1, alpha=0.7, zorder=2, label=f"Baseline ({sesion['hr_baseline']:.1f})")
        ax.legend(loc="upper right", frameon=False, fontsize=8)

    ax.set_title("HR promedio por estímulo", loc="left", fontsize=12, fontweight="bold", pad=12)
    ax.set_ylabel("HR (bpm)")
    ax.tick_params(axis="x", rotation=15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return _figura_a_buffer(fig)


def _grafico_hrv_comparacion(pruebas_por_tipo: dict) -> BytesIO:
    """Página 3, gráfico derecho — SDNN vs RMSSD por estímulo, barras agrupadas."""
    import matplotlib.pyplot as plt

    _estilo_matplotlib()

    etiquetas, sdnn_vals, rmssd_vals = [], [], []
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        if prueba is None:
            continue
        etiquetas.append(_ETIQUETAS_ESTIMULO[tipo])
        sdnn_vals.append(prueba.get("sdnn") or 0)
        rmssd_vals.append(prueba.get("rmssd") or 0)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    if not etiquetas:
        ax.text(0.5, 0.5, "Sin datos de HRV por estímulo.", ha="center", va="center", color=Colors.TEXT_SECONDARY)
        ax.axis("off")
        return _figura_a_buffer(fig)

    x = np.arange(len(etiquetas))
    ancho = 0.35
    ax.bar(x - ancho / 2, sdnn_vals, ancho, label="SDNN", color=Colors.PRIMARY, zorder=3)
    ax.bar(x + ancho / 2, rmssd_vals, ancho, label="RMSSD", color=Colors.ACCENT, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(etiquetas, rotation=15)
    ax.set_ylabel("ms")
    ax.set_title("Variabilidad (SDNN vs RMSSD) por estímulo", loc="left", fontsize=12, fontweight="bold", pad=12)
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return _figura_a_buffer(fig)


def _grafico_radar(pruebas_por_tipo: dict) -> BytesIO:
    """Página 4 — radar de Relajación / Confort / Preferencia, una capa por
    estímulo. Preferencia se mapea a 1-4 (_PREFERENCIA_NUMERICA); si falta
    (bastante común, ver docstring del módulo), esa capa se dibuja igual con
    ese eje en 0 — no se rompe, no se inventa un valor."""
    import matplotlib.pyplot as plt

    _estilo_matplotlib()

    ejes = ["Relajación", "Confort", "Preferencia"]
    n_ejes = len(ejes)
    angulos = [n / float(n_ejes) * 2 * np.pi for n in range(n_ejes)]
    angulos += angulos[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    hay_datos = False
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        if prueba is None:
            continue
        relajacion = prueba.get("likert_relajacion") or 0
        confort = prueba.get("likert_confort") or 0
        preferencia = _PREFERENCIA_NUMERICA.get(prueba.get("preferencia"), 0)
        if relajacion or confort or preferencia:
            hay_datos = True
        valores = [relajacion, confort, preferencia]
        valores += valores[:1]
        color = _COLOR_POR_ESTIMULO[tipo]
        ax.plot(angulos, valores, color=color, linewidth=2, label=_ETIQUETAS_ESTIMULO[tipo])
        ax.fill(angulos, valores, color=color, alpha=0.12)

    ax.set_xticks(angulos[:-1])
    ax.set_xticklabels(ejes, fontsize=11)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8, color=Colors.TEXT_SECONDARY)
    ax.set_title("Autorreporte por estímulo (escala 1-5)", loc="left", fontsize=12, fontweight="bold", pad=20)
    if hay_datos:
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), frameon=False, fontsize=9)
    fig.tight_layout()
    return _figura_a_buffer(fig)


# ============================================================================
# Reportlab — layout del documento
# ============================================================================


class _Estilos:
    """Junta los ParagraphStyle usados en todo el reporte — un solo lugar."""

    def __init__(self) -> None:
        base = getSampleStyleSheet()
        self.titulo = ParagraphStyle(
            "TituloReporte", parent=base["Title"], fontSize=PT_TITULO, leading=PT_TITULO + 4,
            textColor=rl_colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold",
        )
        self.subtitulo_banner = ParagraphStyle(
            "SubtituloBanner", parent=base["Normal"], fontSize=PT_CUERPO,
            textColor=rl_colors.white, alignment=TA_CENTER,
        )
        self.subtitulo = ParagraphStyle(
            "Subtitulo", parent=base["Heading2"], fontSize=PT_SUBTITULO,
            textColor=rl_colors.HexColor(Colors.TEXT_PRIMARY), fontName="Helvetica-Bold",
            spaceBefore=10, spaceAfter=8,
        )
        self.cuerpo = ParagraphStyle(
            "Cuerpo", parent=base["Normal"], fontSize=PT_CUERPO, leading=PT_CUERPO + 4,
            textColor=rl_colors.HexColor(Colors.TEXT_PRIMARY),
        )
        self.etiqueta = ParagraphStyle(
            "Etiqueta", parent=base["Normal"], fontSize=PT_ETIQUETA,
            textColor=rl_colors.HexColor(Colors.TEXT_SECONDARY), fontName="Helvetica-Bold",
        )
        self.kpi = ParagraphStyle(
            "KPI", parent=base["Normal"], fontSize=PT_KPI, leading=PT_KPI + 2,
            textColor=rl_colors.HexColor(Colors.PRIMARY), fontName="Helvetica-Bold",
        )
        self.nota = ParagraphStyle(
            "Nota", parent=base["Normal"], fontSize=PT_NOTA,
            textColor=rl_colors.HexColor(Colors.TEXT_SECONDARY),
        )
        self.insight = ParagraphStyle(
            "Insight", parent=base["Normal"], fontSize=PT_CUERPO + 1, leading=PT_CUERPO + 7,
            textColor=rl_colors.HexColor(Colors.TEXT_PRIMARY),
        )


def _banner_titulo(estilos: _Estilos, ruta_logo: Optional[Path]) -> Table:
    """Portada: banner de color primary con el título en blanco + logo a la izq."""
    celda_logo = ""
    if ruta_logo is not None and Path(ruta_logo).exists():
        try:
            ancho_logo, alto_logo = _ajustar_dimensiones(ruta_logo, ancho_max=3.6 * cm, alto_max=1.8 * cm)
            celda_logo = Image(str(ruta_logo), width=ancho_logo, height=alto_logo)
        except Exception:
            celda_logo = ""

    contenido_titulo = [
        Paragraph("REPORTE DE PARTICIPANTE", estilos.titulo),
        Spacer(1, 0.15 * cm),
        Paragraph(TITULO_SISTEMA, estilos.subtitulo_banner),
    ]
    tabla = Table([[celda_logo, contenido_titulo]], colWidths=[4 * cm, None])
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(Colors.PRIMARY)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ("LEFTPADDING", (0, 0), (0, 0), 14),
            ]
        )
    )
    return tabla


def _tarjeta_dato(etiqueta: str, valor: str, estilos: _Estilos) -> Table:
    """Una celda de la grilla 2x2 de datos del participante — fondo BG_MAIN,
    etiqueta chica mayúscula arriba, valor grande abajo."""
    contenido = Table(
        [[Paragraph(etiqueta.upper(), estilos.etiqueta)], [Paragraph(valor, estilos.kpi)]],
        colWidths=[8.2 * cm],
    )
    contenido.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(Colors.BG_MAIN)),
                ("BOX", (0, 0), (-1, -1), 0.75, rl_colors.HexColor(Colors.BORDER)),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return contenido


def _grilla_participante(participante: dict, sesion: dict, n_sesiones: int, estilos: _Estilos) -> Table:
    fecha_registro = participante["fecha_registro"].strftime("%d/%m/%Y") if participante.get("fecha_registro") else "—"
    duracion = sesion.get("duracion_seg")
    duracion_texto = f"{duracion // 60}m {duracion % 60}s" if duracion else "—"

    celdas = [
        [
            _tarjeta_dato("ID Participante", f"{participante['id_participante']} &nbsp;&nbsp;<font size=9 color='{Colors.TEXT_SECONDARY}'>Registrado: {fecha_registro}</font>", estilos),
            _tarjeta_dato("Edad / Género", f"{participante.get('edad', '—')} años &nbsp;&nbsp;<font size=9 color='{Colors.TEXT_SECONDARY}'>{_GENERO_LEGIBLE.get(participante.get('genero'), '—')}</font>", estilos),
        ],
        [
            _tarjeta_dato("Mano dominante / N° sesiones", f"{_MANO_LEGIBLE.get(participante.get('mano_dominante'), '—')} &nbsp;&nbsp;<font size=9 color='{Colors.TEXT_SECONDARY}'>{n_sesiones} sesión(es)</font>", estilos),
            _tarjeta_dato("Duración / Fecha del reporte", f"{duracion_texto} &nbsp;&nbsp;<font size=9 color='{Colors.TEXT_SECONDARY}'>{datetime.now().strftime('%d/%m/%Y')}</font>", estilos),
        ],
    ]
    tabla = Table(celdas, colWidths=[8.5 * cm, 8.5 * cm])
    tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return tabla


def _resumen_ejecutivo(ranking: pd.DataFrame, sesion: dict, pruebas_por_tipo: dict, estilos: _Estilos) -> Table:
    """Card destacada de la portada: estímulo más efectivo, ΔHR, mayor preferencia,
    score global 0-100."""
    if ranking.empty or ranking["score_relajacion"].isna().all():
        contenido = [[Paragraph("RESUMEN EJECUTIVO", estilos.etiqueta)], [Paragraph("No hay suficientes datos para un resumen (faltan baseline o pruebas).", estilos.cuerpo)]]
        tabla = Table(contenido, colWidths=[17 * cm])
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(Colors.BG_MAIN)),
                    ("BOX", (0, 0), (-1, -1), 1, rl_colors.HexColor(Colors.BORDER)),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                    ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ]
            )
        )
        return tabla

    mejor = ranking.iloc[0]
    etiqueta_mejor = _ETIQUETAS_ESTIMULO.get(mejor["condicion"], mejor["condicion"])
    hr_baseline = sesion.get("hr_baseline")
    delta_hr = (mejor["hr_media"] - hr_baseline) if hr_baseline is not None and pd.notna(mejor["hr_media"]) else None
    # La etiqueta cambia según el signo real: mostrar siempre "Reducción" aunque el HR
    # haya SUBIDO es engañoso (bug real visto probando con P013: el mejor score fue por
    # SDNN/RMSSD mucho más altos, no porque el HR bajara — de hecho subió +1.7 bpm).
    flecha = "↓" if (delta_hr is not None and delta_hr < 0) else ("↑" if delta_hr is not None else "")
    color_delta = Colors.SUCCESS if (delta_hr is not None and delta_hr < 0) else Colors.DANGER
    etiqueta_delta = "Reducción de HR vs baseline" if (delta_hr is not None and delta_hr < 0) else "Cambio de HR vs baseline"

    likerts = {t: p.get("likert_relajacion") for t, p in pruebas_por_tipo.items() if p.get("likert_relajacion") is not None}
    mas_valorado = max(likerts, key=likerts.get) if likerts else None

    score_global = _score_global_0_100(ranking)

    filas = [
        [Paragraph("RESUMEN EJECUTIVO", estilos.etiqueta), ""],
        [
            Paragraph(f"<b>Estímulo más efectivo:</b> {etiqueta_mejor}", estilos.cuerpo),
            Paragraph(f"<b>Score global de la sesión:</b> <font color='{Colors.PRIMARY}' size=14>{score_global if score_global is not None else '—'}/100</font>", estilos.cuerpo),
        ],
        [
            Paragraph(
                f"<b>{etiqueta_delta}:</b> <font color='{color_delta}'>{flecha} {abs(delta_hr):.1f} bpm</font>" if delta_hr is not None else "<b>Cambio de HR vs baseline:</b> N/A",
                estilos.cuerpo,
            ),
            Paragraph(
                f"<b>Mayor preferencia subjetiva:</b> {_ETIQUETAS_ESTIMULO.get(mas_valorado, mas_valorado)} ({likerts[mas_valorado]}/5)" if mas_valorado else "<b>Mayor preferencia subjetiva:</b> N/A",
                estilos.cuerpo,
            ),
        ],
    ]
    tabla = Table(filas, colWidths=[8.5 * cm, 8.5 * cm])
    tabla.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(Colors.BG_MAIN)),
                ("BOX", (0, 0), (-1, -1), 1, rl_colors.HexColor(Colors.SECONDARY)),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return tabla


def _pie_de_pagina_firma(estilos: _Estilos) -> Table:
    linea = Table([[""]], colWidths=[6 * cm])
    linea.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.75, rl_colors.HexColor(Colors.BORDER))]))
    contenido = [
        [linea],
        [Paragraph(f"{INVESTIGADOR} — Investigador principal", estilos.nota)],
        [Paragraph(UNIVERSIDAD, estilos.nota)],
    ]
    tabla = Table(contenido)
    tabla.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return tabla


def _estilo_tabla_premium(encabezados_desde_fila: int = 1) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor(Colors.PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), PT_CUERPO - 1),
            ("ROWBACKGROUNDS", (0, encabezados_desde_fila), (-1, -1), [rl_colors.white, rl_colors.HexColor(Colors.BG_MAIN)]),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor(Colors.BORDER)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )


def _tabla_metricas_bloque(sesion: dict, pruebas_por_tipo: dict, ranking: pd.DataFrame) -> Table:
    """Página 2 — tabla limpia por bloque, con ΔHR vs baseline."""
    hr_baseline = sesion.get("hr_baseline")
    encabezados = ["Bloque", "Duración", "HR prom.", "ΔHR vs baseline", "SDNN", "RMSSD", "Preferencia"]
    filas = [encabezados]

    duracion_sesion = sesion.get("duracion_seg")
    filas.append(
        [
            "Baseline",
            f"{duracion_sesion}s" if duracion_sesion else "—",
            f"{hr_baseline:.1f}" if hr_baseline is not None else "—",
            "—",
            f"{sesion.get('sdnn_baseline'):.1f}" if sesion.get("sdnn_baseline") is not None else "—",
            f"{sesion.get('rmssd_baseline'):.1f}" if sesion.get("rmssd_baseline") is not None else "—",
            "—",
        ]
    )
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        if prueba is None:
            filas.append([_ETIQUETAS_ESTIMULO[tipo], "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])
            continue
        hr_prom = prueba.get("hr_promedio")
        delta = (hr_prom - hr_baseline) if hr_prom is not None and hr_baseline is not None else None
        filas.append(
            [
                _ETIQUETAS_ESTIMULO[tipo],
                f"{prueba.get('duracion_seg', '—')}s",
                f"{hr_prom:.1f}" if hr_prom is not None else "N/A",
                f"{delta:+.1f}" if delta is not None else "N/A",
                f"{prueba.get('sdnn'):.1f}" if prueba.get("sdnn") is not None else "N/A",
                f"{prueba.get('rmssd'):.1f}" if prueba.get("rmssd") is not None else "N/A",
                _PREFERENCIA_LEGIBLE.get(prueba.get("preferencia"), "N/A"),
            ]
        )

    tabla = Table(filas, colWidths=[3.6 * cm, 2.4 * cm, 2.4 * cm, 3.2 * cm, 2.4 * cm, 2.4 * cm, 3.2 * cm], repeatRows=1)
    tabla.setStyle(_estilo_tabla_premium())
    return tabla


def _tabla_ranking_premium(ranking: pd.DataFrame, sesion: dict, estilos: _Estilos) -> Table:
    """Página 3 — ranking de score_relajacion con badges de texto (ver docstring
    del módulo: emoji de medalla NO renderiza en Helvetica, así que se usan
    badges de texto con fondo de color en vez de 🥇🥈🥉)."""
    if ranking.empty:
        return Table([[Paragraph("Sin datos suficientes para un ranking.", estilos.cuerpo)]])

    hr_baseline = sesion.get("hr_baseline")
    colores_puesto = [_ORO, _PLATA, _BRONCE]
    etiquetas_puesto = ["1º LUGAR", "2º LUGAR", "3º LUGAR"]

    filas = [["Puesto", "Estímulo", "Score relajación", "% mejora HR vs baseline"]]
    estilo_filas_color = []
    for i, (_, fila) in enumerate(ranking.iterrows()):
        if pd.isna(fila["score_relajacion"]):
            continue
        etiqueta_puesto = etiquetas_puesto[i] if i < 3 else f"{i + 1}º"
        mejora_pct = None
        if hr_baseline and pd.notna(fila["hr_media"]) and hr_baseline != 0:
            mejora_pct = (hr_baseline - fila["hr_media"]) / hr_baseline * 100
        filas.append(
            [
                etiqueta_puesto,
                _ETIQUETAS_ESTIMULO.get(fila["condicion"], fila["condicion"]),
                f"{fila['score_relajacion']:.3f}",
                f"{mejora_pct:+.1f}%" if mejora_pct is not None else "N/A",
            ]
        )
        if i < 3:
            estilo_filas_color.append((i + 1, colores_puesto[i]))

    tabla = Table(filas, colWidths=[3 * cm, 5 * cm, 4 * cm, 5 * cm], repeatRows=1)
    comandos = list(_estilo_tabla_premium().getCommands())
    for fila_idx, color in estilo_filas_color:
        comandos.append(("BACKGROUND", (0, fila_idx), (0, fila_idx), rl_colors.HexColor(color)))
        comandos.append(("TEXTCOLOR", (0, fila_idx), (0, fila_idx), rl_colors.white))
        comandos.append(("FONTNAME", (0, fila_idx), (0, fila_idx), "Helvetica-Bold"))
    tabla.setStyle(TableStyle(comandos))
    return tabla


def _tabla_comentarios(pruebas_por_tipo: dict, estilos: _Estilos) -> Table:
    """Página 4 — comentarios cualitativos. La tabla 'pruebas' no tiene una
    columna de comentario libre en el esquema actual (ver bd_sqlserver.py) —
    se documenta eso acá en vez de inventar una columna que no existe."""
    filas = [["Estímulo", "Likert relajación", "Likert confort", "Preferencia"]]
    for tipo in _ORDEN_ESTIMULO:
        prueba = pruebas_por_tipo.get(tipo)
        if prueba is None:
            filas.append([_ETIQUETAS_ESTIMULO[tipo], "N/A", "N/A", "N/A"])
            continue
        filas.append(
            [
                _ETIQUETAS_ESTIMULO[tipo],
                str(prueba.get("likert_relajacion")) if prueba.get("likert_relajacion") is not None else "N/A",
                str(prueba.get("likert_confort")) if prueba.get("likert_confort") is not None else "N/A",
                _PREFERENCIA_LEGIBLE.get(prueba.get("preferencia"), "N/A"),
            ]
        )
    tabla = Table(filas, colWidths=[4.5 * cm, 4 * cm, 4 * cm, 4.5 * cm], repeatRows=1)
    tabla.setStyle(_estilo_tabla_premium())
    return tabla


def _correlacion_preferencia_metricas(ranking: pd.DataFrame, pruebas_por_tipo: dict) -> str:
    """Pearson simple entre preferencia numérica (1-4) y score_relajacion — con
    n=4 puntos como mucho, es más una nota descriptiva que un test estadístico
    riguroso, se presenta como tal."""
    pares = []
    for _, fila in ranking.iterrows():
        prueba = pruebas_por_tipo.get(fila["condicion"])
        if prueba is None or pd.isna(fila["score_relajacion"]):
            continue
        pref_num = _PREFERENCIA_NUMERICA.get(prueba.get("preferencia"))
        if pref_num is not None:
            pares.append((pref_num, fila["score_relajacion"]))

    if len(pares) < 2:
        return "No hay suficientes respuestas de preferencia registradas para calcular una correlación con las métricas fisiológicas."

    x = np.array([p[0] for p in pares])
    y = np.array([p[1] for p in pares])
    if np.std(x) == 0 or np.std(y) == 0:
        return "La preferencia no varió entre estímulos con datos suficientes; no se puede calcular una correlación."
    r = float(np.corrcoef(x, y)[0, 1])
    fuerza = "fuerte" if abs(r) > 0.6 else "moderada" if abs(r) > 0.3 else "débil"
    direccion = "positiva" if r > 0 else "negativa"
    return (
        f"Correlación entre preferencia subjetiva y score de relajación: r = {r:.2f} "
        f"({fuerza}, {direccion}) — calculada sobre {len(pares)} estímulo(s) con ambos datos disponibles. "
        "Con tan pocos puntos, es descriptiva, no un test de significancia estadística."
    )


# ============================================================================
# Orquestador
# ============================================================================


def generar_reporte_pdf(
    bd,
    id_participante: str,
    carpeta_salida: Optional[Path] = None,
    ruta_logo: Optional[Path] = None,
) -> Path:
    """Genera el reporte PDF de un participante — 5 páginas, nivel publicación
    académica (ver docstring del módulo para la estructura completa).

    Mantiene la misma superficie que la versión anterior en app_investigador.py
    (mismo tipo de parámetros: una conexión BaseDatosTesis + un id_participante),
    así que AppInvestigador._generar_reporte_pdf() puede seguir llamándola sin
    que la vista de Análisis/Exportar note el cambio.

    Args:
        bd: Instancia conectada de BaseDatosTesis (ver database/bd_sqlserver.py).
        id_participante: ID del participante a reportar.
        carpeta_salida: Carpeta donde guardar el .pdf (default CARPETA_EXPORTS_DEFAULT).
        ruta_logo: Ruta al logo ESPE. Si no existe o es None, el reporte se
            genera igual, solo que sin logo (nunca falla por esto).

    Returns:
        Path: Ruta del .pdf generado.

    Raises:
        ValueError: Si el participante no existe, o no tiene ninguna sesión
            con pruebas registradas (no hay nada que reportar).
    """
    carpeta_salida = Path(carpeta_salida) if carpeta_salida is not None else CARPETA_EXPORTS_DEFAULT

    participante = next((p for p in bd.obtener_participantes() if p["id_participante"] == id_participante), None)
    if participante is None:
        raise ValueError(f"El participante {id_participante} no existe en la base de datos.")

    sesiones = bd.obtener_sesiones_participante(id_participante)
    sesiones_con_pruebas = [(s, bd.obtener_pruebas_sesion(s["id_sesion"])) for s in sesiones]
    sesiones_con_pruebas = [(s, p) for s, p in sesiones_con_pruebas if p]
    if not sesiones_con_pruebas:
        raise ValueError(f"{id_participante} no tiene ninguna sesión con pruebas registradas; no hay nada que reportar.")

    # La más reciente con pruebas — reportar todo el historial haría que el
    # largo del PDF creciera sin límite con cada sesión nueva; obtener_sesiones_participante()
    # ya viene ordenado por fecha_hora DESC (ver bd_sqlserver.py).
    sesion, pruebas = sesiones_con_pruebas[0]
    pruebas_por_tipo = {p["tipo_estimulo"]: p for p in pruebas}

    ranking = _calcular_ranking(pruebas, sesion)

    carpeta_salida.mkdir(parents=True, exist_ok=True)
    ruta = carpeta_salida / f"{id_participante}_reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    estilos = _Estilos()
    elementos: list = []

    # ---------- PÁGINA 1: PORTADA EJECUTIVA ----------
    elementos.append(_banner_titulo(estilos, ruta_logo))
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(_grilla_participante(participante, sesion, len(sesiones), estilos))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(_resumen_ejecutivo(ranking, sesion, pruebas_por_tipo, estilos))
    elementos.append(Spacer(1, 1.2 * cm))
    elementos.append(_pie_de_pagina_firma(estilos))
    elementos.append(PageBreak())

    # ---------- PÁGINA 2: MÉTRICAS PRINCIPALES ----------
    elementos.append(Paragraph("MÉTRICAS FISIOLÓGICAS", estilos.subtitulo))
    hr_prom_sesion = np.nanmean([p.get("hr_promedio") for p in pruebas if p.get("hr_promedio") is not None]) if pruebas else None
    sdnn_prom = np.nanmean([p.get("sdnn") for p in pruebas if p.get("sdnn") is not None]) if pruebas else None
    rmssd_prom = np.nanmean([p.get("rmssd") for p in pruebas if p.get("rmssd") is not None]) if pruebas else None
    fila_kpi = Table(
        [
            [
                _tarjeta_dato("HR baseline", f"{sesion['hr_baseline']:.1f} bpm" if sesion.get("hr_baseline") is not None else "N/A", estilos),
                _tarjeta_dato("HR promedio sesión", f"{hr_prom_sesion:.1f} bpm" if hr_prom_sesion is not None and not np.isnan(hr_prom_sesion) else "N/A", estilos),
                _tarjeta_dato("SDNN promedio", f"{sdnn_prom:.1f} ms" if sdnn_prom is not None and not np.isnan(sdnn_prom) else "N/A", estilos),
                _tarjeta_dato("RMSSD promedio", f"{rmssd_prom:.1f} ms" if rmssd_prom is not None and not np.isnan(rmssd_prom) else "N/A", estilos),
            ]
        ],
        colWidths=[4.25 * cm] * 4,
    )
    fila_kpi.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    elementos.append(fila_kpi)
    elementos.append(Spacer(1, 0.5 * cm))
    buffer_hr_bloques = _grafico_hr_bloques(sesion, pruebas_por_tipo)
    elementos.append(Image(buffer_hr_bloques, width=17 * cm, height=7.3 * cm))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(_tabla_metricas_bloque(sesion, pruebas_por_tipo, ranking))
    elementos.append(PageBreak())

    # ---------- PÁGINA 3: ANÁLISIS COMPARATIVO ----------
    elementos.append(Paragraph("COMPARACIÓN ENTRE ESTÍMULOS", estilos.subtitulo))
    buffer_comparacion = _grafico_comparacion_hr(sesion, pruebas_por_tipo)
    buffer_hrv = _grafico_hrv_comparacion(pruebas_por_tipo)
    fila_graficos = Table([[Image(buffer_comparacion, width=8.4 * cm, height=5.8 * cm), Image(buffer_hrv, width=8.4 * cm, height=5.8 * cm)]], colWidths=[8.5 * cm, 8.5 * cm])
    elementos.append(fila_graficos)
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(Paragraph("Puntaje de relajación", estilos.subtitulo))
    elementos.append(_tabla_ranking_premium(ranking, sesion, estilos))
    elementos.append(PageBreak())

    # ---------- PÁGINA 4: RESPUESTA SUBJETIVA ----------
    elementos.append(Paragraph("AUTORREPORTE DEL PARTICIPANTE", estilos.subtitulo))
    buffer_radar = _grafico_radar(pruebas_por_tipo)
    ancho_radar, alto_radar = _ajustar_dimensiones(BytesIO(buffer_radar.getvalue()), ancho_max=11 * cm, alto_max=11 * cm)
    elementos.append(Image(buffer_radar, width=ancho_radar, height=alto_radar))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(Paragraph("Comentarios y autorreporte por estímulo", estilos.subtitulo))
    elementos.append(_tabla_comentarios(pruebas_por_tipo, estilos))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(Paragraph(_correlacion_preferencia_metricas(ranking, pruebas_por_tipo), estilos.cuerpo))
    elementos.append(PageBreak())

    # ---------- PÁGINA 5: CONCLUSIONES E INSIGHTS ----------
    elementos.append(Paragraph("INTERPRETACIÓN", estilos.subtitulo))
    texto_insight = _generar_insight(ranking, pruebas_por_tipo, sesion)
    caja_insight = Table([[Paragraph(texto_insight, estilos.insight)]], colWidths=[17 * cm])
    caja_insight.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor(Colors.BG_MAIN)),
                ("BOX", (0, 0), (-1, -1), 1, rl_colors.HexColor(Colors.PRIMARY)),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
            ]
        )
    )
    elementos.append(caja_insight)
    elementos.append(Spacer(1, 0.4 * cm))
    if not ranking.empty and not ranking["score_relajacion"].isna().all():
        peor = ranking.iloc[-1]
        sugerencia = (
            f"Para próximas sesiones, se sugiere priorizar {_ETIQUETAS_ESTIMULO.get(ranking.iloc[0]['condicion'], ranking.iloc[0]['condicion'])} "
            f"y evaluar con más repeticiones si la respuesta se mantiene consistente. "
            f"{_ETIQUETAS_ESTIMULO.get(peor['condicion'], peor['condicion'])} mostró la respuesta de relajación más baja de esta sesión."
        )
        elementos.append(Paragraph(f"<b>Sugerencia para próximas sesiones:</b> {sugerencia}", estilos.cuerpo))
        elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph("Metadatos técnicos", estilos.subtitulo))
    metadatos = [
        ["Campo", "Valor"],
        ["Sistema", "Sistema Adaptativo de Frecuencias Terapéuticas — app_investigador.py"],
        ["Sensor cardíaco", "Wahoo TRACKR (BLE) o simulador — ver sesión registrada"],
        ["Base de datos", "SQL Server (BaseDatosTesis)"],
        ["Sesión reportada", f"#{sesion['id_sesion']} — {sesion['fecha_hora'].strftime('%d/%m/%Y %H:%M') if sesion.get('fecha_hora') else '—'}"],
        ["Reporte generado", _fecha_larga_es(datetime.now())],
    ]
    tabla_metadatos = Table(metadatos, colWidths=[5 * cm, 12 * cm])
    tabla_metadatos.setStyle(_estilo_tabla_premium())
    elementos.append(tabla_metadatos)
    elementos.append(Spacer(1, 1 * cm))
    elementos.append(_pie_de_pagina_firma(estilos))

    def _pie_de_pagina(canvas, documento) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", PT_NOTA)
        canvas.setFillColor(rl_colors.HexColor(Colors.TEXT_SECONDARY))
        canvas.drawString(_MARGEN_HORIZONTAL, 1 * cm, f"{id_participante} — Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        canvas.drawRightString(documento.pagesize[0] - _MARGEN_HORIZONTAL, 1 * cm, f"Página {documento.page}")
        canvas.restoreState()

    documento = SimpleDocTemplate(
        str(ruta),
        pagesize=A4,
        leftMargin=_MARGEN_HORIZONTAL,
        rightMargin=_MARGEN_HORIZONTAL,
        topMargin=_MARGEN_VERTICAL,
        bottomMargin=_MARGEN_VERTICAL,
        title=f"Reporte — {id_participante}",
    )
    documento.build(elementos, onFirstPage=_pie_de_pagina, onLaterPages=_pie_de_pagina)
    return ruta
