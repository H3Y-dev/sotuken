package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.ui.components.BadgeSpec
import jp.sotuken.metercapture.ui.components.GaugeKind
import java.time.ZoneId
import org.junit.Assert.*
import org.junit.Test

class HomeUiStateTest {
    @Test fun sentBadgeTurnsNeutralWhenRouteDeviceMissing() {
        val route = """{"v":1,"route_id":"R-20261106093000-a1b2","name":"巡回","devices":[{"id":"A-1","name":"計器"},{"id":"A-2","name":"計器2"}],"updated_at":"2026-11-06T00:30:00Z"}"""
        val item = row(InspectionState.SENT).let { it.copy(inspection = it.inspection.copy(routeSnapshot = route)) }
        fun card(photos: List<QueueItem>) = buildHomeUiState(listOf(item), emptyList(), mapOf("inspection" to photos)).sent.single()
        val complete = card(listOf(photo(), photo(id = "p2", deviceId = "A-2")))
        assertEquals(GaugeKind.OK, complete.kind); assertEquals("送信済み", complete.stateLabel); assertEquals(emptyList<BadgeSpec>(), complete.badges); assertEquals(GaugeKind.OK, complete.edgeKind)
        val missing = card(listOf(photo()))
        assertEquals(GaugeKind.NEUTRAL, missing.kind); assertEquals("送信済み（要確認あり）", missing.stateLabel); assertEquals(listOf(BadgeSpec(GaugeKind.MISSING, "未撮影 1台")), missing.badges); assertEquals(GaugeKind.MISSING, missing.edgeKind)
    }
    @Test fun formatStartedLabelFormatsInRequestedZoneAndFallsBack() {
        val zone = ZoneId.of("Asia/Tokyo")
        assertEquals("11/12(木) 09:00", formatStartedLabel("2026-11-12T00:00:00Z", zone))
        assertEquals("invalid", formatStartedLabel("invalid", zone))
    }
    private fun row(state: InspectionState = InspectionState.IN_PROGRESS) = InspectionListItem(inspection(state = state), InspectionPhotoCount("inspection", 3, 2, 1))
    @Test fun groupsByState() {
        val state = buildHomeUiState(InspectionState.entries.map { row(it).let { row -> row.copy(inspection = row.inspection.copy(inspectionId = it.name)) } }, emptyList(), emptyMap())
        assertEquals(1, state.inProgress.size); assertEquals(2, state.waiting.size); assertEquals(2, state.sent.size)
    }
    @Test fun sortsNewestFirstWithinGroup() {
        val old = row(); val newer = old.copy(inspection = old.inspection.copy(inspectionId = "new", startedAt = "2026-11-07T00:00:00Z"))
        assertEquals(listOf("new", "inspection"), buildHomeUiState(listOf(old, newer), emptyList(), emptyMap()).inProgress.map { it.inspectionId })
    }
    @Test fun inProgressSubtitleShowsOperatorPlaceAndCounts() = assertEquals("大久保 ・ 第1工場 写真3枚 ・ 2台", buildHomeUiState(listOf(row()), emptyList(), emptyMap()).inProgress.single().subtitle)
    @Test fun waitingSubtitleMentionsAutoSend() = assertEquals("写真3枚 ・ 接続確認後に自動送信", buildHomeUiState(listOf(row(InspectionState.WAITING)), emptyList(), emptyMap()).waiting.single().subtitle)
    @Test fun sentIncompleteShowsUndeliveredCount() {
        val failed = photo().copy(sendState = SendState.FAILED)
        val state = buildHomeUiState(listOf(row(InspectionState.SENT_INCOMPLETE)), emptyList(), mapOf("inspection" to listOf(failed))).sent.single()
        assertEquals("未着あり 1枚", state.stateLabel); assertEquals("写真3枚 ・ 未着 1枚", state.subtitle)
    }
    @Test fun legacyUndeliveredShownOnlyWhenPositive() {
        assertNull(buildHomeUiState(emptyList(), emptyList(), emptyMap()).legacyUndelivered)
        assertEquals("点検なしの写真 未着 1枚", buildHomeUiState(emptyList(), listOf(photo(inspectionId = null)), emptyMap()).legacyUndelivered)
        assertNull(buildHomeUiState(emptyList(), listOf(photo()), emptyMap()).legacyUndelivered)
    }
}
