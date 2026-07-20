package io.github.mikkey12.sprichblitz.backend

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit

/**
 * Thin HTTP client against the Sprichblitz backend. Only consumes the API —
 * the backend is untouched. Semantics mirror the Windows client
 * (windows_client/.../backend/client.py): Bearer auth on everything except
 * `/health`, transport failures normalised to [BackendError] with the synthetic
 * `connection_error` / `timeout` codes, HTTP 4xx/5xx routed through
 * [ErrorMapping.fromResponse].
 *
 * Timeouts are per-call: the token test uses a short 3 s budget, the audio
 * upload a generous 60 s one. OkHttp's `newBuilder()` shares the connection pool
 * and dispatcher, so the per-call clients are cheap.
 */
class BackendClient(
    baseUrl: String,
    private val token: String,
    private val client: OkHttpClient = defaultClient(),
) {
    private val base: String = baseUrl.trimEnd('/')

    /** `GET /health` — public, no auth. Used as the reachability probe. */
    fun health(timeoutMs: Long = 3_000): HealthResponse {
        val req = Request.Builder().url("$base/health").get().build()
        val body = call(req, timeoutMs)
        return backendJson.decodeFromString(HealthResponse.serializer(), body)
    }

    /**
     * `GET /config` (authed). Doubles as the token-validity check: a 2xx means
     * the token is accepted; any 4xx/5xx throws a mapped [BackendError].
     */
    fun checkConfig(timeoutMs: Long = 3_000) {
        val req = authed(Request.Builder().url("$base/config").get()).build()
        call(req, timeoutMs)
    }

    /** `GET /me` (authed) — profile. Used by the settings connection test. */
    fun me(timeoutMs: Long = 3_000): MeResponse {
        val req = authed(Request.Builder().url("$base/me").get()).build()
        return backendJson.decodeFromString(MeResponse.serializer(), call(req, timeoutMs))
    }

    /**
     * `POST /console/session` (authed, TLS-only server-side) — swaps the Bearer
     * for a single-use, ~60 s bootstrap code.
     *
     * SECURITY INVARIANT: the Bearer never leaves this client. Only the returned
     * code goes into the WebView URL ([consoleBootstrapUrl]); the backend then
     * sets its own HttpOnly cookie and redirects to /app/.
     *
     * [bootNonce] (optional) binds the code to a client nonce against session
     * fixation: the caller sets the same value as the `sb_boot` cookie in the
     * WebView; `GET /console/bootstrap` then requires it. Sent as
     * `X-Sb-Boot-Nonce`.
     */
    fun createConsoleSession(bootNonce: String? = null, timeoutMs: Long = 10_000): ConsoleSessionResponse {
        val builder = authed(
            Request.Builder().url("$base/console/session").post("".toRequestBody(null)),
        )
        if (bootNonce != null) builder.header("X-Sb-Boot-Nonce", bootNonce)
        return backendJson.decodeFromString(
            ConsoleSessionResponse.serializer(), call(builder.build(), timeoutMs),
        )
    }

    /**
     * URL the WebView loads. Carries ONLY the single-use code — never the Bearer.
     * Fetch the code immediately before opening (it expires in ~60 s).
     */
    fun consoleBootstrapUrl(code: String): String = "$base/console/bootstrap?code=$code"

    /** `DELETE /console/session` — idempotent console logout (needs no auth). */
    fun deleteConsoleSession(timeoutMs: Long = 5_000) {
        val req = Request.Builder().url("$base/console/session").delete().build()
        call(req, timeoutMs)
    }

    /**
     * `GET /me/modes` → effective per-mode status, rendered dynamically: every
     * mode the backend returns is kept (no fixed-enum gate), so a new backend
     * mode needs no app change.
     */
    fun modes(timeoutMs: Long = 10_000): List<ModeStatus> {
        val req = authed(Request.Builder().url("$base/me/modes").get()).build()
        val body = call(req, timeoutMs)
        val dtos = backendJson.decodeFromString(
            kotlinx.serialization.builtins.ListSerializer(ModeStatusDto.serializer()),
            body,
        )
        // Dynamic: render EVERY mode the backend returns (no fixed-enum gate), so
        // a new backend mode shows up without an app rebuild.
        return dtos.map { dto ->
            ModeStatus(
                key = dto.modeKey,
                displayName = dto.displayName?.takeIf { it.isNotBlank() } ?: dto.modeKey,
                enabled = dto.enabled,
            )
        }
    }

    /**
     * `POST /full` multipart upload. The filename ends in `.m4a` and the part
     * carries `audio/mp4` — the backend uses the extension as a format hint.
     */
    fun full(
        audioFile: File,
        modeKey: String,
        locale: String? = null,
        timeoutMs: Long = 60_000,
    ): FullResponse {
        val fileBody = audioFile.asRequestBody("audio/mp4".toMediaType())
        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "recording.m4a", fileBody)
            .addFormDataPart("mode", modeKey)
            .apply { if (!locale.isNullOrBlank()) addFormDataPart("locale", locale) }
            .build()
        val req = authed(Request.Builder().url("$base/full").post(multipart)).build()
        val body = call(req, timeoutMs)
        return backendJson.decodeFromString(FullResponse.serializer(), body)
    }

    // ------------------------------------------------------------------

    private fun authed(builder: Request.Builder): Request.Builder =
        builder.header("Authorization", "Bearer $token")

    /**
     * Execute [req] with a per-call timeout, returning the response body on
     * success or throwing a [BackendError]. Transport failures become
     * `timeout` / `connection_error`; HTTP errors go through [ErrorMapping].
     */
    private fun call(req: Request, timeoutMs: Long): String {
        // read/write must match the per-call budget: OkHttp's default readTimeout
        // is 10 s, which would fire while the backend is still computing (the
        // local exact_swiss/35B path can take >10 s) — long before callTimeout.
        val perCall = client.newBuilder()
            .callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .writeTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .build()
        try {
            perCall.newCall(req).execute().use { resp ->
                // The body read must stay inside the try: with callTimeout the
                // headers can arrive before the deadline while the body read
                // times out afterwards.
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw ErrorMapping.fromResponse(resp.code, text)
                }
                return text
            }
        } catch (e: BackendError) {
            throw e // already-mapped HTTP error — do not reclassify as transport
        } catch (e: InterruptedIOException) {
            // callTimeout / socket read timeouts surface as InterruptedIOException.
            throw BackendError(
                message = "Timeout beim Backend-Call: ${e.message}",
                code = BackendError.CODE_TIMEOUT,
            )
        } catch (e: Exception) {
            throw BackendError(
                message = "Backend nicht erreichbar: ${e.message}",
                code = BackendError.CODE_CONNECTION_ERROR,
            )
        }
    }

    companion object {
        /**
         * Default client. `callTimeout` is overridden per call; the connect
         * timeout keeps the reachability probe snappy.
         */
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .build()
    }
}
