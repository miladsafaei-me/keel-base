package keel.offlinehost

/** The answer Play gives to a purchase flow, in our own words so the core never touches Play classes. */
enum class StoreResult { OK, CANCELLED, ALREADY_OWNED, ERROR }

/**
 * The part of Play Billing the core needs. [PlayStore] in Billing.kt is the real one; the unit
 * tests use a fake. Every callback may arrive on any thread; the core does not care.
 */
interface StoreClient {
    val ready: Boolean
    fun connect(done: (ok: Boolean) -> Unit)
    fun queryPurchases(subscription: Boolean, done: (ok: Boolean, items: List<OwnedItem>) -> Unit)
    fun queryProduct(productId: String, subscription: Boolean, done: (ok: Boolean, info: ProductInfo?) -> Unit)
    fun acknowledge(token: String)
    /** Opens Play's purchase sheet; [host] is the Activity. False when Play could not start it. */
    fun launch(host: Any, productId: String, offerToken: String?): Boolean
    fun end()
}

/** The small cache that lets Pro work offline (SharedPreferences in the app, a map in tests). */
interface KeyValue {
    fun get(key: String): String?
    fun put(values: Map<String, String?>)
}

/**
 * Play Billing for one Pro product, a one-time item or a subscription, as plain logic.
 * Purchases are queried on connect and on every resume, acknowledged at once, and the state
 * cached so Pro works offline. Every change goes to [onChange] as entitlement JSON, every
 * purchase flow ends in [onPurchaseResult] (`ok`, `pending`, `owned`, `cancelled`, `error`,
 * `unavailable`). A blank [productId] means the app sells nothing yet: Play is never asked.
 *
 * A reinstall starts with an empty cache, and the first query brings the purchase back, so
 * restore needs no button of its own; the page's restore action simply calls [refresh].
 */
class BillingCore(
    private val store: StoreClient,
    private val productId: String,
    private val subscription: Boolean,
    private val cache: KeyValue,
    private val onChange: (String) -> Unit,
    private val onPurchaseResult: (String) -> Unit,
) {
    var state: ProState = runCatching { ProState.valueOf(cache.get("state") ?: "UNKNOWN") }.getOrDefault(ProState.UNKNOWN)
        private set
    private var price: String? = cache.get("price")
    private var renewing: Boolean = cache.get("renewing") == "1"
    /** This install has seen an active Pro at least once: a later NONE is a lapse, not a stranger. */
    private var ever: Boolean = cache.get("ever") == "1" || state == ProState.ACTIVE
    private var info: ProductInfo? = null

    fun entitlement() = Entitlement(
        state = state,
        price = if (subscription) null else price,
        subscription = subscription,
        renewing = subscription && state == ProState.ACTIVE && renewing,
        lapsed = subscription && state == ProState.NONE && ever,
        plans = if (subscription) info?.plans.orEmpty() else emptyList(),
    )

    fun json(): String = EntitlementRules.toJson(entitlement())

    fun connect() {
        if (productId.isBlank()) { set(ProState.NONE); return }
        if (store.ready) { refresh(); return }
        store.connect { ok -> if (ok) refresh() else set(EntitlementRules.onQueryFailed(state)) }
    }

    fun refresh() {
        if (productId.isBlank()) return
        if (!store.ready) { connect(); return }
        store.queryPurchases(subscription) { ok, items ->
            if (ok) apply(items) else set(EntitlementRules.onQueryFailed(state))
        }
        store.queryProduct(productId, subscription) { ok, found ->
            if (ok && found != null) {
                info = found
                if (!subscription) found.oneTimePrice?.let { price = it; save() }
                onChange(json())
            }
        }
    }

    /**
     * Starts a purchase. A subscription needs [planId] (the base plan id, `monthly` or `yearly`);
     * a one-time product ignores it. Before Play has priced the product, or for an unknown plan,
     * the page hears `unavailable` and a new query starts.
     */
    fun purchase(host: Any, planId: String?) {
        val found = info
        if (productId.isBlank() || found == null) { result("unavailable"); refresh(); return }
        val token = if (subscription) found.plans.firstOrNull { it.id == planId }?.offerToken else null
        if (subscription && token == null) { result("unavailable"); return }
        if (!store.launch(host, productId, token)) result("error")
    }

    /**
     * Play's purchase listener. On OK the list holds only the purchases this flow changed, so it
     * may raise the state but never lower it; a full query follows and settles it.
     */
    fun onPurchasesUpdated(code: StoreResult, items: List<OwnedItem>?) {
        when (code) {
            StoreResult.OK -> {
                val list = items.orEmpty()
                acknowledge(list)
                val s = EntitlementRules.stateOf(list, productId)
                if (s == ProState.ACTIVE || (s == ProState.PENDING && state != ProState.ACTIVE)) {
                    if (s == ProState.ACTIVE) { ever = true; renewing = EntitlementRules.renewing(list, productId) }
                    set(s)
                }
                result(if (s == ProState.PENDING) "pending" else "ok")
                refresh()
            }
            StoreResult.ALREADY_OWNED -> { refresh(); result("owned") }
            StoreResult.CANCELLED -> result("cancelled")
            StoreResult.ERROR -> result("error")
        }
    }

    fun end() = store.end()

    private fun apply(items: List<OwnedItem>) {
        acknowledge(items)
        val s = EntitlementRules.stateOf(items, productId)
        renewing = EntitlementRules.renewing(items, productId)
        if (s == ProState.ACTIVE) ever = true
        set(s)
    }

    private fun acknowledge(items: List<OwnedItem>) {
        for (token in EntitlementRules.toAcknowledge(items, productId)) store.acknowledge(token)
    }

    private fun result(r: String) = onPurchaseResult("{\"result\":\"$r\"}")

    private fun set(s: ProState) {
        state = s
        save()
        onChange(json())
    }

    private fun save() {
        cache.put(mapOf(
            "state" to state.name,
            "price" to price,
            "renewing" to if (renewing) "1" else "0",
            "ever" to if (ever) "1" else "0",
        ))
    }
}
