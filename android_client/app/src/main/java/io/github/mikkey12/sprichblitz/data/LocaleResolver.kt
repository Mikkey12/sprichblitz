package io.github.mikkey12.sprichblitz.data

import java.util.Locale

/**
 * Resolves the `locale` value sent to `POST /full`, mirroring the Windows
 * client's `locale_override` semantics (config.py):
 *  - "auto" → the current device locale as a BCP47 tag (e.g. `de-CH`),
 *  - "off"  → send nothing (backend applies no locale-specific correction),
 *  - anything else → treated as an explicit BCP47 code and sent verbatim.
 *
 * Pure function → unit tested.
 */
object LocaleResolver {

    fun resolve(override: String, deviceLocale: Locale = Locale.getDefault()): String? {
        return when (override.trim().lowercase(Locale.ROOT)) {
            Prefs.LOCALE_OFF -> null
            Prefs.LOCALE_AUTO, "" -> deviceLocale.toLanguageTag()
                .takeIf { it.isNotBlank() && it != "und" }
            else -> override.trim()
        }
    }
}
