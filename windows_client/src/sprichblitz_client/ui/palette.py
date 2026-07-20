"""Sprichblitz-Design-System für den Windows-Client (CustomTkinter).

Spiegelt ``docs/design_system.md`` – den Vertrag. Quelle der Wahrheit ist
``backend/src/sprichblitz_backend/console_static/style.css`` (``:root`` + der
``prefers-color-scheme: dark``-Block); die Doku hält dieselben Werte fest, damit
native Clients kein CSS parsen müssen.

**Werte hier NICHT anpassen.** Fällt eine Abweichung zum Vertrag auf: melden –
der Backend-Agent pflegt ``style.css`` und die Doku gemeinsam. Der Test
``tests/unit/test_palette.py`` vergleicht dieses Modul gegen die Doku-Tabelle und
schlägt bei Drift an.

CustomTkinter nimmt für jede Farbe ein ``(hell, dunkel)``-Tupel – das passt 1:1
auf die zwei Spalten der Farbtabelle, deshalb sind die Tokens hier Tupel.
"""

from __future__ import annotations

# --- Farb-Tokens: (hell, dunkel) -------------------------------------------

ACCENT = ("#4f46e5", "#818cf8")
ON_ACCENT = ("#ffffff", "#14141c")
ACCENT_SUBTLE = ("#eeedfe", "#24243a")
DANGER = ("#b00020", "#f87171")
SUCCESS = ("#0f6e56", "#5dcaa5")
BG = ("#f6f6f7", "#131316")
SURFACE = ("#ffffff", "#1c1c21")
BORDER = ("#e4e4e7", "#2f2f36")
BORDER_STRONG = ("#c8c8cf", "#46464f")
TEXT = ("#1b1b1f", "#ececee")
TEXT_MUTED = ("#6a6a73", "#9a9aa4")

# --- Mass-Tokens (4er-Raster, keine krummen Werte) -------------------------

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS = 8  # Controls (Buttons, Felder)
RADIUS_CARD = 12  # Karten

#: Mindesthöhe für alles Antippbare (``--sb-tap``). Auf dem Desktop ist die
#: Maus präziser als ein Finger; 44 bleibt trotzdem die Untergrenze aus dem
#: Vertrag – Buttons sollen nicht darunter rutschen.
TAP = 44

# --- Typo-Tokens -----------------------------------------------------------

TEXT_XS = 12
TEXT_SM = 14
TEXT_MD = 16
TEXT_LG = 18
TEXT_XL = 22

WEIGHT_NORMAL = "normal"  # 400
WEIGHT_BOLD = "bold"  # 600 – Tk kennt nur normal/bold, 500 ist nicht darstellbar


# --- Button-Rollen ---------------------------------------------------------
#
# „Ein Akzent pro Ansicht": Genau EIN Button trägt die Akzentfläche – im
# Settings-Fenster ist das „Speichern" in der Fussleiste (auf jedem Tab
# sichtbar). Alles andere ist sekundär. Rot ist ausschliesslich destruktiv.


def primary_button() -> dict:
    """Die eine bestätigende Aktion: Akzentfläche."""
    return {
        "fg_color": ACCENT,
        "hover_color": ACCENT,
        "text_color": ON_ACCENT,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def secondary_button() -> dict:
    """Alles andere: ruhige Fläche mit Rahmen, kein Akzent."""
    return {
        "fg_color": "transparent",
        "hover_color": ACCENT_SUBTLE,
        "text_color": TEXT,
        "border_color": BORDER_STRONG,
        "border_width": 1,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def danger_button() -> dict:
    """Destruktiv (löschen, widerrufen) – roter Rahmen und Text, nie als Akzent."""
    return {
        "fg_color": "transparent",
        "hover_color": ACCENT_SUBTLE,
        "text_color": DANGER,
        "border_color": DANGER,
        "border_width": 1,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def accent_control() -> dict:
    """Kontrollen, deren aktiver Zustand den Akzent trägt (Checkbox, Slider …)."""
    return {"fg_color": ACCENT, "hover_color": ACCENT}


def entry_style() -> dict:
    """Eingabefeld: Fläche = surface, Rahmen = border-strong."""
    return {
        "fg_color": SURFACE,
        "text_color": TEXT,
        "border_color": BORDER_STRONG,
        "border_width": 1,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def card_style() -> dict:
    """Ruhige, klar abgegrenzte Inhaltsfläche."""
    return {
        "fg_color": SURFACE,
        "border_color": BORDER,
        "border_width": 1,
        "corner_radius": RADIUS_CARD,
    }


def checkbox_style() -> dict:
    """Checkbox: nur der aktive Zustand trägt den Akzent."""
    return {
        **accent_control(),
        "border_color": BORDER_STRONG,
        "text_color": TEXT,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def segmented_style() -> dict:
    """Segmentwahl mit akzentuiertem aktivem Segment."""
    return {
        "selected_color": ACCENT,
        "selected_hover_color": ACCENT,
        "unselected_color": SURFACE,
        "unselected_hover_color": ACCENT_SUBTLE,
        "text_color": TEXT,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def slider_style() -> dict:
    """Slider mit neutraler Spur und Akzent für Wert und Griff."""
    return {
        "fg_color": BORDER,
        "progress_color": ACCENT,
        "button_color": ACCENT,
        "button_hover_color": ACCENT,
    }


def option_menu_style() -> dict:
    """Auswahlfeld im selben visuellen Raster wie Eingabefelder."""
    return {
        "fg_color": SURFACE,
        "button_color": ACCENT_SUBTLE,
        "button_hover_color": ACCENT_SUBTLE,
        "text_color": TEXT,
        "dropdown_fg_color": SURFACE,
        "dropdown_hover_color": ACCENT_SUBTLE,
        "dropdown_text_color": TEXT,
        "corner_radius": RADIUS,
        "height": TAP,
    }


def textbox_style() -> dict:
    """Mehrzeiliges, read-only-taugliches Inhaltsfeld."""
    return {
        "fg_color": SURFACE,
        "text_color": TEXT,
        "border_color": BORDER_STRONG,
        "border_width": 1,
        "corner_radius": RADIUS,
    }
