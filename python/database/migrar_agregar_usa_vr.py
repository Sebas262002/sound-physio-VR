"""Migración: agrega la columna 'usa_vr' a la tabla 'sesiones' (integración
Meta Quest 2 — ver vr/unity_osc.py, sesion_completa.py y
BaseDatosTesis.crear_sesion()).

Ejecutar una sola vez, después de haber actualizado bd_sqlserver.py con el
parámetro usa_vr en crear_sesion(). Es seguro correrlo más de una vez: si la
columna ya existe, no hace nada (no falla, no duplica).

Uso:
    python database/migrar_agregar_usa_vr.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bd_sqlserver import BaseDatosTesis  # noqa: E402


def migrar() -> None:
    """Agrega sesiones.usa_vr (BIT NOT NULL DEFAULT 0) si todavía no existe."""
    bd = BaseDatosTesis()
    if not bd.conectar():
        print("No se pudo conectar a SQL Server — revisá C:\\Tesis_Kevin\\.env.")
        return

    ya_existe = bd.ejecutar_query(
        "SELECT 1 AS existe FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = 'sesiones' AND COLUMN_NAME = 'usa_vr'"
    )
    if ya_existe:
        print("La columna 'usa_vr' ya existe en 'sesiones' — nada que migrar.")
        return

    bd.ejecutar_query("ALTER TABLE sesiones ADD usa_vr BIT NOT NULL DEFAULT 0")
    print("Columna 'usa_vr' agregada a 'sesiones' (BIT NOT NULL DEFAULT 0).")


if __name__ == "__main__":
    migrar()
