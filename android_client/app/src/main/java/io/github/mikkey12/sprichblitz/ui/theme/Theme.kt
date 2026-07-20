package io.github.mikkey12.sprichblitz.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * Sprichblitz design tokens — mirrored from docs/design_system.md (the contract).
 * Source of truth: backend/.../console_static/style.css (:root + the
 * prefers-color-scheme: dark block). Verified identical on 2026-07-16.
 *
 * Do NOT invent or tweak values here. If a value drifts from the contract,
 * report it — the backend agent maintains style.css and the doc together.
 *
 * Deliberately NO dynamicColor / Material You: it would replace the brand accent
 * with the wallpaper palette, which defeats the purpose of a design system.
 * Light/dark follows the system (isSystemInDarkTheme) — no in-app switch.
 * The system font is Compose's default (FontFamily.Default → system-ui), which
 * is exactly what the contract demands.
 */

// --- Colour tokens ---------------------------------------------------------

private object LightTokens {
    val Accent = Color(0xFF4F46E5)
    val OnAccent = Color(0xFFFFFFFF)
    val AccentSubtle = Color(0xFFEEEDFE)
    val Danger = Color(0xFFB00020)
    val Success = Color(0xFF0F6E56)
    val Bg = Color(0xFFF6F6F7)
    val Surface = Color(0xFFFFFFFF)
    val Border = Color(0xFFE4E4E7)
    val BorderStrong = Color(0xFFC8C8CF)
    val Text = Color(0xFF1B1B1F)
    val TextMuted = Color(0xFF6A6A73)
}

private object DarkTokens {
    val Accent = Color(0xFF818CF8)
    val OnAccent = Color(0xFF14141C)
    val AccentSubtle = Color(0xFF24243A)
    val Danger = Color(0xFFF87171)
    val Success = Color(0xFF5DCAA5)
    val Bg = Color(0xFF131316)
    val Surface = Color(0xFF1C1C21)
    val Border = Color(0xFF2F2F36)
    val BorderStrong = Color(0xFF46464F)
    val Text = Color(0xFFECECEE)
    val TextMuted = Color(0xFF9A9AA4)
}

/*
 * Token → Material slot mapping (the contract names the first seven):
 *   accent        → primary          on-accent  → onPrimary
 *   surface       → surface          bg         → background
 *   danger        → error            text       → onSurface / onBackground
 *   text-muted    → onSurfaceVariant (labels, supporting text, hints)
 * Derived, so Material's defaults (purple!) never leak into a slot we render:
 *   accent-subtle → primaryContainer / secondaryContainer (badges, selected chips)
 *   border-strong → outline (field + button borders)
 *   border        → outlineVariant (hairlines) and surfaceVariant (neutral fill)
 *   surface       → all surfaceContainer* slots (cards sit on bg as --sb-surface)
 * secondary/tertiary are pinned to the accent on purpose: one accent, no stray hues.
 */
private val LightColors = with(LightTokens) {
    lightColorScheme(
        primary = Accent,
        onPrimary = OnAccent,
        primaryContainer = AccentSubtle,
        onPrimaryContainer = Text,
        secondary = Accent,
        onSecondary = OnAccent,
        secondaryContainer = AccentSubtle,
        onSecondaryContainer = Text,
        tertiary = Accent,
        onTertiary = OnAccent,
        background = Bg,
        onBackground = Text,
        surface = Surface,
        onSurface = Text,
        surfaceVariant = Border,
        onSurfaceVariant = TextMuted,
        surfaceContainerLowest = Surface,
        surfaceContainerLow = Surface,
        surfaceContainer = Surface,
        surfaceContainerHigh = Surface,
        surfaceContainerHighest = Surface,
        error = Danger,
        onError = OnAccent,
        outline = BorderStrong,
        outlineVariant = Border,
    )
}

private val DarkColors = with(DarkTokens) {
    darkColorScheme(
        primary = Accent,
        onPrimary = OnAccent,
        primaryContainer = AccentSubtle,
        onPrimaryContainer = Text,
        secondary = Accent,
        onSecondary = OnAccent,
        secondaryContainer = AccentSubtle,
        onSecondaryContainer = Text,
        tertiary = Accent,
        onTertiary = OnAccent,
        background = Bg,
        onBackground = Text,
        surface = Surface,
        onSurface = Text,
        surfaceVariant = Border,
        onSurfaceVariant = TextMuted,
        surfaceContainerLowest = Surface,
        surfaceContainerLow = Surface,
        surfaceContainer = Surface,
        surfaceContainerHigh = Surface,
        surfaceContainerHighest = Surface,
        error = Danger,
        onError = OnAccent,
        outline = BorderStrong,
        outlineVariant = Border,
    )
}

// --- Size tokens (--sb-space-*, --sb-radius*, --sb-tap) --------------------

/** 4er-Raster — keine krummen Werte. */
val Space1 = 4.dp
val Space2 = 8.dp
val Space3 = 12.dp
val Space4 = 16.dp
val Space5 = 24.dp
val Space6 = 32.dp

/** `--sb-radius` — Controls (Buttons, Felder). */
val RadiusControl = 8.dp

/** `--sb-radius-card` — Karten. */
val RadiusCard = 12.dp

/**
 * `--sb-tap` is 44dp; Material's minimum is 48dp. The stricter rule wins, so
 * anything tappable is at least this tall.
 */
val TouchTarget = 48.dp

// --- Typo tokens (--sb-text-*; weights 400/500/600, nothing else) ----------

private val SbTypography = Typography(
    // --sb-text-xl (22px), Kopfzeile
    headlineSmall = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.W600),
    // --sb-text-lg (18px), Screen-Titel
    titleLarge = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.W600),
    // --sb-text-sm (14px), Abschnitts-Titel
    titleSmall = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.W600),
    // --sb-text-md (16px), Fliesstext
    bodyLarge = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.W400),
    bodyMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.W400),
    // --sb-text-xs (12px), Hinweise/Kennzahlen
    bodySmall = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.W400),
    // --sb-text-sm (14px), Controls/Buttons — 500 laut Vertrag
    labelLarge = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.W500),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.W500),
)

/**
 * `--sb-success` has no Material slot — it is a text state („gespeichert ✓",
 * „erreichbar"), not a surface. Exposed separately so screens don't reach for
 * the accent (which must stay reserved for the one active thing).
 */
val successColor: Color
    @Composable get() = if (isSystemInDarkTheme()) DarkTokens.Success else LightTokens.Success

@Composable
fun SprichblitzTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = SbTypography,
        content = content,
    )
}
