package io.github.mikkey12.sprichblitz.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Keystore-backed storage for the Bearer token. The secret never enters normal prefs or logs. */
class SecureTokenStore(context: Context) {

    private val appContext = context.applicationContext

    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    init {
        // Einmalige Migration: Werte der entfernten Clientfunktion löschen.
        // Sie werden weder gelesen noch übertragen.
        prefs.edit()
            .remove(REMOVED_CF_CLIENT_ID)
            .remove(REMOVED_CF_CLIENT_SECRET)
            .apply()
    }

    fun getToken(): String? = prefs.getString(KEY_TOKEN, null)?.takeIf { it.isNotBlank() }

    fun hasToken(): Boolean = getToken() != null

    fun setToken(token: String) {
        prefs.edit().putString(KEY_TOKEN, token).apply()
    }

    fun clear() {
        prefs.edit().remove(KEY_TOKEN).apply()
    }

    companion object {
        private const val FILE_NAME = "sprichblitz_secret"
        private const val KEY_TOKEN = "bearer_token"
        private const val REMOVED_CF_CLIENT_ID = "cf_access_client_id"
        private const val REMOVED_CF_CLIENT_SECRET = "cf_access_client_secret"
    }
}
