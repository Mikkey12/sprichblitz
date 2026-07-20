package io.github.mikkey12.sprichblitz.ui

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView

/**
 * Hosts the backend console ("Konto & Modi") in a WebView.
 *
 * SECURITY INVARIANT: the Bearer NEVER reaches this WebView — not as a header,
 * not as a query param, and there is deliberately **no JavaScript bridge**
 * (`addJavascriptInterface`). [url] is the `/console/bootstrap?code=…` URL; its
 * single-use, ~60 s code is all that travels here. The backend redeems it, sets
 * its own HttpOnly+Secure cookie and redirects to `/app/` (same origin, so no
 * third-party cookie is needed).
 */
@SuppressLint("SetJavaScriptEnabled") // the console is vanilla JS, served same-origin by our backend
@Composable
fun ConsoleScreen(
    url: String,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    nonce: String? = null,
) {
    val webViewRef = remember { mutableStateOf<WebView?>(null) }

    BackHandler {
        val wv = webViewRef.value
        if (wv != null && wv.canGoBack()) wv.goBack() else onClose()
    }

    // Drop the console cookie when the screen goes away. The server's Set-Cookie
    // deletion from DELETE /console/session only reaches the caller (OkHttp, which
    // has no cookie jar), and sb_console carries Max-Age → it is a PERSISTENT
    // cookie, so removeSessionCookies() would not touch it. The console is this
    // app's only WebView, so clearing all cookies is safe and unambiguous.
    DisposableEffect(Unit) {
        onDispose {
            CookieManager.getInstance().apply {
                removeAllCookies(null)
                flush()
            }
            // Same reasoning as the cookie: leave nothing of the console behind —
            // and a purged cache cannot go stale against a newer app.js either.
            webViewRef.value?.clearCache(true)
            webViewRef.value?.destroy()
            webViewRef.value = null
        }
    }

    Column(modifier = modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onClose) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Zurück")
            }
            Text("Konto & Modi", style = MaterialTheme.typography.titleLarge)
        }
        AndroidView(
            factory = { ctx ->
                CookieManager.getInstance().setAcceptCookie(true)
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    // Never serve the console from the WebView's own cache. It is
                    // opened fresh via a single-use bootstrap each time, so caching
                    // buys nothing — but a stale index.html paired with a newer
                    // app.js drifts the two apart and the console dies on a null
                    // element (that is what "Cannot set properties of null" was).
                    // The backend already sends no-cache for /app; this makes the
                    // client side match instead of trusting the cache.
                    settings.cacheMode = WebSettings.LOAD_NO_CACHE
                    // Same origin → third-party cookies stay off.
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
                    // Anti-Session-Fixation: den Nonce als sb_boot-Cookie setzen, BEVOR
                    // die Bootstrap-URL lädt. Der Backend-Redeem verlangt Cookie == an
                    // den Code gebundener Nonce; ein Angreifer kann das im Browser des
                    // Opfers nicht setzen.
                    webViewClient = WebViewClient() // keep navigation inside the WebView
                    webViewRef.value = this
                    if (!nonce.isNullOrBlank()) {
                        // setCookie ist asynchron. Erst im Callback navigieren,
                        // sonst kann /console/bootstrap den gebundenen Code vor
                        // dem sb_boot-Cookie erreichen und sicher mit 400 ablehnen.
                        CookieManager.getInstance().setCookie(
                            url,
                            "sb_boot=$nonce; Path=/console; Secure; SameSite=Lax",
                        ) {
                            CookieManager.getInstance().flush()
                            post { loadUrl(url) }
                        }
                    } else {
                        loadUrl(url)
                    }
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
