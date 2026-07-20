package io.github.mikkey12.sprichblitz.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.mikkey12.sprichblitz.audio.AudioRecorder
import io.github.mikkey12.sprichblitz.backend.BackendClient
import io.github.mikkey12.sprichblitz.backend.BackendError
import io.github.mikkey12.sprichblitz.backend.ErrorMapping
import io.github.mikkey12.sprichblitz.backend.FullResponse
import io.github.mikkey12.sprichblitz.backend.FallbackModes
import io.github.mikkey12.sprichblitz.backend.ModeStatus
import io.github.mikkey12.sprichblitz.data.LocaleResolver
import io.github.mikkey12.sprichblitz.data.Prefs
import io.github.mikkey12.sprichblitz.data.SecureTokenStore
import io.github.mikkey12.sprichblitz.net.validateBackendUrl
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

enum class Screen { SETUP, MAIN, RESULT, SETTINGS, CONSOLE }

data class UiState(
    val screen: Screen = Screen.SETUP,
    // Setup
    val backendUrl: String = Prefs.DEFAULT_URL,
    val testing: Boolean = false,
    val setupMessage: String? = null,
    val setupIsError: Boolean = false,
    // Main
    val modes: List<ModeStatus> = FallbackModes.defaults,
    val selectedMode: String = FallbackModes.DEFAULT_KEY,
    val recording: Boolean = false,
    val elapsedSec: Int = 0,
    val uploading: Boolean = false,
    val error: String? = null,
    val authError: Boolean = false,
    val notice: String? = null,
    val localeOverride: String = Prefs.LOCALE_AUTO,
    // Result
    val result: FullResponse? = null,
    // Settings (device-local: URL, token, locale)
    val hasToken: Boolean = false,
    val settingsTesting: Boolean = false,
    val settingsMessage: String? = null,
    val settingsIsError: Boolean = false,
    // Console WebView — carries ONLY the single-use bootstrap code, never the Bearer
    val consoleUrl: String? = null,
    // Anti-Session-Fixation-Nonce: als sb_boot-Cookie in die WebView, gebunden an den Code.
    val consoleNonce: String? = null,
    val consoleLoading: Boolean = false,
)

/** Hard stop at 59 s — one second below the backend's 60 s limit. */
const val MAX_RECORD_SEC = 59

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = Prefs(app)
    private val tokenStore = SecureTokenStore(app)
    private val recorder = AudioRecorder(app)

    private val _state = MutableStateFlow(
        UiState(
            screen = if (tokenStore.hasToken()) Screen.MAIN else Screen.SETUP,
            backendUrl = prefs.backendUrl,
            localeOverride = prefs.localeOverride,
            hasToken = tokenStore.hasToken(),
        ),
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var timerJob: Job? = null

    init {
        if (tokenStore.hasToken()) refreshModes()
    }

    // --- Setup -------------------------------------------------------------

    fun testConnection(
        url: String,
        token: String,
    ) {
        val check = validateBackendUrl(url)
        if (!check.ok) {
            _state.update { it.copy(setupMessage = check.message, setupIsError = true) }
            return
        }
        if (token.isBlank()) {
            _state.update { it.copy(setupMessage = "Token erforderlich.", setupIsError = true) }
            return
        }
        _state.update { it.copy(testing = true, setupMessage = null, setupIsError = false) }
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val client = BackendClient(url.trim(), token.trim())
                    client.health()       // reachable?
                    client.checkConfig()  // token valid? (only a 200 here counts)
                }
            }
            result.onSuccess {
                prefs.backendUrl = url.trim()
                tokenStore.setToken(token.trim())
                _state.update {
                    it.copy(
                        testing = false,
                        setupMessage = null,
                        setupIsError = false,
                        backendUrl = prefs.backendUrl,
                        hasToken = true,
                        screen = Screen.MAIN,
                    )
                }
                refreshModes()
            }.onFailure { e ->
                _state.update {
                    it.copy(testing = false, setupMessage = messageFor(e), setupIsError = true)
                }
            }
        }
    }

    fun openSetup() {
        _state.update {
            it.copy(
                screen = Screen.SETUP,
                backendUrl = prefs.backendUrl,
                setupMessage = null,
                setupIsError = false,
                error = null,
                authError = false,
            )
        }
    }

    // --- Modes / settings --------------------------------------------------

    /** Fail-open like the Windows client: keep the static fallback on any error. */
    fun refreshModes() {
        val client = clientOrNull() ?: return
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { client.modes() } }
                .onSuccess { modes ->
                    if (modes.isNotEmpty()) {
                        _state.update { st ->
                            val stillValid = modes.any { it.key == st.selectedMode && it.enabled }
                            st.copy(
                                modes = modes,
                                selectedMode = if (stillValid) st.selectedMode
                                else modes.firstOrNull { it.enabled }?.key ?: st.selectedMode,
                            )
                        }
                    }
                }
        }
    }

    fun selectMode(key: String) = _state.update { it.copy(selectedMode = key) }

    // --- Settings (device-local) -------------------------------------------

    fun openSettings() {
        _state.update {
            it.copy(
                screen = Screen.SETTINGS,
                backendUrl = prefs.backendUrl,
                localeOverride = prefs.localeOverride,
                hasToken = tokenStore.hasToken(),
                settingsMessage = null,
                settingsIsError = false,
            )
        }
    }

    fun closeSettings() {
        _state.update {
            it.copy(screen = Screen.MAIN, settingsMessage = null, settingsIsError = false)
        }
    }

    /**
     * Persist the device-local settings. A blank [tokenInput] KEEPS the stored
     * token — the field only ever shows a mask, never the stored secret.
     */
    fun saveSettings(
        url: String,
        tokenInput: String,
        locale: String,
    ) {
        val check = validateBackendUrl(url)
        if (!check.ok) {
            _state.update { it.copy(settingsMessage = check.message, settingsIsError = true) }
            return
        }
        if (tokenInput.isBlank() && !tokenStore.hasToken()) {
            _state.update { it.copy(settingsMessage = "Token erforderlich.", settingsIsError = true) }
            return
        }
        prefs.backendUrl = url.trim()
        prefs.localeOverride = locale.trim()
        if (tokenInput.isNotBlank()) tokenStore.setToken(tokenInput.trim())
        _state.update {
            it.copy(
                backendUrl = prefs.backendUrl,
                localeOverride = prefs.localeOverride,
                hasToken = tokenStore.hasToken(),
                settingsMessage = "Gespeichert.",
                settingsIsError = false,
            )
        }
        refreshModes()
    }

    /**
     * Connection test that separates the two failure modes:
     * `/health` (no auth) fails → URL/reachability problem;
     * `/me` (Bearer) fails with auth_failed → token problem.
     */
    fun testSettings(
        url: String,
        tokenInput: String,
    ) {
        val check = validateBackendUrl(url)
        if (!check.ok) {
            _state.update { it.copy(settingsMessage = check.message, settingsIsError = true) }
            return
        }
        val token = tokenInput.ifBlank { tokenStore.getToken().orEmpty() }
        if (token.isBlank()) {
            _state.update { it.copy(settingsMessage = "Token erforderlich.", settingsIsError = true) }
            return
        }
        _state.update {
            it.copy(settingsTesting = true, settingsMessage = null, settingsIsError = false)
        }
        viewModelScope.launch {
            val (msg, isError) = withContext(Dispatchers.IO) {
                probeConnection(url.trim(), token)
            }
            _state.update {
                it.copy(settingsTesting = false, settingsMessage = msg, settingsIsError = isError)
            }
        }
    }

    /** Two-step probe → (message, isError). Blocking; call on IO. */
    private fun probeConnection(
        url: String,
        token: String,
    ): Pair<String, Boolean> {
        val client = BackendClient(url, token)
        try {
            client.health() // no auth involved → a failure here is the URL
        } catch (e: Throwable) {
            return "URL-Problem: ${messageFor(e)}" to true
        }
        return try {
            val me = client.me() // /health was fine → a failure here is the token
            "Verbunden als ${me.name} · Verarbeitung: ${me.processingLocation}" to false
        } catch (e: Throwable) {
            if ((e as? BackendError)?.code == BackendError.CODE_AUTH_FAILED) {
                "Token-Problem: Token ungültig – bitte prüfen." to true
            } else {
                "Backend erreichbar, aber /me schlug fehl: ${messageFor(e)}" to true
            }
        }
    }

    // --- Console WebView ---------------------------------------------------

    /**
     * Opens the backend console. Swaps the Bearer for a single-use bootstrap code
     * and hands ONLY that code to the WebView; the backend then sets its own
     * HttpOnly cookie and redirects to /app/. The code lives ~60 s, so it is
     * fetched immediately before opening.
     */
    fun openConsole() {
        val token = tokenStore.getToken() ?: run {
            _state.update { it.copy(settingsMessage = "Kein Token hinterlegt.", settingsIsError = true) }
            return
        }
        val check = validateBackendUrl(prefs.backendUrl)
        if (!check.ok) {
            _state.update { it.copy(settingsMessage = check.message, settingsIsError = true) }
            return
        }
        _state.update {
            it.copy(consoleLoading = true, settingsMessage = null, settingsIsError = false)
        }
        // Nonce hier erzeugen (nicht auf dem IO-Thread), damit er in onSuccess
        // in den State wandern und als sb_boot-Cookie in die WebView kann.
        val bootNonce = java.util.UUID.randomUUID().toString()
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val client = BackendClient(prefs.backendUrl, token)
                    client.consoleBootstrapUrl(client.createConsoleSession(bootNonce = bootNonce).code)
                }
            }.onSuccess { url ->
                _state.update {
                    it.copy(
                        consoleLoading = false,
                        consoleUrl = url,
                        consoleNonce = bootNonce,
                        screen = Screen.CONSOLE,
                    )
                }
            }.onFailure { e ->
                _state.update {
                    it.copy(
                        consoleLoading = false,
                        settingsMessage = "Konsole konnte nicht geöffnet werden: ${messageFor(e)}",
                        settingsIsError = true,
                    )
                }
            }
        }
    }

    /**
     * Leaves the console: drops the bootstrap URL and calls the idempotent
     * `DELETE /console/session` (needs no auth → no Bearer sent). The WebView's
     * own cookie is cleared in the UI layer via CookieManager, since the server's
     * Set-Cookie deletion only applies to the caller (OkHttp has no cookie jar).
     */
    fun closeConsole() {
        val url = prefs.backendUrl
        _state.update {
            it.copy(
                screen = Screen.SETTINGS,
                consoleUrl = null,
                consoleNonce = null,
            )
        }
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    BackendClient(url, "").deleteConsoleSession()
                }
            }
        }
    }

    fun setLocaleOverride(value: String) {
        prefs.localeOverride = value
        _state.update { it.copy(localeOverride = value) }
    }

    // --- Recording / upload ------------------------------------------------

    fun startRecording() {
        if (_state.value.recording || _state.value.uploading) return
        runCatching { recorder.start() }
            .onSuccess {
                _state.update {
                    it.copy(recording = true, elapsedSec = 0, error = null, authError = false)
                }
                startTimer()
            }
            .onFailure {
                _state.update { it.copy(error = "Aufnahme konnte nicht gestartet werden.") }
            }
    }

    /** Stop recording and upload. Called on toggle-off or at the 59 s hard stop. */
    fun stopAndUpload() {
        if (!_state.value.recording) return
        timerJob?.cancel()
        val file = recorder.stop()
        // Reset the timer immediately on stop: during upload the spinner replaces
        // the timer, and if the upload later fails we return to an idle main screen
        // that must read 00:00, not the last recording's duration.
        _state.update { it.copy(recording = false, elapsedSec = 0) }
        if (file == null) {
            _state.update { it.copy(error = "Aufnahme zu kurz oder fehlgeschlagen.") }
            return
        }
        upload(file, _state.value.selectedMode)
    }

    fun cancelRecording() {
        timerJob?.cancel()
        recorder.cancel()
        _state.update { it.copy(recording = false, elapsedSec = 0) }
    }

    private fun upload(file: File, modeKey: String) {
        val client = clientOrNull() ?: run {
            file.delete()
            _state.update { it.copy(error = "Kein Token hinterlegt.", authError = true) }
            return
        }
        val locale = LocaleResolver.resolve(prefs.localeOverride)
        _state.update { it.copy(uploading = true, error = null, authError = false) }
        viewModelScope.launch {
            try {
                val resp = withContext(Dispatchers.IO) { client.full(file, modeKey, locale) }
                _state.update {
                    it.copy(
                        uploading = false,
                        result = resp,
                        screen = Screen.RESULT,
                        notice = if (resp.usedFallback) "Fallback-Provider wurde verwendet." else null,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                val isAuth = (e as? BackendError)?.code == BackendError.CODE_AUTH_FAILED
                _state.update {
                    it.copy(uploading = false, error = messageFor(e), authError = isAuth)
                }
            } finally {
                // Privacy invariant: cancellation must not skip cleanup.
                withContext(NonCancellable + Dispatchers.IO) { file.delete() }
            }
        }
    }

    private fun startTimer() {
        timerJob?.cancel()
        timerJob = viewModelScope.launch {
            while (_state.value.recording) {
                delay(1_000)
                if (!_state.value.recording) break
                val next = _state.value.elapsedSec + 1
                _state.update { it.copy(elapsedSec = next) }
                if (next >= MAX_RECORD_SEC) {
                    stopAndUpload()
                    break
                }
            }
        }
    }

    // --- Result ------------------------------------------------------------

    fun newDictation() {
        _state.update {
            it.copy(screen = Screen.MAIN, result = null, elapsedSec = 0, error = null, notice = null)
        }
    }

    fun onMicPermissionDenied() {
        _state.update { it.copy(error = "Mikrofon-Berechtigung verweigert – Aufnahme nicht möglich.") }
    }

    fun clearError() = _state.update { it.copy(error = null) }
    fun clearNotice() = _state.update { it.copy(notice = null) }

    // --- helpers -----------------------------------------------------------

    private fun clientOrNull(): BackendClient? {
        val token = tokenStore.getToken() ?: return null
        return BackendClient(prefs.backendUrl, token)
    }

    private fun messageFor(e: Throwable): String =
        if (e is BackendError) ErrorMapping.userMessage(e)
        else e.message ?: "Unbekannter Fehler."

    override fun onCleared() {
        super.onCleared()
        recorder.cancel()
    }
}
