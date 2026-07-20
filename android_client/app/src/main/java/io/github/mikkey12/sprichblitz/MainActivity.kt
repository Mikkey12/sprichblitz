package io.github.mikkey12.sprichblitz

import android.app.Activity
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.mikkey12.sprichblitz.ui.AppViewModel
import io.github.mikkey12.sprichblitz.ui.ConsoleScreen
import io.github.mikkey12.sprichblitz.ui.MainScreen
import io.github.mikkey12.sprichblitz.ui.ResultScreen
import io.github.mikkey12.sprichblitz.ui.Screen
import io.github.mikkey12.sprichblitz.ui.SettingsScreen
import io.github.mikkey12.sprichblitz.ui.SetupScreen
import io.github.mikkey12.sprichblitz.ui.theme.SprichblitzTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SprichblitzTheme {
                val vm: AppViewModel = viewModel()
                val state by vm.state.collectAsStateWithLifecycle()
                val snackbar = remember { SnackbarHostState() }

                // Secrets and transcripts must not appear in screenshots or the
                // recents preview (setup/settings/console/result).
                SecureFlag(
                    active = shouldUseSecureFlag(state.screen),
                )

                // Surface transient errors / notices as snackbars.
                LaunchedEffect(state.error) {
                    val msg = state.error ?: return@LaunchedEffect
                    if (state.authError) {
                        val res = snackbar.showSnackbar(
                            message = msg,
                            actionLabel = "Einstellungen",
                            duration = SnackbarDuration.Long,
                        )
                        if (res == SnackbarResult.ActionPerformed) vm.openSettings()
                    } else {
                        snackbar.showSnackbar(msg, duration = SnackbarDuration.Short)
                    }
                    vm.clearError()
                }
                LaunchedEffect(state.notice) {
                    val msg = state.notice ?: return@LaunchedEffect
                    snackbar.showSnackbar(msg, duration = SnackbarDuration.Short)
                    vm.clearNotice()
                }

                Scaffold(
                    modifier = Modifier.fillMaxSize(),
                    snackbarHost = { SnackbarHost(snackbar) },
                ) { inner ->
                    val content = Modifier.padding(inner)
                    val main = @Composable {
                        MainScreen(
                            state = state,
                            onSelectMode = vm::selectMode,
                            onStartRecording = vm::startRecording,
                            onStopRecording = vm::stopAndUpload,
                            onMicDenied = vm::onMicPermissionDenied,
                            onOpenSettings = vm::openSettings,
                            modifier = content,
                        )
                    }
                    when (state.screen) {
                        Screen.SETUP -> SetupScreen(
                            state = state,
                            onTest = vm::testConnection,
                            modifier = content,
                        )
                        Screen.MAIN -> main()
                        Screen.SETTINGS -> SettingsScreen(
                            state = state,
                            onTest = vm::testSettings,
                            onSave = vm::saveSettings,
                            onOpenConsole = vm::openConsole,
                            onBack = vm::closeSettings,
                            modifier = content,
                        )
                        Screen.CONSOLE -> {
                            val url = state.consoleUrl
                            if (url != null) {
                                ConsoleScreen(
                                    url = url,
                                    nonce = state.consoleNonce,
                                    onClose = vm::closeConsole,
                                    modifier = content,
                                )
                            } else {
                                // Defensive: no bootstrap URL → back to settings.
                                SettingsScreen(
                                    state = state,
                                    onTest = vm::testSettings,
                                    onSave = vm::saveSettings,
                                    onOpenConsole = vm::openConsole,
                                    onBack = vm::closeSettings,
                                    modifier = content,
                                )
                            }
                        }
                        Screen.RESULT -> {
                            val result = state.result
                            if (result != null) {
                                ResultScreen(
                                    result = result,
                                    onNewDictation = vm::newDictation,
                                    modifier = content,
                                )
                            } else {
                                // Defensive: no result → fall back to main.
                                main()
                            }
                        }
                    }
                }
            }
        }
    }
}

internal fun shouldUseSecureFlag(screen: Screen): Boolean = when (screen) {
    Screen.SETUP, Screen.SETTINGS, Screen.CONSOLE, Screen.RESULT -> true
    Screen.MAIN -> false
}

@Composable
private fun SecureFlag(active: Boolean) {
    val view = LocalView.current
    DisposableEffect(active) {
        val window = (view.context as? Activity)?.window
        if (active) window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        else window?.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
    }
}
