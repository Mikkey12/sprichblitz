"""CLI-Smoke-Test für die Etappe-5a-Logik.

Funktioniert auch auf macOS (Backend-Host) – nutzt nur Module, die
nicht von Win32-APIs abhängen.

Ablauf (Mikrofon-Modus, Default):
    1. Config laden (auto-init bei erstem Start).
    2. Token aus Keyring; falls leer, interaktiv abfragen und speichern.
    3. ``--seconds`` Sekunden Audio aufnehmen (Default 3 s, max 59 s).
    4. RMS-VAD prüfen, bei Stille abbrechen.
    5. ``POST /full`` mit Mode aus ``--mode`` (Default ``exact_de``).
    6. ``final_text`` in die System-Zwischenablage legen (pyperclip).
    7. Latenzen + verwendete Provider auf stdout.

Ablauf (``--audio-file``-Modus):
    1.–2. wie oben.
    3. WAV-Datei vom übergebenen Pfad lesen und Format prüfen
       (16 kHz, mono, 16-bit PCM – sonst harter Fehler).
    4. VAD entfällt (File ist per Definition valide).
    5.–7. wie oben.

Beispiel:
    python -m scripts.cli_smoke --seconds 5 --mode exact_de
    python -m scripts.cli_smoke --audio-file /tmp/test.wav --mode mail
"""

from __future__ import annotations

import argparse
import getpass
import io
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

from sprichblitz_client import secrets_store
from sprichblitz_client.audio.recorder import record_for_seconds
from sprichblitz_client.audio.timeout import HARD_TIMEOUT_SECONDS
from sprichblitz_client.audio.vad.rms import RMSVAD
from sprichblitz_client.backend.client import BackendClient
from sprichblitz_client.config import load_config
from sprichblitz_client.logging_setup import configure_logging
from sprichblitz_client.models import BackendError, Mode

EXPECTED_RATE = 16000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPWIDTH = 2  # 16-bit PCM

TOKEN_ENV_VAR = "SPRICHBLITZ_BACKEND_TOKEN"


def _decode_wav_to_int16(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        rate = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    return np.frombuffer(raw, dtype=np.int16), rate


def _load_wav_file(path: Path) -> tuple[bytes, float]:
    """Liest WAV-Datei und prüft strikt 16 kHz / mono / 16-bit PCM.

    Returns: (wav_bytes, duration_seconds)
    Raises:  ValueError mit klarer Meldung bei Format-Abweichung.
    """
    if not path.exists():
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {path}")
    raw = path.read_bytes()
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            comp = wf.getcomptype()
    except wave.Error as exc:
        raise ValueError(f"Datei ist kein gültiges WAV: {path} ({exc})") from exc

    problems: list[str] = []
    if rate != EXPECTED_RATE:
        problems.append(f"Sample-Rate {rate} Hz (erwartet {EXPECTED_RATE} Hz)")
    if channels != EXPECTED_CHANNELS:
        problems.append(f"{channels} Kanäle (erwartet {EXPECTED_CHANNELS})")
    if sampwidth != EXPECTED_SAMPWIDTH:
        problems.append(
            f"{sampwidth * 8}-bit Sample-Tiefe (erwartet "
            f"{EXPECTED_SAMPWIDTH * 8}-bit PCM)"
        )
    if comp != "NONE":
        problems.append(f"Kompression '{comp}' (erwartet 'NONE'/PCM)")
    if problems:
        raise ValueError(
            "WAV-Format passt nicht zum Backend-Erwartungswert "
            "(16 kHz, mono, 16-bit PCM):\n  - " + "\n  - ".join(problems)
            + f"\nDatei: {path}\n"
            "Tipp: macOS `say --data-format=LEI16@16000 -o file.wav \"…\"` "
            "oder `ffmpeg -i in.* -ar 16000 -ac 1 -sample_fmt s16 out.wav`."
        )
    duration = n_frames / float(rate)
    return raw, duration


def _ensure_token() -> str:
    env_token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if env_token:
        # Bypass für headless Smoke-Tests (z.B. macOS-tmux ohne Keychain-UI).
        # Der produktive Windows-Client nutzt diesen Pfad NICHT, sondern liest
        # ausschliesslich via secrets_store aus dem Credential Manager.
        print(
            f"Using token from env (${TOKEN_ENV_VAR}), not keyring.",
            file=sys.stderr,
        )
        return env_token

    token = secrets_store.get_token()
    if token:
        return token
    print(
        "Kein Bearer-Token im Keyring gefunden.\n"
        f"Tipp: für headless-Tests ${TOKEN_ENV_VAR} setzen.\n"
        "Sonst Token aus backend/.env (BACKEND_AUTH_TOKEN) eingeben — "
        "wird im System-Keystore gespeichert (auf macOS: Keychain)."
    )
    token = getpass.getpass("Token: ").strip()
    if not token:
        print("Abbruch: leeres Token.", file=sys.stderr)
        sys.exit(2)
    secrets_store.set_token(token)
    print("Token gespeichert.")
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sprichblitz Client Smoke-Test")
    parser.add_argument(
        "--mode",
        type=str,
        default=Mode.exact_de.value,
        help="Backend-Modusschlüssel (config-getrieben, z. B. exact_de oder mundart)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=3.0,
        help="Aufnahme-Dauer in Sekunden (Default: 3, max 59); "
        "ignoriert wenn --audio-file gesetzt.",
    )
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=None,
        help="Pfad zu einer WAV-Datei (16 kHz mono 16-bit PCM). Wenn gesetzt, "
        "wird statt vom Mikrofon aufgenommen aus dieser Datei gelesen, und "
        "der VAD-Schritt entfällt.",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="Override für die Backend-URL (sonst aus Client-Config).",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Ergebnis nicht in die Zwischenablage legen",
    )
    args = parser.parse_args(argv)

    use_file = args.audio_file is not None
    if not use_file and (args.seconds <= 0 or args.seconds > HARD_TIMEOUT_SECONDS):
        print(
            f"--seconds muss zwischen 0 und {HARD_TIMEOUT_SECONDS} liegen.",
            file=sys.stderr,
        )
        return 2

    configure_logging("INFO")
    cfg = load_config()
    backend_url = args.backend_url or cfg.backend_url
    token = _ensure_token()
    mode = Mode(args.mode)

    print(f"Backend: {backend_url}")
    print(f"Modus:   {mode.value}")

    if use_file:
        print(f"Audio-Datei: {args.audio_file}")
        try:
            wav_bytes, duration_s = _load_wav_file(args.audio_file)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Audio-Datei-Fehler: {exc}", file=sys.stderr)
            return 2
        print(
            f"WAV geladen: {len(wav_bytes)} Bytes, {duration_s:.2f} s "
            f"@ {EXPECTED_RATE} Hz mono 16-bit PCM (Format-Check OK)"
        )
        print("VAD übersprungen (Audio aus Datei).")
    else:
        print(f"Aufnahme: {args.seconds:.1f} s @ 16 kHz mono …")
        started = time.monotonic()
        wav_bytes = record_for_seconds(args.seconds)
        record_ms = int((time.monotonic() - started) * 1000)
        print(f"Aufnahme fertig in {record_ms} ms; WAV-Bytes: {len(wav_bytes)}")

        samples, rate = _decode_wav_to_int16(wav_bytes)
        vad = RMSVAD(threshold_dbfs=cfg.vad_rms_threshold_dbfs)
        vad_result = vad.analyse(samples, rate, cfg.vad_min_speech_ratio)
        print(
            f"VAD ({vad_result.backend}): speech_ratio={vad_result.speech_ratio:.2f}, "
            f"is_speech={vad_result.is_speech}"
        )
        if not vad_result.is_speech:
            print("Keine Sprache erkannt – kein API-Call.", file=sys.stderr)
            return 3

    started = time.monotonic()
    try:
        with BackendClient(backend_url, token) as client:
            result = client.full(wav_bytes, mode)
    except BackendError as exc:
        print(f"Backend-Fehler [{exc.code}]: {exc.error}", file=sys.stderr)
        if exc.provider:
            print(f"  provider: {exc.provider}", file=sys.stderr)
        return 1
    api_ms = int((time.monotonic() - started) * 1000)

    print()
    print(f"=== Ergebnis ({api_ms} ms client-seitig, "
          f"{result.total_duration_ms} ms server-seitig) ===")
    print(f"STT: {result.stt_provider} / {result.stt_model}"
          + (" (fallback)" if result.used_fallback else ""))
    if result.llm_provider:
        print(f"LLM: {result.llm_provider} / {result.llm_model}")
    print()
    print(result.final_text)
    print()

    if not args.no_clipboard:
        try:
            import pyperclip

            pyperclip.copy(result.final_text)
            print("→ in die Zwischenablage kopiert.")
        except Exception as exc:
            print(f"Clipboard-Copy fehlgeschlagen: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
