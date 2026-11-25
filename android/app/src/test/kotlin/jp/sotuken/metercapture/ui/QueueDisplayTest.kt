package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import jp.sotuken.metercapture.ui.components.GaugeKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QueueDisplayTest {
    @Test fun sendStatusKindFollowsLabelOrder() {
        val held = item(SendState.PENDING).copy(receiverId = "old")
        assertEquals("別のPC宛て（保留）", sendStatusLabel(held, "new") { false })
        assertEquals(GaugeKind.WARN, sendStatusKind(held, "new") { false })
        assertEquals(GaugeKind.WAIT, sendStatusKind(item(SendState.PENDING), isSendable = { false }))
        assertEquals(GaugeKind.WAIT, sendStatusKind(item(SendState.PENDING)))
        assertEquals(GaugeKind.WAIT, sendStatusKind(item(SendState.SENDING)))
        assertEquals(GaugeKind.WAIT, sendStatusKind(item(SendState.SENT, QueueItem.VIA_FOLDER)))
        assertEquals(GaugeKind.OK, sendStatusKind(item(SendState.SENT, QueueItem.VIA_HTTP)))
        assertEquals(GaugeKind.OK, sendStatusKind(item(SendState.SENT, QueueItem.VIA_USB)))
        assertEquals(GaugeKind.OK, sendStatusKind(item(SendState.SENT)))
        assertEquals(GaugeKind.FAIL, sendStatusKind(item(SendState.FAILED)))
    }
    @Test
    fun deleteAvailabilityAndConfirmationFollowState() {
        val unsent = "この写真を削除します。まだPCに未着のため、削除するとPCには送られません。"
        val sent = "端末内の写真を削除します。PCに到着した記録は消えません。"
        for (state in SendState.entries) {
            assertEquals(state != SendState.SENDING, canDelete(item(state)))
        }
        assertEquals(unsent, deleteConfirmationText(item(SendState.PENDING)))
        assertEquals(unsent, deleteConfirmationText(item(SendState.FAILED)))
        assertEquals(sent, deleteConfirmationText(item(SendState.SENT, QueueItem.VIA_HTTP)))
        assertEquals(sent, deleteConfirmationText(item(SendState.SENT, QueueItem.VIA_FOLDER)))
        assertEquals(unsent, deleteConfirmationText(
            item(SendState.SENT, QueueItem.VIA_FOLDER).copy(receiverId = "old"), "current",
        ))
    }

    private fun item(
        state: SendState,
        via: String? = null,
        error: String? = null,
        id: String = "id",
    ) = QueueItem(
        localId = id,
        imagePath = "/tmp/a.jpg",
        capturedAt = "2026-01-01T00:00:00Z",
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
        sendState = state,
        retryCount = 0,
        lastError = error,
        sentAt = null,
        sentVia = via,
    )

    @Test
    fun folderSentIsShownAsNotArrived() {
        assertEquals("PCに未着（端末に保存済み）", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_FOLDER)))
    }

    @Test
    fun httpSentIsShownAsReceived() {
        assertEquals("PCに到着", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_HTTP)))
    }

    @Test
    fun sentWithoutViaKeepsGenericLabel() {
        assertEquals("送信済み", sendStatusLabel(item(SendState.SENT, null)))
    }

    @Test
    fun otherStatesKeepLabels() {
        assertEquals("未送信", sendStatusLabel(item(SendState.PENDING)))
        assertEquals("送信中", sendStatusLabel(item(SendState.SENDING)))
        assertEquals("送信失敗", sendStatusLabel(item(SendState.FAILED)))
    }

    @Test
    fun undeliveredCountOnlyCountsFolderSent() {
        val items = listOf(
            item(SendState.SENT, QueueItem.VIA_FOLDER, id = "1"),
            item(SendState.SENT, QueueItem.VIA_FOLDER, id = "2"),
            item(SendState.SENT, QueueItem.VIA_HTTP, id = "3"),
            item(SendState.FAILED, id = "4"),
        )
        assertEquals(2, undeliveredCount(items))
        assertEquals("PCに未着 2枚（端末に保存済み）", undeliveredSummary(items))
    }

    @Test
    fun summaryIsNullWhenNothingUndelivered() {
        assertNull(undeliveredSummary(listOf(item(SendState.SENT, QueueItem.VIA_HTTP))))
        assertNull(undeliveredSummary(emptyList()))
    }

    @Test
    fun errorTextShownForFailedAndUndeliveredOnly() {
        assertEquals("端末への保存に失敗しました", errorTextFor(item(SendState.FAILED, error = "接続失敗")))
        assertEquals("端末への保存に失敗しました", errorTextFor(item(SendState.SENT, QueueItem.VIA_FOLDER, "接続失敗")))
        assertNull(errorTextFor(item(SendState.SENT, QueueItem.VIA_HTTP, "古いエラー")))
        assertNull(errorTextFor(item(SendState.FAILED, error = "  ")))
        assertNull(errorTextFor(item(SendState.FAILED, error = null)))
    }

    @Test
    fun reasonFromLastErrorMapsRawErrors() {
        assertEquals(null, reasonFromLastError(" "))
        assertEquals("送信先が未設定です", reasonFromLastError("送信先未設定"))
        assertEquals("合言葉が違います", reasonFromLastError("PC未接続: Health check failed with HTTP 401: x"))
        assertEquals("写真のファイルが見つかりません", reasonFromLastError("HTTP失敗: Image file does not exist"))
        assertEquals("PCが写真を受け付けませんでした", reasonFromLastError("追い送り失敗: HTTP 413: too large"))
        assertEquals("応答がありません", reasonFromLastError("HTTP失敗: unknown"))
        assertEquals("端末への保存に失敗しました", reasonFromLastError("Folder sender failed: x"))
        assertEquals("接続できません", reasonFromLastError("PC未接続: 接続できません"))
    }

    @Test
    fun canRetryOnlyForFailed() {
        assertTrue(canRetry(item(SendState.FAILED)))
        assertFalse(canRetry(item(SendState.PENDING)))
        assertFalse(canRetry(item(SendState.SENT, QueueItem.VIA_FOLDER)))
    }

    @Test
    fun sendStatusLabelDistinguishesAllConditions() {
        assertEquals("未送信", sendStatusLabel(item(SendState.PENDING)))
        assertEquals("PCに未着（端末に保存済み）", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_FOLDER)))
        assertEquals("PCに到着", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_HTTP)))
        assertEquals("送信失敗", sendStatusLabel(item(SendState.FAILED)))
        assertEquals("完了後に送信", sendStatusLabel(item(SendState.PENDING), isSendable = { false }))
        val held = item(SendState.PENDING).copy(receiverId = "old-pc")
        assertEquals("別のPC宛て（保留）", sendStatusLabel(held, currentReceiverId = "new-pc"))
    }

    @Test
    fun undeliveredSummaryIncludesPendingAndExcludesNonSendableOrHeld() {
        val pendingOnly = listOf(
            item(SendState.PENDING, id = "1"),
            item(SendState.PENDING, id = "2"),
        )
        assertEquals("未送信 2枚（端末に保存済み）", undeliveredSummary(pendingOnly))

        val mixed = listOf(
            item(SendState.PENDING, id = "1"),
            item(SendState.SENT, QueueItem.VIA_FOLDER, id = "2"),
        )
        assertEquals("未送信 2枚（端末に保存済み）", undeliveredSummary(mixed))

        val nonSendableMixed = listOf(
            item(SendState.PENDING, id = "1"),
            item(SendState.PENDING, id = "2"),
        )
        assertEquals(
            "未送信 1枚（端末に保存済み）",
            undeliveredSummary(nonSendableMixed, isSendable = { it.localId == "1" }),
        )

        val heldMixed = listOf(
            item(SendState.PENDING, id = "1").copy(receiverId = "old"),
            item(SendState.SENT, QueueItem.VIA_FOLDER, id = "2"),
        )
        assertEquals(
            "PCに未着 1枚（端末に保存済み）",
            undeliveredSummary(heldMixed, currentReceiverId = "current"),
        )
    }

    @Test
    fun errorTextForPendingWhenConnectionUnreachable() {
        val pending = item(SendState.PENDING)
        assertEquals(
            "接続できません",
            errorTextFor(pending, connectionUnreachable = true, connectionReason = "接続できません"),
        )
        assertEquals(
            "接続できません",
            errorTextFor(pending.copy(lastError = "PC未接続: 接続できません"), connectionUnreachable = true),
        )
        assertNull(
            errorTextFor(pending, connectionUnreachable = false, connectionReason = "接続できません"),
        )
        assertNull(
            errorTextFor(pending, connectionUnreachable = true, connectionReason = "接続できません", isSendable = { false }),
        )
        val held = pending.copy(receiverId = "old-pc")
        assertNull(
            errorTextFor(held, connectionUnreachable = true, connectionReason = "接続できません", currentReceiverId = "new-pc"),
        )
    }
}
