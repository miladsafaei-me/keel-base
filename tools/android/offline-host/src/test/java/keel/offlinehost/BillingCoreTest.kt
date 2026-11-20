package keel.offlinehost

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * BillingCore against a fake Play: every state a subscription can be in, the purchase flow,
 * restore on start, resume and reinstall, offline use, and the one-time path the electrical
 * calculator still sells.
 */
class BillingCoreTest {

    /** A Play that answers at once with whatever the test put in it. */
    private class FakeStore : StoreClient {
        var connects = true
        var online = true
        var items = listOf<OwnedItem>()
        var info: ProductInfo? = null
        var launchOk = true
        val acknowledged = mutableListOf<String>()
        val launched = mutableListOf<String?>()
        var connected = false
        override val ready get() = connected
        override fun connect(done: (Boolean) -> Unit) { connected = connects; done(connects) }
        override fun queryPurchases(subscription: Boolean, done: (Boolean, List<OwnedItem>) -> Unit) = done(online, if (online) items else emptyList())
        override fun queryProduct(productId: String, subscription: Boolean, done: (Boolean, ProductInfo?) -> Unit) = done(online, if (online) info else null)
        override fun acknowledge(token: String) { acknowledged += token }
        override fun launch(host: Any, productId: String, offerToken: String?): Boolean { launched += offerToken; return launchOk }
        override fun end() { connected = false }
    }

    private class MapCache(val map: MutableMap<String, String?> = mutableMapOf()) : KeyValue {
        override fun get(key: String) = map[key]
        override fun put(values: Map<String, String?>) { map.putAll(values) }
    }

    private val monthly = Plan("monthly", "$4.00", "P1M", 4_000_000, "USD", "tok-m")
    private val yearly = Plan("yearly", "$29.00", "P1Y", 29_000_000, "USD", "tok-y")
    private val subsInfo = ProductInfo(null, listOf(monthly, yearly))

    private fun sub(purchased: Boolean = true, pending: Boolean = false, ack: Boolean = true, renewing: Boolean = true, token: String = "s") =
        OwnedItem(listOf("pro"), purchased, pending, ack, token, renewing)

    private class Rig(val store: FakeStore, val cache: MapCache, subscription: Boolean, product: String) {
        val changes = mutableListOf<String>()
        val results = mutableListOf<String>()
        val core = BillingCore(store, product, subscription, cache, { changes += it }, { results += it })
    }

    private fun rig(subscription: Boolean = true, product: String = "pro", cache: MapCache = MapCache(), setup: FakeStore.() -> Unit = {}) =
        Rig(FakeStore().apply { info = if (subscription) subsInfo else ProductInfo("$14.99", emptyList()) }.apply(setup), cache, subscription, product)

    // Subscription states

    @Test fun activeRenewingSubscription() {
        val r = rig { items = listOf(sub()) }
        r.core.connect()
        val e = r.core.entitlement()
        assertEquals(ProState.ACTIVE, e.state)
        assertTrue(e.renewing)
        assertFalse(e.lapsed)
        assertEquals(listOf("monthly", "yearly"), e.plans.map { it.id })
    }

    @Test fun gracePeriodKeepsPro() {
        // Play keeps returning a purchased, renewing subscription while it retries a failed payment.
        val r = rig { items = listOf(sub(renewing = true)) }
        r.core.connect()
        assertEquals(ProState.ACTIVE, r.core.state)
    }

    @Test fun cancelledButPaidKeepsProAndSaysItWillNotRenew() {
        val r = rig { items = listOf(sub(renewing = false)) }
        r.core.connect()
        val e = r.core.entitlement()
        assertEquals(ProState.ACTIVE, e.state)
        assertFalse(e.renewing)
    }

    @Test fun accountHoldEndsProAndShowsALapse() {
        val r = rig { items = listOf(sub()) }
        r.core.connect()
        r.store.items = emptyList() // on hold: Play stops returning the purchase
        r.core.refresh()
        val e = r.core.entitlement()
        assertEquals(ProState.NONE, e.state)
        assertTrue(e.lapsed)
    }

    @Test fun neverSubscribedIsNoneWithoutLapse() {
        val r = rig()
        r.core.connect()
        assertEquals(ProState.NONE, r.core.state)
        assertFalse(r.core.entitlement().lapsed)
    }

    @Test fun pendingPaymentIsPendingThenActive() {
        val r = rig { items = listOf(sub(purchased = false, pending = true, ack = false)) }
        r.core.connect()
        assertEquals(ProState.PENDING, r.core.state)
        assertTrue(r.store.acknowledged.isEmpty())
        r.store.items = listOf(sub(ack = false, token = "paid"))
        r.core.refresh()
        assertEquals(ProState.ACTIVE, r.core.state)
        assertEquals(listOf("paid"), r.store.acknowledged)
    }

    @Test fun unacknowledgedSubscriptionIsAcknowledged() {
        val r = rig { items = listOf(sub(ack = false, token = "a")) }
        r.core.connect()
        assertEquals(listOf("a"), r.store.acknowledged)
    }

    // Restore

    @Test fun restoreOnStartAfterReinstall() {
        // A reinstall has an empty cache; the first query brings the subscription back.
        val r = rig(cache = MapCache()) { items = listOf(sub()) }
        assertEquals(ProState.UNKNOWN, r.core.state)
        r.core.connect()
        assertEquals(ProState.ACTIVE, r.core.state)
    }

    @Test fun restoreOnResumePicksUpAPurchaseMadeElsewhere() {
        val r = rig()
        r.core.connect()
        assertEquals(ProState.NONE, r.core.state)
        r.store.items = listOf(sub()) // bought on another phone with the same account
        r.core.refresh() // the host calls refresh on every resume and from the page's restore action
        assertEquals(ProState.ACTIVE, r.core.state)
    }

    // Offline

    @Test fun offlineKeepsCachedPro() {
        val cache = MapCache()
        rig(cache = cache) { items = listOf(sub(renewing = false)) }.core.connect()
        val r = rig(cache = cache) { online = false }
        r.core.connect()
        val e = r.core.entitlement()
        assertEquals(ProState.ACTIVE, e.state)
        assertFalse(e.renewing)
        assertTrue(e.plans.isEmpty()) // prices are never shown from the cache
    }

    @Test fun noConnectionWithNoCacheIsNone() {
        val r = rig { connects = false }
        r.core.connect()
        assertEquals(ProState.NONE, r.core.state)
    }

    @Test fun cachedLapseSurvivesARestartOffline() {
        val cache = MapCache()
        val first = rig(cache = cache) { items = listOf(sub()) }
        first.core.connect()
        first.store.items = emptyList()
        first.core.refresh()
        val r = rig(cache = cache) { online = false }
        r.core.connect()
        assertTrue(r.core.entitlement().lapsed)
    }

    // Purchase flow

    @Test fun purchaseLaunchesThePlansOfferToken() {
        val r = rig()
        r.core.connect()
        r.core.purchase(Any(), "yearly")
        assertEquals(listOf<String?>("tok-y"), r.store.launched)
    }

    @Test fun unknownPlanIsUnavailable() {
        val r = rig()
        r.core.connect()
        r.core.purchase(Any(), "weekly")
        assertTrue(r.store.launched.isEmpty())
        assertEquals("""{"result":"unavailable"}""", r.results.last())
    }

    @Test fun purchaseBeforePricesIsUnavailable() {
        val r = rig { online = false }
        r.core.connect()
        r.core.purchase(Any(), "monthly")
        assertEquals("""{"result":"unavailable"}""", r.results.last())
    }

    @Test fun failedLaunchIsAnError() {
        val r = rig { launchOk = false }
        r.core.connect()
        r.core.purchase(Any(), "monthly")
        assertEquals("""{"result":"error"}""", r.results.last())
    }

    @Test fun successfulPurchaseActivatesAndAcknowledges() {
        val r = rig()
        r.core.connect()
        r.store.items = listOf(sub(ack = false, token = "new"))
        r.core.onPurchasesUpdated(StoreResult.OK, listOf(sub(ack = false, token = "new")))
        assertEquals(ProState.ACTIVE, r.core.state)
        assertTrue("new" in r.store.acknowledged)
        assertEquals("""{"result":"ok"}""", r.results.last())
    }

    @Test fun pendingPurchaseResultSaysPending() {
        val r = rig()
        r.core.connect()
        val p = sub(purchased = false, pending = true, ack = false)
        r.store.items = listOf(p)
        r.core.onPurchasesUpdated(StoreResult.OK, listOf(p))
        assertEquals(ProState.PENDING, r.core.state)
        assertEquals("""{"result":"pending"}""", r.results.last())
    }

    @Test fun purchaseUpdateWithoutProNeverDowngrades() {
        val r = rig { items = listOf(sub()) }
        r.core.connect()
        r.core.onPurchasesUpdated(StoreResult.OK, listOf(OwnedItem(listOf("other"), true, false, true, "o")))
        assertEquals(ProState.ACTIVE, r.core.state)
    }

    @Test fun cancelledFlowChangesNothing() {
        val r = rig()
        r.core.connect()
        r.core.onPurchasesUpdated(StoreResult.CANCELLED, null)
        assertEquals(ProState.NONE, r.core.state)
        assertEquals("""{"result":"cancelled"}""", r.results.last())
    }

    @Test fun alreadyOwnedRestores() {
        val r = rig()
        r.core.connect()
        r.store.items = listOf(sub())
        r.core.onPurchasesUpdated(StoreResult.ALREADY_OWNED, null)
        assertEquals(ProState.ACTIVE, r.core.state)
        assertEquals("""{"result":"owned"}""", r.results.last())
    }

    @Test fun subscriptionJsonCarriesPlansAndFlags() {
        val r = rig { items = listOf(sub(renewing = false)) }
        r.core.connect()
        assertEquals(
            """{"state":"active","subscription":true,"renewing":false,"lapsed":false,"plans":[""" +
                """{"id":"monthly","price":"$4.00","period":"P1M","micros":4000000,"currency":"USD"},""" +
                """{"id":"yearly","price":"$29.00","period":"P1Y","micros":29000000,"currency":"USD"}]}""",
            r.core.json(),
        )
    }

    // The one-time path (electrical calculator) and an app that sells nothing

    @Test fun oneTimeProductKeepsItsOldJson() {
        val r = rig(subscription = false, product = "pro_lifetime") {
            items = listOf(OwnedItem(listOf("pro_lifetime"), true, false, false, "l"))
        }
        r.core.connect()
        assertEquals("""{"state":"active","price":"$14.99"}""", r.core.json())
        assertEquals(listOf("l"), r.store.acknowledged)
    }

    @Test fun oneTimePurchaseLaunchesWithoutAToken() {
        val r = rig(subscription = false, product = "pro_lifetime")
        r.core.connect()
        r.core.purchase(Any(), null)
        assertEquals(listOf<String?>(null), r.store.launched)
    }

    @Test fun blankProductSellsNothing() {
        val r = rig(product = "")
        r.core.connect()
        assertEquals(ProState.NONE, r.core.state)
        assertFalse(r.store.connected)
    }
}
