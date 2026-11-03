"""Migra las sesiones piloto ya guardadas en CSV (datos/sesiones/) a SQL Server.

Reutiliza analizar_metricas_sesion() (ver
python/analisis/analizar_sesion_completa.py) para calcular, por cada
sesión histórica, exactamente las mismas métricas por bloque que ya se ven
en los reportes .md — así los datos que quedan en SQL Server son
consistentes con los reportes ya generados, en vez de recalcularlos con
otra lógica.

QUÉ SE MIGRA Y CÓMO:
Cada participante encontrado en datos/sesiones/*.csv se registra en
'participantes' (si no existe ya). Cada sesión (CSV + su JSON de eventos
correspondiente, emparejados por el sufijo de fecha/hora del nombre de
archivo) se convierte en una fila de 'sesiones' (con hr_baseline/
rmssd_baseline/sdnn_baseline tomados del bloque "baseline"), y cada bloque
de ESTÍMULO (solfeggio/binaural/isocronico/preferencia — no los de
reposo/silencio) se convierte en una fila de 'pruebas' (ver
mapear_bloque_a_prueba() en bd_sqlserver.py).

DATOS DEMOGRÁFICOS FALTANTES:
Los CSV de sesión solo tienen HR/R-R/condición — nunca hubo un paso que
capturara edad/género. Ese dato no se puede inventar, así que este script
registra a los participantes migrados con esos campos en NULL y una
observación que lo deja explícito, salvo que se completen a mano en
DEMOGRAFIA_PARTICIPANTES (abajo) antes de correr la migración.

SESIONES QUE NO SE PUEDEN EMPAREJAR:
Si un CSV no tiene su JSON de eventos correspondiente (mismo sufijo de
fecha/hora) — pasó con una sesión temprana de P01, antes de que existiera
el JSON de eventos — esa sesión se omite con una advertencia, en vez de
fallar toda la migración.

CORRER ESTE SCRIPT MÁS DE UNA VEZ:
Antes de insertar una sesión, se chequea si ya existe una fila en 'sesiones'
con notas="Migrado desde <mismo nombre de CSV>" para ese participante — si
ya existe, se omite (no se duplica). Esto hace seguro volver a correr el
script sobre la misma carpeta (ej. tras agregar participantes nuevos): las
sesiones ya migradas antes simplemente se saltan, no se cuentan dos veces.
Además, cada corrida deja un registro con fecha en
datos/migraciones_log/migracion_<fecha>_<hora>.txt, con el detalle de qué se
migró y qué se omitió por ya existir — así, si corrés el script dos veces,
el segundo .txt deja ver claramente que todo (o casi todo) ya estaba.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, r"C:\Tesis_Kevin\python\database")
sys.path.insert(0, r"C:\Tesis_Kevin\python\analisis")

from bd_sqlserver import BaseDatosTesis, mapear_bloque_a_prueba  # noqa: E402
from analizar_sesion_completa import analizar_metricas_sesion  # noqa: E402

logger = logging.getLogger(__name__)

CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")
CARPETA_LOGS_MIGRACION = Path(r"C:\Tesis_Kevin\datos\migraciones_log")

# Completa acá los datos demográficos REALES de cada participante antes de
# migrar en serio (ej. "P01": {"edad": 24, "genero": "F"}).
# Cualquier participante que no aparezca acá se registra con esos campos en
# NULL — no se inventan valores.
DEMOGRAFIA_PARTICIPANTES: dict[str, dict] = {}


def _listar_participantes_con_sesiones() -> list[str]:
    """Encuentra los IDs de participante con al menos un CSV de sesión en datos/sesiones/.

    Returns:
        list[str]: IDs de participante ordenados alfabéticamente (ej. ["P01", "P02", ...]).
    """
    ids = set()
    for ruta in CARPETA_SESIONES.glob("*.csv"):
        nombre = ruta.stem
        if "_estimulos" in nombre or "_unificado" in nombre or "_test_" in nombre:
            continue
        ids.add(nombre.split("_")[0])
    return sorted(ids)


def _emparejar_archivos_sesion(participante_id: str) -> list[dict]:
    """Empareja cada CSV de sesión del participante con su JSON de eventos y WAV, por sufijo.

    Args:
        participante_id: ID del participante, ej. "P01".

    Returns:
        list[dict]: Una entrada por sesión encontrada: csv (Path),
            json_eventos (Path), wav (Optional[Path]), sufijo (str, ej.
            "20260812_2044"). Las sesiones sin JSON de eventos que calce se
            omiten (con advertencia impresa).
    """
    sesiones = []
    for ruta_csv in sorted(CARPETA_SESIONES.glob(f"{participante_id}_*.csv")):
        nombre = ruta_csv.stem
        if "_estimulos" in nombre or "_unificado" in nombre or "_test_" in nombre:
            continue

        sufijo = nombre[len(participante_id) + 1 :]  # "P01_20260812_2044" -> "20260812_2044"
        ruta_json = CARPETA_SESIONES / f"{participante_id}_estimulos_{sufijo}.json"
        if not ruta_json.exists():
            print(f"  Advertencia: {ruta_csv.name} no tiene JSON de eventos ({ruta_json.name}); se omite esta sesión.")
            continue

        carpeta_audio = CARPETA_SESIONES / "audio"
        candidatos_wav = list(carpeta_audio.glob(f"{participante_id}_*_{sufijo}.wav")) if carpeta_audio.exists() else []
        ruta_wav = candidatos_wav[0] if candidatos_wav else None

        sesiones.append({"csv": ruta_csv, "json_eventos": ruta_json, "wav": ruta_wav, "sufijo": sufijo})

    return sesiones


def _registrar_participante_si_no_existe(bd: BaseDatosTesis, participante_id: str) -> None:
    """Registra al participante con sus datos demográficos si ya están en DEMOGRAFIA_PARTICIPANTES,
    o con campos en NULL y una observación si no. No hace nada si ya está registrado
    (registrar_participante() ya valida existencia).
    """
    datos = DEMOGRAFIA_PARTICIPANTES.get(participante_id, {})
    observaciones = datos.get(
        "observaciones",
        "Migrado desde CSV piloto (migrar_csv_a_sqlserver.py)."
        + ("" if participante_id in DEMOGRAFIA_PARTICIPANTES else " Datos demográficos no disponibles — completar manualmente."),
    )
    bd.registrar_participante(
        participante_id,
        edad=datos.get("edad"),
        genero=datos.get("genero"),
        observaciones=observaciones,
    )


def _valor_o_none(fila: pd.Series, columna: str) -> Optional[float]:
    """Extrae fila[columna] como float nativo, o None si no existe o es NaN."""
    if columna not in fila or pd.isna(fila[columna]):
        return None
    return float(fila[columna])


def _sesion_ya_migrada(bd: BaseDatosTesis, participante_id: str, nombre_csv: str) -> bool:
    """True si ya existe una sesión migrada desde este mismo CSV para este participante.

    Evita duplicar sesiones si el script se corre más de una vez sobre la
    misma carpeta (ver CORRER ESTE SCRIPT MÁS DE UNA VEZ en el docstring del
    módulo).
    """
    notas_esperadas = f"Migrado desde {nombre_csv}"
    filas = bd.ejecutar_query(
        "SELECT id_sesion FROM sesiones WHERE id_participante = ? AND notas = ?",
        (participante_id, notas_esperadas),
    )
    return bool(filas)


def _sesion_duplicada_por_metricas(
    bd: BaseDatosTesis,
    participante_id: str,
    hr_baseline: Optional[float],
    rmssd_baseline: Optional[float],
    sdnn_baseline: Optional[float],
    tolerancia: float = 0.05,
) -> bool:
    """True si ya existe una sesión de este participante con el MISMO hr/rmssd/sdnn
    de baseline (dentro de una tolerancia chica, por redondeo de punto flotante).

    Cubre el caso que _sesion_ya_migrada() NO detecta: una sesión que la app en
    vivo (app_investigador.py) ya guardó directo en SQL Server (notas="Registrado
    desde app_investigador.py", texto distinto al que arma este script), y cuyo
    CSV de respaldo también está en datos/sesiones/. Sin este chequeo, migrar
    ese CSV crearía una SEGUNDA fila de sesión para el mismo evento real — mismo
    bug que _sesion_ya_migrada() evita, pero por la otra puerta.

    Comparar por valores de baseline (no por fecha/hora) es necesario porque la
    sesión en vivo se guarda en SQL Server recién DESPUÉS de que el participante
    completa el Cuestionario post-sesión (ver _vista_cuestionario en
    app_investigador.py) — ese paso lo hace una persona real, a su ritmo, así
    que el tiempo entre "se escribió el CSV" y "se guardó en la base" no tiene
    un límite confiable (se detectó en una prueba real que superó los 21
    minutos). hr/rmssd/sdnn de baseline, en cambio, se calculan siempre con la
    misma lógica (analizar_metricas_sesion) en los dos caminos, así que
    coinciden exactamente para el mismo evento real, sin depender de relojes
    ni de cuánto tardó nadie en responder nada.
    """
    if hr_baseline is None or rmssd_baseline is None or sdnn_baseline is None:
        return False
    for sesion in bd.obtener_sesiones_participante(participante_id):
        if (
            sesion.get("hr_baseline") is not None
            and sesion.get("rmssd_baseline") is not None
            and sesion.get("sdnn_baseline") is not None
            and abs(sesion["hr_baseline"] - hr_baseline) <= tolerancia
            and abs(sesion["rmssd_baseline"] - rmssd_baseline) <= tolerancia
            and abs(sesion["sdnn_baseline"] - sdnn_baseline) <= tolerancia
        ):
            return True
    return False


def _escribir_log_migracion(migradas: list[str], omitidas: list[str]) -> Path:
    """Escribe un .txt con fecha/hora en datos/migraciones_log/, con el detalle
    de qué se migró y qué se omitió por ya existir. Sirve para notar de
    inmediato si una corrida no hizo nada nuevo (todo omitido = ya se había
    migrado antes).

    Returns:
        Path: ruta del archivo de log escrito.
    """
    CARPETA_LOGS_MIGRACION.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now()
    ruta_log = CARPETA_LOGS_MIGRACION / f"migracion_{ahora.strftime('%Y%m%d_%H%M%S')}.txt"
    with open(ruta_log, "w", encoding="utf-8") as f:
        f.write(f"Migración corrida el {ahora.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Sesiones migradas (nuevas): {len(migradas)}\n")
        for linea in migradas:
            f.write(f"  + {linea}\n")
        f.write(f"\nSesiones omitidas (ya existían de una corrida anterior): {len(omitidas)}\n")
        for linea in omitidas:
            f.write(f"  = {linea}\n")
    return ruta_log


def migrar_todo(bd: BaseDatosTesis) -> None:
    """Recorre todos los participantes con sesiones en CSV y los migra a SQL Server.

    Args:
        bd: Instancia ya conectada de BaseDatosTesis.
    """
    participantes = _listar_participantes_con_sesiones()
    print(f"Participantes encontrados en {CARPETA_SESIONES}: {participantes}")

    total_sesiones = 0
    total_pruebas = 0
    migradas_detalle: list[str] = []
    omitidas_detalle: list[str] = []

    for participante_id in participantes:
        print(f"\n=== {participante_id} ===")
        _registrar_participante_si_no_existe(bd, participante_id)

        for info in _emparejar_archivos_sesion(participante_id):
            if _sesion_ya_migrada(bd, participante_id, info["csv"].name):
                print(f"  Omitida (ya migrada antes): {info['csv'].name}")
                omitidas_detalle.append(f"{participante_id}: {info['csv'].name} (ya migrada antes)")
                continue

            print(f"  Analizando sesión {info['sufijo']} ({info['csv'].name})...")
            try:
                resultado = analizar_metricas_sesion(
                    participante_id=participante_id,
                    ruta_csv=info["csv"],
                    ruta_wav=info["wav"],
                    ruta_json_eventos=info["json_eventos"],
                    generar_grafica=False,
                )
            except Exception as error:
                print(f"    Advertencia: no se pudo analizar esta sesión ({error}); se omite.")
                continue

            tabla = resultado["tabla_combinada"]
            fila_baseline = tabla.loc[tabla["estimulo"] == "baseline"]
            hr_baseline = _valor_o_none(fila_baseline.iloc[0], "hr_media") if not fila_baseline.empty else None
            sdnn_baseline = _valor_o_none(fila_baseline.iloc[0], "sdnn") if not fila_baseline.empty else None
            rmssd_baseline = _valor_o_none(fila_baseline.iloc[0], "rmssd") if not fila_baseline.empty else None

            if _sesion_duplicada_por_metricas(bd, participante_id, hr_baseline, rmssd_baseline, sdnn_baseline):
                print(f"  Omitida (ya estaba guardada en vivo por la app, mismos valores de baseline): {info['csv'].name}")
                omitidas_detalle.append(f"{participante_id}: {info['csv'].name} (ya guardada en vivo por la app)")
                continue

            id_sesion = bd.crear_sesion(
                participante_id,
                hr_baseline,
                rmssd_baseline,
                sdnn_baseline,
                notas=f"Migrado desde {info['csv'].name}",
            )
            if id_sesion is None:
                print("    Advertencia: no se pudo crear la fila de sesión; se omite.")
                continue

            duracion_total = resultado["resumen_general"].get("duracion_total_seg")
            if duracion_total is not None and not pd.isna(duracion_total):
                bd.actualizar_duracion_sesion(id_sesion, int(duracion_total))

            total_sesiones += 1
            migradas_detalle.append(f"{participante_id}: {info['csv'].name}")
            pruebas_de_esta_sesion = 0

            for _, fila in tabla.iterrows():
                info_prueba = mapear_bloque_a_prueba(fila["estimulo"])
                if info_prueba is None:
                    continue  # bloques de reposo/silencio: no son "pruebas"

                metricas_dict = {
                    "hr_promedio": fila.get("hr_media"),
                    "hr_min": fila.get("hr_min"),
                    "hr_max": fila.get("hr_max"),
                    "rmssd": fila.get("rmssd"),
                    "sdnn": fila.get("sdnn"),
                    "pnn50": fila.get("pnn50"),
                    "resp_por_min": fila.get("respiraciones_min"),
                }
                duracion_bloque = _valor_o_none(fila, "duracion_seg")

                id_prueba = bd.registrar_prueba(
                    id_sesion,
                    participante_id,
                    info_prueba["tipo_estimulo"],
                    info_prueba["frecuencia_hz"],
                    metricas_dict,
                    duracion_seg=int(duracion_bloque) if duracion_bloque is not None else None,
                )
                if id_prueba is not None:
                    total_pruebas += 1
                    pruebas_de_esta_sesion += 1

            print(f"    id_sesion={id_sesion}, {pruebas_de_esta_sesion} prueba(s) registrada(s).")

    ruta_log = _escribir_log_migracion(migradas_detalle, omitidas_detalle)
    print(
        f"\n=== Migración completa: {total_sesiones} sesión(es) NUEVA(S), {total_pruebas} prueba(s) registradas, "
        f"{len(omitidas_detalle)} sesión(es) omitida(s) por ya existir ==="
    )
    print(f"Registro de esta corrida guardado en: {ruta_log}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    bd = BaseDatosTesis()
    print("=== Conectando a SQL Server ===")
    if not bd.conectar():
        print("No se pudo conectar. Revisa tu .env y que SQL Server esté corriendo.")
        raise SystemExit(1)

    try:
        migrar_todo(bd)
    finally:
        bd.desconectar()
