package io.github.mikkey12.sprichblitz.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Locale

class LocaleResolverTest {

    @Test
    fun offSendsNothing() {
        assertNull(LocaleResolver.resolve("off", Locale.forLanguageTag("de-CH")))
    }

    @Test
    fun autoUsesDeviceLocaleAsBcp47() {
        assertEquals("de-CH", LocaleResolver.resolve("auto", Locale.forLanguageTag("de-CH")))
        assertEquals("fr-CH", LocaleResolver.resolve("AUTO", Locale.forLanguageTag("fr-CH")))
    }

    @Test
    fun explicitCodeIsSentVerbatim() {
        assertEquals("de-DE", LocaleResolver.resolve("de-DE", Locale.forLanguageTag("en-US")))
    }

    @Test
    fun blankOverrideBehavesLikeAuto() {
        assertEquals("de-CH", LocaleResolver.resolve("  ", Locale.forLanguageTag("de-CH")))
    }
}
