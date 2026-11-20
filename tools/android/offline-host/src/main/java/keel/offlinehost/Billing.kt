package keel.offlinehost

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams

/**
 * Play Billing for the app's one Pro product: the Android side of [BillingCore], which holds
 * every rule. [productType] is `inapp` (a one-time item, the default) or `subs` (a subscription
 * whose base plans the page buys by id). A blank [productId] means the app sells nothing yet.
 */
class Billing(
    context: Context,
    private val productId: String,
    productType: String,
    onChange: (String) -> Unit,
    onPurchaseResult: (String) -> Unit,
) {
    val subscription = productType.trim().equals("subs", ignoreCase = true)
    private val store = PlayStore(context)
    private val core = BillingCore(store, productId, subscription, PrefsCache(context), onChange, onPurchaseResult)

    init { store.onUpdate = core::onPurchasesUpdated }

    fun json(): String = core.json()
    fun connect() = core.connect()
    fun refresh() = core.refresh()
    fun purchase(activity: Activity, planId: String? = null) = core.purchase(activity, planId)
    fun end() = core.end()
}

/** The entitlement cache in SharedPreferences, the file the one-time path has always used. */
private class PrefsCache(context: Context) : KeyValue {
    private val prefs = context.getSharedPreferences("entitlement", Context.MODE_PRIVATE)
    override fun get(key: String): String? = prefs.getString(key, null)
    override fun put(values: Map<String, String?>) {
        val edit = prefs.edit()
        values.forEach { (k, v) -> edit.putString(k, v) }
        edit.apply()
    }
}

/** [StoreClient] on Play Billing. Purchases and product details become plain [OwnedItem] and [ProductInfo]. */
private class PlayStore(context: Context) : StoreClient {
    var onUpdate: (StoreResult, List<OwnedItem>?) -> Unit = { _, _ -> }

    private val details = mutableMapOf<String, ProductDetails>()

    private val client: BillingClient = BillingClient.newBuilder(context)
        .setListener { result, purchases -> onUpdate(code(result), purchases?.map(::owned)) }
        .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
        .enableAutoServiceReconnection()
        .build()

    override val ready: Boolean get() = client.isReady

    override fun connect(done: (Boolean) -> Unit) {
        client.startConnection(object : BillingClientStateListener {
            override fun onBillingSetupFinished(result: BillingResult) = done(result.responseCode == BillingClient.BillingResponseCode.OK)
            override fun onBillingServiceDisconnected() { /* auto reconnection is on */ }
        })
    }

    override fun queryPurchases(subscription: Boolean, done: (Boolean, List<OwnedItem>) -> Unit) {
        client.queryPurchasesAsync(QueryPurchasesParams.newBuilder().setProductType(type(subscription)).build()) { result, purchases ->
            done(result.responseCode == BillingClient.BillingResponseCode.OK, purchases.map(::owned))
        }
    }

    override fun queryProduct(productId: String, subscription: Boolean, done: (Boolean, ProductInfo?) -> Unit) {
        val product = QueryProductDetailsParams.Product.newBuilder().setProductId(productId).setProductType(type(subscription)).build()
        client.queryProductDetailsAsync(QueryProductDetailsParams.newBuilder().setProductList(listOf(product)).build()) { result, found ->
            if (result.responseCode != BillingClient.BillingResponseCode.OK) { done(false, null); return@queryProductDetailsAsync }
            val d = found.productDetailsList.firstOrNull()
            if (d == null) { done(true, null); return@queryProductDetailsAsync }
            details[productId] = d
            done(true, info(d))
        }
    }

    override fun acknowledge(token: String) {
        client.acknowledgePurchase(AcknowledgePurchaseParams.newBuilder().setPurchaseToken(token).build()) { }
    }

    override fun launch(host: Any, productId: String, offerToken: String?): Boolean {
        val d = details[productId] ?: return false
        val activity = host as? Activity ?: return false
        val item = BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(d)
        if (offerToken != null) item.setOfferToken(offerToken)
        val params = BillingFlowParams.newBuilder().setProductDetailsParamsList(listOf(item.build())).build()
        return client.launchBillingFlow(activity, params).responseCode == BillingClient.BillingResponseCode.OK
    }

    override fun end() = client.endConnection()

    private fun type(subscription: Boolean) = if (subscription) BillingClient.ProductType.SUBS else BillingClient.ProductType.INAPP

    private fun code(result: BillingResult) = when (result.responseCode) {
        BillingClient.BillingResponseCode.OK -> StoreResult.OK
        BillingClient.BillingResponseCode.USER_CANCELED -> StoreResult.CANCELLED
        BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> StoreResult.ALREADY_OWNED
        else -> StoreResult.ERROR
    }

    private fun owned(p: Purchase) = OwnedItem(
        products = p.products,
        purchased = p.purchaseState == Purchase.PurchaseState.PURCHASED,
        pending = p.purchaseState == Purchase.PurchaseState.PENDING,
        acknowledged = p.isAcknowledged,
        token = p.purchaseToken,
        autoRenewing = p.isAutoRenewing,
    )

    /** Base plans only (offers with no offer id); an intro offer added in Play Console is not sold here. */
    private fun info(d: ProductDetails) = ProductInfo(
        oneTimePrice = d.oneTimePurchaseOfferDetails?.formattedPrice,
        plans = d.subscriptionOfferDetails.orEmpty().filter { it.offerId == null }.mapNotNull { offer ->
            val phase = offer.pricingPhases.pricingPhaseList.lastOrNull() ?: return@mapNotNull null
            Plan(offer.basePlanId, phase.formattedPrice, phase.billingPeriod, phase.priceAmountMicros, phase.priceCurrencyCode, offer.offerToken)
        },
    )
}
