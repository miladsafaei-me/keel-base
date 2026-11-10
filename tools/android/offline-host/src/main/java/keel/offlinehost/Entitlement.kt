package keel.offlinehost

/**
 * What the app knows about the Pro purchase, independent of Play Billing so the
 * rules can be unit-tested with plain values.
 *
 *  - ACTIVE: a purchased Pro item exists (acknowledged or not; acknowledging is our job).
 *  - PENDING: the only Pro item is waiting for payment (cash, bank transfer).
 *  - NONE: no Pro item.
 *  - UNKNOWN: Play has not answered yet; the cached state stands in, so Pro works offline.
 */
enum class ProState(val wire: String) { UNKNOWN("unknown"), NONE("none"), PENDING("pending"), ACTIVE("active") }

/** One purchase as the logic needs it: which products, its state, whether it is acknowledged. */
data class OwnedItem(val products: List<String>, val purchased: Boolean, val pending: Boolean, val acknowledged: Boolean, val token: String)

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
        val esc = price?.replace("\\", "\\\\")?.replace("\"", "\\\"")
        return if (esc == null) "{\"state\":\"${state.wire}\"}" else "{\"state\":\"${state.wire}\",\"price\":\"$esc\"}"
    }
}
