package jp.sotuken.metercapture.queue

import java.io.File
import java.time.Instant
import jp.sotuken.metercapture.inspection.RoundOutcome
import jp.sotuken.metercapture.inspection.decideAfterRound
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.ui.countUndelivered
import jp.sotuken.metercapture.ui.isUndelivered
import jp.sotuken.metercapture.ui.latestHttpSentAt
import jp.sotuken.metercapture.ui.sendStatusLabel
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class UsbArrivalTest {
    @get:Rule val temporary = TemporaryFolder()
    private val item = QueueItem("id", "/photo.jpg", "2026-11-11T00:00:00Z", null,
        null, null, SendState.SENT, 0, null, null, QueueItem.VIA_FOLDER)

    @Test fun allFilesPresentIsNotArrival() {
        assertFalse(isUsbArrival(item, listOf(true, true, true, true)))
    }

    @Test fun anyRemainingFilePreventsArrival() {
        for (remaining in 0..3) {
            assertFalse(isUsbArrival(item, List(4) { it == remaining }))
        }
    }

    @Test fun allFilesAbsentIsArrival() {
        assertTrue(isUsbArrival(item, List(4) { false }))
    }

    @Test fun httpIsNotTarget() {
        assertFalse(isUsbArrival(item.copy(sentVia = QueueItem.VIA_HTTP), List(4) { false }))
    }

    @Test fun onlySentFolderIsTarget() {
        for (state in listOf(SendState.PENDING, SendState.FAILED, SendState.SENDING)) {
            assertFalse(isUsbArrival(item.copy(sendState = state), List(4) { false }))
        }
        assertFalse(isUsbArrival(item.copy(sentVia = null), List(4) { false }))
    }

    @Test fun incompleteFileCheckIsNotArrival() {
        assertFalse(isUsbArrival(item, emptyList()))
    }

    @Test fun refreshPersistsArrivalAndClearsFallbackError() = runTest {
        val dao = FakeQueueDao()
        dao.insert(item.copy(lastError = "offline"))
        val store = RoomQueueStore(dao)
        val outbox = temporary.newFolder()
        store.refreshUsbArrivals(outbox)
        val arrived = dao.findById(item.localId)!!
        assertEquals(QueueItem.VIA_USB, arrived.sentVia)
        assertEquals(item.copy(sentVia = QueueItem.VIA_USB), arrived)
        store.refreshUsbArrivals(outbox)
        assertEquals(arrived, dao.findById(item.localId))
    }

    @Test fun refreshKeepsEachRemainingFilePendingArrival() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)
        val outbox = temporary.newFolder()
        val base = SenderPayloads.buildBaseName(item)
        dao.insert(item)
        for (suffix in listOf(".json", ".jpg", ".json.part", ".jpg.part")) {
            val file = File(outbox, base + suffix).apply { writeText("remaining") }
            store.refreshUsbArrivals(outbox)
            assertEquals(item, dao.findById(item.localId))
            assertTrue(file.delete())
        }
    }

    @Test fun unavailableOutboxDoesNotImplyArrival() = runTest {
        val dao = FakeQueueDao()
        dao.insert(item)
        RoomQueueStore(dao).refreshUsbArrivals(File(temporary.root, "unavailable"))
        assertEquals(item, dao.findById(item.localId))
    }

    @Test fun offlineWorkerRouteDetectsArrivalWithoutResending() = runTest {
        val dao = FakeQueueDao()
        dao.insert(item)
        SendRouter(dao, RoomQueueStore(dao), temporary.newFolder(),
            httpSenderProvider = { null },
            healthChecker = { error("HTTP must not be called") }).route()
        assertEquals(QueueItem.VIA_USB, dao.findById(item.localId)!!.sentVia)
    }

    @Test fun usbArrivalCountsAsDeliveredAcrossDisplaysAndInspectionRound() {
        val arrived = item.copy(sentVia = QueueItem.VIA_USB, sentAt = item.capturedAt)
        assertTrue(arrived.hasArrived())
        assertFalse(arrived.copy(sendState = SendState.FAILED).hasArrived())
        assertEquals(0, countUndelivered(listOf(arrived)))
        assertFalse(isUndelivered(arrived))
        assertEquals("送信済み(USB)", sendStatusLabel(arrived))
        assertEquals(Instant.parse(item.capturedAt), latestHttpSentAt(listOf(arrived)))
        assertEquals(RoundOutcome.ReadyForManifest(emptyList()), decideAfterRound(listOf(arrived), null))
    }
}
