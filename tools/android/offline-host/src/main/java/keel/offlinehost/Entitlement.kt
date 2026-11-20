package keel.offlinehost

/**
 * What the app knows about the Pro purchase, independent of Play Billing so the
 * rules can be unit-tested with plain values.
 *
 *  - ACTIVE: a purchased Pro item exists (acknowledged or not; acknowledging is our job).
 *    For a subscription this covers a running plan, the grace period after a failed renewal,
 *    and a cancelled plan that is paid until its end date: Play keeps returning all three.
 *  - PENDING: the only Pro item is waiting for payment (cash, bank transfer).
 *  - NONE: no Pro item. For a subscription this covers expiry, account hold and pause, which
 *    Play stops returning; [Entitlement.lapsed] tells the page this user had Pro before.
 *  - UNKNOWN: Play has not answered yet; the cached state stands in, so Pro works offline.
 */
enum class ProState(val wire: String) { UNKNOWN("unknown"), NONE("none"), PENDING("pending"), ACTIVE("active") }

/** One purchase as the logic needs it: which products, its state, whether it is acknowledged, whether it renews. */
data class OwnedItem(
    val products: List<String>,
    val purchased: Boolean,
    val pending: Boolean,
    val acknowledged: Boolean,
    val token: String,
    val autoRenewing: Boolean = false,
)

/**
 * One base plan of the subscription as Play prices it for this user: the plan id from Play
 * Console (`monthly`, `yearly`), the localized price, the ISO 8601 period (`P1M`, `P1Y`), the
 * price in micros and its currency (so the page can compare plans), and the token that buys it.
 */
data class Plan(val id: String, val price: String, val period: String, val micros: Long, val currency: String, val offerToken: String)

/** What Play says about the product itself: a one-time price, or the subscription's base plans. */
data class ProductInfo(val oneTimePrice: String?, val plans: List<Plan>)

/**
 * Everything the page is told. A one-time product carries [price]; a subscription carries
 * [plans] (empty until Play answers, never cached, so an offline page shows no stale price),
 * [renewing] (false once the user cancelled a plan that is still paid) and [lapsed] (no Pro now,
 * but this install saw Pro before: expired, on hold or paused).
 */
data class Entitlement(
    val state: ProState,
    val price: String? = null,
    val subscription: Boolean = false,
    val renewing: Boolean = false,
    val lapsed: Boolean = false,
    val plans: List<Plan> = emptyList(),
)

object EntitlementRules {
    /** The state a list of owned items gives for the Pro product. */
    fun stateOf(items: List<OwnedItem>, productId: String): ProState {
        val pro = items.filter { productId in it.products }
        return when {
            pro.any { it.purchased } -> ProState.ACTIVE
            pro.any { it.pending } -> ProState.PENDING
            else -> ProState.NONE
        }
    }

    /** True when a purchased Pro item will renew; false once the user cancelled it (paid until its end). */
    fun renewing(items: List<OwnedItem>, productId: String): Boolean =
        items.any { productId in it.products && it.purchased && it.autoRenewing }

    /** Tokens to acknowledge: purchased Pro items not yet acknowledged (Play refunds them after three days otherwise). */
    fun toAcknowledge(items: List<OwnedItem>, productId: String): List<String> =
        items.filter { productId in it.products && it.purchased && !it.acknowledged }.map { it.token }

    /**
     * The state to show when a query fails: the cached one, never a downgrade. A
     * buyer who opens the app offline keeps Pro.
     */
    fun onQueryFailed(cached: ProState): ProState = if (cached == ProState.UNKNOWN) ProState.NONE else cached

    /** Written by hand, not with org.json, so the rules run in plain JVM unit tests. */
    fun toJson(state: ProState, price: String?): String {
        val esc = price?.let(::esc)
        return if (esc == null) "{\"state\":\"${state.wire}\"}" else "{\"state\":\"${state.wire}\",\"price\":\"$esc\"}"
    }

    /** The page's view of [e]. A one-time product keeps exactly the old shape of [toJson]. */
    fun toJson(e: Entitlement): String {
        if (!e.subscription) return toJson(e.state, e.price)
        val plans = e.plans.joinToString(",") {
            "{\"id\":\"${esc(it.id)}\",\"price\":\"${esc(it.price)}\",\"period\":\"${esc(it.period)}\",\"micros\":${it.micros},\"currency\":\"${esc(it.currency)}\"}"
        }
        return "{\"state\":\"${e.state.wire}\",\"subscription\":true,\"renewing\":${e.renewing},\"lapsed\":${e.lapsed},\"plans\":[$plans]}"
    }

    private fun esc(s: String) = s.replace("\\", "\\\\").replace("\"", "\\\"")
}
