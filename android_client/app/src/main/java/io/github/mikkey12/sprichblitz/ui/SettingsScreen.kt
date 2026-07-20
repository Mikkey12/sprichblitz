package io.github.mikkey12.sprichblitz.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import io.github.mikkey12.sprichblitz.data.Prefs
import io.github.mikkey12.sprichblitz.net.validateBackendUrl
import io.github.mikkey12.sprichblitz.ui.theme.Space1
import io.github.mikkey12.sprichblitz.ui.theme.Space2
import io.github.mikkey12.sprichblitz.ui.theme.Space4
import io.github.mikkey12.sprichblitz.ui.theme.TouchTarget
import io.github.mikkey12.sprichblitz.ui.theme.successColor

/** How the locale override is expressed: auto | off | a fixed BCP47 code. */
private enum class LocaleMode { AUTO, OFF, FIXED }

private fun localeModeOf(value: String): LocaleMode = when (value.trim().lowercase()) {
    Prefs.LOCALE_AUTO, "" -> LocaleMode.AUTO
    Prefs.LOCALE_OFF -> LocaleMode.OFF
    else -> LocaleMode.FIXED
}

/**
 * Device-local settings: backend URL, Bearer token, locale override — plus the
 * entry point into the backend console (WebView).
 *
 * Backend-side settings (BYO keys, mode overrides, processing_location, stats)
 * are deliberately NOT rebuilt natively; they live in the console.
 */
@Composable
fun SettingsScreen(
    state: UiState,
    onTest: (url: String, token: String) -> Unit,
    onSave: (
        url: String,
        token: String,
        locale: String,
    ) -> Unit,
    onOpenConsole: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var url by rememberSaveable { mutableStateOf(state.backendUrl) }
    var token by rememberSaveable { mutableStateOf("") }
    var tokenVisible by rememberSaveable { mutableStateOf(false) }
    var localeMode by rememberSaveable { mutableStateOf(localeModeOf(state.localeOverride)) }
    var localeCode by rememberSaveable {
        mutableStateOf(if (localeModeOf(state.localeOverride) == LocaleMode.FIXED) state.localeOverride else "de-CH")
    }

    val urlCheck = remember(url) { validateBackendUrl(url) }
    fun localeValue(): String = when (localeMode) {
        LocaleMode.AUTO -> Prefs.LOCALE_AUTO
        LocaleMode.OFF -> Prefs.LOCALE_OFF
        LocaleMode.FIXED -> localeCode.trim()
    }
    val busy = state.settingsTesting || state.consoleLoading

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Space4),
        verticalArrangement = Arrangement.spacedBy(Space4),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Zurück")
            }
            Text("Einstellungen", style = MaterialTheme.typography.titleLarge)
        }

        Text("Gerät", style = MaterialTheme.typography.titleSmall)

        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Backend-URL") },
            singleLine = true,
            enabled = !busy,
            isError = url.isNotBlank() && !urlCheck.ok,
            supportingText = {
                if (url.isNotBlank() && !urlCheck.ok) Text(urlCheck.message.orEmpty())
                else Text("Pflichtfeld, muss https:// sein.")
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("Bearer-Token") },
            singleLine = true,
            enabled = !busy,
            visualTransformation = if (tokenVisible) VisualTransformation.None
            else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(
                keyboardType = if (tokenVisible) KeyboardType.Text else KeyboardType.Password,
            ),
            trailingIcon = {
                IconButton(onClick = { tokenVisible = !tokenVisible }) {
                    Icon(
                        imageVector = if (tokenVisible) Icons.Filled.VisibilityOff
                        else Icons.Filled.Visibility,
                        contentDescription = if (tokenVisible) "Token verbergen" else "Token anzeigen",
                    )
                }
            },
            supportingText = {
                Text(
                    if (state.hasToken) "Gespeichert (••••). Leer lassen = unverändert; neuer Wert ersetzt ihn."
                    else "Noch kein Token gespeichert.",
                )
            },
            modifier = Modifier.fillMaxWidth(),
        )

        Text("Sprache (locale)", style = MaterialTheme.typography.titleSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(Space2)) {
            FilterChip(
                selected = localeMode == LocaleMode.AUTO,
                onClick = { localeMode = LocaleMode.AUTO },
                enabled = !busy,
                label = { Text("Automatisch") },
                modifier = Modifier.heightIn(min = TouchTarget),
            )
            FilterChip(
                selected = localeMode == LocaleMode.OFF,
                onClick = { localeMode = LocaleMode.OFF },
                enabled = !busy,
                label = { Text("Aus") },
                modifier = Modifier.heightIn(min = TouchTarget),
            )
            FilterChip(
                selected = localeMode == LocaleMode.FIXED,
                onClick = { localeMode = LocaleMode.FIXED },
                enabled = !busy,
                label = { Text("Fester Code") },
                modifier = Modifier.heightIn(min = TouchTarget),
            )
        }
        if (localeMode == LocaleMode.FIXED) {
            OutlinedTextField(
                value = localeCode,
                onValueChange = { localeCode = it },
                label = { Text("BCP47-Code") },
                singleLine = true,
                enabled = !busy,
                supportingText = { Text("z. B. de-CH, de-DE, fr-CH") },
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // Exactly ONE accent per screen: "Speichern" is the confirming action and
        // gets the filled button. Everything else stays outlined.
        Row(horizontalArrangement = Arrangement.spacedBy(Space2), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = { onTest(url, token) },
                enabled = !busy,
                modifier = Modifier.weight(1f).heightIn(min = TouchTarget),
            ) { Text(if (state.settingsTesting) "Teste…" else "Verbindung testen") }
            Button(
                onClick = {
                    onSave(url, token, localeValue())
                },
                enabled = !busy,
                modifier = Modifier.weight(1f).heightIn(min = TouchTarget),
            ) { Text("Speichern") }
        }

        if (state.settingsTesting) CircularProgressIndicator()

        state.settingsMessage?.let { msg ->
            Text(
                msg,
                // Success is --sb-success, not the accent: the accent is reserved
                // for the one active thing, it must not decorate a status line.
                color = if (state.settingsIsError) MaterialTheme.colorScheme.error
                else successColor,
                style = MaterialTheme.typography.bodyMedium,
            )
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = Space1))

        Text("Backend", style = MaterialTheme.typography.titleSmall)
        Text(
            "API-Keys, Modi-Overrides, Verarbeitungsort und Statistiken werden in " +
                "der Web-Konsole verwaltet.",
            style = MaterialTheme.typography.bodySmall,
        )
        // Outlined, not filled: navigating to the console is a secondary action —
        // the screen's one accent already belongs to "Speichern".
        OutlinedButton(
            onClick = onOpenConsole,
            enabled = !busy && state.hasToken,
            modifier = Modifier.fillMaxWidth().heightIn(min = TouchTarget),
        ) { Text(if (state.consoleLoading) "Öffne Konsole…" else "Konto & Modi öffnen") }
    }
}
