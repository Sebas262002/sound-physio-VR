"""Diagnóstico: lista los dispositivos de audio disponibles en el sistema.

Script de utilidad para elegir el micrófono lavalier correcto antes de
capturar respiración (ver python/audio/). No define ninguna clase: solo
imprime en consola lo que sounddevice/PortAudio detecta en la máquina.
"""

import sounddevice as sd


if __name__ == "__main__":
    dispositivos = sd.query_devices()
    indice_entrada_defecto = sd.default.device[0]  # [0]=entrada, [1]=salida
    ancho_indice = len(str(len(dispositivos) - 1))  # ancho dinámico según cuántos dispositivos hay

    print("=== Dispositivos de audio disponibles ===\n")

    encabezado = (
        f"{'':>3} {'Idx':>{ancho_indice}} {'Nombre':<45} "
        f"{'Entrada':>8} {'Salida':>8} {'Frec. (Hz)':>11}"
    )
    print(encabezado)
    print("-" * len(encabezado))

    for indice, dispositivo in enumerate(dispositivos):
        # Se marca con >>> el dispositivo de entrada usado automáticamente por sounddevice
        marca = ">>>" if indice == indice_entrada_defecto else "   "
        # Algunos nombres de dispositivos Bluetooth traen saltos de línea; se limpian para no romper la tabla
        nombre = dispositivo["name"].replace("\n", " ").replace("\r", " ").strip()
        print(
            f"{marca} {indice:>{ancho_indice}} {nombre:<45} "
            f"{dispositivo['max_input_channels']:>8} "
            f"{dispositivo['max_output_channels']:>8} "
            f"{dispositivo['default_samplerate']:>11.0f}"
        )

    print(
        "\nPara el proyecto necesitamos un dispositivo con canales de entrada > 0.\n"
        "El dispositivo por defecto marcado con >>> es el que se usará automáticamente."
    )
