"""Windows-Runtime-Smoke für die tatsächlich verwendeten CustomTkinter-APIs."""

from __future__ import annotations

import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="benötigt Windows-Tk")
def test_customtkinter_widgets_accept_design_system_styles() -> None:
    """Major-Upgrades müssen echte Widgets bauen, nicht nur Imports bestehen."""
    import customtkinter as ctk

    from sprichblitz_client.ui import palette

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.withdraw()
    try:
        card = ctk.CTkFrame(root, **palette.card_style())
        ctk.CTkLabel(card, text="Sprichblitz", text_color=palette.TEXT)
        ctk.CTkButton(card, text="Speichern", **palette.primary_button())
        ctk.CTkEntry(card, **palette.entry_style())
        ctk.CTkCheckBox(card, text="Aktiv", **palette.checkbox_style())
        ctk.CTkTextbox(card, **palette.textbox_style())
        ctk.CTkScrollableFrame(card, fg_color="transparent")
        ctk.CTkSegmentedButton(card, values=["A", "B"], **palette.segmented_style())
        ctk.CTkSlider(card, **palette.slider_style())
        ctk.CTkOptionMenu(card, values=["A", "B"], **palette.option_menu_style())
        tabs = ctk.CTkTabview(
            card,
            fg_color=palette.SURFACE,
            segmented_button_selected_color=palette.ACCENT,
            segmented_button_selected_hover_color=palette.ACCENT,
            segmented_button_unselected_color=palette.SURFACE,
            segmented_button_unselected_hover_color=palette.ACCENT_SUBTLE,
            text_color=palette.TEXT,
            corner_radius=palette.RADIUS_CARD,
        )
        tabs.add("Backend")
        card.pack()
        root.update_idletasks()
    finally:
        root.destroy()
