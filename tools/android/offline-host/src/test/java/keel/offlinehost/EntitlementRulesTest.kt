package keel.offlinehost

import org.junit.Assert.assertEquals
import org.junit.Test

/** Every path of the entitlement rules, with fake purchases in place of Play Billing. */
class EntitlementRulesTest {
    private val pro = "pro_lifetime"
    private fun item(purchased: Boolean = false, pending: Boolean = false, ack: Boolean = false, product: String = pro, token: String = "t") =
        OwnedItem(listOf(product), purchased, pending, ack, token)

    @Test fun noPurchasesIsNone() = assertEquals(ProState.NONE, EntitlementRules.stateOf(emptyList(), pro))
    @Test fun purchasedIsActive() = assertEquals(ProState.ACTIVE, EntitlementRules.stateOf(listOf(item(purchased = true)), pro))
    @Test fun pendingIsPending() = assertEquals(ProState.PENDING, EntitlementRules.stateOf(listOf(item(pending = true)), pro))
    @Test fun purchasedWinsOverPending() = assertEquals(ProState.ACTIVE, EntitlementRules.stateOf(listOf(item(pending = true), item(purchased = true)), pro))
    @Test fun otherProductIsNone() = assertEquals(ProState.NONE, EntitlementRules.stateOf(listOf(item(purchased = true, product = "other")), pro))

    @Test fun unacknowledgedPurchaseIsAcknowledged() =
        assertEquals(listOf("a"), EntitlementRules.toAcknowledge(listOf(item(purchased = true, token = "a"), item(purchased = true, ack = true, token = "b"), item(pending = true, token = "c")), pro))

    @Test fun failedQueryKeepsCachedPro() = assertEquals(ProState.ACTIVE, EntitlementRules.onQueryFailed(ProState.ACTIVE))
    @Test fun failedQueryWithNoCacheIsNone() = assertEquals(ProState.NONE, EntitlementRules.onQueryFailed(ProState.UNKNOWN))

    @Test fun jsonCarriesStateAndPrice() = assertEquals("""{"state":"active","price":"$14.99"}""", EntitlementRules.toJson(ProState.ACTIVE, "$14.99"))
}
