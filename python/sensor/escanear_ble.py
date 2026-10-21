"""Escaneo de dispositivos Bluetooth Low Energy (BLE) cercanos para localizar el
sensor cardíaco Wahoo TRACKR HR y anotar su dirección MAC.

Script de diagnóstico de una sola vez: no es parte del pipeline de captura
de datos, es la herramienta previa para descubrir la MAC del sensor real y
poder codificarla en el futuro sensor_wahoo.py (el módulo que reemplazará
a SimuladorCardiaco, ver python/sensor/simulador_cardiaco.py, cuando se
conecte el hardware real en vez de seguir simulando).

¿Por qué async/await con bleak? El Bluetooth es inherentemente asíncrono:
escanear significa "quedarse escuchando" anuncios (advertisements) que los
dispositivos BLE cercanos transmiten por su cuenta, en momentos que no
controla nuestro programa. bleak (la librería que envuelve el Bluetooth
del sistema operativo) expone esa espera como una corrutina async en vez
de bloquear el hilo con time.sleep(): mientras se espera, Python puede
seguir atendiendo otras tareas. Acá el script no tiene nada más que hacer
mientras espera, pero es el patrón correcto de bleak y el que hace falta
cuando esto se integre a un programa más grande (ej. junto a Unity vía
python-osc, donde sí habría otras cosas corriendo al mismo tiempo).

¿Qué es la MAC address y para qué la necesitamos? Es el identificador
físico de 6 bytes (ej. "AA:BB:CC:DD:EE:FF") grabado de fábrica en cada
adaptador Bluetooth. A diferencia del nombre del dispositivo (que puede
repetirse entre varias unidades del mismo modelo, o venir vacío), la MAC
es inequívoca: es la dirección exacta que sensor_wahoo.py usará para
conectarse A ESE sensor específico sin volver a escanear ni arriesgarse a
conectar por error a otro Wahoo si hubiera más de uno cerca (ej. en un
laboratorio con varios equipos).

¿Por qué 15 segundos de timeout? Los dispositivos BLE no transmiten su
anuncio todo el tiempo: lo hacen en intervalos (típicamente entre 100 ms y
1 s, más lento aún en dispositivos que cuidan batería). Un timeout muy
corto (ej. 3s) podría no alcanzar a capturar ni un solo anuncio del sensor
si el intervalo es largo o hay interferencia en el entorno; 15s da margen
de sobra para varias rondas de anuncio incluso en el peor caso, sin hacer
esperar demasiado a quien está corriendo el diagnóstico.
"""

import asyncio

from bleak import BleakScanner
from bleak.backends.device import BLEDevice


SERVICIO_FRECUENCIA_CARDIACA = "0000180d-0000-1000-8000-00805f9b34fb"
"""UUID estándar Bluetooth SIG del "Heart Rate Service": todo sensor de
frecuencia cardíaca BLE (de cualquier marca) lo anuncia, incluso cuando el
nombre del dispositivo no viene en el paquete de anuncio que bleak lee por
default (algunos sensores, el Wahoo TRACKR incluido, solo entregan el
nombre en una respuesta de escaneo adicional que Windows sí pide pero
BleakScanner.discover() no pide por default). Filtrar por este UUID en vez
de por el nombre encuentra el sensor aunque aparezca como "(sin nombre)".
"""


async def escanear_dispositivos(timeout_seg: float = 15.0) -> dict[BLEDevice, list[str]]:
    """Escanea dispositivos BLE cercanos durante timeout_seg segundos.

    Args:
        timeout_seg: Duración del escaneo, en segundos (default 15.0).

    Returns:
        dict[BLEDevice, list[str]]: Dispositivos BLE encontrados, mapeados a
            la lista de UUID de servicio que cada uno anuncia (puede venir
            vacía si el dispositivo no anuncia servicios).
    """
    print(f"Escaneando dispositivos BLE durante {timeout_seg:.0f} segundos...")
    print("(asegúrate de que el sensor Wahoo TRACKR HR esté encendido y cerca)\n")

    # return_adv=True devuelve también los AdvertisementData de cada
    # dispositivo (incluye .service_uuids), no solo el BLEDevice básico
    resultado = await BleakScanner.discover(timeout=timeout_seg, return_adv=True)
    return {dispositivo: adv.service_uuids for dispositivo, adv in resultado.values()}


def _imprimir_tabla_dispositivos(dispositivos: dict[BLEDevice, list[str]]) -> None:
    """Imprime una tabla alineada con nombre, MAC y servicios de cada dispositivo.

    Args:
        dispositivos: Diccionario devuelto por escanear_dispositivos().
    """
    print(f"=== Dispositivos BLE encontrados: {len(dispositivos)} ===\n")

    if not dispositivos:
        print("  (ningún dispositivo respondió durante el escaneo)")
        return

    # Ancho de columna dinámico según el nombre más largo, para que la tabla
    # quede alineada sin importar qué dispositivos haya alrededor
    ancho_nombre = max((len(dispositivo.name or "(sin nombre)") for dispositivo in dispositivos))
    ancho_nombre = max(ancho_nombre, len("Nombre"))

    encabezado = f"{'Nombre':<{ancho_nombre}}  {'MAC':<17}  {'¿Frec. cardíaca?':<17}"
    print(encabezado)
    print("-" * len(encabezado))

    for dispositivo, uuids in dispositivos.items():
        nombre = dispositivo.name or "(sin nombre)"
        es_cardiaco = "<-- SÍ (este es)" if SERVICIO_FRECUENCIA_CARDIACA in uuids else ""
        print(f"{nombre:<{ancho_nombre}}  {dispositivo.address:<17}  {es_cardiaco}")


def _buscar_wahoo(dispositivos: dict[BLEDevice, list[str]]) -> list[BLEDevice]:
    """Filtra los dispositivos que anuncian el Heart Rate Service o cuyo nombre
    contenga 'wahoo'/'trackr' (sin distinguir mayúsculas).

    El filtro por servicio va primero porque es el confiable: algunos
    sensores, el Wahoo TRACKR incluido, no siempre entregan el nombre en el
    paquete de anuncio que lee bleak (ver SERVICIO_FRECUENCIA_CARDIACA).

    Args:
        dispositivos: Diccionario devuelto por escanear_dispositivos().

    Returns:
        list[BLEDevice]: Subconjunto de dispositivos que coinciden con el sensor buscado.
    """
    coincidencias = []
    for dispositivo, uuids in dispositivos.items():
        nombre = (dispositivo.name or "").lower()
        if SERVICIO_FRECUENCIA_CARDIACA in uuids or "wahoo" in nombre or "trackr" in nombre:
            coincidencias.append(dispositivo)
    return coincidencias


def _imprimir_resultado_busqueda(coincidencias: list[BLEDevice]) -> None:
    """Imprime el resultado de la búsqueda específica del Wahoo TRACKR HR.

    Args:
        coincidencias: Dispositivos devueltos por _buscar_wahoo().
    """
    print("\n=== Búsqueda específica: Wahoo / TRACKR ===\n")

    if coincidencias:
        for dispositivo in coincidencias:
            print("[OK] WAHOO ENCONTRADO")
            print(f"  Nombre: {dispositivo.name}")
            print(f"  MAC:    {dispositivo.address}")
            print("  Guarda esta MAC para usarla en sensor_wahoo.py\n")
    else:
        print("[!] No se encontró ningún Wahoo/TRACKR\n")
        print("Sugerencias:")
        print("  - Verifica que el sensor tenga los electrodos húmedos")
        print("  - Verifica que el LED azul esté parpadeando")
        print("  - Verifica que no esté conectado a otro dispositivo (ej. el celular)")
        print("  - Reintenta el escaneo (python escanear_ble.py)")


async def main() -> None:
    """Punto de entrada asíncrono: escanea, imprime la tabla y busca el Wahoo."""
    try:
        dispositivos = await escanear_dispositivos(timeout_seg=15.0)
    except Exception as error:
        print(f"Error al escanear BLE: {error}")
        print("¿Está el Bluetooth de la PC encendido? ¿bleak tiene permisos del sistema?")
        return

    _imprimir_tabla_dispositivos(dispositivos)
    coincidencias = _buscar_wahoo(dispositivos)
    _imprimir_resultado_busqueda(coincidencias)


if __name__ == "__main__":
    # asyncio.run() crea el event loop, corre main() hasta que termina, y lo cierra:
    # es el punto de entrada estándar para un script async de arriba a abajo
    asyncio.run(main())
