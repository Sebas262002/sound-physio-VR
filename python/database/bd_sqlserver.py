"""Única puerta de entrada a SQL Server para todo el sistema.

Ningún otro módulo del proyecto debe importar pyodbc directamente ni
construir su propia cadena de conexión — todo pasa por
BaseDatosTesis, para que la lógica de conexión, reintentos y manejo de
errores viva en un solo lugar.

¿Por qué pyodbc puro y no un ORM (SQLAlchemy)? Las 3 tablas
(participantes, sesiones, pruebas) ya existen con una estructura fija y
simple (ver el esquema completo abajo), y las operaciones que necesita
este proyecto son un puñado de INSERT/SELECT/UPDATE bien definidos, no
consultas dinámicas complejas. Un ORM agregaría una capa de mapeo
objeto-relacional (modelos, sesión ORM, migraciones) que no aporta nada
acá y sí resta control directo sobre el SQL que se ejecuta — con pyodbc
puro se sabe exactamente qué sentencia corre contra la base.

CONNECTION POOLING:
pyodbc.pooling = True (default de la librería, se deja explícito abajo)
activa el pooling nativo del Driver Manager de ODBC: conexiones físicas
reutilizadas a nivel de sistema operativo entre distintos objetos
pyodbc.connect(), no solo dentro de este proceso. A nivel de aplicación,
BaseDatosTesis además mantiene UNA sola conexión (self.conexion) que se
reutiliza en todos los métodos en vez de abrir una nueva por consulta —
evitar el costo de reconectar en cada INSERT/SELECT.

CREDENCIALES (.env):
Las credenciales NUNCA se hardcodean acá. Se leen de un archivo .env
(ver .env.example en la raíz del proyecto) con python-dotenv:

    DB_SERVER=DESKTOP-059IB6K\\SQLEXPRESS
    DB_DATABASE=TesisKevin
    DB_USER=sa
    DB_PASSWORD=...
    DB_DRIVER=ODBC Driver 17 for SQL Server

El .env real está en .gitignore (nunca se sube a git); .env.example sí
se versiona, con valores de ejemplo, como plantilla.

ESQUEMA DE LA BASE (ya creado en SQL Server, este módulo no lo modifica):

    participantes:
        id_participante VARCHAR(10) PK, edad INT NULL, genero VARCHAR(10) NULL,
        fecha_registro DATETIME NOT NULL,
        consentimiento BIT NULL, observaciones VARCHAR(500) NULL,
        ruta_preferencia_wav NVARCHAR(500) NULL

        NOTA: ruta_preferencia_wav se agregó para precargar el Día 2 de un
        participante que ya hizo Día 1 (ver actualizar_ruta_preferencia() y
        _autocompletar_participante_existente() en app_investigador.py). La
        MISMA canción se reutiliza en Día 4 y, si corresponde, en Día 5 — ver
        PROTOCOLO EXPERIMENTAL FINAL en sesion_completa.py. Si tu SQL Server
        todavía no tiene esta columna, correr una sola vez:

            ALTER TABLE participantes ADD ruta_preferencia_wav NVARCHAR(500) NULL;

        ruta_preferencia_wav_2 y mano_dominante EXISTIERON y se ELIMINARON
        (la primera porque el protocolo pasó a reutilizar una sola canción en
        vez de pedir una segunda distinta; la segunda a pedido explícito del
        tutor, no aportaba nada al análisis de la tesis — ver Hipótesis
        H1/H0). Si tu SQL Server todavía tiene alguna de esas columnas de una
        versión vieja, correr una vez (ver también
        database/migrar_quitar_preferencia_2.py):

            ALTER TABLE participantes DROP COLUMN ruta_preferencia_wav_2;
            ALTER TABLE participantes DROP COLUMN mano_dominante;

    sesiones:
        id_sesion INT IDENTITY PK, id_participante VARCHAR(10) FK NOT NULL,
        fecha_hora DATETIME NOT NULL, duracion_seg INT NULL,
        hr_baseline/rmssd_baseline/sdnn_baseline FLOAT NULL, notas VARCHAR(500) NULL,
        usa_vr BIT NOT NULL DEFAULT 0,
        dia_sesion INT NULL (1-5 del protocolo), valida BIT NOT NULL DEFAULT 1
        (0 = sesión descartada del análisis, ver marcar_sesion_invalida()).
        Si tu SQL Server todavía no tiene dia_sesion/valida, correr una sola vez
        database/migrar_agregar_dia_valida.py (crear_sesion() sigue funcionando
        sin ellas: solo deja de guardar el día).

    pruebas:
        id_prueba INT IDENTITY PK, id_sesion INT FK NOT NULL,
        id_participante VARCHAR(10) FK NOT NULL, tipo_estimulo VARCHAR(20) NOT NULL,
        frecuencia_hz FLOAT NULL, duracion_seg INT NULL,
        hr_promedio/hr_min/hr_max/rmssd/sdnn/pnn50/resp_por_min FLOAT NULL,
        preferencia VARCHAR(20) NULL, likert_relajacion/likert_confort INT NULL,
        fecha_hora DATETIME NOT NULL

RETRY AUTOMÁTICO:
Todos los métodos públicos pasan por _ejecutar(), el único punto del
módulo que de verdad toca pyodbc. Si una consulta falla por un error de
conexión (BLE/red/servidor reiniciado, etc.), _ejecutar() cierra la
conexión rota, reintenta reconectar y reintenta la MISMA consulta hasta
max_reintentos veces (default 3) antes de propagar el error. Nunca deja
una transacción a medias: cualquier excepción hace rollback() antes de
reintentar o de propagar.
"""

import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import pyodbc
from dotenv import load_dotenv

pyodbc.pooling = True

logger = logging.getLogger(__name__)

RUTA_ENV_DEFAULT = Path(r"C:\Tesis_Kevin\.env")

# Mapeo banda de frecuencia -> Hz nominal, usado cuando el nombre del bloque
# no trae el número explícito (ej. "binaural_theta" en vez de "binaural_6Hz_theta") —
# coincide con las frecuencias reales generadas por generador_tonos.py.
_BANDA_A_HZ = {"delta": 3.0, "theta": 6.0, "alpha": 10.0, "beta": 20.0, "gamma": 40.0}
# Orden IMPORTA: next() en mapear_bloque_a_prueba() devuelve el primer match,
# así que los tipos compuestos ("solfeggio_isocronico", que contiene la
# substring "solfeggio") deben ir ANTES que su tipo genérico, si no
# "solfeggio_isocronico_528Hz" se etiquetaría como "solfeggio" a secas.
_TIPOS_ESTIMULO = ("solfeggio_isocronico", "paisaje", "solfeggio", "binaural", "isocronico", "preferencia")


def _limpiar_valor(valor: Any) -> Any:
    """Convierte NaN y escalares numpy a valores nativos aptos para pyodbc.

    Las métricas de este proyecto vienen de pandas/numpy (ver
    analizar_sesion.py), que representa "sin dato" como NaN — pyodbc no
    sabe insertar un NaN de Python en una columna FLOAT de SQL Server (lo
    manda tal cual y el driver lo rechaza o lo corrompe). De paso, castea
    escalares numpy (int64, float64, etc.) a tipos nativos: pyodbc a veces
    falla al bindear un tipo numpy directamente.

    Args:
        valor: Cualquier valor a insertar en una columna de la base.

    Returns:
        Any: El mismo valor si es válido; None si era NaN (o si el propio
            valor es None de entrada).
    """
    if valor is None:
        return None
    if hasattr(valor, "item"):  # escalar numpy (np.float64, np.int64, ...)
        valor = valor.item()
    if isinstance(valor, float) and math.isnan(valor):
        return None
    return valor


def mapear_bloque_a_prueba(nombre_bloque: str) -> Optional[dict]:
    """Traduce el nombre de un bloque de protocolo a (tipo_estimulo, frecuencia_hz).

    Usado tanto por sesion_completa.py (al guardar una sesión recién
    capturada) como por migrar_csv_a_sqlserver.py (al migrar sesiones
    piloto ya guardadas en CSV) — un solo lugar para esta traducción.

    Args:
        nombre_bloque: Nombre del bloque tal como aparece en el protocolo
            (ver sesion_completa.py, obtener_protocolo_sesion_dia()), ej.
            "binaural_theta", "solfeggio_isocronico_528Hz",
            "paisaje_biofilico", "preferencia".

    Returns:
        Optional[dict]: {"tipo_estimulo": str, "frecuencia_hz": Optional[float]}
            si el bloque es un estímulo reconocido (solfeggio_isocronico/
            paisaje/solfeggio/binaural/isocronico/preferencia — ver
            _TIPOS_ESTIMULO); None si es un bloque de reposo/silencio
            (baseline, descansoN, cierre, estabilizacion) — esos no van a
            la tabla "pruebas", solo se usan para el baseline de
            "sesiones". Para "paisaje_biofilico", frecuencia_hz siempre
            queda en None: es ruido filtrado, no tiene una única
            frecuencia portadora que reportar.
    """
    nombre_normalizado = nombre_bloque.lower()
    tipo_estimulo = next((tipo for tipo in _TIPOS_ESTIMULO if tipo in nombre_normalizado), None)
    if tipo_estimulo is None:
        return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*hz", nombre_normalizado)
    if match:
        frecuencia_hz: Optional[float] = float(match.group(1))
    else:
        banda = next((banda for banda in _BANDA_A_HZ if banda in nombre_normalizado), None)
        frecuencia_hz = _BANDA_A_HZ.get(banda) if banda else None

    return {"tipo_estimulo": tipo_estimulo, "frecuencia_hz": frecuencia_hz}


class BaseDatosTesis:
    """Puerta de entrada única a SQL Server (participantes, sesiones, pruebas).

    Attributes:
        server (str): Servidor\\instancia de SQL Server (ej. "DESKTOP-059IB6K\\SQLEXPRESS").
        database (str): Nombre de la base de datos.
        usuario (str): Usuario de SQL Server.
        password (str): Password del usuario.
        driver (str): Nombre del driver ODBC instalado.
        max_reintentos (int): Reintentos ante fallo de conexión, antes de propagar el error.
        conexion (Optional[pyodbc.Connection]): Conexión activa reutilizada entre llamadas, o None.
    """

    def __init__(self, ruta_env: Optional[Path] = None, max_reintentos: int = 3) -> None:
        """Carga las credenciales desde .env, sin conectar todavía.

        Args:
            ruta_env: Ruta al archivo .env. None usa RUTA_ENV_DEFAULT
                (C:\\Tesis_Kevin\\.env).
            max_reintentos: Máximo de reintentos ante fallos de conexión,
                tanto al conectar como al ejecutar cualquier consulta.
        """
        ruta_env = Path(ruta_env) if ruta_env is not None else RUTA_ENV_DEFAULT
        if ruta_env.exists():
            load_dotenv(dotenv_path=ruta_env)
        else:
            logger.warning(
                f"No se encontró el archivo .env en {ruta_env}; se intentará leer las "
                "variables de entorno del sistema (DB_SERVER, DB_DATABASE, DB_USER, DB_PASSWORD)."
            )

        self.server = os.getenv("DB_SERVER", "")
        self.database = os.getenv("DB_DATABASE", "")
        self.usuario = os.getenv("DB_USER", "")
        self.password = os.getenv("DB_PASSWORD", "")
        self.driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
        self.max_reintentos = max_reintentos
        self.conexion: Optional[pyodbc.Connection] = None
        # None = todavía no consultado; ver _sesiones_tiene_dia_valida()
        self._sesiones_con_dia_valida: Optional[bool] = None

        if not all([self.server, self.database, self.usuario, self.password]):
            logger.warning(
                "Faltan variables de entorno de conexión (DB_SERVER/DB_DATABASE/DB_USER/"
                "DB_PASSWORD). Revisa tu .env."
            )

    def conectar(self) -> bool:
        """Abre la conexión a SQL Server, con reintento automático.

        Returns:
            bool: True si logró conectar; False si agotó max_reintentos.
        """
        cadena = (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.usuario};"
            f"PWD={self.password};"
            "TrustServerCertificate=yes;"
        )
        for intento in range(1, self.max_reintentos + 1):
            try:
                self.conexion = pyodbc.connect(cadena, timeout=10)
                self.conexion.autocommit = False
                logger.info(f"Conectado a SQL Server ({self.server}/{self.database}).")
                return True
            except pyodbc.Error as error:
                logger.warning(f"Intento {intento}/{self.max_reintentos} de conexión falló: {error}")
                self.conexion = None
                if intento < self.max_reintentos:
                    time.sleep(1.5 * intento)

        logger.error("No se pudo conectar a SQL Server tras agotar los reintentos.")
        return False

    def desconectar(self) -> None:
        """Cierra la conexión activa, si hay una. Nunca deja una transacción abierta."""
        if self.conexion is None:
            return
        try:
            self.conexion.close()
            logger.info("Conexión a SQL Server cerrada.")
        except pyodbc.Error as error:
            logger.warning(f"Error al cerrar la conexión (se ignora, ya se descarta el objeto): {error}")
        finally:
            self.conexion = None

    def _ejecutar(self, sql: str, params: Optional[tuple] = None) -> Optional[list[dict[str, Any]]]:
        """Ejecuta sql con reintento automático si la conexión se cae a mitad de camino.

        Único punto del módulo que de verdad toca pyodbc — todos los demás
        métodos (incluido ejecutar_query) pasan por acá, así la lógica de
        reconexión/commit/rollback vive en un solo lugar.

        Args:
            sql: Sentencia SQL, con "?" como placeholders (estilo pyodbc).
            params: Parámetros posicionales de la sentencia.

        Returns:
            Optional[list[dict]]: Filas como lista de dicts si la sentencia
                devuelve un result set (SELECT, o INSERT/UPDATE con OUTPUT);
                None si no produce ninguno (INSERT/UPDATE/DELETE simples).

        Raises:
            ConnectionError: Si tras max_reintentos intentos no se pudo
                ejecutar la consulta (conexión caída de forma persistente).
        """
        ultimo_error: Optional[Exception] = None
        for intento in range(1, self.max_reintentos + 1):
            try:
                if self.conexion is None and not self.conectar():
                    raise ConnectionError("No hay conexión activa a SQL Server.")

                cursor = self.conexion.cursor()
                cursor.execute(sql, params or ())

                resultados = None
                if cursor.description is not None:
                    columnas = [columna[0] for columna in cursor.description]
                    resultados = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]

                self.conexion.commit()
                cursor.close()
                return resultados

            except pyodbc.Error as error:
                ultimo_error = error
                logger.warning(f"Intento {intento}/{self.max_reintentos} de consulta falló: {error}")
                if self.conexion is not None:
                    try:
                        self.conexion.rollback()
                    except pyodbc.Error:
                        pass
                self.desconectar()  # fuerza reconexión limpia en el próximo intento
                if intento < self.max_reintentos:
                    time.sleep(1.0 * intento)

        logger.error(f"La consulta falló tras {self.max_reintentos} intentos: {ultimo_error}")
        raise ConnectionError(f"No se pudo ejecutar la consulta tras {self.max_reintentos} intentos: {ultimo_error}")

    def ejecutar_query(self, sql: str, params: Optional[tuple] = None) -> Optional[list[dict[str, Any]]]:
        """Ejecuta cualquier sentencia SQL custom (SELECT o de escritura), con reintento automático.

        Método genérico para consultas que no encajan en los métodos
        específicos de abajo (ej. reportes ad-hoc, limpieza de datos de
        prueba).

        Args:
            sql: Sentencia SQL, con "?" como placeholders.
            params: Parámetros posicionales de la sentencia.

        Returns:
            Optional[list[dict]]: Ver _ejecutar().
        """
        return self._ejecutar(sql, params)

    def registrar_participante(
        self,
        id_participante: str,
        edad: Optional[int],
        genero: Optional[str],
        observaciones: str = "",
        consentimiento: bool = True,
    ) -> bool:
        """Registra un nuevo participante, validando que no exista ya.

        Args:
            id_participante: Identificador del participante, ej. "P001".
            edad: Edad en años. None si no se conoce (columna nullable).
            genero: Género autoreportado. None si no se conoce.
            observaciones: Notas libres (máx. 500 caracteres en la tabla).
            consentimiento: Si el participante dio consentimiento informado
                (default True — se asume que solo se llega a este método
                tras haberlo obtenido en el protocolo presencial).

        Returns:
            bool: True si se registró; False si ya existía (se avisa por
                log, no se sobreescribe) o si falló la inserción.
        """
        try:
            existentes = self._ejecutar(
                "SELECT 1 FROM participantes WHERE id_participante = ?", (id_participante,)
            )
            if existentes:
                logger.warning(f"El participante {id_participante} ya está registrado; no se vuelve a insertar.")
                return False

            self._ejecutar(
                """
                INSERT INTO participantes
                    (id_participante, edad, genero, fecha_registro, consentimiento, observaciones)
                VALUES (?, ?, ?, GETDATE(), ?, ?)
                """,
                (id_participante, edad, genero, consentimiento, observaciones or None),
            )
            logger.info(f"Participante {id_participante} registrado.")
            return True
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo registrar al participante {id_participante}: {error}")
            return False

    def _sesiones_tiene_dia_valida(self) -> bool:
        """Indica si 'sesiones' ya tiene las columnas dia_sesion y valida (una consulta, luego cacheado).

        Permite que crear_sesion() siga funcionando en una base que todavía no
        corrió database/migrar_agregar_dia_valida.py, en vez de fallar en plena
        captura con un participante frente al equipo.

        Returns:
            bool: True si ambas columnas existen; False si falta alguna o la
                consulta falla.
        """
        if self._sesiones_con_dia_valida is None:
            try:
                filas = self._ejecutar(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = 'sesiones' AND COLUMN_NAME IN ('dia_sesion', 'valida')"
                )
                self._sesiones_con_dia_valida = len(filas or []) == 2
            except (pyodbc.Error, ConnectionError) as error:
                logger.warning(f"No se pudo consultar las columnas de 'sesiones': {error}")
                return False
        return self._sesiones_con_dia_valida

    def crear_sesion(
        self,
        id_participante: str,
        hr_baseline: Optional[float],
        rmssd_baseline: Optional[float],
        sdnn_baseline: Optional[float],
        notas: str = "",
        usa_vr: bool = False,
        dia_sesion: Optional[int] = None,
        valida: bool = True,
    ) -> Optional[int]:
        """Crea la fila de una nueva sesión y devuelve su id generado.

        Args:
            id_participante: Participante dueño de la sesión (debe existir
                ya en 'participantes', por la FK).
            hr_baseline: HR promedio del bloque baseline, o None.
            rmssd_baseline: RMSSD del bloque baseline, o None.
            sdnn_baseline: SDNN del bloque baseline, o None.
            notas: Notas libres (máx. 500 caracteres).
            usa_vr: Si la sesión corrió con Meta Quest 2 (ver usar_vr en
                ejecutar_sesion_completa(), sesion_completa.py) — puramente
                informativo, no afecta ninguna métrica.
            dia_sesion: Día del protocolo (1 a 5). None si no se conoce. Se
                ignora (con una advertencia) si la tabla aún no tiene la
                columna — ver database/migrar_agregar_dia_valida.py.
            valida: False si la sesión nace descartada del análisis (p. ej. se
                sabe de antemano que la señal falló). Lo normal es True y
                marcarla después con marcar_sesion_invalida().

        Returns:
            Optional[int]: id_sesion (IDENTITY) generado por SQL Server,
                o None si falló la inserción.
        """
        try:
            if self._sesiones_tiene_dia_valida():
                filas = self._ejecutar(
                    """
                    INSERT INTO sesiones
                        (id_participante, fecha_hora, hr_baseline, rmssd_baseline, sdnn_baseline, notas, usa_vr, dia_sesion, valida)
                    OUTPUT INSERTED.id_sesion
                    VALUES (?, GETDATE(), ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id_participante,
                        _limpiar_valor(hr_baseline),
                        _limpiar_valor(rmssd_baseline),
                        _limpiar_valor(sdnn_baseline),
                        notas or None,
                        usa_vr,
                        dia_sesion,
                        valida,
                    ),
                )
            else:
                if dia_sesion is not None:
                    logger.warning(
                        "La tabla 'sesiones' no tiene dia_sesion/valida: el día no se guarda. "
                        "Correr database/migrar_agregar_dia_valida.py."
                    )
                filas = self._ejecutar(
                    """
                    INSERT INTO sesiones (id_participante, fecha_hora, hr_baseline, rmssd_baseline, sdnn_baseline, notas, usa_vr)
                    OUTPUT INSERTED.id_sesion
                    VALUES (?, GETDATE(), ?, ?, ?, ?, ?)
                    """,
                    (
                        id_participante,
                        _limpiar_valor(hr_baseline),
                        _limpiar_valor(rmssd_baseline),
                        _limpiar_valor(sdnn_baseline),
                        notas or None,
                        usa_vr,
                    ),
                )
            id_sesion = filas[0]["id_sesion"] if filas else None
            logger.info(f"Sesión {id_sesion} creada para {id_participante} (usa_vr={usa_vr}, día={dia_sesion}).")
            return id_sesion
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo crear la sesión para {id_participante}: {error}")
            return None

    def marcar_sesion_invalida(self, id_sesion: int, motivo: str = "") -> bool:
        """Descarta una sesión del análisis (valida = 0) sin borrar sus datos.

        Pensado para sesiones repetidas o con señal cardíaca defectuosa: el
        análisis (analisis_intrasujeto.py) ignora las sesiones inválidas, así
        una sesión repetida no cuenta doble. El motivo se anexa a 'notas'.

        Args:
            id_sesion: Sesión a descartar.
            motivo: Razón breve (ej. "sensor se desconectó a los 3 min").

        Returns:
            bool: True si se marcó; False si la tabla aún no tiene la columna
                'valida' o falló la consulta.
        """
        if not self._sesiones_tiene_dia_valida():
            logger.error("Falta la columna 'valida': correr database/migrar_agregar_dia_valida.py primero.")
            return False
        try:
            self._ejecutar(
                """
                UPDATE sesiones
                SET valida = 0,
                    notas = LEFT(COALESCE(notas + ' | ', '') + ?, 500)
                WHERE id_sesion = ?
                """,
                (f"INVALIDA: {motivo}" if motivo else "INVALIDA", id_sesion),
            )
            logger.info(f"Sesión {id_sesion} marcada como inválida ({motivo or 'sin motivo'}).")
            return True
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo marcar la sesión {id_sesion} como inválida: {error}")
            return False

    def actualizar_ruta_preferencia(self, id_participante: str, ruta_preferencia_wav: str) -> bool:
        """Guarda/actualiza la ruta del audio de preferencia personal de un
        participante YA registrado — pensado para el Día 2 (o cualquier momento
        en que el investigador la complete/corrija), así el Día 2 de ese mismo
        participante la trae precargada sin volver a escribirla (ver
        _autocompletar_participante_existente() en app_investigador.py).

        Requiere la columna ruta_preferencia_wav en la tabla participantes (ver
        el ALTER TABLE en el docstring del módulo, sección ESQUEMA DE LA BASE)
        — si esa columna no existe todavía, esto falla igual que cualquier
        otro error de SQL: se loggea y devuelve False, sin romper el registro
        del participante (que ya se hizo antes, por separado).

        Args:
            id_participante: Identificador del participante.
            ruta_preferencia_wav: Ruta al WAV de preferencia (como string).

        Returns:
            bool: True si se actualizó correctamente; False si falló.
        """
        try:
            self._ejecutar(
                "UPDATE participantes SET ruta_preferencia_wav = ? WHERE id_participante = ?",
                (ruta_preferencia_wav, id_participante),
            )
            return True
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo actualizar la ruta de preferencia de {id_participante}: {error}")
            return False

    def actualizar_duracion_sesion(self, id_sesion: int, duracion_seg: int) -> bool:
        """Actualiza duracion_seg de una sesión ya creada (se conoce recién al terminarla).

        Args:
            id_sesion: id de la sesión a actualizar.
            duracion_seg: Duración total real de la sesión, en segundos.

        Returns:
            bool: True si se actualizó correctamente; False si falló.
        """
        try:
            self._ejecutar(
                "UPDATE sesiones SET duracion_seg = ? WHERE id_sesion = ?",
                (_limpiar_valor(duracion_seg), id_sesion),
            )
            return True
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo actualizar la duración de la sesión {id_sesion}: {error}")
            return False

    def registrar_prueba(
        self,
        id_sesion: int,
        id_participante: str,
        tipo_estimulo: str,
        frecuencia_hz: Optional[float],
        metricas_dict: dict[str, Any],
        preferencia: Optional[str] = None,
        likert_relajacion: Optional[int] = None,
        likert_confort: Optional[int] = None,
        duracion_seg: Optional[int] = None,
    ) -> Optional[int]:
        """Registra una prueba (un estímulo probado dentro de una sesión).

        Args:
            id_sesion: Sesión a la que pertenece esta prueba.
            id_participante: Participante (redundante con sesiones.id_participante
                a propósito — así se puede filtrar 'pruebas' directo por
                participante sin JOIN, ver el esquema de la tabla).
            tipo_estimulo: "solfeggio", "binaural", "isocronico" o "preferencia".
            frecuencia_hz: Frecuencia del estímulo en Hz, o None (ej. "preferencia"
                no tiene una frecuencia fija).
            metricas_dict: Dict con las claves hr_promedio, hr_min, hr_max,
                rmssd, sdnn, pnn50, resp_por_min — todas opcionales; las
                ausentes o NaN quedan como NULL (ver _limpiar_valor()).
            preferencia: Si el participante marcó este estímulo como su
                preferido (valor libre, ej. "preferida"/"no preferida"), o
                None si no se preguntó/no aplica.
            likert_relajacion: Escala Likert de relajación autoreportada, o None.
            likert_confort: Escala Likert de confort autoreportado, o None.
            duracion_seg: Duración real de este bloque, en segundos.

        Returns:
            Optional[int]: id_prueba generado, o None si falló la inserción.
        """
        try:
            valores = (
                id_sesion,
                id_participante,
                tipo_estimulo,
                _limpiar_valor(frecuencia_hz),
                _limpiar_valor(duracion_seg),
                _limpiar_valor(metricas_dict.get("hr_promedio")),
                _limpiar_valor(metricas_dict.get("hr_min")),
                _limpiar_valor(metricas_dict.get("hr_max")),
                _limpiar_valor(metricas_dict.get("rmssd")),
                _limpiar_valor(metricas_dict.get("sdnn")),
                _limpiar_valor(metricas_dict.get("pnn50")),
                _limpiar_valor(metricas_dict.get("resp_por_min")),
                preferencia,
                _limpiar_valor(likert_relajacion),
                _limpiar_valor(likert_confort),
            )
            filas = self._ejecutar(
                """
                INSERT INTO pruebas
                    (id_sesion, id_participante, tipo_estimulo, frecuencia_hz, duracion_seg,
                     hr_promedio, hr_min, hr_max, rmssd, sdnn, pnn50, resp_por_min,
                     preferencia, likert_relajacion, likert_confort, fecha_hora)
                OUTPUT INSERTED.id_prueba
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                """,
                valores,
            )
            id_prueba = filas[0]["id_prueba"] if filas else None
            logger.info(f"Prueba {id_prueba} ({tipo_estimulo}) registrada en sesión {id_sesion}.")
            return id_prueba
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo registrar la prueba '{tipo_estimulo}' de la sesión {id_sesion}: {error}")
            return None

    def obtener_participantes(self) -> list[dict[str, Any]]:
        """Devuelve todos los participantes registrados.

        Returns:
            list[dict]: Una fila por participante (todas las columnas de
                'participantes'), o lista vacía si falla la consulta.
        """
        try:
            return self._ejecutar("SELECT * FROM participantes ORDER BY fecha_registro") or []
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo obtener la lista de participantes: {error}")
            return []

    def obtener_sesiones_participante(self, id_participante: str) -> list[dict[str, Any]]:
        """Devuelve todas las sesiones de un participante, en orden cronológico.

        Args:
            id_participante: Identificador del participante.

        Returns:
            list[dict]: Una fila por sesión, o lista vacía si falla la consulta.
        """
        try:
            return (
                self._ejecutar(
                    "SELECT * FROM sesiones WHERE id_participante = ? ORDER BY fecha_hora", (id_participante,)
                )
                or []
            )
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo obtener las sesiones de {id_participante}: {error}")
            return []

    def obtener_pruebas_sesion(self, id_sesion: int) -> list[dict[str, Any]]:
        """Devuelve todas las pruebas (estímulos) de una sesión.

        Args:
            id_sesion: Identificador de la sesión.

        Returns:
            list[dict]: Una fila por prueba, o lista vacía si falla la consulta.
        """
        try:
            return self._ejecutar("SELECT * FROM pruebas WHERE id_sesion = ? ORDER BY fecha_hora", (id_sesion,)) or []
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo obtener las pruebas de la sesión {id_sesion}: {error}")
            return []

    def siguiente_id_participante(self) -> str:
        """Genera el siguiente id_participante disponible, formato P001, P002, ...

        Busca el mayor id_participante con formato "P" + 3 dígitos y
        devuelve el siguiente número. Si no hay ninguno con ese formato
        (base vacía, o solo IDs con otro formato), empieza en "P001".

        Returns:
            str: Siguiente ID sugerido, ej. "P013".
        """
        try:
            filas = self._ejecutar(
                """
                SELECT TOP 1 id_participante FROM participantes
                WHERE id_participante LIKE 'P[0-9][0-9][0-9]'
                ORDER BY id_participante DESC
                """
            )
            if not filas:
                return "P001"
            numero_actual = int(filas[0]["id_participante"][1:])
            return f"P{numero_actual + 1:03d}"
        except (pyodbc.Error, ConnectionError) as error:
            logger.error(f"No se pudo calcular el siguiente id_participante: {error}")
            return "P001"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    bd = BaseDatosTesis()

    print("=== Conectando a SQL Server ===")
    if not bd.conectar():
        print("No se pudo conectar. Revisa tu .env y que SQL Server esté corriendo.")
        raise SystemExit(1)

    ID_PRUEBA = "P999"
    try:
        print(f"\n=== Próximo id_participante sugerido (antes de registrar {ID_PRUEBA}) ===")
        print(f"  {bd.siguiente_id_participante()}")

        print(f"\n=== Registrando participante de prueba {ID_PRUEBA} ===")
        registrado = bd.registrar_participante(
            ID_PRUEBA,
            edad=25,
            genero="F",
            observaciones="Participante de prueba generado por bd_sqlserver.py __main__",
        )
        print(f"  Registrado: {registrado}")

        print("\n=== Registrando de nuevo (debe devolver False, ya existe) ===")
        print(f"  Registrado: {bd.registrar_participante(ID_PRUEBA, 25, 'F')}")

        print("\n=== Creando sesión de prueba ===")
        id_sesion = bd.crear_sesion(
            ID_PRUEBA,
            hr_baseline=70.0,
            rmssd_baseline=45.0,
            sdnn_baseline=50.0,
            notas="Sesión de prueba (bd_sqlserver.py __main__)",
        )
        print(f"  id_sesion: {id_sesion}")
        if id_sesion is None:
            raise RuntimeError("No se pudo crear la sesión de prueba.")

        print("\n=== Registrando 4 pruebas (Solfeggio 432/528/639Hz + Preferencia) ===")
        pruebas_prueba = [
            (
                "solfeggio",
                432.0,
                {
                    "hr_promedio": 68.5,
                    "hr_min": 64.0,
                    "hr_max": 73.0,
                    "rmssd": 42.1,
                    "sdnn": 48.3,
                    "pnn50": 30.2,
                    "resp_por_min": 12.5,
                },
                None,
            ),
            (
                "solfeggio",
                528.0,
                {
                    "hr_promedio": 66.2,
                    "hr_min": 61.0,
                    "hr_max": 71.0,
                    "rmssd": 44.8,
                    "sdnn": 51.0,
                    "pnn50": 33.1,
                    "resp_por_min": 10.8,
                },
                None,
            ),
            (
                "solfeggio",
                639.0,
                {
                    "hr_promedio": 69.0,
                    "hr_min": 65.0,
                    "hr_max": 74.0,
                    "rmssd": 40.5,
                    "sdnn": 46.7,
                    "pnn50": 28.4,
                    "resp_por_min": 13.2,
                },
                None,
            ),
            (
                "preferencia",
                None,
                {
                    "hr_promedio": 65.0,
                    "hr_min": 60.0,
                    "hr_max": 70.0,
                    "rmssd": 47.3,
                    "sdnn": 53.5,
                    "pnn50": 35.6,
                    "resp_por_min": 11.4,
                },
                "preferida",
            ),
        ]
        for tipo_estimulo, frecuencia_hz, metricas, preferencia in pruebas_prueba:
            id_prueba = bd.registrar_prueba(
                id_sesion,
                ID_PRUEBA,
                tipo_estimulo,
                frecuencia_hz,
                metricas,
                preferencia=preferencia,
                likert_relajacion=4,
                likert_confort=5,
                duracion_seg=60,
            )
            etiqueta = f"{tipo_estimulo} {frecuencia_hz}Hz" if frecuencia_hz else tipo_estimulo
            print(f"  {etiqueta} -> id_prueba={id_prueba}")

        bd.actualizar_duracion_sesion(id_sesion, 480)

        print("\n=== Consultando datos insertados ===")
        print("Participantes:")
        for fila in bd.obtener_participantes():
            print(f"  {fila}")
        print(f"Sesiones de {ID_PRUEBA}:")
        for fila in bd.obtener_sesiones_participante(ID_PRUEBA):
            print(f"  {fila}")
        print(f"Pruebas de la sesión {id_sesion}:")
        for fila in bd.obtener_pruebas_sesion(id_sesion):
            print(f"  {fila}")

    finally:
        print(f"\n=== Limpiando: borrando participante de prueba {ID_PRUEBA} ===")
        try:
            bd.ejecutar_query("DELETE FROM pruebas WHERE id_participante = ?", (ID_PRUEBA,))
            bd.ejecutar_query("DELETE FROM sesiones WHERE id_participante = ?", (ID_PRUEBA,))
            bd.ejecutar_query("DELETE FROM participantes WHERE id_participante = ?", (ID_PRUEBA,))
            print("  Limpieza completada.")
        except Exception as error:
            print(f"  Advertencia: no se pudo limpiar completamente ({error}). Borra {ID_PRUEBA} manualmente si hace falta.")

        bd.desconectar()
