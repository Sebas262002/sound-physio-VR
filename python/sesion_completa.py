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

INTERACCIÓN EMBEBIDA: esperar a que el participante se siente (usar_vr=True):
A pedido del tutor, el participante ya no está quieto desde el arranque:
camina libremente por el entorno VR (con los dos joysticks, sin sostener
nada en la mano — ver por qué esto importaba en el diseño anterior de
"micrófono en la mano") hasta que decide sentarse en la silla virtual. Del
lado Unity, SentarseTrigger.cs detecta esto (colisión de la cámara del
casco con un trigger cerca de la silla + 2s de permanencia) y
SesionStateMachine.cs confirma con 3s adicionales de preparación antes de
mandar "/sesion/inicio" por OSC (ver CONTRATO OSC en vr/unity_osc.py).

Este módulo espera esa confirmación con UnityOSC.esperar_confirmacion_sentado()
DESPUÉS de conectar el sensor y el micrófono, pero ANTES de la
estabilización — así la estabilización (que exige que el participante ya
esté quieto, ver PERÍODO DE ESTABILIZACIÓN arriba) ocurre de verdad estando
sentado, no mientras todavía camina. Es una espera SIN límite de tiempo por
diseño (decisión explícita: cortarla con un timeout arbitrario interrumpiría
una sesión real válida solo porque el participante tardó en acomodarse) —
quien llama puede cortarla a mano con `cancelar_espera_sentado` (scripts de
consola: Ctrl+C; app_investigador.py: botón "Cancelar sesión" en la Vista en
vivo). Si se cancela, esta función lanza RuntimeError como cualquier otro
fallo de la captura (ver el resto del docstring) — no hay hilos que limpiar
todavía en ese punto, ninguno de los 3 hilos reales llegó a arrancar.

Si Unity no respondió siquiera a iniciar_sesion() (apagado, escena sin
Play), esta espera NO se ejecuta — no tendría sentido esperar una señal que
nunca va a poder llegar. La sesión sigue en modo degradado de siempre (ver
PERSISTENCIA / degradación): arranca de inmediato, sin VR, tal como con
usar_vr=False.

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

PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS (parámetro `dia`):
La primera versión de este protocolo metía las 4 condiciones (Solfeggio,
Binaural, Isocrónico, Preferencia) en UNA sola sesión de ~8 minutos, con
solo 30s de descanso entre cada una. El director de tesis observó que
ese diseño de "sesiones seguidas" no sirve para atribuir con confianza
un cambio fisiológico a un estímulo específico: el efecto de arrastre
(carryover) entre condiciones consecutivas contamina la respuesta del
estímulo siguiente, sin importar cuánto descanso corto se intercale (ver
también, para la justificación teórica completa, la sección del
protocolo experimental en el Estado del Arte de la tesis, Cap. II).

El protocolo corregido (ver obtener_protocolo_sesion_dia() y
asignar_estimulos_dia1_dia3()) evalúa cada tipo de estímulo en su PROPIA
sesión, en un día distinto, separadas por 24-48 horas:

    Día 1: baseline(120s) -> uno de los 3 tipos estandarizados,
           sorteado (300s) -> cierre(60s)
    Día 2: baseline(120s) -> preferencia personal, canción #1 (300s) -> cierre(60s)
    Día 3: baseline(120s) -> el tipo estandarizado restante que NO
           salió en Día 1 (300s) -> cierre(60s)
    Día 4: baseline(120s) -> preferencia personal, canción #2 —
           DISTINTA a la de Día 2 (300s) -> cierre(60s)

Cada sesión captura 480s (8 min); con estabilización (30s default, no
incluida en el protocolo, ver tiempo_estabilizacion_seg): 510s (8.5 min)
de pared. Cuatro sesiones por participante en total, no una.

¿Por qué 2 sesiones de preferencia (Día 2 y Día 4) en vez de 1? La
Hipótesis de la tesis (H1/H0, Cap. I) compara DOS GRUPOS — "frecuencias
terapéuticas comunes" vs. "sonidos de preferencia personal" — no estímulos
individuales entre sí. Con una sola sesión de preferencia, ese grupo
quedaba representado por un único dato; agregar una segunda sesión (con
una canción DISTINTA, no una repetición — evita que la segunda medición
esté sesgada por habituación al MISMO estímulo) da más datos para ese
grupo, dejando la comparación 2 sesiones terapéuticas vs. 2 sesiones de
preferencia, simétrica en ambos lados. Ver
Recomendador.comparar_grupos_terapeutica_vs_preferencia() (recomendador.py)
para cómo se promedian esas 2 sesiones de cada grupo — SIEMPRE normalizando
cada una contra el baseline de SU PROPIO día antes de promediar, nunca
mezclando HR crudo de baselines distintos.

¿Por qué estos 3 tipos estandarizados (Binaural Theta, Solfeggio +
isocrónico, Paisaje biofílico) y no otra combinación? Son los tres
enfoques que el Estado del Arte de la tesis (Cap. II, "Enfoques de
Estimulación Sonora en Entornos Virtuales") documenta con representación
comparable en la literatura revisada, sin que ninguno se muestre
consistentemente superior a los demás. Binaural Theta usa la receta
citada textualmente en el Estado del Arte (429 Hz oído izquierdo, 435 Hz
oído derecho, beat percibido de 6 Hz — Saldırım & Şerbetçioğlu, 2025).
Solfeggio + isocrónico combina en un solo estímulo las dos técnicas que
el texto agrupa bajo un mismo enfoque (portadora Solfeggio de 528 Hz,
pulsada isocrónicamente en Theta). Paisaje biofílico es una síntesis de
agua + brisa + aves (ver generador_tonos.py) que aproxima, sin depender
de grabaciones con licencia incierta, los paisajes sonoros naturales que
la literatura documenta con capacidad restauradora (Jin et al., 2026;
Kawai et al., 2025; Long et al., 2023, 2024).

¿Por qué se SORTEA cuál de los 3 le toca a Día 1 y a Día 3 en vez de
fijarlo? Justamente porque el Estado del Arte concluye que ningún tipo
domina sobre los demás — fijar arbitrariamente uno sería una decisión no
justificada por la literatura. Cada participante termina evaluando 2 de
los 3 tipos estandarizados (distintos entre participantes, salvo
coincidencia del sorteo) más 2 mediciones de su propia preferencia
personal (Días 2 y 4, canciones distintas). Ver
asignar_estimulos_dia1_dia3() para el mecanismo exacto del sorteo de los
tipos estandarizados (determinista por participante, sin necesitar
guardar estado entre sesiones) — los Días 2 y 4 no se sortean, siempre
son "preferencia", solo cambia qué canción trae el participante cada vez.

Todo esto se contrasta contra la condición que de verdad importa para la
hipótesis central de la tesis: la preferencia sonora personal del
participante (Días 2 y 4, tomadas en conjunto como UN grupo — ver más
abajo), evaluando si un estímulo "genérico" bien fundamentado en teoría
puede igualar o superar la respuesta fisiológica ante lo que el
participante YA prefiere escuchar.

¿Por qué 120 segundos de baseline (no 60s, que era el valor de la
versión anterior de este módulo)? El Estado del Arte exige
explícitamente "2 minutos de reposo basal" antes de cada estímulo para
asegurar una línea base limpia e individual — 60s alcanzaba apenas el
piso del Task Force ESC/NASPE (1996) para que SDNN sea calculable, pero
no cumplía ese requisito específico del diseño experimental ya aprobado
de la tesis.

¿Por qué 300 segundos de estímulo (no 60s)? Coincide con la duración
real de los WAV generados por generador_tonos.py: la ventana mínima para
que RMSSD/SDNN sean confiables (Task Force ESC/NASPE, 1996, "Heart rate
variability: standards of measurement, physiological interpretation, and
clinical use") y la duración óptima de inmersión sin fatiga, validada
por Jin et al. (2026) y Liu & Li (2026).

¿Por qué 60 segundos de cierre? No es un requisito citado explícitamente
en el Estado del Arte — es una práctica de ingeniería para terminar la
sesión con un bloque de reposo limpio antes de desconectar el sensor, en
vez de cortar la captura justo cuando termina el estímulo (momento en
que la respuesta fisiológica todavía está en transición).

¿Cómo se compara con la preferencia personal? El bloque "preferencia" se
resuelve, mapea y reproduce exactamente igual que los bloques de
estímulo estandarizado (mismo pipeline de _resolver_ruta_estimulo() /
reproducir_por_duracion()) — la única diferencia es que su WAV no sale
de audio_estimulos/ sino del parámetro preferencia_wav (el audio que el
participante trae de antemano). Al usar la MISMA estructura de sesión
(baseline 120s + estímulo 300s + cierre 60s) que Día 1 y Día 3, su
métrica HRV/HR/respiración queda directamente comparable con las de los
tipos estandarizados sin ningún ajuste adicional — la comparación
"terapéuticas vs. preferencia" (el hallazgo central de la tesis, ver
Recomendador.comparar_grupos_terapeutica_vs_preferencia() en
recomendador.py) agrupa las 4 sesiones de un mismo participante en esos
2 grupos (Días 1+3 vs. Días 2+4) y promedia dentro de cada uno.

PERSISTENCIA EN SQL SERVER (guardar_en_bd):
Además de los 3 archivos locales (CSV/WAV/JSON, que SIEMPRE se guardan —
SQL Server es un agregado en paralelo, nunca los reemplaza), con
guardar_en_bd=True (default) la sesión también queda en las tablas
participantes/sesiones/pruebas de SQL Server (ver
python/database/bd_sqlserver.py). Para esto se reutiliza
analizar_metricas_sesion() UNA sola vez (no dos): la misma tabla de
métricas por bloque alimenta tanto el reporte .md (si
analizar_automaticamente=True) como las filas de "pruebas" — evita
correr el análisis dos veces.

Como este módulo nunca recolectó datos demográficos del participante
(edad/género — no hay ningún paso del protocolo que los pida), si el
participante no existe todavía en 'participantes' se
auto-registra con esos campos en NULL y una observación que lo deja
explícito. Hace falta completarlos a mano (por SQL directo, o editando la
fila) si se necesitan para el análisis por esos factores.

Si SQL Server no está disponible (servidor apagado, credenciales
inválidas, etc.), el guardado en base de datos falla con una advertencia
impresa — la sesión capturada NUNCA se pierde, ya está en disco antes de
intentar guardarla en SQL Server.
"""

import math
import re
import sys
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

sys.path.insert(0, r"C:\Tesis_Kevin\python\sensor")
sys.path.insert(0, r"C:\Tesis_Kevin\python\audio")
sys.path.insert(0, r"C:\Tesis_Kevin\python\analisis")
sys.path.insert(0, r"C:\Tesis_Kevin\python\database")
sys.path.insert(0, r"C:\Tesis_Kevin\python")  # para "import vr.unity_osc" (paquete, no módulo suelto)

from simulador_cardiaco import SimuladorCardiaco  # noqa: E402
from capturar_sesion import CapturaSesion  # noqa: E402
from sensor_wahoo import SensorWahoo, HiloSensorBLE  # noqa: E402
from capturar_respiracion import CapturaAudio  # noqa: E402
from reproductor_estimulos import ReproductorEstimulos  # noqa: E402
from analizar_sesion_completa import analizar_metricas_sesion, _generar_reporte_md  # noqa: E402
from bd_sqlserver import BaseDatosTesis, mapear_bloque_a_prueba  # noqa: E402
from vr.unity_osc import UnityOSC  # noqa: E402

CARPETA_ESTIMULOS = Path(r"C:\Tesis_Kevin\audio_estimulos")
CARPETA_SESIONES = Path(r"C:\Tesis_Kevin\datos\sesiones")


# Los 3 tipos de estímulo estandarizado que compiten por Día 1 y Día 3 (ver
# PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS más arriba). Cada participante
# recibe 2 de estos 3 (uno por día, sorteados por asignar_estimulos_dia1_dia3());
# el tercero simplemente no se le aplica a ese participante en particular.
# Estos son los "nombre" de bloque que espera _resolver_ruta_estimulo().
TIPOS_ESTANDARIZADOS = ["binaural_theta", "solfeggio_isocronico_528Hz", "paisaje_biofilico"]

# Skybox de Unity por bloque, solo relevante si usar_vr=True (ver
# obtener_protocolo_sesion_dia() y vr/unity_osc.py). Los bloques de descanso
# NO tienen entrada acá a propósito: "usar el skybox del bloque anterior" se
# resuelve programáticamente más abajo, no se hardcodea por duplicado (si
# alguna vez cambia el orden de bloques, no hay dos lugares que mantener
# sincronizados a mano).
_AMBIENTE_VR_POR_BLOQUE = {
    "baseline": "FS002_Day",  # dia luminoso calmado, igual los 3 dias
    "binaural_theta": "FS000_Day_06",  # dia con luna, magico
    "solfeggio_isocronico_528Hz": "FS013_Day",  # dia alternativo, energetico
    "paisaje_biofilico": "FS017_Day",  # entorno natural/despejado, coherente con agua+brisa+aves
    "preferencia": "FS002_Night",  # noche intima
    "cierre": "FS017_Sunset",  # atardecer de despedida
}


def asignar_estimulos_dia1_dia3(participante_id: str, semilla: Optional[int] = None) -> tuple[str, str]:
    """Sortea qué 2 de los 3 tipos estandarizados le tocan a Día 1 y Día 3.

    Ver "¿Por qué se SORTEA cuál de los 3 le toca...?" en el docstring del
    módulo: como el Estado del Arte no encuentra un tipo consistentemente
    superior a los demás, el sistema sortea en vez de fijar uno
    arbitrariamente. Día 2 siempre es la preferencia personal — no
    participa de este sorteo.

    Reproducibilidad: si semilla es None (default), la asignación se
    deriva de forma determinista de participante_id (mismo participante
    -> mismo resultado siempre), así que llamar a esta función por
    separado el día de la sesión 1 y otra vez el día de la sesión 3 (dos
    ejecuciones distintas del script, días distintos) da el mismo
    resultado sin necesitar guardar ningún estado intermedio entre
    sesiones. Pasar una semilla explícita solo tiene sentido para
    pruebas donde se quiere forzar una asignación repetible
    independiente del participante_id.

    Args:
        participante_id: ID del participante, ej. "P01".
        semilla: Semilla explícita para el generador aleatorio. None usa
            un hash estable (CRC32) de participante_id como semilla.

    Returns:
        tuple[str, str]: (tipo_dia1, tipo_dia3) — dos valores distintos
            de TIPOS_ESTANDARIZADOS. El tercer tipo (no devuelto) es el
            que NO se le aplica a este participante.
    """
    if semilla is None:
        semilla = zlib.crc32(participante_id.encode("utf-8"))
    rng = np.random.default_rng(semilla)
    orden = rng.permutation(TIPOS_ESTANDARIZADOS)
    return str(orden[0]), str(orden[1])


def obtener_protocolo_sesion_dia(
    tipo_estimulo: str,
    duracion_baseline_seg: int = 120,
    duracion_estimulo_seg: int = 300,
    duracion_cierre_seg: int = 60,
    usar_vr: bool = False,
) -> list[dict]:
    """Protocolo de UNA sesión de UN día (ver PROTOCOLO EXPERIMENTAL FINAL
    DE LA TESIS en el docstring del módulo para la justificación completa):
    baseline -> un único estímulo -> cierre. Nunca mezcla más de un tipo de
    estímulo en la misma sesión — es justo lo que corrige este diseño
    frente a la versión anterior de este módulo (obtener_protocolo_tesis_final(),
    eliminada), que metía las 4 condiciones seguidas en una sola sesión de
    ~8 minutos.

    Cada tipo de estímulo se evalúa en su PROPIA sesión, en un día distinto
    (24-48h de separación): Día 1 y Día 3 con dos de los tres tipos de
    TIPOS_ESTANDARIZADOS (ver asignar_estimulos_dia1_dia3()), y Día 2 y
    Día 4 con la preferencia personal (dos canciones distintas, ver
    PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS) — pero esta función solo
    arma el protocolo de UN día; quién llama decide (o consulta
    asignar_estimulos_dia1_dia3()) qué día es y qué tipo le corresponde.

    Args:
        tipo_estimulo: Uno de TIPOS_ESTANDARIZADOS ("binaural_theta",
            "solfeggio_isocronico_528Hz", "paisaje_biofilico") o
            "preferencia" (Día 2 o Día 4 — el nombre de bloque es igual
            en ambos, lo que cambia es qué WAV se le resuelve, ver
            _resolver_audio_real()). Se usa tal cual como "nombre" del
            bloque de estímulo, así que _resolver_ruta_estimulo() lo
            resuelve contra audio_estimulos/ sin transformación.
        duracion_baseline_seg: Duración del bloque "baseline" inicial.
            Default 120 (2 minutos): el mínimo que exige el Estado del
            Arte para una línea base fisiológica limpia antes de cada
            estímulo.
        duracion_estimulo_seg: Duración del bloque de estímulo. Default
            300 (5 minutos): coincide con la duración real de los WAV
            generados por generador_tonos.py (ver ese módulo para la
            justificación completa de por qué 5 minutos).
        duracion_cierre_seg: Duración del bloque de cierre final, en
            segundos. No es un requisito citado en el Estado del Arte,
            sino una práctica de ingeniería para cerrar la sesión con un
            bloque de reposo limpio antes de desconectar el sensor.
        usar_vr: Si True, cada bloque trae además "ambiente_vr" con el
            nombre del skybox de Unity correspondiente (ver
            _AMBIENTE_VR_POR_BLOQUE y vr/unity_osc.py).

    Returns:
        list[dict]: 3 bloques (baseline, <tipo_estimulo>, cierre), cada
            uno con "tipo", "nombre" y "duracion_seg" (y "ambiente_vr" si
            usar_vr=True).

    Raises:
        ValueError: Si tipo_estimulo no es ninguno de los valores
            reconocidos (los 3 de TIPOS_ESTANDARIZADOS ni "preferencia").
    """
    tipos_validos = TIPOS_ESTANDARIZADOS + ["preferencia"]
    if tipo_estimulo not in tipos_validos:
        raise ValueError(
            f"tipo_estimulo '{tipo_estimulo}' no reconocido. Debe ser uno de: {tipos_validos}"
        )

    protocolo = [
        {"tipo": "silencio", "duracion_seg": duracion_baseline_seg, "nombre": "baseline"},
        {"tipo": "estimulo", "nombre": tipo_estimulo, "duracion_seg": duracion_estimulo_seg},
        {"tipo": "silencio", "duracion_seg": duracion_cierre_seg, "nombre": "cierre"},
    ]

    if usar_vr:
        ambiente_previo: Optional[str] = None
        for bloque in protocolo:
            ambiente = _AMBIENTE_VR_POR_BLOQUE.get(bloque["nombre"], ambiente_previo)
            bloque["ambiente_vr"] = ambiente
            ambiente_previo = ambiente

    return protocolo


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

    Mapeo (ver REPRODUCCIÓN DE AUDIO REAL en el docstring del módulo; el
    orden de los checks IMPORTA, ver más abajo):
        "baseline" / "reposo" / cualquier otro nombre no reconocido → None
            (se trata como silencio: no hay WAV asociado a "no hacer nada")
        contiene "solfeggio_isocronico" → audio_estimulos/solfeggio_isocronico/,
            buscando el patrón "NNNHz" dentro del propio nombre (ej.
            "solfeggio_isocronico_528Hz" -> "528Hz"). Se revisa ANTES que
            "solfeggio" a secas porque toda substring "solfeggio_isocronico"
            también contiene "solfeggio" — si se revisara al revés,
            "solfeggio_isocronico_528Hz" resolvería (mal) contra
            audio_estimulos/solfeggio/ en vez de la carpeta combinada.
        contiene "solfeggio" (y no "isocronico") → audio_estimulos/solfeggio/,
            buscando el patrón "NNNHz" dentro del propio nombre si lo trae
            (ej. "solfeggio_528Hz" -> "528Hz"), o cualquier solfeggio si no.
        contiene "binaural"   → audio_estimulos/binaurales/, buscando el
            rango que siga a "binaural_" (ej. "binaural_theta" -> "theta").
        contiene "isocronico" (y no "solfeggio") → audio_estimulos/isocronicos/,
            mismo criterio que "binaural".
        contiene "paisaje" → audio_estimulos/paisajes/ (solo hay un archivo,
            no hace falta patrón de búsqueda).
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

    if "solfeggio_isocronico" in nombre_normalizado:
        match = re.search(r"\d+Hz", nombre_bloque, re.IGNORECASE)
        patron = match.group(0) if match else ""
        return reproductor_temp._buscar_estimulo(CARPETA_ESTIMULOS / "solfeggio_isocronico", patron)

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

    if "paisaje" in nombre_normalizado:
        return reproductor_temp._buscar_estimulo(CARPETA_ESTIMULOS / "paisajes", "")

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
    palabras_clave_estimulo = ("solfeggio", "binaural", "isocronico", "paisaje", "preferencia")
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


def _hilo_observador_vr(
    protocolo: list[dict],
    estado_compartido: dict,
    unity_osc: UnityOSC,
    detener: threading.Event,
) -> None:
    """Cuerpo del hilo D (opcional, solo si usar_vr=True): le avisa a Unity cuando
    cambia el bloque en curso, EN PARALELO al audio — sin tocar
    ReproductorEstimulos ni reproducir_protocolo() para nada.

    Funciona por polling: reproducir_protocolo() (sin modificar, ver
    audio/reproductor_estimulos.py:321-325) ya actualiza
    estado_compartido["estimulo_actual"] = nombre_del_bloque justo antes de
    empezar cada bloque — este hilo solo OBSERVA ese mismo dict compartido
    cada 0.2s y, cuando el nombre cambia, busca el "ambiente_vr" de ese bloque
    en `protocolo`. No escribe nada en estado_compartido, no llama a nada de
    sounddevice, no interfiere con el hilo de audio.

    El envío a Unity se deduplica por VALOR de ambiente_vr, no por nombre de
    bloque: un descanso que hereda el mismo skybox del bloque anterior (ver
    obtener_protocolo_sesion_dia()) NO dispara un cambiar_ambiente() de
    nuevo — solo se manda cuando el skybox realmente cambia. Antes deduplicaba
    por nombre de bloque, así que un descanso heredado SÍ reenviaba el mismo
    valor (redundante pero inofensivo — Unity solo recargaba el mismo
    material); se ajustó para que la cantidad de envíos OSC coincida con la
    cantidad de transiciones visuales reales, que es lo que valida
    vr/probar_integracion.py comparando contra _AMBIENTE_VR_POR_BLOQUE.

    Args:
        protocolo: Mismo protocolo con "ambiente_vr" por bloque (ver
            obtener_protocolo_sesion_dia(usar_vr=True)).
        estado_compartido: El mismo dict que reproducir_protocolo() ya escribe.
        unity_osc: Cliente ya construido (ver ejecutar_sesion_completa()).
        detener: Se setea desde afuera cuando el bloque de estímulos terminó,
            para que este hilo pare de sondear (daemon=True lo respalda si
            igual quedara colgado por algún motivo).
    """
    mapa_ambiente = {b["nombre"]: b.get("ambiente_vr") for b in protocolo}
    ultimo_bloque = None
    ultimo_ambiente_enviado = None
    while not detener.is_set():
        bloque_actual = estado_compartido.get("estimulo_actual")
        if bloque_actual and bloque_actual != ultimo_bloque and bloque_actual in mapa_ambiente:
            ambiente = mapa_ambiente[bloque_actual]
            if ambiente is not None and ambiente != ultimo_ambiente_enviado:
                unity_osc.cambiar_ambiente(ambiente)
                ultimo_ambiente_enviado = ambiente
            ultimo_bloque = bloque_actual
        detener.wait(0.2)


def _hilo_estimulos(
    reproductor: ReproductorEstimulos,
    protocolo: list[dict],
    t0: float,
    estado_compartido: dict,
    resultado: dict,
    lock: threading.Lock,
    silencioso: bool = False,
    usar_vr: bool = False,
    unity_osc: Optional[UnityOSC] = None,
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
        usar_vr: Si True (y unity_osc no es None), lanza _hilo_observador_vr()
            en paralelo — ver ese docstring. Default False: comportamiento
            IDÉNTICO al de antes de esta integración, ni un hilo de más.
        unity_osc: Cliente ya construido por ejecutar_sesion_completa(). Se
            ignora si usar_vr=False.
    """
    detener_vr = threading.Event()
    hilo_vr: Optional[threading.Thread] = None
    if usar_vr and unity_osc is not None:
        hilo_vr = threading.Thread(
            target=_hilo_observador_vr, args=(protocolo, estado_compartido, unity_osc, detener_vr), daemon=True, name="vr"
        )
        hilo_vr.start()

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
    finally:
        # Pase lo que pase con el audio (éxito o excepción), el observador VR
        # no tiene por qué seguir sondeando — se corta acá siempre.
        detener_vr.set()
        if hilo_vr is not None:
            hilo_vr.join(timeout=1.0)


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


def _valor_o_none(fila: Any, columna: str) -> Optional[float]:
    """Extrae fila[columna] como float nativo, o None si falta o es NaN.

    Las métricas de tabla_combinada vienen de pandas/numpy (ver
    analizar_sesion.py); SQL Server/pyodbc necesita None (NULL), no NaN.
    """
    if columna not in fila:
        return None
    valor = fila[columna]
    if valor is None:
        return None
    try:
        if math.isnan(valor):
            return None
    except TypeError:
        pass
    return float(valor)


def _guardar_en_sql_server(
    participante_id: str, resultado_metricas: dict, duracion_total_real: float, usa_vr: bool = False
) -> Optional[int]:
    """Guarda una sesión ya analizada en SQL Server (sesiones + pruebas), en paralelo a los CSV.

    Ver PERSISTENCIA EN SQL SERVER en el docstring del módulo. Nunca se
    llama a esto si resultado_metricas es None (el análisis previo falló):
    el caller ya se encarga de esa validación antes de invocar esta función.

    Args:
        participante_id: ID del participante de esta sesión.
        resultado_metricas: dict devuelto por analizar_metricas_sesion()
            (trae tabla_combinada y resumen_general).
        duracion_total_real: Duración real de la sesión (segundos de pared,
            sin contar estabilización) — respaldo si resumen_general no la trae.
        usa_vr: Si la sesión corrió con Meta Quest 2 (ver usar_vr en
            ejecutar_sesion_completa()) — se guarda tal cual en la columna
            sesiones.usa_vr (ver bd_sqlserver.py), solo informativo.

    Returns:
        Optional[int]: id_sesion creado en SQL Server, o None si falló
            cualquier parte del guardado (conexión, inserción, etc. — ver
            logs de BaseDatosTesis para el detalle).
    """
    bd = BaseDatosTesis()
    if not bd.conectar():
        print("Advertencia: no se pudo conectar a SQL Server; la sesión no se guarda en base de datos.")
        return None

    try:
        bd.registrar_participante(
            participante_id,
            edad=None,
            genero=None,
            observaciones="Auto-registrado por sesion_completa.py - completar datos demográficos.",
        )

        tabla = resultado_metricas["tabla_combinada"]
        fila_baseline = tabla.loc[tabla["estimulo"] == "baseline"]
        hr_baseline = _valor_o_none(fila_baseline.iloc[0], "hr_media") if not fila_baseline.empty else None
        sdnn_baseline = _valor_o_none(fila_baseline.iloc[0], "sdnn") if not fila_baseline.empty else None
        rmssd_baseline = _valor_o_none(fila_baseline.iloc[0], "rmssd") if not fila_baseline.empty else None

        id_sesion = bd.crear_sesion(
            participante_id,
            hr_baseline,
            rmssd_baseline,
            sdnn_baseline,
            notas="Registrado automáticamente por sesion_completa.py",
            usa_vr=usa_vr,
        )
        if id_sesion is None:
            print("Advertencia: no se pudo crear la fila de sesión en SQL Server.")
            return None

        duracion_total = resultado_metricas["resumen_general"].get("duracion_total_seg")
        duracion_final = _valor_o_none({"d": duracion_total}, "d")
        bd.actualizar_duracion_sesion(id_sesion, int(duracion_final if duracion_final is not None else duracion_total_real))

        pruebas_guardadas = 0
        for _, fila in tabla.iterrows():
            info_prueba = mapear_bloque_a_prueba(fila["estimulo"])
            if info_prueba is None:
                continue  # bloques de reposo/silencio: no son "pruebas"

            metricas_dict = {
                "hr_promedio": fila.get("hr_media"),
                "hr_min": fila.get("hr_min"),
                "hr_max": fila.get("hr_max"),
                "rmssd": fila.get("rmssd"),
                "sdnn": fila.get("sdnn"),
                "pnn50": fila.get("pnn50"),
                "resp_por_min": fila.get("respiraciones_min"),
            }
            duracion_bloque = _valor_o_none(fila, "duracion_seg")

            id_prueba = bd.registrar_prueba(
                id_sesion,
                participante_id,
                info_prueba["tipo_estimulo"],
                info_prueba["frecuencia_hz"],
                metricas_dict,
                duracion_seg=int(duracion_bloque) if duracion_bloque is not None else None,
            )
            if id_prueba is not None:
                pruebas_guardadas += 1

        print(f"Sesión guardada en SQL Server: id_sesion={id_sesion}, {pruebas_guardadas} prueba(s).")
        return id_sesion
    finally:
        bd.desconectar()


def ejecutar_sesion_completa(
    participante_id: str,
    protocolo_corto: bool = True,
    usar_sensor_real: bool = False,
    mac_address: Optional[str] = None,
    silencioso_estimulos: bool = False,
    protocolo_personalizado: Optional[list[dict]] = None,
    dia: Optional[int] = None,
    tipo_estimulo_dia: Optional[str] = None,
    tiempo_estabilizacion_seg: int = 30,
    reproducir_audio_real: bool = False,
    preferencia_wav: Optional[Path] = None,
    preferencia_wav_2: Optional[Path] = None,
    dispositivo_salida_audio: Optional[int] = None,
    analizar_automaticamente: bool = True,
    guardar_en_bd: bool = True,
    usar_vr: bool = False,
    unity_ip: str = "127.0.0.1",
    unity_puerto: int = 8000,
    cancelar_espera_sentado: Optional[threading.Event] = None,
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
            Tiene prioridad sobre dia si ambos se indican.
        dia: Si se indica (1, 2, 3 o 4), usa obtener_protocolo_sesion_dia()
            (ver PROTOCOLO EXPERIMENTAL FINAL DE LA TESIS en el docstring
            del módulo): el protocolo estandarizado de UNA sesión de UN
            día (baseline 120s, un único estímulo de 300s, cierre 60s;
            480s capturados, 510s de pared con estabilización por
            defecto). Día 2 siempre reproduce preferencia_wav (requerido,
            lanza ValueError si no se indica) y Día 4 siempre reproduce
            preferencia_wav_2 (una canción DISTINTA, también requerida) —
            Días 1 y 3 usan tipo_estimulo_dia si se indica, o si no, el
            resultado de asignar_estimulos_dia1_dia3(participante_id) —
            así que llamar a esta función con dia=1 y luego, en otro día,
            con dia=3 para el MISMO participante_id da automáticamente el
            tipo complementario, sin tener que pasar nada más. Ignorado si
            se indica protocolo_personalizado.
        tipo_estimulo_dia: Override manual del tipo de estímulo para Día 1
            o Día 3 (uno de sesion_completa.TIPOS_ESTANDARIZADOS) — evita
            el sorteo automático de asignar_estimulos_dia1_dia3(). Se
            ignora si dia es None o dia in (2, 4) (esos días siempre son
            "preferencia"). Pensado para forzar un tipo específico en
            pruebas; en sesiones reales, dejar en None para que el
            sorteo determinista decida.
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
        preferencia_wav: Ruta al audio de la PRIMERA canción de preferencia
            personal del participante (Día 2). Solo se usa si
            reproducir_audio_real=True y el protocolo tiene un bloque
            cuyo nombre contiene "preferencia".
        preferencia_wav_2: Ruta al audio de la SEGUNDA canción de
            preferencia personal (Día 4) — una canción DISTINTA a
            preferencia_wav, no una repetición (ver PROTOCOLO EXPERIMENTAL
            FINAL en el docstring del módulo: Días 2 y 4 son ambos
            "preferencia" para efectos de tipo_estimulo, pero cada uno con
            su propio archivo). Solo se usa si dia == 4.
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
        guardar_en_bd: Si True (default), al terminar guarda la sesión en
            SQL Server (tablas participantes/sesiones/pruebas — ver
            PERSISTENCIA EN SQL SERVER en el docstring del módulo), en
            paralelo a los 3 archivos locales (que se guardan siempre,
            pase lo que pase con esto). Si el guardado falla (SQL Server
            apagado, etc.), se imprime una advertencia y la sesión local
            NO se pierde. Reutiliza el mismo análisis de métricas que
            analizar_automaticamente (no se corre dos veces).
        usar_vr: Si True, arma un UnityOSC y le avisa a Unity/Meta Quest 2 el
            skybox correspondiente a cada bloque, en paralelo al audio (ver
            vr/unity_osc.py y _hilo_observador_vr()) — SOLO afecta lo visual,
            el audio se sigue reproduciendo exactamente igual que con
            usar_vr=False. Solo tiene efecto real si el protocolo en uso trae
            "ambiente_vr" por bloque (ver obtener_protocolo_sesion_dia(),
            se activa automáticamente si dia es 1, 2 o 3 también);
            con protocolo_corto o protocolo_personalizado sin esa clave, no
            pasa nada (no crashea, simplemente no hay skybox que cambiar). Si
            Unity está apagado o no responde, la sesión sigue igual — nunca
            se interrumpe la captura por esto (ver PERSISTENCIA / degradación
            en el docstring del módulo).
        unity_ip: IP donde escucha Unity. Ignorado si usar_vr=False.
        unity_puerto: Puerto UDP donde Unity escucha. Ignorado si usar_vr=False.
        cancelar_espera_sentado: threading.Event opcional para cortar a mano la
            espera de INTERACCIÓN EMBEBIDA (ver más abajo) si Unity nunca
            confirma que el participante se sentó. None (default): la espera
            no tiene límite de tiempo y solo Ctrl+C la corta — pensado para
            scripts de línea de comandos sin UI (ver app_investigador.py para
            el caso con botón "Cancelar sesión").

    Returns:
        dict: participante_id, ruta_csv (Path), ruta_wav (Path o None si
            no había micrófono disponible), ruta_json_estimulos (Path),
            duracion_total_seg (float, tiempo de pared real de la sesión,
            sin contar la estabilización), resumen_estabilizacion (dict
            con hr_promedio, num_lecturas, tiempo_estabilizacion_seg),
            ruta_reporte (Path o None si analizar_automaticamente=False o
            si el análisis automático falló), id_sesion_bd (Optional[int]:
            id de la fila creada en SQL Server, o None si guardar_en_bd=False
            o si falló el guardado).

    Raises:
        RuntimeError: Si falla la captura cardíaca o la reproducción de
            estímulos (los dos hilos que SÍ son indispensables para tener
            una sesión válida; el audio es opcional).
        Exception: Si usar_sensor_real=True y no logra conectar al sensor
            Wahoo (propagada desde HiloSensorBLE.iniciar(), antes de
            lanzar ningún hilo — falla rápido y claro).
        ValueError: Si no se indica protocolo_personalizado, dia, ni
            protocolo_corto=True — ver el bloque if/elif de más abajo:
            desde la limpieza de Fase 2 ya no existe un protocolo "de
            ejemplo" implícito al que caer por default (ver ese bloque).
    """
    fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")

    # --- Protocolo de estímulos (mismo para el reproductor y, traducido, para el sensor) ---
    reproductor = ReproductorEstimulos(device_id=dispositivo_salida_audio)
    carpeta_estimulos_temp: Optional[Path] = None

    if protocolo_personalizado is not None:
        protocolo = protocolo_personalizado
    elif dia is not None:
        if dia not in (1, 2, 3, 4):
            raise ValueError(f"dia debe ser 1, 2, 3 o 4 (recibido: {dia}).")

        if dia == 2:
            if preferencia_wav is None:
                raise ValueError(
                    "dia=2 requiere preferencia_wav: es el primer día de preferencia "
                    "sonora personal del participante."
                )
            tipo_dia = "preferencia"
        elif dia == 4:
            if preferencia_wav_2 is None:
                raise ValueError(
                    "dia=4 requiere preferencia_wav_2: es el segundo día de preferencia "
                    "sonora personal del participante, con una canción DISTINTA a la del "
                    "Día 2 (ver PROTOCOLO EXPERIMENTAL FINAL en el docstring del módulo)."
                )
            tipo_dia = "preferencia"
        elif tipo_estimulo_dia is not None:
            tipo_dia = tipo_estimulo_dia
        else:
            tipo_dia1, tipo_dia3 = asignar_estimulos_dia1_dia3(participante_id)
            tipo_dia = tipo_dia1 if dia == 1 else tipo_dia3
            print(
                f"Día {dia} de {participante_id}: tipo de estímulo sorteado -> '{tipo_dia}' "
                f"(sorteo completo para este participante: día1='{tipo_dia1}', día3='{tipo_dia3}')"
            )

        protocolo = obtener_protocolo_sesion_dia(tipo_dia, usar_vr=usar_vr)
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
        # Limpieza de Fase 2: antes esto caía en
        # construir_protocolo_ejemplo(CARPETA_ESTIMULOS) — el protocolo "de
        # ejemplo" viejo de 4 estímulos, leyendo contra las carpetas reales
        # audio_estimulos/solfeggio/ e /isocronicos/, que ya no existen (se
        # borraron: no forman parte del protocolo oficial de 3 días, ver
        # TIPOS_ESTANDARIZADOS). Fallar rápido y explícito acá es mejor que
        # dejar que _buscar_estimulo() tire un FileNotFoundError confuso
        # más abajo, apuntando a una carpeta que ya no existe.
        raise ValueError(
            "Debés indicar protocolo_personalizado=, dia=1/2/3/4, o protocolo_corto=True. "
            "Ya no existe un protocolo 'de ejemplo' implícito (ver PROTOCOLO POR DÍA en "
            "el docstring del módulo)."
        )

    if reproducir_audio_real:
        # Día 4 usa la SEGUNDA canción (preferencia_wav_2), no la primera — ver
        # PROTOCOLO EXPERIMENTAL FINAL en el docstring del módulo.
        wav_preferencia_de_este_dia = preferencia_wav_2 if dia == 4 else preferencia_wav
        protocolo = _resolver_audio_real(protocolo, wav_preferencia_de_este_dia)

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

    # --- VR (Meta Quest 2) — ver vr/unity_osc.py y INTERACCIÓN EMBEBIDA en el docstring
    # del módulo. unity_osc queda en None si usar_vr=False: nada de lo que sigue en esta
    # función cambia de comportamiento en ese caso (default). Va ANTES de la
    # estabilización a propósito: si el participante todavía está caminando, hay que
    # esperar a que se siente antes de "descartar lecturas de estabilización", que
    # exige que ya esté quieto (ver PERÍODO DE ESTABILIZACIÓN arriba). ---
    unity_osc: Optional[UnityOSC] = None
    if usar_vr:
        unity_osc = UnityOSC(ip=unity_ip, puerto=unity_puerto)
        if not unity_osc.iniciar_sesion(participante_id):
            print(
                f"Advertencia: no se pudo avisarle a Unity que arrancó la sesión de "
                f"{participante_id} (¿está la escena corriendo?) — la sesión continúa igual, "
                "sin VR (tampoco se espera confirmación de 'sentado': no tendría sentido "
                "esperar una señal que nunca va a llegar)."
            )
        else:
            print("Esperando a que el participante se siente en la silla (VR)...")
            confirmado = unity_osc.esperar_confirmacion_sentado(cancelar=cancelar_espera_sentado)
            if not confirmado:
                # El sensor real ya puede estar conectado en este punto (BLE se conecta
                # ANTES que esta espera, ver más arriba) — hay que soltarlo acá, porque
                # una excepción salta directo al "except" de quien llama sin pasar por
                # la desconexión normal de más abajo (esa solo corre si los 3 hilos
                # llegaron a arrancar y terminar).
                if hilo_ble is not None:
                    hilo_ble.detener()
                raise RuntimeError(
                    "Sesión cancelada: no se confirmó que el participante se sentó "
                    "(cancelada a mano, o Unity dejó de responder)."
                )

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
            args=(reproductor, protocolo, t0, estado_compartido, resultado, lock, silencioso_efectivo, usar_vr, unity_osc),
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

    if unity_osc is not None:
        unity_osc.terminar_sesion()

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

    # El análisis (y el guardado en SQL Server) corren DESPUÉS de que los 3 archivos ya
    # están guardados en disco — si cualquiera de los dos falla, la sesión capturada no
    # se pierde, solo no queda su reporte y/o su fila en la base de datos.
    resultado_metricas = None
    if analizar_automaticamente or guardar_en_bd:
        print("\n=== Calculando métricas post-sesión ===")
        try:
            resultado_metricas = analizar_metricas_sesion(
                participante_id=participante_id,
                ruta_csv=resultado["ruta_csv"],
                ruta_wav=ruta_wav,
                ruta_json_eventos=ruta_json_estimulos,
                generar_grafica=analizar_automaticamente,
            )
        except Exception as error:
            print(
                f"Advertencia: el análisis de métricas post-sesión falló ({error}); "
                "los 3 archivos de la sesión sí se guardaron correctamente."
            )

    ruta_reporte = None
    if analizar_automaticamente and resultado_metricas is not None:
        print("\n=== Generando reporte consolidado ===")
        try:
            ruta_reporte = _generar_reporte_md(
                participante_id=resultado_metricas["participante_id"],
                resumen_general=resultado_metricas["resumen_general"],
                tabla_combinada=resultado_metricas["tabla_combinada"],
                resultado_recomendacion=resultado_metricas["resultado_recomendacion"],
                ruta_grafica_sesion=resultado_metricas["ruta_grafica_sesion"],
                ruta_csv=resultado_metricas["ruta_csv"],
                ruta_wav=resultado_metricas["ruta_wav"],
                ruta_json_eventos=resultado_metricas["ruta_json_eventos"],
                ruta_tabla_unificada=resultado_metricas["ruta_tabla_unificada"],
            )
            print(f"=== Reporte generado: {ruta_reporte} ===")
        except Exception as error:
            print(f"Advertencia: no se pudo generar el reporte Markdown ({error}).")

    id_sesion_bd = None
    if guardar_en_bd and resultado_metricas is not None:
        print("\n=== Guardando sesión en SQL Server ===")
        try:
            id_sesion_bd = _guardar_en_sql_server(participante_id, resultado_metricas, duracion_total_real, usa_vr=usar_vr)
        except Exception as error:
            print(
                f"Advertencia: no se pudo guardar en SQL Server ({error}); "
                "los archivos locales sí se guardaron correctamente."
            )

    return {
        "participante_id": participante_id,
        "ruta_csv": resultado["ruta_csv"],
        "ruta_wav": ruta_wav,
        "ruta_json_estimulos": ruta_json_estimulos,
        "duracion_total_seg": round(duracion_total_real, 2),
        "resumen_estabilizacion": resumen_estabilizacion,
        "ruta_reporte": ruta_reporte,
        "id_sesion_bd": id_sesion_bd,
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
    print(f"Reporte:        {resultado['ruta_reporte']}")
    print(f"id_sesion (BD): {resultado['id_sesion_bd']}")
