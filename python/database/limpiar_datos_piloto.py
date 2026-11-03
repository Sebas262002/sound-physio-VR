"""Borra por completo las sesiones piloto (P01-P12, P001-P019) y limpia la
base de datos antes de empezar la recolección real con los participantes
definitivos.

QUÉ HACE, EN ORDEN:
1. Respalda el contenido ACTUAL de participantes/sesiones/pruebas a CSV
   (datos/backups/, con marca de tiempo) — ÚNICO rastro que se conserva, por
   si hace falta recuperar algo tras un error de operador (ej. confirmar el
   borrado por accidente). Son 3 archivos chicos, no "asoman" resultados.
2. Borra todas las filas de pruebas, sesiones y participantes (en ese orden,
   por las llaves foráneas) — deja la base completamente vacía para arrancar
   con P001 real sin colisión.
3. Borra para siempre (no archiva) los archivos de sesión piloto de
   datos/sesiones/ (CSV, JSON de eventos y WAV), datos/procesados/ (CSV
   unificados de sincronizador.py), y TODO el contenido de
   resultados/exportados/, resultados/graficas/, resultados/reportes/ y
   resultados/tablas/ (PDF, Excel, PNG, .md generados mientras se probaba
   el sistema) — a pedido explícito del usuario, para que no quede ningún
   resultado de prueba asomando por ninguna carpeta. Las carpetas en sí NO
   se borran (el sistema las espera ahí), solo su contenido.

Lo ÚNICO que sobrevive es el respaldo CSV de la base de datos en
datos/backups/ (paso 1). Todo lo demás se borra de verdad, sin papelera.

Pensado para correrse UNA sola vez, justo antes de registrar al primer
participante real. Pide confirmación explícita antes de borrar nada.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\Tesis_Kevin\python\database")
from bd_sqlserver import BaseDatosTesis  # noqa: E402

RAIZ = Path(r"C:\Tesis_Kevin")
CARPETA_SESIONES = RAIZ / "datos" / "sesiones"
CARPETA_BACKUPS = RAIZ / "datos" / "backups"
CARPETA_PROCESADOS = RAIZ / "datos" / "procesados"
CARPETA_RESULTADOS = RAIZ / "resultados"
# Subcarpetas de resultados/ que se vacían por completo (PDF, Excel, gráficas,
# reportes .md de las sesiones piloto/pruebas propias) — ver reportes/,
# graficas/ y exportados/ ya usados por app_investigador.py y analisis_grupal.py.
SUBCARPETAS_RESULTADOS = ["exportados", "graficas", "reportes", "tablas"]

TABLAS = ["pruebas", "sesiones", "participantes"]  # orden de borrado por FK


def respaldar_tabla(bd: BaseDatosTesis, tabla: str, sufijo: str) -> int:
    """Exporta el contenido completo de una tabla a CSV antes de borrarla.

    Returns:
        int: número de filas respaldadas.
    """
    filas = bd.ejecutar_query(f"SELECT * FROM {tabla}")
    filas = filas or []
    CARPETA_BACKUPS.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_BACKUPS / f"antes_de_limpiar_{tabla}_{sufijo}.csv"
    if filas:
        columnas = list(filas[0].keys())
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            f.write(",".join(columnas) + "\n")
            for fila in filas:
                f.write(",".join(str(fila[c]) if fila[c] is not None else "" for c in columnas) + "\n")
    else:
        ruta.write_text("", encoding="utf-8-sig")
    print(f"  Respaldado {tabla}: {len(filas)} fila(s) -> {ruta.name}")
    return len(filas)


def vaciar_carpeta(carpeta: Path) -> int:
    """Borra TODO el contenido de carpeta/ (archivos y subcarpetas), sin
    borrar la carpeta en sí — el sistema espera encontrarla ahí.

    Returns:
        int: número de archivos borrados (las subcarpetas no cuentan aparte).
    """
    if not carpeta.exists():
        return 0
    borrados = 0
    for ruta in carpeta.rglob("*"):
        if ruta.is_file():
            ruta.unlink()
            borrados += 1
    # Limpia subcarpetas que hayan quedado vacías (ej. datos/sesiones/audio/),
    # de adentro hacia afuera para no fallar por carpetas no vacías.
    for ruta in sorted(carpeta.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if ruta.is_dir():
            try:
                ruta.rmdir()
            except OSError:
                pass  # no estaba vacía (no debería pasar, pero no es motivo para fallar)
    return borrados


def borrar_archivos_piloto() -> None:
    """Borra para siempre el contenido de datos/sesiones/, datos/procesados/
    y las subcarpetas de resultados/ (exportados, graficas, reportes, tablas).
    """
    n = vaciar_carpeta(CARPETA_SESIONES)
    print(f"  datos/sesiones/: {n} archivo(s) borrado(s).")

    n = vaciar_carpeta(CARPETA_PROCESADOS)
    print(f"  datos/procesados/: {n} archivo(s) borrado(s).")

    for nombre in SUBCARPETAS_RESULTADOS:
        n = vaciar_carpeta(CARPETA_RESULTADOS / nombre)
        print(f"  resultados/{nombre}/: {n} archivo(s) borrado(s).")


def limpiar_todo() -> None:
    sufijo = datetime.now().strftime("%Y%m%d_%H%M")

    print("=== Conectando a SQL Server ===")
    bd = BaseDatosTesis()
    if not bd.conectar():
        print("No se pudo conectar. Revisa tu .env y que SQL Server esté corriendo.")
        raise SystemExit(1)

    try:
        print("\n=== Paso 1: Respaldo de las tablas actuales (datos/backups/) ===")
        total_filas = sum(respaldar_tabla(bd, tabla, sufijo) for tabla in TABLAS)

        print(f"\nSe respaldaron {total_filas} fila(s) en total.")
        print(
            "\nADVERTENCIA: esto va a BORRAR PARA SIEMPRE las sesiones de prueba, los CSV/JSON/WAV, "
            "los PDF/Excel/gráficas exportados y los CSV procesados. Solo sobrevive el respaldo CSV "
            "de la base de datos que se acaba de guardar en datos/backups/."
        )
        respuesta = input("¿Confirmas que quieres borrar todo esto? Escribe 'si' para continuar: ").strip().lower()
        if respuesta != "si":
            print("Cancelado. No se borró nada.")
            return

        print("\n=== Paso 2: Borrando filas de la base de datos ===")
        for tabla in TABLAS:
            bd.ejecutar_query(f"DELETE FROM {tabla}")
            print(f"  {tabla}: limpiada.")

    finally:
        bd.desconectar()

    print("\n=== Paso 3: Borrando archivos de sesión, procesados y resultados piloto ===")
    borrar_archivos_piloto()

    print("\n=== Listo ===")
    print("La base de datos quedó vacía y lista para registrar participantes reales desde P001.")
    print("Las carpetas de trabajo (datos/sesiones/, datos/procesados/, resultados/*) quedaron")
    print("completamente vacías, listas para arrancar como si fuera la primera vez.")
    print(f"Lo único que sobrevivió es el respaldo CSV de la base de datos, en {CARPETA_BACKUPS}.")


if __name__ == "__main__":
    limpiar_todo()
