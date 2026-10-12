"""Panel de escritorio del investigador — sistema adaptativo de frecuencias terapéuticas.

Interfaz Flet (0.86.5) para que Kevin corra las sesiones experimentales sin
tocar la consola: registrar participantes, correr una sesión guiada
(estímulo → cuestionario → siguiente estímulo), y revisar/analizar/exportar
los datos ya guardados en SQL Server.

5 vistas, navegación por NavigationRail (sidebar):
    0. Inicio        — dashboard con KPIs desde SQL Server.
    1. Nueva sesión   — registro de participante + intake + verificación de hardware.
    2. Sesión en vivo — monitor de la captura real/simulada (timer, HR, estímulo actual).
    3. Cuestionario   — Likert de relajación/confort + preferencia, uno por cada
                        estímulo, DESPUÉS de que termina la sesión completa.
    4. Análisis       — tabs internos: resumen, comparación, recomendación, SQL, exportar.

INTEGRACIÓN CON BASE DE DATOS:
Usa exclusivamente C:\\Tesis_Kevin\\python\\database\\bd_sqlserver.py
(BaseDatosTesis) — esta app no abre ninguna conexión propia a SQL Server ni
conoce el esquema de las tablas más allá de lo que esa clase ya expone.

¿POR QUÉ ft.Tabs NO SE USA PARA LOS TABS INTERNOS DE ANÁLISIS?
En Flet 0.86.5, ft.Tabs cambió de forma: ft.Tab ya no tiene un parámetro
"content" (solo trae label/icon), y ft.Tabs tampoco tiene un parámetro
"tabs" — el control se reorganizó around un modelo más parecido al
TabController de Flutter, sin una forma simple y bien documentada en esta
versión de asociar contenido a cada pestaña. En vez de arriesgar una
integración a ciegas con una API que cambió de raíz, los "tabs" de la
vista Análisis se implementan a mano: una fila de botones que resaltan el
activo y reconstruyen el área de contenido — mismo resultado visual,
usando solo controles cuya API se verificó contra esta versión instalada.

CAPTURA REAL (Vista 2) — reutiliza sesion_completa.py, no lo duplica ni lo modifica:
_hilo_orquestador() importa y usa DIRECTO las mismas piezas que
ejecutar_sesion_completa() usa internamente: CapturaSesion, SensorWahoo/
HiloSensorBLE, CapturaAudio, ReproductorEstimulos, obtener_protocolo_sesion_dia(),
_resolver_audio_real(), _ejecutar_estabilizacion(), y los hilos módulo-nivel
_hilo_sensor/_hilo_estimulos/_hilo_audio — exactamente la misma lógica de
captura ya validada con hardware real en las sesiones piloto P01-P12.

PROTOCOLO POR DÍA (no 4 estímulos en una sola sesión): a partir del rediseño
pedido por el tutor, cada sesión real corre UN solo tipo de estímulo —
baseline -> <tipo> -> cierre (ver obtener_protocolo_sesion_dia() y
TIPOS_ESTANDARIZADOS en sesion_completa.py) — y el mismo participante vuelve
en 5 días separados (24-48h entre cada uno): 2 días de sonido terapéutico
repetido (Días 1 y 3, el MISMO tipo sorteado una sola vez) + 2 días de
preferencia musical repetida (Días 2 y 4, la MISMA canción) + 1 día
adaptativo (Día 5, repite la condición que mejor resultó) — ver el porqué
de repetir el mismo estímulo en comparar_grupos_terapeutica_vs_preferencia()
más abajo. "Nueva sesión" (Vista 1) pide al investigador elegir a mano el
Día (1-5) de la sesión que va a correr: Días 2 y 4 siempre son preferencia
sonora personal (ambos usan campo_preferencia_wav, la misma ruta); Días 1 y
3 usan el sorteo determinístico de asignar_estimulos_dia1_dia3() (mismo
participante_id -> mismo resultado, sin necesidad de persistir qué le
tocó); Día 5 consulta la BD y decide automáticamente (ver
decidir_estimulo_dia5 en sesion_completa.py) — esa decisión NUNCA se
mezcla con el contraste estadístico de H1/H0 (ver DIAS_CONTRASTE_H1H0 en
analisis_intrasujeto.py). Por eso self.bloques_estimulo_sesion (armado en
_al_registrar_participante) tiene UN solo elemento, no varios de
_METADATOS_TIPO_ESTIMULO — ver ese atributo para el cuestionario post-hoc.

RESULTADO CENTRAL DE LA TESIS (H1/H0, Anexo 5 página 19): la hipótesis NO
compara las 4 sesiones individualmente entre sí — compara exactamente 2
GRUPOS pooleados: "frecuencias terapéuticas comunes" (Días 1+3 promediados)
vs. "sonidos de preferencia personal" (Días 2+4 promediados). El Día 5
(adaptativa) queda SIEMPRE fuera de este contraste — repite a propósito la
condición ganadora, así que mezclarlo acá sesgaría el resultado a su favor
(ver DIAS_CONTRASTE_H1H0 en analisis_intrasujeto.py). Por eso los 2 días de
preferencia existen (para tener con qué promediar ese grupo, igual que los
2 días terapéuticos) — NO para comparar una canción de preferencia contra
otra, ni un tipo terapéutico contra otro (ahora repiten el mismo estímulo
dos veces cada uno, no dos estímulos distintos). Ver
Recomendador.comparar_grupos_terapeutica_vs_preferencia() y la pestaña
Recomendación (_tab_recomendacion / _construir_tarjeta_comparacion_grupos),
que muestra este resultado de 2 grupos como PRIMARIO; el ranking sesión por
sesión (calcular_score_relajacion()) queda como detalle SECUNDARIO.

¿Por qué no se llama directo a ejecutar_sesion_completa() (una sola línea)?
Porque esa función es 100% bloqueante y no expone hacia afuera ni
estado_compartido ni el objeto sensor mientras corre — sin eso, esta UI no
tendría de dónde leer HR en vivo ni qué bloque está sonando ahora mismo.
Por eso _hilo_orquestador() re-arma el mismo lanzamiento de 3 hilos con t0
compartido (mismo patrón, línea por línea equivalente a
ejecutar_sesion_completa()), pero guardando sensor/estado_compartido como
atributos de self para que un segundo bucle (en el mismo hilo orquestador)
pueda hacer polling cada 1s y refrescar la UI vía page.update().

¿Por qué NO hay botones Pausar/Saltar en modo real? Los 3 hilos (sensor,
audio, estímulos) están sincronizados por un único t0 compartido — pausar
uno sin pausar los otros dos rompería esa sincronización y corrompería los
timestamps del CSV/WAV/JSON resultantes. sesion_completa.py tampoco soporta
pausar a mitad de una sesión real; esta UI no inventa una capacidad que el
sistema real no tiene.

¿Por qué el Cuestionario (Vista 3) es POST-HOC (después de toda la sesión)
y no intercalado entre estímulos? Por la misma razón: nada en
sesion_completa.py pausa la captura a mitad de camino para esperar una
respuesta del investigador. La sesión de UN día (baseline -> estímulo ->
cierre, protocolo real de obtener_protocolo_sesion_dia()) corre de punta a
punta sin interrupciones; al terminar, se analiza con
analizar_metricas_sesion() (mismo pipeline que el reporte .md/PDF) y ahí sí
se muestra el único cuestionario de ese día (binaural_theta,
solfeggio_isocronico_528Hz, paisaje_biofilico o preferencia, según el día
— ver self.bloques_estimulo_sesion) — ver mapear_bloque_a_prueba() en
bd_sqlserver.py para cómo se traduce cada nombre de bloque a tipo_estimulo/
frecuencia_hz.

RESPIRACIÓN EN VIVO: no existe. detectar_respiraciones.py analiza el WAV
completo DESPUÉS de grabarlo, no en streaming — no hay forma de contar
respiraciones en tiempo real sin reescribir ese módulo. La Vista 2 muestra
"se calcula al finalizar" en vez de inventar un número; el valor real
aparece recién en el Cuestionario/Análisis, calculado por
analizar_metricas_sesion() sobre el WAV ya completo.

REPORTE PDF DE PARTICIPANTE (Vista 4, tab Exportar):
Se genera con reportlab (SimpleDocTemplate + flowables Table/Paragraph/Image)
directo desde SQL Server — no depende de los CSV de datos/sesiones/ ni de
analizar_sesion_completa.py, así que también sirve para participantes
capturados solo por esta app (sin CSV asociado). Los gráficos de barras se
renderizan con matplotlib (backend "Agg", sin ventana) a un PNG en memoria
(io.BytesIO) que reportlab embebe como flowable Image — mismo patrón que ya
usa el resto del proyecto para gráficas (ver analizar_sesion.py), en vez de
pelear con el motor de gráficos propio de reportlab.

Logo ESPE: se busca en RUTA_LOGO_ESPE (python/interfaz/assets/logo_espe.png).
Ese archivo NO viene incluido — nadie generó ni descargó un logo institucional
por código. Si no existe, el reporte se genera igual, solo que sin logo (con
una advertencia en el log) — nunca falla por esto.
"""

import asyncio
import logging
import math
import sys
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import flet as ft
import flet_charts as fc

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Tesis_Kevin\python")
sys.path.insert(0, r"C:\Tesis_Kevin\python\database")
sys.path.insert(0, r"C:\Tesis_Kevin\python\analisis")
sys.path.insert(0, r"C:\Tesis_Kevin\python\sensor")

from escanear_ble import escanear_dispositivos  # noqa: E402
from bd_sqlserver import BaseDatosTesis, mapear_bloque_a_prueba  # noqa: E402
from analizar_sesion_completa import analizar_metricas_sesion  # noqa: E402
from analizar_sesion import CARPETA_GRAFICAS  # noqa: E402
from sesion_completa import (  # noqa: E402
    SimuladorCardiaco,
    SensorWahoo,
    HiloSensorBLE,
    CapturaSesion,
    CapturaAudio,
    ReproductorEstimulos,
    TIPOS_ESTANDARIZADOS,
    asignar_estimulos_dia1_dia3,
    decidir_estimulo_dia5,
    obtener_protocolo_sesion_dia,
    _resolver_audio_real,
    _calcular_duracion_total_protocolo,
    _ejecutar_estabilizacion,
    _hilo_sensor,
    _hilo_estimulos,
    _hilo_audio,
    CARPETA_SESIONES,
)
from recomendador import Recomendador  # noqa: E402
from vr.unity_osc import UnityOSC  # noqa: E402
from design_system import Colors, Motion, Radius, Shadows, Spacing, Typography, gradiente  # noqa: E402
from componentes import (  # noqa: E402
    BotonAccionPrincipal,
    EmptyState,
    FormularioParticipante,
    GlassCard,
    GradientButton,
    IconCircle,
    IndicadorHardware,
    KPICard,
    MetricBadge,
    SectionHeader,
    SelectorLikert,
    SnackBarError,
    SnackBarExito,
    StatusPill,
    Timeline,
)

logger = logging.getLogger(__name__)

CARPETA_EXPORTS = Path(r"C:\Tesis_Kevin\resultados\exportados")
CARPETA_BACKUPS = Path(r"C:\Tesis_Kevin\datos\backups")
RUTA_LOGO_ESPE = Path(__file__).parent / "assets" / "logo_espe.png"

# Duraciones usadas por ESTA app — decisión explícita, mitad y mitad:
#   - DURACION_ESTIMULO_SEG SÍ sigue el Estado del Arte al pie de la letra: 300s
#     (5 min) es el mínimo que exige Task Force ESC/NASPE 1996 para RMSSD/SDNN
#     confiables, y la duración que Jin et al. (2026) y Liu & Li (2026) validaron
#     como óptima de inmersión (ver mismo rationale en generador_tonos.py, donde
#     los WAV ya se generan a 300s). Para que una sesión real cuente como dato de
#     tesis, el estímulo tiene que durar esto, no menos.
#   - DURACION_BASELINE_SEG y DURACION_CIERRE_SEG se dejan cortos (15s) A PROPÓSITO
#     (a pedido explícito del usuario) en vez de los 120s que el Task Force
#     recomienda para un baseline con margen de confiabilidad completo — el
#     mismo trade-off de SDNN de baseline ya documentado antes, asumido a
#     conciencia para no alargar cada sesión con silencio.
# Ya no hay bloques "descanso": el protocolo por día es baseline -> UN estímulo ->
# cierre (ver obtener_protocolo_sesion_dia()), nunca los 4 tipos seguidos en la
# misma sesión.
DURACION_BASELINE_SEG = 15
DURACION_ESTIMULO_SEG = 300
DURACION_CIERRE_SEG = 15

# MAC del Wahoo que la sesión real va a intentar conectar (ver
# _al_registrar_participante(): sensor = SensorWahoo(), sin override de
# mac_address) — se lee del propio default de SensorWahoo en vez de duplicar el
# literal acá, para que el chequeo de hardware (ver _verificar_wahoo_ble) nunca
# pueda desincronizarse silenciosamente de la MAC que la sesión usa de verdad.
MAC_WAHOO_DEFAULT = SensorWahoo().mac_address


async def _escanear_mac_wahoo(mac: str, timeout_seg: float = 12.0) -> bool:
    """Escaneo BLE corto (ver sensor/escanear_ble.py): True si `mac` aparece entre
    los anuncios BLE recibidos durante timeout_seg segundos — confirma que el
    sensor Wahoo está prendido y cerca, con el mismo criterio de "chequeo real,
    no cosmético" que UnityOSC.ping() ya usa para el Meta Quest 2 (ver
    _al_cambiar_switch_vr).

    timeout_seg=12.0 por defecto — valor encontrado probando en vivo con el
    Wahoo TRACKR real de este proyecto: 4s (el default original) NUNCA lo
    detectó, 8s lo detectó solo 1 de 3 intentos, 12s lo detectó 3 de 3. El
    TRACKR anuncia en un intervalo bastante largo (ahorro de batería de un
    sensor de pecho) — 12s no es "instantáneo" para un chequeo de switch, pero
    un falso negativo acá bloquearía al investigador de arrancar una sesión
    real con el sensor puesto y funcionando, que es peor que esperar 12s.
    """
    dispositivos = await escanear_dispositivos(timeout_seg=timeout_seg)
    return any(dispositivo.address.upper() == mac.upper() for dispositivo in dispositivos)


# Metadatos (título/ícono) de CADA tipo de estímulo posible del protocolo por día
# (ver TIPOS_ESTANDARIZADOS en sesion_completa.py) — lookup, NO "los bloques de
# esta sesión": una sesión real ahora corre uno solo de estos 4 (el que le tocó a
# ese participante ese día, ver asignar_estimulos_dia1_dia3()). El bloque real de
# la sesión en curso vive en self.bloques_estimulo_sesion (un solo elemento),
# armado en _al_registrar_participante().
_METADATOS_TIPO_ESTIMULO = {
    "binaural_theta": {"titulo": "Binaural Theta", "icono": "🎧"},
    "solfeggio_isocronico_528Hz": {"titulo": "Solfeggio + Isocrónico 528Hz", "icono": "🎵"},
    "paisaje_biofilico": {"titulo": "Paisaje biofílico", "icono": "🌿"},
    "preferencia": {"titulo": "Preferencia personal", "icono": "❤️"},
}

# Etiquetas legibles para los 5 bloques posibles del protocolo (obtener_protocolo_sesion_dia()
# en sesion_completa.py: baseline, UN estímulo de los 4 de _METADATOS_TIPO_ESTIMULO, cierre)
# — usado por la barra segmentada y el "Siguiente: ..." de la Vista en vivo.
_ETIQUETAS_BLOQUE = {
    "baseline": "Baseline (reposo)",
    "cierre": "Cierre",
    **{nombre: meta["titulo"] for nombre, meta in _METADATOS_TIPO_ESTIMULO.items()},
}

# tipo_estimulo tal como se guarda en la tabla "pruebas" (ver _TIPOS_ESTIMULO en
# bd_sqlserver.py: "solfeggio_isocronico", "paisaje", "binaural", "preferencia" — el
# nombre de bloque real ya resuelto por mapear_bloque_a_prueba(), sin el sufijo
# "_theta"/"_528Hz"/"_biofilico") — un color fijo por tipo en vez de un color por
# índice de fila, para que cada tipo se muestre siempre con el mismo color donde
# se muestre (ver _tab_comparacion_estimulos).
_COLOR_POR_TIPO_ESTIMULO = {
    "solfeggio_isocronico": Colors.PRIMARY,
    "binaural": Colors.SECONDARY,
    "paisaje": Colors.ACCENT,
    "preferencia": Colors.SUCCESS,
}


def _zona_hr(hr: float) -> tuple[str, str]:
    """Clasifica un HR puntual en una zona con etiqueta+color, para el chip de la Vista en
    vivo (MEJORA 7) — deliberadamente separado de AppInvestigador._color_por_hr(), que usa
    otros límites (55/60/90/100) para colorear el número grande; este chip usa los límites
    que se pidieron explícitamente para la "zona" (50/60/100/140), un concepto distinto.

    Returns:
        tuple[str, str]: (etiqueta, color) — color es uno de Colors.SUCCESS/WARNING/DANGER.
    """
    if hr < 50 or hr > 140:
        return "ZONA CRÍTICA", Colors.DANGER
    if hr < 60:
        return "ZONA BAJA", Colors.WARNING
    if hr > 100:
        return "ZONA ALTA", Colors.WARNING
    return "ZONA NORMAL", Colors.SUCCESS


def _calidad_senal(segundos_desde_ultimo_hr: float) -> tuple[int, str, str]:
    """Clasifica la calidad de señal BLE según hace cuánto cambió el último HR recibido
    (MEJORA 9) — ver _actualizar_controles_en_vivo_real() para cómo se mide ese tiempo sin
    tocar SensorWahoo (no expone un timestamp propio de "última notificación").

    Returns:
        tuple[int, str, str]: (barras de 1 a 4, color, etiqueta).
    """
    if segundos_desde_ultimo_hr < 2:
        return 4, Colors.SUCCESS, "Excelente"
    if segundos_desde_ultimo_hr < 5:
        return 3, Colors.SUCCESS, "Buena"
    if segundos_desde_ultimo_hr < 10:
        return 2, Colors.WARNING, "Débil"
    return 1, Colors.DANGER, "Posible pérdida"

_GENERO_LEGIBLE = {"M": "Masculino", "F": "Femenino", "O": "Otro", "N": "Prefiere no decir"}

_DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _fecha_larga_es(fecha: datetime) -> str:
    """Formatea una fecha como "Jueves, 20 de agosto de 2026", sin depender del
    locale del sistema (no siempre hay uno en español instalado en Windows)."""
    return f"{_DIAS_ES[fecha.weekday()]}, {fecha.day} de {_MESES_ES[fecha.month - 1]} de {fecha.year}"


def _tiempo_relativo_es(momento: datetime, ahora: Optional[datetime] = None) -> str:
    """Formatea un datetime pasado como "Hace X horas"/"Hace X días"/"Hace un momento"."""
    ahora = ahora or datetime.now()
    segundos = max(0, (ahora - momento).total_seconds())
    if segundos < 60:
        return "Hace un momento"
    minutos = segundos / 60
    if minutos < 60:
        return f"Hace {int(minutos)} min"
    horas = minutos / 60
    if horas < 24:
        return f"Hace {int(horas)} horas"
    return f"Hace {int(horas / 24)} días"

# Destinos del sidebar. Se dibujan a mano (Container + Row, no ft.NavigationRail) por la
# misma razón que los tabs de Análisis (ver docstring del módulo): en Flet 0.86.5 el theming
# automático de NavigationRail no expone un color de icono/label propio para tema oscuro sin
# adivinar cómo ColorScheme deriva esos tonos — un sidebar hecho a mano con los colores de
# Colors.TEXT_ON_DARK/TEXT_ON_DARK_MUTED explícitos es la opción verificable, no la que "debería"
# funcionar.
_DESTINOS_SIDEBAR = [
    {"icono": ft.Icons.HOME_OUTLINED, "icono_activo": ft.Icons.HOME, "label": "Inicio"},
    {"icono": ft.Icons.PERSON_ADD_ALT_OUTLINED, "icono_activo": ft.Icons.PERSON_ADD, "label": "Nueva sesión"},
    {"icono": ft.Icons.MONITOR_HEART_OUTLINED, "icono_activo": ft.Icons.MONITOR_HEART, "label": "En vivo"},
    {"icono": ft.Icons.ASSIGNMENT_OUTLINED, "icono_activo": ft.Icons.ASSIGNMENT, "label": "Cuestionario"},
    {"icono": ft.Icons.INSIGHTS_OUTLINED, "icono_activo": ft.Icons.INSIGHTS, "label": "Análisis"},
]


class AppInvestigador:
    """Controlador principal de la app: estado de sesión + construcción de las 5 vistas.

    Attributes:
        page (ft.Page): Página raíz de Flet.
        bd (Optional[BaseDatosTesis]): Conexión a SQL Server, o None si no
            se pudo conectar (la app sigue funcionando en modo degradado,
            mostrando el problema en vez de crashear).
    """

    def __init__(self, page: ft.Page) -> None:
        """Inicializa la app: conecta a la base, arma la ventana y muestra la Vista 1.

        Args:
            page: Página raíz que Flet crea para esta sesión.
        """
        self.page = page
        self.bd: Optional[BaseDatosTesis] = None

        # --- Estado de la sesión experimental activa (None = no hay ninguna en curso) ---
        self.participante_actual: Optional[dict] = None
        self.usar_sensor_real: bool = False
        self.reproducir_audio_real: bool = True
        self.ruta_preferencia_wav: Optional[str] = None
        # VR (Meta Quest 2, solo visual — ver vr/unity_osc.py). _vr_ok arranca en True
        # porque con el switch apagado (default) no bloquea nada; se pone en False recién
        # cuando el switch se enciende y el ping todavía no confirmó que Unity responde.
        self.usar_vr: bool = False
        self._vr_ok: bool = True
        # Sensor Wahoo (BLE real). _wahoo_ok arranca en True por la misma razón que
        # _vr_ok: con el switch apagado (default) no bloquea nada; se pone en False
        # recién cuando el switch se enciende y el escaneo BLE no lo detectó (ver
        # _verificar_wahoo_ble, _al_cambiar_switch_sensor).
        self._wahoo_ok: bool = True

        # --- Estado de la captura en curso (ver _hilo_orquestador) ---
        self.hilo_orquestador: Optional[threading.Thread] = None
        self.sensor_captura = None  # SimuladorCardiaco o SensorWahoo — peek de HR en vivo
        self.estado_compartido_captura: dict = {"estimulo_actual": ""}
        self.t0_captura: Optional[float] = None
        self.duracion_total_protocolo: float = 0.0
        self.duracion_total_real_sesion: float = 0.0
        self.hr_historial: list[float] = []
        self.error_captura: Optional[str] = None
        self.captura_terminada: bool = False
        # --- Espera de interacción embebida (usar_vr=True, ver INTERACCIÓN EMBEBIDA en
        # el docstring de sesion_completa.py): el participante camina libremente en el
        # entorno VR hasta que se sienta; recién ahí arranca el t0 real. Mientras
        # esperando_sentado es True, _vista_sesion_en_vivo() muestra un panel distinto
        # con un botón "Cancelar sesión" que setea este Event. ---
        self.esperando_sentado: bool = False
        self._evento_cancelar_espera_sentado: threading.Event = threading.Event()
        # Bloques (nombre/duracion_seg) del protocolo de ESTA sesión, calculado en
        # _al_registrar_participante() ANTES de navegar a la Vista en vivo — así la
        # barra segmentada y el "Siguiente: ..." ya tienen datos reales en el primer
        # render, sin esperar a que _hilo_orquestador() arranque (ese hilo recalcula
        # su propia copia por separado; llamar dos veces a obtener_protocolo_sesion_dia()
        # es seguro porque es una función pura, sin efectos secundarios).
        self.protocolo_activo: list[dict] = []
        # Día (1/2/3) y tipo de estímulo YA sorteado/asignado para la sesión en curso
        # (ver PROTOCOLO POR DÍA en el docstring del módulo y _al_registrar_participante) —
        # bloques_estimulo_sesion tiene un único elemento: el cuestionario post-hoc
        # (Vista 3) itera sobre esto, no sobre _METADATOS_TIPO_ESTIMULO completo.
        self.dia_sesion: int = 1
        self.tipo_estimulo_sesion: Optional[str] = None
        self.bloques_estimulo_sesion: list[dict] = []
        # --- Estado SOLO de UI para las mejoras visuales de la Vista en vivo — nunca
        # se escribe nada de esto en el sensor/hilos, solo se lee (peek) igual que
        # hr_historial/_peek_hr ya hacían. Ver _actualizar_controles_en_vivo_real(). ---
        self._hr_baseline_muestras: list[float] = []
        self._hr_baseline_vivo: Optional[float] = None
        self._ultimo_hr_valor: Optional[float] = None
        self._ultimo_hr_cambio_ts: Optional[float] = None

        # --- Métricas ya analizadas (ver analizar_metricas_sesion()) + cuestionario post-hoc ---
        self.resultado_metricas_sesion: Optional[dict] = None
        self.respuestas_cuestionario: dict[str, dict] = {}
        self.indice_pregunta_actual: int = 0

        # --- Estado de formularios (se recrean en cada _navegar a esas vistas) ---
        self.formulario: Optional[FormularioParticipante] = None
        self.likert_relajacion: Optional[SelectorLikert] = None
        self.likert_confort: Optional[SelectorLikert] = None
        self.chip_preferencia_seleccionado: Optional[str] = None
        self.chips_preferencia: dict[str, ft.Chip] = {}
        self._ultimo_resultado_sql: list[dict] = []
        self._tab_analisis: str = "resumen"
        self._indice_activo: int = 0

        self._conectar_bd()
        self._configurar_pagina()
        self._construir_layout()
        self._navegar(0)

    # =================================================================
    # Conexión e infraestructura
    # =================================================================

    def _conectar_bd(self) -> None:
        """Intenta conectar a SQL Server; si falla, la app sigue en modo degradado.

        No lanza excepción: self.bd queda en None y cada vista que necesite
        datos de la base lo detecta y muestra un mensaje explicativo en vez
        de romper toda la app.
        """
        try:
            candidata = BaseDatosTesis()
            if candidata.conectar():
                self.bd = candidata
            else:
                self.bd = None
                logger.error("No se pudo conectar a SQL Server (ver .env).")
        except Exception as error:
            logger.error(f"Error inicializando BaseDatosTesis: {error}")
            self.bd = None
        # Solo para mostrar "verificado a las HH:MM" en la KPICard de Estado del sistema
        # (Vista Inicio) — no afecta la conexión en sí, es puramente informativo.
        self._hora_conexion_bd = datetime.now()

    def _configurar_pagina(self) -> None:
        """Aplica tema Material 3 + tipografía Inter, tamaño de ventana y modo escritorio."""
        page = self.page
        page.title = "Sistema Adaptativo — Panel del Investigador"
        # Google Fonts (única dependencia externa nueva permitida explícitamente) — el CSS
        # de Inter se referencia por URL, no hay paquete Python nuevo que instalar.
        page.fonts = {
            "Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
        }
        page.theme = ft.Theme(
            color_scheme_seed=Colors.PRIMARY, use_material3=True, font_family=Typography.FONT_FAMILY
        )
        page.theme_mode = ft.ThemeMode.LIGHT
        page.bgcolor = Colors.BG_MAIN
        page.padding = 0
        page.window.width = 1440
        page.window.height = 920
        page.window.min_width = 1400
        page.window.min_height = 900
        page.window.resizable = True
        # Diagnóstico temporal: page.update() no lanza en Python si el CLIENTE (Flutter)
        # rechaza algún control — este hook es la única forma de ver ese error, porque
        # normalmente ni aparece en esta consola. Se saca una vez encontrado el bug de
        # la Vista en vivo en blanco.
        page.on_error = lambda e: logger.error(f"[CLIENTE FLET] {e.data}")

        if self.bd is None:
            self.page.show_dialog(
                ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Sin conexión a SQL Server"),
                    content=ft.Text(
                        "No se pudo conectar a la base de datos. Revisa que SQL Server esté "
                        "corriendo y que C:\\Tesis_Kevin\\.env tenga las credenciales correctas. "
                        "Puedes seguir explorando la app, pero ninguna vista con datos reales "
                        "va a funcionar hasta que se resuelva la conexión."
                    ),
                    actions=[ft.TextButton(content=ft.Text("Entendido"), on_click=lambda e: self.page.pop_dialog())],
                )
            )

    def _construir_layout(self) -> None:
        """Arma el layout fijo: sidebar oscuro a la izquierda + área de contenido a la derecha."""
        self.contenedor_sidebar = ft.Container(
            width=248, bgcolor=Colors.BG_SIDEBAR, content=self._construir_sidebar()
        )
        self.area_contenido = ft.Container(
            expand=True,
            padding=ft.padding.Padding.all(Spacing.XL),
            bgcolor=Colors.BG_MAIN,
            content=ft.Text("Cargando..."),
        )

        self.page.add(
            ft.Row(
                expand=True,
                spacing=0,
                controls=[self.contenedor_sidebar, self.area_contenido],
            )
        )

    def _construir_sidebar(self) -> ft.Control:
        """Reconstruye el sidebar completo (logo, ítems de navegación, estado de BD y avatar).

        Se reconstruye entero en cada _navegar() en vez de mutar ítems existentes — mismo
        patrón que ya usa el resto de la app para "tabs" hechos a mano (ver Vista Análisis):
        con solo 5 ítems el costo es insignificante y evita tener que llevar estado de
        estilo duplicado por fuera de _DESTINOS_SIDEBAR.

        Returns:
            ft.Control: Columna lista para meter en self.contenedor_sidebar.content.
        """
        bd_conectada = self.bd is not None
        items_nav = [self._item_sidebar(i, destino) for i, destino in enumerate(_DESTINOS_SIDEBAR)]

        return ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    padding=ft.padding.Padding.symmetric(vertical=Spacing.XL, horizontal=Spacing.LG),
                    content=ft.Row(
                        spacing=Spacing.SM,
                        controls=[
                            IconCircle(
                                ft.Icons.SPA,
                                ft.Colors.with_opacity(0.15, Colors.TEXT_ON_DARK),
                                Colors.TEXT_ON_DARK,
                                tamaño=36,
                            ),
                            ft.Column(
                                spacing=0,
                                tight=True,
                                controls=[
                                    ft.Text("Panel del", size=11, color=Colors.TEXT_ON_DARK_MUTED),
                                    ft.Text(
                                        "Investigador", size=16, weight=ft.FontWeight.W_700, color=Colors.TEXT_ON_DARK
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
                ft.Column(spacing=Spacing.XS, controls=items_nav),
                ft.Container(expand=True),
                ft.Container(
                    padding=ft.padding.Padding.all(Spacing.MD),
                    content=ft.Column(
                        spacing=Spacing.SM,
                        controls=[
                            ft.Divider(color=ft.Colors.with_opacity(0.12, Colors.TEXT_ON_DARK), height=1),
                            StatusPill(
                                "bd",
                                "SQL Server conectado" if bd_conectada else "Sin conexión a BD",
                                Colors.SUCCESS if bd_conectada else Colors.DANGER,
                            ),
                            ft.Row(
                                spacing=Spacing.SM,
                                controls=[
                                    ft.Container(
                                        width=32,
                                        height=32,
                                        border_radius=16,
                                        bgcolor=Colors.PRIMARY,
                                        alignment=ft.alignment.Alignment.CENTER,
                                        content=ft.Text("K", size=16, weight=ft.FontWeight.W_700, color=Colors.TEXT_ON_DARK),
                                    ),
                                    ft.Column(
                                        spacing=0,
                                        tight=True,
                                        controls=[
                                            ft.Text("Kevin", size=13, weight=ft.FontWeight.W_600, color=Colors.TEXT_ON_DARK),
                                            ft.Text("v1.0.0", size=10, color=Colors.TEXT_ON_DARK_MUTED),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        )

    def _item_sidebar(self, indice: int, destino: dict) -> ft.Container:
        """Construye un ítem clickeable del sidebar, resaltado si es el activo.

        Args:
            indice: Posición del destino (0-4), la misma que espera _navegar().
            destino: Entrada de _DESTINOS_SIDEBAR con icono/icono_activo/label.

        Returns:
            ft.Container: Fila icono+texto, con fondo/color según esté activo.
        """
        activo = indice == self._indice_activo
        color_texto = Colors.TEXT_ON_DARK if activo else Colors.TEXT_ON_DARK_MUTED
        return ft.Container(
            on_click=lambda e, i=indice: self._navegar(i),
            ink=True,
            border_radius=Radius.BUTTON,
            margin=ft.margin.Margin.symmetric(horizontal=Spacing.SM),
            padding=ft.padding.Padding.symmetric(vertical=Spacing.SM + 2, horizontal=Spacing.MD),
            bgcolor=ft.Colors.with_opacity(0.14, Colors.TEXT_ON_DARK) if activo else None,
            animate=Motion.FAST,
            content=ft.Row(
                spacing=Spacing.SM,
                controls=[
                    ft.Icon(destino["icono_activo"] if activo else destino["icono"], color=color_texto, size=20),
                    ft.Text(
                        destino["label"],
                        color=color_texto,
                        size=14,
                        weight=ft.FontWeight.W_600 if activo else ft.FontWeight.W_400,
                    ),
                ],
            ),
        )

    def _navegar(self, indice: int) -> None:
        """Cambia de vista: reconstruye el sidebar y el área de contenido para `indice`.

        Args:
            indice: 0=Inicio, 1=Nueva sesión, 2=En vivo, 3=Cuestionario, 4=Análisis.
        """
        constructores = [
            self._vista_inicio,
            self._vista_nueva_sesion,
            self._vista_sesion_en_vivo,
            self._vista_cuestionario,
            self._vista_analisis,
        ]
        self._indice_activo = indice
        self.contenedor_sidebar.content = self._construir_sidebar()
        try:
            self.area_contenido.content = constructores[indice]()
        except Exception as error:
            logger.error(f"Error construyendo la vista {indice}: {error}")
            self.area_contenido.content = ft.Text(f"Error al cargar esta vista: {error}", color=Colors.DANGER)
        self._actualizar_pagina_segura()

    def _actualizar_pagina_segura(self) -> None:
        """Empuja page.update() de forma segura sin importar desde qué hilo se llame.

        Bug real encontrado probando la app: page.update() llamado directo
        desde un threading.Thread (ej. _hilo_orquestador) termina en
        asyncio.Queue.put_nowait() — que NO es seguro entre hilos: el ítem
        queda encolado pero el event loop de Flet no se "despierta" para
        procesarlo, así que la UI se ve congelada hasta que ALGÚN OTRO evento
        (ej. hacer click en el sidebar) empuja al loop a revisar la cola, y
        recién ahí aparecen de golpe todos los cambios acumulados.
        page.loop.call_soon_threadsafe() es la forma correcta de cruzar ese
        límite de hilos (documentada en ft.Page.run_task/run_thread) — y es
        segura de llamar también desde el propio hilo del event loop (los
        handlers de clicks/etc.), así que se usa siempre, sin distinguir de
        qué hilo viene la llamada.
        """
        try:
            self.page.loop.call_soon_threadsafe(self.page.update)
        except Exception as error:
            logger.warning(f"No se pudo programar la actualización de la página: {error}")

    def _mostrar_snack(self, snack: ft.SnackBar) -> None:
        """Muestra un SnackBar, tolerando el caso de que ya haya uno abierto."""
        try:
            self.page.show_dialog(snack)
        except Exception as error:
            logger.warning(f"No se pudo mostrar el snackbar ({error}); se ignora.")

    # =================================================================
    # VISTA 0: INICIO
    # =================================================================

    def _vista_inicio(self) -> ft.Control:
        """Dashboard con KPIs, línea de tiempo de sesiones recientes y accesos rápidos."""
        total_participantes = 0
        total_sesiones = 0
        nuevos_participantes_semana = 0
        nuevas_sesiones_semana = 0
        ultima_sesion_id = "—"
        ultima_sesion_fecha_corta = "Sin sesiones todavía"
        ultima_sesion_relativa = None
        eventos_timeline: list[dict] = []

        if self.bd is not None:
            try:
                total_participantes = len(self.bd.obtener_participantes())
                filas = self.bd.ejecutar_query("SELECT COUNT(*) AS n FROM sesiones WHERE duracion_seg IS NOT NULL") or []
                total_sesiones = filas[0]["n"] if filas else 0

                filas_p_semana = (
                    self.bd.ejecutar_query(
                        "SELECT COUNT(*) AS n FROM participantes WHERE fecha_registro >= DATEADD(day, -7, GETDATE())"
                    )
                    or []
                )
                nuevos_participantes_semana = filas_p_semana[0]["n"] if filas_p_semana else 0

                filas_s_semana = (
                    self.bd.ejecutar_query(
                        "SELECT COUNT(*) AS n FROM sesiones WHERE fecha_hora >= DATEADD(day, -7, GETDATE())"
                    )
                    or []
                )
                nuevas_sesiones_semana = filas_s_semana[0]["n"] if filas_s_semana else 0

                # Subconsulta escalar (COUNT de 'pruebas' por id_sesion, la FK real) en vez
                # de un JOIN+GROUP BY: para 5 filas es más simple de leer y evita traer filas
                # de más solo para contar — mismo dato, una sola consulta, sin interpolar
                # valores de fila en el texto del SQL (eso sí sería un riesgo de inyección
                # real, aunque los valores vengan de nuestra propia BD).
                filas_recientes = (
                    self.bd.ejecutar_query(
                        "SELECT TOP 5 s.id_sesion, s.id_participante, s.fecha_hora, s.hr_baseline, "
                        "(SELECT COUNT(*) FROM pruebas p WHERE p.id_sesion = s.id_sesion) AS n_pruebas "
                        "FROM sesiones s ORDER BY s.fecha_hora DESC"
                    )
                    or []
                )
                if filas_recientes:
                    ultima = filas_recientes[0]
                    ultima_sesion_id = ultima["id_participante"]
                    ultima_sesion_fecha_corta = ultima["fecha_hora"].strftime("%d/%m · %H:%M")
                    ultima_sesion_relativa = _tiempo_relativo_es(ultima["fecha_hora"])

                for fila in filas_recientes:
                    n_pruebas = fila.get("n_pruebas") or 0
                    badges = ["✅ Completa" if n_pruebas >= 4 else "⏳ Incompleta", f"{n_pruebas} estímulos"]
                    if fila.get("hr_baseline") is not None:
                        badges.append(f"HR {fila['hr_baseline']:.0f}")
                    eventos_timeline.append(
                        {
                            "titulo": f"Sesión — {fila['id_participante']}",
                            "subtitulo": "Protocolo completo registrado",
                            "hora": fila["fecha_hora"].strftime("%d/%m %H:%M"),
                            "icono": ft.Icons.FACT_CHECK_OUTLINED,
                            "color": Colors.SECONDARY,
                            "badges": badges,
                        }
                    )
            except Exception as error:
                logger.error(f"Error consultando KPIs de inicio: {error}")

        estado_color = Colors.SUCCESS if self.bd is not None else Colors.DANGER
        estado_texto = "Conectado" if self.bd is not None else "Sin conexión"
        estado_nota = f"Verificado a las {self._hora_conexion_bd.strftime('%H:%M')}" if self._hora_conexion_bd else None

        ahora = datetime.now()

        return ft.Column(
            expand=True,
            spacing=Spacing.XL,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Row(
                    spacing=Spacing.MD,
                    controls=[
                        IconCircle(ft.Icons.SPA, ft.Colors.with_opacity(0.12, Colors.PRIMARY), Colors.PRIMARY, tamaño=52),
                        ft.Column(
                            spacing=2,
                            controls=[
                                ft.Text(spans=[ft.TextSpan("Bienvenido de nuevo, Kevin 👋", style=Typography.H1)]),
                                ft.Text(spans=[ft.TextSpan(_fecha_larga_es(ahora), style=Typography.BODY_SECONDARY)]),
                                ft.Container(height=Spacing.XS),
                                ft.Text(spans=[ft.TextSpan("Sistema Adaptativo de Frecuencias Terapéuticas", style=Typography.H3)]),
                                ft.Text(spans=[ft.TextSpan("Panel del investigador — ESPE", style=Typography.BODY_SECONDARY)]),
                            ],
                        ),
                    ],
                ),
                ft.ResponsiveRow(
                    spacing=Spacing.MD,
                    run_spacing=Spacing.MD,
                    controls=[
                        ft.Container(
                            col={"xs": 12, "sm": 6, "md": 3},
                            content=KPICard(
                                "Participantes",
                                str(total_participantes),
                                ft.Icons.PEOPLE_OUTLINE,
                                Colors.PRIMARY,
                                tendencia=f"+{nuevos_participantes_semana} esta semana",
                            ),
                        ),
                        ft.Container(
                            col={"xs": 12, "sm": 6, "md": 3},
                            content=KPICard(
                                "Sesiones completadas",
                                str(total_sesiones),
                                ft.Icons.FACT_CHECK_OUTLINED,
                                Colors.SECONDARY,
                                tendencia=f"+{nuevas_sesiones_semana} esta semana",
                            ),
                        ),
                        ft.Container(
                            col={"xs": 12, "sm": 6, "md": 3},
                            content=KPICard(
                                "Última sesión",
                                ultima_sesion_id,
                                ft.Icons.SCHEDULE,
                                Colors.WARNING,
                                valor_secundario=ultima_sesion_fecha_corta,
                                nota=ultima_sesion_relativa,
                                icono_nota=ft.Icons.SCHEDULE,
                            ),
                        ),
                        ft.Container(
                            col={"xs": 12, "sm": 6, "md": 3},
                            content=KPICard(
                                "Estado del sistema",
                                estado_texto,
                                ft.Icons.DNS_OUTLINED,
                                estado_color,
                                nota=estado_nota,
                                icono_nota=ft.Icons.CHECK_CIRCLE_OUTLINE,
                            ),
                        ),
                    ],
                ),
                ft.Row(
                    spacing=Spacing.LG,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            expand=2,
                            padding=ft.padding.Padding.all(Spacing.LG),
                            border_radius=Radius.CARD,
                            bgcolor=Colors.BG_CARD,
                            shadow=Shadows.SM,
                            content=ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    SectionHeader("Actividad reciente", "Últimas sesiones registradas en SQL Server"),
                                    Timeline(eventos_timeline),
                                ],
                            ),
                        ),
                        ft.Container(
                            expand=1,
                            padding=ft.padding.Padding.all(Spacing.LG),
                            border_radius=Radius.CARD,
                            bgcolor=Colors.BG_CARD,
                            shadow=Shadows.SM,
                            content=ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    SectionHeader("Accesos rápidos"),
                                    GradientButton(
                                        "Iniciar nueva sesión",
                                        on_click=lambda e: self._navegar(1),
                                        icono=ft.Icons.ADD_CIRCLE_OUTLINE,
                                    ),
                                    GradientButton(
                                        "Ver análisis",
                                        on_click=lambda e: self._navegar(4),
                                        icono=ft.Icons.INSIGHTS_OUTLINED,
                                        color_start=Colors.SECONDARY,
                                        color_end=Colors.ACCENT,
                                    ),
                                    ft.OutlinedButton(
                                        content=ft.Row(
                                            spacing=Spacing.XS + 2,
                                            tight=True,
                                            alignment=ft.MainAxisAlignment.CENTER,
                                            controls=[
                                                ft.Icon(ft.Icons.FILE_DOWNLOAD_OUTLINED, size=18, color=Colors.PRIMARY),
                                                ft.Text("Exportar reporte", color=Colors.PRIMARY, weight=ft.FontWeight.W_600, size=14),
                                            ],
                                        ),
                                        on_click=lambda e: self._cambiar_tab_analisis("exportar"),
                                        style=ft.ButtonStyle(
                                            side=ft.BorderSide(1.5, Colors.PRIMARY),
                                            bgcolor=ft.Colors.TRANSPARENT,
                                            shape=ft.RoundedRectangleBorder(radius=Radius.BUTTON),
                                            padding=ft.padding.Padding.symmetric(vertical=14, horizontal=22),
                                        ),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            ],
        )

    # =================================================================
    # VISTA 1: NUEVA SESIÓN
    # =================================================================

    def _vista_nueva_sesion(self) -> ft.Control:
        """Formulario de registro de participante + panel de verificación de hardware."""
        id_sugerido = "P001"
        if self.bd is not None:
            try:
                id_sugerido = self.bd.siguiente_id_participante()
            except Exception as error:
                logger.error(f"No se pudo calcular el siguiente ID: {error}")

        self.formulario = FormularioParticipante(id_sugerido, on_change=self._revalidar_formulario)
        # Autocompletado al salir del campo ID (on_blur, no on_change — on_change
        # dispara en CADA tecla mientras escribe el ID, y una consulta a SQL Server
        # por tecla sería un desperdicio y podría parpadear la UI a medio tipear).
        # Ver _autocompletar_participante_existente().
        self.formulario.campo_id.on_blur = self._autocompletar_participante_existente

        mic_ok = self._verificar_microfono()
        db_ok = self.bd is not None

        # Envueltos en Container para poder REEMPLAZAR el IndicadorHardware entero cuando
        # cambia el estado (switch apagado / detectado / no detectado) — mismo patrón que
        # contenedor_tabla en _tab_resumen_general(): reemplazar el control, no mutar sus
        # props in-place (ver el bug real documentado ahí).
        self._contenedor_indicador_wahoo = ft.Container(content=self._construir_indicador_wahoo())
        self._contenedor_indicador_vr = ft.Container(content=self._construir_indicador_vr())

        panel_hardware = ft.Column(
            spacing=Spacing.XS,
            controls=[
                self._contenedor_indicador_wahoo,
                IndicadorHardware(
                    "Micrófono F15-2",
                    mic_ok,
                    None if mic_ok else "No se detectó un micrófono de entrada por defecto en este equipo",
                ),
                self._contenedor_indicador_vr,
                IndicadorHardware(
                    "Base de datos SQL Server", db_ok, None if db_ok else "No se pudo conectar — revisa .env"
                ),
            ],
        )

        self.boton_registrar = BotonAccionPrincipal(
            "Registrar e Iniciar Sesión", on_click=self._al_registrar_participante, disabled=True
        )
        # Lista lo que falta del formulario en vez de solo deshabilitar el botón en
        # silencio — un botón inactivo sin explicación es un bug de UX (ver
        # _revalidar_formulario()), por eso se inicializa ya con los errores actuales.
        self.texto_validacion_formulario = ft.Text(
            "\n".join(f"• {e}" for e in self.formulario.errores()), size=12, color=Colors.WARNING
        )
        tarjeta_validacion_formulario = ft.Container(
            padding=ft.padding.Padding.all(Spacing.MD),
            border_radius=Radius.INPUT,
            bgcolor=ft.Colors.with_opacity(0.10, Colors.WARNING),
            content=ft.Row(
                spacing=Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=Colors.WARNING, size=20),
                    ft.Column(
                        expand=True,
                        spacing=Spacing.XS,
                        controls=[
                            ft.Text("Faltan datos por completar", size=13, weight=ft.FontWeight.W_600, color=Colors.WARNING),
                            self.texto_validacion_formulario,
                        ],
                    ),
                ],
            ),
        )

        # --- Día de la sesión (1/2/3/4/5, ver PROTOCOLO POR DÍA en el docstring del
        # módulo) — el investigador lo elige a mano; Días 2 y 4 fuerzan
        # tipo_estimulo="preferencia" y usan campo_preferencia_wav (la MISMA canción
        # en ambos días — ya no hay un segundo campo obligatorio). El Día 5 es
        # adaptativo: se decide automáticamente contra la BD (ver
        # decidir_estimulo_dia5 en sesion_completa.py) y también puede necesitar
        # campo_preferencia_wav si la condición ganadora resulta "preferencia" (ver
        # _revalidar_formulario, _al_registrar_participante). ft.Dropdown en esta
        # versión de Flet no dispara "on_change" (ver el mismo bug real documentado
        # en selector_orden más abajo, en _tab_participantes) — el evento correcto
        # es "on_select". ---
        self.selector_dia = ft.Dropdown(
            label="Día de la sesión",
            value="1",
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
            options=[
                ft.dropdown.Option("1", "Día 1 — estímulo sorteado"),
                ft.dropdown.Option("2", "Día 2 — preferencia personal"),
                ft.dropdown.Option("3", "Día 3 — repite estímulo de Día 1"),
                ft.dropdown.Option("4", "Día 4 — repite preferencia de Día 2"),
                ft.dropdown.Option("5", "Día 5 — adaptativa (repite el mejor estímulo)"),
            ],
        )
        self.selector_dia.on_select = lambda e: self._revalidar_formulario()

        # --- Modo de sesión: real vs. simulado (ver CAPTURA REAL en el docstring del módulo) ---
        # Chequeo real, no cosmético (mismo criterio que _al_cambiar_switch_vr más abajo):
        # al prender el switch, corre un escaneo BLE corto (_verificar_wahoo_ble) buscando
        # la MAC exacta que la sesión real va a intentar conectar (MAC_WAHOO_DEFAULT) — el
        # ícono de arriba recién se pone verde si lo encontró de verdad.
        def _al_cambiar_switch_sensor(e: ft.ControlEvent) -> None:
            if self.check_sensor_real.value:
                self._wahoo_ok = self._verificar_wahoo_ble()
            else:
                self._wahoo_ok = True  # apagado no bloquea nada, ver _revalidar_formulario()
            self._contenedor_indicador_wahoo.content = self._construir_indicador_wahoo()
            self._revalidar_formulario()

        self.check_sensor_real = ft.Switch(
            label="Usar sensor Wahoo TRACKR real (BLE)",
            value=False,
            active_color=Colors.PRIMARY,
            on_change=_al_cambiar_switch_sensor,
        )
        self.check_audio_real = ft.Switch(label="Reproducir estímulos de audio reales", value=True, active_color=Colors.PRIMARY)

        # --- VR (Meta Quest 2, SOLO visual — ver vr/unity_osc.py). El audio no cambia en
        # absoluto con esto prendido o apagado, de ahí el texto debajo del switch. ---
        def _al_cambiar_switch_vr(e: ft.ControlEvent) -> None:
            if self.check_usar_vr.value:
                # ping() bloquea hasta ~1.5s (timeout de UnityOSC) — aceptable para un
                # chequeo puntual disparado por un click, mismo criterio que ya usa
                # _verificar_microfono() en esta misma vista (también síncrono).
                self._vr_ok = UnityOSC().ping()
            else:
                self._vr_ok = True  # apagado no bloquea nada, ver _revalidar_formulario()
            self._contenedor_indicador_vr.content = self._construir_indicador_vr()
            self._revalidar_formulario()

        self.check_usar_vr = ft.Switch(
            label="Usar Meta Quest 2 (visual)", value=False, active_color=Colors.PRIMARY, on_change=_al_cambiar_switch_vr
        )

        self.campo_preferencia_wav = ft.TextField(
            label="Ruta al audio de preferencia personal (obligatorio en Días 2, 4 y 5)",
            hint_text=r"C:\Tesis_Kevin\audio_estimulos\preferencias\mi_cancion.wav",
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
            prefix_icon=ft.Icons.AUDIO_FILE_OUTLINED,
            on_change=lambda e: self._revalidar_formulario(),
        )

        def _tarjeta(titulo: str, icono: str, contenido: ft.Control) -> ft.Control:
            return ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                shadow=Shadows.SM,
                content=ft.Column(
                    spacing=Spacing.MD,
                    controls=[
                        ft.Row(
                            spacing=Spacing.SM,
                            controls=[
                                IconCircle(icono, ft.Colors.with_opacity(0.12, Colors.PRIMARY), Colors.PRIMARY, tamaño=32),
                                ft.Text(titulo, size=16, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY),
                            ],
                        ),
                        contenido,
                    ],
                ),
            )

        panel_modo_sesion = ft.Column(
            spacing=Spacing.SM,
            controls=[
                self.selector_dia,
                self.check_sensor_real,
                self.check_audio_real,
                self.check_usar_vr,
                ft.Text(
                    "El audio se sigue reproduciendo por audífonos Bluetooth como siempre.",
                    size=11,
                    color=Colors.TEXT_SECONDARY,
                ),
                self.campo_preferencia_wav,
                ft.Container(
                    padding=ft.padding.Padding.all(Spacing.SM),
                    border_radius=Radius.INPUT,
                    bgcolor=ft.Colors.with_opacity(0.08, Colors.WARNING),
                    content=ft.Text(
                        f"Protocolo de UN día: baseline {DURACION_BASELINE_SEG}s -> UN estímulo "
                        f"{DURACION_ESTIMULO_SEG}s (Días 2 y 4: preferencia personal, canción distinta "
                        f"cada día; Días 1 y 3: sorteado entre binaural_theta / "
                        f"solfeggio_isocronico_528Hz / paisaje_biofilico, ver "
                        f"asignar_estimulos_dia1_dia3()) -> cierre {DURACION_CIERRE_SEG}s — no se puede "
                        "pausar ni saltar bloques a mitad de camino (ver docstring del módulo). Con "
                        "Meta Quest 2 activado: el participante camina libremente por el entorno VR y "
                        "el protocolo recién arranca cuando se sienta en la silla (confirmado por "
                        "Unity) — la Vista en vivo muestra 'Esperando a que se siente...' hasta entonces.",
                        size=11,
                        color=Colors.TEXT_SECONDARY,
                    ),
                ),
            ],
        )

        breadcrumb = ft.Row(
            spacing=Spacing.XS,
            controls=[
                ft.TextButton(
                    content=ft.Text("Inicio", size=12, color=Colors.TEXT_SECONDARY),
                    on_click=lambda e: self._navegar(0),
                    style=ft.ButtonStyle(padding=ft.padding.Padding.symmetric(vertical=0, horizontal=Spacing.XS)),
                ),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=Colors.TEXT_SECONDARY),
                ft.Text("Nueva sesión", size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY),
            ],
        )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=Spacing.LG,
            controls=[
                breadcrumb,
                SectionHeader("Nueva sesión", "Registra un participante y verifica el hardware antes de arrancar"),
                ft.ResponsiveRow(
                    spacing=Spacing.LG,
                    run_spacing=Spacing.LG,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            col={"xs": 12, "lg": 7},
                            content=_tarjeta("Datos del participante", ft.Icons.PERSON_OUTLINE, self.formulario.build()),
                        ),
                        ft.Container(
                            col={"xs": 12, "lg": 5},
                            content=ft.Column(
                                spacing=Spacing.LG,
                                controls=[
                                    _tarjeta("Verificación de hardware", ft.Icons.SETTINGS_INPUT_ANTENNA, panel_hardware),
                                    _tarjeta("Modo de sesión", ft.Icons.TUNE, panel_modo_sesion),
                                ],
                            ),
                        ),
                    ],
                ),
                tarjeta_validacion_formulario,
                ft.Row(
                    spacing=Spacing.SM,
                    controls=[
                        ft.OutlinedButton(content=ft.Text("Cancelar"), on_click=lambda e: self._navegar(0)),
                        self.boton_registrar.contenedor,
                    ],
                ),
            ],
        )

    def _autocompletar_participante_existente(self, e: ft.ControlEvent) -> None:
        """Si el ID que se acaba de escribir en campo_id ya existe en la BD, precarga
        sus datos demográficos y sus rutas de audio de preferencia si ya las tenía
        guardadas (mismo participante — no hace falta re-tipearlas en cada uno de
        sus 5 días) y sugiere el Día siguiente en self.selector_dia.

        La sugerencia de Día es una HEURÍSTICA (cantidad de sesiones ya guardadas +
        1, tope 5), NO un dato autoritativo: bd_sqlserver.py no persiste ningún
        campo "dia" en la tabla de sesiones (el Día es un concepto que solo existe
        en memoria, ver PROTOCOLO POR DÍA en el docstring del módulo), así que esto
        puede quedar mal si una sesión anterior falló a mitad de camino sin
        guardarse, o si el investigador necesita repetir un día. Por eso queda
        editable — nunca deshabilita el selector, solo lo pre-selecciona.

        No toca check_consentimiento a propósito: el consentimiento se confirma
        activamente cada sesión, no se hereda de una sesión anterior.
        """
        if self.bd is None:
            return
        id_participante = (self.formulario.campo_id.value or "").strip()
        if not id_participante:
            return

        participantes = self.bd.obtener_participantes()
        existente = next((p for p in participantes if p.get("id_participante") == id_participante), None)
        if existente is None:
            return  # ID nuevo (o todavía no registrado): nada que precargar

        self.formulario.campo_edad.value = str(existente["edad"])
        self.formulario.grupo_genero.establecer(existente["genero"])
        # .get() (no []): si todavía no se corrió el ALTER TABLE que agrega esta
        # columna (ver ESQUEMA DE LA BASE en bd_sqlserver.py), el SELECT * de
        # obtener_participantes() simplemente no la trae — sin esto, romper acá.
        ruta_guardada = existente.get("ruta_preferencia_wav")
        if ruta_guardada and getattr(self, "campo_preferencia_wav", None) is not None:
            self.campo_preferencia_wav.value = ruta_guardada

        sesiones_previas = self.bd.obtener_sesiones_participante(id_participante)
        dia_sugerido = min(len(sesiones_previas) + 1, 5)
        if getattr(self, "selector_dia", None) is not None:
            self.selector_dia.value = str(dia_sugerido)

        self._mostrar_snack(
            SnackBarExito(
                f"{id_participante} ya existe ({len(sesiones_previas)} sesión(es) previa(s)) — "
                f"datos precargados, Día {dia_sugerido} sugerido (revisalo antes de registrar)."
            )
        )
        self._revalidar_formulario()

    def _revalidar_formulario(self) -> None:
        """Habilita/deshabilita el botón de registro y muestra qué falta, en vivo."""
        if self.formulario is None:
            return
        errores = self.formulario.errores()
        # VR encendido pero Unity sin responder: no dejar arrancar la sesión (a pedido
        # explícito) — se suma a la MISMA lista que ya usa el investigador para ver qué
        # falta, en vez de un mensaje aparte (ver texto_validacion_formulario más abajo).
        if getattr(self, "check_usar_vr", None) is not None and self.check_usar_vr.value and not self._vr_ok:
            errores.append("Meta Quest 2 no responde — activá Unity con el Quest conectado y presioná Play.")
        # Wahoo activado pero no detectado por BLE: mismo criterio que VR arriba —
        # no dejar arrancar una sesión real con un sensor que ya sabemos que no está.
        if getattr(self, "check_sensor_real", None) is not None and self.check_sensor_real.value and not self._wahoo_ok:
            errores.append("Sensor Wahoo TRACKR no detectado por BLE — verificá que esté prendido y cerca.")
        # Días 2 y 4 son SIEMPRE preferencia personal (ver PROTOCOLO POR DÍA en el
        # docstring del módulo) — sin su ruta de WAV ese bloque no tendría qué
        # reproducir. Día 4 repite la MISMA canción del Día 2 (mismo campo, ya no
        # uno separado). El Día 5 también puede terminar siendo "preferencia" (la
        # sesión adaptativa repite lo que mejor resultó en los Días 1-4) — como no
        # se sabe cuál condición gana hasta calcularlo contra la BD, se exige el
        # campo igual en Día 5 para no bloquear el registro a mitad de camino.
        if (
            getattr(self, "selector_dia", None) is not None
            and self.selector_dia.value in ("2", "4", "5")
            and not (getattr(self, "campo_preferencia_wav", None) and (self.campo_preferencia_wav.value or "").strip())
        ):
            errores.append("Días 2, 4 y 5 requieren la ruta al audio de preferencia personal.")
        self.boton_registrar.disabled = bool(errores)
        self.texto_validacion_formulario.value = "\n".join(f"• {e}" for e in errores)
        self._actualizar_pagina_segura()

    def _construir_indicador_wahoo(self) -> ft.Control:
        """Arma el IndicadorHardware del sensor Wahoo según el estado actual: switch
        apagado (neutro), encendido+detectado (verde), encendido+no detectado (rojo).
        Mismo patrón que _construir_indicador_vr (getattr porque se llama también en
        la construcción inicial de la vista, antes de que self.check_sensor_real
        exista todavía)."""
        switch = getattr(self, "check_sensor_real", None)
        if switch is None or not switch.value:
            return IndicadorHardware(
                "Sensor cardíaco Wahoo TRACKR (BLE)",
                False,
                "Desactivado — activá el switch para verificarlo y usarlo en esta sesión.",
            )
        if self._wahoo_ok:
            return IndicadorHardware(
                "Sensor cardíaco Wahoo TRACKR (BLE)", True, f"Detectado por BLE ({MAC_WAHOO_DEFAULT})."
            )
        return IndicadorHardware(
            "Sensor cardíaco Wahoo TRACKR (BLE)",
            False,
            "No se detectó por BLE — verificá que esté prendido, con los electrodos húmedos, y cerca.",
        )

    def _construir_indicador_vr(self) -> ft.Control:
        """Arma el IndicadorHardware de Meta Quest 2 según el estado actual: switch
        apagado (neutro), encendido+ping OK (verde), encendido+ping falló (rojo, con
        el tooltip exacto pedido). Se llama tanto en la construcción inicial de la
        vista (self.check_usar_vr todavía no existe en ESE momento puntual — ver el
        getattr) como desde el on_change del switch."""
        switch = getattr(self, "check_usar_vr", None)
        if switch is None or not switch.value:
            return IndicadorHardware(
                "Meta Quest 2 (Unity)", False, "Desactivado — activá el switch para usarlo en esta sesión."
            )
        if self._vr_ok:
            return IndicadorHardware("Meta Quest 2 (Unity)", True, "Unity respondió correctamente.")
        return IndicadorHardware(
            "Meta Quest 2 (Unity)",
            False,
            "Unity no responde en puerto 8000. Abrí la escena en Unity con el Quest conectado y presioná Play.",
        )

    @staticmethod
    def _verificar_microfono() -> bool:
        """Chequeo real (no simulado): ¿hay un dispositivo de entrada de audio por defecto?

        Returns:
            bool: True si sounddevice reporta un dispositivo de entrada con
                al menos un canal. No confirma que sea específicamente el
                F15-2 — solo que hay ALGÚN micrófono disponible.
        """
        try:
            import sounddevice as sd

            info = sd.query_devices(kind="input")
            return bool(info) and info.get("max_input_channels", 0) > 0
        except Exception as error:
            logger.warning(f"No se pudo verificar el micrófono: {error}")
            return False

    @staticmethod
    def _verificar_wahoo_ble(timeout_seg: float = 12.0) -> bool:
        """Chequeo real y no cosmético (ver _escanear_mac_wahoo): True si la MAC del
        Wahoo (MAC_WAHOO_DEFAULT) aparece en un escaneo BLE de 12s (ver el porqué
        de ese número exacto en _escanear_mac_wahoo — 4s y 8s daban falsos
        negativos probando con el sensor real de este proyecto). Un escaneo
        puede seguir dando un falso negativo puntual si el sensor anuncia en un
        intervalo todavía más largo (ver sensor/escanear_ble.py) — no es 100%
        definitivo, la conexión real al arrancar la sesión
        (HiloSensorBLE.iniciar()) es la que manda.

        Corre en un hilo aparte a propósito: este método se llama desde el
        on_change del switch, que Flet dispara en el MISMO hilo donde ya corre su
        propio event loop de asyncio — asyncio.run() no se puede llamar si ya hay
        un loop corriendo en ese hilo (RuntimeError real, encontrado probando esto:
        "asyncio.run() cannot be called from a running event loop"). Un hilo nuevo
        no hereda ningún loop, así que ahí adentro asyncio.run() es seguro; el
        .join() de afuera preserva el mismo comportamiento bloqueante (~timeout_seg)
        que ya tenía _al_cambiar_switch_sensor.

        Returns:
            bool: True si se detectó. False si no se detectó, O si el escaneo
                falló (Bluetooth apagado, sin permisos, etc.) — nunca lanza
                excepción hacia quien llama.
        """
        resultado: dict = {"detectado": False}

        def _correr_scan() -> None:
            try:
                resultado["detectado"] = asyncio.run(_escanear_mac_wahoo(MAC_WAHOO_DEFAULT, timeout_seg=timeout_seg))
            except Exception as error:
                logger.warning(f"No se pudo escanear BLE para verificar el Wahoo: {error}")

        hilo_scan = threading.Thread(target=_correr_scan, daemon=True)
        hilo_scan.start()
        hilo_scan.join()
        return resultado["detectado"]

    def _al_registrar_participante(self, e: ft.ControlEvent) -> None:
        """Registra el participante y arranca la captura (Vista 2). La fila de 'sesiones'
        se crea recién al terminar (ver _guardar_en_sql_server()) — se necesitan las
        métricas ya calculadas para poder guardar el baseline real."""
        if self.bd is None:
            self._mostrar_snack(SnackBarError("No hay conexión a SQL Server; no se puede registrar."))
            return

        # Validado también en _revalidar_formulario (deshabilita el botón) — se repite
        # acá como última barrera antes de tocar la BD/el hardware real, por si el
        # estado del botón quedó desactualizado.
        dia_sesion = int(self.selector_dia.value or "1")
        ruta_preferencia_wav = (self.campo_preferencia_wav.value or "").strip() or None
        if dia_sesion in (2, 4, 5) and ruta_preferencia_wav is None:
            self._mostrar_snack(SnackBarError("Días 2, 4 y 5 requieren la ruta al audio de preferencia personal."))
            return

        datos = self.formulario.obtener_datos()
        try:
            registrado = self.bd.registrar_participante(
                datos["id_participante"],
                datos["edad"],
                datos["genero"],
                observaciones=datos["observaciones"],
                consentimiento=datos["consentimiento"],
            )
            if not registrado:
                logger.warning(f"{datos['id_participante']} ya existía; se reutiliza para la nueva sesión.")

            # Guarda/actualiza la ruta de preferencia en el participante (no en la
            # sesión) cada vez que se indica una — así el Día 2/Día 4 de ESTE MISMO
            # participante la trae precargada la próxima vez (ver
            # _autocompletar_participante_existente()). No es solo para Día 2/4: si
            # se indicó en cualquier día, se guarda igual.
            if ruta_preferencia_wav is not None:
                self.bd.actualizar_ruta_preferencia(datos["id_participante"], ruta_preferencia_wav)

            self.participante_actual = datos
            self.usar_sensor_real = bool(self.check_sensor_real.value)
            self.reproducir_audio_real = bool(self.check_audio_real.value)
            self.ruta_preferencia_wav = ruta_preferencia_wav
            self.usar_vr = bool(self.check_usar_vr.value)
            self.dia_sesion = dia_sesion

            # Días 2 y 4 son SIEMPRE preferencia personal (ver PROTOCOLO POR DÍA en el
            # docstring del módulo, sesion_completa.py); Días 1 y 3 usan el sorteo
            # determinístico de asignar_estimulos_dia1_dia3() — mismo participante_id
            # siempre da el mismo resultado, sin necesidad de guardar en la BD qué le
            # tocó cada día. Día 5 consulta la BD para decidir automáticamente cuál
            # condición repetir (ver decidir_estimulo_dia5 en sesion_completa.py) —
            # eso es lo que hace al sistema "adaptativo".
            if self.dia_sesion in (2, 4):
                self.tipo_estimulo_sesion = "preferencia"
            elif self.dia_sesion == 5:
                try:
                    self.tipo_estimulo_sesion = decidir_estimulo_dia5(datos["id_participante"])
                except ValueError as error:
                    self._mostrar_snack(
                        SnackBarError(f"No se pudo decidir el estímulo del Día 5: {error}")
                    )
                    return
                logger.info(
                    f"{datos['id_participante']} día 5 (adaptativa): estímulo decidido -> "
                    f"'{self.tipo_estimulo_sesion}'"
                )
            else:
                tipo_dia1, tipo_dia3 = asignar_estimulos_dia1_dia3(datos["id_participante"])
                self.tipo_estimulo_sesion = tipo_dia1 if self.dia_sesion == 1 else tipo_dia3
                logger.info(
                    f"{datos['id_participante']} día {self.dia_sesion}: estímulo sorteado -> "
                    f"'{self.tipo_estimulo_sesion}' (sorteo completo: día1='{tipo_dia1}', día3='{tipo_dia3}')"
                )

            self.bloques_estimulo_sesion = [
                {
                    "nombre": self.tipo_estimulo_sesion,
                    **_METADATOS_TIPO_ESTIMULO.get(
                        self.tipo_estimulo_sesion, {"titulo": self.tipo_estimulo_sesion, "icono": "🎧"}
                    ),
                }
            ]

            # Aviso ANTES de arrancar (no solo en el log de consola, que a veces no se
            # revisa): si va a sonar audio real pero el WAV de preferencia no existe, ese
            # bloque va a quedar en silencio (degradación ya existente en
            # _resolver_audio_real() de sesion_completa.py) — mejor que se sepa de una.
            # Día 2 y Día 4 repiten la MISMA canción (self.ruta_preferencia_wav); Día 5
            # solo la necesita si tipo_estimulo_sesion resultó "preferencia".
            if (
                self.reproducir_audio_real
                and self.tipo_estimulo_sesion == "preferencia"
                and not Path(self.ruta_preferencia_wav).exists()
            ):
                self._mostrar_snack(
                    SnackBarError(f"No existe el archivo '{self.ruta_preferencia_wav}': ese bloque va a sonar en silencio.")
                )

            # Reset de estado de captura: por si ya se corrió una sesión antes en el
            # mismo proceso de la app (ver el bug real de tiempo_transcurrido_sesion
            # heredado, encontrado probando la versión anterior).
            self.hr_historial = []
            self.resultado_metricas_sesion = None
            self.respuestas_cuestionario = {}
            self.indice_pregunta_actual = 0
            self.error_captura = None
            self.captura_terminada = False
            self.esperando_sentado = False
            self._evento_cancelar_espera_sentado.clear()
            self._hr_baseline_muestras = []
            self._hr_baseline_vivo = None
            self._ultimo_hr_valor = None
            self._ultimo_hr_cambio_ts = None
            # Mismo protocolo (mismo tipo_estimulo_sesion ya sorteado arriba) que
            # _hilo_orquestador() va a recalcular — se arma acá también (función pura,
            # sin I/O) solo para que la Vista en vivo tenga la lista de bloques
            # disponible desde su primer render.
            self.protocolo_activo = obtener_protocolo_sesion_dia(
                self.tipo_estimulo_sesion,
                duracion_baseline_seg=DURACION_BASELINE_SEG,
                duracion_estimulo_seg=DURACION_ESTIMULO_SEG,
                duracion_cierre_seg=DURACION_CIERRE_SEG,
            )

            self._mostrar_snack(
                SnackBarExito(
                    f"{datos['id_participante']} registrado (Día {self.dia_sesion}, "
                    f"estímulo '{self.tipo_estimulo_sesion}'). Iniciando captura..."
                )
            )
            self._navegar(2)
            self._iniciar_captura()
        except Exception as error:
            logger.error(f"Error registrando participante: {error}")
            self._mostrar_snack(SnackBarError(f"No se pudo registrar: {error}"))

    # =================================================================
    # VISTA 2: SESIÓN EN VIVO
    # =================================================================

    def _vista_sesion_en_vivo(self) -> ft.Control:
        """Monitor "cockpit" de la captura real/simulada en curso (ver _hilo_orquestador)."""
        if self.participante_actual is None:
            return EmptyState(
                ft.Icons.SENSORS_OFF,
                "No hay una sesión activa",
                "Registrá un participante en Nueva sesión para arrancar la captura.",
                accion=GradientButton("Ir a Nueva sesión", on_click=lambda e: self._navegar(1), icono=ft.Icons.ARROW_FORWARD),
                color=Colors.TEXT_SECONDARY,
            )

        if self.error_captura is not None:
            return ft.Column(
                spacing=Spacing.MD,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    IconCircle(ft.Icons.ERROR_OUTLINE, ft.Colors.with_opacity(0.12, Colors.DANGER), Colors.DANGER, tamaño=64),
                    ft.Text("La captura falló", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(self.error_captura, color=Colors.DANGER),
                    GradientButton("Volver a Inicio", on_click=lambda e: self._navegar(0)),
                ],
            )

        # Interacción embebida (ver INTERACCIÓN EMBEBIDA en el docstring de
        # sesion_completa.py): el participante todavía está caminando por el entorno
        # VR — sensor y micrófono ya están conectados, pero t0/estabilización/audio NO
        # arrancaron todavía. Reemplaza el cockpit normal entero mientras dura (no
        # tiene sentido mostrar timers en 00:00 de un protocolo que no arrancó).
        if self.esperando_sentado:
            return ft.Column(
                expand=True,
                spacing=Spacing.LG,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.ProgressRing(color=Colors.PRIMARY),
                    ft.Text("Esperando a que el participante se siente...", size=20, weight=ft.FontWeight.W_600),
                    ft.Container(
                        width=420,
                        content=ft.Text(
                            "El sensor y el micrófono ya están conectados. El participante puede "
                            "seguir caminando por el entorno VR — el baseline, el estímulo y el "
                            "cierre arrancan automáticamente en cuanto se siente en la silla.",
                            size=13,
                            color=Colors.TEXT_SECONDARY,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ),
                    ft.OutlinedButton(
                        content=ft.Text("Cancelar sesión", color=Colors.DANGER),
                        on_click=self._al_cancelar_espera_sentado,
                    ),
                ],
            )

        modo_texto = []
        modo_texto.append("sensor Wahoo real" if self.usar_sensor_real else "sensor simulado")
        modo_texto.append("audio real" if self.reproducir_audio_real else "sin audio real")

        # --- Timers: bloque actual (grande) + sesión total (chico), ver MEJORA 1 ---
        self.texto_timer_bloque = ft.Text(
            spans=[ft.TextSpan("00:00 / 00:00", style=ft.TextStyle(size=28, weight=ft.FontWeight.W_800, color=Colors.TEXT_PRIMARY))]
        )
        self.texto_timer_sesion = ft.Text(
            spans=[ft.TextSpan("00:00 / 00:00", style=Typography.BODY_SECONDARY)]
        )
        self.barra_progreso_sesion = ft.ProgressBar(
            value=0, color=Colors.PRIMARY, bgcolor=Colors.BORDER, border_radius=Radius.CHIP, width=460
        )
        self.texto_estimulo_actual = ft.Text("Preparando sesión (estabilización)...", size=18, weight=ft.FontWeight.W_600)
        self.texto_bloque_siguiente = ft.Text("", size=12, color=Colors.TEXT_SECONDARY)
        self.texto_hr_actual = ft.Text("--", size=40, weight=ft.FontWeight.W_800, color=Colors.SUCCESS)
        self.texto_comparacion_baseline = ft.Text("Calculando baseline...", size=11, color=Colors.TEXT_SECONDARY)
        self.texto_respiraciones = ft.Text("Se calcula al finalizar", size=13, color=Colors.TEXT_SECONDARY)
        # HRV en vivo: solo disponible con sensor Wahoo real (ver _peek_hrv) — el
        # simulador no expone un historial de R-R sin interferir con la captura.
        valor_inicial_hrv = "—" if self.usar_sensor_real else "N/D"
        self.texto_sdnn_actual = ft.Text(valor_inicial_hrv, size=24, weight=ft.FontWeight.W_700, color=Colors.SECONDARY)
        self.texto_rmssd_actual = ft.Text(valor_inicial_hrv, size=24, weight=ft.FontWeight.W_700, color=Colors.SECONDARY)

        # --- Chip de zona de HR (MEJORA 7) ---
        self._punto_zona_hr = ft.Container(width=8, height=8, border_radius=4, bgcolor=Colors.BORDER)
        self._texto_zona_hr = ft.Text("—", size=11, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY)
        self._chip_zona_hr = ft.Container(
            padding=ft.padding.Padding.symmetric(vertical=Spacing.XS, horizontal=Spacing.SM),
            border_radius=Radius.CHIP,
            bgcolor=ft.Colors.with_opacity(0.10, Colors.TEXT_SECONDARY),
            content=ft.Row(spacing=Spacing.XS, tight=True, controls=[self._punto_zona_hr, self._texto_zona_hr]),
        )

        # Corazón "pulsante": late al mismo ritmo que _actualizar_controles_en_vivo_real()
        # refresca la UI (~1s) — reutiliza el único punto de update ya probado seguro
        # entre hilos, en vez de armar un temporizador nuevo solo para la animación. El
        # tempo (animate_scale.duration) se recalcula cada tick según el HR real — ver
        # MEJORA 8 en _actualizar_controles_en_vivo_real().
        self._icono_pulso = ft.Container(
            content=ft.Icon(ft.Icons.FAVORITE, color=Colors.DANGER, size=26),
            scale=1.0,
            animate_scale=Motion.NORMAL,
        )
        # Gauge circular detrás del HR — value se normaliza sobre un rango 40-140bpm
        # (ver _actualizar_controles_en_vivo_real), solo decorativo.
        self._anillo_hr = ft.ProgressRing(
            value=0, width=120, height=120, stroke_width=8, color=Colors.SUCCESS, bgcolor=Colors.BORDER
        )

        # --- Señal BLE (MEJORA 9) y latidos capturados (MEJORA 10): solo con sensor real ---
        self._barras_senal: list[ft.Container] = []
        self.texto_calidad_senal = ft.Text("", size=11, color=Colors.TEXT_SECONDARY)
        indicador_senal: Optional[ft.Control] = None
        if self.usar_sensor_real:
            for i in range(4):
                self._barras_senal.append(
                    ft.Container(width=4, height=8 + i * 4, border_radius=2, bgcolor=Colors.BORDER)
                )
            indicador_senal = ft.Row(
                spacing=Spacing.XS,
                controls=[
                    ft.Text("📶", size=13),
                    ft.Row(spacing=2, tight=True, controls=self._barras_senal),
                    self.texto_calidad_senal,
                ],
            )

        self.texto_latidos_capturados = ft.Text(
            "N/D en modo simulado" if not self.usar_sensor_real else "0", size=24, weight=ft.FontWeight.W_700, color=Colors.PRIMARY
        )
        self.texto_ultimos_rr = ft.Text("", size=11, color=Colors.TEXT_SECONDARY)

        self.serie_hr = fc.LineChartData(
            points=[],
            color=Colors.PRIMARY,
            curved=True,
            stroke_width=3,
            shadow=ft.BoxShadow(blur_radius=6, color=ft.Colors.with_opacity(0.18, Colors.PRIMARY)),
            below_line_gradient=ft.LinearGradient(
                colors=[ft.Colors.with_opacity(0.25, Colors.PRIMARY), ft.Colors.with_opacity(0.0, Colors.PRIMARY)],
                begin=ft.alignment.Alignment.TOP_CENTER,
                end=ft.alignment.Alignment.BOTTOM_CENTER,
            ),
        )
        # Línea punteada de referencia en el HR baseline (MEJORA 3) — un segundo LineChartData
        # plano en vez de alguna API de "línea horizontal" (flet_charts no tiene una: ver
        # dir(flet_charts), no expone nada tipo ChartHorizontalLine). Arranca vacía porque
        # todavía no hay baseline calculado; _actualizar_controles_en_vivo_real() la llena
        # una vez que self._hr_baseline_vivo tiene valor.
        self.serie_baseline_hr = fc.LineChartData(
            points=[],
            color=ft.Colors.with_opacity(0.35, Colors.TEXT_SECONDARY),
            stroke_width=1.5,
            dash_pattern=[6, 4],
            point=False,
            curved=False,
        )
        self.grafico_hr = fc.LineChart(
            data_series=[self.serie_hr, self.serie_baseline_hr],
            min_y=40,
            max_y=140,
            height=160,
            left_axis=fc.ChartAxis(show_labels=True, label_size=36, show_min=False, show_max=False),
            bottom_axis=fc.ChartAxis(show_labels=False),
            horizontal_grid_lines=fc.ChartGridLines(interval=20, color=Colors.BORDER),
            interactive=False,
        )

        def _tarjeta(contenido: ft.Control, expand: int = 1) -> ft.Control:
            return ft.Container(
                expand=expand,
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                shadow=Shadows.SM,
                content=contenido,
            )

        self._segmentos_bloque: dict[str, ft.Container] = {}

        def _barra_segmentada() -> ft.Control:
            """Un segmento por bloque del protocolo real — ver MEJORA 2. Ancho proporcional
            a duracion_seg (expand=int, flex de Flet), no todos iguales."""
            if not self.protocolo_activo:
                return self.barra_progreso_sesion  # fallback defensivo, no debería pasar
            segmentos = []
            for bloque in self.protocolo_activo:
                seg = ft.Container(
                    expand=max(1, int(bloque["duracion_seg"])),
                    height=8,
                    border_radius=4,
                    bgcolor=Colors.BORDER,
                    opacity=1,
                    animate=Motion.NORMAL,
                    animate_opacity=Motion.NORMAL,
                )
                self._segmentos_bloque[bloque["nombre"]] = seg
                segmentos.append(seg)
            return ft.Row(spacing=2, controls=segmentos)

        return ft.Column(
            expand=True,
            spacing=Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Row(
                    spacing=Spacing.SM,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(
                            spacing=Spacing.SM,
                            controls=[
                                StatusPill(
                                    "participante",
                                    f"{self.participante_actual['id_participante']} · "
                                    f"{self.participante_actual['edad']} años · "
                                    f"{_GENERO_LEGIBLE.get(self.participante_actual['genero'], '—')}",
                                    Colors.PRIMARY,
                                ),
                                StatusPill("modo", " · ".join(modo_texto), Colors.SECONDARY),
                            ],
                        ),
                        indicador_senal if indicador_senal is not None else ft.Container(),
                    ],
                ),
                # --- "Cockpit": corazón+label a la izquierda, 2 timers (bloque/sesión) a la
                # derecha, barra segmentada abajo (ver MEJORA 1 y 2). ---
                ft.Container(
                    padding=ft.padding.Padding.symmetric(vertical=Spacing.LG),
                    content=ft.Column(
                        spacing=Spacing.SM,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Row(
                                        spacing=Spacing.SM,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            self._icono_pulso,
                                            ft.Text(spans=[ft.TextSpan("HR EN VIVO", style=Typography.LABEL)]),
                                        ],
                                    ),
                                    ft.Column(
                                        spacing=0,
                                        horizontal_alignment=ft.CrossAxisAlignment.END,
                                        controls=[
                                            ft.Row(
                                                spacing=Spacing.XS,
                                                controls=[
                                                    ft.Text("Bloque:", size=12, color=Colors.TEXT_SECONDARY),
                                                    self.texto_timer_bloque,
                                                ],
                                            ),
                                            ft.Row(
                                                spacing=Spacing.XS,
                                                controls=[
                                                    ft.Text("Sesión:", size=11, color=Colors.TEXT_SECONDARY),
                                                    self.texto_timer_sesion,
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            _barra_segmentada(),
                        ],
                    ),
                ),
                _tarjeta(
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Column(
                                spacing=Spacing.XS,
                                controls=[
                                    ft.Row(
                                        spacing=Spacing.SM,
                                        controls=[
                                            ft.Icon(ft.Icons.GRAPHIC_EQ, color=Colors.PRIMARY, size=20),
                                            self.texto_estimulo_actual,
                                        ],
                                    ),
                                    self.texto_bloque_siguiente,
                                ],
                            ),
                            # MEJORA 4: el disclaimer largo pasa a un tooltip — mismo texto,
                            # visible al pasar el mouse, no como bloque de texto permanente.
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE,
                                color=Colors.TEXT_SECONDARY,
                                size=18,
                                tooltip=(
                                    "La sesión no se puede pausar ni saltar bloques: los 3 flujos de "
                                    "datos (sensor, micrófono, estímulos) están sincronizados por un "
                                    "único reloj compartido, igual que en sesion_completa.py."
                                ),
                            ),
                        ],
                    )
                ),
                ft.Row(
                    spacing=Spacing.LG,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        _tarjeta(
                            ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=Spacing.SM,
                                controls=[
                                    ft.Text(spans=[ft.TextSpan("HR ACTUAL", style=Typography.LABEL)]),
                                    ft.Stack(
                                        alignment=ft.alignment.Alignment.CENTER,
                                        controls=[
                                            self._anillo_hr,
                                            ft.Column(
                                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                                spacing=0,
                                                tight=True,
                                                controls=[self.texto_hr_actual, ft.Text("bpm", size=12, color=Colors.TEXT_SECONDARY)],
                                            ),
                                        ],
                                    ),
                                    # MEJORA 6: comparación contra el baseline de ESTA sesión.
                                    self.texto_comparacion_baseline,
                                    # MEJORA 7: chip de zona.
                                    self._chip_zona_hr,
                                ],
                            )
                        ),
                        _tarjeta(
                            ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    ft.Text(spans=[ft.TextSpan("VARIABILIDAD (HRV)", style=Typography.LABEL)]),
                                    # No se arma con MetricBadge(): ese helper crea su propio ft.Text
                                    # interno a partir de un valor fijo, y acá self.texto_sdnn_actual/
                                    # self.texto_rmssd_actual necesitan ser los controles reales que
                                    # _actualizar_controles_en_vivo_real() mute en cada tick — si se
                                    # envolvieran en MetricBadge, las actualizaciones caerían en un
                                    # ft.Text huérfano que nunca llegó a la página.
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text(spans=[ft.TextSpan("SDNN (~60s)", style=Typography.LABEL)]),
                                            ft.Row(
                                                spacing=4,
                                                vertical_alignment=ft.CrossAxisAlignment.END,
                                                controls=[self.texto_sdnn_actual, ft.Text("ms", size=13, color=Colors.TEXT_SECONDARY)],
                                            ),
                                        ],
                                    ),
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text(spans=[ft.TextSpan("RMSSD (~60s)", style=Typography.LABEL)]),
                                            ft.Row(
                                                spacing=4,
                                                vertical_alignment=ft.CrossAxisAlignment.END,
                                                controls=[self.texto_rmssd_actual, ft.Text("ms", size=13, color=Colors.TEXT_SECONDARY)],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            expand=1,
                        ),
                        _tarjeta(
                            ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    ft.Text(spans=[ft.TextSpan("RESPIRACIÓN", style=Typography.LABEL)]),
                                    ft.Row(
                                        spacing=Spacing.SM,
                                        controls=[
                                            IconCircle(ft.Icons.AIR, ft.Colors.with_opacity(0.12, Colors.ACCENT), Colors.ACCENT, tamaño=36),
                                            self.texto_respiraciones,
                                        ],
                                    ),
                                ],
                            ),
                            expand=1,
                        ),
                        # MEJORA 10: solo tiene sentido con sensor real — con el simulador,
                        # texto_latidos_capturados ya arranca en "N/D en modo simulado" y
                        # nunca se muta (ver _actualizar_controles_en_vivo_real).
                        _tarjeta(
                            ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    ft.Text(spans=[ft.TextSpan("LATIDOS CAPTURADOS", style=Typography.LABEL)]),
                                    self.texto_latidos_capturados,
                                    self.texto_ultimos_rr,
                                ],
                            ),
                            expand=1,
                        ),
                    ],
                ),
                _tarjeta(
                    ft.Column(
                        spacing=Spacing.SM,
                        controls=[
                            ft.Text(spans=[ft.TextSpan("FRECUENCIA CARDÍACA — ÚLTIMOS 30 PUNTOS", style=Typography.LABEL)]),
                            self.grafico_hr,
                        ],
                    )
                ),
            ],
        )

    def _al_cancelar_espera_sentado(self, e: ft.ControlEvent) -> None:
        """Botón "Cancelar sesión" del panel "Esperando a que se siente" (ver
        _vista_sesion_en_vivo). Solo tiene efecto MIENTRAS self.esperando_sentado es
        True — _hilo_orquestador() revisa este Event cada 0.5s dentro de
        UnityOSC.esperar_confirmacion_sentado() (ver ese docstring)."""
        self._evento_cancelar_espera_sentado.set()
        self._mostrar_snack(SnackBarExito("Cancelando sesión..."))

    def _iniciar_captura(self) -> None:
        """Lanza _hilo_orquestador() en un hilo aparte para no bloquear la UI durante ~8 minutos."""
        self.hilo_orquestador = threading.Thread(
            target=self._hilo_orquestador, args=(self.participante_actual["id_participante"],), daemon=True
        )
        self.hilo_orquestador.start()

    def _hilo_orquestador(self, participante_id: str) -> None:
        """Corre estabilización + captura real/simulada, reutilizando las piezas de sesion_completa.py.

        Ver CAPTURA REAL en el docstring del módulo para el porqué de este
        diseño (por qué no se llama ejecutar_sesion_completa() directo, por
        qué no hay pausa/saltar). Al terminar, deja resultado_metricas_sesion
        listo y navega a la Vista 3 (Cuestionario, primer bloque de estímulo).
        """
        hilo_ble: Optional[HiloSensorBLE] = None
        try:
            fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")
            reproductor = ReproductorEstimulos()
            protocolo = obtener_protocolo_sesion_dia(
                self.tipo_estimulo_sesion,
                duracion_baseline_seg=DURACION_BASELINE_SEG,
                duracion_estimulo_seg=DURACION_ESTIMULO_SEG,
                duracion_cierre_seg=DURACION_CIERRE_SEG,
                usar_vr=self.usar_vr,
            )
            if self.reproducir_audio_real:
                # Día 2, Día 4 y (si corresponde) Día 5 usan la MISMA canción —
                # ya no hay una segunda ruta distinta por día (ver PROTOCOLO
                # EXPERIMENTAL FINAL en sesion_completa.py).
                preferencia_wav = Path(self.ruta_preferencia_wav) if self.ruta_preferencia_wav else None
                protocolo = _resolver_audio_real(protocolo, preferencia_wav)
            self.duracion_total_protocolo = _calcular_duracion_total_protocolo(protocolo)
            # Mismos nombre/duracion_seg que el self.protocolo_activo ya calculado en
            # _al_registrar_participante() (ver ahí el porqué) — se reasigna acá con la
            # versión real (post _resolver_audio_real) por si alguna vez difiere.
            self.protocolo_activo = protocolo

            # --- VR (Meta Quest 2) — ver vr/unity_osc.py. unity_osc queda en None si
            # usar_vr=False: el resto de esta función no cambia de comportamiento en ese
            # caso (default), ni un hilo/objeto de más. ---
            unity_osc: Optional[UnityOSC] = None
            unity_avisado = False
            if self.usar_vr:
                unity_osc = UnityOSC()
                unity_avisado = unity_osc.iniciar_sesion(participante_id)
                if not unity_avisado:
                    logger.warning(
                        f"No se pudo avisarle a Unity que arrancó la sesión de {participante_id} "
                        "(¿está la escena corriendo?) — la sesión continúa igual, sin VR."
                    )

            if self.usar_sensor_real:
                sensor = SensorWahoo()
                hilo_ble = HiloSensorBLE(sensor)
                hilo_ble.iniciar()  # bloquea hasta conectar; propaga si falla
            else:
                sensor = SimuladorCardiaco()
            self.sensor_captura = sensor

            captura_sesion = CapturaSesion(sensor=sensor, participante_id=participante_id, frecuencia_hz=1.0)

            captura_audio = None
            try:
                candidata = CapturaAudio()
                info = candidata.get_dispositivo_info()
                if info["canales_entrada"] > 0:
                    captura_audio = candidata
            except Exception as error:
                logger.warning(f"Sin micrófono disponible ({error}); la sesión sigue sin grabar audio.")

            # --- Interacción embebida (ver INTERACCIÓN EMBEBIDA en el docstring de
            # sesion_completa.py): el participante camina libremente por el entorno VR
            # con los dos joysticks hasta sentarse; recién ahí arranca la estabilización
            # (que exige que ya esté quieto) y el protocolo real. Sensor y micrófono ya
            # están conectados ANTES de esta espera (el chest strap se lo puso antes de
            # ponerse el casco), así que no hay tiempo de hardware desperdiciado
            # esperando. Sin límite de tiempo por diseño: el investigador cancela a mano
            # con el botón de la Vista en vivo si algo no anda (Unity caído, participante
            # tarda demasiado), en vez de que esto se corte solo por un timeout arbitrario. ---
            if self.usar_vr and unity_avisado:
                self.esperando_sentado = True
                self._navegar(2)  # re-renderiza la Vista 2 mostrando el panel de espera
                confirmado = unity_osc.esperar_confirmacion_sentado(cancelar=self._evento_cancelar_espera_sentado)
                self.esperando_sentado = False
                self._navegar(2)  # vuelve a re-renderizar, ya con el cockpit normal
                if not confirmado:
                    if hilo_ble is not None:
                        hilo_ble.detener()
                    raise RuntimeError(
                        "Sesión cancelada: no se confirmó que el participante se sentó "
                        "(cancelada a mano, o Unity dejó de responder)."
                    )

            _ejecutar_estabilizacion(sensor, 30)

            resultado: dict = {"metadata_audio": None}
            estado_compartido: dict = {"estimulo_actual": protocolo[0]["nombre"]}
            lock = threading.Lock()
            t0 = time.monotonic()
            self.estado_compartido_captura = estado_compartido
            self.t0_captura = t0

            silencioso_efectivo = not self.reproducir_audio_real

            hilos = [
                threading.Thread(
                    target=_hilo_sensor, args=(captura_sesion, t0, fecha_hora, estado_compartido, resultado, lock), name="sensor"
                ),
                threading.Thread(
                    target=_hilo_estimulos,
                    args=(reproductor, protocolo, t0, estado_compartido, resultado, lock, silencioso_efectivo, self.usar_vr, unity_osc),
                    name="estimulos",
                ),
            ]
            if captura_audio is not None:
                hilos.append(
                    threading.Thread(
                        target=_hilo_audio,
                        args=(captura_audio, self.duracion_total_protocolo, participante_id, t0, fecha_hora, resultado, lock),
                        name="audio",
                    )
                )

            for hilo in hilos:
                hilo.start()

            # Polling en vivo: mientras los 3 hilos reales corren, esta UI solo LEE su
            # estado (estado_compartido, sensor.hr_bpm_actual) — nunca llama a leer()
            # ni toca nada que esos hilos estén escribiendo, para no interferir con la
            # captura real (ver CAPTURA REAL en el docstring del módulo).
            while any(hilo.is_alive() for hilo in hilos):
                time.sleep(1)
                try:
                    self._actualizar_controles_en_vivo_real()
                except Exception as error:
                    logger.error(f"Error actualizando la vista en vivo: {error}")

            for hilo in hilos:
                hilo.join()

            if unity_osc is not None:
                unity_osc.terminar_sesion()

            if hilo_ble is not None:
                time.sleep(2.5)
                hilo_ble.detener()
                hilo_ble = None

            if "ruta_csv" not in resultado or "eventos" not in resultado:
                raise RuntimeError(
                    f"La captura no terminó correctamente: {resultado.get('error_sensor') or resultado.get('error_estimulos')}"
                )

            ruta_json_estimulos = CARPETA_SESIONES / f"{participante_id}_estimulos_{fecha_hora}.json"
            reproductor.guardar_eventos(
                resultado["eventos"],
                ruta_json_estimulos,
                metadata={"tiempo_estabilizacion_seg": 30, "estabilizacion_completada": True},
            )
            ruta_wav = Path(resultado["metadata_audio"]["ruta_wav"]) if resultado["metadata_audio"] is not None else None

            self.estado_compartido_captura["estimulo_actual"] = "analizando"
            # generar_grafica=True: produce la misma gráfica de 4 paneles que
            # analizar_sesion.py ya generaba trabajando sin la interfaz (HR en el
            # tiempo, R-R en el tiempo, distribución por condición, HRV por bloque) —
            # se reutiliza tal cual (AnalisisSesion.graficar_sesion()), no se reinventa.
            # Se embebe en el reporte PDF (ver _generar_reporte_pdf()).
            self.resultado_metricas_sesion = analizar_metricas_sesion(
                participante_id=participante_id,
                ruta_csv=resultado["ruta_csv"],
                ruta_wav=ruta_wav,
                ruta_json_eventos=ruta_json_estimulos,
                generar_grafica=True,
            )
            self.duracion_total_real_sesion = time.monotonic() - t0
            self.captura_terminada = True
            self._navegar(3)  # primer cuestionario post-hoc

        except Exception as error:
            logger.error(f"Error en la captura de sesión: {error}")
            self.error_captura = str(error)
            self.esperando_sentado = False
            if hilo_ble is not None:
                try:
                    hilo_ble.detener()
                except Exception:
                    pass
            self._navegar(2)  # re-renderiza la Vista 2, que ahora muestra el error

    @staticmethod
    def _peek_hr(sensor) -> Optional[float]:
        """Lee el último HR conocido SIN consumir nada (ni llamar a leer()).

        SensorWahoo expone hr_bpm_actual; SimuladorCardiaco expone hr_actual
        (ver docstring del módulo para por qué nunca se llama a sensor.leer()
        desde acá).
        """
        valor = getattr(sensor, "hr_bpm_actual", None)
        if valor is None:
            valor = getattr(sensor, "hr_actual", None)
        return float(valor) if valor else None

    @staticmethod
    def _peek_hrv(sensor) -> Optional[tuple[float, float]]:
        """Calcula SDNN/RMSSD "en vivo" sobre los últimos ~60 intervalos R-R ya recibidos.

        Solo funciona con SensorWahoo (expone rr_ms_queue, un deque que SOLO
        CRECE por notificaciones BLE — leerlo con slicing no consume ni
        interfiere con lo que _hilo_sensor está escribiendo al CSV).
        SimuladorCardiaco no expone un historial de R-R equivalente sin
        interferir con su propio filtro exponencial (ver _peek_hr), así que
        en modo simulado esto siempre da None — no se inventa un valor.

        Es una estimación aproximada ("los últimos 60 intervalos", no
        exactamente los últimos 60 segundos de reloj) — el valor correcto,
        segmentado por bloque, lo calcula analizar_metricas_sesion() al
        terminar la sesión.

        Returns:
            Optional[tuple[float, float]]: (sdnn_ms, rmssd_ms), o None si no
                hay sensor real o todavía no llegaron suficientes R-R (<3).
        """
        cola = getattr(sensor, "rr_ms_queue", None)
        if not cola or len(cola) < 3:
            return None
        import numpy as np

        rr = np.array(list(cola)[-60:], dtype=float)
        sdnn = float(np.std(rr, ddof=1))
        rmssd = float(np.sqrt(np.mean(np.diff(rr) ** 2)))
        return sdnn, rmssd

    @staticmethod
    def _formato_mmss(segundos) -> str:
        m, s = divmod(int(max(0, segundos)), 60)
        return f"{m:02d}:{s:02d}"

    def _actualizar_controles_en_vivo_real(self) -> None:
        """Refresca timers, barra segmentada, HR/HRV, sparkline, señal BLE y latidos
        durante la captura real/simulada — llamado 1 vez por segundo desde el bucle de
        polling de _hilo_orquestador() (ver ese método: nunca llama a sensor.leer() ni
        toca nada que los 3 hilos de captura estén escribiendo, solo lee/peek)."""
        if self.t0_captura is None:
            return  # todavía en estabilización

        transcurrido_sesion = time.monotonic() - self.t0_captura

        nombre_bloque = self.estado_compartido_captura.get("estimulo_actual", "—")
        indice_bloque = next(
            (i for i, b in enumerate(self.protocolo_activo) if b["nombre"] == nombre_bloque),
            len(self.protocolo_activo),
        )

        # --- MEJORA 1: timer de bloque + timer de sesión, MM:SS/MM:SS ---
        if indice_bloque < len(self.protocolo_activo):
            duracion_bloque = self.protocolo_activo[indice_bloque]["duracion_seg"]
            offset_bloque = sum(b["duracion_seg"] for b in self.protocolo_activo[:indice_bloque])
            transcurrido_bloque = min(duracion_bloque, transcurrido_sesion - offset_bloque)
        else:
            duracion_bloque = 0
            transcurrido_bloque = 0
        self.texto_timer_bloque.value = f"{self._formato_mmss(transcurrido_bloque)} / {self._formato_mmss(duracion_bloque)}"
        self.texto_timer_sesion.value = (
            f"{self._formato_mmss(transcurrido_sesion)} / {self._formato_mmss(self.duracion_total_protocolo)}"
        )

        # Fallback defensivo (protocolo_activo vacío, no debería pasar — ver
        # _barra_segmentada()): mantiene la barra continua vieja funcionando igual.
        if self.duracion_total_protocolo:
            self.barra_progreso_sesion.value = min(1.0, transcurrido_sesion / self.duracion_total_protocolo)

        # --- MEJORA 2: barra segmentada — verde lo ya corrido, indigo pulsando el actual,
        # gris lo que falta. El "pulso" reusa el mismo ping-pong ya usado en el corazón. ---
        for i, bloque in enumerate(self.protocolo_activo):
            segmento = self._segmentos_bloque.get(bloque["nombre"])
            if segmento is None:
                continue
            if i < indice_bloque:
                segmento.bgcolor = Colors.SUCCESS
                segmento.opacity = 1
            elif i == indice_bloque:
                segmento.bgcolor = Colors.PRIMARY
                segmento.opacity = 0.6 if segmento.opacity == 1 else 1
            else:
                segmento.bgcolor = Colors.BORDER
                segmento.opacity = 1

        # --- MEJORA 5: bloque actual + siguiente, con etiquetas legibles ---
        self.texto_estimulo_actual.value = f"Bloque actual: {_ETIQUETAS_BLOQUE.get(nombre_bloque, nombre_bloque)}"
        if indice_bloque + 1 < len(self.protocolo_activo):
            siguiente = self.protocolo_activo[indice_bloque + 1]["nombre"]
            self.texto_bloque_siguiente.value = f"Siguiente: {_ETIQUETAS_BLOQUE.get(siguiente, siguiente)}"
        else:
            self.texto_bloque_siguiente.value = "Fin de sesión"

        hr = self._peek_hr(self.sensor_captura)
        if hr:
            color_hr = self._color_por_hr(hr)
            self.texto_hr_actual.value = f"{hr:.0f}"
            self.texto_hr_actual.color = color_hr
            self.hr_historial.append(hr)
            self.hr_historial = self.hr_historial[-30:]
            self.serie_hr.points = [fc.LineChartDataPoint(x=i, y=valor) for i, valor in enumerate(self.hr_historial)]

            # MEJORA 3: eje Y adaptativo sobre los últimos 30 puntos (antes 40-140 fijo,
            # que aplanaba visualmente un HR estable — ver el pedido original).
            self.grafico_hr.min_y = min(self.hr_historial) - 5
            self.grafico_hr.max_y = max(self.hr_historial) + 5

            # Gauge circular decorativo (ver _vista_sesion_en_vivo) — normaliza el mismo
            # HR ya calculado sobre el rango fijo 40-140bpm (a propósito NO el eje
            # adaptativo de arriba: el gauge necesita un rango estable para no saltar).
            anillo = self._anillo_hr
            anillo.value = max(0.0, min(1.0, (hr - 40) / 100))
            anillo.color = color_hr

            # Baseline "en vivo" aproximado (promedio de HR durante el bloque baseline) —
            # ver docstring de self._hr_baseline_vivo en __init__: es una estimación de UI,
            # no el baseline oficial que analizar_metricas_sesion() calcula post-hoc.
            if nombre_bloque == "baseline":
                self._hr_baseline_muestras.append(hr)
            elif self._hr_baseline_muestras and self._hr_baseline_vivo is None:
                self._hr_baseline_vivo = sum(self._hr_baseline_muestras) / len(self._hr_baseline_muestras)

            # MEJORA 6: comparación contra ese baseline en vivo.
            if self._hr_baseline_vivo is None:
                self.texto_comparacion_baseline.value = "Calculando baseline..."
                self.texto_comparacion_baseline.color = Colors.TEXT_SECONDARY
                self.serie_baseline_hr.points = []
            else:
                diferencia = hr - self._hr_baseline_vivo
                flecha = "↓" if diferencia < 0 else ("↑" if diferencia > 0 else "→")
                color_diferencia = Colors.SUCCESS if diferencia < 0 else (Colors.DANGER if diferencia > 0 else Colors.TEXT_SECONDARY)
                self.texto_comparacion_baseline.value = (
                    f"{flecha} {diferencia:+.0f} bpm vs baseline ({self._hr_baseline_vivo:.0f})"
                )
                self.texto_comparacion_baseline.color = color_diferencia
                # Línea punteada plana a la altura del baseline, mismo largo que la serie de HR.
                self.serie_baseline_hr.points = [
                    fc.LineChartDataPoint(x=i, y=self._hr_baseline_vivo) for i in range(len(self.hr_historial))
                ]

            # MEJORA 7: chip de zona.
            etiqueta_zona, color_zona = _zona_hr(hr)
            self._texto_zona_hr.value = etiqueta_zona
            self._texto_zona_hr.color = color_zona
            self._punto_zona_hr.bgcolor = color_zona
            self._chip_zona_hr.bgcolor = ft.Colors.with_opacity(0.10, color_zona)

            # MEJORA 9: si el HR peek cambió respecto al tick anterior, la señal está viva —
            # resetea el cronómetro de "hace cuánto no cambia" (ver _calidad_senal()).
            if hr != self._ultimo_hr_valor:
                self._ultimo_hr_valor = hr
                self._ultimo_hr_cambio_ts = time.monotonic()

        # MEJORA 8: el corazón pulsa al tempo del HR real (medio ciclo = 60000/hr/2 ms);
        # en estabilización (hr todavía None/0) usa el tempo estándar de 60bpm.
        intervalo_medio_ms = max(150, int(30_000 / hr)) if hr else 500
        self._icono_pulso.animate_scale = ft.Animation(duration=intervalo_medio_ms, curve=ft.AnimationCurve.EASE_IN_OUT)
        self._icono_pulso.scale = 1.15 if self._icono_pulso.scale == 1.0 else 1.0

        # MEJORA 9: barras de señal — solo tienen sentido con sensor real.
        if self.usar_sensor_real and self._barras_senal:
            segundos_sin_cambio = (
                time.monotonic() - self._ultimo_hr_cambio_ts if self._ultimo_hr_cambio_ts is not None else 999
            )
            n_barras, color_senal, etiqueta_senal = _calidad_senal(segundos_sin_cambio)
            for i, barra in enumerate(self._barras_senal):
                barra.bgcolor = color_senal if i < n_barras else Colors.BORDER
            self.texto_calidad_senal.value = f"Señal Wahoo: {etiqueta_senal}"
            self.texto_calidad_senal.color = color_senal

        hrv = self._peek_hrv(self.sensor_captura)
        if hrv is not None:
            sdnn, rmssd = hrv
            self.texto_sdnn_actual.value = f"{sdnn:.1f}"
            self.texto_rmssd_actual.value = f"{rmssd:.1f}"

        # MEJORA 10: latidos capturados — mismo self.sensor_captura.rr_ms_queue que ya
        # usa _peek_hrv(), leído sin consumir (ver ese método). Con simulador no se toca:
        # el texto ya arranca en "N/D en modo simulado" (ver _vista_sesion_en_vivo).
        if self.usar_sensor_real:
            cola = getattr(self.sensor_captura, "rr_ms_queue", None)
            if cola:
                self.texto_latidos_capturados.value = f"{len(cola):,}"
                ultimos_rr = list(cola)[-5:]
                self.texto_ultimos_rr.value = "Últimos R-R: " + ", ".join(f"{v:.0f}" for v in ultimos_rr) + " ms"

        self._actualizar_pagina_segura()

    @staticmethod
    def _color_por_hr(hr: float) -> str:
        """Verde en rango normal de reposo, amarillo cerca de los límites, rojo fuera de rango."""
        if hr < 55 or hr > 100:
            return Colors.DANGER
        if hr < 60 or hr > 90:
            return Colors.WARNING
        return Colors.SUCCESS

    # =================================================================
    # VISTA 3: CUESTIONARIO LIKERT
    # =================================================================

    def _metricas_de_bloque(self, nombre_bloque: str) -> Optional[dict]:
        """Busca la fila de tabla_combinada correspondiente a nombre_bloque, si ya hay
        una sesión analizada (ver resultado_metricas_sesion, _hilo_orquestador)."""
        if self.resultado_metricas_sesion is None:
            return None
        tabla = self.resultado_metricas_sesion["tabla_combinada"]
        fila = tabla.loc[tabla["estimulo"] == nombre_bloque]
        return fila.iloc[0].to_dict() if not fila.empty else None

    def _vista_cuestionario(self) -> ft.Control:
        """Cuestionario post-estímulo (Likert + preferencia) del ÚNICO bloque de estímulo
        de esta sesión (self.bloques_estimulo_sesion, ver PROTOCOLO POR DÍA en el
        docstring del módulo) — se muestra DESPUÉS de que termina toda la captura real
        (ver CAPTURA REAL en el docstring del módulo)."""
        if self.participante_actual is None or self.resultado_metricas_sesion is None:
            return EmptyState(
                ft.Icons.ASSIGNMENT_OUTLINED,
                "Todavía no hay una sesión analizada para responder",
                "El cuestionario aparece automáticamente al terminar la captura completa.",
                accion=GradientButton("Ir a Nueva sesión", on_click=lambda e: self._navegar(1), icono=ft.Icons.ARROW_FORWARD),
            )

        bloque = self.bloques_estimulo_sesion[self.indice_pregunta_actual]
        metricas_bloque = self._metricas_de_bloque(bloque["nombre"])
        if metricas_bloque is not None and not math.isnan(metricas_bloque.get("hr_media", float("nan"))):
            subtitulo_metricas = f"HR promedio registrada en este bloque: {metricas_bloque['hr_media']:.1f} bpm"
        else:
            subtitulo_metricas = "Sin datos de HR válidos para este bloque (ver el reporte para más detalle)."

        self.likert_relajacion = SelectorLikert("¿Qué tan RELAJADA te sentiste?", "Nada relajada", "Muy relajada")
        self.likert_confort = SelectorLikert("¿Qué tan CÓMODA te sentiste?", "Muy incómoda", "Muy cómoda")

        self.chip_preferencia_seleccionado = None
        self.chips_preferencia = {}
        opciones_preferencia = [
            ("no_me_gusto", "😞 No me gustó"),
            ("neutral", "😐 Neutral"),
            ("me_gusta", "🙂 Me gusta"),
            ("me_gusta_mucho", "😍 Me gusta mucho"),
        ]
        chips_controles = []
        for valor, etiqueta in opciones_preferencia:
            chip = ft.Chip(
                label=ft.Text(etiqueta, size=13, weight=ft.FontWeight.W_600),
                selected=False,
                on_select=self._crear_handler_chip(valor),
                shape=ft.StadiumBorder(),
                bgcolor=Colors.BG_MAIN,
                selected_color=ft.Colors.with_opacity(0.15, Colors.PRIMARY),
                check_color=Colors.PRIMARY,
                padding=ft.padding.Padding.symmetric(vertical=Spacing.SM, horizontal=Spacing.MD),
                select_animation_style=ft.AnimationStyle(duration=Motion.FAST.duration, curve=ft.AnimationCurve.EASE_OUT),
            )
            self.chips_preferencia[valor] = chip
            chips_controles.append(chip)

        self.campo_comentarios = ft.TextField(
            label="Comentarios (opcional)",
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )

        progreso = (self.indice_pregunta_actual) / len(self.bloques_estimulo_sesion)

        return ft.Container(
            expand=True,
            gradient=ft.LinearGradient(
                colors=[Colors.BG_MAIN, ft.Colors.with_opacity(0.5, Colors.SECONDARY)],
                begin=ft.alignment.Alignment.TOP_LEFT,
                end=ft.alignment.Alignment.BOTTOM_RIGHT,
            ),
            # Bug real reportado: con alignment=CENTER en este Container (como estaba antes),
            # cuando el contenido (2 sliders + 4 chips + comentarios + botón) es más alto que
            # la ventana, se recorta arriba/abajo sin ninguna forma de hacer scroll — el
            # investigador no podía llegar al botón "Guardar y continuar". Un Column con
            # scroll=AUTO como hijo directo del Container resuelve esto: cuando el contenido
            # entra, horizontal_alignment lo sigue centrando horizontalmente igual que antes;
            # cuando no entra, se puede scrollear en vez de perderse. Los dos Container(height=)
            # de arriba/abajo reemplazan el centrado vertical que daba alignment=CENTER (una
            # Column con scroll no soporta centrado vertical real — ver MainAxisAlignment vs.
            # scroll en Flet/Flutter).
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(height=Spacing.XL),
                    ft.Container(
                        width=600,
                        # GlassCard (glassmorphism): esta es la única tarjeta de la app que se ve
                        # sobre un fondo con degradado propio en vez del bg plano de la página, así
                        # que es el lugar natural para el efecto "vidrio esmerilado" (ver limitación
                        # de blur=/Stack documentada en GlassCard, componentes.py).
                        content=GlassCard(
                            ft.Column(
                                spacing=Spacing.MD,
                                controls=[
                                    ft.Column(
                                        spacing=Spacing.XS,
                                        controls=[
                                            ft.Text(
                                                spans=[
                                                    ft.TextSpan(
                                                        f"ESTÍMULO {self.indice_pregunta_actual + 1} DE {len(self.bloques_estimulo_sesion)}",
                                                        style=Typography.LABEL,
                                                    )
                                                ]
                                            ),
                                            ft.ProgressBar(
                                                value=progreso, color=Colors.PRIMARY, bgcolor=Colors.BORDER, border_radius=Radius.CHIP
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=Spacing.SM,
                                        controls=[
                                            ft.Text(bloque["icono"], size=30),
                                            ft.Text(spans=[ft.TextSpan(bloque["titulo"], style=Typography.H2)]),
                                        ],
                                    ),
                                    ft.Text(spans=[ft.TextSpan(subtitulo_metricas, style=Typography.BODY_SECONDARY)]),
                                    ft.Divider(color=Colors.BORDER),
                                    self.likert_relajacion.build(),
                                    self.likert_confort.build(),
                                    ft.Text("¿Te gustó este sonido?", size=15, weight=ft.FontWeight.W_600),
                                    ft.Row(wrap=True, spacing=Spacing.SM, controls=chips_controles),
                                    self.campo_comentarios,
                                    GradientButton(
                                        "Guardar y continuar", on_click=self._al_guardar_cuestionario, icono=ft.Icons.ARROW_FORWARD
                                    ),
                                ],
                            ),
                        ),
                    ),
                    ft.Container(height=Spacing.XL),
                ],
            ),
        )

    def _crear_handler_chip(self, valor: str):
        """Fábrica de handlers on_select: hace que los 4 chips de preferencia sean mutuamente excluyentes."""

        def handler(e: ft.ControlEvent) -> None:
            for clave, chip in self.chips_preferencia.items():
                chip.selected = clave == valor
            self.chip_preferencia_seleccionado = valor
            self._actualizar_pagina_segura()

        return handler

    def _al_guardar_cuestionario(self, e: ft.ControlEvent) -> None:
        """Guarda la respuesta del bloque actual EN MEMORIA (respuestas_cuestionario) y
        avanza. Recién al responder el ÚLTIMO bloque se escribe todo a SQL Server de una
        sola vez (ver _finalizar_sesion) — self.bloques_estimulo_sesion tiene un único
        elemento (protocolo por día, ver PROTOCOLO POR DÍA en el docstring del módulo),
        así que en la práctica esto se resuelve en una sola vuelta, pero el loop queda
        genérico por si algún día se corre un protocolo con más de un estímulo."""
        bloque = self.bloques_estimulo_sesion[self.indice_pregunta_actual]
        self.respuestas_cuestionario[bloque["nombre"]] = {
            "preferencia": self.chip_preferencia_seleccionado,
            "likert_relajacion": self.likert_relajacion.valor,
            "likert_confort": self.likert_confort.valor,
        }

        if self.indice_pregunta_actual + 1 < len(self.bloques_estimulo_sesion):
            self.indice_pregunta_actual += 1
            self._navegar(3)
        else:
            self._finalizar_sesion()

    def _finalizar_sesion(self) -> None:
        """Tras el último cuestionario: guarda sesión + la prueba de esta sesión en SQL
        Server y navega a Análisis."""
        participante_id = self.participante_actual["id_participante"]
        id_sesion = self._guardar_en_sql_server(
            participante_id,
            self.resultado_metricas_sesion,
            self.duracion_total_real_sesion,
            respuestas_cuestionario=self.respuestas_cuestionario,
        )
        if id_sesion is not None:
            self._mostrar_snack(SnackBarExito(f"Sesión #{id_sesion} guardada en SQL Server."))
        else:
            self._mostrar_snack(SnackBarError("La sesión se capturó pero no se pudo guardar en SQL Server (ver logs)."))

        self.participante_actual = None
        self.resultado_metricas_sesion = None
        self._navegar(4)

    def _valor_o_none(self, fila, columna: str) -> Optional[float]:
        """Extrae fila[columna] como float nativo, o None si falta/es NaN (NULL para SQL Server)."""
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
        self,
        participante_id: str,
        resultado_metricas: dict,
        duracion_total_real: float,
        respuestas_cuestionario: Optional[dict] = None,
    ) -> Optional[int]:
        """Crea la fila de 'sesiones' y una fila de 'pruebas' por cada bloque de estímulo
        real (ver mapear_bloque_a_prueba()). El participante ya debe existir (se
        registra en _al_registrar_participante, antes de arrancar la captura).

        Args:
            participante_id: ID del participante (ya registrado).
            resultado_metricas: dict de analizar_metricas_sesion() (tabla_combinada, resumen_general).
            duracion_total_real: Respaldo si resumen_general no trae duracion_total_seg.
            respuestas_cuestionario: nombre_de_bloque -> {preferencia, likert_relajacion,
                likert_confort}, ver _al_guardar_cuestionario().

        Returns:
            Optional[int]: id_sesion creado, o None si falló.
        """
        if self.bd is None:
            logger.error("No hay conexión a SQL Server; la sesión no se guarda en base de datos.")
            return None

        try:
            tabla = resultado_metricas["tabla_combinada"]
            fila_baseline = tabla.loc[tabla["estimulo"] == "baseline"]
            hr_baseline = self._valor_o_none(fila_baseline.iloc[0], "hr_media") if not fila_baseline.empty else None
            sdnn_baseline = self._valor_o_none(fila_baseline.iloc[0], "sdnn") if not fila_baseline.empty else None
            rmssd_baseline = self._valor_o_none(fila_baseline.iloc[0], "rmssd") if not fila_baseline.empty else None

            id_sesion = self.bd.crear_sesion(
                participante_id,
                hr_baseline,
                rmssd_baseline,
                sdnn_baseline,
                notas="Registrado desde app_investigador.py",
                usa_vr=self.usar_vr,
                dia_sesion=self.dia_sesion,
            )
            if id_sesion is None:
                logger.error("No se pudo crear la fila de sesión en SQL Server.")
                return None

            duracion_total = resultado_metricas["resumen_general"].get("duracion_total_seg")
            duracion_final = self._valor_o_none({"d": duracion_total}, "d")
            self.bd.actualizar_duracion_sesion(id_sesion, int(duracion_final if duracion_final is not None else duracion_total_real))

            pruebas_guardadas = 0
            for _, fila in tabla.iterrows():
                info_prueba = mapear_bloque_a_prueba(fila["estimulo"])
                if info_prueba is None:
                    continue  # bloques de reposo/silencio: no son "pruebas"

                respuesta = (respuestas_cuestionario or {}).get(fila["estimulo"], {})
                metricas_dict = {
                    "hr_promedio": fila.get("hr_media"),
                    "hr_min": fila.get("hr_min"),
                    "hr_max": fila.get("hr_max"),
                    "rmssd": fila.get("rmssd"),
                    "sdnn": fila.get("sdnn"),
                    "pnn50": fila.get("pnn50"),
                    "resp_por_min": fila.get("respiraciones_min"),
                }
                duracion_bloque = self._valor_o_none(fila, "duracion_seg")

                id_prueba = self.bd.registrar_prueba(
                    id_sesion,
                    participante_id,
                    info_prueba["tipo_estimulo"],
                    info_prueba["frecuencia_hz"],
                    metricas_dict,
                    preferencia=respuesta.get("preferencia"),
                    likert_relajacion=respuesta.get("likert_relajacion"),
                    likert_confort=respuesta.get("likert_confort"),
                    duracion_seg=int(duracion_bloque) if duracion_bloque is not None else None,
                )
                if id_prueba is not None:
                    pruebas_guardadas += 1

            logger.info(f"Sesión guardada en SQL Server: id_sesion={id_sesion}, {pruebas_guardadas} prueba(s).")
            return id_sesion
        except Exception as error:
            logger.error(f"Error guardando en SQL Server: {error}")
            return None

    # =================================================================
    # VISTA 4: ANÁLISIS
    # =================================================================

    def _vista_analisis(self) -> ft.Control:
        """Dashboard de análisis con 5 "tabs" (implementados a mano, ver docstring del módulo)."""

        def boton_tab(clave: str, etiqueta: str, icono: str) -> ft.Control:
            activo = self._tab_analisis == clave
            return ft.Container(
                ink=True,
                on_click=lambda e, c=clave: self._cambiar_tab_analisis(c),
                border_radius=Radius.CHIP,
                padding=ft.padding.Padding.symmetric(vertical=Spacing.SM, horizontal=Spacing.MD),
                bgcolor=Colors.PRIMARY if activo else "transparent",
                animate=Motion.FAST,
                content=ft.Row(
                    spacing=Spacing.XS + 2,
                    tight=True,
                    controls=[
                        ft.Icon(icono, size=16, color=Colors.TEXT_ON_DARK if activo else Colors.TEXT_SECONDARY),
                        ft.Text(
                            etiqueta,
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=Colors.TEXT_ON_DARK if activo else Colors.TEXT_SECONDARY,
                        ),
                    ],
                ),
            )

        barra_tabs = ft.Container(
            padding=ft.padding.Padding.all(Spacing.XS),
            border_radius=Radius.CHIP,
            bgcolor=Colors.BG_CARD,
            shadow=Shadows.SM,
            content=ft.Row(
                spacing=Spacing.XS,
                wrap=True,
                controls=[
                    boton_tab("resumen", "Resumen General", ft.Icons.TABLE_CHART_OUTLINED),
                    boton_tab("comparacion", "Comparación de Estímulos", ft.Icons.BAR_CHART),
                    boton_tab("recomendacion", "Recomendación", ft.Icons.RECOMMEND_OUTLINED),
                    boton_tab("sql", "Consulta SQL", ft.Icons.CODE),
                    boton_tab("exportar", "Exportar", ft.Icons.DOWNLOAD),
                ],
            ),
        )

        return ft.Column(
            expand=True,
            spacing=Spacing.LG,
            controls=[
                SectionHeader("Análisis", "Resultados agregados de todas las sesiones en SQL Server"),
                barra_tabs,
                ft.Container(expand=True, content=self._construir_tab_actual()),
            ],
        )

    def _cambiar_tab_analisis(self, clave: str) -> None:
        """Cambia el tab activo y reconstruye la Vista 4 completa (simple, sin estados a medias)."""
        self._tab_analisis = clave
        self._navegar(4)

    def _construir_tab_actual(self) -> ft.Control:
        if self._tab_analisis == "resumen":
            return self._tab_resumen_general()
        if self._tab_analisis == "comparacion":
            return self._tab_comparacion_estimulos()
        if self._tab_analisis == "recomendacion":
            return self._tab_recomendacion()
        if self._tab_analisis == "sql":
            return self._tab_consulta_sql()
        return self._tab_exportar()

    # --- TAB A: Resumen General ---
    def _tab_resumen_general(self) -> ft.Control:
        """Tabla de participantes con N° de sesiones, filtrable por ID y ordenable."""
        if self.bd is None:
            return EmptyState(ft.Icons.CLOUD_OFF_OUTLINED, "Sin conexión a SQL Server", "Revisa que el servicio esté corriendo y las credenciales en .env.")
        try:
            participantes = self.bd.obtener_participantes()
            conteo = self.bd.ejecutar_query("SELECT id_participante, COUNT(*) AS n_sesiones FROM sesiones GROUP BY id_participante") or []
        except Exception as error:
            return EmptyState(ft.Icons.ERROR_OUTLINE, "Error consultando datos", str(error))

        mapa_conteo = {f["id_participante"]: f["n_sesiones"] for f in conteo}
        filas_base = [
            {
                "id": p["id_participante"],
                "edad": p["edad"] if p["edad"] is not None else -1,
                "genero": _GENERO_LEGIBLE.get(p["genero"], "—"),
                "fecha": p["fecha_registro"],
                "n_sesiones": mapa_conteo.get(p["id_participante"], 0),
            }
            for p in participantes
        ]

        campo_filtro = ft.TextField(
            label="Filtrar por ID",
            width=220,
            prefix_icon=ft.Icons.SEARCH,
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )
        selector_orden = ft.Dropdown(
            label="Ordenar por",
            width=200,
            value="id",
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
            options=[
                ft.dropdown.Option("id", "ID"),
                ft.dropdown.Option("edad", "Edad"),
                ft.dropdown.Option("fecha", "Fecha de registro"),
                ft.dropdown.Option("n_sesiones", "N° de sesiones"),
            ],
        )
        contenedor_tabla = ft.Container()

        def construir_tabla(filas: list[dict]) -> ft.DataTable:
            return ft.DataTable(
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                heading_row_color=Colors.BG_MAIN,
                heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
                data_text_style=ft.TextStyle(size=13, color=Colors.TEXT_PRIMARY),
                horizontal_lines=ft.border.BorderSide(1, Colors.BORDER),
                columns=[
                    ft.DataColumn(label=ft.Text("ID")),
                    ft.DataColumn(label=ft.Text("Edad"), numeric=True),
                    ft.DataColumn(label=ft.Text("Género")),
                    ft.DataColumn(label=ft.Text("Fecha registro")),
                    ft.DataColumn(label=ft.Text("N° sesiones"), numeric=True),
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(f["id"])),
                            ft.DataCell(ft.Text(str(f["edad"]) if f["edad"] >= 0 else "—")),
                            ft.DataCell(ft.Text(f["genero"])),
                            ft.DataCell(ft.Text(f["fecha"].strftime("%d/%m/%Y %H:%M") if f["fecha"] else "—")),
                            ft.DataCell(ft.Text(str(f["n_sesiones"]))),
                        ]
                    )
                    for f in filas
                ],
            )

        def refrescar(e: Optional[ft.ControlEvent] = None) -> None:
            texto = (campo_filtro.value or "").strip().upper()
            filtradas = [f for f in filas_base if texto in f["id"].upper()]
            clave = selector_orden.value or "id"
            filtradas.sort(key=lambda f: (f[clave] is None, f[clave]))
            contenedor_tabla.content = construir_tabla(filtradas)
            if contenedor_tabla.page is not None:
                self._actualizar_pagina_segura()

        campo_filtro.on_change = refrescar
        # ft.Dropdown en esta versión de Flet no tiene "on_change" (ver el mismo bug real
        # encontrado en selector_participante.on_select más abajo, en _tab_recomendacion) —
        # el evento correcto es "on_select". Asignar on_change no tira error (Python deja
        # setear cualquier atributo), pero el handler nunca se ejecuta.
        selector_orden.on_select = refrescar
        contenedor_tabla.content = construir_tabla(filas_base)

        return ft.Container(
            padding=ft.padding.Padding.all(Spacing.LG),
            border_radius=Radius.CARD,
            bgcolor=Colors.BG_CARD,
            shadow=Shadows.SM,
            content=ft.Column(
                spacing=Spacing.MD,
                scroll=ft.ScrollMode.AUTO,
                controls=[ft.Row(spacing=Spacing.SM, controls=[campo_filtro, selector_orden]), contenedor_tabla],
            ),
        )

    # --- TAB B: Comparación de Estímulos ---
    def _tab_comparacion_estimulos(self) -> ft.Control:
        """Barras de HR promedio y % de preferencia por tipo de estímulo, + tabla de estadísticas."""
        if self.bd is None:
            return EmptyState(ft.Icons.CLOUD_OFF_OUTLINED, "Sin conexión a SQL Server", "Revisa que el servicio esté corriendo y las credenciales en .env.")
        try:
            estadisticas = (
                self.bd.ejecutar_query(
                    """
                    SELECT tipo_estimulo,
                           AVG(hr_promedio) AS hr_media,
                           STDEV(hr_promedio) AS hr_desv,
                           COUNT(*) AS n,
                           SUM(CASE WHEN preferencia IN ('me_gusta', 'me_gusta_mucho') THEN 1 ELSE 0 END) AS n_preferido
                    FROM pruebas
                    GROUP BY tipo_estimulo
                    ORDER BY tipo_estimulo
                    """
                )
                or []
            )
        except Exception as error:
            return EmptyState(ft.Icons.ERROR_OUTLINE, "Error consultando estadísticas", str(error))

        if not estadisticas:
            return EmptyState(
                ft.Icons.BAR_CHART, "Todavía no hay pruebas registradas", "Corré al menos una sesión completa para ver comparaciones acá."
            )

        # Color fijo por tipo de estímulo (_COLOR_POR_TIPO_ESTIMULO), no por índice de fila —
        # así "solfeggio_isocronico" es siempre indigo sin importar en qué orden lo devuelva el GROUP BY.
        # Fallback a TEXT_SECONDARY para cualquier tipo_estimulo que no esté en el mapa (no
        # debería pasar dado _TIPOS_ESTIMULO en bd_sqlserver.py, pero no se rompe si pasa).
        def _color_estimulo(tipo: str) -> str:
            return _COLOR_POR_TIPO_ESTIMULO.get(tipo, Colors.TEXT_SECONDARY)

        etiquetas_eje = [fc.ChartAxisLabel(value=i, label=f["tipo_estimulo"]) for i, f in enumerate(estadisticas)]

        # show_min/show_max=True (el default de ChartAxis) fuerza una etiqueta EXTRA en el
        # valor mínimo/máximo exacto, además de las etiquetas normales por intervalo — con un
        # max_y no redondo (ej. 81.28...) esa etiqueta se ve rota/superpuesta (bug visto en
        # captura real de la app: "81.\n280" y "10\n0" encima de los ejes normales). Se
        # desactivan acá abajo.
        #
        # min_y/max_y = piso/techo de los datos ±2, redondeados al entero hacia afuera (floor/
        # ceil) — a pedido explícito: valores 67.7-68.8 deben dar un eje 65-71, no 65.7-70.8.
        # Antes se usaba _limites_eje_y() (margen del 30% del rango) — con un rango de HR tan
        # chico (67.7-68.8, ~1bpm) ese 30% daba un margen mínimo y el gráfico se veía "cortado"
        # (bug real reportado: "solo se ve el eje 67.5 y las puntas de las barras").
        valores_hr = [f["hr_media"] for f in estadisticas if f["hr_media"] is not None]
        if valores_hr:
            min_y_hr = math.floor(min(valores_hr) - 2)
            max_y_hr = math.ceil(max(valores_hr) + 2)
        else:
            min_y_hr, max_y_hr = 0, 100

        grafico_hr = fc.BarChart(
            groups=[
                fc.BarChartGroup(
                    x=i,
                    rods=[
                        fc.BarChartRod(
                            to_y=f["hr_media"] or 0,
                            width=32,
                            color=_color_estimulo(f["tipo_estimulo"]),
                            border_radius=6,
                            # selected=True + BarChart.interactive=False (ver más abajo) hace
                            # que el tooltip quede SIEMPRE visible en vez de solo al pasar el
                            # mouse — es el mecanismo real de flet_charts para "valor encima
                            # de cada barra" (no hay un parámetro "label" directo en BarChartRod).
                            selected=True,
                            tooltip=fc.BarChartRodTooltip(
                                text=f"{f['hr_media']:.1f} bpm" if f["hr_media"] is not None else "N/A",
                                text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_700, color=Colors.TEXT_PRIMARY),
                            ),
                        )
                    ],
                )
                for i, f in enumerate(estadisticas)
            ],
            height=320,
            interactive=False,
            left_axis=fc.ChartAxis(
                show_labels=True, label_size=36, show_min=False, show_max=False,
                title=ft.Text("HR (bpm)", size=11, color=Colors.TEXT_SECONDARY),
            ),
            bottom_axis=fc.ChartAxis(show_labels=True, labels=etiquetas_eje, show_min=False, show_max=False),
            min_y=min_y_hr,
            max_y=max_y_hr,
        )

        # MEJORA: si NINGÚN tipo de estímulo tiene ni un solo "me_gusta"/"me_gusta_mucho"
        # (n_preferido=0 en las 4 filas), el gráfico de % sale con las 4 barras en 0 — que se
        # ve como "vacío/roto", no como un resultado real (bug real reportado probando la
        # app). Se calcula directo de "estadisticas" (ya trae n_preferido de la query
        # existente, ver el SELECT de arriba) — no hace falta una consulta aparte.
        #
        # Nota: esto es distinto de "nadie completó el cuestionario" — technically alguna
        # prueba puede tener preferencia='neutral'/'no_me_gusto' (dato real, no ausente) y
        # aun así dar n_preferido=0 en todos lados. Se decide mostrar igual el EmptyState en
        # ese caso porque un gráfico con las 4 barras en 0% no le aporta nada al
        # investigador — el motivo exacto (nadie respondió vs. a nadie le gustó nada) se ve
        # en la tabla "Estadísticas por estímulo" de abajo, columna N.
        hay_preferencias = any(f.get("n_preferido") for f in estadisticas)

        if hay_preferencias:
            grafico_pref: ft.Control = fc.BarChart(
                groups=[
                    fc.BarChartGroup(
                        x=i,
                        rods=[
                            fc.BarChartRod(
                                to_y=(f["n_preferido"] / f["n"] * 100) if f["n"] else 0,
                                width=32,
                                color=_color_estimulo(f["tipo_estimulo"]),
                                border_radius=6,
                                selected=True,
                                tooltip=fc.BarChartRodTooltip(
                                    text=f"{(f['n_preferido'] / f['n'] * 100) if f['n'] else 0:.0f}%",
                                    text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_700, color=Colors.TEXT_PRIMARY),
                                ),
                            )
                        ],
                    )
                    for i, f in enumerate(estadisticas)
                ],
                height=220,
                interactive=False,
                left_axis=fc.ChartAxis(
                    show_labels=True, label_size=36, show_min=False, show_max=False,
                    title=ft.Text("Preferencia (%)", size=11, color=Colors.TEXT_SECONDARY),
                ),
                bottom_axis=fc.ChartAxis(show_labels=True, labels=etiquetas_eje, show_min=False, show_max=False),
                max_y=100,
            )
        else:
            grafico_pref = EmptyState(
                ft.Icons.SENTIMENT_SATISFIED_ALT,
                "Sin datos de preferencia subjetiva",
                "Los participantes no completaron los chips 😞/😐/🙂/😍 en el Cuestionario "
                "Likert. Este gráfico se habilitará cuando haya al menos una respuesta registrada.",
                color=Colors.TEXT_SECONDARY,
            )

        tabla_stats = ft.DataTable(
            border_radius=Radius.CARD,
            bgcolor=Colors.BG_CARD,
            heading_row_color=Colors.BG_MAIN,
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
            data_text_style=ft.TextStyle(size=13, color=Colors.TEXT_PRIMARY),
            horizontal_lines=ft.border.BorderSide(1, Colors.BORDER),
            columns=[
                ft.DataColumn(label=ft.Text("Estímulo")),
                ft.DataColumn(label=ft.Text("Media HR"), numeric=True),
                ft.DataColumn(label=ft.Text("Desv. estándar"), numeric=True),
                ft.DataColumn(label=ft.Text("N"), numeric=True),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(f["tipo_estimulo"])),
                        ft.DataCell(ft.Text(f"{f['hr_media']:.1f}" if f["hr_media"] is not None else "—")),
                        ft.DataCell(ft.Text(f"{f['hr_desv']:.2f}" if f["hr_desv"] is not None else "—")),
                        ft.DataCell(ft.Text(str(f["n"]))),
                    ]
                )
                for f in estadisticas
            ],
        )

        def _tarjeta(titulo: str, contenido: ft.Control) -> ft.Control:
            return ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                shadow=Shadows.SM,
                content=ft.Column(spacing=Spacing.SM, controls=[ft.Text(titulo, size=15, weight=ft.FontWeight.W_600), contenido]),
            )

        return ft.Column(
            expand=True,
            spacing=Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                _tarjeta("HR promedio por estímulo (bpm)", grafico_hr),
                _tarjeta("Preferencia (%) por estímulo", grafico_pref),
                # Tabla envuelta en una Row con scroll horizontal propio: si algún día se
                # agregan más columnas (o la ventana es angosta) no queda recortada — sin
                # esto, un DataTable más ancho que el card simplemente se corta contra el
                # borde en vez de poder desplazarse (bug real reportado probando esta tab).
                _tarjeta(
                    "Estadísticas por estímulo",
                    ft.Column(
                        spacing=Spacing.SM,
                        controls=[
                            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[tabla_stats]),
                            # Advertencia, no limpieza automática: los conteos (N) de esta
                            # tabla salen tal cual de "pruebas", incluyendo sesiones piloto
                            # tempranas con datos irregulares (ver docstring del módulo/
                            # historial del proyecto) — se avisa en vez de filtrar en
                            # silencio, para no ocultarle al investigador que el N real de
                            # sesiones "limpias" puede ser menor al que muestra la tabla.
                            ft.Text(
                                "Nota: los conteos incluyen todas las sesiones registradas, incluyendo pruebas "
                                "piloto tempranas. Para análisis definitivo, filtrar por sesiones completas "
                                "(con las 4 pruebas registradas).",
                                size=11,
                                color=Colors.TEXT_SECONDARY,
                                italic=True,
                            ),
                        ],
                    ),
                ),
            ],
        )

    # --- TAB C: Recomendación ---
    def _tab_recomendacion(self) -> ft.Control:
        """Calcula, para UN participante, qué condición generó la mejor respuesta de
        relajación — el resultado central de la tesis (ver
        Recomendador.calcular_score_relajacion() en recomendador.py).

        REDISEÑO (ver PROTOCOLO POR DÍA en sesion_completa.py): antes esto comparaba
        las hasta-4 pruebas de UNA sesión entre sí (diseño viejo: 4 estímulos
        seguidos en la misma sesión). Ahora cada sesión trae UNA sola prueba (un día,
        un estímulo) — comparar "dentro de una sesión" ya no tiene sentido, porque no
        hay nada más con qué comparar ahí adentro. La comparación real ahora es ENTRE
        LAS SESIONES (días) del mismo participante: se recorren TODAS sus sesiones,
        se normaliza cada una contra el baseline de ESE MISMO día (nunca contra el de
        otro día — el HR de reposo puede variar de un día a otro, así que mezclar
        baselines entre sesiones sería normalizar mal), y se junta todo en un único
        ranking. Sigue funcionando igual para participantes viejos con una sola
        sesión de 4 pruebas (ahí las 4 SÍ comparten baseline de verdad, porque son la
        misma sesión — Recomendador.calcular_score_relajacion() no cambió nada).
        """
        if self.bd is None:
            return EmptyState(ft.Icons.CLOUD_OFF_OUTLINED, "Sin conexión a SQL Server", "Revisa que el servicio esté corriendo y las credenciales en .env.")

        try:
            participantes = self.bd.obtener_participantes()
        except Exception as error:
            return EmptyState(ft.Icons.ERROR_OUTLINE, "Error consultando participantes", str(error))

        _forma_dropdown = dict(
            border_radius=Radius.INPUT, filled=True, fill_color=Colors.BG_MAIN, border_color=Colors.BORDER, focused_border_color=Colors.PRIMARY
        )
        selector_participante = ft.Dropdown(
            label="Participante",
            width=200,
            options=[ft.dropdown.Option(p["id_participante"]) for p in participantes],
            **_forma_dropdown,
        )
        contenedor_resultado = EmptyState(
            ft.Icons.RECOMMEND_OUTLINED, "Elegí un participante", "El ranking de relajación entre sus sesiones aparece acá."
        )

        def calcular(e: ft.ControlEvent) -> None:
            if not selector_participante.value:
                self._mostrar_snack(SnackBarError("Elige un participante primero."))
                return
            try:
                import pandas as pd

                participante_id = selector_participante.value
                # SELECT * FROM sesiones WHERE id_participante = ? ORDER BY fecha_hora
                # (ver BaseDatosTesis.obtener_sesiones_participante) — todas las sesiones
                # que este participante tenga hasta ahora (1 a 5 de 5 días, o incluso
                # 1 sola sesión vieja de 4 pruebas), no se filtra por cantidad. El Día 5
                # se excluye más abajo SOLO de comparacion_grupos (ver ahí el porqué),
                # no de este ranking por-sesión.
                sesiones = self.bd.obtener_sesiones_participante(participante_id)
                if not sesiones:
                    contenedor_resultado.content = ft.Text(
                        "Este participante no tiene sesiones registradas.", color=Colors.TEXT_SECONDARY
                    )
                    self._actualizar_pagina_segura()
                    return

                # N+1 deliberado (una consulta de pruebas por sesión): son a lo sumo 2-3
                # sesiones por participante bajo el protocolo por día — mismo criterio ya
                # aceptado en otros lados de esta vista (ver Timeline de Inicio).
                rankings_por_sesion = []
                alguna_preferencia = False
                for sesion in sesiones:
                    pruebas = self.bd.obtener_pruebas_sesion(sesion["id_sesion"])
                    if not pruebas:
                        continue
                    tabla = pd.DataFrame(
                        [
                            {
                                "condicion": p["tipo_estimulo"],
                                "hr_media": p.get("hr_promedio"),
                                "sdnn": p.get("sdnn"),
                                "rmssd": p.get("rmssd"),
                                "respiraciones_min": p.get("resp_por_min"),
                            }
                            for p in pruebas
                        ]
                    )
                    # La tabla 'pruebas' nunca guarda una fila "reposo" (el baseline vive
                    # aparte, en sesiones.hr_baseline/sdnn_baseline/rmssd_baseline) — y es
                    # EL BASELINE DE ESTA SESIÓN PUNTUAL, no uno global del participante.
                    baseline_reposo = {
                        "hr_media": sesion.get("hr_baseline"),
                        "sdnn": sesion.get("sdnn_baseline"),
                        "rmssd": sesion.get("rmssd_baseline"),
                        "respiraciones_min": float("nan"),
                    }
                    ranking_sesion = Recomendador().calcular_score_relajacion(tabla, baseline_reposo)
                    ranking_sesion["dia_sesion"] = sesion.get("dia_sesion")
                    rankings_por_sesion.append(ranking_sesion)
                    if any(p.get("preferencia") for p in pruebas):
                        alguna_preferencia = True

                if not rankings_por_sesion:
                    contenedor_resultado.content = ft.Text(
                        "Este participante no tiene pruebas registradas en ninguna sesión.", color=Colors.TEXT_SECONDARY
                    )
                    self._actualizar_pagina_segura()
                    return

                # Cada ranking_por_sesion ya viene ordenado desc, pero al juntar varias
                # sesiones hay que reordenar el conjunto entero — si no, quedaría
                # ordenado "por sesión" en vez de por score real.
                ranking = (
                    pd.concat(rankings_por_sesion, ignore_index=True)
                    .sort_values("score_relajacion", ascending=False)
                    .reset_index(drop=True)
                )
                # "preferencia" acá es la columna categórica de la pregunta "¿te gustó?"
                # (me_gusta/neutral/...) — no forma parte del cálculo de score_relajacion
                # (ese usa solo hr_media/sdnn/rmssd/respiraciones_min, ver Recomendador),
                # así que nunca puede "romper" el ranking; solo se usa para avisar en la
                # UI cuándo falta ese dato subjetivo en TODAS las sesiones.
                #
                # Comparación PRIMARIA (ver H1/H0 en el Anexo 5, página 19): 2 grupos
                # agrupados — "frecuencias terapéuticas comunes" (Días 1+3 promediados)
                # vs. "sonidos de preferencia personal" (Días 2+4 promediados). El
                # ranking por-sesión de más arriba queda como detalle SECUNDARIO (ver
                # Recomendador.comparar_grupos_terapeutica_vs_preferencia()).
                #
                # El Día 5 ("adaptativa") repite a propósito el estímulo que ya dio
                # mejor resultado en los Días 1-4 — incluirlo acá sesgaría el grupo
                # ganador con una muestra elegida porque se sabía que iba a salir
                # bien (mismo criterio que analisis_intrasujeto.preparar_sesiones).
                # Se excluye SOLO de esta comparación de 2 grupos; el ranking por
                # sesión de arriba sí lo muestra, para que el investigador vea qué
                # pasó en esa sesión.
                ranking_para_grupos = ranking[ranking["dia_sesion"] != 5]
                comparacion_grupos = Recomendador().comparar_grupos_terapeutica_vs_preferencia(ranking_para_grupos)
                contenedor_resultado.content = self._construir_resultado_recomendacion(
                    ranking, alguna_preferencia, comparacion_grupos
                )
                self._actualizar_pagina_segura()
            except Exception as error:
                logger.error(f"Error calculando recomendación: {error}")
                self._mostrar_snack(SnackBarError(f"No se pudo calcular la recomendación: {error}"))

        boton_calcular = GradientButton("Calcular recomendación", on_click=calcular, icono=ft.Icons.RECOMMEND_OUTLINED)

        return ft.Column(
            spacing=Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Container(
                    padding=ft.padding.Padding.all(Spacing.LG),
                    border_radius=Radius.CARD,
                    bgcolor=Colors.BG_CARD,
                    shadow=Shadows.SM,
                    content=ft.Column(
                        spacing=Spacing.MD,
                        controls=[
                            ft.Text(
                                "Resultado principal: compara los 2 grupos de la hipótesis del Anexo 5 — "
                                "frecuencias terapéuticas comunes (Días 1+3) vs. sonidos de preferencia "
                                "personal (Días 2+4) — cada sesión normalizada contra el baseline de SU "
                                "PROPIO día antes de promediar. Más abajo queda, como detalle secundario, "
                                "el ranking sesión por sesión.",
                                size=12,
                                color=Colors.TEXT_SECONDARY,
                            ),
                            ft.Row(spacing=Spacing.SM, controls=[selector_participante, boton_calcular]),
                        ],
                    ),
                ),
                contenedor_resultado,
            ],
        )

    def _construir_resultado_recomendacion(
        self, ranking, preferencia_disponible: bool = True, comparacion_grupos: Optional[dict] = None
    ) -> ft.Control:
        """Arma el resultado de la pestaña Recomendación: tarjeta PRIMARIA de la
        comparación de 2 grupos (H1/H0) + detalle SECUNDARIO (tarjeta del mejor
        estímulo individual y tabla de ranking sesión por sesión).

        Args:
            ranking: DataFrame devuelto por Recomendador.calcular_score_relajacion()
                (condicion, hr_media, sdnn, rmssd, respiraciones_min, score_relajacion).
            preferencia_disponible: False si NINGUNA prueba de la sesión tiene la
                columna "preferencia" (me_gusta/neutral/...) cargada — común si el
                cuestionario post-sesión no se completó. El ranking se calcula
                exactamente igual en ambos casos (preferencia no participa de
                score_relajacion, ver calcular()); esto solo cambia un aviso en la UI.
            comparacion_grupos: dict de Recomendador.comparar_grupos_terapeutica_vs_preferencia()
                ({"terapeuticas": {...} | None, "preferencia": {...} | None}) — el
                resultado central de la tesis (Anexo 5, H1/H0). None si no se calculó
                (compatibilidad hacia atrás, no debería pasar desde calcular()).
        """
        import pandas as pd

        if ranking.empty or ranking["score_relajacion"].isna().all():
            return ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=ft.Colors.with_opacity(0.08, Colors.WARNING),
                content=ft.Text(
                    "No se pudo calcular ningún score (faltan datos de baseline o de las pruebas).", color=Colors.WARNING
                ),
            )

        mejor = ranking.iloc[0]
        estado = "más relajada" if mejor["score_relajacion"] > 0 else "más activada"
        # Barra visual del score: puramente decorativa, no altera el valor mostrado en la
        # tabla — mapea el score (típicamente en un rango chico alrededor de 0, sin cota
        # fija) a 0-1 con un clamp generoso [-1, 1] solo para tener algo que pintar.
        score_normalizado = max(0.0, min(1.0, (float(mejor["score_relajacion"]) + 1) / 2))

        tarjeta_recomendado = ft.Container(
            padding=ft.padding.Padding.all(Spacing.XL),
            border_radius=Radius.CARD,
            gradient=ft.LinearGradient(
                colors=[ft.Colors.with_opacity(0.12, Colors.SUCCESS), ft.Colors.with_opacity(0.03, Colors.SUCCESS)],
                begin=ft.alignment.Alignment.TOP_LEFT,
                end=ft.alignment.Alignment.BOTTOM_RIGHT,
            ),
            border=ft.border.Border.all(1, ft.Colors.with_opacity(0.25, Colors.SUCCESS)),
            shadow=Shadows.MD,
            content=ft.Row(
                spacing=Spacing.LG,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    IconCircle(ft.Icons.EMOJI_EVENTS, ft.Colors.with_opacity(0.16, Colors.SUCCESS), Colors.SUCCESS, tamaño=64),
                    ft.Column(
                        expand=True,
                        spacing=Spacing.XS,
                        controls=[
                            ft.Text(spans=[ft.TextSpan("ESTÍMULO RECOMENDADO", style=Typography.LABEL)]),
                            ft.Text(str(mejor["condicion"]), size=28, weight=ft.FontWeight.W_800, color=Colors.SUCCESS),
                            ft.Text(
                                f"Score de relajación: {mejor['score_relajacion']:.3f} ({estado} que el reposo basal)",
                                size=13,
                                color=Colors.TEXT_SECONDARY,
                            ),
                            ft.ProgressBar(value=score_normalizado, color=Colors.SUCCESS, bgcolor=ft.Colors.with_opacity(0.15, Colors.SUCCESS), border_radius=Radius.CHIP),
                        ]
                        + (
                            []
                            if preferencia_disponible
                            else [
                                ft.Row(
                                    spacing=Spacing.XS,
                                    controls=[
                                        ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=Colors.TEXT_SECONDARY),
                                        ft.Text(
                                            "Basado en métricas fisiológicas (sin preferencia subjetiva)",
                                            size=11,
                                            color=Colors.TEXT_SECONDARY,
                                            italic=True,
                                        ),
                                    ],
                                )
                            ]
                        ),
                    ),
                ],
            ),
        )

        tabla_ranking = ft.DataTable(
            border_radius=Radius.CARD,
            bgcolor=Colors.BG_CARD,
            heading_row_color=Colors.BG_MAIN,
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
            data_text_style=ft.TextStyle(size=13, color=Colors.TEXT_PRIMARY),
            horizontal_lines=ft.border.BorderSide(1, Colors.BORDER),
            columns=[
                ft.DataColumn(label=ft.Text("Estímulo")),
                ft.DataColumn(label=ft.Text("HR media"), numeric=True),
                ft.DataColumn(label=ft.Text("SDNN"), numeric=True),
                ft.DataColumn(label=ft.Text("RMSSD"), numeric=True),
                ft.DataColumn(label=ft.Text("Resp/min"), numeric=True),
                ft.DataColumn(label=ft.Text("Score"), numeric=True),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(fila["condicion"]))),
                        ft.DataCell(ft.Text(f"{fila['hr_media']:.1f}" if pd.notna(fila["hr_media"]) else "—")),
                        ft.DataCell(ft.Text(f"{fila['sdnn']:.2f}" if pd.notna(fila["sdnn"]) else "—")),
                        ft.DataCell(ft.Text(f"{fila['rmssd']:.2f}" if pd.notna(fila["rmssd"]) else "—")),
                        ft.DataCell(
                            ft.Text(f"{fila['respiraciones_min']:.1f}" if pd.notna(fila["respiraciones_min"]) else "—")
                        ),
                        ft.DataCell(ft.Text(f"{fila['score_relajacion']:.3f}" if pd.notna(fila["score_relajacion"]) else "—")),
                    ]
                )
                for _, fila in ranking.iterrows()
            ],
        )

        controles = []
        if comparacion_grupos is not None:
            controles.append(self._construir_tarjeta_comparacion_grupos(comparacion_grupos))
        controles.append(
            ft.Text("Detalle secundario por sesión", size=13, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY)
        )
        controles.append(tarjeta_recomendado)
        controles.append(
            ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                shadow=Shadows.SM,
                content=ft.Column(
                    spacing=Spacing.SM,
                    controls=[ft.Text("Ranking completo (por sesión)", size=14, weight=ft.FontWeight.W_600), tabla_ranking],
                ),
            )
        )

        return ft.Column(spacing=Spacing.MD, controls=controles)

    def _construir_tarjeta_comparacion_grupos(self, comparacion_grupos: dict) -> ft.Control:
        """Tarjeta PRIMARIA de la pestaña Recomendación: compara los 2 grupos de la
        hipótesis del Anexo 5 (página 19) — frecuencias terapéuticas comunes (Días 1+3
        promediados) vs. sonidos de preferencia personal (Días 2+4 promediados). Ver
        Recomendador.comparar_grupos_terapeutica_vs_preferencia().

        Con un solo participante y protocolo incompleto (todavía no tiene sus 4
        sesiones) uno de los 2 grupos puede venir en None — se avisa en vez de
        comparar a medias.
        """
        terapeuticas = comparacion_grupos.get("terapeuticas")
        preferencia = comparacion_grupos.get("preferencia")

        if terapeuticas is None or preferencia is None:
            faltante = "terapéuticas (Días 1/3)" if terapeuticas is None else "de preferencia (Días 2/4)"
            return ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=ft.Colors.with_opacity(0.08, Colors.WARNING),
                content=ft.Text(
                    f"Todavía no hay sesiones {faltante} registradas para este participante — la comparación "
                    "de 2 grupos (resultado principal de la tesis) necesita al menos una sesión de cada tipo.",
                    color=Colors.WARNING,
                ),
            )

        score_terapeuticas = terapeuticas["score_relajacion"]
        score_preferencia = preferencia["score_relajacion"]
        if score_terapeuticas > score_preferencia:
            grupo_ganador, texto_ganador = "terapeuticas", "Frecuencias terapéuticas comunes"
        elif score_preferencia > score_terapeuticas:
            grupo_ganador, texto_ganador = "preferencia", "Sonidos de preferencia personal"
        else:
            grupo_ganador, texto_ganador = None, "Empate"

        def _columna_grupo(titulo: str, datos: dict, es_ganador: bool) -> ft.Control:
            return ft.Container(
                expand=True,
                padding=ft.padding.Padding.all(Spacing.MD),
                border_radius=Radius.INPUT,
                bgcolor=ft.Colors.with_opacity(0.12 if es_ganador else 0.04, Colors.SUCCESS if es_ganador else Colors.TEXT_SECONDARY),
                border=ft.border.Border.all(1, ft.Colors.with_opacity(0.3, Colors.SUCCESS)) if es_ganador else None,
                content=ft.Column(
                    spacing=Spacing.XS,
                    controls=[
                        ft.Text(titulo, size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
                        ft.Text(
                            f"{datos['score_relajacion']:.3f}",
                            size=24,
                            weight=ft.FontWeight.W_800,
                            color=Colors.SUCCESS if es_ganador else Colors.TEXT_PRIMARY,
                        ),
                        ft.Text(f"n = {datos['n_sesiones']} sesión(es)", size=11, color=Colors.TEXT_SECONDARY),
                        ft.Text(
                            f"HR {datos['hr_media']:.1f} · SDNN {datos['sdnn']:.2f} · RMSSD {datos['rmssd']:.2f}",
                            size=11,
                            color=Colors.TEXT_SECONDARY,
                        ),
                    ],
                ),
            )

        return ft.Container(
            padding=ft.padding.Padding.all(Spacing.XL),
            border_radius=Radius.CARD,
            gradient=ft.LinearGradient(
                colors=[ft.Colors.with_opacity(0.12, Colors.PRIMARY), ft.Colors.with_opacity(0.03, Colors.PRIMARY)],
                begin=ft.alignment.Alignment.TOP_LEFT,
                end=ft.alignment.Alignment.BOTTOM_RIGHT,
            ),
            border=ft.border.Border.all(1, ft.Colors.with_opacity(0.25, Colors.PRIMARY)),
            shadow=Shadows.MD,
            content=ft.Column(
                spacing=Spacing.MD,
                controls=[
                    ft.Row(
                        spacing=Spacing.SM,
                        controls=[
                            IconCircle(ft.Icons.SCIENCE_OUTLINED, ft.Colors.with_opacity(0.16, Colors.PRIMARY), Colors.PRIMARY, tamaño=40),
                            ft.Column(
                                spacing=0,
                                controls=[
                                    ft.Text("RESULTADO PRINCIPAL — H1/H0 (Anexo 5)", style=Typography.LABEL),
                                    ft.Text(
                                        f"{texto_ganador} generó mayor relajación" if grupo_ganador else "Ambos grupos generaron relajación equivalente",
                                        size=16,
                                        weight=ft.FontWeight.W_700,
                                        color=Colors.TEXT_PRIMARY,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=Spacing.MD,
                        controls=[
                            _columna_grupo("Frecuencias terapéuticas (Días 1+3)", terapeuticas, grupo_ganador == "terapeuticas"),
                            _columna_grupo("Preferencia personal (Días 2+4)", preferencia, grupo_ganador == "preferencia"),
                        ],
                    ),
                    ft.Text(
                        "Score de relajación promediado por grupo (cada sesión ya normalizada contra el "
                        "baseline de su propio día antes de promediar). Con protocolo completo (4 sesiones) "
                        "cada grupo trae n=2.",
                        size=11,
                        color=Colors.TEXT_SECONDARY,
                        italic=True,
                    ),
                ],
            ),
        )

    # --- TAB D: Consulta SQL ---
    def _tab_consulta_sql(self) -> ft.Control:
        """Editor de SQL libre + tabla de resultados + exportar a Excel."""
        campo_sql = ft.TextField(
            label="Consulta SQL",
            multiline=True,
            min_lines=4,
            max_lines=8,
            value="SELECT * FROM participantes;",
            text_style=ft.TextStyle(font_family="Consolas, monospace", size=13),
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )
        contenedor_resultado = EmptyState(ft.Icons.CODE, "Ejecutá una consulta", "Los resultados aparecen acá abajo.")

        def ejecutar(e: ft.ControlEvent) -> None:
            if self.bd is None:
                self._mostrar_snack(SnackBarError("Sin conexión a SQL Server."))
                return
            try:
                resultados = self.bd.ejecutar_query(campo_sql.value)
                self._ultimo_resultado_sql = resultados or []
                if not self._ultimo_resultado_sql:
                    contenedor_resultado.content = ft.Text("Consulta ejecutada. Sin filas para mostrar.", color=Colors.TEXT_SECONDARY)
                else:
                    columnas = list(self._ultimo_resultado_sql[0].keys())
                    contenedor_resultado.content = ft.DataTable(
                        border_radius=Radius.CARD,
                        bgcolor=Colors.BG_CARD,
                        heading_row_color=Colors.BG_MAIN,
                        heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
                        data_text_style=ft.TextStyle(size=13, color=Colors.TEXT_PRIMARY),
                        horizontal_lines=ft.border.BorderSide(1, Colors.BORDER),
                        columns=[ft.DataColumn(label=ft.Text(c)) for c in columnas],
                        rows=[
                            ft.DataRow(cells=[ft.DataCell(ft.Text(str(fila.get(c, "")))) for c in columnas])
                            for fila in self._ultimo_resultado_sql
                        ],
                    )
                self._actualizar_pagina_segura()
            except Exception as error:
                self._mostrar_snack(SnackBarError(f"Error en la consulta: {error}"))

        def exportar(e: ft.ControlEvent) -> None:
            if not self._ultimo_resultado_sql:
                self._mostrar_snack(SnackBarError("Ejecuta una consulta primero."))
                return
            try:
                ruta = self._exportar_a_excel({"consulta": self._ultimo_resultado_sql})
                self._mostrar_snack(SnackBarExito(f"Exportado a {ruta}"))
            except Exception as error:
                self._mostrar_snack(SnackBarError(f"No se pudo exportar: {error}"))

        return ft.Column(
            spacing=Spacing.MD,
            expand=True,
            # Bug real reportado (mismo que Vista Cuestionario): sin scroll=, una consulta
            # que devuelva muchas filas hace que la tabla se corte contra el borde de la
            # ventana sin ninguna forma de bajar a verlas — ver DataTable en ejecutar() más
            # arriba, que puede crecer sin límite según lo que devuelva la query.
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Container(
                    padding=ft.padding.Padding.all(Spacing.LG),
                    border_radius=Radius.CARD,
                    bgcolor=Colors.BG_CARD,
                    shadow=Shadows.SM,
                    content=ft.Column(
                        spacing=Spacing.SM,
                        controls=[
                            campo_sql,
                            ft.Row(
                                spacing=Spacing.SM,
                                controls=[
                                    GradientButton("Ejecutar", on_click=ejecutar, icono=ft.Icons.PLAY_ARROW),
                                    ft.OutlinedButton(content=ft.Text("Exportar a Excel"), icon=ft.Icons.DOWNLOAD, on_click=exportar),
                                ],
                            ),
                        ],
                    ),
                ),
                ft.Container(expand=True, content=contenedor_resultado),
            ],
        )

    # --- TAB E: Exportar ---
    def _tab_exportar(self) -> ft.Control:
        """Exportar todo a Excel, generar reporte de un participante, backup de la BD."""
        selector_participante = ft.Dropdown(
            label="Participante",
            width=260,
            options=[],
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )
        if self.bd is not None:
            try:
                for p in self.bd.obtener_participantes():
                    selector_participante.options.append(ft.dropdown.Option(p["id_participante"]))
            except Exception as error:
                logger.error(f"No se pudo cargar la lista de participantes: {error}")

        def exportar_todo(e: ft.ControlEvent) -> None:
            if self.bd is None:
                self._mostrar_snack(SnackBarError("Sin conexión a SQL Server."))
                return
            try:
                hojas = {
                    "participantes": self.bd.obtener_participantes(),
                    "sesiones": self.bd.ejecutar_query("SELECT * FROM sesiones") or [],
                    "pruebas": self.bd.ejecutar_query("SELECT * FROM pruebas") or [],
                }
                ruta = self._exportar_a_excel(hojas)
                self._mostrar_snack(SnackBarExito(f"Exportado a {ruta}"))
            except Exception as error:
                self._mostrar_snack(SnackBarError(f"No se pudo exportar: {error}"))

        def generar_reporte(e: ft.ControlEvent) -> None:
            if self.bd is None or not selector_participante.value:
                self._mostrar_snack(SnackBarError("Elige un participante primero."))
                return
            try:
                ruta = self._generar_reporte_pdf(selector_participante.value)
                self._mostrar_snack(SnackBarExito(f"Reporte PDF generado en {ruta}"))
            except Exception as error:
                logger.error(f"No se pudo generar el reporte PDF: {error}")
                self._mostrar_snack(SnackBarError(f"No se pudo generar el reporte: {error}"))

        def backup_bd(e: ft.ControlEvent) -> None:
            if self.bd is None:
                self._mostrar_snack(SnackBarError("Sin conexión a SQL Server."))
                return
            try:
                ruta = self._backup_bd()
                self._mostrar_snack(SnackBarExito(f"Backup solicitado: {ruta}"))
            except Exception as error:
                self._mostrar_snack(SnackBarError(f"No se pudo hacer el backup: {error}"))

        def _tarjeta(icono: str, titulo: str, descripcion: str, contenido: ft.Control) -> ft.Control:
            return ft.Container(
                padding=ft.padding.Padding.all(Spacing.LG),
                border_radius=Radius.CARD,
                bgcolor=Colors.BG_CARD,
                shadow=Shadows.SM,
                content=ft.Column(
                    spacing=Spacing.SM,
                    controls=[
                        ft.Row(
                            spacing=Spacing.SM,
                            controls=[
                                IconCircle(icono, ft.Colors.with_opacity(0.12, Colors.PRIMARY), Colors.PRIMARY, tamaño=32),
                                ft.Text(titulo, size=16, weight=ft.FontWeight.W_600),
                            ],
                        ),
                        ft.Text(descripcion, size=12, color=Colors.TEXT_SECONDARY),
                        contenido,
                    ],
                ),
            )

        return ft.Column(
            spacing=Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                _tarjeta(
                    ft.Icons.TABLE_VIEW_OUTLINED,
                    "Exportar todo a Excel",
                    "Vuelca participantes, sesiones y pruebas completas a un .xlsx.",
                    GradientButton("Exportar (participantes, sesiones, pruebas)", on_click=exportar_todo, icono=ft.Icons.DOWNLOAD),
                ),
                _tarjeta(
                    ft.Icons.PICTURE_AS_PDF_OUTLINED,
                    "Reporte de un participante (PDF)",
                    "Genera un PDF con encabezado, datos del participante, tablas de métricas por "
                    "sesión y gráficos comparativos de HR por estímulo (ver RUTA_LOGO_ESPE en el "
                    "docstring del módulo si el logo no aparece).",
                    ft.Row(
                        spacing=Spacing.SM,
                        controls=[
                            selector_participante,
                            ft.OutlinedButton(
                                content=ft.Text("Generar reporte PDF"), icon=ft.Icons.PICTURE_AS_PDF, on_click=generar_reporte
                            ),
                        ],
                    ),
                ),
                _tarjeta(
                    ft.Icons.BACKUP_OUTLINED,
                    "Backup de la base de datos",
                    "Requiere que el propio servicio de SQL Server tenga permiso de escritura "
                    "en la carpeta de destino (no depende de esta app).",
                    ft.OutlinedButton(content=ft.Text("Generar backup"), icon=ft.Icons.BACKUP, on_click=backup_bd),
                ),
            ],
        )

    def _exportar_a_excel(self, hojas: dict[str, list]) -> Path:
        """Escribe cada lista de dicts como una hoja de un .xlsx.

        Args:
            hojas: nombre de hoja -> lista de filas (dicts).

        Returns:
            Path: Ruta del archivo generado en CARPETA_EXPORTS.
        """
        import pandas as pd

        CARPETA_EXPORTS.mkdir(parents=True, exist_ok=True)
        ruta = CARPETA_EXPORTS / f"exportado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        with pd.ExcelWriter(ruta, engine="openpyxl") as escritor:
            for nombre_hoja, filas in hojas.items():
                df = pd.DataFrame(filas) if filas else pd.DataFrame()
                df.to_excel(escritor, sheet_name=nombre_hoja[:31], index=False)
        return ruta

    @staticmethod
    def _limites_eje_y(valores: list[float], colchon: float = 0.3, piso_minimo: float = 0.0) -> tuple[float, float]:
        """Calcula (mínimo, máximo) de eje Y con margen, en vez de arrancar en 0 siempre.

        Bug real reportado probando la app: con HR entre 70-73 bpm, un gráfico
        de barras que arranca en 0 (escala 0-80) hace que esa diferencia real
        de 3 bpm se vea invisible — todas las barras "salen casi iguales". El
        gráfico de 4 paneles de analizar_sesion.py (graficar_sesion()) nunca
        tuvo este problema porque matplotlib autoescala los ejes de sus
        líneas/boxplots; acá, al fijar min_y=0 a mano, se perdía ese ajuste.

        Args:
            valores: Los valores a graficar.
            colchon: Fracción del rango real a agregar como margen arriba/abajo (default 30%).
            piso_minimo: Nunca baja de este valor (0 para HR/HRV — no tiene sentido negativo).

        Returns:
            tuple[float, float]: (mínimo, máximo) para set_ylim()/min_y,max_y.
        """
        if not valores:
            return (0.0, 100.0)
        minimo, maximo = min(valores), max(valores)
        rango = maximo - minimo
        if rango < 1e-6:  # todas las barras miden lo mismo — evita un rango de altura 0
            rango = max(abs(maximo) * 0.1, 1.0)
        margen = rango * colchon
        return (max(piso_minimo, minimo - margen), maximo + margen)

    def _generar_reporte_pdf(self, id_participante: str) -> Path:
        """Genera el reporte PDF (nivel publicación académica) de un participante.

        Delegado a reporte_pdf.py — ese módulo no sabe nada de Flet ni de
        AppInvestigador, solo de BaseDatosTesis + reportlab/matplotlib, así
        que se puede probar y mantener por separado del resto de la app. Esta
        función queda como wrapper fino para que el resto de la app (ver
        generar_reporte() en _tab_exportar()) no note el cambio: misma firma,
        mismo comportamiento externo.

        Args:
            id_participante: ID del participante a reportar.

        Returns:
            Path: Ruta del .pdf generado en CARPETA_EXPORTS.

        Raises:
            ValueError: Si el participante no existe, o no tiene ninguna
                sesión con pruebas registradas.
        """
        from reporte_pdf import generar_reporte_pdf

        return generar_reporte_pdf(self.bd, id_participante, CARPETA_EXPORTS, RUTA_LOGO_ESPE)


    def _backup_bd(self) -> Path:
        """Dispara un BACKUP DATABASE de SQL Server hacia CARPETA_BACKUPS.

        Returns:
            Path: Ruta del .bak solicitado (la escribe el PROCESO de SQL Server,
                no esta app — si ese proceso no tiene permiso sobre la carpeta,
                el backup falla del lado del servidor).
        """
        CARPETA_BACKUPS.mkdir(parents=True, exist_ok=True)
        ruta = CARPETA_BACKUPS / f"TesisKevin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        ruta_escapada = str(ruta).replace("'", "''")
        self.bd.ejecutar_query(f"BACKUP DATABASE [TesisKevin] TO DISK = N'{ruta_escapada}'")
        return ruta


def main(page: ft.Page) -> None:
    """Punto de entrada de la app Flet.

    Args:
        page: Página raíz que Flet crea para esta sesión de la app.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    AppInvestigador(page)


if __name__ == "__main__":
    ft.app(target=main)
