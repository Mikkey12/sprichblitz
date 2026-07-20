package io.github.mikkey12.sprichblitz.net

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlValidationTest {

    @Test
    fun emptyIsHardError() {
        assertFalse(validateBackendUrl("   ").ok)
    }

    @Test
    fun nonHttpSchemeIsHardError() {
        val r = validateBackendUrl("ftp://example.com")
        assertFalse(r.ok)
        assertTrue(r.message!!.contains("https"))
    }

    @Test
    fun missingSchemeIsHardError() {
        assertFalse(validateBackendUrl("sprichblitz.example.com").ok)
    }

    @Test
    fun missingHostIsHardError() {
        assertFalse(validateBackendUrl("https://").ok)
    }

    @Test
    fun malformedSyntaxIsHardError() {
        // Unclosed IPv6 bracket → URI parse failure → syntax error, never a crash.
        val r = validateBackendUrl("http://[::1")
        assertFalse(r.ok)
        assertTrue(r.message!!.contains("Syntax"))
    }

    @Test
    fun httpsIsOk() {
        assertTrue(validateBackendUrl("https://sprichblitz.example.com").ok)
    }

    @Test
    fun httpsWithPortAndPathIsOk() {
        assertTrue(validateBackendUrl("https://192.168.1.10:8000/api").ok)
    }

    @Test
    fun whitespaceIsTrimmed() {
        assertTrue(validateBackendUrl("  https://sprichblitz.example.com  ").ok)
    }

    // --- https is mandatory everywhere (first run AND settings) --------------

    @Test
    fun httpIsRejectedEvenForLocalhostAndPrivateIps() {
        // Previously these were allowed (LAN) with no warning — now hard errors:
        // the Bearer must not travel in the clear and the console needs TLS.
        for (u in listOf(
            "http://localhost:8080",
            "http://192.168.1.10",
            "http://10.0.0.5:1234",
            "http://172.16.3.4",
            "http://[::1]:8080",
        )) {
            val r = validateBackendUrl(u)
            assertFalse(u, r.ok)
            assertTrue(u, r.message!!.contains("https"))
        }
    }

    @Test
    fun httpIsRejectedForPublicHosts() {
        for (u in listOf("http://backend.example.com", "http://8.8.8.8")) {
            val r = validateBackendUrl(u)
            assertFalse(u, r.ok)
            assertTrue(u, r.message!!.contains("https"))
        }
    }
}
