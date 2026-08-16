"""Driver real del sensor cardíaco Wahoo TRACKR HR, vía BLE (Bluetooth Low Energy).

Reemplazo de python/sensor/simulador_cardiaco.py cuando hay hardware real
disponible: implementa la MISMA interfaz (leer(), cambiar_condicion()) que
espera SensorCardiaco (ver capturar_sesion.py), así que CapturaSesion no
necesita ningún cambio para usar este sensor en vez del simulado — solo
hay que instanciar SensorWahoo en lugar de SimuladorCardiaco.

Cómo funciona el perfil BLE Heart Rate Service (Bluetooth SIG,
https://www.bluetooth.com/specifications/specs/gss/):
El Wahoo TRACKR HR expone el servicio estándar "Heart Rate" (UUID 0x180D),
con una característica "Heart Rate Measurement" (UUID 0x2A37) a la que
cualquier cliente BLE puede SUSCRIBIRSE (notify): en vez de tener que
preguntar "¿cuál es tu HR ahora?" repetidamente (polling), el sensor
EMPUJA una notificación cada vez que tiene un nuevo dato (normalmente
~1 vez por segundo). El payload de cada notificación es un paquete binario
con un byte de "flags" seguido de la HR y, si el sensor los reporta,
los intervalos R-R crudos — ver _decodificar_hr_measurement() más abajo
para el desglose byte a byte exacto.

Diferencia entre HR y R-R (por qué se necesitan los dos):
HR (heart rate, bpm) es un promedio — el propio firmware del sensor ya
suavizó/promedió los latidos de una ventana reciente antes de reportarlo.
R-R es el tiempo CRUDO entre cada par de latidos consecutivos, en
milisegundos, sin ningún promediado. Para calcular HRV (SDNN, RMSSD,
pNN50 — ver python/analisis/analizar_sesion.py) hace falta la secuencia
completa de R-R, no el HR promedio: toda la variabilidad late-a-latido que
mide HRV se pierde en cuanto el sensor la promedia a "bpm".

¿Por qué el R-R viene en unidades de 1/1024 de segundo? Es una decisión
histórica del estándar Bluetooth SIG: 1024 = 2^10, una potencia de 2, lo
que le permite al firmware del sensor (hardware embebido de muy bajo
consumo) convertir el contador interno a esas unidades con un simple
desplazamiento de bits en vez de una división — mucho más barato
computacionalmente que dividir por un número no potencia de 2. Para
pasarlo a milisegundos (la unidad que usa el resto de este proyecto):
rr_ms = rr_crudo * (1000 / 1024).
"""

import asyncio
import threading
import time
from collections import deque
from typing import Optional

from bleak import BleakClient

from capturar_sesion import _condicion_desde_nombre

# UUID estándar Bluetooth SIG de la característica "Heart Rate Measurement" (0x2A37),
# expandido a la forma de 128 bits que exige bleak
UUID_HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def _decodificar_hr_measurement(data: bytearray) -> tuple[int, list[float]]:
    """Decodifica el payload binario de la característica Heart Rate Measurement.

    Estructura del paquete (Bluetooth SIG GATT Specification Supplement):
        Byte 0: flags
            bit 0: formato de HR (0 = 1 byte / UINT8, 1 = 2 bytes / UINT16)
            bits 1-2: estado de contacto del sensor con la piel (no se usa aquí)
            bit 3: 1 si el paquete incluye "Energy Expended" (2 bytes, se saltan)
            bit 4: 1 si el paquete incluye uno o más intervalos R-R
        Bytes siguientes: HR (1 o 2 bytes, según el bit 0 de flags)
        [Energy Expended: 2 bytes, si el bit 3 de flags está prendido]
        [R-R intervals: N × 2 bytes little-endian, si el bit 4 está prendido —
         un mismo paquete puede traer VARIOS R-R si el sensor acumuló más de
         un latido desde la última notificación]

    Args:
        data: Payload crudo recibido en la notificación BLE.

    Returns:
        tuple[int, list[float]]: (hr_bpm, lista de intervalos R-R en milisegundos).
    """
    flags = data[0]
    hr_formato_16_bits = bool(flags & 0x01)
    energia_presente = bool(flags & 0x08)
    rr_presente = bool(flags & 0x10)

    indice = 1
    if hr_formato_16_bits:
        hr_bpm = int.from_bytes(data[indice : indice + 2], byteorder="little")
        indice += 2
    else:
        hr_bpm = data[indice]
        indice += 1

    if energia_presente:
        indice += 2  # Energy Expended (uint16): no se usa en este proyecto, se salta

    intervalos_rr_ms = []
    if rr_presente:
        # Cada R-R son 2 bytes little-endian, en unidades de 1/1024 s (ver docstring
        # del módulo); pueden venir varios seguidos en el mismo paquete
        while indice + 1 < len(data):
            rr_crudo = int.from_bytes(data[indice : indice + 2], byteorder="little")
            intervalos_rr_ms.append(rr_crudo * (1000.0 / 1024.0))
            indice += 2

    return hr_bpm, intervalos_rr_ms


class SensorWahoo:
    """Driver BLE del sensor cardíaco Wahoo TRACKR HR (mismo contrato que SimuladorCardiaco).

    Attributes:
        mac_address (str): Dirección MAC del sensor (ver escanear_ble.py).
        reconectar_automatico (bool): Si True, reintenta conectar hasta 3
            veces al perder la conexión BLE inesperadamente.
        estado_compartido (Optional[dict]): Si se indica, leer() sincroniza
            self.condicion automáticamente con
            estado_compartido["estimulo_actual"] (mismo patrón de
            notificación en tiempo real que capturar_sesion.py, ver
            python/sesion_completa.py).
        condicion (str): Etiqueta de condición actual (para el CSV).
        hr_bpm_actual (int): Último HR recibido del sensor (0 si aún no llega ninguno).
        rr_ms_queue (deque[float]): TODOS los intervalos R-R recibidos en la sesión.
        t_inicio (Optional[float]): time.monotonic() al conectar; None hasta conectar().

    Nota de integración: leer() y cambiar_condicion() son síncronos (sin
    async) a propósito, para cumplir exactamente el mismo contrato que
    SimuladorCardiaco espera CapturaSesion (ver capturar_sesion.py). Pero
    las notificaciones BLE de bleak solo se procesan mientras el event loop
    de asyncio de ESTE objeto esté activo. Si se usa SensorWahoo dentro de
    CapturaSesion.ejecutar() — que espera con time.sleep() BLOQUEANTE en un
    hilo normal, no con await — hace falta correr conectar() y sus
    notificaciones en un hilo aparte con su propio event loop, para que no
    se congelen mientras el hilo principal duerme. Ver HiloSensorBLE más
    abajo, que resuelve exactamente eso (usado por
    python/sesion_completa.py cuando usar_sensor_real=True).
    """

    def __init__(
        self,
        mac_address: str = "D6:39:AD:0F:AC:46",
        reconectar_automatico: bool = True,
        estado_compartido: Optional[dict] = None,
    ) -> None:
        """Inicializa el sensor (no conecta todavía: usar await conectar()).

        Args:
            mac_address: MAC del sensor Wahoo TRACKR HR (ver escanear_ble.py).
            reconectar_automatico: Si True, reintenta reconectar hasta 3
                veces al perder la conexión.
            estado_compartido: dict compartido con el hilo de estímulos,
                con la clave "estimulo_actual" (ver docstring de la clase).
        """
        self.mac_address = mac_address
        self.reconectar_automatico = reconectar_automatico
        self.estado_compartido = estado_compartido

        self.condicion = "reposo"
        self.hr_bpm_actual = 0
        # maxlen generoso (~2.7 horas a 1 R-R/seg): cota de seguridad de memoria,
        # no se espera alcanzarla en una sesión real; conserva "TODOS" los R-R
        # para cualquier sesión de duración razonable
        self.rr_ms_queue: deque[float] = deque(maxlen=10000)
        self.t_inicio: Optional[float] = None

        self.cliente: Optional[BleakClient] = None
        self._conectado = False
        # Distingue una desconexión que NOSOTROS pedimos (desconectar()) de una que
        # el sensor/sistema operativo provocó solo — bleak dispara el mismo
        # disconnected_callback en ambos casos, así que sin esta bandera el cierre
        # normal al final de una sesión se confundiría con una pérdida de señal real
        # e intentaría reconectar innecesariamente (ver _on_disconnect())
        self._desconexion_intencional = False

    async def conectar(self) -> None:
        """Conecta al sensor por BLE y se suscribe a las notificaciones de HR.

        Reintenta hasta 3 veces si reconectar_automatico=True (y 1 sola vez,
        sin reintentar, si es False).

        Raises:
            Exception: Si no logra conectar tras agotar los reintentos
                (típicamente bleak.exc.BleakDeviceNotFoundError o timeout).
        """
        self._desconexion_intencional = False  # por si se reconecta tras un desconectar() previo
        intentos_max = 3 if self.reconectar_automatico else 1

        for intento in range(1, intentos_max + 1):
            try:
                self.cliente = BleakClient(self.mac_address, disconnected_callback=self._on_disconnect)
                await self.cliente.connect()
                await self.cliente.start_notify(UUID_HEART_RATE_MEASUREMENT, self._on_hr_notify)

                self.t_inicio = time.monotonic()
                self._conectado = True
                print(f"[OK] Conectado a {self.mac_address} — escuchando notificaciones de HR...")
                return
            except Exception as error:
                print(f"Intento de conexión {intento}/{intentos_max} falló: {error}")
                if intento == intentos_max:
                    raise
                await asyncio.sleep(2)

    def _on_disconnect(self, cliente: BleakClient) -> None:
        """Callback de bleak: se ejecuta SIEMPRE que la conexión BLE se cierra,
        tanto si fue una pérdida de señal real como si fuimos nosotros quienes
        llamamos a desconectar() — por eso se revisa _desconexion_intencional
        antes de disparar el intento de reconexión.
        """
        self._conectado = False
        if self._desconexion_intencional:
            return  # cierre normal pedido por desconectar(): no es un error, no reconectar

        print(f"\n[!] Se perdió la conexión BLE con {self.mac_address}")
        if self.reconectar_automatico:
            asyncio.create_task(self._reconectar())

    async def _reconectar(self, intentos_max: int = 3) -> None:
        """Reintenta conectar hasta intentos_max veces tras una desconexión inesperada."""
        for intento in range(1, intentos_max + 1):
            print(f"Reintentando conexión ({intento}/{intentos_max})...")
            try:
                await self.conectar()
                return
            except Exception as error:
                print(f"  Falló: {error}")
                await asyncio.sleep(2)
        print(f"No se pudo reconectar tras {intentos_max} intentos. Verifica el sensor.")

    def _on_hr_notify(self, sender, data: bytearray) -> None:
        """Callback de bleak: se ejecuta cada vez que llega una notificación de HR.

        Se limita a decodificar y guardar — nada de I/O ni cómputo pesado
        acá, para no demorar al event loop de asyncio (bleak espera que
        los callbacks de notify retornen rápido).

        ¿Por qué una cola (deque) y no solo el último R-R? Un mismo
        paquete de notificación puede traer VARIOS R-R juntos (si el
        sensor acumuló más de un latido desde el envío anterior, algo
        común si el HR es alto o hubo algún retardo de transmisión).
        Guardar solo "el último" descartaría esos R-R intermedios,
        sesgando el cálculo de HRV más adelante (SDNN/RMSSD dependen de
        la secuencia COMPLETA, no de una muestra). Con deque se acumulan
        todos, en orden, listos para exportar al terminar la sesión.

        Args:
            sender: Objeto de la característica que originó la notificación
                (no se usa aquí; bleak lo pasa siempre).
            data: Payload crudo de la notificación.
        """
        try:
            hr_bpm, intervalos_rr_ms = _decodificar_hr_measurement(data)
        except (IndexError, ValueError) as error:
            print(f"Advertencia: paquete HR malformado, se ignora ({error})")
            return

        self.hr_bpm_actual = hr_bpm
        self.rr_ms_queue.extend(intervalos_rr_ms)

    def leer(self) -> dict:
        """Devuelve la última lectura disponible, en el mismo formato que SimuladorCardiaco.

        Returns:
            dict: timestamp (float, segundos desde conectar()), hr_bpm (int,
                0 si aún no llegó ninguna notificación), rr_ms (float, el R-R
                más reciente recibido, 0 si aún no hay ninguno), condicion (str).
        """
        # Si hay estado_compartido, se sincroniza la condición con el estímulo real
        # vigente ahora mismo — mismo patrón de notificación en tiempo real que
        # CapturaSesion._capturar_por_notificaciones() (ver capturar_sesion.py)
        if self.estado_compartido is not None:
            nombre_estimulo = self.estado_compartido.get("estimulo_actual")
            if nombre_estimulo and nombre_estimulo != "fin":
                condicion = _condicion_desde_nombre(nombre_estimulo)
                if condicion != self.condicion:
                    self.cambiar_condicion(condicion)

        timestamp = (time.monotonic() - self.t_inicio) if self.t_inicio is not None else 0.0
        rr_ms = self.rr_ms_queue[-1] if self.rr_ms_queue else 0

        return {
            "timestamp": round(timestamp, 3),
            "hr_bpm": self.hr_bpm_actual,
            "rr_ms": rr_ms,
            "condicion": self.condicion,
        }

    def cambiar_condicion(self, nueva: str) -> None:
        """Actualiza la etiqueta de condición actual (igual que SimuladorCardiaco).

        A diferencia del simulador, esto NO afecta al sensor real (un
        sensor de hardware no "reacciona" a que le cambien una condición
        por software) — solo etiqueta las próximas lecturas para el CSV.

        Args:
            nueva: Nueva condición/etiqueta a registrar.
        """
        self.condicion = nueva

    async def desconectar(self) -> None:
        """Cierra la conexión BLE limpiamente (cancela la suscripción y desconecta)."""
        self._desconexion_intencional = True  # evita que _on_disconnect() intente reconectar
        if self.cliente is not None and self.cliente.is_connected:
            try:
                await self.cliente.stop_notify(UUID_HEART_RATE_MEASUREMENT)
            except Exception:
                pass  # si ya se había desconectado solo, stop_notify puede fallar; no es crítico
            await self.cliente.disconnect()

        self._conectado = False
        print("Sensor Wahoo desconectado.")


class HiloSensorBLE:
    """Corre un SensorWahoo en un hilo dedicado con su propio event loop de asyncio.

    Esto es lo que permite usar SensorWahoo desde código completamente
    SÍNCRONO (como CapturaSesion.ejecutar(), que avanza con time.sleep()
    bloqueante — ver capturar_sesion.py y sesion_completa.py).

    ¿Por qué threading + asyncio en hilos distintos? Las notificaciones BLE
    de bleak solo se procesan mientras su event loop de asyncio está
    "girando" (despachando su cola de callbacks pendientes). CapturaSesion
    avanza con time.sleep(), que NO le cede el control a ningún event
    loop — mientras un hilo está dormido en time.sleep(), cualquier event
    loop que viviera en ESE MISMO hilo quedaría congelado también, y con
    él las notificaciones de HR. La solución estándar para este tipo de
    librerías async es correr su event loop en un hilo APARTE que nunca
    ejecuta time.sleep(): se queda con run_forever() todo el tiempo, así
    que sigue despachando notificaciones sin importar qué tan ocupado (o
    dormido) esté el hilo principal.

    ¿Por qué NO simplemente asyncio.run() en el hilo principal? asyncio.run()
    crea un event loop, corre UNA corrutina hasta que termina, y cierra el
    loop — bloquea el hilo que lo llama durante todo ese tiempo. Si el hilo
    que corre CapturaSesion.ejecutar() llamara asyncio.run() para conectar
    y escuchar al sensor, quedaría atrapado ahí sin poder simultáneamente
    ejecutar su propio bucle de lecturas con time.sleep() — se necesitan
    dos cosas corriendo "al mismo tiempo" (el loop BLE y el bucle síncrono
    de captura), y asyncio.run() en un solo hilo solo puede darte una.

    Cómo entra el GIL (Global Interpreter Lock) en esto: el GIL asegura que
    solo un hilo ejecuta bytecode de Python a la vez, pero SÍ va alternando
    entre hilos constantemente. Operaciones simples como
    `self.hr_bpm_actual = valor` o `deque.append(x)`/`extend(...)` son
    atómicas a nivel de bytecode — no existe un estado "a medio escribir"
    que otro hilo pueda leer a mitad de camino. Por eso SensorWahoo.leer()
    y cambiar_condicion() se pueden llamar tranquilamente desde OTRO hilo
    (el de CapturaSesion) sin necesitar un threading.Lock explícito: el GIL
    ya garantiza que esas lecturas/escrituras puntuales son seguras. Lo que
    SÍ exige cuidado explícito es todo lo relacionado con el event loop de
    asyncio en sí (arrancarlo, pararlo, o pedirle que corra una corrutina
    desde OTRO hilo) — para eso existen las funciones thread-safe que se
    usan en detener(): call_soon_threadsafe() y run_coroutine_threadsafe().
    Llamar a las variantes normales (loop.stop(), o simplemente
    `await sensor.desconectar()`) desde un hilo que no es dueño del loop
    sería una condición de carrera.
    """

    def __init__(self, sensor: "SensorWahoo") -> None:
        """Prepara el hilo (no lo arranca todavía: usar iniciar()).

        Args:
            sensor: Instancia de SensorWahoo a correr en el hilo dedicado.
        """
        self.sensor = sensor
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._hilo: Optional[threading.Thread] = None
        self._listo = threading.Event()
        self._error_conexion: Optional[BaseException] = None

    def iniciar(self, timeout_conexion_seg: float = 20.0) -> None:
        """Arranca el hilo, conecta el sensor, y bloquea hasta que esté listo.

        Al retornar sin excepción, el sensor ya está conectado y recibiendo
        notificaciones — es seguro empezar a llamar self.sensor.leer()
        desde el hilo que llamó a iniciar().

        Args:
            timeout_conexion_seg: Cuánto esperar como máximo a que el hilo
                termine de conectar antes de darlo por fallido.

        Raises:
            TimeoutError: Si el hilo no llega a conectar dentro del timeout.
            Exception: La excepción real de conexión (ej. sensor no
                encontrado), propagada desde dentro del hilo.
        """
        self._hilo = threading.Thread(
            target=self._correr_event_loop, name="ble-sensor-wahoo", daemon=True
        )
        self._hilo.start()

        # Bloquea el hilo LLAMADOR (no el hilo BLE) hasta que _correr_event_loop()
        # confirme éxito o falla — así iniciar() nunca retorna "a medias"
        if not self._listo.wait(timeout=timeout_conexion_seg):
            raise TimeoutError(f"El sensor Wahoo no terminó de conectar en {timeout_conexion_seg}s.")
        if self._error_conexion is not None:
            raise self._error_conexion

    def _correr_event_loop(self) -> None:
        """Cuerpo del hilo dedicado: crea un event loop nuevo y lo mantiene vivo.

        asyncio no permite compartir un mismo event loop entre hilos, así
        que cada hilo que quiera correr corrutinas necesita el suyo propio.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self.sensor.conectar())
        except BaseException as error:
            self._error_conexion = error
            self._listo.set()
            return

        self._listo.set()
        # run_forever() mantiene el loop girando indefinidamente, despachando las
        # notificaciones BLE que vayan llegando, hasta que detener() lo pare
        self._loop.run_forever()
        self._loop.close()

    def detener(self) -> None:
        """Desconecta el sensor y detiene limpiamente el hilo/event loop dedicado."""
        if self._loop is None:
            return

        futuro = asyncio.run_coroutine_threadsafe(self.sensor.desconectar(), self._loop)
        try:
            futuro.result(timeout=10)
        except Exception as error:
            print(f"Advertencia: error al desconectar el sensor Wahoo: {error}")

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._hilo is not None:
            self._hilo.join(timeout=5)


async def correr_sensor_wahoo() -> None:
    """Prueba real de ~35s: conecta, lee HR en reposo y en solfeggio, compara, desconecta.

    Requiere que el sensor Wahoo TRACKR HR esté encendido y la banda
    pectoral puesta sobre la piel (con los electrodos húmedos) para
    reportar HR real.
    """
    sensor = SensorWahoo(mac_address="D6:39:AD:0F:AC:46")
    await sensor.conectar()

    print("\nEsperando 5 segundos para estabilizar la primera lectura...")
    await asyncio.sleep(5)

    sensor.cambiar_condicion("reposo")
    print("\n=== Fase 1: reposo (10 lecturas cada 1.5s) ===")
    lecturas_reposo = []
    for i in range(10):
        await asyncio.sleep(1.5)
        lectura = sensor.leer()
        lecturas_reposo.append(lectura)
        print(f"  [{i + 1}/10] HR={lectura['hr_bpm']} bpm   R-R={lectura['rr_ms']:.0f} ms")

    sensor.cambiar_condicion("solfeggio_528Hz")
    print("\n=== Fase 2: solfeggio_528Hz (10 lecturas cada 1.5s) ===")
    lecturas_solfeggio = []
    for i in range(10):
        await asyncio.sleep(1.5)
        lectura = sensor.leer()
        lecturas_solfeggio.append(lectura)
        print(f"  [{i + 1}/10] HR={lectura['hr_bpm']} bpm   R-R={lectura['rr_ms']:.0f} ms")

    await sensor.desconectar()

    hr_reposo = [lectura["hr_bpm"] for lectura in lecturas_reposo if lectura["hr_bpm"] > 0]
    hr_solfeggio = [lectura["hr_bpm"] for lectura in lecturas_solfeggio if lectura["hr_bpm"] > 0]

    promedio_reposo = sum(hr_reposo) / len(hr_reposo) if hr_reposo else 0.0
    promedio_solfeggio = sum(hr_solfeggio) / len(hr_solfeggio) if hr_solfeggio else 0.0

    print("\n=== Resumen ===")
    print(f"HR promedio en reposo:    {promedio_reposo:.1f} bpm  ({len(hr_reposo)}/10 lecturas válidas)")
    print(f"HR promedio en solfeggio: {promedio_solfeggio:.1f} bpm  ({len(hr_solfeggio)}/10 lecturas válidas)")
    print(f"Diferencia:               {promedio_solfeggio - promedio_reposo:+.1f} bpm")
    print(f"Total de R-R capturados:  {len(sensor.rr_ms_queue)}")


if __name__ == "__main__":
    # asyncio.run() crea el event loop, corre correr_sensor_wahoo() hasta que termina
    # (incluida la desconexión), y lo cierra al final
    asyncio.run(correr_sensor_wahoo())
