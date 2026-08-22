"""Test de regresión de la integración VR: valida el protocolo REAL de 9 bloques.

A diferencia de la primera versión de este script (que usaba un protocolo de
3 bloques con nombres de skybox inventados, independientes del código real),
esta versión llama a obtener_protocolo_tesis_final(usar_vr=True) de verdad —
la misma función que usa la app en producción — con duraciones cortas para
que la corrida entera tome ~25s en vez de los ~7.5 min del protocolo de
tesis real. La secuencia esperada de mensajes OSC se DERIVA de esa llamada
(que a su vez usa _AMBIENTE_VR_POR_BLOQUE, importado acá solo para trazar el
mapeo en el output — no se hardcodea ningún nombre de skybox en este
archivo): si el mapeo cambia mañana, este test lo detecta solo.

Levanta un "Unity falso" (servidor OSC en 127.0.0.1:8000) y corre
ejecutar_sesion_completa() de verdad (sensor simulado, sin audio real, sin
guardar en BD) — no mockea nada del lado Python.

Sale con exit code 1 si la secuencia recibida no coincide con la esperada
(sirve como test de regresión real, no solo un smoke test).

Uso:
    python vr/probar_integracion.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pythonosc import dispatcher, osc_server, udp_client  # noqa: E402

import sesion_completa as sc  # noqa: E402
from sesion_completa import _AMBIENTE_VR_POR_BLOQUE  # noqa: E402

ID_PARTICIPANTE_PRUEBA = "P_TEST_VR_SESION"

# Duraciones cortas: 3+2s en vez de 60+30s — mismos 9 bloques del protocolo
# real de tesis (baseline, 4 estímulos, 3 descansos, cierre), corriendo en
# ~25s en vez de ~7.5 min. Nada de esto toca duracion_estimulo_seg/etc. por
# defecto de obtener_protocolo_tesis_final() en producción — son argumentos
# explícitos, solo para esta corrida de prueba.
DURACION_BASELINE_PRUEBA = 3
DURACION_ESTIMULO_PRUEBA = 3
DURACION_DESCANSO_PRUEBA = 2
DURACION_CIERRE_PRUEBA = 3


def _mensajes_esperados(protocolo: list) -> list:
    """Deriva la secuencia esperada de mensajes OSC (dirección, args) a partir
    del protocolo YA RESUELTO por obtener_protocolo_tesis_final(usar_vr=True)
    — no reimplementa la regla de herencia de descansos, solo lee
    "ambiente_vr" bloque por bloque y deduplica valores consecutivos (mismo
    criterio que _hilo_observador_vr en sesion_completa.py: un descanso que
    hereda el mismo skybox del bloque anterior no genera un /ambiente nuevo).
    """
    esperado = [("/sesion/iniciar", (ID_PARTICIPANTE_PRUEBA,))]
    ultimo_ambiente = None
    for bloque in protocolo:
        ambiente = bloque.get("ambiente_vr")
        if ambiente is not None and ambiente != ultimo_ambiente:
            esperado.append(("/ambiente", (ambiente,)))
            ultimo_ambiente = ambiente
    esperado.append(("/sesion/terminar", ()))
    return esperado


def main() -> int:
    print("=== Mapeo actual (_AMBIENTE_VR_POR_BLOQUE, sesion_completa.py) ===")
    for nombre, ambiente in _AMBIENTE_VR_POR_BLOQUE.items():
        print(f"  {nombre:20s} -> {ambiente}")
    print()

    mensajes_recibidos = []

    def capturar(direccion: str, *args) -> None:
        mensajes_recibidos.append((direccion, args))
        print(f"[UNITY FALSO] {direccion} {args}")
        if direccion == "/ping" and args:
            udp_client.SimpleUDPClient("127.0.0.1", args[0]).send_message("/pong", None)

    disp = dispatcher.Dispatcher()
    disp.set_default_handler(capturar)
    server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 8000), disp)
    hilo_unity = threading.Thread(target=server.serve_forever, daemon=True)
    hilo_unity.start()
    time.sleep(0.3)

    protocolo = sc.obtener_protocolo_tesis_final(
        duracion_baseline_seg=DURACION_BASELINE_PRUEBA,
        duracion_estimulo_seg=DURACION_ESTIMULO_PRUEBA,
        duracion_descanso_seg=DURACION_DESCANSO_PRUEBA,
        duracion_cierre_seg=DURACION_CIERRE_PRUEBA,
        usar_vr=True,
    )
    duracion_estimada = sc._calcular_duracion_total_protocolo(protocolo)
    print(f"=== Protocolo real de {len(protocolo)} bloques, ~{duracion_estimada:.0f}s ===\n")

    esperados = _mensajes_esperados(protocolo)

    resultado = sc.ejecutar_sesion_completa(
        ID_PARTICIPANTE_PRUEBA,
        protocolo_personalizado=protocolo,
        usar_sensor_real=False,
        silencioso_estimulos=True,
        tiempo_estabilizacion_seg=0,
        analizar_automaticamente=False,
        guardar_en_bd=False,
        usar_vr=True,
    )

    time.sleep(0.5)
    server.shutdown()

    # Limpieza: esta prueba genera CSV/WAV/JSON reales en datos/sesiones/ — se
    # borran acá porque son descartables (participante de prueba).
    for ruta in [resultado.get("ruta_csv"), resultado.get("ruta_wav"), resultado.get("ruta_json_estimulos")]:
        if ruta and Path(ruta).exists():
            Path(ruta).unlink()
            print(f"Limpiado: {ruta}")

    print("\n=== RESULTADO ===")
    print("Esperado: ", esperados)
    print("Recibido: ", mensajes_recibidos)

    if mensajes_recibidos == esperados:
        print("\nOK: la secuencia recibida coincide EXACTAMENTE con la derivada de _AMBIENTE_VR_POR_BLOQUE.")
        return 0

    print("\nFALLO: la secuencia recibida NO coincide con la esperada.")
    if len(mensajes_recibidos) != len(esperados):
        print(f"  Cantidad de mensajes distinta: esperados={len(esperados)}, recibidos={len(mensajes_recibidos)}")
    for i, (esp, rec) in enumerate(zip(esperados, mensajes_recibidos)):
        if esp != rec:
            print(f"  Difieren en la posición {i}: esperado={esp}, recibido={rec}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
