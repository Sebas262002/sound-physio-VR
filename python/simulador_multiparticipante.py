"""Genera un dataset sintético de varias sesiones completas con perfiles fisiológicos distintos.

Sirve para poder desarrollar y probar el resto del pipeline (sincronizador,
análisis estadístico entre participantes) ANTES de tener datos reales de
15-20 personas — simulando variabilidad interindividual real: no todos los
participantes reaccionan igual al mismo estímulo.

Reutiliza la infraestructura ya construida en vez de reimplementarla:

- SimuladorCardiaco (python/sensor/simulador_cardiaco.py): un sensor por
  participante, con SUS PROPIOS hr_baseline/variabilidad/AJUSTES_CONDICION
  (ver _construir_ajustes_escalados() más abajo).
- ReproductorEstimulos.reproducir_protocolo(silencioso=True)
  (python/audio/reproductor_estimulos.py): calcula los eventos del
  protocolo (t_inicio/t_fin por bloque) SIN reproducir audio de verdad ni
  esperar en tiempo real — instantáneo. Reproducir 6 sesiones de audio
  real tomaría minutos y no aportaría nada a un dataset sintético.
- CapturaSesion (python/sensor/capturar_sesion.py): se reutiliza para
  guardar el CSV con el mismo formato/nombre que una sesión real, aunque
  aquí las lecturas se generan con un loop rápido (ver
  _generar_lecturas()) en vez de con ejecutar() (que sí espera en tiempo
  real, apropiado para una sesión real pero no para generar un dataset).

No genera WAV real: en su lugar, guarda un JSON de metadata "audio
simulado" con una frecuencia respiratoria plausible por condición (ver
RESPIRACION_POR_CONDICION), para no depender de librosa/sounddevice ni de
grabar 6 sesiones de audio reales.

Reproducibilidad — dos generadores de números aleatorios, no uno:
SimuladorCardiaco usa random.gauss() de la librería estándar (no numpy)
para el ruido de HR y R-R. Este módulo, en cambio, usa numpy para el ruido
de la respiración simulada. Por eso generar_dataset_simulado() siembra
AMBOS generadores (random.seed() y np.random.seed()) — sembrar solo uno
dejaría al otro sin reproducibilidad.
"""

import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Tesis_Kevin\python\sensor")
sys.path.insert(0, r"C:\Tesis_Kevin\python\audio")

from simulador_cardiaco import SimuladorCardiaco  # noqa: E402
from capturar_sesion import CapturaSesion, _condicion_desde_nombre  # noqa: E402
from reproductor_estimulos import ReproductorEstimulos  # noqa: E402

CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")
CARPETA_AUDIO_SESIONES = CARPETA_SESIONES / "audio"

# Perfiles fisiológicos simulados: distintos hr_baseline/variabilidad/respuesta_estimulo
# para representar la variabilidad interindividual real de una muestra de participantes
PERFILES = [
    {"id": "P01", "hr_baseline": 65, "variabilidad": 6, "respuesta_estimulo": -8, "descripcion": "Relajado natural"},
    {"id": "P02", "hr_baseline": 72, "variabilidad": 8, "respuesta_estimulo": -6, "descripcion": "Equilibrado"},
    {"id": "P03", "hr_baseline": 78, "variabilidad": 10, "respuesta_estimulo": -4, "descripcion": "Levemente activado"},
    {"id": "P04", "hr_baseline": 82, "variabilidad": 12, "respuesta_estimulo": -3, "descripcion": "Estresado"},
    {"id": "P05", "hr_baseline": 68, "variabilidad": 7, "respuesta_estimulo": -7, "descripcion": "Meditador experimentado"},
    {"id": "P06", "hr_baseline": 75, "variabilidad": 9, "respuesta_estimulo": -5, "descripcion": "Promedio"},
]

# Frecuencia respiratoria plausible por condición (promedio, desviación estándar),
# para el JSON de "audio simulado" — más baja en condiciones más relajantes
RESPIRACION_POR_CONDICION = {
    "reposo": (15, 2),
    "solfeggio": (12, 2),
    "binaural": (11, 2),
    "isocronico": (12, 2),
    "preferencia": (10, 2),
}


def _construir_ajustes_escalados(respuesta_estimulo: float) -> dict:
    """Escala los ajustes de HR por condición de SimuladorCardiaco según el perfil.

    SimuladorCardiaco.AJUSTES_CONDICION trae un ajuste fijo de -6 bpm para
    "preferencia" (ver simulador_cardiaco.py). Acá, "respuesta_estimulo"
    del perfil REEMPLAZA ese -6 por el valor propio de cada participante
    (ej. -8 para alguien muy reactivo, -3 para alguien que casi no
    reacciona), y las demás condiciones (solfeggio, binaural, isocronico,
    estimulo_negativo) se escalan PROPORCIONALMENTE usando el mismo factor:

        factor = respuesta_estimulo / -6.0
        ajuste_escalado[condicion] = ajuste_original[condicion] * factor

    Con esto, un participante muy reactivo (ej. respuesta_estimulo=-8)
    también reacciona más a solfeggio/binaural/isocronico (no solo a su
    estímulo preferido), manteniendo la misma proporción relativa entre
    condiciones que ya tenía SimuladorCardiaco por defecto.

    Args:
        respuesta_estimulo: Ajuste de HR (bpm) del perfil para su estímulo
            preferido — reemplaza el -6 fijo de "preferencia".

    Returns:
        dict: Copia de AJUSTES_CONDICION escalada para este participante,
            lista para asignar como sensor.AJUSTES_CONDICION (atributo de
            INSTANCIA: no debe tocarse el diccionario de clase compartido,
            o afectaría a todos los demás participantes).
    """
    ajuste_base_preferencia = SimuladorCardiaco.AJUSTES_CONDICION["preferencia"]  # -6.0
    factor = respuesta_estimulo / ajuste_base_preferencia
    return {
        condicion: round(ajuste_original * factor, 2)
        for condicion, ajuste_original in SimuladorCardiaco.AJUSTES_CONDICION.items()
    }


def _construir_protocolo_nominal(protocolo_corto: bool) -> list[dict]:
    """Arma el protocolo de bloques (nombre, tipo, duracion_seg) sin depender de WAV reales.

    A diferencia de ReproductorEstimulos.construir_protocolo_ejemplo()
    (que busca archivos WAV reales para saber cuánto dura cada estímulo),
    acá se define la duración nominal directamente en cada bloque —
    necesario porque este módulo no genera audio real (ver docstring del
    módulo) y reproducir_protocolo(silencioso=True) exige "duracion_seg"
    también en los bloques "estimulo".

    Args:
        protocolo_corto: Si True, bloques de segundos (dataset rápido). Si
            False, duraciones reales del protocolo de la tesis.

    Returns:
        list[dict]: Protocolo con las 5 condiciones representadas: reposo
            (baseline/descansos/cierre), solfeggio, binaural, isocronico y
            preferencia.
    """
    if protocolo_corto:
        dur_silencio, dur_descanso, dur_estimulo = 5, 3, 4
    else:
        dur_silencio, dur_descanso, dur_estimulo = 60, 30, 60

    return [
        {"tipo": "silencio", "nombre": "baseline", "duracion_seg": dur_silencio},
        {"tipo": "estimulo", "nombre": "solfeggio_528Hz", "duracion_seg": dur_estimulo},
        {"tipo": "silencio", "nombre": "descanso1", "duracion_seg": dur_descanso},
        {"tipo": "estimulo", "nombre": "binaural_alpha", "duracion_seg": dur_estimulo},
        {"tipo": "silencio", "nombre": "descanso2", "duracion_seg": dur_descanso},
        {"tipo": "estimulo", "nombre": "isocronico_alpha", "duracion_seg": dur_estimulo},
        {"tipo": "silencio", "nombre": "descanso3", "duracion_seg": dur_descanso},
        {"tipo": "estimulo", "nombre": "preferencia_usuario", "duracion_seg": dur_estimulo},
        {"tipo": "silencio", "nombre": "cierre", "duracion_seg": dur_silencio},
    ]


def _generar_lecturas(sensor: SimuladorCardiaco, eventos: list[dict], frecuencia_hz: float = 1.0) -> list[dict]:
    """Genera las lecturas cardíacas del CSV, a ritmo instantáneo (sin esperar tiempo real).

    SimuladorCardiaco.leer() suaviza la HR hacia el objetivo un 15% POR
    LLAMADA (ver simulador_cardiaco.py), no por segundo real transcurrido
    — por eso es matemáticamente válido llamarlo en un loop rápido, sin
    ningún time.sleep(): la trayectoria de HR generada es la misma que si
    se hubiera esperado un segundo real entre cada lectura.

    Para cada timestamp nominal (0, 1, 2, ... según frecuencia_hz), busca
    en eventos qué bloque está vigente en ese instante, y usa su nombre
    para decidir la condición fisiológica a la que reacciona el sensor.

    Args:
        sensor: Instancia de SimuladorCardiaco ya configurada para este participante.
        eventos: Eventos calculados por reproducir_protocolo(silencioso=True).
        frecuencia_hz: Lecturas por segundo (nominal).

    Returns:
        list[dict]: Filas con timestamp, hr_bpm, rr_ms, condicion, estimulo
            — mismo formato que genera CapturaSesion.
    """
    lecturas = []
    duracion_total = eventos[-1]["t_fin"]
    num_lecturas = int(duracion_total * frecuencia_hz) + 1
    condicion_actual = None

    for i in range(num_lecturas):
        timestamp = i / frecuencia_hz
        # Bloque vigente en este instante nominal (el último evento cubre el borde final)
        bloque = next(
            (evento for evento in eventos if evento["t_inicio"] <= timestamp < evento["t_fin"]),
            eventos[-1],
        )
        nombre_estimulo = bloque["nombre"]
        condicion = _condicion_desde_nombre(nombre_estimulo)

        if condicion != condicion_actual:
            sensor.cambiar_condicion(condicion)
            condicion_actual = condicion

        lectura = sensor.leer()
        lecturas.append(
            {
                "timestamp": round(timestamp, 3),
                "hr_bpm": lectura["hr_bpm"],
                "rr_ms": lectura["rr_ms"],
                "condicion": condicion,
                "estimulo": nombre_estimulo,
            }
        )

    return lecturas


def _generar_metadata_audio_simulada(participante_id: str, eventos: list[dict]) -> dict:
    """Arma el JSON de "audio simulado": respiración plausible por bloque, sin WAV real.

    Usa np.random.normal() (ya sembrado por generar_dataset_simulado())
    con el promedio/desviación estándar de RESPIRACION_POR_CONDICION según
    la condición de cada bloque.

    Args:
        participante_id: Identificador del participante, ej. "P01".
        eventos: Eventos calculados por reproducir_protocolo(silencioso=True).

    Returns:
        dict: Metadata con bandera "estado": "audio simulado" y la lista
            respiracion_por_bloque.
    """
    respiracion_por_bloque = []
    for evento in eventos:
        condicion = _condicion_desde_nombre(evento["nombre"])
        promedio_bpm, desviacion_bpm = RESPIRACION_POR_CONDICION[condicion]
        respiraciones_min = round(float(np.random.normal(promedio_bpm, desviacion_bpm)), 1)

        respiracion_por_bloque.append(
            {
                "nombre": evento["nombre"],
                "condicion": condicion,
                "t_inicio": evento["t_inicio"],
                "t_fin": evento["t_fin"],
                "respiraciones_min": respiraciones_min,
            }
        )

    return {
        "estado": "audio simulado",
        "nota": (
            "No se grabó audio real para este participante (dataset sintético, "
            "ver python/simulador_multiparticipante.py). Los valores de "
            "respiraciones_min son estimaciones plausibles por condición, no "
            "mediciones reales de un micrófono."
        ),
        "participante_id": participante_id,
        "respiracion_por_bloque": respiracion_por_bloque,
    }


def generar_dataset_simulado(
    num_participantes: int = 6,
    protocolo_corto: bool = True,
    semilla_random: int = 42,
) -> list[dict]:
    """Genera sesiones completas simuladas para varios participantes con perfiles distintos.

    Args:
        num_participantes: Cuántos perfiles de PERFILES usar (máximo len(PERFILES)).
        protocolo_corto: Si True, bloques de segundos (dataset rápido para
            pruebas). Si False, duraciones reales del protocolo de la tesis.
        semilla_random: Semilla para random.seed() y np.random.seed(), para
            que el dataset generado sea reproducible.

    Returns:
        list[dict]: Uno por participante, con participante_id, descripcion,
            hr_baseline_promedio, hr_final_promedio, diferencia, ruta_csv,
            ruta_json_estimulos, ruta_json_audio_simulado.
    """
    # Dos generadores de números aleatorios distintos en juego (ver docstring del módulo)
    random.seed(semilla_random)
    np.random.seed(semilla_random)

    if num_participantes > len(PERFILES):
        print(
            f"Advertencia: se pidieron {num_participantes} participantes pero solo hay "
            f"{len(PERFILES)} perfiles definidos en PERFILES; se generan {len(PERFILES)}."
        )
    perfiles_a_usar = PERFILES[:num_participantes]

    protocolo_nominal = _construir_protocolo_nominal(protocolo_corto)
    reproductor = ReproductorEstimulos()
    fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")

    resultados = []

    for perfil in perfiles_a_usar:
        print(f"\n=== Generando sesión simulada: {perfil['id']} ({perfil['descripcion']}) ===")

        sensor = SimuladorCardiaco(hr_baseline=perfil["hr_baseline"], variabilidad=perfil["variabilidad"])
        # Atributo de INSTANCIA (no de clase): no afecta a los demás participantes
        sensor.AJUSTES_CONDICION = _construir_ajustes_escalados(perfil["respuesta_estimulo"])

        estado_compartido = {"estimulo_actual": protocolo_nominal[0]["nombre"]}
        eventos = reproductor.reproducir_protocolo(
            protocolo_nominal, estado_compartido=estado_compartido, silencioso=True
        )

        lecturas = _generar_lecturas(sensor, eventos, frecuencia_hz=1.0)

        # Se reutiliza CapturaSesion solo para guardar el CSV con el mismo formato/nombre
        # que una sesión real; ejecutar() no sirve aquí porque espera en tiempo real
        captura = CapturaSesion(sensor=sensor, participante_id=perfil["id"], frecuencia_hz=1.0)
        captura.lecturas = lecturas
        ruta_csv = captura._guardar_csv(fecha_hora=fecha_hora)

        ruta_json_estimulos = CARPETA_SESIONES / f"{perfil['id']}_estimulos_{fecha_hora}.json"
        reproductor.guardar_eventos(eventos, ruta_json_estimulos)

        metadata_audio_simulada = _generar_metadata_audio_simulada(perfil["id"], eventos)
        ruta_json_audio = CARPETA_AUDIO_SESIONES / f"{perfil['id']}_audio_simulado_{fecha_hora}.json"
        ruta_json_audio.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta_json_audio, "w", encoding="utf-8") as archivo:
            json.dump(metadata_audio_simulada, archivo, indent=2, ensure_ascii=False)

        df_lecturas = pd.DataFrame(lecturas)
        hr_baseline_promedio = df_lecturas.loc[df_lecturas["estimulo"] == "baseline", "hr_bpm"].mean()
        hr_final_promedio = df_lecturas.loc[df_lecturas["estimulo"] == "preferencia_usuario", "hr_bpm"].mean()
        diferencia = hr_final_promedio - hr_baseline_promedio

        resultados.append(
            {
                "participante_id": perfil["id"],
                "descripcion": perfil["descripcion"],
                "hr_baseline_promedio": round(hr_baseline_promedio, 1),
                "hr_final_promedio": round(hr_final_promedio, 1),
                "diferencia": round(diferencia, 1),
                "ruta_csv": ruta_csv,
                "ruta_json_estimulos": ruta_json_estimulos,
                "ruta_json_audio_simulado": ruta_json_audio,
            }
        )

        print(f"  CSV:                 {ruta_csv.name}")
        print(f"  JSON estímulos:      {ruta_json_estimulos.name}")
        print(f"  JSON audio simulado: {ruta_json_audio.name}")

    _imprimir_resumen(resultados)

    return resultados


def _imprimir_resumen(resultados: list[dict]) -> None:
    """Imprime la tabla resumen final: HR baseline vs. final por participante.

    Args:
        resultados: Lista devuelta por generar_dataset_simulado().
    """
    print("\n" + "=" * 82)
    print("=== RESUMEN DEL DATASET SIMULADO ===")
    print("=" * 82)

    encabezado = (
        f"{'ID':<5} {'Descripción':<25} {'HR baseline':>12} {'HR final (pref.)':>18} {'Diferencia':>11}"
    )
    print(encabezado)
    print("-" * len(encabezado))
    for r in resultados:
        print(
            f"{r['participante_id']:<5} {r['descripcion']:<25} "
            f"{r['hr_baseline_promedio']:>10.1f}  {r['hr_final_promedio']:>16.1f}  "
            f"{r['diferencia']:>+9.1f}"
        )

    print(f"\nTotal de sesiones generadas: {len(resultados)}")

    print("\nArchivos generados:")
    for r in resultados:
        print(f"  {r['participante_id']}:")
        print(f"    {r['ruta_csv']}")
        print(f"    {r['ruta_json_estimulos']}")
        print(f"    {r['ruta_json_audio_simulado']}")


if __name__ == "__main__":
    resultados = generar_dataset_simulado(num_participantes=6, protocolo_corto=True)

    print("\n=== Participantes y archivos generados ===")
    for r in resultados:
        print(f"{r['participante_id']} ({r['descripcion']}): {r['ruta_csv'].name}")
