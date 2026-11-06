package jp.sotuken.metercapture.route

import org.junit.Assert.*
import org.junit.Test

// manager.routes.route_qr_payload(get_route(...)) と同じキー・UTF-8・区切り。
internal const val PC_ROUTE_JSON = """{"v":1,"route_id":"R-20261106093000-a1b2","name":"巡回","devices":[{"id":"A","name":"計器"}],"updated_at":"2026-11-06T00:30:00.000000+00:00"}"""

class RouteQrTest {
    @Test fun parsesPrefixedRoute() { assertEquals("巡回", (parseRouteQr("SOTUKEN-ROUTE:$PC_ROUTE_JSON") as RouteQrResult.Ok).route.name) }
    @Test fun rejectsMissingPrefix() { assertEquals("ルートのQRではありません", (parseRouteQr(PC_ROUTE_JSON) as RouteQrResult.Error).message) }
    @Test fun rejectsDeviceQrAndPairingQr() { listOf("SOTUKEN-DEVICE:{}", "SOTUKEN-PAIR:{}").forEach { assertTrue(parseRouteQr(it) is RouteQrResult.Error) } }
    @Test fun rejectsOver2048Bytes() { assertTrue(parseRouteQr("SOTUKEN-ROUTE:" + "あ".repeat(700)) is RouteQrResult.Error) }
    @Test fun rejectsBrokenJson() { assertTrue(parseRouteQr("SOTUKEN-ROUTE:{") is RouteQrResult.Error) }
    @Test fun acceptsExactly2048Bytes() {
        val payload = "SOTUKEN-ROUTE:$PC_ROUTE_JSON"
        assertTrue(parseRouteQr(payload + " ".repeat(2048 - payload.toByteArray(Charsets.UTF_8).size)) is RouteQrResult.Ok)
    }
}
