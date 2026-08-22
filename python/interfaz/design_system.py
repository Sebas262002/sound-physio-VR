"""Sistema de diseño "Neural Wellness" — constantes visuales de app_investigador.py.

Todo color/tipografía/espaciado/sombra/radio de la interfaz sale de acá — nunca
se hardcodea un valor suelto en app_investigador.py ni en componentes.py. Así,
cambiar la paleta o la tipografía es editar un solo archivo.

Notas sobre la API real de Flet 0.86.5 (verificadas contra el código fuente
instalado antes de escribir esto — varias difieren de lo que uno esperaría
por versiones anteriores de Flet):
    - FontWeight NO acepta strings tipo "w700": son miembros de enum,
      ft.FontWeight.W_700.
    - Animation(duration, curve) — duration es un int en milisegundos;
      curve es un miembro de ft.AnimationCurve (enum), no un string.
    - LinearGradient(colors=[...], begin=Alignment, end=Alignment) — el
      degradado vive en "colors", no en begin/end (esos solo marcan la
      dirección).
    - BoxShadow(spread_radius, blur_radius, color, offset, blur_style) —
      esta sí coincide con lo esperado.
"""

import flet as ft


class Colors:
    """Paleta "Neural Wellness": índigo vibrante + lavanda, sobre fondos claros."""

    PRIMARY = "#6366F1"
    PRIMARY_DARK = "#4F46E5"
    SECONDARY = "#A78BFA"
    ACCENT = "#06B6D4"
    SUCCESS = "#10B981"
    WARNING = "#F59E0B"
    DANGER = "#EF4444"

    BG_MAIN = "#FAFAFC"
    BG_CARD = "#FFFFFF"
    BG_SIDEBAR = "#1E1B4B"

    TEXT_PRIMARY = "#0F172A"
    TEXT_SECONDARY = "#64748B"
    TEXT_ON_DARK = "#FFFFFF"
    TEXT_ON_DARK_MUTED = "#A5A6C4"  # texto secundario legible sobre BG_SIDEBAR

    BORDER = "#E2E8F0"

    DISABLED_BG = "#CBD5E1"
    DISABLED_TEXT = "#94A3B8"


class Typography:
    """Estilos de texto reutilizables. FONT_FAMILY se aplica una vez vía page.theme;
    estos TextStyle solo fijan tamaño/peso/espaciado, no la familia (Flet hereda la
    del tema salvo que se indique otra explícitamente)."""

    FONT_FAMILY = "Inter"

    H1 = ft.TextStyle(size=32, weight=ft.FontWeight.W_700, color=Colors.TEXT_PRIMARY)
    H2 = ft.TextStyle(size=24, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY)
    H3 = ft.TextStyle(size=18, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY)
    BODY = ft.TextStyle(size=14, weight=ft.FontWeight.W_400, color=Colors.TEXT_PRIMARY)
    BODY_SECONDARY = ft.TextStyle(size=14, weight=ft.FontWeight.W_400, color=Colors.TEXT_SECONDARY)
    LABEL = ft.TextStyle(size=12, weight=ft.FontWeight.W_500, color=Colors.TEXT_SECONDARY, letter_spacing=0.5)
    KPI_NUMBER = ft.TextStyle(size=42, weight=ft.FontWeight.W_800, color=Colors.TEXT_PRIMARY)


class Spacing:
    """Sistema de espaciado en múltiplos de 4pt."""

    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48


class Radius:
    """Radios de borde por tipo de control."""

    BUTTON = 10
    CARD = 16
    CHIP = 20
    INPUT = 12


class Shadows:
    """Sombras reutilizables (BoxShadow no admite composición con CSS-style strings
    en Flet — son objetos, uno por nivel de elevación)."""

    SM = ft.BoxShadow(spread_radius=0, blur_radius=4, color="#0F172A15")
    MD = ft.BoxShadow(spread_radius=0, blur_radius=12, color="#0F172A20")
    LG = ft.BoxShadow(spread_radius=0, blur_radius=24, color="#0F172A25")


class Motion:
    """Duraciones/curvas de animación estándar, para pasar directo a `animate=`."""

    FAST = ft.Animation(duration=150, curve=ft.AnimationCurve.EASE_OUT)
    NORMAL = ft.Animation(duration=200, curve=ft.AnimationCurve.EASE)
    SLOW = ft.Animation(duration=350, curve=ft.AnimationCurve.EASE_IN_OUT)


def gradiente(color_inicio: str, color_fin: str, diagonal: bool = True) -> ft.LinearGradient:
    """Degradado lineal estándar del sistema — mismo ángulo en toda la app.

    Args:
        color_inicio: Color hex del inicio del degradado.
        color_fin: Color hex del final del degradado.
        diagonal: Si True, va de arriba-izquierda a abajo-derecha (el ángulo
            "premium" típico de botones con gradiente); si False, va de
            izquierda a derecha (para fondos sutiles de vista completa).

    Returns:
        ft.LinearGradient: Listo para pasar a `gradient=` de un Container.
    """
    if diagonal:
        return ft.LinearGradient(
            colors=[color_inicio, color_fin],
            begin=ft.alignment.Alignment.TOP_LEFT,
            end=ft.alignment.Alignment.BOTTOM_RIGHT,
        )
    return ft.LinearGradient(
        colors=[color_inicio, color_fin],
        begin=ft.alignment.Alignment.CENTER_LEFT,
        end=ft.alignment.Alignment.CENTER_RIGHT,
    )
