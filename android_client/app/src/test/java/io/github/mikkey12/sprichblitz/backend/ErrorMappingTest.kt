package io.github.mikkey12.sprichblitz.backend

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ErrorMappingTest {

    @Test
    fun jsonBodyPopulatesErrorCodeProvider() {
        val err = ErrorMapping.fromResponse(
            412,
            """{"error":"Kein API-Key für anthropic hinterlegt","code":"missing_provider_key","provider":"anthropic"}""",
        )
        assertEquals("missing_provider_key", err.code)
        assertEquals("anthropic", err.provider)
        assertEquals(412, err.httpStatus)
        assertTrue(err.message.contains("anthropic"))
    }

    @Test
    fun unauthorizedWithoutBodyBecomesAuthFailed() {
        val err = ErrorMapping.fromResponse(401, null)
        assertEquals(BackendError.CODE_AUTH_FAILED, err.code)
        assertTrue(err.message.contains("Token"))
    }

    @Test
    fun explicitCodeOn403IsNotOverwrittenByAuthFallback() {
        val err = ErrorMapping.fromResponse(403, """{"error":"Mode disabled: mail","code":"mode_disabled"}""")
        assertEquals("mode_disabled", err.code)
    }

    @Test
    fun nonJsonBodyKeepsGenericHttpError() {
        val err = ErrorMapping.fromResponse(500, "<html>Internal Server Error</html>")
        assertEquals(BackendError.CODE_HTTP_ERROR, err.code)
        assertEquals("HTTP 500", err.message)
        assertNull(err.provider)
    }

    @Test
    fun emptyBodyKeepsGenericHttpError() {
        val err = ErrorMapping.fromResponse(502, "")
        assertEquals(BackendError.CODE_HTTP_ERROR, err.code)
        assertEquals("HTTP 502", err.message)
    }

    @Test
    fun userMessagesAreGermanPerCode() {
        fun msg(code: String) = ErrorMapping.userMessage(BackendError("raw", code))

        assertTrue(msg("missing_provider_key").contains("Konsole"))
        assertTrue(msg("provider_key_rejected").contains("abgelehnt"))
        assertTrue(msg("mode_disabled").contains("deaktiviert"))
        assertTrue(msg("rate_limited").contains("Zu viele"))
        assertTrue(msg("backend_busy").contains("ausgelastet"))
        assertTrue(msg("audio_too_large").contains("25 MB"))
        assertTrue(msg("audio_too_long").contains("60"))
        assertTrue(msg("length_required").contains("Länge"))
        assertTrue(msg(BackendError.CODE_AUTH_FAILED).contains("Token"))
        assertTrue(msg(BackendError.CODE_CONNECTION_ERROR).contains("erreichbar"))
        assertTrue(msg(BackendError.CODE_TIMEOUT).contains("Zeitüberschreitung"))
    }

    @Test
    fun unknownCodeFallsBackToRawMessage() {
        val err = BackendError("etwas Spezielles", "weird_code")
        assertEquals("etwas Spezielles", ErrorMapping.userMessage(err))
    }
}
