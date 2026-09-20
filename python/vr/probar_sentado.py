"""Prueba manual y rápida de la confirmación de "sentado" (ver
esperar_confirmacion_sentado() en unity_osc.py) — NO corre ninguna sesión
real: no toca el sensor Wahoo ni graba audio ni guarda nada en la BD. Solo
valida que el mensaje OSC "/sesion/inicio" que manda SesionStateMachine.cs
(tras SentarseTrigger.cs) le llega de verdad a Python por el puerto 9000.

Uso:
    1. Abrí la escena de Unity y presioná Play (con el Quest 2 conectado,
       por cable o Air Link, da igual).
    2. Corré este script (ver instrucciones más abajo).
    3. Ponete el Quest, caminá y sentate en la silla.
    4. Si todo anda bien, el script se destraba solo e imprime "CONFIRMADO".
       Ctrl+C en la terminal cancela la espera en cualquier momento.
"""

import sys

sys.path.insert(0, r"C:\Tesis_Kevin\python")

from vr.unity_osc import UnityOSC  # noqa: E402


def main() -> int:
    cliente = UnityOSC()

    print("Avisándole a Unity que 'arrancó' una sesión de prueba (/sesion/iniciar)...")
    if not cliente.iniciar_sesion("PRUEBA_SENTADO"):
        print("ERROR: no se pudo mandar el mensaje a Unity — ¿está la escena corriendo con Play presionado?")
        return 1

    print("Esperando confirmación de que te sentaste (Ctrl+C para cancelar)...\n")
    confirmado = cliente.esperar_confirmacion_sentado()

    if confirmado:
        print("\nCONFIRMADO: Python recibió '/sesion/inicio' de Unity. La integración funciona.")
        return 0

    print("\nNO CONFIRMADO: no llegó nada (o se canceló con Ctrl+C).")
    print("Revisá: ¿la escena sigue en Play?, ¿el trigger de la silla disparó el evento en la")
    print("consola de Unity?, ¿el puerto 9000 está libre en esta PC (nada más lo está usando)?")
    return 1


if __name__ == "__main__":
    sys.exit(main())
