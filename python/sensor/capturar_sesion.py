"""Captura de una sesión experimental completa a partir de un sensor cardíaco.

Este módulo orquesta la reproducción de un protocolo de estímulos
(secuencia de bloques temporales con distinta condición) mientras lee
continuamente del sensor cardíaco, y guarda todo lo capturado en un CSV
listo para el análisis posterior (ver python/analisis/).

Funciona tanto con SimuladorCardiaco (python/sensor/simulador_cardiaco.py)
como con SensorWahoo, el driver BLE real (python/sensor/sensor_wahoo.py),
sin ningún cambio en este archivo: ambos exponen los mismos dos métodos,
leer() y cambiar_condicion(condicion) — ver SensorCardiaco más abajo para
el contrato exacto, y python/sesion_completa.py (parámetro
usar_sensor_real) para cómo se elige cuál de los dos usar.

Sobre las lecturas con hr_bpm=0 (decisión de diseño):
Con SensorWahoo, la primera lectura de una sesión suele salir en 0 (el
sensor real aún no envió su primera notificación BLE — ver
SensorWahoo.leer()). Este módulo NO descarta esas filas al capturar: se
guardan tal cual en el CSV, igual que cualquier otra lectura. La limpieza
se hace más adelante, al ANALIZAR (ver
AnalisisSesion._mascara_lecturas_validas() en
python/analisis/analizar_sesion.py y el filtro equivalente en
python/analisis/analisis_grupal.py), no acá. Tres razones:
  1. El CSV debe ser un registro fiel y completo de la sesión tal como
     ocurrió — incluidos sus artefactos de hardware — útil para
     diagnóstico futuro (ej. medir cuánto tarda el sensor en dar la
     primera lectura real, sesión a sesión).
  2. Descartar filas al capturar dejaría huecos en la grilla temporal de
     ~1 lectura/segundo, complicando cualquier código que asuma muestreo
     regular (ej. la interpolación de sincronizador.py).
  3. El criterio de qué es "artefacto" es más fácil de ajustar en el
     código de análisis (se puede afinar sin volver a capturar nada) que
     si quedara fijado para siempre en el momento de la captura.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

# Carpeta donde se guardan los CSV de cada sesión de participante
CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")


def _condicion_desde_nombre(nombre_estimulo: str) -> str:
    """Traduce el nombre de un estímulo (ej. "solfeggio_528Hz") a una condición
    fisiológica reconocida por SensorCardiaco.cambiar_condicion().

    Se usa en el modo por notificaciones (ver ejecutar()), donde el sensor
    solo conoce el NOMBRE real del estímulo que está sonando (vía
    estado_compartido) y necesita mapearlo a una condición para decidir
    cómo debe reaccionar la HR. Duplicada a propósito de la función
    homónima en python/sesion_completa.py: este módulo de sensor/ no debe
    depender del orquestador de nivel superior.
    """
    nombre_normalizado = nombre_estimulo.lower()
    for condicion in ("solfeggio", "binaural", "isocronico", "preferencia", "estimulo_negativo"):
        if condicion in nombre_normalizado:
            return condicion
    return "reposo"  # fallback: bloques de silencio (baseline, descansoN, cierre, ...)


class SensorCardiaco(Protocol):
    """Contrato mínimo que debe cumplir cualquier sensor (simulado o real).

    SimuladorCardiaco y SensorWahoo (el driver BLE real, ver
    python/sensor/sensor_wahoo.py) implementan estos dos métodos, así que
    CapturaSesion puede usar cualquiera de los dos sin cambios: basta con
    pasar un objeto u otro al construirla (esto es tipado estructural —
    Protocol no exige herencia, solo que existan los métodos).
    """

    def leer(self) -> dict:
        """Devuelve una lectura con al menos hr_bpm, rr_ms y condicion."""
        ...

    def cambiar_condicion(self, nueva_condicion: str) -> None:
        """Cambia la condición experimental activa del sensor."""
        ...


class CapturaSesion:
    """Ejecuta un protocolo de estímulos y guarda las lecturas en CSV.

    Attributes:
        sensor (SensorCardiaco): Objeto con métodos leer() y cambiar_condicion().
        participante_id (str): Identificador del participante, ej. "P01".
        frecuencia_hz (float): Lecturas por segundo a solicitar al sensor.
        estimulos (list[tuple]): Protocolo cargado con programar_estimulos().
        lecturas (list[dict]): Filas capturadas durante ejecutar().
    """

    def __init__(
        self,
        sensor: SensorCardiaco,
        participante_id: str,
        frecuencia_hz: float = 1.0,
    ) -> None:
        """Inicializa la captura.

        Args:
            sensor: Instancia del simulador o del sensor real.
            participante_id: Identificador del participante, ej. "P01".
            frecuencia_hz: Cuántas lecturas por segundo pedir al sensor
                (default 1.0 = 1 lectura/segundo).
        """
        self.sensor = sensor
        self.participante_id = participante_id
        self.frecuencia_hz = frecuencia_hz
        self.estimulos: list[tuple] = []
        self.lecturas: list[dict] = []

    def programar_estimulos(self, lista_estimulos: list[tuple]) -> None:
        """Carga el protocolo de estímulos a ejecutar.

        Args:
            lista_estimulos: Lista de tuplas
                (inicio_seg, duracion_seg, condicion, nombre_estimulo),
                ordenadas por inicio_seg. Ejemplo:
                [(0, 60, "reposo", "baseline"),
                 (60, 120, "solfeggio", "528Hz")]
        """
        # Se ordena por inicio_seg por si el usuario los pasó desordenados
        self.estimulos = sorted(lista_estimulos, key=lambda bloque: bloque[0])

    def ejecutar(
        self,
        t0_externo: Optional[float] = None,
        fecha_hora: Optional[str] = None,
        estado_compartido: Optional[dict] = None,
    ) -> Path:
        """Captura lecturas del sensor y guarda el CSV.

        Tiene dos modos, según se indique estado_compartido o no:

        - Modo CRONOGRAMA (estado_compartido=None, comportamiento original):
          recorre self.estimulos (cargado con programar_estimulos()) y
          asume que cada bloque dura exactamente lo programado. Simple,
          pero si el protocolo real corre con latencias (ej. abrir el
          dispositivo de audio para reproducir cada estímulo), la columna
          "condicion" del CSV queda desfasada respecto a lo que realmente
          sonó — el bloque siguiente empieza en el CSV antes o después de
          que empezó de verdad.

        - Modo NOTIFICACIONES (estado_compartido no es None): en vez de
          seguir un cronograma nominal, en cada lectura consulta
          estado_compartido["estimulo_actual"] — que otro hilo (típicamente
          ReproductorEstimulos.reproducir_protocolo(), ver
          python/sesion_completa.py) actualiza en tiempo real justo cuando
          CADA bloque empieza de verdad. Así "condicion" queda sincronizada
          exactamente con los eventos reales, sin la deriva acumulada del
          modo cronograma. El bucle termina cuando el valor es "fin".

        Args:
            t0_externo: Referencia de tiempo (time.monotonic()) a usar como
                "inicio de sesión" en vez de capturar una propia. Se usa
                cuando este hilo corre en paralelo con otros (ver
                python/sesion_completa.py) y todos deben compartir el mismo
                punto de referencia para que sus timestamps sean
                directamente comparables. None = comportamiento normal
                (usa su propio time.monotonic() al arrancar).
            fecha_hora: Sufijo de fecha/hora para el nombre del archivo
                (formato "%Y%m%d_%H%M"). None = usa la hora actual al
                guardar. Se expone para que una sesión coordinada con
                otros archivos (audio, estímulos) pueda forzar el mismo
                sufijo en los tres, y así identificarlos como la misma sesión.
            estado_compartido: dict compartido con el hilo que reproduce
                los estímulos, con la clave "estimulo_actual". Si se indica,
                activa el modo NOTIFICACIONES descrito arriba.

        Returns:
            Path: Ruta del archivo CSV generado.

        Raises:
            RuntimeError: Si no se programaron estímulos antes de ejecutar
                Y no se indicó estado_compartido (en modo notificaciones no
                hace falta programar_estimulos()).
        """
        if not self.estimulos and estado_compartido is None:
            raise RuntimeError(
                "No hay estímulos programados. Llama a programar_estimulos() primero "
                "(o pasa estado_compartido para el modo por notificaciones)."
            )

        self.lecturas = []
        tiempo_inicio_captura = t0_externo if t0_externo is not None else time.monotonic()

        print(f"=== Iniciando captura: participante {self.participante_id} ===")

        if estado_compartido is not None:
            self._capturar_por_notificaciones(tiempo_inicio_captura, estado_compartido)
        else:
            self._capturar_por_cronograma(tiempo_inicio_captura)

        duracion_real = time.monotonic() - tiempo_inicio_captura
        ruta_csv = self._guardar_csv(fecha_hora)

        print("\n=== Captura finalizada ===")
        print(f"Total de lecturas: {len(self.lecturas)}")
        print(f"Duración real: {duracion_real:.1f}s")
        print(f"Archivo guardado en: {ruta_csv}")

        return ruta_csv

    def _capturar_por_cronograma(self, tiempo_inicio_captura: float) -> None:
        """Modo original: recorre self.estimulos siguiendo su cronograma nominal."""
        total_bloques = len(self.estimulos)

        for idx, (inicio_seg, duracion_seg, condicion, nombre_estimulo) in enumerate(
            self.estimulos, start=1
        ):
            self.sensor.cambiar_condicion(condicion)
            print(
                f"\n>>> Bloque {idx}/{total_bloques}: '{nombre_estimulo}' "
                f"({condicion}) — {duracion_seg}s"
            )

            # Número de lecturas a tomar en este bloque según la frecuencia configurada
            num_lecturas = max(1, round(duracion_seg * self.frecuencia_hz))

            for i in range(num_lecturas):
                # Tiempo objetivo (relativo al inicio de la sesión) para esta lectura,
                # calculado desde el inicio del bloque para no acumular retraso (drift)
                tiempo_objetivo = inicio_seg + (i / self.frecuencia_hz)
                tiempo_transcurrido = time.monotonic() - tiempo_inicio_captura
                espera = tiempo_objetivo - tiempo_transcurrido
                if espera > 0:
                    time.sleep(espera)

                lectura = self.sensor.leer()
                tiempo_transcurrido = time.monotonic() - tiempo_inicio_captura

                self.lecturas.append(
                    {
                        "timestamp": round(tiempo_transcurrido, 3),
                        "hr_bpm": lectura["hr_bpm"],
                        "rr_ms": lectura["rr_ms"],
                        "condicion": condicion,
                        "estimulo": nombre_estimulo,
                    }
                )

                self._mostrar_progreso(i + 1, num_lecturas, lectura["hr_bpm"])

            print()  # salto de línea al terminar la barra del bloque

    def _capturar_por_notificaciones(self, tiempo_inicio_captura: float, estado_compartido: dict) -> None:
        """Modo nuevo: lee a ritmo fijo, etiquetando cada lectura con el estímulo REAL vigente.

        No depende de self.estimulos ni de ninguna duración nominal: sigue
        leyendo hasta que estado_compartido["estimulo_actual"] pasa a "fin".
        """
        condicion_actual = None
        i = 0

        while True:
            estimulo_actual = estado_compartido.get("estimulo_actual", "reposo")
            if estimulo_actual == "fin":
                break

            # Tiempo objetivo de la próxima lectura, sin acumular retraso (drift)
            tiempo_objetivo = i / self.frecuencia_hz
            tiempo_transcurrido = time.monotonic() - tiempo_inicio_captura
            espera = tiempo_objetivo - tiempo_transcurrido
            if espera > 0:
                time.sleep(espera)

            # Se vuelve a consultar tras la espera: el estímulo pudo cambiar mientras dormía
            estimulo_actual = estado_compartido.get("estimulo_actual", "reposo")
            if estimulo_actual == "fin":
                break

            condicion = _condicion_desde_nombre(estimulo_actual)
            if condicion != condicion_actual:
                self.sensor.cambiar_condicion(condicion)
                condicion_actual = condicion

            lectura = self.sensor.leer()
            tiempo_transcurrido = time.monotonic() - tiempo_inicio_captura

            self.lecturas.append(
                {
                    "timestamp": round(tiempo_transcurrido, 3),
                    "hr_bpm": lectura["hr_bpm"],
                    "rr_ms": lectura["rr_ms"],
                    "condicion": condicion,
                    "estimulo": estimulo_actual,
                }
            )

            self._mostrar_estado_continuo(tiempo_transcurrido, estimulo_actual, lectura["hr_bpm"])
            i += 1

        print()

    def _mostrar_progreso(self, actual: int, total: int, hr_bpm: float) -> None:
        """Imprime una barra de progreso de una línea para el bloque actual.

        Args:
            actual: Número de lectura actual dentro del bloque (1-indexado).
            total: Total de lecturas esperadas en el bloque.
            hr_bpm: HR de la última lectura, para mostrarla junto a la barra.
        """
        ancho_barra = 30
        progreso = actual / total
        llenado = int(ancho_barra * progreso)
        barra = "#" * llenado + "-" * (ancho_barra - llenado)
        print(
            f"\r  [{barra}] {progreso * 100:5.1f}%  HR={hr_bpm:5.1f} bpm",
            end="",
            flush=True,
        )

    @staticmethod
    def _mostrar_estado_continuo(tiempo_transcurrido: float, estimulo_actual: str, hr_bpm: float) -> None:
        """Imprime el estado actual en modo notificaciones (sin barra: no hay total conocido).

        Args:
            tiempo_transcurrido: Segundos desde el inicio de la sesión.
            estimulo_actual: Nombre del bloque de estímulo vigente ahora mismo.
            hr_bpm: HR de la última lectura.
        """
        print(
            f"\r  t={tiempo_transcurrido:6.1f}s  estimulo={estimulo_actual:<25}  HR={hr_bpm:5.1f} bpm",
            end="",
            flush=True,
        )

    def _guardar_csv(self, fecha_hora: Optional[str] = None) -> Path:
        """Guarda self.lecturas como CSV en CARPETA_SESIONES.

        Args:
            fecha_hora: Sufijo de fecha/hora a usar en el nombre de archivo.
                None = usa la hora actual.

        Returns:
            Path: Ruta del archivo CSV creado.
        """
        CARPETA_SESIONES.mkdir(parents=True, exist_ok=True)

        fecha_hora = fecha_hora or datetime.now().strftime("%Y%m%d_%H%M")
        nombre_archivo = f"{self.participante_id}_{fecha_hora}.csv"
        ruta_csv = CARPETA_SESIONES / nombre_archivo

        columnas = ["timestamp", "hr_bpm", "rr_ms", "condicion", "estimulo"]
        df = pd.DataFrame(self.lecturas, columns=columnas)
        df.to_csv(ruta_csv, index=False)

        return ruta_csv


if __name__ == "__main__":
    # Sesión de prueba corta (2 minutos, 4 estímulos) usando el simulador
    from simulador_cardiaco import SimuladorCardiaco

    sensor_prueba = SimuladorCardiaco(hr_baseline=70.0, variabilidad=8.0)
    captura = CapturaSesion(sensor=sensor_prueba, participante_id="P01", frecuencia_hz=1.0)

    captura.programar_estimulos(
        [
            (0, 30, "reposo", "baseline"),
            (30, 30, "solfeggio", "528Hz"),
            (60, 20, "reposo", "descanso1"),
            (80, 40, "preferencia", "cancion_favorita"),
        ]
    )

    captura.ejecutar()
