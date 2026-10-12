"""Migración: agrega las columnas 'dia_sesion' y 'valida' a la tabla 'sesiones'.

- dia_sesion INT NULL: día del protocolo (1 a 5). Las sesiones ya guardadas
  quedan con NULL; analisis_intrasujeto.py infiere su día por orden cronológico.
- valida BIT NOT NULL DEFAULT 1: 0 marca una sesión descartada del análisis
  (repetida o con señal defectuosa), ver BaseDatosTesis.marcar_sesion_invalida().

Es seguro correrlo más de una vez: cada columna se agrega solo si no existe.
NO borra ni modifica filas existentes (las sesiones previas quedan valida = 1).

Uso:
    python database/migrar_agregar_dia_valida.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bd_sqlserver import BaseDatosTesis  # noqa: E402

COLUMNAS_NUEVAS = {
    "dia_sesion": "INT NULL",
    "valida": "BIT NOT NULL DEFAULT 1",
}


def migrar() -> None:
    """Agrega sesiones.dia_sesion y sesiones.valida si todavía no existen."""
    bd = BaseDatosTesis()
    if not bd.conectar():
        print("No se pudo conectar a SQL Server — revisa el contenedor Docker y C:\\Tesis_Kevin\\.env.")
        return

    for columna, definicion in COLUMNAS_NUEVAS.items():
        ya_existe = bd.ejecutar_query(
            "SELECT 1 AS existe FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'sesiones' AND COLUMN_NAME = ?",
            (columna,),
        )
        if ya_existe:
            print(f"La columna '{columna}' ya existe en 'sesiones' — nada que migrar.")
            continue
        bd.ejecutar_query(f"ALTER TABLE sesiones ADD {columna} {definicion}")
        print(f"Columna '{columna}' agregada a 'sesiones' ({definicion}).")

    bd.desconectar()


if __name__ == "__main__":
    migrar()
