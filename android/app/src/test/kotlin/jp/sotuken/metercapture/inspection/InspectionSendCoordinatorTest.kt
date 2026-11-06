package jp.sotuken.metercapture.inspection

import java.time.Instant
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class InspectionSendCoordinatorTest {
    private val queue = FakeQueueDao()
    private val dao = FakeInspectionDao(queue)
    private val now = Instant.parse("2026-11-06T02:00:00Z")
    private val inspection = Inspection("I-1", "巡回", "担当", "工場", null, null, null, InspectionState.WAITING, "2026-11-06T01:00:00Z", now.toString())
    private val photo = QueueItem("a", "/a", "2026-11-06T01:10:00Z", null, null, null, SendState.SENT, 0, null, now.toString(), QueueItem.VIA_HTTP, inspectionId = "I-1")
    private var calls = 0
    private fun coordinator(reply: Result<ManifestReply> = Result.success(ManifestReply(1, emptyList())), poster: Boolean = true) = InspectionSendCoordinator(dao,
        if (poster) { _, _ -> calls++; reply } else null, { "a".repeat(64) }, { now })
    private suspend fun setup(state: InspectionState = InspectionState.SENDING, item: QueueItem = photo) {
        dao.insert(inspection.copy(state = state)); queue.insert(item)
    }
    @Test fun beforeRouteRecoversSending() = runBlocking {
        setup(); coordinator().beforeRoute(false)
        assertEquals(InspectionState.WAITING, dao.findById("I-1")!!.state)
    }
    @Test fun beforeRouteMarksWaitingAsSendingOnlyWhenReachable() = runBlocking {
        setup(InspectionState.WAITING); val c = coordinator()
        c.beforeRoute(false); assertEquals(InspectionState.WAITING, dao.findById("I-1")!!.state)
        c.beforeRoute(true); assertEquals(InspectionState.SENDING, dao.findById("I-1")!!.state)
    }
    @Test fun unfinishedRoundReturnsToWaiting() = runBlocking {
        setup(item = photo.copy(sendState = SendState.PENDING)); coordinator().afterRoute(null)
        assertEquals(InspectionState.WAITING, dao.findById("I-1")!!.state); assertEquals(0, calls)
    }
    @Test fun folderOnlyPhotoKeepsWaiting() = runBlocking {
        setup(item = photo.copy(sentVia = QueueItem.VIA_FOLDER)); coordinator().afterRoute(null)
        assertEquals(InspectionState.WAITING, dao.findById("I-1")!!.state); assertEquals(0, calls)
    }
    @Test fun heldPhotoKeepsWaiting() = runBlocking {
        setup(item = photo.copy(sendState = SendState.FAILED, receiverId = "other")); coordinator().afterRoute("current")
        assertEquals(InspectionState.WAITING, dao.findById("I-1")!!.state); assertEquals(0, calls)
    }
    @Test fun allDeliveredSendsManifestAndMarksSent() = runBlocking {
        setup(); coordinator().afterRoute(null)
        val result = dao.findById("I-1")!!
        assertEquals(InspectionState.SENT, result.state); assertEquals(now.toString(), result.manifestSentAt)
        assertNull(result.manifestError); assertEquals("[]", result.pcMissingFileNames); assertEquals(1, calls)
    }
    @Test fun failedPhotoSendsManifestAndMarksIncomplete() = runBlocking {
        setup(item = photo.copy(sendState = SendState.FAILED)); coordinator().afterRoute(null)
        assertEquals(InspectionState.SENT_INCOMPLETE, dao.findById("I-1")!!.state); assertEquals(1, calls)
    }
    @Test fun pcMissingPhotosMarkIncomplete() = runBlocking {
        setup(); coordinator(Result.success(ManifestReply(0, listOf(SenderPayloads.buildImageFileName(photo))))).afterRoute(null)
        assertEquals(InspectionState.SENT_INCOMPLETE, dao.findById("I-1")!!.state)
        assertEquals(listOf(SenderPayloads.buildImageFileName(photo)), parseMissingFileNames(dao.findById("I-1")!!.pcMissingFileNames))
    }
    @Test fun manifestFailureKeepsWaitingWithError() = runBlocking {
        setup(); coordinator(Result.failure(IllegalStateException("PCのアプリを更新してください"))).afterRoute(null)
        val result = dao.findById("I-1")!!
        assertEquals(InspectionState.WAITING, result.state); assertTrue(result.manifestError!!.contains("更新"))
    }
    @Test fun noPosterKeepsWaitingWithError() = runBlocking {
        setup(); coordinator(poster = false).afterRoute(null)
        assertEquals("PCに届かないため、写真の一覧を送れませんでした", dao.findById("I-1")!!.manifestError)
    }
    @Test fun decideAfterRoundRules() {
        SendState.entries.forEach { state ->
            val result = decideAfterRound(listOf(photo.copy(sendState = state)), null)
            if (state == SendState.PENDING || state == SendState.SENDING) assertEquals(RoundOutcome.Unfinished, result)
            else assertTrue(result is RoundOutcome.ReadyForManifest)
        }
    }
    @Test fun workingInspectionIsNeverSendable() = runBlocking {
        setup(InspectionState.IN_PROGRESS)
        assertFalse(coordinator().isSendable(photo))
        assertTrue(coordinator().isSendable(photo.copy(inspectionId = null)))
        assertTrue(coordinator().isSendable(photo.copy(inspectionId = "missing")))
    }
}
