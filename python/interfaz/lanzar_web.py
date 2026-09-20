"""Lanza el panel del investigador en el NAVEGADOR (modo web de Flet).

No modifica app_investigador.py: solo importa su main() y lo sirve por HTTP en
lugar de abrir la ventana de escritorio. Como el código Python sigue corriendo
en ESTA computadora, el sensor Wahoo (BLE), el audio, el puente OSC hacia Unity
y SQL Server funcionan exactamente igual; el navegador es solo la pantalla.

El servidor escucha únicamente en 127.0.0.1 (esta PC): nadie más de la red puede
abrir el panel ni ver los datos de los participantes.

Diferencias a tener en cuenta frente a la ventana de escritorio:
    - Cada pestaña (o cada recarga con F5) crea una instancia NUEVA de la app.
      No recargues ni cierres la pestaña mientras hay una sesión en curso.
    - El tamaño de ventana que fija la app (1440x920) lo ignora el navegador;
      usa pantalla completa o un zoom que muestre todo el panel.
    - Para detener todo, cierra esta consola o presiona Ctrl+C.

Uso:
    python python/interfaz/lanzar_web.py                # abre el navegador
    python python/interfaz/lanzar_web.py --puerto 8600  # otro puerto
    python python/interfaz/lanzar_web.py --sin-abrir    # solo sirve, sin abrir el navegador
"""

import argparse
import os
import sys
from pathlib import Path

import flet as ft

CARPETA_INTERFAZ = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA_INTERFAZ))

from app_investigador import main  # noqa: E402

HOST_LOCAL = "127.0.0.1"
PUERTO_DEFAULT = 8550


def lanzar(puerto: int = PUERTO_DEFAULT, abrir_navegador: bool = True) -> None:
    """Sirve el panel del investigador por HTTP en localhost.

    Args:
        puerto: Puerto local donde escucha el servidor.
        abrir_navegador: Si True, abre el navegador predeterminado en la URL;
            si False, solo deja el servidor corriendo (abrir a mano
            http://127.0.0.1:<puerto>).
    """
    print(f"Panel del investigador en http://{HOST_LOCAL}:{puerto}  (Ctrl+C para detener)")
    if not abrir_navegador:
        # view=None arrancaría el servidor de la ventana de escritorio, no HTTP. Esta
        # variable de Flet fuerza el servidor web sin abrir el navegador.
        os.environ["FLET_FORCE_WEB_SERVER"] = "true"
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        host=HOST_LOCAL,
        port=puerto,
        assets_dir=str(CARPETA_INTERFAZ / "assets"),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Panel del investigador en el navegador.")
    parser.add_argument("--puerto", type=int, default=PUERTO_DEFAULT)
    parser.add_argument("--sin-abrir", action="store_true", help="no abrir el navegador automáticamente")
    argumentos = parser.parse_args()
    lanzar(argumentos.puerto, abrir_navegador=not argumentos.sin_abrir)
