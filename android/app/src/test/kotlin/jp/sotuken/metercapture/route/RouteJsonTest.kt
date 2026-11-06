package jp.sotuken.metercapture.route

import jp.sotuken.metercapture.inspection.RouteDevice
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class RouteJsonTest {
    private val route = RouteDoc("route-1", "第1工場", listOf(RouteDevice("A-1", "圧力計")), "2026-11-06")
    private fun replacing(key: String, value: JsonElement) = JsonObject(Json.parseToJsonElement(route.toJson()).jsonObject + (key to value)).toString()
    @Test fun parsesValidRoute() = assertEquals(route, parseRouteJson(route.toJson()))
    @Test fun rejectsVersionOtherThanOne() { listOf(JsonPrimitive(2), JsonPrimitive("1"), JsonPrimitive(true)).forEach { assertNull(parseRouteJson(replacing("v", it))) } }
    @Test fun rejectsBadRouteId() { listOf("", "../a", "a".repeat(65)).forEach { assertNull(parseRouteJson(replacing("route_id", JsonPrimitive(it)))) } }
    @Test fun rejectsEmptyOrTooManyDevices() { assertNull(parseRouteJson(route.copy(devices = emptyList()).toJson())); assertNull(parseRouteJson(route.copy(devices = (1..201).map { RouteDevice("A-$it", "機器") }).toJson())); assertNotNull(parseRouteJson(route.copy(devices = (1..200).map { RouteDevice("A-$it", "機器") }).toJson())) }
    @Test fun rejectsDuplicateDeviceIds() = assertNull(parseRouteJson(route.copy(devices = route.devices + route.devices).toJson()))
    @Test fun rejectsInvalidDeviceIdOrName() { listOf(RouteDevice("bad/id", "機器"), RouteDevice("A-1", ""), RouteDevice("A-1", "a\nb"), RouteDevice("a".repeat(33), "機器"), RouteDevice("A-1", "a".repeat(65))).forEach { assertNull(parseRouteJson(route.copy(devices = listOf(it)).toJson())) }; assertNull(parseRouteJson(route.copy(name = "", updatedAt = "").toJson())) }
    @Test fun ignoresUnknownKeys() = assertEquals(route, parseRouteJson(replacing("future", JsonPrimitive(true))))
    @Test fun toJsonRoundTrips() { assertEquals(route, parseRouteJson(route.toJson())); assertNull(parseRouteJson("broken")) }
}
