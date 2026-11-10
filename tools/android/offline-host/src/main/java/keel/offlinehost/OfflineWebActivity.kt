package keel.offlinehost

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
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
import com.google.android.play.core.review.ReviewManagerFactory
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * The shared host of Rovin Studio's offline apps. An app's MainActivity extends this
 * class and adds nothing; its identity (name, product id, colours, icon) comes from
 * the app's own resources, which override this library's defaults.
 *
 * The one screen: the web app in assets/ served at https://appassets.androidplatform.net/app/
 * by a WebViewAssetLoader. Nothing loads from the network. The activity gives the
 * page what it cannot have on its own: system bar insets, bar icon colours, the
 * Back gesture (offered to the page first), sharing, Play Billing and in-app review.
 */
open class OfflineWebActivity : ComponentActivity() {

    private lateinit var web: WebView
    lateinit var billing: Billing
    private var drawn = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setKeepOnScreenCondition { !drawn }
        applyTheme(systemDark())

        billing = Billing(this, getString(R.string.pro_product_id),
            onChange = { json -> runOnUiThread { js("window.appShell && window.appShell.entitlement($json)") } },
            onPurchaseResult = { json -> runOnUiThread { js("window.appShell && window.appShell.purchaseResult($json)") } })

        WebView.setWebContentsDebuggingEnabled(applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
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
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(web.settings, false)
        }

        val loader = WebViewAssetLoader.Builder()
            .addPathHandler(APP_PATH, WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == WebViewAssetLoader.DEFAULT_DOMAIN && url.path.orEmpty().startsWith(APP_PATH)) return false
                openOutside(url)
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pushInsets()
                drawn = true
            }
        }
        web.addJavascriptInterface(Bridge(this), "NativeApp")

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
                web.evaluateJavascript("window.appShell ? window.appShell.back() : false") { handled ->
                    if (handled != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })

        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            web.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}${APP_PATH}index.html?system=${if (systemDark()) "dark" else "light"}")
        }
        billing.connect()
    }

    override fun onResume() {
        super.onResume()
        // Restore is automatic: every return to the app re-reads purchases.
        if (::billing.isInitialized) billing.refresh()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        js("window.appShell && window.appShell.system('${if (systemDark()) "dark" else "light"}')")
    }

    override fun onDestroy() {
        billing.end()
        web.destroy()
        super.onDestroy()
    }

    private var insets = JSONObject().put("top", 0).put("bottom", 0).put("left", 0).put("right", 0)

    private fun js(code: String) {
        if (::web.isInitialized) web.evaluateJavascript(code, null)
    }

    private fun pushInsets() = js("window.appShell && window.appShell.insets($insets)")

    private fun systemDark() =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    /** Transparent bars; icons light on a dark page and dark on a light one; the window ground matches the page. */
    fun applyTheme(dark: Boolean) {
        val style = if (dark) SystemBarStyle.dark(Color.TRANSPARENT) else SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
        val ground = ContextCompat.getColor(this, if (dark) R.color.surface_dark else R.color.surface_light)
        if (::web.isInitialized) web.setBackgroundColor(ground)
        window.setBackgroundDrawable(ColorDrawable(ground))
    }

    /** The Play in-app review card. Google decides whether it shows; the app asks once. */
    fun requestReview() {
        val manager = ReviewManagerFactory.create(this)
        manager.requestReviewFlow().addOnCompleteListener { task ->
            if (task.isSuccessful) manager.launchReviewFlow(this, task.result)
        }
    }

    fun openOutside(url: Uri) {
        try {
            if (url.scheme == "https") CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(this, url)
            else startActivity(Intent(Intent.ACTION_VIEW, url))
        } catch (_: ActivityNotFoundException) {
            // Nothing on the device opens this link; the tap does nothing.
        }
    }

    companion object {
        const val APP_PATH = "/app/"
    }
}
