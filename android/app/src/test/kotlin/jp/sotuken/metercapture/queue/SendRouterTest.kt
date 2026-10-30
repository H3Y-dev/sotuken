package jp.sotuken.metercapture.queue

import java.io.File
import jp.sotuken.metercapture.queue.sender.FolderSender
import jp.sotuken.metercapture.queue.sender.Sender
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SendRouterTest {

    private class RecordingSender(
        var returnSuccess: Boolean = true,
    ) : Sender {
        val sentItems = mutableListOf<QueueItem>()

        override suspend fun send(item: QueueItem): Result<Unit> {
            sentItems.add(item)
            return if (returnSuccess) {
                Result.success(Unit)
            } else {
                Result.failure(RuntimeException("Simulated send failure"))
            }
        }
    }

    @Test
    fun reachableRoutesPendingItemToHttp() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = true)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.success(Unit) },
                folderSender = folderSender,
            )

            router.route()

            val item = dao.findById(localId)
            assertEquals(SendState.SENT, item?.sendState)
            assertEquals(QueueItem.VIA_HTTP, item?.sentVia)
            assertEquals(1, httpSender.sentItems.size)
            assertEquals(0, folderSender.sentItems.size)
        }
    }

    @Test
    fun unreachableRoutesPendingItemToFolder() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = true)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.failure(RuntimeException("接続できません")) }, // 受信口に届かない
                folderSender = folderSender,
            )

            router.route()

            val item = dao.findById(localId)
            assertEquals(SendState.SENT, item?.sendState)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertEquals(0, httpSender.sentItems.size)
            assertEquals(1, folderSender.sentItems.size)
        }
    }

    @Test
    fun notConfiguredRoutesPendingItemToFolder() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { null }, // 設定未完了
                healthChecker = { Result.failure(RuntimeException("接続できません")) },
                folderSender = folderSender,
            )

            router.route()

            val item = dao.findById(localId)
            assertEquals(SendState.SENT, item?.sendState)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertEquals(1, folderSender.sentItems.size)
        }
    }

    @Test
    fun httpFailureFallsBackToFolderSender() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = false) // HTTP失敗
            val folderSender = FolderSender(outboxDir)

            val localId = store.enqueue(imageFile, emptyMeta())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.success(Unit) },
                folderSender = folderSender,
            )

            router.route()

            val item = dao.findById(localId)
            assertEquals(SendState.SENT, item?.sendState)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertEquals(1, httpSender.sentItems.size)
            assertTrue(File(outboxDir, SenderPayloads.buildImageFileName(requireNotNull(item))).isFile)
            assertTrue(File(outboxDir, "${SenderPayloads.buildBaseName(item)}.json").isFile)
        }
    }

    @Test
    fun folderFailureMarksItemAsFailed() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val folderSender = RecordingSender(returnSuccess = false) // 保存箱への保存失敗

            val localId = store.enqueue(imageFile, emptyMeta())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { null },
                healthChecker = { Result.failure(RuntimeException("接続できません")) },
                folderSender = folderSender,
            )

            router.route()

            val item = dao.findById(localId)
            assertEquals(SendState.FAILED, item?.sendState)
            assertTrue(item?.lastError?.contains("Simulated send failure") == true)
        }
    }

    @Test
    fun catchUpResendsFolderItemsViaHttpWhenReachableAndDeletesOutboxFiles() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = true)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)
            store.markSent(localId, QueueItem.VIA_FOLDER)

            val item = dao.findById(localId)!!
            val baseName = SenderPayloads.buildBaseName(item)
            val ext = File(item.imagePath).extension.ifBlank { "jpg" }
            val jsonFile = File(outboxDir, "$baseName.json").apply { writeText("{}") }
            val outboxImg = File(outboxDir, "$baseName.$ext").apply { writeText("img") }

            assertTrue(jsonFile.exists())
            assertTrue(outboxImg.exists())

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.success(Unit) },
                folderSender = folderSender,
            )

            router.route()

            // HTTPで再送された
            assertEquals(1, httpSender.sentItems.size)
            assertEquals(localId, httpSender.sentItems[0].localId)
            // 送信箱のファイルが消去された
            assertFalse(jsonFile.exists())
            assertFalse(outboxImg.exists())
            // sentVia が "http" に更新された
            val updatedItem = dao.findById(localId)
            assertEquals(QueueItem.VIA_HTTP, updatedItem?.sentVia)
            assertEquals(SendState.SENT, updatedItem?.sendState)
        }
    }

    @Test
    fun catchUpDoesNotResendWhenOutboxFilesAlreadyRemoved() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = true)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)
            store.markSent(localId, QueueItem.VIA_FOLDER)

            // USBで既に吸い出され、outboxにファイルが存在しない状況

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.success(Unit) },
                folderSender = folderSender,
            )

            router.route()

            // HTTPで再送されない
            assertEquals(0, httpSender.sentItems.size)
            // sentViaはfolderのまま
            assertEquals(QueueItem.VIA_FOLDER, dao.findById(localId)?.sentVia)
        }
    }

    @Test
    fun failedCatchUpKeepsFolderFilesAndSentVia() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val id = store.enqueue(imageFile, emptyMeta())
            store.markSending(id)
            val item = requireNotNull(dao.findById(id))
            assertTrue(FolderSender(outboxDir).send(item).isSuccess)
            store.markSent(id, QueueItem.VIA_FOLDER)
            val httpSender = RecordingSender(returnSuccess = false)
            SendRouter(dao, store, outboxDir, { httpSender }, { Result.success(Unit) }).route()
            assertEquals(1, httpSender.sentItems.size)
            assertEquals(QueueItem.VIA_FOLDER, dao.findById(id)?.sentVia)
            assertTrue(File(outboxDir, SenderPayloads.buildImageFileName(item)).isFile)
            assertTrue(File(outboxDir, "${SenderPayloads.buildBaseName(item)}.json").isFile)
        }
    }

    @Test
    fun catchUpDeletionFailureLeavesFolderStateForRetry() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val id = store.enqueue(imageFile, emptyMeta())
            store.markSending(id)
            store.markSent(id, QueueItem.VIA_FOLDER)
            val item = requireNotNull(dao.findById(id))
            val blockedFile = File(outboxDir, "${SenderPayloads.buildBaseName(item)}.json")
            blockedFile.mkdirs()
            File(blockedFile, "block-delete").writeText("keep")
            val httpSender = RecordingSender()
            val result = runCatching {
                SendRouter(dao, store, outboxDir, { httpSender }, { Result.success(Unit) }).route()
            }
            assertTrue(result.exceptionOrNull() is IllegalStateException)
            assertEquals(QueueItem.VIA_FOLDER, dao.findById(id)?.sentVia)
            assertTrue(blockedFile.exists())
        }
    }

    @Test
    fun catchUpDoesNotResendWhenUnreachable() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val httpSender = RecordingSender(returnSuccess = true)
            val folderSender = RecordingSender(returnSuccess = true)

            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)
            store.markSent(localId, QueueItem.VIA_FOLDER)

            val item = dao.findById(localId)!!
            val baseName = SenderPayloads.buildBaseName(item)
            val ext = File(item.imagePath).extension.ifBlank { "jpg" }
            val jsonFile = File(outboxDir, "$baseName.json").apply { writeText("{}") }
            val outboxImg = File(outboxDir, "$baseName.$ext").apply { writeText("img") }

            val router = SendRouter(
                queueDao = dao,
                queueStore = store,
                outboxDir = outboxDir,
                httpSenderProvider = { httpSender },
                healthChecker = { Result.failure(RuntimeException("接続できません")) }, // 届かない
                folderSender = folderSender,
            )

            router.route()

            assertEquals(0, httpSender.sentItems.size)
            assertTrue(jsonFile.exists())
            assertTrue(outboxImg.exists())
            assertEquals(QueueItem.VIA_FOLDER, dao.findById(localId)?.sentVia)
        }
    }

    @Test
    fun healthFailureRecordsReasonInLastError() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())

            SendRouter(
                dao, store, outboxDir, { RecordingSender() },
                { Result.failure(RuntimeException("timeout")) },
                RecordingSender(),
            ).route()

            val item = dao.findById(localId)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertTrue(item?.lastError?.contains("PC未接続") == true)
            assertTrue(item?.lastError?.contains("timeout") == true)
        }
    }

    @Test
    fun httpFailureRecordsReasonInLastError() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())

            SendRouter(
                dao, store, outboxDir, { RecordingSender(returnSuccess = false) },
                { Result.success(Unit) }, RecordingSender(),
            ).route()

            val item = dao.findById(localId)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertTrue(item?.lastError?.contains("HTTP失敗") == true)
            assertTrue(item?.lastError?.contains("Simulated send failure") == true)
        }
    }

    @Test
    fun notConfiguredRecordsReasonInLastError() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())

            SendRouter(
                dao, store, outboxDir, { null },
                { Result.failure(RuntimeException("x")) }, RecordingSender(),
            ).route()

            val item = dao.findById(localId)
            assertEquals(QueueItem.VIA_FOLDER, item?.sentVia)
            assertTrue(item?.lastError?.contains("送信先未設定") == true)
        }
    }

    @Test
    fun catchUpSuccessClearsLastErrorAndFailureUpdatesIt() = runTest {
        withTestEnv { outboxDir, imageFile ->
            val dao = FakeQueueDao()
            val store = RoomQueueStore(dao)
            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)
            store.markSent(localId, QueueItem.VIA_FOLDER, "PC未接続: timeout")
            val item = dao.findById(localId)!!
            File(outboxDir, "${SenderPayloads.buildBaseName(item)}.json").writeText("{}")

            val failing = RecordingSender(returnSuccess = false)
            SendRouter(dao, store, outboxDir, { failing }, { Result.success(Unit) }, RecordingSender()).route()
            assertTrue(dao.findById(localId)?.lastError?.contains("Simulated send failure") == true)
            assertEquals(QueueItem.VIA_FOLDER, dao.findById(localId)?.sentVia)

            val ok = RecordingSender()
            SendRouter(dao, store, outboxDir, { ok }, { Result.success(Unit) }, RecordingSender()).route()
            assertEquals(QueueItem.VIA_HTTP, dao.findById(localId)?.sentVia)
            assertNull(dao.findById(localId)?.lastError)
        }
    }

    private suspend fun withTestEnv(block: suspend (outboxDir: File, imageFile: File) -> Unit) {
        val tempDir = File.createTempFile("send-router-test-", "").apply {
            delete()
            mkdirs()
        }
        val outbox = File(tempDir, "outbox").apply { mkdirs() }
        val imageFile = File(tempDir, "test.jpg").apply { writeText("image-data") }

        try {
            block(outbox, imageFile)
        } finally {
            tempDir.deleteRecursively()
        }
    }

    private fun emptyMeta() = CaptureMeta(
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
    )
}
