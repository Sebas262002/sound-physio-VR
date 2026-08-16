"""Análisis automático post-sesión: consolida los 3 archivos de una sesión en un reporte.

Orquesta, en un solo paso, los módulos de análisis que hasta ahora había
que correr por separado:

    sincronizador.py         → tabla unificada (HR + condición + respiración)
    analizar_sesion.py       → HR/HRV por bloque + gráfica de 4 paneles
    detectar_respiraciones.py → frecuencia respiratoria, SEGMENTADA por bloque
                                usando los timestamps del JSON de eventos
    recomendador.py          → estímulo con mejor respuesta fisiológica

...y arma un reporte Markdown legible en resultados/reportes/, en vez de
tener que leer 3 archivos y varias tablas sueltas por separado.

¿Por qué Markdown y no PDF? Un PDF con matplotlib.backends.backend_pdf
sirve bien para EMBEBER gráficas, pero las tablas de métricas quedarían
como texto plano dibujado a mano (sin las utilidades de formato de una
tabla real) o habría que rasterizarlas como imagen — más código y más
frágil para el mismo resultado. Markdown ya renderiza tablas de forma
nativa en GitHub/VSCode/la mayoría de visores, permite embeber la gráfica
PNG con una sola línea (![...](ruta.png)), y no agrega ninguna dependencia
nueva al proyecto (a diferencia de intentar generar PDF con reportlab u
otra librería no instalada).

RESPIRACIÓN SEGMENTADA POR BLOQUE — cómo funciona:
detectar_respiraciones.py normalmente analiza el WAV completo de una
sesión de punta a punta. Acá, en cambio, se usa el JSON de eventos (con
los t_inicio/t_fin REALES de cada bloque, ver reproductor_estimulos.py)
para CORTAR el audio en tramos y analizar cada uno por separado con su
propia instancia de DetectorRespiracion — mismo patrón que ya usa
sincronizador.py en detectar_respiraciones_por_ventana() (asignar
self.audio/self.sr directamente, sin volver a leer el archivo del disco
por tramo). Así se puede reportar "frecuencia respiratoria durante
solfeggio" en vez de solo "frecuencia respiratoria en toda la sesión".
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, r"C:\Tesis_Kevin\python\sensor")
sys.path.insert(0, r"C:\Tesis_Kevin\python\audio")

from analizar_sesion import AnalisisSesion, CARPETA_GRAFICAS  # noqa: E402
from detectar_respiraciones import DetectorRespiracion  # noqa: E402
from recomendador import Recomendador  # noqa: E402
from sincronizador import SincronizadorSesion  # noqa: E402

CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")
CARPETA_AUDIO_SESIONES = CARPETA_SESIONES / "audio"
CARPETA_REPORTES = Path(r"C:\Tesis_Kevin\resultados\reportes")


def _encontrar_archivos_participante(participante_id: str) -> dict:
    """Busca los 3 archivos más recientes de un participante en datos/sesiones/.

    Args:
        participante_id: Identificador del participante, ej. "P09".

    Returns:
        dict: csv (Path), json_eventos (Path), wav (Optional[Path], None
            si no hay ninguna grabación de audio para ese participante).

    Raises:
        FileNotFoundError: Si no se encuentra CSV o JSON de eventos.
    """
    csvs = [
        ruta
        for ruta in CARPETA_SESIONES.glob(f"{participante_id}_*.csv")
        if not ruta.stem.startswith(f"{participante_id}_unificado")
    ]
    if not csvs:
        raise FileNotFoundError(f"No se encontró ningún CSV para {participante_id} en {CARPETA_SESIONES}")
    ruta_csv = max(csvs, key=lambda ruta: ruta.stat().st_mtime)

    jsons_eventos = list(CARPETA_SESIONES.glob(f"{participante_id}_estimulos_*.json"))
    if not jsons_eventos:
        raise FileNotFoundError(f"No se encontró ningún JSON de eventos para {participante_id}")
    ruta_json_eventos = max(jsons_eventos, key=lambda ruta: ruta.stat().st_mtime)

    wavs = list(CARPETA_AUDIO_SESIONES.glob(f"{participante_id}_*.wav")) if CARPETA_AUDIO_SESIONES.exists() else []
    ruta_wav = max(wavs, key=lambda ruta: ruta.stat().st_mtime) if wavs else None

    return {"csv": ruta_csv, "json_eventos": ruta_json_eventos, "wav": ruta_wav}


def _analizar_respiracion_por_bloque(
    ruta_wav: Path, eventos: list[dict], t0_referencia_audio: float = 0.0
) -> pd.DataFrame:
    """Segmenta el WAV según los t_inicio/t_fin del JSON de eventos y analiza cada bloque.

    Args:
        ruta_wav: WAV de la sesión (grabación de respiración).
        eventos: Lista de bloques del JSON de eventos (nombre, tipo, t_inicio, t_fin).
        t0_referencia_audio: Segundos desde el t0 de la sesión en que empezó a
            grabarse el WAV (metadata_audio["timestamp_inicio"] del JSON
            hermano del WAV; normalmente ~0 si el mic arrancó casi junto
            con el resto). Se resta de los t_inicio/t_fin de cada evento
            para ubicar el offset correcto DENTRO del propio archivo WAV.

    Returns:
        pd.DataFrame: nombre, tipo, duracion_seg, numero_respiraciones,
            frecuencia_respiratoria_bpm, interpretacion — una fila por bloque.
    """
    detector_completo = DetectorRespiracion(ruta_wav)
    detector_completo.cargar()

    filas = []
    for evento in eventos:
        inicio_audio = max(0.0, evento["t_inicio"] - t0_referencia_audio)
        fin_audio = min(detector_completo.duracion_seg, evento["t_fin"] - t0_referencia_audio)

        if fin_audio <= inicio_audio:
            # El bloque cae fuera de lo que alcanzó a grabar el WAV (ej. si el mic
            # arrancó tarde o terminó antes que el protocolo) — no hay nada que analizar
            filas.append(
                {
                    "nombre": evento["nombre"],
                    "tipo": evento["tipo"],
                    "duracion_seg": round(evento["t_fin"] - evento["t_inicio"], 1),
                    "numero_respiraciones": 0,
                    "frecuencia_respiratoria_bpm": float("nan"),
                    "interpretacion": "Sin audio disponible para este bloque",
                }
            )
            continue

        muestra_inicio = int(inicio_audio * detector_completo.sr)
        muestra_fin = int(fin_audio * detector_completo.sr)

        # Sub-detector que reutiliza el audio ya cargado (sin releer el WAV del disco
        # por bloque) — mismo patrón que sincronizador.py, detectar_respiraciones_por_ventana()
        detector_bloque = DetectorRespiracion(ruta_wav)
        detector_bloque.audio = detector_completo.audio[muestra_inicio:muestra_fin]
        detector_bloque.sr = detector_completo.sr
        detector_bloque.duracion_seg = (muestra_fin - muestra_inicio) / detector_completo.sr

        resumen_bloque = detector_bloque.analizar()  # usa los defaults optimizados para el F15-2

        filas.append(
            {
                "nombre": evento["nombre"],
                "tipo": evento["tipo"],
                "duracion_seg": resumen_bloque["duracion_analizada_seg"],
                "numero_respiraciones": resumen_bloque["numero_respiraciones"],
                "frecuencia_respiratoria_bpm": resumen_bloque["frecuencia_respiratoria_bpm"],
                "interpretacion": resumen_bloque["interpretacion"],
            }
        )

    return pd.DataFrame(filas)


def _df_a_markdown(df: pd.DataFrame) -> str:
    """Convierte un DataFrame a una tabla Markdown, a mano (sin depender de tabulate,
    que no está instalado en este proyecto — ver docstring del módulo).
    """
    columnas = list(df.columns)
    encabezado = "| " + " | ".join(str(c) for c in columnas) + " |"
    separador = "| " + " | ".join("---" for _ in columnas) + " |"
    filas = []
    for _, fila in df.iterrows():
        valores = []
        for valor in fila:
            if isinstance(valor, float):
                valores.append("NaN" if pd.isna(valor) else f"{valor:.2f}")
            else:
                valores.append(str(valor))
        filas.append("| " + " | ".join(valores) + " |")
    return "\n".join([encabezado, separador, *filas])


def analizar_sesion_completa(
    participante_id: Optional[str] = None,
    ruta_csv: Optional[Path] = None,
    ruta_wav: Optional[Path] = None,
    ruta_json_eventos: Optional[Path] = None,
    generar_grafica: bool = True,
) -> Path:
    """Ejecuta el pipeline completo de análisis y arma un reporte Markdown consolidado.

    Se puede llamar de dos formas:
      - Con participante_id solo: busca automáticamente sus 3 archivos más
        recientes en datos/sesiones/ (ver _encontrar_archivos_participante()).
      - Con las rutas explícitas (ruta_csv, ruta_json_eventos obligatorias;
        ruta_wav opcional) — así lo llama sesion_completa.py justo después
        de guardar los 3 archivos de una sesión recién capturada, sin
        depender de que sean "los más recientes" en disco.

    Args:
        participante_id: ID del participante. Si se omite, se deriva del
            nombre de ruta_csv.
        ruta_csv: CSV cardíaco. Si es None, se busca junto con participante_id.
        ruta_wav: WAV de audio. Si es None, se omite el análisis respiratorio
            y la fila "respiraciones_min" queda en NaN para todos los bloques.
        ruta_json_eventos: JSON de eventos de estímulos.
        generar_grafica: Si True, genera y guarda la gráfica de 4 paneles
            (ver AnalisisSesion.graficar_sesion()) y la referencia en el reporte.

    Returns:
        Path: Ruta del reporte Markdown generado.
    """
    if ruta_csv is None or ruta_json_eventos is None:
        if participante_id is None:
            raise ValueError("Indica participante_id, o las rutas de archivo explícitamente.")
        archivos = _encontrar_archivos_participante(participante_id)
        ruta_csv = ruta_csv or archivos["csv"]
        ruta_json_eventos = ruta_json_eventos or archivos["json_eventos"]
        ruta_wav = ruta_wav if ruta_wav is not None else archivos["wav"]

    ruta_csv = Path(ruta_csv)
    ruta_json_eventos = Path(ruta_json_eventos)
    ruta_wav = Path(ruta_wav) if ruta_wav is not None else None
    participante_id = participante_id or ruta_csv.stem.split("_")[0]

    print(f"=== Analizando sesión completa: {participante_id} ===")
    print(f"  CSV:            {ruta_csv.name}")
    print(f"  WAV:            {ruta_wav.name if ruta_wav else '(no disponible)'}")
    print(f"  JSON eventos:   {ruta_json_eventos.name}")

    # --- a) sincronizador.py: tabla unificada (solo si hay WAV) ---
    ruta_tabla_unificada = None
    if ruta_wav is not None and ruta_wav.exists():
        print("\n--- Sincronizando datos (sincronizador.py) ---")
        try:
            sincronizador = SincronizadorSesion(ruta_csv, ruta_wav, ruta_json_eventos)
            sincronizador.cargar_todo()
            sincronizador.alinear_temporalmente()
            sincronizador.crear_tabla_unificada()
            ruta_tabla_unificada = sincronizador.guardar_tabla_unificada()
        except Exception as error:
            print(f"Advertencia: falló la sincronización ({error}); se continúa sin tabla unificada.")
    else:
        print("\n--- Sin WAV disponible: se omite sincronizador.py ---")

    # --- b) analizar_sesion.py: HR/HRV por bloque + gráfica ---
    print("\n--- Analizando HR/HRV (analizar_sesion.py) ---")
    analisis = AnalisisSesion(ruta_csv)
    analisis.cargar()
    resumen_general = analisis.resumen_general()
    tabla_hr = analisis.metricas_por_condicion()

    ruta_grafica_sesion = None
    if generar_grafica:
        analisis.graficar_sesion(guardar_en=f"{participante_id}_analisis.png")
        ruta_grafica_sesion = CARPETA_GRAFICAS / f"{participante_id}_analisis.png"

    # --- c) detectar_respiraciones.py, segmentado por bloque usando el JSON de eventos ---
    tabla_respiracion = None
    if ruta_wav is not None and ruta_wav.exists():
        print("\n--- Analizando respiración por bloque (detectar_respiraciones.py) ---")
        ruta_json_audio = ruta_wav.with_suffix(".json")
        t0_audio = 0.0
        if ruta_json_audio.exists():
            with open(ruta_json_audio, encoding="utf-8") as archivo:
                metadata_audio = json.load(archivo)
            t0_audio = metadata_audio.get("timestamp_inicio", 0.0)

        with open(ruta_json_eventos, encoding="utf-8") as archivo:
            contenido_eventos = json.load(archivo)
        # Formato nuevo {"metadata":..., "eventos":[...]} o formato viejo (lista bare) —
        # ver ReproductorEstimulos.guardar_eventos() en reproductor_estimulos.py
        eventos = (
            contenido_eventos["eventos"]
            if isinstance(contenido_eventos, dict) and "eventos" in contenido_eventos
            else contenido_eventos
        )

        tabla_respiracion = _analizar_respiracion_por_bloque(ruta_wav, eventos, t0_audio)
        print(tabla_respiracion[["nombre", "frecuencia_respiratoria_bpm", "interpretacion"]].to_string(index=False))
    else:
        print("\n--- Sin WAV disponible: se omite análisis respiratorio ---")

    # --- Combinar HR + respiración en una sola tabla ---
    tabla_combinada = tabla_hr.rename(columns={"hr_promedio": "hr_media"}).copy()
    if tabla_respiracion is not None:
        tabla_combinada = tabla_combinada.merge(
            tabla_respiracion[["nombre", "frecuencia_respiratoria_bpm"]].rename(
                columns={"nombre": "estimulo", "frecuencia_respiratoria_bpm": "respiraciones_min"}
            ),
            on="estimulo",
            how="left",
        )
    else:
        tabla_combinada["respiraciones_min"] = float("nan")

    # --- d) recomendador.py sobre las métricas combinadas (HR + HRV + respiración) ---
    print("\n--- Calculando recomendación (recomendador.py) ---")
    recomendador = Recomendador()
    resultado_recomendacion = None
    if "baseline" in tabla_combinada["estimulo"].values:
        baseline_dict = tabla_combinada.loc[tabla_combinada["estimulo"] == "baseline"].iloc[0].to_dict()
        ranking = recomendador.calcular_score_relajacion(tabla_combinada, baseline_dict)
        candidatos = ranking[~ranking["condicion"].isin(recomendador.excluir_condiciones)]
        if not candidatos.empty:
            mejor = candidatos.iloc[0]
            resultado_recomendacion = {
                "condicion_recomendada": mejor["condicion"],
                "score": round(float(mejor["score_relajacion"]), 4),
                "ranking_completo": ranking,
            }
            print(f"  Recomendado: {mejor['condicion']} (score={mejor['score_relajacion']:.3f})")
        else:
            print("  No quedaron condiciones candidatas tras excluir reposo.")
    else:
        print("  No hay bloque 'baseline': no se puede calcular una recomendación con baseline propio.")

    ruta_reporte = _generar_reporte_md(
        participante_id=participante_id,
        resumen_general=resumen_general,
        tabla_combinada=tabla_combinada,
        resultado_recomendacion=resultado_recomendacion,
        ruta_grafica_sesion=ruta_grafica_sesion,
        ruta_csv=ruta_csv,
        ruta_wav=ruta_wav,
        ruta_json_eventos=ruta_json_eventos,
        ruta_tabla_unificada=ruta_tabla_unificada,
    )

    print(f"\n=== Reporte generado: {ruta_reporte} ===")
    return ruta_reporte


def _generar_reporte_md(
    participante_id: str,
    resumen_general: dict,
    tabla_combinada: pd.DataFrame,
    resultado_recomendacion: Optional[dict],
    ruta_grafica_sesion: Optional[Path],
    ruta_csv: Path,
    ruta_wav: Optional[Path],
    ruta_json_eventos: Path,
    ruta_tabla_unificada: Optional[Path],
) -> Path:
    """Arma el archivo Markdown del reporte consolidado. Ver analizar_sesion_completa()."""
    CARPETA_REPORTES.mkdir(parents=True, exist_ok=True)
    fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")
    ruta_reporte = CARPETA_REPORTES / f"{participante_id}_reporte_completo_{fecha_hora}.md"

    lineas = [
        f"# Reporte de sesión — {participante_id}",
        "",
        f"**Fecha del reporte:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Duración total analizada:** {resumen_general['duracion_total_seg']}s",
        f"**Total de lecturas cardíacas:** {resumen_general['total_lecturas']}",
        f"**Lecturas descartadas (artefacto HR=0):** {resumen_general['lecturas_descartadas_hr0']}",
        f"**Condiciones evaluadas:** {', '.join(str(c) for c in resumen_general['condiciones_evaluadas'])}",
        "",
        "## Archivos fuente",
        "",
        f"- CSV cardíaco: `{ruta_csv}`",
    ]
    if ruta_wav is not None:
        lineas.append(f"- WAV audio: `{ruta_wav}`")
    lineas.append(f"- JSON eventos: `{ruta_json_eventos}`")
    if ruta_tabla_unificada is not None:
        lineas.append(f"- Tabla unificada: `{ruta_tabla_unificada}`")
    lineas.append("")

    lineas.append("## Métricas por bloque")
    lineas.append("")
    columnas_mostrar = [
        "condicion",
        "estimulo",
        "duracion_seg",
        "hr_media",
        "sdnn",
        "rmssd",
        "pnn50",
        "respiraciones_min",
    ]
    columnas_presentes = [columna for columna in columnas_mostrar if columna in tabla_combinada.columns]
    lineas.append(_df_a_markdown(tabla_combinada[columnas_presentes]))
    lineas.append("")

    lineas.append("## Comparación baseline vs. cada bloque")
    lineas.append("")
    if "baseline" in tabla_combinada["estimulo"].values:
        hr_baseline = tabla_combinada.loc[tabla_combinada["estimulo"] == "baseline", "hr_media"].iloc[0]
        for _, fila in tabla_combinada.iterrows():
            if fila["estimulo"] == "baseline":
                continue
            diferencia = fila["hr_media"] - hr_baseline
            direccion = "más baja" if diferencia < 0 else "más alta"
            lineas.append(
                f"- **{fila['estimulo']}**: HR {fila['hr_media']:.1f} bpm "
                f"({diferencia:+.1f} bpm, {direccion} que baseline)"
            )
        lineas.append("")
        lineas.append(
            "*Nota: comparación descriptiva de una sola sesión (N=1), no una prueba estadística — "
            "para conclusiones inferenciales hace falta agregar varios participantes "
            "(ver analisis_grupal.py, comparar_condiciones_pareado()).*"
        )
    else:
        lineas.append("No hay bloque `baseline` para comparar.")
    lineas.append("")

    lineas.append("## Estímulo recomendado")
    lineas.append("")
    if resultado_recomendacion is not None:
        lineas.append(
            f"**{resultado_recomendacion['condicion_recomendada']}** "
            f"(score de relajación: {resultado_recomendacion['score']:.3f})"
        )
        lineas.append("")
        lineas.append(
            "*Score positivo = más relajado que el baseline; negativo = más activado. "
            "Combina HR, SDNN, RMSSD y respiración (si hay audio), ponderados — ver "
            "Recomendador.calcular_score_relajacion() en recomendador.py.*"
        )
        lineas.append("")
        lineas.append("Ranking completo:")
        lineas.append("")
        lineas.append(_df_a_markdown(resultado_recomendacion["ranking_completo"]))
    else:
        lineas.append("No se pudo calcular una recomendación para esta sesión.")
    lineas.append("")

    if ruta_grafica_sesion is not None:
        lineas.append("## Gráfica de la sesión")
        lineas.append("")
        lineas.append(f"![Análisis de sesión]({ruta_grafica_sesion})")
        lineas.append("")

    with open(ruta_reporte, "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(lineas))

    return ruta_reporte


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Genera un reporte consolidado post-sesión a partir de los archivos de un participante."
    )
    parser.add_argument("--participante", required=True, help='ID del participante, ej. "P09"')
    argumentos = parser.parse_args()

    analizar_sesion_completa(participante_id=argumentos.participante)
