package io.github.mikkey12.sprichblitz

import io.github.mikkey12.sprichblitz.ui.Screen
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityTest {
    @Test
    fun `sensitive screens block screenshots and recents previews`() {
        assertTrue(shouldUseSecureFlag(Screen.SETUP))
        assertTrue(shouldUseSecureFlag(Screen.SETTINGS))
        assertTrue(shouldUseSecureFlag(Screen.CONSOLE))
        assertTrue(shouldUseSecureFlag(Screen.RESULT))
        assertFalse(shouldUseSecureFlag(Screen.MAIN))
    }
}
