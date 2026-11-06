package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import org.junit.Assert.*
import org.junit.Test

class HomeUiStateTest {
    private fun row(state: InspectionState = InspectionState.IN_PROGRESS) = InspectionListItem(inspection(state = state), InspectionPhotoCount("inspection", 3, 2, 1))
    @Test fun groupsByState() {
        val state = buildHomeUiState(InspectionState.entries.map { row(it).let { row -> row.copy(inspection = row.inspection.copy(inspectionId = it.name)) } }, emptyList(), emptyMap())
        assertEquals(1, state.inProgress.size); assertEquals(2, state.waiting.size); assertEquals(2, state.sent.size)
    }
    @Test fun sortsNewestFirstWithinGroup() {
        val old = row(); val newer = old.copy(inspection = old.inspection.copy(inspectionId = "new", startedAt = "2026-11-07T00:00:00Z"))
        assertEquals(listOf("new", "inspection"), buildHomeUiState(listOf(old, newer), emptyList(), emptyMap()).inProgress.map { it.inspectionId })
    }
    @Test fun inProgressSubtitleShowsOperatorPlaceAndCounts() = assertEquals("大久保 ・ 第1工場 写真3枚 ・ 2機器", buildHomeUiState(listOf(row()), emptyList(), emptyMap()).inProgress.single().subtitle)
    @Test fun waitingSubtitleMentionsAutoSend() = assertEquals("写真3枚 ・ 接続確認後に自動送信", buildHomeUiState(listOf(row(InspectionState.WAITING)), emptyList(), emptyMap()).waiting.single().subtitle)
    @Test fun sentIncompleteShowsUndeliveredCount() {
        val failed = photo().copy(sendState = SendState.FAILED)
        val state = buildHomeUiState(listOf(row(InspectionState.SENT_INCOMPLETE)), emptyList(), mapOf("inspection" to listOf(failed))).sent.single()
        assertEquals("送信済み（未到着1枚）", state.stateLabel); assertEquals("写真3枚 ・ 1枚が未到着", state.subtitle)
    }
    @Test fun legacyUndeliveredShownOnlyWhenPositive() {
        assertNull(buildHomeUiState(emptyList(), emptyList(), emptyMap()).legacyUndelivered)
        assertEquals("点検なしの写真: 未着1件", buildHomeUiState(emptyList(), listOf(photo(inspectionId = null)), emptyMap()).legacyUndelivered)
        assertNull(buildHomeUiState(emptyList(), listOf(photo()), emptyMap()).legacyUndelivered)
    }
}
