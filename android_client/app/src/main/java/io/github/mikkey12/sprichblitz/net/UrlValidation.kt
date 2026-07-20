package io.github.mikkey12.sprichblitz.net

import java.net.URI

/**
 * Result of validating a backend URL. [ok] == false is a hard error → block
 * saving; [message] then says why.
 */
data class BackendUrlCheck(
    val ok: Boolean,
    val message: String? = null,
)

/**
 * Validate a backend URL (pure, UI-free, unit tested). One rule everywhere —
 * first run and settings alike:
 *  - non-empty, parseable, host present,
 *  - **https is mandatory**.
 *
 * Why https-only (unlike the Windows client, which still allows http to
 * localhost/RFC-1918): the Bearer travels on every authed call, and the console
 * bootstrap is TLS-only server-side (`require_tls` on `POST /console/session` +
 * `GET /console/bootstrap`, because it mints a Secure cookie). An http backend
 * would silently break the console and ship the token in the clear, so the
 * client rejects it outright rather than warning about it.
 */
fun validateBackendUrl(raw: String): BackendUrlCheck {
    val url = raw.trim()
    if (url.isEmpty()) {
        return BackendUrlCheck(false, "Backend-URL erforderlich.")
    }

    val uri = try {
        URI(url)
    } catch (_: Exception) {
        return BackendUrlCheck(false, "URL ist ungültig (fehlerhafte Syntax).")
    }

    val scheme = uri.scheme?.lowercase()
    val host = uri.host
    if (scheme == null || (scheme != "http" && scheme != "https")) {
        return BackendUrlCheck(false, "URL muss mit https:// beginnen.")
    }
    if (host.isNullOrEmpty()) {
        return BackendUrlCheck(false, "URL hat keinen gültigen Host.")
    }
    if (scheme != "https") {
        return BackendUrlCheck(
            false,
            "Backend-URL muss https:// sein – http überträgt Token und Diktattext " +
                "unverschlüsselt, und die Konsole verlangt TLS.",
        )
    }
    return BackendUrlCheck(true)
}
