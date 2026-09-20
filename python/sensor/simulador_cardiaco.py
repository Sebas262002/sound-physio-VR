"""Simulador de sensor cardíaco tipo Wahoo TRACKR HR.

Este módulo permite desarrollar y probar el pipeline de captura de datos
fisiológicos sin necesidad de tener el sensor físico conectado. Genera
lecturas de frecuencia cardíaca (HR) e intervalos R-R con un comportamiento
similar al de un sensor real: la HR se desplaza gradualmente hacia un valor
objetivo según la condición experimental, y los R-R incluyen variabilidad
natural (ruido gaussiano).

Cuando llegue el sensor Wahoo TRACKR HR real, este módulo se reemplaza por
uno que lea del BLE (con la librería bleak), manteniendo la misma interfaz
(cambiar_condicion, leer) para no tener que modificar el resto del sistema.
"""

import random
import time


class SimuladorCardiaco:
    """Simula un sensor cardíaco de pecho tipo Wahoo TRACKR HR.

    La frecuencia cardíaca no salta instantáneamente al valor objetivo de
    cada condición: se suaviza con un filtro exponencial (media móvil
    exponencial), igual que la respuesta fisiológica real ante un estímulo.

    Attributes:
        hr_baseline (float): Frecuencia cardíaca de reposo del participante (bpm).
        variabilidad (float): Desviación estándar del ruido aplicado a la HR
            objetivo en cada lectura (bpm). Simula fluctuaciones naturales
            como la arritmia sinusal respiratoria.
        condicion_actual (str): Condición experimental activa.
        hr_objetivo (float): HR hacia la que se está desplazando el simulador (bpm).
        hr_actual (float): Última HR generada (bpm).
        suavizado (float): Factor alpha del filtro exponencial (0 a 1).
    """

    # Ajuste de HR objetivo respecto al baseline, en bpm, por cada condición.
    # Valores negativos = relajación (baja la HR), positivos = activación (sube la HR).
    AJUSTES_CONDICION = {
        "reposo": 0.0,
        "solfeggio": -4.0,
        "binaural": -5.0,
        "isocronico": -3.0,
        "paisaje": -4.5,
        "preferencia": -6.0,
        "estimulo_negativo": 8.0,
    }

    def __init__(self, hr_baseline: float = 70.0, variabilidad: float = 8.0) -> None:
        """Inicializa el simulador en condición de reposo.

        Args:
            hr_baseline: Frecuencia cardíaca de reposo del participante (bpm).
            variabilidad: Desviación estándar del ruido de HR por lectura (bpm).
        """
        self.hr_baseline = hr_baseline
        self.variabilidad = variabilidad
        self.suavizado = 0.15  # alpha del filtro exponencial (0=no reacciona, 1=salto instantáneo)

        self.condicion_actual = "reposo"
        self.hr_objetivo = hr_baseline
        self.hr_actual = hr_baseline

        self._tiempo_inicio = time.time()

    def cambiar_condicion(self, nueva_condicion: str) -> None:
        """Cambia la condición experimental activa y recalcula la HR objetivo.

        Args:
            nueva_condicion: Una de "reposo", "solfeggio", "binaural",
                "isocronico", "paisaje", "preferencia", "estimulo_negativo".

        Raises:
            ValueError: Si nueva_condicion no es una condición reconocida.
        """
        if nueva_condicion not in self.AJUSTES_CONDICION:
            condiciones_validas = ", ".join(self.AJUSTES_CONDICION.keys())
            raise ValueError(
                f"Condición '{nueva_condicion}' no reconocida. "
                f"Debe ser una de: {condiciones_validas}"
            )

        self.condicion_actual = nueva_condicion
        self.hr_objetivo = self.hr_baseline + self.AJUSTES_CONDICION[nueva_condicion]

    def leer(self) -> dict:
        """Genera una lectura simulada del sensor.

        La HR actual se actualiza con un filtro exponencial que la acerca
        al objetivo de la condición vigente:

            hr_actual_nueva = hr_actual + suavizado * (objetivo_con_ruido - hr_actual)

        Con suavizado=0.15, cada lectura recorre el 15% de la distancia que
        falta hasta el objetivo, por lo que la transición es gradual (no un
        salto), igual que la respuesta cardíaca real ante un estímulo.

        El intervalo R-R se deriva de la HR actual (rr_ms = 60000 / hr_bpm)
        y se le suma ruido gaussiano de ~30 ms de desviación estándar, que
        es el orden de magnitud típico de la variabilidad latido-a-latido
        en reposo.

        Returns:
            dict: Con las claves:
                - timestamp (float): segundos desde que se creó el simulador.
                - hr_bpm (float): frecuencia cardíaca simulada.
                - rr_ms (float): intervalo R-R simulado, en milisegundos.
                - condicion (str): condición experimental activa.
        """
        # Ruido sobre el objetivo: simula fluctuaciones naturales de la HR
        # (respiración, actividad del sistema nervioso autónomo, etc.)
        ruido_hr = random.gauss(0, self.variabilidad)
        objetivo_con_ruido = self.hr_objetivo + ruido_hr

        # Filtro exponencial: desplaza hr_actual hacia el objetivo gradualmente
        self.hr_actual += self.suavizado * (objetivo_con_ruido - self.hr_actual)
        self.hr_actual = max(self.hr_actual, 30.0)  # evita valores fisiológicamente imposibles

        # R-R en ms a partir de la HR, con ruido gaussiano de variabilidad natural (~30 ms SD)
        rr_ms = (60000.0 / self.hr_actual) + random.gauss(0, 30)

        timestamp = time.time() - self._tiempo_inicio

        return {
            "timestamp": round(timestamp, 3),
            "hr_bpm": round(self.hr_actual, 1),
            "rr_ms": round(rr_ms, 1),
            "condicion": self.condicion_actual,
        }


if __name__ == "__main__":
    # Ejemplo de uso: 10 lecturas, cambiando a "preferencia" a la mitad
    # para observar cómo la HR desciende gradualmente hacia el nuevo objetivo.
    simulador = SimuladorCardiaco(hr_baseline=70.0, variabilidad=8.0)

    print("=== Simulación de sensor cardíaco (Wahoo TRACKR HR) ===")
    for i in range(1, 11):
        if i == 6:
            print("\n--> Cambiando condición a 'preferencia' (debería bajar la HR)\n")
            simulador.cambiar_condicion("preferencia")

        lectura = simulador.leer()
        print(
            f"[{i:02d}] t={lectura['timestamp']:6.2f}s  "
            f"HR={lectura['hr_bpm']:5.1f} bpm  "
            f"R-R={lectura['rr_ms']:6.1f} ms  "
            f"condicion={lectura['condicion']}"
        )
        time.sleep(1)
