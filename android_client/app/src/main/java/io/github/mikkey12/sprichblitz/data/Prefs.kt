package io.github.mikkey12.sprichblitz.data

import android.content.Context

/**
 * Non-secret settings (backend URL, locale override). Plain SharedPreferences —
 * the Bearer token deliberately does NOT live here (see [SecureTokenStore]).
 */
class Prefs(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences("sprichblitz_prefs", Context.MODE_PRIVATE)

    var backendUrl: String
        get() = prefs.getString(KEY_URL, DEFAULT_URL)?.takeIf { it.isNotBlank() } ?: DEFAULT_URL
        set(value) = prefs.edit().putString(KEY_URL, value.trim()).apply()

    /** "auto" = device locale, "off" = send nothing, or a fixed BCP47 code. */
    var localeOverride: String
        get() = prefs.getString(KEY_LOCALE, LOCALE_AUTO) ?: LOCALE_AUTO
        set(value) = prefs.edit().putString(KEY_LOCALE, value.trim()).apply()

    companion object {
        const val DEFAULT_URL = "https://sprichblitz.example.com"
        const val LOCALE_AUTO = "auto"
        const val LOCALE_OFF = "off"
        private const val KEY_URL = "backend_url"
        private const val KEY_LOCALE = "locale_override"
    }
}
