package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.device.DeviceQr
import jp.sotuken.metercapture.inspection.RouteDevice
import jp.sotuken.metercapture.inspection.photo
import org.junit.Assert.*
import org.junit.Test

class CaptureTargetTest {
    private val route = listOf(RouteDevice("A-1", "圧力計"), RouteDevice("A-2", "温度計"))
    @Test fun qrTargetHasQrSource() {
        val target = targetFromQr(DeviceQr("A-1", "圧力計"))
        assertEquals(CaptureTarget("A-1", "圧力計", "qr"), target)
        assertEquals("qr", target.toMeta().deviceIdSource)
        assertNull(target.toMeta().operatorValue)
        assertNull(target.toMeta().operatorNote)
    }
    @Test fun routeTargetHasManualSource() = assertEquals(CaptureTarget("A-1", "圧力計", "manual"), targetFromRoute(route.first()))
    @Test fun manualTargetWithoutIdHasNoSource() = assertEquals(CaptureTarget(null, "圧力計", null), manualTarget(" 圧力計 ", "").getOrThrow())
    @Test fun manualTargetRejectsInvalidId() { assertTrue(manualTarget("圧力計", "A/1").isFailure) }
    @Test fun manualTargetRejectsInvalidName() {
        listOf("", " ", "a".repeat(65), "a\nb").forEach { assertTrue(manualTarget(it, "A-1").isFailure) }
    }
    @Test fun retakeKeepsDeviceAndSource() = assertEquals(CaptureTarget("A-1", "圧力計", "qr"), targetFromPhoto(photo().copy(deviceIdSource = "qr")))
    @Test fun initialTargetIsFirstMissingRouteDevice() = assertEquals(targetFromRoute(route[1]), initialTarget(route, listOf(photo())))
    @Test fun afterCaptureAdvancesToNextMissing() = assertEquals(targetFromRoute(route[1]), targetAfterCapture(route, listOf(photo()), targetFromRoute(route[0])))
    @Test fun afterCaptureWithoutRouteClearsTarget() = assertNull(targetAfterCapture(null, listOf(photo()), targetFromRoute(route[0])))
    @Test fun afterCaptureOfLastMissingIsNull() = assertNull(targetAfterCapture(route, listOf(photo(), photo("two", "A-2")), targetFromRoute(route[1])))
    @Test fun afterCaptureOfExtraClearsTarget() = assertNull(targetAfterCapture(route, listOf(photo(deviceId = "Z-9")), CaptureTarget("Z-9", "追加", "manual")))
    @Test fun targetSourceLabelIdentifiesSources() {
        val routeIds = setOf("A-1", "A-2")
        assertEquals("QR", targetSourceLabel(CaptureTarget("A-1", "圧力計", "qr"), routeIds))
        assertEquals("一覧から", targetSourceLabel(CaptureTarget("A-1", "圧力計", "manual"), routeIds))
        assertEquals("手入力", targetSourceLabel(CaptureTarget("X-9", "その他", "manual"), routeIds))
        assertEquals("機器IDなし", targetSourceLabel(CaptureTarget(null, "名前のみ", null), routeIds))
        assertEquals("機器IDなし", targetSourceLabel(null, routeIds))
    }
    @Test fun shouldKeepQrTargetPreservesSameDeviceQrOnly() {
        val device = RouteDevice("A-1", "圧力計")
        assertTrue(shouldKeepQrTarget(CaptureTarget("A-1", "圧力計", "qr"), device))
        assertFalse(shouldKeepQrTarget(CaptureTarget("A-2", "温度計", "qr"), device))
        assertFalse(shouldKeepQrTarget(CaptureTarget("A-1", "圧力計", "manual"), device))
        assertFalse(shouldKeepQrTarget(null, device))
    }
}
