package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.SendState
import org.junit.Assert.*
import org.junit.Test

class HistoryUiStateTest {
    @Test fun routeRowsMarkDoneAndCounts() {
        val state = buildHistoryUiState(displayInspection, displayRoute, listOf(photo(), photo("two")))
        assertEquals(listOf(RouteCheckRow(displayRoute[0], 2, true), RouteCheckRow(displayRoute[1], 0, false)), state.routeRows)
        assertEquals("1 / 2機器", state.deviceLine)
    }
    @Test fun duplicateNoticePerDevice() = assertEquals(listOf("A-1は2枚あります。撮り直しの写真か確認してください。"), buildHistoryUiState(displayInspection, null, listOf(photo(), photo("two"))).notices)
    @Test fun sourceLabels() {
        assertEquals("QR", deviceSourceLabel(photo().copy(deviceIdSource = "qr"), setOf("A-1")))
        assertEquals("一覧から", deviceSourceLabel(photo().copy(deviceIdSource = "manual"), setOf("A-1")))
        assertEquals("手入力", deviceSourceLabel(photo().copy(deviceIdSource = "manual"), emptySet()))
        assertEquals("機器IDなし", deviceSourceLabel(photo(deviceId = null).copy(deviceIdSource = "qr"), emptySet()))
    }
    @Test fun editDisabledAfterCompletion() = assertFalse(buildHistoryUiState(displayInspection.copy(state = InspectionState.WAITING), null, listOf(photo())).rows.single().canEdit)
    @Test fun editDisabledWhileSending() = assertFalse(buildHistoryUiState(displayInspection, null, listOf(photo().copy(sendState = SendState.SENDING))).rows.single().canEdit)
    @Test fun noRouteNote() {
        assertEquals("対象一覧がないため、未撮影の機器は判定できません", buildHistoryUiState(displayInspection, null, emptyList()).noRouteNote)
        assertNull(buildHistoryUiState(displayInspection, displayRoute, emptyList()).noRouteNote)
    }
}
