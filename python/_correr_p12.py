"""Sesión piloto P12 — Día 1 del protocolo experimental final de la tesis
(dia=1, ver obtener_protocolo_sesion_dia() en sesion_completa.py): baseline
-> UN estímulo (sorteado para P12 por asignar_estimulos_dia1_dia3()) ->
cierre. Días 2 (preferencia, requiere preferencia_wav) y 3 (el otro
estímulo sorteado) se corren por separado, con 24-48h de diferencia, cada
uno con este mismo script cambiando solo dia=2/dia=3.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Tesis_Kevin\python")
from sesion_completa import ejecutar_sesion_completa

resultado = ejecutar_sesion_completa(
    participante_id="P12",
    usar_sensor_real=True,
    reproducir_audio_real=True,
    dia=1,
    preferencia_wav=Path("C:/Tesis_Kevin/audio_estimulos/preferencias/mi_cancion.wav"),
    tiempo_estabilizacion_seg=30,
)

print("\n=== Rutas generadas (P12) ===")
print(f"CSV cardíaco:   {resultado['ruta_csv']}")
print(f"WAV audio:      {resultado['ruta_wav']}")
print(f"JSON estímulos: {resultado['ruta_json_estimulos']}")
print(f"Duración total: {resultado['duracion_total_seg']}s")
print(f"Reporte:        {resultado['ruta_reporte']}")
