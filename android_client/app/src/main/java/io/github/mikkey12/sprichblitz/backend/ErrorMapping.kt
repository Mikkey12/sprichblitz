package io.github.mikkey12.sprichblitz.backend

/**
 * Pure error mapping — no Android, no OkHttp types — so it is fully unit
 * testable. Ports `_error_from_response` from the Windows client
 * (windows_client/.../backend/client.py) and adds the German UI-message table
 * required by the Android brief.
 */
object ErrorMapping {

    /**
     * Turn an HTTP status + (maybe-JSON) body into a [BackendError], following
     * the same precedence as the Windows client:
     *  - start with generic `http_error` / `HTTP <status>`,
     *  - overlay `error` / `code` / `provider` from a JSON `{error,code,provider}`,
     *  - if it is a 401/403 that carried no explicit code, treat it as auth_failed.
     */
    fun fromResponse(status: Int, body: String?): BackendError {
        var code = BackendError.CODE_HTTP_ERROR
        var error = "HTTP $status"
        var provider: String? = null

        if (!body.isNullOrBlank()) {
            try {
                val parsed = backendJson.decodeFromString(ErrorBody.serializer(), body)
                parsed.error?.takeIf { it.isNotBlank() }?.let { error = it }
                parsed.code?.takeIf { it.isNotBlank() }?.let { code = it }
                provider = parsed.provider?.takeIf { it.isNotBlank() }
            } catch (_: Exception) {
                // Body was not the expected JSON — keep the generic message.
            }
        }

        if (status in intArrayOf(401, 403) && code == BackendError.CODE_HTTP_ERROR) {
            code = BackendError.CODE_AUTH_FAILED
            error = "Authentifizierung fehlgeschlagen – Bearer-Token prüfen."
        }

        return BackendError(message = error, code = code, provider = provider, httpStatus = status)
    }

    /**
     * Stable, user-facing German message for a [BackendError]. Falls back to the
     * backend's own `error` text for codes we do not special-case.
     */
    fun userMessage(err: BackendError): String = when (err.code) {
        "missing_provider_key" ->
            "Für diesen Modus fehlt ein API-Key. Bitte in der Sprichblitz-Konsole hinterlegen."
        "provider_key_rejected" ->
            "Der hinterlegte API-Key wurde abgelehnt. Bitte in der Konsole prüfen/erneuern."
        "provider_key_undecryptable" ->
            "Der hinterlegte API-Key ist nicht mehr lesbar. Bitte in der Konsole neu hinterlegen."
        "mode_disabled" ->
            "Dieser Modus ist deaktiviert."
        "mode_misconfigured" ->
            "Dieser Modus ist fehlerhaft konfiguriert (Provider/Prompt fehlt)."
        "rate_limited" ->
            "Zu viele Anfragen – bitte kurz warten und erneut versuchen."
        "backend_busy" ->
            "Das Backend ist gerade ausgelastet – bitte erneut versuchen."
        "audio_too_large" ->
            "Die Aufnahme ist zu gross (max. 25 MB)."
        "audio_too_long" ->
            "Die Aufnahme ist zu lang (max. 60 Sekunden)."
        "length_required" ->
            "Upload abgelehnt: Länge des Audios konnte nicht bestimmt werden."
        BackendError.CODE_AUTH_FAILED ->
            "Zugang abgelehnt – Bearer-Token in den Einstellungen prüfen."
        BackendError.CODE_CONNECTION_ERROR ->
            "Backend nicht erreichbar. Netzwerkverbindung prüfen."
        BackendError.CODE_TIMEOUT ->
            "Zeitüberschreitung beim Backend. Bitte erneut versuchen."
        else -> err.message
    }
}
