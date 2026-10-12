"""Migración: elimina la columna 'ruta_preferencia_wav_2' de la tabla 'participantes'.

El protocolo pasó de pedir 2 canciones de preferencia distintas (Día 2 y
Día 4) a reutilizar una sola canción (ruta_preferencia_wav) en Día 2, Día 4
y, si corresponde, Día 5 — ver PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS en
el docstring de sesion_completa.py. ruta_preferencia_wav_2 ya no se usa en
ningún lado del código; esta migración borra la columna y, con ella, los
valores que ya tuviera guardados (no hay forma de "borrar la columna pero
conservar los datos" — si necesitás conservarlos, respaldalos antes de
correr esto).

Es seguro correrlo más de una vez: si la columna ya no existe, no hace nada.

Uso:
    python database/migrar_quitar_preferencia_2.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bd_sqlserver import BaseDatosTesis  # noqa: E402

COLUMNA = "ruta_preferencia_wav_2"


def migrar() -> None:
    """Elimina participantes.ruta_preferencia_wav_2 si todavía existe."""
    bd = BaseDatosTesis()
    if not bd.conectar():
        print("No se pudo conectar a SQL Server — revisa el contenedor Docker y C:\\Tesis_Kevin\\.env.")
        return

    ya_existe = bd.ejecutar_query(
        "SELECT 1 AS existe FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = 'participantes' AND COLUMN_NAME = ?",
        (COLUMNA,),
    )
    if not ya_existe:
        print(f"La columna '{COLUMNA}' ya no existe en 'participantes' — nada que migrar.")
        bd.desconectar()
        return

    bd.ejecutar_query(f"ALTER TABLE participantes DROP COLUMN {COLUMNA}")
    print(f"Columna '{COLUMNA}' eliminada de 'participantes'.")

    bd.desconectar()


if __name__ == "__main__":
    migrar()
