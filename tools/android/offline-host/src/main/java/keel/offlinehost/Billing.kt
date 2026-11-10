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
 * Play Billing for the one-time Pro product. Purchases are queried on connect and
 * on every resume, acknowledged at once, and the result cached so Pro works
 * offline. Every change is reported through [onChange] as entitlement JSON.
 * A blank [productId] means the app sells nothing yet: Play is never asked.
 */
class Billing(context: Context, private val productId: String, private val onChange: (String) -> Unit, private val onPurchaseResult: (String) -> Unit) {

    private val prefs = context.getSharedPreferences("entitlement", Context.MODE_PRIVATE)
    private var details: ProductDetails? = null

    var state: ProState = runCatching { ProState.valueOf(prefs.getString("state", "UNKNOWN")!!) }.getOrDefault(ProState.UNKNOWN)
        private set
    var price: String? = prefs.getString("price", null)
        private set

    private val client: BillingClient = BillingClient.newBuilder(context)
        .setListener { result, purchases -> handle(result, purchases) }
        .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
        .enableAutoServiceReconnection()
        .build()

    fun json(): String = EntitlementRules.toJson(state, price)

    fun connect() {
        if (productId.isBlank()) { set(ProState.NONE); return }
        if (client.isReady) { refresh(); return }
        client.startConnection(object : BillingClientStateListener {
            override fun onBillingSetupFinished(result: BillingResult) {
                if (result.responseCode == BillingClient.BillingResponseCode.OK) refresh() else set(EntitlementRules.onQueryFailed(state))
            }
            override fun onBillingServiceDisconnected() { /* auto reconnection is on */ }
        })
    }

    fun refresh() {
        if (productId.isBlank()) return
        if (!client.isReady) { connect(); return }
        client.queryPurchasesAsync(QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.INAPP).build()) { result, purchases ->
            if (result.responseCode == BillingClient.BillingResponseCode.OK) apply(purchases) else set(EntitlementRules.onQueryFailed(state))
        }
        val product = QueryProductDetailsParams.Product.newBuilder().setProductId(productId).setProductType(BillingClient.ProductType.INAPP).build()
        client.queryProductDetailsAsync(QueryProductDetailsParams.newBuilder().setProductList(listOf(product)).build()) { result, found ->
            if (result.responseCode == BillingClient.BillingResponseCode.OK) {
                details = found.productDetailsList.firstOrNull()
                details?.oneTimePurchaseOfferDetails?.formattedPrice?.let { price = it; save() }
                onChange(json())
            }
        }
    }

    fun purchase(activity: Activity) {
        val d = details
        if (d == null) { onPurchaseResult("""{"result":"unavailable"}"""); refresh(); return }
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(d).build()))
            .build()
        client.launchBillingFlow(activity, params)
    }

    private fun handle(result: BillingResult, purchases: List<Purchase>?) {
        when (result.responseCode) {
            BillingClient.BillingResponseCode.OK -> { apply(purchases.orEmpty()); onPurchaseResult("""{"result":"ok"}""") }
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> { refresh(); onPurchaseResult("""{"result":"owned"}""") }
            BillingClient.BillingResponseCode.USER_CANCELED -> onPurchaseResult("""{"result":"cancelled"}""")
            else -> onPurchaseResult("""{"result":"error"}""")
        }
    }

    private fun apply(purchases: List<Purchase>) {
        val items = purchases.map {
            OwnedItem(it.products, it.purchaseState == Purchase.PurchaseState.PURCHASED, it.purchaseState == Purchase.PurchaseState.PENDING, it.isAcknowledged, it.purchaseToken)
        }
        for (token in EntitlementRules.toAcknowledge(items, productId)) {
            client.acknowledgePurchase(AcknowledgePurchaseParams.newBuilder().setPurchaseToken(token).build()) { }
        }
        set(EntitlementRules.stateOf(items, productId))
    }

    private fun set(s: ProState) {
        state = s
        save()
        onChange(json())
    }

    private fun save() {
        prefs.edit().putString("state", state.name).putString("price", price).apply()
    }

    fun end() { client.endConnection() }
}
