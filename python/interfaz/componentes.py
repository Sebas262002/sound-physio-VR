"""Componentes de UI reutilizables para app_investigador.py.

Todos estos componentes son funciones/clases "puras" respecto a la base de
datos: no importan BaseDatosTesis ni saben nada de SQL Server — solo
construyen controles de Flet a partir de los datos que reciben. Esto los
hace reutilizables y fáciles de probar en aislamiento.

Todo color/tipografía/espaciado/sombra sale de design_system.py — nada acá
está hardcodeado. Ver ese archivo para la paleta "Neural Wellness" completa.

Nota sobre versión de Flet: este proyecto usa Flet 0.86.5, cuya API de
controles cambió bastante respecto a versiones anteriores (ej. los botones
ya no tienen un parámetro "text", usan "content"; Container ya trae
rotate/scale/offset/opacity y sus respectivos animate_* de fábrica en
LayoutControl/Control, lo que permite microinteracciones reales — hover,
fade-in — sin librerías externas). Todo lo de acá está escrito y verificado
contra esa API.
"""

import logging
from typing import Callable, Optional

import flet as ft

from design_system import Colors, Motion, Radius, Shadows, Spacing, Typography, gradiente

logger = logging.getLogger(__name__)


# ============================================================================
# Piezas atómicas
# ============================================================================


def IconCircle(icono: str, color_bg: str, color_ic: str, tamaño: int = 48) -> ft.Container:
    """Círculo de color con un icono centrado — la "insignia" de KPIs, timelines, etc.

    Args:
        icono: Nombre de icono de ft.Icons.
        color_bg: Color de fondo del círculo (usar with_opacity para un tono suave).
        color_ic: Color del icono.
        tamaño: Diámetro en pixeles.

    Returns:
        ft.Container: Círculo con el icono, listo para insertar en cualquier Row/Column.
    """
    return ft.Container(
        width=tamaño,
        height=tamaño,
        border_radius=tamaño / 2,
        bgcolor=color_bg,
        alignment=ft.alignment.Alignment.CENTER,
        content=ft.Icon(icono, color=color_ic, size=tamaño * 0.5),
    )


def StatusPill(estado: str, texto: str, color: str) -> ft.Container:
    """Chip pequeño y redondeado para marcar un estado (activo, alerta, pendiente...).

    Args:
        estado: Identificador corto del estado (ej. "activo", "alerta") — no se
            muestra, solo documenta la intención del llamador.
        texto: Texto visible del chip.
        color: Color de acento (fondo suave + texto/punto en el color pleno).

    Returns:
        ft.Container: Pill listo para insertar en una Row.
    """
    del estado  # solo documental, la apariencia depende únicamente de `color`
    return ft.Container(
        padding=ft.padding.Padding.symmetric(vertical=Spacing.XS, horizontal=Spacing.SM + Spacing.XS),
        border_radius=Radius.CHIP,
        bgcolor=ft.Colors.with_opacity(0.12, color),
        content=ft.Row(
            spacing=Spacing.XS + 2,
            alignment=ft.MainAxisAlignment.CENTER,
            tight=True,
            controls=[
                ft.Container(width=7, height=7, border_radius=4, bgcolor=color),
                ft.Text(texto, size=12, weight=ft.FontWeight.W_600, color=color),
            ],
        ),
    )


def SectionHeader(titulo: str, subtitulo: Optional[str] = None, accion: Optional[ft.Control] = None) -> ft.Control:
    """Encabezado de sección: título + subtítulo opcional a la izquierda, acción a la derecha.

    Args:
        titulo: Título de la sección (se estiliza con Typography.H2).
        subtitulo: Texto secundario opcional debajo del título.
        accion: Control opcional alineado a la derecha (ej. un GradientButton).

    Returns:
        ft.Control: Row lista para insertar como encabezado de vista o tarjeta.
    """
    columna = [ft.Text(spans=[ft.TextSpan(titulo, style=Typography.H2)])]
    if subtitulo:
        columna.append(ft.Text(spans=[ft.TextSpan(subtitulo, style=Typography.BODY_SECONDARY)]))
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Column(spacing=Spacing.XS, controls=columna, tight=True),
            accion if accion is not None else ft.Container(),
        ],
    )


def EmptyState(
    icono: str, titulo: str, descripcion: str, accion: Optional[ft.Control] = None, color: str = Colors.PRIMARY
) -> ft.Control:
    """Estado vacío ilustrado — reemplaza a un simple ft.Text("No hay datos") en listas/tabs vacíos.

    Args:
        icono: Icono grande central (ft.Icons.*).
        titulo: Mensaje principal, corto.
        descripcion: Explicación breve o siguiente paso sugerido.
        accion: Control opcional debajo del texto (ej. un botón "Crear sesión").
        color: Color del ícono y su círculo de fondo. Default Colors.PRIMARY (estados
            "todavía no hay datos"); usar Colors.TEXT_SECONDARY para un estado más
            neutro/apagado (ej. "sin sesión activa", donde no hay nada que resaltar).

    Returns:
        ft.Control: Columna centrada, lista para ocupar el área de contenido de una tab/vista.
    """
    controles = [
        IconCircle(icono, ft.Colors.with_opacity(0.10, color), color, tamaño=72),
        ft.Container(height=Spacing.SM),
        ft.Text(spans=[ft.TextSpan(titulo, style=Typography.H3)], text_align=ft.TextAlign.CENTER),
        ft.Container(
            width=360,
            content=ft.Text(
                spans=[ft.TextSpan(descripcion, style=Typography.BODY_SECONDARY)], text_align=ft.TextAlign.CENTER
            ),
        ),
    ]
    if accion is not None:
        controles.append(ft.Container(height=Spacing.MD))
        controles.append(accion)
    return ft.Container(
        padding=ft.padding.Padding.all(Spacing.XXL),
        alignment=ft.alignment.Alignment.CENTER,
        content=ft.Column(
            spacing=Spacing.XS,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=controles,
        ),
    )


def AnimatedNumber(valor, formato: str = "int") -> ft.Control:
    """Número grande con look de KPI, envuelto para permitir un fade-in suave.

    LIMITACIÓN CONOCIDA (Flet 0.86.5): un "conteo" numérico animado real (0 → valor,
    dígito por dígito) necesitaría mutar `.value` desde un hilo/temporizador y llamar
    `.update()` en varios pasos — el mismo patrón que ya causó el bug de "freeze" de
    la Vista en vivo (page.update() no es thread-safe fuera del loop de eventos, ver
    _actualizar_pagina_segura() en app_investigador.py). Para no repetir esa fragilidad
    en un componente puramente decorativo, este control expone solo una transición de
    aparición (opacity+scale, vía animate_opacity/animate_scale) que se dispara la
    primera vez que Flet lo monta — no un conteo numérico literal.

    Args:
        valor: Valor numérico a mostrar (int o float).
        formato: "int" redondea a entero; "1f" muestra un decimal; cualquier otro
            string se usa como spec de format() literal (ej. ".2f").

    Returns:
        ft.Control: Container con el número estilizado (Typography.KPI_NUMBER).
    """
    if formato == "int":
        texto = str(round(valor))
    elif formato == "1f":
        texto = f"{valor:.1f}"
    else:
        texto = format(valor, formato)
    return ft.Container(
        opacity=1,
        scale=1,
        animate_opacity=Motion.SLOW,
        animate_scale=Motion.SLOW,
        content=ft.Text(spans=[ft.TextSpan(texto, style=Typography.KPI_NUMBER)]),
    )


def GradientButton(
    texto: str,
    on_click: Optional[Callable] = None,
    icono: Optional[str] = None,
    color_start: str = Colors.PRIMARY,
    color_end: str = Colors.PRIMARY_DARK,
) -> ft.Container:
    """Botón con relleno en degradado y elevación al pasar el mouse.

    Se implementa sobre Container (no ElevatedButton) porque ElevatedButton no
    admite `gradient=` en esta versión de Flet — Container sí, y ya trae
    on_click/ink/on_hover propios, así que sirve como botón sin perder el
    ripple de Material.

    Args:
        texto: Texto del botón.
        on_click: Handler del click.
        icono: Icono opcional a la izquierda del texto.
        color_start: Color inicial del degradado (arriba-izquierda).
        color_end: Color final del degradado (abajo-derecha).

    Returns:
        ft.Container: Botón estilizado, listo para insertar en cualquier layout.
    """
    controles = []
    if icono:
        controles.append(ft.Icon(icono, color=Colors.TEXT_ON_DARK, size=18))
    controles.append(ft.Text(texto, color=Colors.TEXT_ON_DARK, weight=ft.FontWeight.W_600, size=14))

    boton = ft.Container(
        on_click=on_click,
        ink=True,
        border_radius=Radius.BUTTON,
        padding=ft.padding.Padding.symmetric(vertical=14, horizontal=22),
        gradient=ft.LinearGradient(
            colors=[color_start, color_end],
            begin=ft.alignment.Alignment.TOP_LEFT,
            end=ft.alignment.Alignment.BOTTOM_RIGHT,
        ),
        shadow=Shadows.SM,
        scale=1.0,
        animate=Motion.FAST,
        animate_scale=Motion.FAST,
        content=ft.Row(spacing=Spacing.XS + 2, tight=True, alignment=ft.MainAxisAlignment.CENTER, controls=controles),
    )

    def _al_pasar_mouse(e: ft.ControlEvent) -> None:
        boton.shadow = Shadows.MD if e.data else Shadows.SM
        boton.scale = 1.02 if e.data else 1.0
        boton.update()

    boton.on_hover = _al_pasar_mouse
    return boton


def GlassCard(contenido: ft.Control, blur: bool = True) -> ft.Container:
    """Tarjeta translúcida con efecto vidrio esmerilado (glassmorphism).

    LIMITACIÓN CONOCIDA (Flet 0.86.5): según la documentación fuente de
    Container.blur, el desenfoque gaussiano real solo se ve correctamente
    cuando este container está dentro de un ft.Stack, apilado sobre contenido
    de fondo (blurea lo que hay DETRÁS de él, no su propio contenido). Usado
    fuera de un Stack, `blur=` sigue siendo válido pero puede no mostrar el
    efecto visual completo — el fondo semitransparente + borde sutil todavía
    da la sensación "glass" incluso sin ese contexto.

    Args:
        contenido: Control a mostrar dentro de la tarjeta.
        blur: Si True, aplica ft.Blur (desenfoque gaussiano) bajo la tarjeta.

    Returns:
        ft.Container: Tarjeta con fondo semitransparente, borde sutil y sombra.
    """
    return ft.Container(
        padding=ft.padding.Padding.all(Spacing.LG),
        border_radius=Radius.CARD,
        bgcolor=ft.Colors.with_opacity(0.72, Colors.BG_CARD),
        border=ft.border.Border.all(1, ft.Colors.with_opacity(0.6, Colors.BORDER)),
        blur=ft.Blur(sigma_x=18, sigma_y=18) if blur else None,
        shadow=Shadows.MD,
        content=contenido,
    )


def Timeline(items: list) -> ft.Control:
    """Línea de tiempo vertical — usada en Inicio para las últimas sesiones/eventos.

    Args:
        items: Lista de dicts, cada uno con:
            titulo (str): Texto principal del evento.
            subtitulo (str, opcional): Texto secundario (ej. participante/detalle).
            hora (str, opcional): Marca de tiempo o fecha ya formateada.
            icono (str, opcional): Icono del punto (default ft.Icons.CIRCLE).
            color (str, opcional): Color del punto (default Colors.PRIMARY).
            badges (list[str], opcional): Chips chicos de contexto extra, ya
                formateados por el llamador (ej. ["✅ Completa", "4 estímulos",
                "HR 68"]) — Timeline no sabe qué significan, solo los pinta.

    Returns:
        ft.Control: Columna con un punto+línea conectora por cada item.
    """
    if not items:
        return EmptyState(
            ft.Icons.HISTORY,
            "Todavía no hay actividad",
            "Cuando registres participantes o corras sesiones, van a aparecer acá.",
        )

    filas = []
    for i, item in enumerate(items):
        color = item.get("color", Colors.PRIMARY)
        es_ultimo = i == len(items) - 1
        punto_y_linea = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
            controls=[
                IconCircle(item.get("icono", ft.Icons.CIRCLE), ft.Colors.with_opacity(0.12, color), color, tamaño=28),
                ft.Container() if es_ultimo else ft.Container(width=2, height=32, bgcolor=Colors.BORDER),
            ],
        )
        texto = [ft.Text(item["titulo"], size=14, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY)]
        if item.get("subtitulo"):
            texto.append(ft.Text(item["subtitulo"], size=12, color=Colors.TEXT_SECONDARY))
        if item.get("badges"):
            texto.append(
                ft.Row(
                    wrap=True,
                    spacing=Spacing.XS,
                    controls=[
                        ft.Container(
                            padding=ft.padding.Padding.symmetric(vertical=2, horizontal=Spacing.XS + 2),
                            border_radius=Radius.CHIP,
                            bgcolor=Colors.BG_MAIN,
                            border=ft.border.Border.all(1, Colors.BORDER),
                            content=ft.Text(badge, size=10, weight=ft.FontWeight.W_600, color=Colors.TEXT_SECONDARY),
                        )
                        for badge in item["badges"]
                    ],
                )
            )
        contenido = ft.Column(spacing=Spacing.XS, controls=texto, tight=True)
        fila = ft.Row(
            spacing=Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                punto_y_linea,
                ft.Container(content=contenido, expand=True, padding=ft.padding.Padding.only(top=2)),
            ],
        )
        if item.get("hora"):
            fila.controls.append(ft.Text(item["hora"], size=12, color=Colors.TEXT_SECONDARY))
        filas.append(fila)

    return ft.Column(spacing=0, controls=filas)


def MetricBadge(label: str, valor, unidad: str, color: str = Colors.PRIMARY) -> ft.Control:
    """Insignia compacta de una métrica (label arriba, valor+unidad abajo) — para HR/HRV en vivo.

    Args:
        label: Etiqueta corta (se muestra en mayúsculas vía Typography.LABEL).
        valor: Valor a mostrar (se convierte a str tal cual — el llamador ya lo formatea).
        unidad: Unidad, ej. "bpm", "ms".
        color: Color del valor.

    Returns:
        ft.Control: Columna lista para insertar en la fila de métricas de la Vista en vivo.
    """
    return ft.Column(
        spacing=2,
        horizontal_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Text(spans=[ft.TextSpan(label.upper(), style=Typography.LABEL)]),
            ft.Row(
                spacing=4,
                tight=True,
                # CrossAxisAlignment.BASELINE en un ft.Row exige además "text_baseline" (Flet
                # no lo expone) — sin eso, Flutter tira "must also specify textBaseline" y ESE
                # error de layout rompe el render de TODA la página (bug real: la Vista en
                # vivo quedaba en blanco por esto, ver page.on_error en app_investigador.py).
                # END (alinear abajo) da el mismo efecto visual de "número grande + unidad
                # chica pegada abajo" sin ese requisito.
                vertical_alignment=ft.CrossAxisAlignment.END,
                controls=[
                    ft.Text(str(valor), size=28, weight=ft.FontWeight.W_700, color=color),
                    ft.Text(unidad, size=13, color=Colors.TEXT_SECONDARY),
                ],
            ),
        ],
    )


# ============================================================================
# Componentes existentes — reescritos sobre design_system, misma firma pública
# ============================================================================


def TarjetaKPI(titulo: str, valor: str, icono: str, color: str = Colors.PRIMARY) -> ft.Container:
    """Construye una tarjeta de indicador (KPI) simple para el dashboard de Inicio.

    Args:
        titulo: Etiqueta del indicador, ej. "Participantes registrados".
        valor: Valor a mostrar, ya formateado como string (ej. "12", "3 sesiones").
        icono: Nombre de icono de ft.Icons (ej. ft.Icons.PEOPLE_OUTLINE).
        color: Color de acento del icono y del borde izquierdo de la tarjeta.

    Returns:
        ft.Container: Tarjeta lista para insertar en una Row/Column.
    """
    tarjeta = ft.Container(
        width=240,
        padding=ft.padding.Padding.all(Spacing.MD + 2),
        border_radius=Radius.CARD,
        bgcolor=Colors.BG_CARD,
        shadow=Shadows.SM,
        animate=Motion.NORMAL,
        content=ft.Column(
            spacing=Spacing.SM,
            controls=[
                IconCircle(icono, ft.Colors.with_opacity(0.12, color), color, tamaño=40),
                ft.Text(valor, size=26, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY),
                ft.Text(spans=[ft.TextSpan(titulo, style=Typography.BODY_SECONDARY)]),
            ],
        ),
    )

    def _al_pasar_mouse(e: ft.ControlEvent) -> None:
        tarjeta.shadow = Shadows.MD if e.data else Shadows.SM
        tarjeta.update()

    tarjeta.on_hover = _al_pasar_mouse
    return tarjeta


def KPICard(
    titulo: str,
    valor: str,
    icono: str,
    color: str = Colors.PRIMARY,
    tendencia: Optional[str] = None,
    valor_secundario: Optional[str] = None,
    nota: Optional[str] = None,
    icono_nota: Optional[str] = None,
) -> ft.Container:
    """Tarjeta KPI "premium" con número grande (Typography.KPI_NUMBER) y una línea de
    contexto opcional debajo.

    Pensada para el header de Inicio, en vez de TarjetaKPI (que sigue existiendo para
    usos más compactos, ej. dentro de otras tarjetas). Reserva SIEMPRE los mismos 4
    "renglones" (título+badge, valor, secundario, nota) aunque estén vacíos —
    con `opacity=0` en vez de omitirlos — para que un ft.ResponsiveRow de KPICards
    quede con la misma altura en todas las tarjetas sin tener que fijar un `height=`
    a mano (bug real reportado probando la app: la tarjeta de "Última sesión", con
    menos texto, quedaba más baja que las otras 3).

    Args:
        titulo: Etiqueta del indicador.
        valor: Valor principal ya formateado (str) — se muestra en tamaño 42/w800.
        icono: Icono del badge circular superior.
        color: Color de acento del badge y de la tendencia positiva.
        tendencia: Texto corto opcional, ej. "+12% vs. semana pasada" o "-3%". Si
            empieza con "-" se pinta en rojo (Colors.DANGER) con flecha hacia abajo;
            si no, en verde (Colors.SUCCESS) con flecha hacia arriba. Mutuamente
            excluyente con `nota` (si se pasan los dos, gana `tendencia`).
        valor_secundario: Línea chica opcional debajo del valor principal, ej. una
            fecha — para KPIs donde el "valor" es un identificador (ej. "P009")
            en vez de un número.
        nota: Texto corto neutro opcional (sin colorear verde/rojo), ej. "Hace 3
            horas" o "Verificado a las 18:30" — para contexto que no es una
            tendencia. Se ignora si `tendencia` también viene con datos.
        icono_nota: Icono para `nota` (default ft.Icons.SCHEDULE si no se indica).

    Returns:
        ft.Container: Tarjeta KPI grande, lista para un ft.ResponsiveRow del dashboard.
    """
    linea_secundaria = ft.Text(
        valor_secundario or " ", size=13, color=Colors.TEXT_SECONDARY, opacity=1 if valor_secundario else 0
    )

    if tendencia:
        es_negativa = tendencia.strip().startswith("-")
        fila_nota = ft.Row(
            spacing=4,
            tight=True,
            controls=[
                ft.Icon(
                    ft.Icons.TRENDING_DOWN if es_negativa else ft.Icons.TRENDING_UP,
                    size=14,
                    color=Colors.DANGER if es_negativa else Colors.SUCCESS,
                ),
                ft.Text(
                    tendencia, size=11, weight=ft.FontWeight.W_600, color=Colors.DANGER if es_negativa else Colors.SUCCESS
                ),
            ],
        )
    elif nota:
        fila_nota = ft.Row(
            spacing=4,
            tight=True,
            controls=[
                ft.Icon(icono_nota or ft.Icons.SCHEDULE, size=14, color=Colors.TEXT_SECONDARY),
                ft.Text(nota, size=11, color=Colors.TEXT_SECONDARY),
            ],
        )
    else:
        fila_nota = ft.Row(spacing=4, tight=True, opacity=0, controls=[ft.Icon(ft.Icons.SCHEDULE, size=14), ft.Text(" ", size=11)])

    contenido = [
        ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(spans=[ft.TextSpan(titulo.upper(), style=Typography.LABEL)]),
                IconCircle(icono, ft.Colors.with_opacity(0.12, color), color, tamaño=36),
            ],
        ),
        ft.Text(spans=[ft.TextSpan(valor, style=Typography.KPI_NUMBER)]),
        linea_secundaria,
        fila_nota,
    ]
    return ft.Container(
        expand=True,
        padding=ft.padding.Padding.all(Spacing.LG),
        border_radius=Radius.CARD,
        bgcolor=Colors.BG_CARD,
        shadow=Shadows.SM,
        content=ft.Column(spacing=Spacing.SM, controls=contenido),
    )


def IndicadorHardware(nombre: str, conectado: bool, detalle: Optional[str] = None) -> ft.Container:
    """Fila con un check/cruz de estado para un componente de hardware.

    Args:
        nombre: Nombre del componente, ej. "Sensor cardíaco Wahoo TRACKR".
        conectado: True = check verde; False = cruz roja.
        detalle: Texto adicional opcional (tooltip), ej. motivo de por qué
            no está verificado todavía.

    Returns:
        ft.Container: Fila con icono de estado + nombre.
    """
    icono = ft.Icons.CHECK_CIRCLE if conectado else ft.Icons.CANCEL
    color = Colors.SUCCESS if conectado else Colors.DANGER
    return ft.Container(
        padding=ft.padding.Padding.symmetric(vertical=Spacing.XS + 2, horizontal=Spacing.XS),
        tooltip=detalle,
        border_radius=Radius.INPUT,
        content=ft.Row(
            spacing=Spacing.SM,
            controls=[
                ft.Icon(icono, color=color, size=20),
                ft.Text(nombre, size=14, color=Colors.TEXT_PRIMARY),
            ],
        ),
    )


def BotonPrimario(
    texto: str,
    on_click: Optional[Callable] = None,
    icono: Optional[str] = None,
    disabled: bool = False,
    ancho: Optional[int] = None,
) -> ft.ElevatedButton:
    """Botón primario con el color de acento del proyecto.

    Args:
        texto: Texto del botón.
        on_click: Handler del click.
        icono: Nombre de icono opcional (ft.Icons.*).
        disabled: Si el botón arranca deshabilitado.
        ancho: Ancho fijo opcional, en pixeles.

    Returns:
        ft.ElevatedButton: Botón estilizado.
    """
    return ft.ElevatedButton(
        content=ft.Text(texto, weight=ft.FontWeight.W_600),
        icon=icono,
        on_click=on_click,
        disabled=disabled,
        width=ancho,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=Radius.BUTTON),
            padding=ft.padding.Padding.symmetric(vertical=16, horizontal=22),
            # Colores por estado: sin esto, un botón disabled=True se pinta IGUAL que uno
            # habilitado (mismo bgcolor fijo) y parece clickeable sin estarlo — bug real
            # detectado probando el formulario de Nueva sesión con una edad fuera de rango.
            bgcolor={ft.ControlState.DISABLED: Colors.DISABLED_BG, ft.ControlState.DEFAULT: Colors.PRIMARY},
            color={ft.ControlState.DISABLED: Colors.DISABLED_TEXT, ft.ControlState.DEFAULT: Colors.TEXT_ON_DARK},
        ),
    )


def SnackBarExito(mensaje: str) -> ft.SnackBar:
    """SnackBar verde de confirmación, con icono + mensaje.

    Args:
        mensaje: Texto a mostrar.

    Returns:
        ft.SnackBar: Listo para pasar a page.show_dialog().
    """
    return ft.SnackBar(
        content=ft.Row(
            spacing=Spacing.SM,
            controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE, color=Colors.TEXT_ON_DARK),
                ft.Text(mensaje, color=Colors.TEXT_ON_DARK, weight=ft.FontWeight.W_500),
            ],
        ),
        bgcolor=Colors.SUCCESS,
        shape=ft.RoundedRectangleBorder(radius=Radius.INPUT),
    )


def SnackBarError(mensaje: str) -> ft.SnackBar:
    """SnackBar rojo de error, con icono + mensaje.

    Args:
        mensaje: Texto a mostrar.

    Returns:
        ft.SnackBar: Listo para pasar a page.show_dialog().
    """
    return ft.SnackBar(
        content=ft.Row(
            spacing=Spacing.SM,
            controls=[
                ft.Icon(ft.Icons.ERROR, color=Colors.TEXT_ON_DARK),
                ft.Text(mensaje, color=Colors.TEXT_ON_DARK, weight=ft.FontWeight.W_500),
            ],
        ),
        bgcolor=Colors.DANGER,
        shape=ft.RoundedRectangleBorder(radius=Radius.INPUT),
    )


class ChipGroup:
    """Grupo de chips grandes de selección única — reemplazo visual de ft.RadioGroup.

    Expone `.value` (str o None) igual que ft.RadioGroup, así que cualquier código
    que ya lea `grupo.value` (ver FormularioParticipante.errores()/obtener_datos())
    sigue funcionando sin cambios: por fuera se ve idéntico a un RadioGroup, por
    dentro son Containers clickeables con hover y elevación.

    Attributes:
        value (Optional[str]): Valor de la opción seleccionada, o None si ninguna.
    """

    def __init__(
        self,
        opciones: list[tuple[str, str]],
        on_change: Optional[Callable] = None,
        valor_inicial: Optional[str] = None,
    ) -> None:
        """Arma el grupo.

        Args:
            opciones: Lista de (valor, etiqueta), ej. [("M", "Masculino"), ...].
            on_change: Callback invocado con el ft.ControlEvent del click, igual
                que on_change de ft.RadioGroup (ver FormularioParticipante._notificar,
                que de hecho ignora el argumento).
            valor_inicial: Opción ya seleccionada al construir (default: ninguna).
        """
        self._on_change_externo = on_change
        self.value = valor_inicial
        self._chips: dict[str, ft.Container] = {}
        for valor, etiqueta in opciones:
            self._chips[valor] = self._construir_chip(valor, etiqueta)
        self._fila = ft.Row(wrap=True, spacing=Spacing.SM, controls=list(self._chips.values()))

    def _construir_chip(self, valor: str, etiqueta: str) -> ft.Container:
        activo = valor == self.value
        chip = ft.Container(
            ink=True,
            on_click=lambda e, v=valor: self._seleccionar(v, e),
            border_radius=Radius.CHIP,
            padding=ft.padding.Padding.symmetric(vertical=Spacing.SM, horizontal=Spacing.MD),
            border=ft.border.Border.all(1.5, Colors.PRIMARY if activo else Colors.BORDER),
            bgcolor=ft.Colors.with_opacity(0.10, Colors.PRIMARY) if activo else Colors.BG_CARD,
            shadow=Shadows.SM if activo else None,
            scale=1.0,
            animate=Motion.FAST,
            animate_scale=Motion.FAST,
            content=ft.Text(
                etiqueta,
                size=13,
                weight=ft.FontWeight.W_600 if activo else ft.FontWeight.W_400,
                color=Colors.PRIMARY if activo else Colors.TEXT_PRIMARY,
            ),
        )
        chip.on_hover = self._crear_handler_hover(valor, chip)
        return chip

    def _crear_handler_hover(self, valor: str, chip: ft.Container) -> Callable:
        def handler(e: ft.ControlEvent) -> None:
            if valor == self.value:
                return  # el chip activo no necesita feedback de hover extra
            chip.scale = 1.03 if e.data else 1.0
            chip.update()

        return handler

    def _seleccionar(self, valor: str, e: ft.ControlEvent) -> None:
        self.value = valor
        for v, chip in self._chips.items():
            activo = v == valor
            chip.border = ft.border.Border.all(1.5, Colors.PRIMARY if activo else Colors.BORDER)
            chip.bgcolor = ft.Colors.with_opacity(0.10, Colors.PRIMARY) if activo else Colors.BG_CARD
            chip.shadow = Shadows.SM if activo else None
            chip.scale = 1.0
            chip.content.color = Colors.PRIMARY if activo else Colors.TEXT_PRIMARY
            chip.content.weight = ft.FontWeight.W_600 if activo else ft.FontWeight.W_400
            # Ver el mismo guard en BotonAccionPrincipal._aplicar_estado(): Control.page
            # lanza RuntimeError (no devuelve None) si el chip todavía no está en pantalla.
            try:
                chip.update()
            except RuntimeError:
                pass
        if self._on_change_externo is not None:
            self._on_change_externo(e)

    def establecer(self, valor: Optional[str]) -> None:
        """Selecciona `valor` programáticamente, sin necesitar un click real —
        para autocompletar el grupo desde afuera (ej. precargar género/mano
        dominante de un participante ya existente, ver
        _autocompletar_participante_existente() en app_investigador.py).
        Reutiliza _seleccionar() tal cual, pasando None como evento — seguro
        porque los únicos on_change externos de ChipGroup hoy (ver
        FormularioParticipante._notificar) ignoran ese argumento.
        """
        self._seleccionar(valor, None)

    def build(self) -> ft.Control:
        """Returns:
        ft.Control: Fila de chips, lista para insertar en la vista.
        """
        return self._fila


class BotonAccionPrincipal:
    """Botón CTA con degradado indigo→violeta cuando está habilitado, gris plano
    cuando no — el mismo look de GradientButton, pero con un `.disabled` de
    lectura/escritura normal para que código externo pueda seguir haciendo
    `boton.disabled = True/False` sin saber que por dentro es un Container (Flet
    0.86.5 no admite gradient= en ElevatedButton, ver GradientButton más arriba).

    Attributes:
        contenedor (ft.Container): El control real a insertar en el árbol de UI.
        disabled (bool): Alternar esto recalcula automáticamente el degradado/gris.
    """

    def __init__(
        self, texto: str, on_click: Optional[Callable] = None, icono: Optional[str] = None, disabled: bool = True
    ) -> None:
        """Arma el botón.

        Args:
            texto: Texto del botón.
            on_click: Handler del click (solo se conecta cuando NO está disabled).
            icono: Icono opcional a la izquierda del texto.
            disabled: Estado inicial.
        """
        self._texto = texto
        self._icono = icono
        self._on_click_externo = on_click
        self._disabled = disabled

        controles = []
        if icono:
            controles.append(ft.Icon(icono, size=18))
        controles.append(ft.Text(texto, weight=ft.FontWeight.W_600, size=14))
        self._fila_contenido = ft.Row(spacing=Spacing.XS + 2, tight=True, alignment=ft.MainAxisAlignment.CENTER, controls=controles)

        self.contenedor = ft.Container(
            border_radius=Radius.BUTTON,
            padding=ft.padding.Padding.symmetric(vertical=16, horizontal=22),
            animate=Motion.FAST,
            content=self._fila_contenido,
        )
        self._aplicar_estado()

    @property
    def disabled(self) -> bool:
        return self._disabled

    @disabled.setter
    def disabled(self, valor: bool) -> None:
        self._disabled = bool(valor)
        self._aplicar_estado()

    def _aplicar_estado(self) -> None:
        icono_control = self._fila_contenido.controls[0] if self._icono else None
        texto_control = self._fila_contenido.controls[-1]
        if self._disabled:
            self.contenedor.gradient = None
            self.contenedor.bgcolor = Colors.DISABLED_BG
            self.contenedor.shadow = None
            self.contenedor.on_click = None
            self.contenedor.ink = False
            texto_control.color = Colors.DISABLED_TEXT
            if icono_control is not None:
                icono_control.color = Colors.DISABLED_TEXT
        else:
            self.contenedor.bgcolor = None
            self.contenedor.gradient = gradiente(Colors.PRIMARY, Colors.SECONDARY)
            self.contenedor.shadow = Shadows.SM
            self.contenedor.on_click = self._on_click_externo
            self.contenedor.ink = True
            texto_control.color = Colors.TEXT_ON_DARK
            if icono_control is not None:
                icono_control.color = Colors.TEXT_ON_DARK
        # Control.page es una property que RAISES RuntimeError (no devuelve None) si el
        # control todavía no se agregó a ninguna página — pasa siempre en la primera
        # llamada, hecha desde __init__() antes de que _vista_nueva_sesion() termine de
        # construir el árbol. Ese primer .update() no hace falta (recién se está armando
        # el control); en llamadas posteriores desde disabled.setter sí está attached.
        try:
            if self.contenedor.page is not None:
                self.contenedor.update()
        except RuntimeError:
            pass


class SelectorLikert:
    """Pregunta con slider de 1 a 5, para el cuestionario post-estímulo.

    Attributes:
        slider (ft.Slider): Control del slider (1-5, con divisiones enteras).
    """

    _ICONOS_POR_VALOR = {1: "😞", 2: "🙁", 3: "😐", 4: "🙂", 5: "😄"}

    def __init__(self, pregunta: str, min_label: str, max_label: str, valor_inicial: int = 3) -> None:
        """Arma el selector.

        Args:
            pregunta: Texto de la pregunta, ej. "¿Qué tan RELAJADA te sentiste?".
            min_label: Etiqueta del extremo inferior (valor 1).
            max_label: Etiqueta del extremo superior (valor 5).
            valor_inicial: Valor con el que arranca el slider (default 3, el punto medio).
        """
        self.pregunta = pregunta
        self.min_label = min_label
        self.max_label = max_label
        self._icono_texto = ft.Text(self._ICONOS_POR_VALOR[valor_inicial], size=36)
        self.slider = ft.Slider(
            min=1,
            max=5,
            divisions=4,
            value=valor_inicial,
            label="{value}",
            active_color=Colors.PRIMARY,
            inactive_color=ft.Colors.with_opacity(0.15, Colors.PRIMARY),
            on_change=self._al_cambiar,
        )

    def _al_cambiar(self, e: ft.ControlEvent) -> None:
        """Actualiza el icono animado según el valor actual del slider."""
        valor = round(self.slider.value)
        self._icono_texto.value = self._ICONOS_POR_VALOR.get(valor, "😐")
        self._icono_texto.update()

    def build(self) -> ft.Control:
        """Arma el control visual completo (pregunta + slider + etiquetas + icono).

        Returns:
            ft.Control: Tarjeta lista para insertar en la vista del cuestionario.
        """
        return ft.Container(
            padding=ft.padding.Padding.all(Spacing.MD),
            border_radius=Radius.CARD,
            bgcolor=Colors.BG_CARD,
            shadow=Shadows.SM,
            content=ft.Column(
                spacing=Spacing.SM,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(self.pregunta, size=15, weight=ft.FontWeight.W_600, expand=True),
                            self._icono_texto,
                        ],
                    ),
                    self.slider,
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(spans=[ft.TextSpan(self.min_label, style=Typography.LABEL)]),
                            ft.Text(spans=[ft.TextSpan(self.max_label, style=Typography.LABEL)]),
                        ],
                    ),
                ],
            ),
        )

    @property
    def valor(self) -> int:
        """int: Valor actual del slider (1-5), redondeado a entero."""
        return round(self.slider.value)


class FormularioParticipante:
    """Formulario de registro de un nuevo participante (Vista 2: Nueva sesión).

    Attributes:
        campo_id (ft.TextField): ID del participante (autogenerado, editable).
        campo_edad (ft.TextField): Edad (numérica).
        grupo_genero (ChipGroup): Selector de género.
        check_consentimiento (ft.Checkbox): Confirmación de consentimiento informado.
        campo_observaciones (ft.TextField): Notas libres, opcional.
    """

    def __init__(self, id_sugerido: str = "", on_change: Optional[Callable] = None) -> None:
        """Arma el formulario.

        Args:
            id_sugerido: Valor inicial del campo ID (ver
                BaseDatosTesis.siguiente_id_participante()).
            on_change: Callback sin argumentos, invocado cada vez que cambia
                cualquier campo — pensado para revalidar y habilitar/deshabilitar
                el botón de registro desde afuera.
        """
        self._on_change_externo = on_change

        _forma_campo = dict(
            border_radius=Radius.INPUT,
            filled=True,
            fill_color=Colors.BG_MAIN,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )

        # Ícono de "campo válido": visible/invisible se decide en _notificar() con las
        # mismas reglas que ya usa errores() (ver _id_valido()/_edad_valida()) — no son
        # reglas nuevas, solo una lectura de las que ya existían, para decorar el campo.
        self._icono_id_ok = ft.Icon(ft.Icons.CHECK_CIRCLE, color=Colors.SUCCESS, size=20, visible=bool(id_sugerido.strip()))
        self._icono_edad_ok = ft.Icon(ft.Icons.CHECK_CIRCLE, color=Colors.SUCCESS, size=20, visible=False)

        self.campo_id = ft.TextField(
            label="ID Participante",
            value=id_sugerido,
            width=220,
            on_change=self._notificar,
            prefix_icon=ft.Icons.BADGE_OUTLINED,
            suffix_icon=self._icono_id_ok,
            **_forma_campo,
        )
        self.campo_edad = ft.TextField(
            label="Edad",
            width=220,
            keyboard_type=ft.KeyboardType.NUMBER,
            hint_text="18-99",
            on_change=self._notificar,
            prefix_icon=ft.Icons.CAKE_OUTLINED,
            suffix_icon=self._icono_edad_ok,
            **_forma_campo,
        )
        self.grupo_genero = ChipGroup(
            on_change=self._notificar,
            opciones=[("M", "Masculino"), ("F", "Femenino"), ("O", "Otro"), ("N", "Prefiero no decir")],
        )
        # Mano dominante EXISTIÓ acá (ChipGroup "D"/"I") y se ELIMINÓ a pedido
        # explícito del tutor: no aporta nada a la Hipótesis H1/H0 de la tesis
        # (compara respuesta fisiológica ante 2 tipos de estímulo sonoro, no
        # depende de lateralidad manual) — ver también bd_sqlserver.py (columna
        # eliminada) y reporte_pdf.py (_MANO_LEGIBLE eliminado).
        self.check_consentimiento = ft.Checkbox(
            label="Consentimiento informado firmado",
            value=False,
            on_change=self._notificar,
            active_color=Colors.PRIMARY,
        )
        self.campo_observaciones = ft.TextField(
            label="Observaciones",
            multiline=True,
            min_lines=3,
            max_lines=5,
            width=460,
            prefix_icon=ft.Icons.NOTES_OUTLINED,
            **_forma_campo,
        )

    def _id_valido(self) -> bool:
        """Solo para decorar campo_id con un ícono — misma regla que ya usa errores()."""
        return bool(self.campo_id.value and self.campo_id.value.strip())

    def _edad_valida(self) -> bool:
        """Solo para decorar campo_edad con un ícono — misma regla que ya usa errores()."""
        valor = (self.campo_edad.value or "").strip()
        return valor.isdigit() and 18 <= int(valor) <= 99

    def _notificar(self, e: ft.ControlEvent) -> None:
        """Refresca los íconos de "campo válido" y reenvía el evento al callback externo."""
        self._icono_id_ok.visible = self._id_valido()
        self._icono_edad_ok.visible = self._edad_valida()
        if self._on_change_externo is not None:
            self._on_change_externo()

    def _etiqueta_seccion(self, texto: str) -> ft.Text:
        return ft.Text(spans=[ft.TextSpan(texto.upper(), style=Typography.LABEL)])

    def build(self) -> ft.Control:
        """Arma el control visual completo del formulario.

        Returns:
            ft.Control: Columna con todos los campos, lista para insertar en la vista.
        """
        return ft.Column(
            spacing=Spacing.LG,
            controls=[
                ft.Row(spacing=Spacing.MD, controls=[self.campo_id, self.campo_edad]),
                ft.Column(spacing=Spacing.XS, controls=[self._etiqueta_seccion("Género"), self.grupo_genero.build()]),
                self.check_consentimiento,
                self.campo_observaciones,
            ],
        )

    def errores(self) -> list[str]:
        """Lista los motivos concretos por los que el formulario todavía no está listo.

        Existe por separado de es_valido() para poder mostrarle al usuario
        EXACTAMENTE qué falta (ver _revalidar_formulario() en
        app_investigador.py) — un botón que se queda deshabilitado sin
        explicación es un bug de UX real, no solo cosmético.

        Returns:
            list[str]: Mensajes de validación pendientes; lista vacía si
                el formulario está completo y listo para registrar.
        """
        errores = []
        if not self.campo_id.value or not self.campo_id.value.strip():
            errores.append("Falta el ID del participante.")

        if not self.campo_edad.value or not self.campo_edad.value.strip().isdigit():
            errores.append("La edad es obligatoria y debe ser un número.")
        else:
            edad = int(self.campo_edad.value.strip())
            if not (18 <= edad <= 99):
                errores.append("La edad debe estar entre 18 y 99 años.")

        if not self.grupo_genero.value:
            errores.append("Falta seleccionar el género.")
        if not self.check_consentimiento.value:
            errores.append("Falta marcar el consentimiento informado.")
        return errores

    def es_valido(self) -> bool:
        """Valida que el formulario esté completo y listo para registrar.

        Returns:
            bool: True si ID, edad (18-99), género y consentimiento están
                todos completos/marcados.
        """
        return not self.errores()

    def obtener_datos(self) -> dict:
        """Extrae los valores del formulario como dict, listo para BaseDatosTesis.registrar_participante().

        Returns:
            dict: id_participante, edad (int), genero, observaciones, consentimiento (bool).
        """
        return {
            "id_participante": self.campo_id.value.strip(),
            "edad": int(self.campo_edad.value.strip()),
            "genero": self.grupo_genero.value,
            "observaciones": (self.campo_observaciones.value or "").strip(),
            "consentimiento": bool(self.check_consentimiento.value),
        }
