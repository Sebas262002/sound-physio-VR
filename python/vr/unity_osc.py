"""Cliente OSC para controlar el ambiente visual (skybox) en Unity/Meta Quest 2.

SOLO VISUAL — este módulo no reproduce, graba ni toca audio de ninguna forma.
El audio de los estímulos se sigue reproduciendo 100% por sounddevice (ver
audio/reproductor_estimulos.py), por el dispositivo de salida por defecto de
Windows (los audífonos Bluetooth emparejados, si los hay) — exactamente igual
que antes de esta integración. Este módulo solo le avisa a Unity qué escena/
skybox mostrar en el Quest, en paralelo, sin acoplarse al audio para nada.

¿Por qué UDP/OSC y no otra cosa? Es liviano, sin conexión persistente que
mantener viva, y es el protocolo estándar para este tipo de puente
Python↔Unity/Processing/TouchDesigner (ver Open Sound Control, protocolo
usado originalmente para audio pero hoy genérico para control en tiempo
real). No agrega ninguna dependencia de threading nueva sobre el resto del
sistema: cada envío es un datagrama UDP independiente y no bloqueante.

CONTRATO OSC (qué debe implementar la escena de Unity del lado receptor):

    Python -> Unity, puerto `puerto` (default 8000):
        /ambiente         (string)  nombre del skybox a mostrar, ej. "SkyMorning"
        /sesion/iniciar   (string)  id_participante
        /sesion/terminar  (sin argumentos)
        /ping             (int)     puerto donde Python espera el /pong de vuelta

    Unity -> Python, puerto `puerto_escucha` (default 9000):
        /pong             (sin argumentos)  respuesta a /ping — confirma que
                                             la escena está corriendo y con
                                             su receptor OSC activo

Si la escena de Unity no implementa el lado de /ping->/pong, ping() siempre
va a dar False — no hay forma de distinguir "Unity está corriendo pero no
implementa el contrato" de "Unity apagado" sin acceso al código C# de la
escena, así que acá se documenta el contrato en vez de asumirlo a ciegas.

UDP no confirma entrega: cambiar_ambiente()/iniciar_sesion()/terminar_sesion()
devuelven True apenas el sistema operativo aceptó el paquete para transmitir,
NO que Unity lo haya recibido o aplicado — para saber si Unity está
realmente escuchando, usar ping() (el único método que espera una
respuesta real, con timeout).
"""

import logging
import threading
from typing import Optional

from pythonosc import dispatcher as osc_dispatcher
from pythonosc import osc_server
from pythonosc import udp_client

logger = logging.getLogger(__name__)


class UnityOSC:
    """Cliente OSC liviano para controlar el ambiente visual de una escena Unity.

    Attributes:
        ip (str): IP donde escucha Unity (default "127.0.0.1", misma máquina
            que la app — el Quest 2 recibe la imagen ya renderizada por Link/
            Air Link/cable, Unity sigue corriendo en la PC).
        puerto (int): Puerto UDP donde Unity recibe mensajes OSC (default 8000).
        puerto_escucha (int): Puerto UDP local donde Python espera el /pong de
            ping() (default 9000 — distinto de `puerto` a propósito, para no
            mezclar el socket de envío con el de recepción).
        timeout_ping (float): Segundos a esperar una respuesta en ping() antes
            de asumir que Unity no está disponible.
    """

    def __init__(
        self,
        ip: str = "127.0.0.1",
        puerto: int = 8000,
        puerto_escucha: int = 9000,
        timeout_ping: float = 1.5,
    ) -> None:
        """Arma el cliente OSC.

        No abre ninguna conexión todavía — UDP no tiene "conectar" de verdad,
        cada envío en _enviar() es un datagrama independiente. Si `ip`/`puerto`
        son inválidos de una forma que Python puede detectar de entrada (poco
        común, ej. una IP mal formada), la construcción del socket cliente
        falla acá mismo y se loggea, dejando el cliente en un estado inerte
        (todos los métodos públicos devuelven False después, en vez de lanzar).

        Args:
            ip: IP donde escucha Unity.
            puerto: Puerto UDP de Unity.
            puerto_escucha: Puerto UDP local para recibir el /pong de ping().
            timeout_ping: Segundos de espera máxima en ping().
        """
        self.ip = ip
        self.puerto = puerto
        self.puerto_escucha = puerto_escucha
        self.timeout_ping = timeout_ping
        try:
            self._cliente: Optional[udp_client.SimpleUDPClient] = udp_client.SimpleUDPClient(self.ip, self.puerto)
        except OSError as error:
            logger.warning(f"[UnityOSC] No se pudo crear el cliente OSC para {ip}:{puerto}: {error}")
            self._cliente = None

    def _enviar(self, direccion: str, *valores) -> bool:
        """Envía un mensaje OSC, tolerando cualquier falla de red sin propagarla.

        Args:
            direccion: Dirección OSC (ej. "/ambiente").
            *valores: 0, 1 o más argumentos del mensaje.

        Returns:
            bool: True si el envío no lanzó ninguna excepción de red (NO
                confirma que Unity lo haya recibido, ver docstring del módulo).
        """
        if self._cliente is None:
            return False
        if not valores:
            payload = None
        elif len(valores) == 1:
            payload = valores[0]
        else:
            payload = list(valores)
        try:
            self._cliente.send_message(direccion, payload)
            logger.info(f"[UnityOSC] {direccion} {valores} -> {self.ip}:{self.puerto}")
            return True
        except OSError as error:
            logger.warning(f"[UnityOSC] No se pudo enviar {direccion} a {self.ip}:{self.puerto}: {error}")
            return False

    def cambiar_ambiente(self, nombre_skybox: str) -> bool:
        """Le pide a Unity que muestre el skybox indicado.

        Args:
            nombre_skybox: Nombre del ambiente (ej. "SkyMorning", "SkySunset",
                "SkyDay", "SkyNight", "SkyEarlyMorning" — ver
                obtener_protocolo_tesis_final() en sesion_completa.py para el
                mapeo bloque -> ambiente_vr).

        Returns:
            bool: True si el mensaje se pudo enviar.
        """
        return self._enviar("/ambiente", nombre_skybox)

    def iniciar_sesion(self, id_participante: str) -> bool:
        """Avisa a Unity que arrancó una sesión, para que la escena se prepare.

        Args:
            id_participante: ID del participante de esta sesión.

        Returns:
            bool: True si el mensaje se pudo enviar.
        """
        return self._enviar("/sesion/iniciar", id_participante)

    def terminar_sesion(self) -> bool:
        """Avisa a Unity que la sesión terminó.

        Returns:
            bool: True si el mensaje se pudo enviar.
        """
        return self._enviar("/sesion/terminar")

    def ping(self) -> bool:
        """Verifica si Unity está corriendo y respondiendo de verdad.

        A diferencia de los otros métodos (que solo confirman que el paquete
        UDP salió), esto abre un servidor OSC temporal en self.puerto_escucha,
        manda "/ping <puerto_escucha>" a Unity, y espera hasta timeout_ping
        segundos un "/pong" de vuelta — ver CONTRATO OSC en el docstring del
        módulo. El servidor se cierra siempre al terminar, haya o no
        respuesta (no deja ningún socket abierto entre llamadas).

        Returns:
            bool: True si Unity respondió a tiempo. False si Unity está
                apagado, el puerto de escucha ya está ocupado por otro
                proceso, la escena no implementa /pong, o cualquier otro
                error de red — nunca lanza una excepción hacia quien llama.
        """
        if self._cliente is None:
            return False

        respondio = threading.Event()

        def _al_recibir_pong(direccion: str, *args) -> None:
            respondio.set()

        disp = osc_dispatcher.Dispatcher()
        disp.map("/pong", _al_recibir_pong)

        servidor: Optional[osc_server.BlockingOSCUDPServer] = None
        try:
            servidor = osc_server.BlockingOSCUDPServer(
                ("0.0.0.0", self.puerto_escucha), disp, timeout=self.timeout_ping
            )
            self._cliente.send_message("/ping", self.puerto_escucha)
            servidor.handle_request()  # bloquea hasta timeout_ping, o hasta que llega algo
        except OSError as error:
            logger.warning(
                f"[UnityOSC] No se pudo hacer ping a Unity (puerto de escucha "
                f"{self.puerto_escucha} ocupado, o sin red): {error}"
            )
            return False
        finally:
            if servidor is not None:
                servidor.server_close()

        if respondio.is_set():
            logger.info(f"[UnityOSC] Unity respondió el ping ({self.ip}:{self.puerto}).")
        else:
            logger.warning(
                f"[UnityOSC] Unity no respondió el ping en {self.timeout_ping}s "
                f"({self.ip}:{self.puerto}) — ¿está la escena corriendo con Play presionado?"
            )
        return respondio.is_set()
