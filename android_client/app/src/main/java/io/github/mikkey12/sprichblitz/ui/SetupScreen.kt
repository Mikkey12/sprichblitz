package io.github.mikkey12.sprichblitz.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import io.github.mikkey12.sprichblitz.net.validateBackendUrl

@Composable
fun SetupScreen(
    state: UiState,
    onTest: (url: String, token: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var url by rememberSaveable { mutableStateOf(state.backendUrl) }
    var token by rememberSaveable { mutableStateOf("") }
    var tokenVisible by rememberSaveable { mutableStateOf(false) }

    // Live URL check — https is mandatory, so anything invalid is a hard error.
    val urlCheck = remember(url) { validateBackendUrl(url) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Einrichtung", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Backend-URL und Zugriffs-Token eingeben, dann die Verbindung testen.",
            style = MaterialTheme.typography.bodyMedium,
        )

        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Backend-URL") },
            singleLine = true,
            enabled = !state.testing,
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
            label = { Text("Token") },
            singleLine = true,
            enabled = !state.testing,
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
            supportingText = { Text("Aus der Zwischenablage einfügen und mit dem Auge kontrollieren.") },
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = { onTest(url, token) },
            enabled = !state.testing,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (state.testing) "Teste…" else "Verbindung testen")
        }

        if (state.testing) {
            CircularProgressIndicator()
        }

        state.setupMessage?.let { msg ->
            Text(
                msg,
                color = if (state.setupIsError) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
