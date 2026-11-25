package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import org.junit.Assert.*
import org.junit.Test

internal val displayInspection = Inspection("inspection", "11/06 朝の点検", null, null, null, null, null, InspectionState.IN_PROGRESS, "2026-11-06T00:00:00Z")
internal val displayRoute = listOf(RouteDevice("A-1", "圧力計"), RouteDevice("A-2", "温度計"))

class CaptureUiStateTest {
    @Test fun savedTimeFormatsInRequestedZone() {
        assertEquals("11/06 09:32", formatInspectionCaptureTime("2026-11-06T00:32:00Z", java.time.ZoneId.of("Asia/Tokyo")))
        assertEquals("invalid", formatInspectionCaptureTime("invalid", java.time.ZoneId.of("Asia/Tokyo")))
    }
    @Test fun routeProgressText() = assertEquals("撮影 1/2台", buildCaptureUiState(displayInspection, displayRoute, listOf(photo()), null, null).progress)
    @Test fun noRouteProgressText() {
        val state = buildCaptureUiState(displayInspection, null, listOf(photo(), photo("two")), null, null)
        assertEquals("写真2枚 ・ 1台", state.progress)
        assertEquals("この点検：写真2枚 ・ 1台", state.countLine)
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
    @Test fun countTodayPhotosRespectsZoneAndDayBoundary() {
        val tokyo = ZoneId.of("Asia/Tokyo")
        val items = listOf(
            photo().copy(capturedAt = "2026-11-12T14:59:59Z"),
            photo("two").copy(capturedAt = "2026-11-12T15:00:00Z"),
            photo("three").copy(capturedAt = "2026-11-13T14:59:59Z"),
            photo("four").copy(capturedAt = "broken"),
        )
        assertEquals(2, countTodayPhotos(items, LocalDate.of(2026, 11, 13), tokyo))
    }
    @Test fun todayCaptureCountAfterSaveHandlesQueueDateBasisAndMultipleUnreflected() {
        val tokyo = ZoneId.of("Asia/Tokyo")
        val today = Instant.parse("2026-11-13T01:00:00Z")
        val existingOne = listOf(photo().copy(imagePath = "/existing.jpg", capturedAt = "2026-11-13T00:10:00Z"))
        assertEquals(2, todayCaptureCountAfterSave(existingOne, "/new.jpg", today, zone = tokyo))

        val reflectedTwo = existingOne + photo("two").copy(imagePath = "/new.jpg", capturedAt = "2026-11-13T01:00:00Z")
        assertEquals(2, todayCaptureCountAfterSave(reflectedTwo, "/new.jpg", today, zone = tokyo))

        val unconfirmed = mapOf("/unconfirmed1.jpg" to Instant.parse("2026-11-13T00:30:00Z"))
        assertEquals(2, todayCaptureCountAfterSave(emptyList(), "/new.jpg", today, unconfirmed, tokyo))

        val boundaryReflected = listOf(photo().copy(imagePath = "/boundary.jpg", capturedAt = "2026-11-12T15:00:00Z"))
        val prevDayFallback = Instant.parse("2026-11-12T14:59:59Z")
        assertEquals(1, todayCaptureCountAfterSave(boundaryReflected, "/boundary.jpg", prevDayFallback, zone = tokyo))

        val prevDayUnconfirmed = mapOf("/prev.jpg" to Instant.parse("2026-11-12T14:59:59Z"))
        assertEquals(1, todayCaptureCountAfterSave(emptyList(), "/new.jpg", today, prevDayUnconfirmed, tokyo))
    }
}
