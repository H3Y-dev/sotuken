package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import org.junit.Assert.*
import org.junit.Test

class CompleteUiStateTest {
    @Test fun warningsInFixedOrder() {
        val photos = listOf(photo(), photo("two"), photo("extra", "Z-9"), photo("unknown", null, null))
        assertEquals(listOf("未撮影：温度計 A-2", "重複：圧力計 A-1 が2枚", "一覧外：Z-9", "機器IDなし：1枚"), buildCompleteUiState(displayInspection, summarizeInspection(photos, displayRoute)).warnings)
    }
    @Test fun labelChangesWhenWarningsExist() {
        assertEquals("点検を完了する", buildCompleteUiState(displayInspection, summarizeInspection(listOf(photo()), listOf(displayRoute[0]))).completeLabel)
        assertEquals("確認して点検を完了する", buildCompleteUiState(displayInspection, summarizeInspection(listOf(photo()), displayRoute)).completeLabel)
    }
    @Test fun zeroPhotosBlocksCompletion() {
        val state = buildCompleteUiState(displayInspection, summarizeInspection(emptyList(), null))
        assertFalse(state.canComplete)
        assertEquals("写真がありません。撮影してから完了してください", state.blockReason)
    }
    @Test fun noRouteWarning() = assertEquals(listOf("対象一覧がないため、未撮影は確認できません"), buildCompleteUiState(displayInspection, summarizeInspection(listOf(photo()), null)).warnings)
    @Test fun completedInspectionCannotCompleteAgain() = assertFalse(buildCompleteUiState(displayInspection.copy(state = InspectionState.WAITING), summarizeInspection(listOf(photo()), null)).canComplete)
}
