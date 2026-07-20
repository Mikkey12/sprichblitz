package io.github.mikkey12.sprichblitz.backend

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.File

class BackendClientTest {

    private lateinit var server: MockWebServer
    private lateinit var client: BackendClient
    private lateinit var audio: File

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        client = BackendClient(server.url("/").toString(), token = "secret-token")
        audio = File.createTempFile("recording", ".m4a").apply { writeBytes(ByteArray(64) { it.toByte() }) }
    }

    @After
    fun tearDown() {
        server.shutdown()
        audio.delete()
    }

    @Test
    fun healthParsesAndNeedsNoAuth() {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"status":"ok","version":"1.2.3","uptime_seconds":42}"""),
        )
        val h = client.health()
        assertEquals("1.2.3", h.version)
        assertEquals(42L, h.uptimeSeconds)

        val req = server.takeRequest()
        assertEquals("/health", req.path)
        // /health is public — client must not send Authorization.
        assertEquals(null, req.getHeader("Authorization"))
    }

    @Test
    fun checkConfigSendsBearerAndSucceedsOn200() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"version":"1"}"""))
        client.checkConfig()
        val req = server.takeRequest()
        assertEquals("/config", req.path)
        assertEquals("Bearer secret-token", req.getHeader("Authorization"))
    }

    @Test
    fun checkConfigMapsUnauthorizedToAuthFailed() {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        try {
            client.checkConfig()
            fail("expected BackendError")
        } catch (e: BackendError) {
            assertEquals(BackendError.CODE_AUTH_FAILED, e.code)
        }
    }

    @Test
    fun fullUploadsMultipartWithModeAndFilename() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"mode":"exact_de","raw_text":"roh","final_text":"Fertiger Text",""" +
                    """"stt_provider":"whisper","llm_provider":null,"used_fallback":false,""" +
                    """"audio_seconds":3.5,"total_duration_ms":1200}""",
            ),
        )
        val res = client.full(audio, "exact_de", locale = "de-CH")
        assertEquals("Fertiger Text", res.finalText)
        assertEquals(3.5, res.audioSeconds, 0.0001)
        assertFalse(res.usedFallback)

        val req = server.takeRequest()
        assertEquals("/full", req.path)
        assertEquals("POST", req.method)
        assertEquals("Bearer secret-token", req.getHeader("Authorization"))
        val bodyText = req.body.readUtf8()
        assertTrue(bodyText.contains("name=\"file\""))
        assertTrue(bodyText.contains("recording.m4a"))
        assertTrue(bodyText.contains("name=\"mode\""))
        assertTrue(bodyText.contains("exact_de"))
        assertTrue(bodyText.contains("name=\"locale\""))
        assertTrue(bodyText.contains("de-CH"))
    }

    @Test
    fun fullOmitsLocaleWhenNull() {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"final_text":"x","total_duration_ms":1}"""),
        )
        client.full(audio, "mail", locale = null)
        val bodyText = server.takeRequest().body.readUtf8()
        assertFalse(bodyText.contains("name=\"locale\""))
    }

    @Test
    fun fullMapsMissingProviderKeyError() {
        server.enqueue(
            MockResponse().setResponseCode(412).setBody(
                """{"error":"Kein API-Key für anthropic hinterlegt","code":"missing_provider_key"}""",
            ),
        )
        try {
            client.full(audio, "rage")
            fail("expected BackendError")
        } catch (e: BackendError) {
            assertEquals("missing_provider_key", e.code)
            assertEquals(412, e.httpStatus)
        }
    }

    @Test
    fun modesAreDynamicKeepingUnknownKeysWithDisplayNameFallback() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[
                  {"mode_key":"exact_de","display_name":"Hochdeutsch","enabled":true},
                  {"mode_key":"mail","display_name":null,"enabled":false},
                  {"mode_key":"future_mode","display_name":"X","enabled":true}
                ]""",
            ),
        )
        val modes = client.modes()
        // Dynamic: every backend mode is kept, incl. one the app has never heard of.
        assertEquals(3, modes.size)
        val exact = modes.first { it.key == "exact_de" }
        assertEquals("Hochdeutsch", exact.displayName)
        assertTrue(exact.enabled)
        val mail = modes.first { it.key == "mail" }
        assertEquals("mail", mail.displayName) // null display_name → falls back to the key
        assertFalse(mail.enabled)
        val future = modes.first { it.key == "future_mode" }
        assertEquals("X", future.displayName) // unknown mode still rendered
        assertTrue(future.enabled)
    }

    @Test
    fun meSendsBearerAndParsesProfile() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"name":"demo","processing_location":"local","keys":{"openai":true,"anthropic":false}}""",
            ),
        )
        val me = client.me()
        assertEquals("demo", me.name)
        assertEquals("local", me.processingLocation)
        assertEquals(true, me.keys["openai"])

        val req = server.takeRequest()
        assertEquals("/me", req.path)
        assertEquals("Bearer secret-token", req.getHeader("Authorization"))
    }

    @Test
    fun createConsoleSessionPostsWithBearerAndReturnsCode() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody("""{"code":"abc123","expires_in":60}"""),
        )
        val res = client.createConsoleSession(bootNonce = "nonce-123")
        assertEquals("abc123", res.code)
        assertEquals(60, res.expiresIn)

        val req = server.takeRequest()
        assertEquals("/console/session", req.path)
        assertEquals("POST", req.method)
        assertEquals("Bearer secret-token", req.getHeader("Authorization"))
        assertEquals("nonce-123", req.getHeader("X-Sb-Boot-Nonce"))
    }

    @Test
    fun consoleBootstrapUrlCarriesOnlyTheCodeNeverTheBearer() {
        val url = client.consoleBootstrapUrl("abc123")
        assertTrue(url.endsWith("/console/bootstrap?code=abc123"))
        // The security invariant: the Bearer must never end up in the WebView URL.
        assertFalse(url.contains("secret-token"))
        assertFalse(url.contains("Bearer"))
    }

    @Test
    fun deleteConsoleSessionSendsNoBearer() {
        server.enqueue(MockResponse().setResponseCode(204))
        client.deleteConsoleSession()
        val req = server.takeRequest()
        assertEquals("/console/session", req.path)
        assertEquals("DELETE", req.method)
        // Logout needs no auth → don't send the durable credential.
        assertEquals(null, req.getHeader("Authorization"))
    }

    @Test
    fun timeoutSurfacesAsTimeoutCode() {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"final_text":"x","total_duration_ms":1}""")
                .setBodyDelay(2, java.util.concurrent.TimeUnit.SECONDS),
        )
        try {
            client.full(audio, "exact_de", timeoutMs = 300)
            fail("expected timeout BackendError")
        } catch (e: BackendError) {
            assertEquals(BackendError.CODE_TIMEOUT, e.code)
        }
    }
}
