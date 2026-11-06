package jp.sotuken.metercapture.queue

import java.io.File
import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.sender.Sender
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class SendRouterInspectionGateTest {
    @get:Rule val temp = TemporaryFolder()
    private val dao = FakeQueueDao()
    private val store = RoomQueueStore(dao)
    private class RecordingSender : Sender {
        val sent = mutableListOf<QueueItem>()
        override suspend fun send(item: QueueItem): Result<Unit> { sent += item; return Result.success(Unit) }
    }
    @Test fun inProgressPhotoStaysPendingAndIsNotWrittenToOutbox() = runTest {
        val folder = RecordingSender(); val outbox = temp.newFolder(); dao.insert(photo())
        SendRouter(dao, store, outbox, { null }, { Result.success(Unit) }, folderSender = folder, isSendable = { isPhotoSendable(it, InspectionState.IN_PROGRESS) }).route()
        assertEquals(SendState.PENDING, dao.findById("photo")?.sendState); assertTrue(folder.sent.isEmpty()); assertTrue(outbox.listFiles().orEmpty().isEmpty())
    }
    @Test fun waitingPhotoIsSentOverHttp() = runTest {
        val http = RecordingSender(); dao.insert(photo())
        SendRouter(dao, store, temp.newFolder(), { http }, { Result.success(Unit) }, isSendable = { isPhotoSendable(it, InspectionState.WAITING) }).route()
        assertEquals(1, http.sent.size); assertEquals(QueueItem.VIA_HTTP, dao.findById("photo")?.sentVia)
    }
    @Test fun legacyPhotoIsSentAsBefore() = runTest {
        val http = RecordingSender(); dao.insert(photo(inspectionId = null))
        SendRouter(dao, store, temp.newFolder(), { http }, { Result.success(Unit) }, isSendable = { isPhotoSendable(it, InspectionState.IN_PROGRESS) }).route()
        assertEquals(1, http.sent.size); assertEquals(SendState.SENT, dao.findById("photo")?.sendState)
    }
    @Test fun catchUpSkipsNonSendablePhotos() = runTest {
        val http = RecordingSender(); dao.insert(photo().copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_FOLDER)); dao.insert(photo("waiting", inspectionId = "waiting").copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_FOLDER))
        val outbox = temp.newFolder()
        for (item in dao.findByState(SendState.SENT)) File(outbox, "${SenderPayloads.buildBaseName(item)}.json").writeText("{}")
        SendRouter(dao, store, outbox, { http }, { Result.success(Unit) }, isSendable = { isPhotoSendable(it, if (it.inspectionId == "waiting") InspectionState.WAITING else InspectionState.IN_PROGRESS) }).route()
        assertEquals(listOf("waiting"), http.sent.map { it.localId }); assertEquals(QueueItem.VIA_FOLDER, dao.findById("photo")?.sentVia); assertEquals(QueueItem.VIA_HTTP, dao.findById("waiting")?.sentVia)
    }
    @Test fun defaultGateKeepsExistingBehavior() = runTest {
        val http = RecordingSender(); dao.insert(photo())
        SendRouter(dao, store, temp.newFolder(), { http }, { Result.success(Unit) }).route()
        assertEquals(1, http.sent.size); assertEquals(SendState.SENT, dao.findById("photo")?.sendState)
    }
}
