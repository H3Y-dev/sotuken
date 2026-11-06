package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QueueDisplayTest {
    @Test
    fun deleteAvailabilityAndConfirmationFollowState() {
        val unsent = "この写真を削除します。まだPCに届いていないため、削除するとPCには送られません。"
        val sent = "端末内の写真を削除します。PCに届いた記録は消えません。"
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
        assertEquals("PC未到着・端末に保存済み", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_FOLDER)))
    }

    @Test
    fun httpSentIsShownAsReceived() {
        assertEquals("PC受信済み", sendStatusLabel(item(SendState.SENT, QueueItem.VIA_HTTP)))
    }

    @Test
    fun sentWithoutViaKeepsGenericLabel() {
        assertEquals("送信済み", sendStatusLabel(item(SendState.SENT, null)))
    }

    @Test
    fun otherStatesKeepLabels() {
        assertEquals("未送信", sendStatusLabel(item(SendState.PENDING)))
        assertEquals("送信中", sendStatusLabel(item(SendState.SENDING)))
        assertEquals("失敗", sendStatusLabel(item(SendState.FAILED)))
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
        assertEquals("PC未到着: 2件（端末に保存済み）", undeliveredSummary(items))
    }

    @Test
    fun summaryIsNullWhenNothingUndelivered() {
        assertNull(undeliveredSummary(listOf(item(SendState.SENT, QueueItem.VIA_HTTP))))
        assertNull(undeliveredSummary(emptyList()))
    }

    @Test
    fun errorTextShownForFailedAndUndeliveredOnly() {
        assertEquals("接続失敗", errorTextFor(item(SendState.FAILED, error = "接続失敗")))
        assertEquals("接続失敗", errorTextFor(item(SendState.SENT, QueueItem.VIA_FOLDER, "接続失敗")))
        assertNull(errorTextFor(item(SendState.SENT, QueueItem.VIA_HTTP, "古いエラー")))
        assertNull(errorTextFor(item(SendState.FAILED, error = "  ")))
        assertNull(errorTextFor(item(SendState.FAILED, error = null)))
    }

    @Test
    fun canRetryOnlyForFailed() {
        assertTrue(canRetry(item(SendState.FAILED)))
        assertFalse(canRetry(item(SendState.PENDING)))
        assertFalse(canRetry(item(SendState.SENT, QueueItem.VIA_FOLDER)))
    }
}
