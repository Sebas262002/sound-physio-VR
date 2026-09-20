"""Reproduce los estímulos generados por generador_tonos.py y registra eventos con timestamps.

Este módulo es el que "orquesta" qué estímulo suena cuándo durante una
sesión, y —más importante— deja un registro exacto (JSON de eventos) de a
qué hora real empezó y terminó cada bloque.

Ese JSON de eventos es la CLAVE MAESTRA de sincronización del sistema: la
sesión genera tres flujos de datos por separado —

    1. python/sensor/capturar_sesion.py   → HR/R-R del sensor cardíaco
    2. python/audio/capturar_respiracion.py → audio de respiración
    3. python/audio/reproductor_estimulos.py (este módulo) → estímulos sonoros

— cada uno con sus propios timestamps en segundos desde su propio inicio.
Sin el JSON de eventos no habría forma de saber, mirando el CSV del sensor
cardíaco, en qué segundo exacto empezó a sonar "solfeggio_528Hz" para poder
comparar la respuesta fisiológica de ESE tramo específico. Todos los
módulos del sistema usan time.monotonic() como reloj común (nunca
time.time(), que puede saltar hacia atrás o adelante si el sistema
operativo ajusta la hora) precisamente para que estos tres registros
puedan alinearse de forma confiable si se inician con una referencia común.

¿Por qué reproducción síncrona (bloquea hasta terminar)? Porque
necesitamos saber el instante REAL en que cada estímulo terminó de sonar,
no solo cuándo se le pidió al sistema operativo que lo reprodujera. Abrir
el dispositivo de audio y empezar a reproducir tiene una latencia variable
(ver la nota sobre esto en capturar_respiracion.py); si el siguiente bloque
del protocolo empezara sin esperar a que el audio realmente haya
terminado, el timestamp registrado no reflejaría lo que el participante
escuchó de verdad.

¿Por qué sd.OutputStream explícito y NO sd.play()/sd.stop()/sd.wait()?
(Fix aplicado 16/08/2026, ver bug de respiración en ceros durante P01/P09).
sd.play(), sd.rec(), sd.stop() y sd.wait() son funciones de conveniencia
de sounddevice que comparten un único "stream activo" a nivel de módulo
(variable global `_last_callback`). Interalmente, sd.play() empieza
llamando a stop() (sounddevice.py, _CallbackContext.start_stream): eso
significa que si capturar_respiracion.py ya tiene una grabación en curso
con sd.rec() cuando este módulo llama a sd.play() para el estímulo, ese
sd.play() CIERRA la grabación en curso — el micrófono deja de recibir
audio real y el resto del buffer queda en ceros/basura sin inicializar.
Esto se confirmó reproduciendo el bug con un script mínimo y leyendo el
código fuente de sounddevice (línea "stop()  # Stop previous
playback/recording" dentro de start_stream()). La solución es no usar
las funciones de conveniencia: sd.OutputStream (acá) y sd.InputStream
(en capturar_respiracion.py) son objetos de stream independientes, cada
uno con su propio callback y su propio ciclo de vida — no tocan el
estado global compartido, así que pueden correr en simultáneo sin que
uno le corte el paso al otro.
"""

import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


class ReproductorEstimulos:
    """Reproduce estímulos WAV y registra el protocolo experimental ejecutado.

    Attributes:
        device_id (Optional[int]): Índice del dispositivo de salida a usar
            (ver listar_dispositivos_audio.py). None = usar el default del
            sistema (típicamente los audífonos del participante).
    """

    def __init__(self, device_id: Optional[int] = None) -> None:
        """Inicializa el reproductor.

        Args:
            device_id: Índice del dispositivo de salida. None usa el
                dispositivo de salida por defecto del sistema.
        """
        self.device_id = device_id

    def _nombre_dispositivo_salida(self) -> str:
        """Resuelve el nombre legible del dispositivo de salida en uso."""
        if self.device_id is not None:
            return sd.query_devices(self.device_id)["name"]
        return sd.query_devices(kind="output")["name"]

    @staticmethod
    def _mostrar_progreso(transcurrido: float, total: float) -> None:
        """Imprime una barra de progreso de una línea en la consola."""
        ancho_barra = 30
        progreso = min(transcurrido / total, 1.0) if total > 0 else 1.0
        llenado = int(ancho_barra * progreso)
        barra = "#" * llenado + "-" * (ancho_barra - llenado)
        print(f"\r  [{barra}] {progreso * 100:5.1f}%  {transcurrido:4.1f}/{total:.1f}s", end="", flush=True)

    def _esperar_con_progreso(self, duracion_seg: float) -> None:
        """Espera duracion_seg segundos mostrando una barra de progreso (para bloques de silencio)."""
        tiempo_inicio = time.monotonic()
        while (transcurrido := time.monotonic() - tiempo_inicio) < duracion_seg:
            self._mostrar_progreso(transcurrido, duracion_seg)
            time.sleep(0.1)
        self._mostrar_progreso(duracion_seg, duracion_seg)
        print()

    @staticmethod
    def _preparar_datos_para_stream(datos: np.ndarray) -> np.ndarray:
        """Asegura que el array de audio tenga forma (muestras, canales), como espera sd.OutputStream."""
        if datos.ndim == 1:
            return datos.reshape(-1, 1)
        return datos

    def _crear_callback_loop(self, datos: np.ndarray) -> tuple:
        """Crea el callback de un sd.OutputStream que reproduce datos en loop indefinido.

        Returns:
            tuple: (callback, posicion) — posicion es un dict mutable
                {"i": int} con el índice de lectura actual, expuesto para
                que quien lo use pueda inspeccionar/reiniciar el avance.
        """
        posicion = {"i": 0}
        total_muestras = len(datos)

        def callback(outdata, frames, time_info, status):
            i = posicion["i"]
            fin = i + frames
            if fin <= total_muestras:
                outdata[:] = datos[i:fin]
                posicion["i"] = fin if fin < total_muestras else 0
            else:
                # Se cruza el final del array: completar con el inicio (loop)
                resto = fin - total_muestras
                outdata[: total_muestras - i] = datos[i:]
                outdata[total_muestras - i:] = datos[:resto]
                posicion["i"] = resto

        return callback, posicion

    def reproducir(self, ruta_wav: Path) -> dict:
        """Reproduce un WAV de forma síncrona (bloquea hasta que termina).

        Usa un sd.OutputStream explícito (no sd.play()/sd.wait()) para no
        interferir con una grabación simultánea de capturar_respiracion.py
        — ver la nota en el docstring del módulo sobre por qué sd.play()
        no es seguro para reproducción/grabación concurrentes.

        Args:
            ruta_wav: Ruta al archivo .wav a reproducir.

        Returns:
            dict: timestamp_inicio, timestamp_fin (float, monotonic),
                ruta_archivo, nombre_archivo, duracion_seg, device_used.
        """
        ruta_wav = Path(ruta_wav)
        datos, sr = sf.read(ruta_wav, dtype="float32")
        datos = self._preparar_datos_para_stream(datos)
        duracion_seg = len(datos) / sr
        device_used = self._nombre_dispositivo_salida()

        print(f"\n>>> Reproduciendo: {ruta_wav.name} ({duracion_seg:.1f}s, device={device_used})")

        callback, _ = self._crear_callback_loop(datos)

        timestamp_inicio = time.monotonic()
        with sd.OutputStream(
            samplerate=sr, channels=datos.shape[1], device=self.device_id, callback=callback
        ):
            while (transcurrido := time.monotonic() - timestamp_inicio) < duracion_seg:
                self._mostrar_progreso(transcurrido, duracion_seg)
                time.sleep(0.1)
            self._mostrar_progreso(duracion_seg, duracion_seg)
            print()
        timestamp_fin = time.monotonic()

        return {
            "timestamp_inicio": round(timestamp_inicio, 3),
            "timestamp_fin": round(timestamp_fin, 3),
            "ruta_archivo": str(ruta_wav),
            "nombre_archivo": ruta_wav.name,
            "duracion_seg": round(duracion_seg, 3),
            "device_used": device_used,
        }

    def reproducir_por_duracion(self, ruta_wav: Path, duracion_seg: float) -> dict:
        """Reproduce ruta_wav durante EXACTAMENTE duracion_seg segundos.

        A diferencia de reproducir() (donde el bloque dura lo que dure el
        WAV), acá la duración del BLOQUE manda: si el WAV es más corto que
        duracion_seg, se repite en loop hasta completar el tiempo; si es
        más largo, se corta al llegar a duracion_seg. Pensado para
        protocolos donde el nombre del bloque define cuánto debe durar
        (ej. "solfeggio_528Hz" de 45s en el protocolo) independientemente
        de cuánto dure el archivo de audio_estimulos/ que se le asocie.

        Usa un sd.OutputStream explícito con un callback que hace el loop
        manualmente sobre el array (en vez de sd.play(..., loop=True) +
        sd.stop()) — ver la nota en el docstring del módulo: sd.play()
        interrumpe cualquier sd.rec() de capturar_respiracion.py que esté
        corriendo en simultáneo porque ambos comparten estado global.

        Args:
            ruta_wav: Ruta al archivo .wav a reproducir.
            duracion_seg: Duración exacta que debe durar la reproducción.

        Returns:
            dict: timestamp_inicio, timestamp_fin (float, monotonic),
                ruta_archivo, nombre_archivo, duracion_wav_seg (duración
                real del archivo), duracion_real_seg (cuánto duró la
                reproducción de verdad, debería ser ≈duracion_seg),
                device_used.
        """
        ruta_wav = Path(ruta_wav)
        datos, sr = sf.read(ruta_wav, dtype="float32")
        datos = self._preparar_datos_para_stream(datos)
        duracion_wav = len(datos) / sr
        device_used = self._nombre_dispositivo_salida()

        modo = "loop" if duracion_wav < duracion_seg else "corte"
        print(
            f"\n>>> Reproduciendo: {ruta_wav.name} (WAV={duracion_wav:.1f}s, "
            f"bloque={duracion_seg:.1f}s, modo={modo}, device={device_used})"
        )

        callback, _ = self._crear_callback_loop(datos)

        timestamp_inicio = time.monotonic()
        with sd.OutputStream(
            samplerate=sr, channels=datos.shape[1], device=self.device_id, callback=callback
        ):
            while (transcurrido := time.monotonic() - timestamp_inicio) < duracion_seg:
                self._mostrar_progreso(transcurrido, duracion_seg)
                time.sleep(0.1)
            self._mostrar_progreso(duracion_seg, duracion_seg)
            print()
        # Salir del "with" detiene y cierra el stream exactamente al llegar a duracion_seg
        timestamp_fin = time.monotonic()

        return {
            "timestamp_inicio": round(timestamp_inicio, 3),
            "timestamp_fin": round(timestamp_fin, 3),
            "ruta_archivo": str(ruta_wav),
            "nombre_archivo": ruta_wav.name,
            "duracion_wav_seg": round(duracion_wav, 3),
            "duracion_real_seg": round(timestamp_fin - timestamp_inicio, 3),
            "device_used": device_used,
        }

    def reproducir_protocolo(
        self,
        protocolo: list[dict],
        t0_externo: Optional[float] = None,
        estado_compartido: Optional[dict] = None,
        silencioso: bool = False,
        avance_instantaneo: bool = True,
    ) -> list[dict]:
        """Ejecuta en orden una lista de bloques de estímulo/silencio.

        Cada bloque de protocolo es un dict con "tipo" ("estimulo" o
        "silencio"), "nombre", y "ruta" (solo si tipo="estimulo") o
        "duracion_seg" (solo si tipo="silencio"; también requerido en
        bloques "estimulo" cuando silencioso=True, ver abajo).

        Args:
            protocolo: Lista de bloques a ejecutar en orden (ver
                construir_protocolo_ejemplo() para el formato exacto).
            t0_externo: Referencia de tiempo (time.monotonic()) a usar como
                "inicio de protocolo" en vez de capturar una propia. Se usa
                cuando este hilo corre en paralelo con la captura cardíaca
                y de audio de la misma sesión (ver python/sesion_completa.py),
                para que los tres registros compartan la misma escala de
                tiempo. Ignorado si silencioso=True. None = comportamiento
                normal (usa su propio time.monotonic() al arrancar).
            estado_compartido: dict compartido con el hilo del sensor
                cardíaco (ver CapturaSesion.ejecutar() en
                python/sensor/capturar_sesion.py). Justo ANTES de empezar
                cada bloque (antes de reproducir el WAV o de esperar el
                silencio), se actualiza
                estado_compartido["estimulo_actual"] = nombre del bloque,
                para que el sensor sepa en tiempo real qué está sonando
                de verdad — en vez de que el sensor tenga que asumir un
                cronograma nominal que no contempla la latencia real de
                abrir el dispositivo de audio. Al terminar el protocolo
                (incluyendo si falla a mitad de camino), se pone en "fin"
                para que el sensor sepa que debe dejar de leer.
            silencioso: Si True, NO reproduce audio de verdad (no llama
                sd.play()/sd.wait()). En este modo, los bloques "estimulo"
                TAMBIÉN deben traer "duracion_seg" (no hay un WAV real del
                que leerla). Ver avance_instantaneo para la diferencia
                entre las dos variantes de este modo.
            avance_instantaneo: Solo aplica si silencioso=True. Si True
                (default), calcula los eventos sumando duraciones sin
                ningún time.sleep() — instantáneo, pensado para generar
                datasets sintéticos rápido donde nada depende de avanzar
                en tiempo real (ver python/simulador_multiparticipante.py).
                Si False, SÍ espera con time.sleep(duracion) en cada
                bloque (tiempo real de verdad, solo que sin reproducir
                audio) — necesario para probar un sensor real en paralelo
                (ver python/sesion_completa.py, usar_sensor_real=True): con
                avance_instantaneo=True ahí, este hilo notificaría "fin"
                casi al instante y cortaría la captura del sensor después
                de una sola lectura.

        Returns:
            list[dict]: Un evento por bloque, con nombre, tipo, t_inicio y
                t_fin (segundos desde que empezó el protocolo; para
                bloques "estimulo" incluye también "ruta" si el bloque la trae).

        Raises:
            ValueError: Si algún bloque tiene un "tipo" que no es
                "estimulo" ni "silencio", o si falta "duracion_seg" en un
                bloque "estimulo" estando silencioso=True.
        """
        total_bloques = len(protocolo)

        if silencioso:
            return self._reproducir_protocolo_silencioso(protocolo, estado_compartido, avance_instantaneo)

        eventos = []
        tiempo_inicio_protocolo = t0_externo if t0_externo is not None else time.monotonic()

        print(f"=== Iniciando protocolo de {total_bloques} bloques ===")

        for idx, bloque in enumerate(protocolo, start=1):
            # Se notifica ANTES de empezar a reproducir/esperar el bloque, para que el
            # sensor vea el cambio en el instante real en que el bloque empieza de verdad
            if estado_compartido is not None:
                estado_compartido["estimulo_actual"] = bloque["nombre"]

            print(f"\n[Bloque {idx}/{total_bloques}] '{bloque['nombre']}' ({bloque['tipo']})")

            if bloque["tipo"] == "estimulo":
                # Si el bloque trae su propia duracion_seg, esta MANDA sobre la duración
                # natural del WAV (se repite en loop o se corta, ver reproducir_por_duracion());
                # si no la trae, comportamiento original: el bloque dura lo que dure el WAV
                if "duracion_seg" in bloque:
                    resultado = self.reproducir_por_duracion(bloque["ruta"], bloque["duracion_seg"])
                else:
                    resultado = self.reproducir(bloque["ruta"])

                t_inicio_evento = round(resultado["timestamp_inicio"] - tiempo_inicio_protocolo, 3)
                t_fin_evento = round(resultado["timestamp_fin"] - tiempo_inicio_protocolo, 3)
                evento = {
                    "nombre": bloque["nombre"],
                    "tipo": "estimulo",
                    "t_inicio": t_inicio_evento,
                    "t_fin": t_fin_evento,
                    "ruta": resultado["ruta_archivo"],
                    "audio_reproducido": {
                        "ruta": resultado["ruta_archivo"],
                        "duracion_real_seg": resultado.get("duracion_real_seg", resultado.get("duracion_seg")),
                        "t_inicio": t_inicio_evento,
                        "t_fin": t_fin_evento,
                    },
                }
            elif bloque["tipo"] == "silencio":
                t_inicio_abs = time.monotonic()
                self._esperar_con_progreso(bloque["duracion_seg"])
                t_fin_abs = time.monotonic()
                evento = {
                    "nombre": bloque["nombre"],
                    "tipo": "silencio",
                    "t_inicio": round(t_inicio_abs - tiempo_inicio_protocolo, 3),
                    "t_fin": round(t_fin_abs - tiempo_inicio_protocolo, 3),
                }
            else:
                raise ValueError(
                    f"Tipo de bloque desconocido: '{bloque['tipo']}' en '{bloque['nombre']}'"
                )

            eventos.append(evento)

        if estado_compartido is not None:
            estado_compartido["estimulo_actual"] = "fin"

        return eventos

    def _reproducir_protocolo_silencioso(
        self,
        protocolo: list[dict],
        estado_compartido: Optional[dict],
        avance_instantaneo: bool = True,
    ) -> list[dict]:
        """Calcula los eventos del protocolo sin reproducir audio.

        Tiene dos variantes, según avance_instantaneo:

        - avance_instantaneo=True (default): reloj puramente nominal (un
          contador float que arranca en 0.0, sin ningún time.sleep()).
          Pensado para generar datasets sintéticos rápido — ver
          python/simulador_multiparticipante.py, donde reproducir 6
          sesiones completas en tiempo real tomaría minutos sin necesidad,
          ya que ahí nada más en el sistema depende de avanzar en tiempo
          real (el sensor también es instantáneo, ver _generar_lecturas()
          en ese módulo).

        - avance_instantaneo=False: SÍ espera con time.sleep(duracion) en
          cada bloque, en tiempo real de verdad — nada más que sin llamar
          sd.play()/sd.wait(). Pensado para probar un sensor REAL (ej.
          SensorWahoo) sin depender de la biblioteca de audio: el sensor
          necesita que pase tiempo de pared de verdad para poder tomar
          lecturas durante cada bloque (ver python/sesion_completa.py,
          usar_sensor_real=True). Con avance_instantaneo=True aquí, el
          hilo de estímulos terminaría en microsegundos y notificaría
          "fin" casi al instante, cortando la captura del sensor real
          después de una sola lectura — este modo evita exactamente eso.

        Args:
            protocolo: Bloques con "duracion_seg" explícito (también en
                los de tipo "estimulo", ya que no hay WAV real del que leerla).
            estado_compartido: dict a notificar en tiempo real (ver
                reproducir_protocolo()).
            avance_instantaneo: Ver arriba.
        """
        eventos = []
        total_bloques = len(protocolo)
        modo = "instantáneo" if avance_instantaneo else "tiempo real, sin audio"
        print(f"=== Calculando protocolo de {total_bloques} bloques (modo silencioso, {modo}) ===")

        tiempo_actual = 0.0  # solo se usa en el modo instantáneo
        tiempo_inicio_real = time.monotonic()  # solo se usa en el modo tiempo real

        for bloque in protocolo:
            if estado_compartido is not None:
                estado_compartido["estimulo_actual"] = bloque["nombre"]

            duracion = bloque.get("duracion_seg")
            if duracion is None:
                raise ValueError(
                    f"Bloque '{bloque['nombre']}' sin 'duracion_seg': en modo silencioso "
                    "todos los bloques (incluidos los de tipo 'estimulo') deben traerla, "
                    "porque no hay un WAV real del que leerla."
                )

            if avance_instantaneo:
                t_inicio_bloque = tiempo_actual
                t_fin_bloque = tiempo_actual + duracion
                tiempo_actual = t_fin_bloque
            else:
                t_inicio_bloque = time.monotonic() - tiempo_inicio_real
                time.sleep(duracion)  # avanza en tiempo real de verdad, sin reproducir nada
                t_fin_bloque = time.monotonic() - tiempo_inicio_real

            evento = {
                "nombre": bloque["nombre"],
                "tipo": bloque["tipo"],
                "t_inicio": round(t_inicio_bloque, 3),
                "t_fin": round(t_fin_bloque, 3),
            }
            if bloque["tipo"] == "estimulo" and "ruta" in bloque:
                evento["ruta"] = str(bloque["ruta"])

            eventos.append(evento)

        if estado_compartido is not None:
            estado_compartido["estimulo_actual"] = "fin"

        return eventos

    def guardar_eventos(
        self, eventos: list[dict], ruta_json: Path, metadata: Optional[dict] = None
    ) -> Path:
        """Guarda la lista de eventos del protocolo en un JSON.

        Si metadata es None (default), guarda la lista de eventos tal cual
        (formato original, compatible con todo lo que ya lee este JSON —
        ej. python/analisis/sincronizador.py, python/simulador_multiparticipante.py).
        Si se indica metadata, guarda en cambio un objeto
        {"metadata": metadata, "eventos": eventos} — usado por
        python/sesion_completa.py para registrar, por ejemplo, el período
        de estabilización aplicado antes del protocolo.

        Args:
            eventos: Lista de eventos devuelta por reproducir_protocolo().
            ruta_json: Ruta destino del archivo .json (se crean las carpetas padre).
            metadata: dict opcional con información adicional de la sesión.

        Returns:
            Path: ruta_json.
        """
        ruta_json = Path(ruta_json)
        ruta_json.parent.mkdir(parents=True, exist_ok=True)

        contenido = {"metadata": metadata, "eventos": eventos} if metadata is not None else eventos

        with open(ruta_json, "w", encoding="utf-8") as archivo_json:
            json.dump(contenido, archivo_json, indent=2, ensure_ascii=False)

        return ruta_json

    def _buscar_estimulo(self, carpeta: Path, patron: str) -> Path:
        """Busca en carpeta el primer WAV cuyo nombre contenga patron.

        Se busca por substring (no por nombre exacto) porque los archivos
        de generador_tonos.py incluyen una descripción en el nombre
        (ej. "solfeggio_528Hz_transformacion_y_milagros.wav") que no
        conviene hardcodear aquí.

        Args:
            carpeta: Carpeta donde buscar (ej. audio_estimulos/solfeggio/).
            patron: Substring a buscar en el nombre de archivo (ej. "528Hz").

        Returns:
            Path: Ruta del primer WAV que coincide.

        Raises:
            FileNotFoundError: Si no hay ningún WAV que coincida.
        """
        # patron="" (ej. paisaje_biofilico, con un solo archivo en su carpeta, o
        # "solfeggio" sin sufijo "NNNHz" detectado) arma "**.wav" con el f-string de
        # abajo — error real encontrado en pruebas: pathlib rechaza "**" combinado con
        # otros caracteres en el mismo componente ("Invalid pattern: '**' can only be
        # an entire path component"). Con patron vacío no hay nada que filtrar, así
        # que se usa "*.wav" directo en vez de construir el "**" accidental.
        patron_glob = "*.wav" if not patron else f"*{patron}*.wav"
        coincidencias = sorted(Path(carpeta).glob(patron_glob))
        if not coincidencias:
            raise FileNotFoundError(
                f"No se encontró ningún WAV con '{patron}' en {carpeta}. "
                "¿Corriste generador_tonos.py primero?"
            )
        return coincidencias[0]

    def construir_protocolo_ejemplo(
        self,
        carpeta_estimulos: Path,
        preferencia_wav: Optional[Path] = None,
        duracion_silencio_seg: int = 60,
        duracion_descanso_seg: int = 30,
    ) -> list[dict]:
        """Arma un protocolo de EJEMPLO de 4 bloques de estímulo — YA NO es el
        protocolo real de la tesis (ver PROTOCOLO POR DÍA en sesion_completa.py:
        ahora es un solo estímulo por sesión, uno por día). Este método
        sobrevivió la limpieza de Fase 2 solo porque ejecutar_sesion_completa()
        todavía lo usa internamente para protocolo_corto=True (pruebas rápidas
        de humo, ver ese código) — apuntando SIEMPRE a una carpeta temporal
        autogenerada ahí mismo, nunca a audio_estimulos/ real.

        Baseline (silencio) → Solfeggio 528Hz → descanso → Binaural Alpha →
        descanso → Isocrónico Alpha → descanso → preferencia personal
        (si se indica) → cierre (silencio).

        Los WAV de Solfeggio/Binaural/Isocrónico se buscan dentro de
        carpeta_estimulos/solfeggio/, /binaurales/ e /isocronicos/ — para que
        esto funcione, carpeta_estimulos tiene que tener esa estructura con
        WAV de verdad adentro (protocolo_corto=True se encarga de generarla
        como carpeta temporal antes de llamar acá; NO uses esto apuntando a
        audio_estimulos/ real, esas subcarpetas /solfeggio/ e /isocronicos/
        ya no existen ahí).

        Args:
            carpeta_estimulos: Carpeta con la estructura /solfeggio/,
                /binaurales/, /isocronicos/ ya generada (ver arriba — NO es
                audio_estimulos/ real).
            preferencia_wav: Ruta a la canción/estímulo de preferencia
                personal del participante. Si es None, ese bloque se omite.
            duracion_silencio_seg: Duración de baseline y cierre, en
                segundos (default 60, el valor real del protocolo).
            duracion_descanso_seg: Duración de los descansos entre
                estímulos, en segundos (default 30, el valor real).

        Returns:
            list[dict]: Protocolo listo para pasar a reproducir_protocolo().
        """
        carpeta_estimulos = Path(carpeta_estimulos)

        ruta_solfeggio = self._buscar_estimulo(carpeta_estimulos / "solfeggio", "528Hz")
        ruta_binaural_alpha = self._buscar_estimulo(carpeta_estimulos / "binaurales", "alpha")
        ruta_isocronico_alpha = self._buscar_estimulo(carpeta_estimulos / "isocronicos", "alpha")

        protocolo = [
            {"tipo": "silencio", "duracion_seg": duracion_silencio_seg, "nombre": "baseline"},
            {"tipo": "estimulo", "ruta": ruta_solfeggio, "nombre": "solfeggio_528Hz"},
            {"tipo": "silencio", "duracion_seg": duracion_descanso_seg, "nombre": "descanso1"},
            {"tipo": "estimulo", "ruta": ruta_binaural_alpha, "nombre": "binaural_alpha"},
            {"tipo": "silencio", "duracion_seg": duracion_descanso_seg, "nombre": "descanso2"},
            {"tipo": "estimulo", "ruta": ruta_isocronico_alpha, "nombre": "isocronico_alpha"},
            {"tipo": "silencio", "duracion_seg": duracion_descanso_seg, "nombre": "descanso3"},
        ]

        if preferencia_wav is not None:
            protocolo.append(
                {"tipo": "estimulo", "ruta": Path(preferencia_wav), "nombre": "preferencia_usuario"}
            )
        # si preferencia_wav es None, el bloque de preferencia simplemente se omite

        protocolo.append({"tipo": "silencio", "duracion_seg": duracion_silencio_seg, "nombre": "cierre"})

        return protocolo


if __name__ == "__main__":
    import shutil
    from datetime import datetime

    from generador_tonos import GeneradorTonos

    # Para que la prueba tome ~30-40s (no los ~10 min del protocolo real),
    # se generan estímulos cortos (4s) en una carpeta temporal, con la misma
    # estructura de subcarpetas que espera construir_protocolo_ejemplo()
    CARPETA_TEST = Path(r"C:\Tesis_Kevin\datos\sesiones\_temp_estimulos_prueba")
    generador_prueba = GeneradorTonos(duracion_seg=4)
    generador_prueba.generar_solfeggio(528, CARPETA_TEST / "solfeggio" / "solfeggio_528Hz_prueba.wav")
    generador_prueba.generar_binaural(200, 10, CARPETA_TEST / "binaurales" / "binaural_10Hz_alpha_prueba.wav")
    generador_prueba.generar_isocronico(200, 10, CARPETA_TEST / "isocronicos" / "isocronico_10Hz_alpha_prueba.wav")

    reproductor = ReproductorEstimulos()
    protocolo_prueba = reproductor.construir_protocolo_ejemplo(
        CARPETA_TEST, duracion_silencio_seg=5, duracion_descanso_seg=3
    )

    eventos = reproductor.reproducir_protocolo(protocolo_prueba)

    fecha_hora = datetime.now().strftime("%Y%m%d_%H%M")
    ruta_json = Path(r"C:\Tesis_Kevin\datos\sesiones") / f"P01_test_estimulos_{fecha_hora}.json"
    reproductor.guardar_eventos(eventos, ruta_json)

    duracion_total = eventos[-1]["t_fin"] - eventos[0]["t_inicio"]
    print("\n=== Resumen ===")
    print(f"Total de bloques: {len(eventos)}")
    print(f"Duración total: {duracion_total:.1f}s")
    print(f"Eventos guardados en: {ruta_json}")

    # Los estímulos de prueba son temporales, no forman parte de la biblioteca real
    shutil.rmtree(CARPETA_TEST)
