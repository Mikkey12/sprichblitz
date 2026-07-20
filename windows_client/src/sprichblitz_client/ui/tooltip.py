"""Leichter Hover-Tooltip für Tk/customtkinter + Info-Icon-Helfer.

customtkinter bringt keinen Tooltip mit. Diese Mini-Implementierung
zeigt beim Drüberfahren über ein Widget (z. B. ein „ⓘ"-Icon) eine kleine
Sprechblase mit erklärendem Text. Bewusst tkinter-nah gehalten, damit es
ohne Zusatz-Dependency funktioniert.
"""

from __future__ import annotations


class Tooltip:
    """Bindet einen Hover-Tooltip an ein bestehendes Widget."""

    def __init__(
        self,
        widget: object,
        text: str,
        *,
        wraplength: int = 340,
        delay_ms: int = 350,
    ) -> None:
        self._widget = widget
        self._text = text
        self._wrap = wraplength
        self._delay = delay_ms
        self._tip: object | None = None
        self._after_id: object | None = None
        widget.bind("<Enter>", self._schedule, add="+")  # type: ignore[attr-defined]
        widget.bind("<Leave>", self._hide, add="+")  # type: ignore[attr-defined]
        widget.bind("<ButtonPress>", self._hide, add="+")  # type: ignore[attr-defined]

    def _schedule(self, _event: object = None) -> None:
        self._cancel()
        try:
            self._after_id = self._widget.after(self._delay, self._show)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - Widget weg
            pass

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip is not None:
            return
        import tkinter as tk

        try:
            x = self._widget.winfo_rootx() + 18  # type: ignore[attr-defined]
            y = (
                self._widget.winfo_rooty()  # type: ignore[attr-defined]
                + self._widget.winfo_height()  # type: ignore[attr-defined]
                + 6
            )
        except Exception:  # pragma: no cover
            return
        tip = tk.Toplevel(self._widget)  # type: ignore[arg-type]
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip,
            text=self._text,
            justify="left",
            wraplength=self._wrap,
            background="#23262b",
            foreground="#e6e6e6",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
        ).pack()
        self._tip = tip

    def _hide(self, _event: object = None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
            self._tip = None


def attach_info_icon(parent: object, text: str) -> object:
    """Erzeugt ein kleines „ⓘ"-Label mit Hover-Tooltip und gibt es zurück.

    Aufrufer platziert das Label selbst (``grid``/``pack``)."""
    import customtkinter as ctk  # type: ignore[import-not-found]

    from . import palette

    icon = ctk.CTkLabel(
        parent,
        text="ⓘ",
        width=16,
        text_color=palette.TEXT_MUTED,
        font=ctk.CTkFont(size=palette.TEXT_SM),
    )
    try:
        icon.configure(cursor="question_arrow")
    except Exception:  # pragma: no cover - Plattform ohne Cursor
        pass
    Tooltip(icon, text)
    return icon
