# Para la reunión con mi tutor

## Sobre el Capítulo III

Ya avancé corrigiendo varias cosas del Capítulo III que estaban mal o
desactualizadas: dejé bien claro en todo el capítulo que se usa una sola
canción de preferencia personal (no dos, como decía antes en algunas partes),
corregí un conteo de iteraciones que estaba mal en una tabla, arreglé una
referencia a una figura que estaba apuntando a la que no era, y ajusté la
introducción del capítulo para que no prometa cosas que todavía no he
escrito (como la parte de validación del instrumento y consideraciones
éticas, que las tengo pendientes todavía).

---

## Sobre el baseline: por qué lo dejé en 2 minutos y no en 15 segundos

Profe, quería explicarle por qué decidí dejar el baseline en 2 minutos, en
vez de bajarlo a 15 segundos como habíamos hablado.

Lo primero que quiero aclarar es que el baseline no es tiempo muerto. Mi
sistema no mide simplemente "la frecuencia cardíaca durante el estímulo" —
mide el **cambio** respecto a cómo estaba la persona antes de empezar. O sea,
le resto la frecuencia cardíaca del baseline a la frecuencia cardíaca durante
el estímulo, y esa resta es mi dato principal.

Y esto es importante porque cada participante llega distinto cada día —
unos días más estresado, otros más relajado, por cosas que no tienen nada
que ver con el sonido. Si no tengo un baseline confiable de ESE día, no puedo
saber si el cambio que veo se debe al estímulo o simplemente a que la
persona ya llegó distinta. El baseline es lo que me permite aislar el efecto
real del sonido.

Ahora, el problema con 15 segundos es que no me alcanza para calcular bien
las otras métricas que también uso, que son el RMSSD y el SDNN — estas
miden la variabilidad del corazón, no solo el promedio. Para que esos
números salgan confiables, se necesitan varios latidos seguidos. En 15
segundos, una persona en reposo apenas da unos 17 o 20 latidos — eso es muy
poco, el número me saldría con mucho ruido.

Yo ya tengo citada en mi Estado del Arte una fuente (Shaffer & Ginsberg,
2017) que dice que el RMSSD recién se puede medir de forma confiable desde
1 minuto de registro. Entonces decidí dejarlo en 2 minutos, que me da un
margen de seguridad por encima de ese mínimo, y además es consistente con el
estándar que ya uso de referencia en todo el trabajo, que es el del Task
Force de la Sociedad Europea de Cardiología de 1996.

Y sobre lo que usted me comentó, de que esos 2 minutos se sienten como
tiempo muerto — sí le hice caso a esa parte, pero lo resolví de otra forma:
voy a poner un cartel de texto flotante en Unity, con las instrucciones
rápidas de seguridad para el participante — algo como "no te pongas de pie,
puedes mover la cabeza libremente" — pero ese cartel lo voy a mostrar
ANTES de que empiece a contar el baseline, en los 30 segundos que ya tengo
de estabilización al principio, que de por sí ya se descartan y no se usan
para nada del análisis. Así la persona no está sentada sin hacer nada esos
2 minutos — recibe las instrucciones justo antes — pero tampoco contamino
la medición del baseline metiendo una tarea de lectura justo cuando estoy
tratando de medir su estado de reposo real.
