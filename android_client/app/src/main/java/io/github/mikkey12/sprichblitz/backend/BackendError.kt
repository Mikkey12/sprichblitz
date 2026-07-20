package io.github.mikkey12.sprichblitz.backend

/**
 * Normalised backend failure. Mirrors the Windows client's `BackendError`
 * (windows_client/.../models) plus a couple of client-only synthetic codes for
 * transport problems (no JSON body from the server in those cases).
 *
 * [message] is the raw backend `error` text (English/German as the backend
 * sends it); [userMessage] turns [code] into a stable German UI string.
 */
class BackendError(
    override val message: String,
    val code: String,
    val provider: String? = null,
    val httpStatus: Int? = null,
) : Exception(message) {

    companion object {
        // Client-only synthetic codes (no server response involved).
        const val CODE_CONNECTION_ERROR = "connection_error"
        const val CODE_TIMEOUT = "timeout"
        const val CODE_HTTP_ERROR = "http_error"
        const val CODE_AUTH_FAILED = "auth_failed"
    }
}
