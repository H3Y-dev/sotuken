package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import org.junit.Assert.*
import org.junit.Test

internal val displayInspection = Inspection("inspection", "11/06 朝の点検", null, null, null, null, null, InspectionState.IN_PROGRESS, "2026-11-06T00:00:00Z")
internal val displayRoute = listOf(RouteDevice("A-1", "圧力計"), RouteDevice("A-2", "温度計"))

class CaptureUiStateTest {
    @Test fun savedTimeFormatsInRequestedZone() {
        assertEquals("11/06 09:32", formatInspectionCaptureTime("2026-11-06T00:32:00Z", java.time.ZoneId.of("Asia/Tokyo")))
        assertEquals("invalid", formatInspectionCaptureTime("invalid", java.time.ZoneId.of("Asia/Tokyo")))
    }
    @Test fun routeProgressText() = assertEquals("対象 2機器中 1機器を撮影", buildCaptureUiState(displayInspection, displayRoute, listOf(photo()), null, null).progress)
    @Test fun noRouteProgressText() {
        val state = buildCaptureUiState(displayInspection, null, listOf(photo(), photo("two")), null, null)
        assertEquals("写真2枚 ・ 1機器", state.progress)
        assertEquals("この点検：写真2枚 ・ 1機器", state.countLine)
    }
    @Test fun missingChipsOnlyWithRoute() {
        assertEquals(listOf(displayRoute[1]), buildCaptureUiState(displayInspection, displayRoute, listOf(photo()), null, null).missingChips)
        assertTrue(buildCaptureUiState(displayInspection, null, emptyList(), null, null).missingChips.isEmpty())
    }
    @Test fun emptyTargetTexts() {
        val state = buildCaptureUiState(displayInspection, null, emptyList(), null, null)
        assertEquals("機器が選ばれていません", state.targetName)
        assertEquals("QRを読むか、手入力してください", state.targetId)
        assertEquals("機器IDなし", state.targetSourceLabel)
    }
    @Test fun targetSourceLabelInState() {
        val state = buildCaptureUiState(displayInspection, displayRoute, emptyList(), CaptureTarget("A-1", "圧力計", "qr"), null)
        assertEquals("QR", state.targetSourceLabel)
    }
}
