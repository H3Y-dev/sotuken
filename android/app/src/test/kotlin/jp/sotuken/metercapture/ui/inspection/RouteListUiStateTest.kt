package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.route.*
import org.junit.Assert.*
import org.junit.Test

class RouteListUiStateTest {
    @Test fun savedRowsShowCountTimeAndSourceWithoutNetwork() {
        val route = requireNotNull(parseRouteJson(PC_ROUTE_JSON))
        val state = buildRouteListUiState(listOf(SavedRoute(route, "now", "qr")), null, false, null, null)
        assertEquals("巡回", state.saved.single().name)
        assertEquals("1機器 ・ ${route.updatedAt} ・ QR", state.saved.single().detail)
        assertNull(state.remote)
    }
    @Test fun passesLoadingErrorAndConfirmation() {
        val route = requireNotNull(parseRouteJson(PC_ROUTE_JSON))
        val remote = listOf(RouteSummary(route.routeId, route.name, 1, route.updatedAt))
        val state = buildRouteListUiState(emptyList(), remote, true, "PCに接続できません", route)
        assertTrue(state.loading); assertEquals(remote, state.remote); assertEquals(route, state.confirm); assertEquals("PCに接続できません", state.error)
    }
}
