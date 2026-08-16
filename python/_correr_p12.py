"""Sesión piloto P12 — primera corrida del PROTOCOLO EXPERIMENTAL FINAL de
la tesis (usar_protocolo_final=True, ver obtener_protocolo_tesis_final()
en sesion_completa.py): baseline -> solfeggio_528Hz -> descanso ->
binaural_alpha -> descanso -> isocronico_alpha -> descanso -> preferencia
-> cierre. 450s capturados + 30s estabilización = 480s (8 min) de pared.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Tesis_Kevin\python")
from sesion_completa import ejecutar_sesion_completa

resultado = ejecutar_sesion_completa(
    participante_id="P12",
    usar_sensor_real=True,
    reproducir_audio_real=True,
    usar_protocolo_final=True,
    preferencia_wav=Path("C:/Tesis_Kevin/audio_estimulos/preferencias/mi_cancion.wav"),
    tiempo_estabilizacion_seg=30,
)

print("\n=== Rutas generadas (P12) ===")
print(f"CSV cardíaco:   {resultado['ruta_csv']}")
print(f"WAV audio:      {resultado['ruta_wav']}")
print(f"JSON estímulos: {resultado['ruta_json_estimulos']}")
print(f"Duración total: {resultado['duracion_total_seg']}s")
print(f"Reporte:        {resultado['ruta_reporte']}")
