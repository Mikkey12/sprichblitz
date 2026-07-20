package io.github.mikkey12.sprichblitz.ui

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.PersistableBundle
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.getSystemService
import io.github.mikkey12.sprichblitz.backend.FullResponse

@Composable
fun ResultScreen(
    result: FullResponse,
    onNewDictation: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current

    // Auto-copy the finished text on arrival (sensitive flag set).
    LaunchedEffect(result) { copySensitive(context, result.finalText) }

    Column(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Fertig – in die Zwischenablage kopiert", style = MaterialTheme.typography.titleMedium)

        Card(modifier = Modifier.fillMaxWidth().weight(1f)) {
            Text(
                text = result.finalText,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = { shareText(context, result.finalText) }, modifier = Modifier.weight(1f)) {
                Icon(Icons.Filled.Share, contentDescription = null)
                Text("  Teilen")
            }
            OutlinedButton(
                onClick = { copySensitive(context, result.finalText) },
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Filled.ContentCopy, contentDescription = null)
                Text("  Kopieren")
            }
        }

        OutlinedButton(onClick = onNewDictation, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Refresh, contentDescription = null)
            Text("  Neu diktieren")
        }
    }
}

/** Copy to clipboard, flagged sensitive so the OS keeps it out of previews/history. */
private fun copySensitive(context: Context, text: String) {
    val clipboard = context.getSystemService<ClipboardManager>() ?: return
    val clip = ClipData.newPlainText("Sprichblitz", text)
    clip.description.extras = PersistableBundle().apply {
        putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
    }
    clipboard.setPrimaryClip(clip)
}

private fun shareText(context: Context, text: String) {
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(send, "Teilen"))
}
