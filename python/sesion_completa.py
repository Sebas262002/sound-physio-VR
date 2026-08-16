"""Ejecuta una sesión experimental completa: sensor + audio + estímulos en paralelo.

Orquesta los tres módulos que hasta ahora se corrían por separado —

    python/sensor/capturar_sesion.py       (HR/R-R del sensor cardíaco)
    python/audio/capturar_respiracion.py   (audio de respiración)
    python/audio/reproductor_estimulos.py  (reproducción de estímulos)

— en tres threading.Thread que arrancan casi al mismo instante, TODOS
recibiendo la MISMA referencia t0 = time.monotonic() capturada una sola
vez antes de lanzarlos. Esto resuelve de raíz el problema que quedó
documentado como limitación en python/analisis/sincronizador.py: ahí, como
cada script se ejecutaba por separado (en momentos distintos, decididos
por el investigador), solo se podía ASUMIR que empezaron al mismo tiempo y
re-anclar cada archivo a esa suposición. Acá, al compartir el mismo t0
real dentro del mismo proceso, los tres registros quedan genuinamente en
la misma escala de tiempo — no es una aproximación.

¿Por qué threading y no multiprocessing, si Python tiene el GIL (Global
Interpreter Lock) que impide que dos hilos ejecuten bytecode Python al
mismo tiempo? Porque las tres tareas son casi enteramente de ESPERA
(I/O-bound), no de cómputo (CPU-bound): grabar y reproducir audio ocurren
en hilos internos de PortAudio fuera del GIL, y las esperas del sensor
(time.sleep()) LIBERAN el GIL mientras duermen. En este tipo de carga,
threading logra concurrencia real (los tres "avanzan" al mismo tiempo)
sin la complejidad extra de multiprocessing (procesos separados, memoria
no compartida, serialización de resultados).

Para que los tres módulos pudieran aceptar este t0 compartido, se les
agregó un parámetro opcional t0_externo (y fecha_hora, para que los tres
archivos de salida queden con el mismo sufijo y se identifiquen como la
misma sesión) a:

    CapturaSesion.ejecutar(t0_externo=..., fecha_hora=...)
    CapturaAudio.grabar_con_metadata(t0_externo=..., fecha_hora=...)
    ReproductorEstimulos.reproducir_protocolo(t0_externo=...)

Ambos parámetros son None por default, así que los tres módulos siguen
funcionando exactamente igual que antes cuando se corren solos.

CAPTURA POR NOTIFICACIONES (no por cronograma nominal):
La primera versión de este módulo le daba al sensor un protocolo
PRE-CALCULADO (duración nominal de cada bloque, sumadas una tras otra) y
el sensor simplemente lo seguía a ciegas. Eso funcionaba para el
timestamp global (gracias al t0 compartido), pero la columna "condicion"
del CSV se iba desfasando del estímulo que sonaba DE VERDAD, porque
reproducir cada WAV toma un poco más de lo nominal (latencia de abrir el
dispositivo de audio, ~0.5-1s por bloque) — y ese desfase se acumula
bloque tras bloque.

La solución: el hilo de estímulos (ReproductorEstimulos.reproducir_protocolo)
ahora NOTIFICA en tiempo real, actualizando un dict compartido
estado_compartido = {"estimulo_actual": ...} justo antes de que cada
bloque empiece a sonar de verdad. El hilo del sensor (CapturaSesion.ejecutar
en modo notificaciones) ya no sigue ningún cronograma: en cada lectura
simplemente consulta ese dict para saber qué está sonando AHORA, y deja
de leer cuando ve "estimulo_actual" == "fin". Al ser dos hilos leyendo/
escribiendo una sola clave de un dict, no hace falta un lock — en CPython
la asignación y lectura de una clave de dict es atómica a nivel de
bytecode.

SENSOR REAL (SensorWahoo) vs. SIMULADO (SimuladorCardiaco):
Con usar_sensor_real=True, el hilo del sensor usa SensorWahoo (driver BLE
real, ver python/sensor/sensor_wahoo.py) en vez de SimuladorCardiaco — y
NO hace falta tocar capturar_sesion.py para esto: CapturaSesion acepta
cualquier objeto que tenga leer() y cambiar_condicion() (SensorCardiaco es
un typing.Protocol, tipado estructural, no herencia), y SensorWahoo ya
cumple ese contrato exactamente.

Lo que sí hace falta es resolver que SensorWahoo es async por dentro (usa
bleak) mientras CapturaSesion.ejecutar() es 100% síncrono (avanza con
time.sleep() bloqueante, no con await). Para eso se usa HiloSensorBLE (ver
python/sensor/sensor_wahoo.py): corre la conexión BLE y sus notificaciones
en un hilo dedicado con su propio event loop de asyncio, que sigue
girando (run_forever()) sin importar qué tan ocupado esté el hilo de
CapturaSesion — así sensor.hr_bpm_actual y sensor.rr_ms_queue se siguen
actualizando en tiempo real aunque el hilo que llama a sensor.leer() esté
dormido en time.sleep(). leer()/cambiar_condicion() siguen siendo seguros
de llamar desde ese otro hilo sin un Lock explícito porque son operaciones
atómicas bajo el GIL (ver la explicación completa en el docstring de
HiloSensorBLE).

Nota sobre timestamps: aunque SensorWahoo.leer() devuelve su propio
"timestamp" (segundos desde que SE CONECTÓ el sensor), CapturaSesion NO lo
usa para el CSV — calcula su propio tiempo transcurrido desde el t0
compartido de la sesión (igual que con SimuladorCardiaco) y solo toma
hr_bpm/rr_ms del dict que devuelve leer(). Por eso el reloj interno de
SensorWahoo no necesita coincidir con t0: son dos relojes independientes,
y el que termina en el CSV es siempre el de la sesión compartida.

PERÍODO DE ESTABILIZACIÓN (tiempo_estabilizacion_seg):
El período de estabilización permite que la respuesta cardíaca del
participante se asiente tras colocarse el sensor y sentarse. Sin este
margen, el primer bloque baseline incluiría la transición fisiológica
natural de HR alto (por movimiento previo) a HR estable, sesgando las
métricas HRV (SDNN especialmente) hacia valores artificialmente altos —
esto se observó de forma directa en una sesión real: el bloque baseline
sin estabilización previa dio un SDNN más del doble que el bloque de
reposo al final de la misma sesión, pese a que fisiológicamente ambos
deberían ser similares (ver conversación de la tarea que agregó este
período).

Durante la estabilización, el sensor ya está conectado y se lee
activamente (para descartar cualquier HR=0 inicial del hardware real,
ver SensorWahoo), pero esas lecturas NO se guardan en ningún CSV — es
tiempo de descarte deliberado. t0 (la referencia compartida entre los 3
hilos) se captura DESPUÉS de que termina la estabilización, así que el
CSV siempre arranca en t=0 con la primera lectura del protocolo oficial,
nunca con la estabilización.

REPRODUCCIÓN DE AUDIO REAL (reproducir_audio_real):
Hasta ahora, los bloques "estimulo" de un protocolo_personalizado (ej.
"solfeggio_528Hz") eran solo ETIQUETAS: el hilo de estímulos notificaba el
nombre a estado_compartido, pero no reproducía ningún WAV — útil para
probar el sensor sin depender de la biblioteca de audio_estimulos/, pero
insuficiente para una sesión piloto real donde el participante debe
escuchar el estímulo de verdad.

Con reproducir_audio_real=True, _resolver_audio_real() completa
automáticamente la "ruta" de cada bloque "estimulo" que no la traiga,
mapeando su nombre a un WAV de audio_estimulos/ (ver
_resolver_ruta_estimulo() para el mapeo exacto). Como los bloques de un
protocolo_personalizado también traen su propia duracion_seg (necesaria
para el modo por notificaciones del sensor), ReproductorEstimulos usa
reproducir_por_duracion() en vez de reproducir(): la duración del BLOQUE
manda sobre la duración del WAV — se repite en loop si el WAV es más
corto, se corta si es más largo (ver reproductor_estimulos.py).

Nota sobre threading: esto NO necesita ningún hilo nuevo. El hilo de
estímulos (_hilo_estimulos) ya corre en paralelo al del sensor y al de
audio desde el diseño original del módulo (ver el primer bloque de este
docstring); reproducir el WAV ahí adentro con un sd.OutputStream (que
corre en su propio callback en segundo plano, ver reproductor_estimulos.py)
+ sondeo con time.sleep(0.1) no bloquea a los otros dos hilos, que siguen
su propio camino sin enterarse.

PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS (usar_protocolo_final):
Tras las sesiones piloto P10/P11 (que validaron hardware real y audio
real de estímulos en paralelo, ver el fix de sd.InputStream/OutputStream
en capturar_respiracion.py y reproductor_estimulos.py), este es el
protocolo ESTANDARIZADO para todos los participantes del estudio (ver
obtener_protocolo_tesis_final()):

    baseline(60s) → solfeggio_528Hz(60s) → descanso1(30s) →
    binaural_alpha(60s) → descanso2(30s) → isocronico_alpha(60s) →
    descanso3(30s) → preferencia(60s) → cierre(60s)

Duración capturada: 450s (7.5 min); con estabilización (30s, no incluida
en el protocolo, ver tiempo_estabilizacion_seg): 480s (8 min) de pared.

¿Por qué estos 3 tipos de estímulo (Solfeggio, Binaural, Isocrónico) y
no otra combinación? Son las tres familias de "frecuencias terapéuticas"
que el marco teórico de la tesis compara: Solfeggio (tonos puros de
frecuencia fija, tradición new-age/musicoterapia), Binaural (dos tonos
casi idénticos, uno por oído, cuya diferencia de frecuencia el cerebro
percibe como un "beat" — requiere audífonos estéreo, que ya se usan en
el protocolo) e Isocrónico (un solo tono pulsado a la misma frecuencia
objetivo, sin necesitar estéreo ni beats binaurales). Los tres apuntan
al MISMO rango objetivo (Alpha, ~8-12Hz, asociado a relajación
despierta) en Binaural/Isocrónico, lo que permite una comparación
directa de TÉCNICA (binaural vs. isocrónico) a frecuencia objetivo
constante — no solo de familia de estímulo. El Solfeggio 528Hz se
incluye como referencia de la familia más popularmente citada en la
literatura de "frecuencias terapéuticas" fuera del ámbito académico
estricto. Todo esto se contrasta contra la condición que de verdad
importa para la hipótesis central de la tesis: la preferencia sonora
personal del participante (bloque "preferencia"), evaluando si un
estímulo "genérico" bien fundamentado en teoría puede igualar o superar
a la respuesta fisiológica ante lo que el participante YA prefiere
escuchar.

¿Por qué 60 segundos por bloque de estímulo/baseline/cierre? Es el piso
recomendado por el Task Force de la European Society of Cardiology y la
North American Society of Pacing and Electrophysiology (Task Force
ESC/NASPE, 1996, "Heart rate variability: standards of measurement,
physiological interpretation, and clinical use") para que SDNN se pueda
calcular de forma confiable sobre una ventana corta: SDNN depende de
capturar suficiente variabilidad natural del ritmo cardíaco, y con
ventanas más cortas el estimador queda dominado por ruido de muestreo
(muy pocos intervalos R-R para que la desviación estándar sea estable).
RMSSD, al depender de diferencias sucesivas en vez de la dispersión
total, tolera mejor ventanas cortas, pero se mantiene la misma duración
para las tres métricas por consistencia metodológica entre bloques.

¿Por qué 30 segundos de descanso entre estímulos (y no menos)? Da
margen a que la respuesta cardíaca se desacople del estímulo anterior
antes de iniciar el siguiente — sin este margen, un efecto de
"arrastre" (carryover) del estímulo N podría contaminar la línea base
implícita del estímulo N+1, dificultando atribuir los cambios de HR/HRV
específicamente al estímulo que está sonando en ese momento y no a un
remanente del anterior. 30s es menor que los 60s de los bloques de
estímulo porque el descanso no necesita producir una métrica HRV propia
de calidad publicable — solo necesita ser suficiente para el "reset"
fisiológico entre condiciones.

¿Cómo se compara con la preferencia personal? El bloque "preferencia" se
resuelve, mapea y reproduce exactamente igual que los demás bloques de
estímulo (mismo pipeline de _resolver_ruta_estimulo() /
reproducir_por_duracion()) — la única diferencia es que su WAV no sale
de audio_estimulos/ sino del parámetro preferencia_wav (el audio que
cada participante trae de antemano). Al quedar en la MISMA posición
relativa del protocolo (después de isocrónico, con el mismo descanso
previo) y la MISMA duración (60s) que los demás estímulos, su métrica
HRV/HR/respiración queda directamente comparable con las de Solfeggio,
Binaural e Isocrónico sin ningún ajuste adicional — la comparación
"solfeggio vs. preferencia" (el hallazgo central de la tesis, ver
analizar_sesion_completa.py) simplemente lee ambas filas de la misma
tabla de métricas por bloque.
"""

import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import soundfile as sf

sys.path.insert(0, r"C:\Tesis_Kevin\python\sensor")
sys.path.insert(0, r"C:\Tesis_Kevin\python\audio")
sys.path.insert(0, r"C:\Tesis_Kevin\python\analisis")

from simulador_cardiaco import SimuladorCardiaco  # noqa: E402
from capturar_sesion import CapturaSesion  # noqa: E402
from sensor_wahoo import SensorWahoo, HiloSensorBLE  # noqa: E402
from capturar_respiracion import CapturaAudio  # noqa: E402
from reproductor_estimulos import ReproductorEstimulos  # noqa: E402
from analizar_sesion_completa import analizar_sesion_completa  # noqa: E402

CARPETA_ESTIMULOS = Path(r"C:\Tesis_Kevin\audio_estimulos")
CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")


def obtener_protocolo_tesis_final() -> list[dict]:
    """Protocolo experimental oficial de la tesis (ver PROTOCOLO EXPERIMENTAL
    FINAL DE LA TESIS en el docstring del módulo para la justificación
    completa de duraciones y selección de estímulos).

    Compara la respuesta fisiológica ante 3 tipos de estímulo terapéutico
    (Solfeggio, Binaural, Isocrónico — los dos últimos en rango Alpha) contra
    la preferencia sonora personal del participante.

    Los bloques "estimulo" NO traen "ruta": se resuelven por nombre contra
    audio_estimulos/ (o preferencia_wav, para "preferencia") cuando
    ejecutar_sesion_completa() llama a _resolver_audio_real() — igual que
    cualquier otro protocolo_personalizado con reproducir_audio_real=True.

    Duración total: 450s (7.5 min), sin contar estabilización.

    Returns:
        list[dict]: 9 bloques (baseline, solfeggio_528Hz, descanso1,
            binaural_alpha, descanso2, isocronico_alpha, descanso3,
            preferencia, cierre), cada uno con "tipo", "nombre" y
            "duracion_seg".
    """
    return [
        {"tipo": "silencio", "duracion_seg": 60, "nombre": "baseline"},
        {"tipo": "estimulo", "nombre": "solfeggio_528Hz", "duracion_seg": 60},
        {"tipo": "silencio", "duracion_seg": 30, "nombre": "descanso1"},
        {"tipo": "estimulo", "nombre": "binaural_alpha", "duracion_seg": 60},
        {"tipo": "silencio", "duracion_seg": 30, "nombre": "descanso2"},
        {"tipo": "estimulo", "nombre": "isocronico_alpha", "duracion_seg": 60},
        {"tipo": "silencio", "duracion_seg": 30, "nombre": "descanso3"},
        {"tipo": "estimulo", "nombre": "preferencia", "duracion_seg": 60},
        {"tipo": "silencio", "duracion_seg": 60, "nombre": "cierre"},
    ]


def _calcular_duracion_total_protocolo(protocolo: list[dict]) -> float:
    """Suma la duración nominal de todos los bloques del protocolo.

    El sensor cardíaco ya NO necesita esto (ver más abajo: captura por
    notificaciones en tiempo real, sin cronograma nominal). Pero
    CapturaAudio.grabar() sí lo necesita: a diferencia del sensor, no
    puede "escuchar" cuándo termina el protocolo y extender su grabación
    dinámicamente — hay que saber de antemano cuánto tiempo grabar. Por
    eso el audio se graba por esta duración nominal (con un
    pequeño margen de latencia normal de apertura de dispositivo, igual
    que en capturar_respiracion.py).

    Args:
        protocolo: Protocolo en formato ReproductorEstimulos (ver
            construir_protocolo_ejemplo()), o un protocolo personalizado
            con "duracion_seg" explícito en TODOS los bloques (ver
            silencioso_estimulos en ejecutar_sesion_completa()).

    Returns:
        float: Duración total nominal del protocolo, en segundos.
    """
    duracion_total = 0.0
    for bloque in protocolo:
        # Si el bloque ya trae duracion_seg (protocolo personalizado / modo
        # silencioso), se usa directo; si no, se asume bloque "estimulo" real
        # con "ruta" a un WAV, y se lee su duración del archivo
        if "duracion_seg" in bloque:
            duracion_total += float(bloque["duracion_seg"])
        else:
            duracion_total += sf.info(bloque["ruta"]).duration
    return duracion_total


def _resolver_ruta_estimulo(nombre_bloque: str, preferencia_wav: Optional[Path]) -> Optional[Path]:
    """Mapea el NOMBRE de un bloque de estímulo a un WAV real de audio_estimulos/.

    Mapeo (ver REPRODUCCIÓN DE AUDIO REAL en el docstring del módulo):
        "baseline" / "reposo" / cualquier otro nombre no reconocido → None
            (se trata como silencio: no hay WAV asociado a "no hacer nada")
        contiene "solfeggio"  → audio_estimulos/solfeggio/, buscando el
            patrón "NNNHz" dentro del propio nombre si lo trae (ej.
            "solfeggio_528Hz" -> "528Hz"), o cualquier solfeggio si no.
        contiene "binaural"   → audio_estimulos/binaurales/, buscando el
            rango que siga a "binaural_" (ej. "binaural_alpha" -> "alpha").
        contiene "isocronico" → audio_estimulos/isocronicos/, mismo criterio.
        contiene "preferencia" → usa preferencia_wav tal cual.

    Reutiliza ReproductorEstimulos._buscar_estimulo() (búsqueda por
    substring en el nombre de archivo) para no duplicar esa lógica.

    Args:
        nombre_bloque: El "nombre" del bloque del protocolo (ej. "solfeggio_528Hz").
        preferencia_wav: Ruta al audio de preferencia personal del
            participante, o None si no se indicó.

    Returns:
        Optional[Path]: Ruta al WAV a reproducir, o None si el nombre no
            corresponde a ningún estímulo con audio (debe tratarse como silencio).

    Raises:
        FileNotFoundError: Si el nombre pide un tipo de estímulo reconocido
            pero no se encuentra ningún WAV que calce (o, para
            "preferencia", si no se indicó preferencia_wav).
    """
    nombre_normalizado = nombre_bloque.lower()
    reproductor_temp = ReproductorEstimulos()  # solo para reusar _buscar_estimulo()

    if "solfeggio" in nombre_normalizado:
        match = re.search(r"\d+Hz", nombre_bloque, re.IGNORECASE)
        patron = match.group(0) if match else ""
        return reproductor_temp._buscar_estimulo(CARPETA_ESTIMULOS / "solfeggio", patron)

    if "binaural" in nombre_normalizado:
        resto = nombre_normalizado.split("binaural", 1)[1].strip("_")
        patron = resto.split("_")[0] if resto else "alpha"
        return reproductor_temp._buscar_estimulo(CARPETA_ESTIMULOS / "binaurales", patron)

    if "isocronico" in nombre_normalizado:
        resto = nombre_normalizado.split("isocronico", 1)[1].strip("_")
        patron = resto.split("_")[0] if resto else "alpha"
        return reproductor_temp._buscar_estimulo(CARPETA_ESTIMULOS / "isocronicos", patron)

    if "preferencia" in nombre_normalizado:
        if preferencia_wav is None:
            raise FileNotFoundError(
                f"El bloque '{nombre_bloque}' pide audio de preferencia personal, pero no "
                "se indicó preferencia_wav."
            )
        return Path(preferencia_wav)

    return None  # "baseline", "reposo", "descanso", "cierre", etc.: sin WAV, es silencio


def _resolver_audio_real(protocolo: list[dict], preferencia_wav: Optional[Path]) -> list[dict]:
    """Completa "ruta" en los bloques "estimulo" que aún no la tengan.

    No modifica el protocolo original (arma una lista/dicts nuevos) — el
    caller puede seguir usando su propio protocolo_personalizado sin
    efectos secundarios inesperados.

    Args:
        protocolo: Protocolo a resolver (ver formato en reproducir_protocolo()).
        preferencia_wav: Ver _resolver_ruta_estimulo().

    Returns:
        list[dict]: Copia del protocolo, con "ruta" agregada a los bloques
            "estimulo" que se pudieron resolver. Los bloques que ya traían
            "ruta" quedan intactos; los que no se pudieron resolver (nombre
            no reconocido, o error al buscar el archivo) se degradan a
            tipo "silencio" con una advertencia impresa, en vez de fallar
            toda la sesión por un solo bloque.
    """
    palabras_clave_estimulo = ("solfeggio", "binaural", "isocronico", "preferencia")
    protocolo_resuelto = []

    for bloque_original in protocolo:
        bloque = dict(bloque_original)

        if bloque["tipo"] == "estimulo" and "ruta" not in bloque:
            nombre_normalizado = bloque["nombre"].lower()
            es_nombre_reconocido = any(palabra in nombre_normalizado for palabra in palabras_clave_estimulo)

            try:
                ruta = _resolver_ruta_estimulo(bloque["nombre"], preferencia_wav)
            except FileNotFoundError as error:
                print(f"Advertencia: {error} El bloque '{bloque['nombre']}' se trata como silencio.")
                ruta = None

            if ruta is not None:
                bloque["ruta"] = ruta
            else:
                # Solo se avisa si el nombre SÍ parecía pedir un estímulo con audio (ej.
                # "solfeggio_999Hz" sin WAV que calce) — nombres como "baseline" o "reposo"
                # nunca tuvieron audio asociado, así que no hace falta advertir nada ahí
                if es_nombre_reconocido:
                    print(
                        f"Advertencia: no se pudo resolver audio para '{bloque['nombre']}'; "
                        "se trata como silencio (sin reproducir nada)."
                    )
                bloque["tipo"] = "silencio"

        protocolo_resuelto.append(bloque)

    return protocolo_resuelto


def _ejecutar_estabilizacion(sensor, tiempo_estabilizacion_seg: int) -> dict:
    """Lee del sensor durante tiempo_estabilizacion_seg segundos SIN guardar nada.

    Muestra un countdown en consola con la HR actual (útil para confirmar
    visualmente que el sensor real ya está transmitiendo), pero estas
    lecturas nunca llegan al CSV ni a estado_compartido — existen solo
    para que el hardware/la fisiología se asiente antes de que arranque el
    protocolo oficial (ver docstring del módulo).

    Args:
        sensor: Instancia de SimuladorCardiaco o SensorWahoo, ya conectada
            (o lista para usar) antes de llamar a esta función.
        tiempo_estabilizacion_seg: Segundos a esperar. 0 desactiva la
            estabilización (retorna de inmediato).

    Returns:
        dict: hr_promedio (float o None si no hubo lecturas válidas),
            num_lecturas (int, cuántas de las lecturas tomadas tenían
            hr_bpm > 0), tiempo_estabilizacion_seg (el mismo parámetro,
            para incluir en el reporte/metadata).
    """
    if tiempo_estabilizacion_seg <= 0:
        return {
            "hr_promedio": None,
            "num_lecturas": 0,
            "tiempo_estabilizacion_seg": 0,
        }

    # SimuladorCardiaco no reconoce "estabilizacion" como condición (lanzaría
    # ValueError); SensorWahoo acepta cualquier etiqueta libremente. Con el
    # sensor real queda registrado que estas lecturas son de estabilización;
    # con el simulado, se usa "reposo" como equivalente más cercano.
    try:
        sensor.cambiar_condicion("estabilizacion")
    except ValueError:
        sensor.cambiar_condicion("reposo")

    print(f"\n=== Estabilización ({tiempo_estabilizacion_seg}s) ===")
    print("Dejando que la respuesta cardíaca se asiente antes de iniciar el protocolo oficial...")

    hr_valores = []
    for segundos_restantes in range(tiempo_estabilizacion_seg, 0, -1):
        lectura = sensor.leer()
        if lectura["hr_bpm"] > 0:
            hr_valores.append(lectura["hr_bpm"])
        print(
            f"\rEstabilizando... {segundos_restantes:2d}s   HR={lectura['hr_bpm']:>3} bpm   ",
            end="",
            flush=True,
        )
        time.sleep(1)
    print()

    hr_promedio = round(sum(hr_valores) / len(hr_valores), 1) if hr_valores else None
    if hr_promedio is not None:
        print(f"Estabilización completa. HR promedio durante estabilización: {hr_promedio} bpm")
    else:
        print("Estabilización completa (sin lecturas válidas de HR).")

    return {
        "hr_promedio": hr_promedio,
        "num_lecturas": len(hr_valores),
        "tiempo_estabilizacion_seg": tiempo_estabilizacion_seg,
    }


def _hilo_sensor(
    captura_sesion: CapturaSesion,
    t0: float,
    fecha_hora: str,
    estado_compartido: dict,
    resultado: dict,
    lock: threading.Lock,
) -> None:
    """Cuerpo del hilo A: captura cardíaca durante toda la sesión.

    Corre en modo NOTIFICACIONES (estado_compartido) en vez de modo
    cronograma: no sigue un protocolo nominal precalculado, sino que en
    cada lectura consulta qué estímulo está sonando AHORA MISMO según el
    hilo de estímulos — así "condicion" queda sincronizada con los
    eventos reales sin la deriva que tenía el cronograma nominal.
    """
    try:
        ruta_csv = captura_sesion.ejecutar(
            t0_externo=t0, fecha_hora=fecha_hora, estado_compartido=estado_compartido
        )
        with lock:
            resultado["ruta_csv"] = ruta_csv
    except Exception as error:
        with lock:
            resultado["error_sensor"] = str(error)
        print(f"\n[hilo sensor] ERROR: {error}")


def _hilo_estimulos(
    reproductor: ReproductorEstimulos,
    protocolo: list[dict],
    t0: float,
    estado_compartido: dict,
    resultado: dict,
    lock: threading.Lock,
    silencioso: bool = False,
) -> None:
    """Cuerpo del hilo B: reproducción del protocolo de estímulos.

    Notifica a estado_compartido antes de cada bloque (ver
    ReproductorEstimulos.reproducir_protocolo()). Si este hilo falla a
    mitad de camino, el except de abajo igual marca "fin" — si no, el
    hilo del sensor (que espera ese valor para terminar su bucle)
    quedaría esperando para siempre y sesion_completa.py nunca terminaría.

    Args:
        silencioso: Si True, no reproduce audio real (no sd.play()), pero
            SÍ avanza en tiempo real (avance_instantaneo=False: usa
            time.sleep() en cada bloque) — necesario porque este módulo
            corre todo en paralelo y sincronizado; el modo instantáneo de
            reproducir_protocolo() (pensado para
            simulador_multiparticipante.py, donde nada más corre en
            tiempo real) notificaría "fin" casi al instante y cortaría la
            captura del sensor tras una sola lectura.
    """
    try:
        eventos = reproductor.reproducir_protocolo(
            protocolo,
            t0_externo=t0,
            estado_compartido=estado_compartido,
            silencioso=silencioso,
            avance_instantaneo=False,
        )
        with lock:
            resultado["eventos"] = eventos
    except Exception as error:
        estado_compartido["estimulo_actual"] = "fin"
        with lock:
            resultado["error_estimulos"] = str(error)
        print(f"\n[hilo estimulos] ERROR: {error}")


def _hilo_audio(
    captura_audio: CapturaAudio,
    duracion_seg: float,
    participante_id: str,
    t0: float,
    fecha_hora: str,
    resultado: dict,
    lock: threading.Lock,
) -> None:
    """Cuerpo del hilo C: grabación de audio durante toda la sesión.

    Si el micrófono falla durante la grabación (no solo al detectarlo
    antes de arrancar), se captura la excepción acá para que los otros dos
    hilos (sensor y estímulos) terminen con normalidad — la sesión se
    guarda igual, solo que sin audio.
    """
    try:
        metadata = captura_audio.grabar_con_metadata(
            duracion_seg,
            participante_id,
            condicion="sesion_completa",
            t0_externo=t0,
            fecha_hora=fecha_hora,
        )
        with lock:
            resultado["metadata_audio"] = metadata
    except Exception as error:
        print(f"\n[hilo audio] Advertencia: falló la grabación ({error}). Se continúa sin audio.")
        with lock:
            resultado["metadata_audio"] = None
            resultado["error_audio"] = str(error)


def ejecutar_sesion_completa(
    participante_id: str,
    protocolo_corto: bool = True,
    usar_sensor_real: bool = False,
    mac_address: Optional[str] = None,
    silencioso_estimulos: bool = False,
    protocolo_personalizado: Optional[list[dict]] = None,
    usar_protocolo_final: bool = False,
    tiempo_estabilizacion_seg: int = 30,
    reproducir_audio_real: bool = False,
    preferencia_wav: Optional[Path] = None,
    dispositivo_salida_audio: Optional[int] = None,
    analizar_automaticamente: bool = True,
) -> dict:
    """Ejecuta sensor cardíaco + grabación de audio + reproducción de estímulos en paralelo.

    Args:
        participante_id: Identificador del participante, ej. "P01".
        protocolo_corto: Si True, usa bloques de 5-10s (~30-40s de sesión
            total) para pruebas rápidas. Si False, usa las duraciones
            reales del protocolo de la tesis (60s por estímulo, ~10 min
            total). Ignorado si se indica protocolo_personalizado.
        usar_sensor_real: Si True, usa SensorWahoo (driver BLE real, ver
            python/sensor/sensor_wahoo.py) corriendo en un hilo aparte con
            su propio event loop (ver HiloSensorBLE), en vez de
            SimuladorCardiaco. Requiere el sensor Wahoo TRACKR HR
            encendido y puesto.
        mac_address: MAC del sensor Wahoo a usar (ver escanear_ble.py).
            Solo aplica si usar_sensor_real=True; None usa el default de
            SensorWahoo (el sensor ya identificado, D6:39:AD:0F:AC:46).
        silencioso_estimulos: Si True, el hilo de estímulos NO reproduce
            audio real (sin sd.play()): solo calcula los eventos con
            timing nominal y notifica igual a estado_compartido. Útil para
            probar el sensor real sin depender de la biblioteca de
            estímulos ni de hardware de salida de audio. Requiere que
            TODOS los bloques del protocolo usado (ver
            protocolo_personalizado) traigan "duracion_seg" explícito,
            incluidos los de tipo "estimulo" (ver
            ReproductorEstimulos.reproducir_protocolo()).
        protocolo_personalizado: Si se indica, se usa este protocolo tal
            cual (lista de bloques dict) en vez de construirlo con
            construir_protocolo_ejemplo() — pensado para pruebas puntuales
            con una secuencia de bloques distinta a la del protocolo
            estándar de la tesis (ej. una prueba corta con el sensor real).
            Tiene prioridad sobre usar_protocolo_final si ambos se indican.
        usar_protocolo_final: Si True, usa obtener_protocolo_tesis_final()
            (ver PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS en el docstring
            del módulo): el protocolo estandarizado de 8 minutos
            (baseline, solfeggio_528Hz, descanso, binaural_alpha,
            descanso, isocronico_alpha, descanso, preferencia, cierre)
            que se usará con todos los participantes del estudio (450s
            capturados, 480s de pared con estabilización por defecto).
            Ignorado si se indica protocolo_personalizado. Requiere
            preferencia_wav (el bloque "preferencia" no tiene sentido sin
            él) — lanza ValueError si no se indica.
        tiempo_estabilizacion_seg: Segundos de lectura "de descarte" antes
            de arrancar el protocolo oficial (default 30; usar 60 para
            sesiones más rigurosas, o 0 para desactivarlo en pruebas
            rápidas). Ver PERÍODO DE ESTABILIZACIÓN en el docstring del
            módulo para el rationale completo.
        reproducir_audio_real: Si True, reproduce por los altavoces/audífonos
            el WAV real correspondiente a cada bloque "estimulo" (ver
            REPRODUCCIÓN DE AUDIO REAL en el docstring del módulo). Si
            False (default), los bloques quedan solo como etiquetas para
            el sensor, sin sonar nada — el comportamiento que ya existía.
            Fuerza silencioso_estimulos=False internamente (no tiene
            sentido pedir audio real y a la vez pedir que no suene nada).
        preferencia_wav: Ruta al audio de preferencia personal del
            participante. Solo se usa si reproducir_audio_real=True y el
            protocolo tiene un bloque cuyo nombre contiene "preferencia".
        dispositivo_salida_audio: Índice del dispositivo de salida a usar
            para reproducir los estímulos (ver listar_dispositivos_audio.py).
            None usa el dispositivo de salida por defecto del sistema.
        analizar_automaticamente: Si True (default), al terminar de guardar
            los 3 archivos de la sesión se ejecuta automáticamente
            analizar_sesion_completa() (ver python/analisis/analizar_sesion_completa.py):
            sincroniza los 3 archivos, calcula HR/HRV por bloque, analiza
            respiración segmentada por bloque, calcula una recomendación,
            y genera un reporte Markdown consolidado. Si falla, se
            imprime una advertencia pero NO se pierde la sesión ya
            capturada (los 3 archivos ya están guardados en disco antes
            de intentar analizarlos). Si False, la función solo captura y
            guarda, sin analizar nada (comportamiento original).

    Returns:
        dict: participante_id, ruta_csv (Path), ruta_wav (Path o None si
            no había micrófono disponible), ruta_json_estimulos (Path),
            duracion_total_seg (float, tiempo de pared real de la sesión,
            sin contar la estabilización), resumen_estabilizacion (dict
            con hr_promedio, num_lecturas, tiempo_estabilizacion_seg),
            ruta_reporte (Path o None si analizar_automaticamente=False o
            si el análisis automático falló).

    Raises:
        RuntimeError: Si falla la captura cardíaca o la reproducción de
            estímulos (los dos hilos que SÍ son indispensables para tener
            una sesión válida; el audio es opcional).
        Exception: Si usar_sensor_real=True y no logra conectar al sensor
            Wahoo (propagada desde HiloSensorBLE.iniciar(), antes de
            lanzar ningún hilo — falla rápido y claro).
    """
    fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")

    # --- Protocolo de estímulos (mismo para el reproductor y, traducido, para el sensor) ---
    reproductor = ReproductorEstimulos(device_id=dispositivo_salida_audio)
    carpeta_estimulos_temp: Optional[Path] = None

    if protocolo_personalizado is not None:
        protocolo = protocolo_personalizado
    elif usar_protocolo_final:
        if preferencia_wav is None:
            raise ValueError(
                "usar_protocolo_final=True requiere preferencia_wav: el bloque "
                "'preferencia' del protocolo final de la tesis necesita saber qué "
                "audio reproducir para ese bloque."
            )
        protocolo = obtener_protocolo_tesis_final()
    elif protocolo_corto:
        # construir_protocolo_ejemplo() solo controla la duración de los bloques de
        # SILENCIO (duracion_silencio_seg/duracion_descanso_seg); los bloques de
        # ESTÍMULO duran lo que dure el WAV que encuentre en carpeta_estimulos. Como
        # los WAV reales de audio_estimulos/ duran 60s cada uno, para lograr una
        # sesión de prueba de ~30-40s se generan estímulos cortos temporales (mismo
        # truco que en el __main__ de reproductor_estimulos.py) y se apunta ahí en
        # vez de a la biblioteca real.
        from generador_tonos import GeneradorTonos  # import local: solo se usa aquí

        carpeta_estimulos_temp = CARPETA_SESIONES / "_temp_estimulos_sesion_completa"
        generador_prueba = GeneradorTonos(duracion_seg=4)
        generador_prueba.generar_solfeggio(
            528, carpeta_estimulos_temp / "solfeggio" / "solfeggio_528Hz_prueba.wav"
        )
        generador_prueba.generar_binaural(
            200, 10, carpeta_estimulos_temp / "binaurales" / "binaural_10Hz_alpha_prueba.wav"
        )
        generador_prueba.generar_isocronico(
            200, 10, carpeta_estimulos_temp / "isocronicos" / "isocronico_10Hz_alpha_prueba.wav"
        )

        protocolo = reproductor.construir_protocolo_ejemplo(
            carpeta_estimulos_temp, duracion_silencio_seg=5, duracion_descanso_seg=3
        )
    else:
        protocolo = reproductor.construir_protocolo_ejemplo(CARPETA_ESTIMULOS)

    if reproducir_audio_real:
        protocolo = _resolver_audio_real(protocolo, preferencia_wav)

    duracion_total_protocolo = _calcular_duracion_total_protocolo(protocolo)

    # --- Sensor cardíaco: real (BLE, en su propio hilo) o simulado ---
    hilo_ble: Optional[HiloSensorBLE] = None
    if usar_sensor_real:
        print("Conectando al sensor Wahoo real (esto puede tardar unos segundos)...")
        sensor = SensorWahoo(mac_address=mac_address) if mac_address else SensorWahoo()
        hilo_ble = HiloSensorBLE(sensor)
        hilo_ble.iniciar()  # bloquea hasta conectar; si falla, lanza la excepción acá mismo
    else:
        sensor = SimuladorCardiaco()

    captura_sesion = CapturaSesion(sensor=sensor, participante_id=participante_id, frecuencia_hz=1.0)
    # No se llama programar_estimulos(): en modo notificaciones (ver _hilo_sensor) el
    # sensor no sigue un cronograma nominal, así que no lo necesita.

    # --- Micrófono: se prueba ANTES de lanzar hilos; si no hay hardware disponible,
    # se omite el hilo de audio por completo en vez de lanzarlo para que falle ---
    captura_audio: Optional[CapturaAudio] = None
    try:
        candidata = CapturaAudio()
        info_dispositivo = candidata.get_dispositivo_info()
        if info_dispositivo["canales_entrada"] > 0:
            captura_audio = candidata
        else:
            print(
                "Advertencia: el dispositivo de entrada por defecto no tiene canales "
                "de entrada; se omite la grabación de audio."
            )
    except Exception as error:
        print(f"Advertencia: no se pudo acceder al micrófono ({error}); se omite la grabación de audio.")

    # --- Estabilización: lee del sensor y descarta, ANTES de fijar t0. Así t0 (y por lo
    # tanto el t=0 del CSV) arranca justo cuando empieza el protocolo oficial, nunca
    # durante la estabilización (ver PERÍODO DE ESTABILIZACIÓN en el docstring del módulo) ---
    resumen_estabilizacion = _ejecutar_estabilizacion(sensor, tiempo_estabilizacion_seg)

    # --- t0 y estado_compartido: se crean UNA sola vez, justo antes de lanzar los hilos.
    # estado_compartido["estimulo_actual"] arranca con el nombre del primer bloque (en vez
    # de un genérico "reposo") para no dejar ni una lectura mal etiquetada mientras el hilo
    # de estímulos ejecuta su primera notificación real. ---
    resultado: dict = {"metadata_audio": None}
    estado_compartido: dict = {"estimulo_actual": protocolo[0]["nombre"]}
    lock = threading.Lock()
    t0 = time.monotonic()

    # reproducir_audio_real=True fuerza silencioso=False: no tiene sentido haber
    # resuelto rutas de audio real y a la vez pedirle al reproductor que no suene nada
    silencioso_efectivo = False if reproducir_audio_real else silencioso_estimulos

    hilos = [
        threading.Thread(
            target=_hilo_sensor,
            args=(captura_sesion, t0, fecha_hora, estado_compartido, resultado, lock),
            name="sensor",
        ),
        threading.Thread(
            target=_hilo_estimulos,
            args=(reproductor, protocolo, t0, estado_compartido, resultado, lock, silencioso_efectivo),
            name="estimulos",
        ),
    ]
    if captura_audio is not None:
        hilos.append(
            threading.Thread(
                target=_hilo_audio,
                args=(captura_audio, duracion_total_protocolo, participante_id, t0, fecha_hora, resultado, lock),
                name="audio",
            )
        )

    print(
        f"=== Sesión completa: {participante_id} | {len(hilos)} hilos en paralelo | "
        f"protocolo ~{duracion_total_protocolo:.0f}s ===\n"
    )

    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    duracion_total_real = time.monotonic() - t0

    if hilo_ble is not None:
        # Espera antes de desconectar (no antes de calcular duracion_total_real, para
        # no inflar la duración reportada de la sesión): da margen a que termine de
        # procesarse cualquier notificación BLE que ya estuviera en camino cuando el
        # último bloque terminó, en vez de cortar la conexión de golpe
        print("Esperando 2.5s antes de desconectar el sensor Wahoo...")
        time.sleep(2.5)
        hilo_ble.detener()

    if carpeta_estimulos_temp is not None:
        # Los estímulos cortos eran solo para esta prueba, no forman parte de la
        # biblioteca real; se borran ya que los tres hilos terminaron de usarlos
        import shutil

        shutil.rmtree(carpeta_estimulos_temp, ignore_errors=True)

    if "ruta_csv" not in resultado:
        raise RuntimeError(f"Falló la captura cardíaca: {resultado.get('error_sensor', 'error desconocido')}")
    if "eventos" not in resultado:
        raise RuntimeError(
            f"Falló la reproducción de estímulos: {resultado.get('error_estimulos', 'error desconocido')}"
        )

    # El JSON de eventos se guarda acá (no dentro del hilo) para poder usar el
    # mismo fecha_hora compartido y así identificar los 3 archivos como una sesión.
    # La estabilización NO se incluye como bloque de "eventos" (nunca se le pidió a
    # ReproductorEstimulos que la reproduzca) — solo queda registrada como metadata,
    # para tener constancia de que sí se hizo sin mezclarla con el protocolo oficial.
    ruta_json_estimulos = CARPETA_SESIONES / f"{participante_id}_estimulos_{fecha_hora}.json"
    metadata_estimulos = {
        "tiempo_estabilizacion_seg": resumen_estabilizacion["tiempo_estabilizacion_seg"],
        "estabilizacion_completada": True,
    }
    reproductor.guardar_eventos(resultado["eventos"], ruta_json_estimulos, metadata=metadata_estimulos)

    ruta_wav = (
        Path(resultado["metadata_audio"]["ruta_wav"]) if resultado["metadata_audio"] is not None else None
    )

    print("\n=== Sesión completa finalizada ===")
    print(f"CSV cardíaco:   {resultado['ruta_csv']}")
    print(f"WAV audio:      {ruta_wav if ruta_wav else '(no disponible)'}")
    print(f"JSON estímulos: {ruta_json_estimulos}")
    print(f"Duración total real: {duracion_total_real:.1f}s (sin contar estabilización)")

    # El análisis automático corre DESPUÉS de que los 3 archivos ya están guardados en
    # disco — si falla, la sesión capturada no se pierde, solo no queda su reporte
    ruta_reporte = None
    if analizar_automaticamente:
        print("\n=== Ejecutando análisis automático post-sesión ===")
        try:
            ruta_reporte = analizar_sesion_completa(
                participante_id=participante_id,
                ruta_csv=resultado["ruta_csv"],
                ruta_wav=ruta_wav,
                ruta_json_eventos=ruta_json_estimulos,
            )
        except Exception as error:
            print(
                f"Advertencia: el análisis automático falló ({error}); "
                "los 3 archivos de la sesión sí se guardaron correctamente."
            )

    return {
        "participante_id": participante_id,
        "ruta_csv": resultado["ruta_csv"],
        "ruta_wav": ruta_wav,
        "ruta_json_estimulos": ruta_json_estimulos,
        "duracion_total_seg": round(duracion_total_real, 2),
        "resumen_estabilizacion": resumen_estabilizacion,
        "ruta_reporte": ruta_reporte,
    }


if __name__ == "__main__":
    # tiempo_estabilizacion_seg=0: este es el demo RÁPIDO (protocolo_corto=True), pensado
    # para probar que el pipeline corre de punta a punta, no una sesión experimental real
    # — la estabilización importa para HRV limpio, no para un smoke test de ~30-40s.
    resultado = ejecutar_sesion_completa(
        participante_id="P01", protocolo_corto=True, tiempo_estabilizacion_seg=0
    )

    print("\n=== Rutas generadas ===")
    print(f"CSV cardíaco:   {resultado['ruta_csv']}")
    print(f"WAV audio:      {resultado['ruta_wav']}")
    print(f"JSON estímulos: {resultado['ruta_json_estimulos']}")
    print(f"Duración total: {resultado['duracion_total_seg']}s")
