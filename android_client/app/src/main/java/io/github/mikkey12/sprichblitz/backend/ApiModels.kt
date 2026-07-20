package io.github.mikkey12.sprichblitz.backend

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** Shared JSON decoder — tolerant of extra fields the client does not model. */
val backendJson: Json = Json {
    ignoreUnknownKeys = true
    isLenient = true
    explicitNulls = false
}

/** `GET /health` (public). */
@Serializable
data class HealthResponse(
    val status: String = "ok",
    val version: String = "",
    @SerialName("uptime_seconds") val uptimeSeconds: Long = 0,
)

/** One entry of `GET /me/modes`. */
@Serializable
data class ModeStatusDto(
    @SerialName("mode_key") val modeKey: String,
    @SerialName("display_name") val displayName: String? = null,
    val enabled: Boolean = true,
)

/** `POST /full` success payload (subset the client actually uses). */
@Serializable
data class FullResponse(
    @SerialName("final_text") val finalText: String,
    @SerialName("raw_text") val rawText: String = "",
    @SerialName("used_fallback") val usedFallback: Boolean = false,
    @SerialName("stt_provider") val sttProvider: String = "",
    @SerialName("llm_provider") val llmProvider: String? = null,
    @SerialName("total_duration_ms") val totalDurationMs: Long = 0,
    @SerialName("audio_seconds") val audioSeconds: Double = 0.0,
)

/** `GET /me` — profile + which BYO provider keys are present. */
@Serializable
data class MeResponse(
    val name: String = "",
    @SerialName("processing_location") val processingLocation: String = "",
    val keys: Map<String, Boolean> = emptyMap(),
)

/**
 * `POST /console/session` — swaps the Bearer for a single-use bootstrap code
 * (~60 s). Only this code may travel into the WebView URL, never the Bearer.
 */
@Serializable
data class ConsoleSessionResponse(
    val code: String,
    @SerialName("expires_in") val expiresIn: Int = 0,
)

/** Backend error envelope: `{error, code, provider?}`. */
@Serializable
data class ErrorBody(
    val error: String? = null,
    val code: String? = null,
    val provider: String? = null,
)

/**
 * Effective per-mode status shown as chips on the main screen. Built dynamically
 * from [ModeStatusDto] (online) or the static [FallbackModes] catalog (offline).
 *
 * [key] is the wire value sent as the `mode` field. The client no longer gates
 * modes through a fixed enum, so a NEW backend mode appears with no app rebuild.
 */
data class ModeStatus(
    val key: String,
    val displayName: String,
    val enabled: Boolean,
)
