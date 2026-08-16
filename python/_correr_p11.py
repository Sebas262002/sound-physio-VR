"""Sesión piloto COMPLETA P11 — incluye el bloque de preferencia personal,
que valida la hipótesis central de la tesis (comparar respuesta fisiológica
ante Solfeggio 528Hz vs. la música de preferencia personal del participante).

Protocolo: estabilización(30s, descartada) -> baseline(30s) ->
solfeggio_528Hz(60s) -> descanso1(30s) -> preferencia(60s) -> cierre(30s).
Duración capturada ~3.5 min, ~4 min contando estabilización.
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Tesis_Kevin\python")
from sesion_completa import ejecutar_sesion_completa

protocolo_p11 = [
    {"tipo": "silencio", "duracion_seg": 30, "nombre": "baseline"},
    {"tipo": "estimulo", "nombre": "solfeggio_528Hz", "duracion_seg": 60},
    {"tipo": "silencio", "duracion_seg": 30, "nombre": "descanso1"},
    {"tipo": "estimulo", "nombre": "preferencia", "duracion_seg": 60},
    {"tipo": "silencio", "duracion_seg": 30, "nombre": "cierre"},
]

resultado = ejecutar_sesion_completa(
    participante_id="P11",
    usar_sensor_real=True,
    reproducir_audio_real=True,
    preferencia_wav=Path("C:/Tesis_Kevin/audio_estimulos/preferencias/mi_cancion.wav"),
    protocolo_personalizado=protocolo_p11,
    tiempo_estabilizacion_seg=30,
)

print("\n=== Rutas generadas (P11) ===")
print(f"CSV cardíaco:   {resultado['ruta_csv']}")
print(f"WAV audio:      {resultado['ruta_wav']}")
print(f"JSON estímulos: {resultado['ruta_json_estimulos']}")
print(f"Duración total: {resultado['duracion_total_seg']}s")
print(f"Reporte:        {resultado['ruta_reporte']}")
