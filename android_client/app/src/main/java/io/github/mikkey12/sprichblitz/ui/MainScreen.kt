package io.github.mikkey12.sprichblitz.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import io.github.mikkey12.sprichblitz.ui.theme.Space2
import io.github.mikkey12.sprichblitz.ui.theme.Space4
import io.github.mikkey12.sprichblitz.ui.theme.TouchTarget

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MainScreen(
    state: UiState,
    onSelectMode: (String) -> Unit,
    onStartRecording: () -> Unit,
    onStopRecording: () -> Unit,
    onMicDenied: () -> Unit,
    onOpenSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> if (granted) onStartRecording() else onMicDenied() }

    fun onRecordButton() {
        if (state.recording) {
            onStopRecording()
            return
        }
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) onStartRecording() else permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
    }

    Column(modifier = modifier.fillMaxSize().padding(Space4)) {
        // Header with settings menu.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Sprichblitz",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Filled.Settings, contentDescription = "Einstellungen")
            }
        }

        Spacer(Modifier.height(Space4))

        // Mode chips (disabled modes greyed out). Chips are tappable → TouchTarget.
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(Space2),
            verticalArrangement = Arrangement.spacedBy(Space2),
        ) {
            state.modes.forEach { m ->
                FilterChip(
                    selected = state.selectedMode == m.key,
                    onClick = { if (m.enabled) onSelectMode(m.key) },
                    enabled = m.enabled && !state.recording && !state.uploading,
                    label = { Text(m.displayName) },
                    modifier = Modifier.heightIn(min = TouchTarget),
                )
            }
        }

        Spacer(Modifier.weight(1f))

        // Big record button + status.
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            when {
                state.uploading -> UploadingIndicator()
                else -> RecordButton(
                    recording = state.recording,
                    elapsedSec = state.elapsedSec,
                    onClick = ::onRecordButton,
                )
            }
        }

        Spacer(Modifier.weight(1f))

        Text(
            if (state.recording) "Aufnahme läuft – erneut tippen zum Beenden (max. ${MAX_RECORD_SEC}s)"
            else if (state.uploading) "Wird verarbeitet…"
            else "Modus wählen und tippen, um zu diktieren",
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth().padding(vertical = Space2),
        )
    }
}

/**
 * The one primary action of this screen → it carries the accent, in BOTH states.
 *
 * It used to turn red while recording. The contract is explicit: red is
 * exclusively destructive ("nie als Hervorhebung") — and stopping a recording
 * destroys nothing. The Mic↔Stop icon plus the running timer carry the state.
 */
@Composable
private fun RecordButton(recording: Boolean, elapsedSec: Int, onClick: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Surface(
            onClick = onClick,
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(140.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    imageVector = if (recording) Icons.Filled.Stop else Icons.Filled.Mic,
                    contentDescription = if (recording) "Stopp" else "Aufnehmen",
                    // onPrimary, not white: on the dark accent the token is near-black.
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(56.dp),
                )
            }
        }
        Spacer(Modifier.height(Space4))
        Text(
            text = formatElapsed(elapsedSec),
            fontFamily = FontFamily.Monospace,
            fontSize = 28.sp,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun UploadingIndicator() {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier = Modifier
                .size(140.dp)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            CircularProgressIndicator()
        }
        Spacer(Modifier.height(Space4))
        Text("Hochladen…", style = MaterialTheme.typography.titleMedium)
    }
}

private fun formatElapsed(sec: Int): String = "%02d:%02d".format(sec / 60, sec % 60)
