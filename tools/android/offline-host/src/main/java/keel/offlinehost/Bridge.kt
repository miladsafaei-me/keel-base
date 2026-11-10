package keel.offlinehost

import android.content.Intent
import android.net.Uri
import android.util.Base64
import android.webkit.JavascriptInterface
import androidx.core.content.FileProvider
import java.io.File

/** What the web app may ask of the device, as window.NativeApp. Every call arrives off the main thread. */
class Bridge(private val activity: OfflineWebActivity) {

    @JavascriptInterface
    fun theme(mode: String) = activity.runOnUiThread { activity.applyTheme(mode == "dark") }

    @JavascriptInterface
    fun version(): String =
        activity.packageManager.getPackageInfo(activity.packageName, 0).versionName.orEmpty()

    @JavascriptInterface
    fun entitlement(): String = activity.billing.json()

    @JavascriptInterface
    fun refresh() = activity.runOnUiThread { activity.billing.refresh() }

    @JavascriptInterface
    fun purchase(productId: String) = activity.runOnUiThread { activity.billing.purchase(activity) }

    @JavascriptInterface
    fun restore() = activity.runOnUiThread { activity.billing.refresh() }

    @JavascriptInterface
    fun requestReview() = activity.runOnUiThread { activity.requestReview() }

    @JavascriptInterface
    fun open(url: String) = activity.runOnUiThread { activity.openOutside(Uri.parse(url)) }

    @JavascriptInterface
    fun shareText(title: String, text: String) = activity.runOnUiThread {
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_SUBJECT, title).putExtra(Intent.EXTRA_TEXT, text)
        activity.startActivity(Intent.createChooser(send, title))
    }

    /** A file made by the web app (a PDF report, a JSON export), handed to the share sheet. */
    @JavascriptInterface
    fun shareFile(name: String, mime: String, base64: String) {
        val safe = name.replace(Regex("[^A-Za-z0-9._-]"), "_").take(80)
        val dir = File(activity.cacheDir, "shared").apply { mkdirs() }
        val file = File(dir, safe)
        file.writeBytes(Base64.decode(base64, Base64.DEFAULT))
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", file)
        activity.runOnUiThread {
            val send = Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            activity.startActivity(Intent.createChooser(send, safe))
        }
    }
}
