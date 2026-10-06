package keel.signalapp

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.browser.customtabs.CustomTabColorSchemeParams
import androidx.browser.customtabs.CustomTabsIntent
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * The one screen of a signal app: the site's own app, bundled in assets/ and
 * served at https://<site>/app/ by a WebViewAssetLoader, so its relative
 * requests (/s-api/...) reach the live site as same-origin calls and need no
 * CORS. Everything visible is drawn by the web shell (assets/index.html); this
 * activity only hosts it and gives it what a page cannot have on its own:
 *
 *   - the system bar and keyboard insets, as CSS pixels (window.signalShell.insets)
 *   - the status and navigation bar icon colour, set from the shell's theme
 *   - the system Back gesture, offered to the shell first
 *   - every link off the app opened outside it, in a Custom Tab or its own app
 */
class MainActivity : ComponentActivity() {

    private lateinit var web: WebView
    private lateinit var host: String
    private var drawn = false
    private var insets = JSONObject().put("top", 0).put("bottom", 0).put("left", 0).put("right", 0)

    private val appRoot get() = "https://$host$APP_PATH"

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setKeepOnScreenCondition { !drawn }
        host = getString(R.string.site_host)
        applyBars(systemDark())

        // A debug build can be inspected from chrome://inspect; a release build cannot.
        WebView.setWebContentsDebuggingEnabled((applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0)
        web = WebView(this)
        web.setBackgroundColor(ContextCompat.getColor(this, R.color.surface))
        setContentView(web)

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)
            setSupportZoom(false)
            builtInZoomControls = false
            textZoom = 100
            userAgentString = "$userAgentString ${getString(R.string.app_name).replace(' ', '-')}-Android/${versionName()}"
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(web.settings, false)
        }

        val loader = WebViewAssetLoader.Builder()
            .setDomain(host)
            .addPathHandler(APP_PATH, WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == host && url.path.orEmpty().startsWith(APP_PATH)) return false
                openOutside(url)
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pushInsets()
                drawn = true
            }
        }
        web.addJavascriptInterface(Bridge(), "SignalAndroid")

        ViewCompat.setOnApplyWindowInsetsListener(web) { _, windowInsets ->
            val bars = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = windowInsets.getInsets(WindowInsetsCompat.Type.ime())
            val d = resources.displayMetrics.density
            insets = JSONObject()
                .put("top", (bars.top / d).roundToInt())
                .put("bottom", (max(bars.bottom, ime.bottom) / d).roundToInt())
                .put("left", (bars.left / d).roundToInt())
                .put("right", (bars.right / d).roundToInt())
                .put("keyboard", ime.bottom > bars.bottom)
            pushInsets()
            WindowInsetsCompat.CONSUMED
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("window.signalShell ? window.signalShell.back() : false") { handled ->
                    if (handled != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })

        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            web.loadUrl("${appRoot}index.html?system=${if (systemDark()) "dark" else "light"}")
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        val dark = systemDark()
        web.evaluateJavascript("window.signalShell && window.signalShell.system('${if (dark) "dark" else "light"}')", null)
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }

    private fun systemDark() =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    private fun versionName(): String =
        packageManager.getPackageInfo(packageName, 0).versionName ?: ""

    /** Transparent bars; their icons light on a dark shell and dark on a light one. */
    private fun applyBars(dark: Boolean) {
        val style = if (dark) SystemBarStyle.dark(Color.TRANSPARENT) else SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }

    private fun pushInsets() {
        if (!::web.isInitialized) return
        web.evaluateJavascript("window.signalShell && window.signalShell.insets($insets)", null)
    }

    private fun openOutside(url: Uri) {
        try {
            if (url.scheme == "https" || url.scheme == "http") {
                val dark = isDarkShell
                val bar = ContextCompat.getColor(this, if (dark) R.color.surface_dark else R.color.surface_light)
                CustomTabsIntent.Builder()
                    .setShowTitle(true)
                    .setColorScheme(if (dark) CustomTabsIntent.COLOR_SCHEME_DARK else CustomTabsIntent.COLOR_SCHEME_LIGHT)
                    .setDefaultColorSchemeParams(CustomTabColorSchemeParams.Builder().setToolbarColor(bar).build())
                    .build()
                    .launchUrl(this, url)
            } else {
                startActivity(Intent(Intent.ACTION_VIEW, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        } catch (_: ActivityNotFoundException) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, url))
            } catch (_: ActivityNotFoundException) {
                // No app on the device handles this link; the tap does nothing.
            }
        }
    }

    private var isDarkShell = false

    /** What the web shell may ask of the device. Every call arrives off the main thread. */
    inner class Bridge {
        @JavascriptInterface
        fun theme(mode: String) {
            runOnUiThread {
                isDarkShell = mode == "dark"
                applyBars(isDarkShell)
            }
        }

        @JavascriptInterface
        fun open(url: String) {
            runOnUiThread { openOutside(Uri.parse(url)) }
        }

        @JavascriptInterface
        fun version(): String = versionName()
    }

    private companion object {
        const val APP_PATH = "/app/"
    }
}
