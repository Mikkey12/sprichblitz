package io.github.mikkey12.sprichblitz.backend

/**
 * Static fallback mode catalog — used ONLY when `GET /me/modes` is unreachable
 * (fail-open, like the Windows client). When the call succeeds, the client
 * renders whatever the backend returns; there is deliberately NO fixed enum
 * gating modes, so a new backend mode needs no app change.
 *
 * The keys must match the backend `Mode` values; the display names here are just
 * the offline placeholders (online, the effective `display_name` from the backend
 * wins).
 */
object FallbackModes {
    val defaults: List<ModeStatus> = listOf(
        ModeStatus("exact_de", "Hochdeutsch", enabled = true),
        ModeStatus("exact_swiss", "Schweizerdeutsch", enabled = true),
        ModeStatus("mail", "Mail", enabled = true),
        ModeStatus("rage", "Wut → höflich", enabled = true),
        ModeStatus("emoji", "Emoji", enabled = true),
    )

    /** Wire key of the initially selected mode. */
    const val DEFAULT_KEY: String = "exact_de"
}
