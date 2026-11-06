package jp.sotuken.metercapture.queue

import androidx.sqlite.db.SupportSQLiteDatabase
import java.io.File
import java.lang.reflect.Proxy
import jp.sotuken.metercapture.queue.sender.FolderSender
import jp.sotuken.metercapture.queue.sender.Sender
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.ui.sendStatusLabel
import jp.sotuken.metercapture.ui.canRetry
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ReceiverPinTest {
    private val meta = CaptureMeta(null, null, null)

    private suspend fun withQueue(block: suspend (FakeQueueDao, File, File) -> Unit) {
        val dir = File(System.getProperty("java.io.tmpdir"), "receiver-pin-${java.util.UUID.randomUUID()}")
        check(dir.mkdirs())
        try {
            val image = File(dir, "photo.jpg").apply { writeText("same image bytes") }
            block(FakeQueueDao(), File(dir, "outbox"), image)
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun returningToOriginalReceiverAutomaticallyResumesWithoutReassigning() = runTest {
        withQueue { dao, outbox, image ->
            val store = RoomQueueStore(dao) { "pc-a" }
            val id = store.enqueue(image, meta)
            var sends = 0
            val sender = object : Sender {
                override suspend fun send(item: QueueItem): Result<Unit> {
                    sends++
                    assertEquals("pc-a", item.receiverId)
                    return Result.success(Unit)
                }
            }
            SendRouter(dao, store, outbox, { sender }, { Result.success(Unit) },
                currentReceiverId = "pc-b").route()
            assertTrue(dao.findById(id)!!.isHeldFor("pc-b"))
            assertEquals(0, sends)
            SendRouter(dao, store, outbox, { sender }, { Result.success(Unit) },
                currentReceiverId = "pc-a").route()
            assertEquals(SendState.SENT, dao.findById(id)?.sendState)
            assertEquals(1, sends)
        }
    }

    @Test
    fun legacyQueueItemWithoutReceiverFieldDefaultsToUnpinned() {
        val item = QueueItem("legacy", "/photo.jpg", "2026-11-06T00:00:00Z", null, null, null,
            SendState.PENDING, 0, null, null)
        assertNull(item.receiverId)
    }

    @Test
    fun capturePinsReceiverAndNormalizesEmptyIds() = runTest {
        withQueue { dao, _, image ->
            for (receiver in listOf("pc-a", "", "  ", null)) {
                val store = RoomQueueStore(dao) { receiver }
                val item = dao.findById(store.enqueue(image, meta))!!
                assertEquals(receiver?.takeIf { it.isNotBlank() }, item.receiverId)
            }
        }
    }

    @Test
    fun matchingAndLegacyUnpinnedItemsAreSent() = runTest {
        withQueue { dao, outbox, image ->
            val store = RoomQueueStore(dao)
            val legacy = store.enqueue(image, meta)
            val pinned = RoomQueueStore(dao) { "pc-a" }.enqueue(image, meta)
            val sent = mutableListOf<String>()
            val sender = object : Sender {
                override suspend fun send(item: QueueItem): Result<Unit> {
                    sent.add(item.localId)
                    return Result.success(Unit)
                }
            }
            SendRouter(dao, store, outbox, { sender }, { Result.success(Unit) },
                currentReceiverId = "pc-a").route()
            assertEquals(setOf(legacy, pinned), sent.toSet())
            assertTrue(sent.all { dao.findById(it)?.sendState == SendState.SENT })
        }
    }

    @Test
    fun pinnedItemIsHeldWhenCurrentReceiverIsMissingEvenOffline() = runTest {
        withQueue { dao, outbox, image ->
            val store = RoomQueueStore(dao) { "pc-a" }
            val id = store.enqueue(image, meta)
            SendRouter(dao, store, outbox, { null }, { error("No health request expected") }).route()
            val item = dao.findById(id)!!
            assertEquals(SendState.PENDING, item.sendState)
            assertTrue(item.isHeldFor(null))
            assertEquals(0, item.retryCount)
            assertNull(item.lastError)
            assertFalse(outbox.exists())
            assertTrue(image.exists())
            assertEquals("別のPC宛て(保留)", sendStatusLabel(item))
            assertFalse(canRetry(item))
        }
    }

    @Test
    fun heldOutboxIsKeptThenReassignedAndCleanedOnlyAfterSuccess() = runTest {
        withQueue { dao, outbox, image ->
            val store = RoomQueueStore(dao) { "pc-a" }
            val id = store.enqueue(image, meta)
            SendRouter(dao, store, outbox, { null }, { error("offline") },
                currentReceiverId = "pc-a").route()
            val files = outbox.listFiles()!!.toList()
            var sends = 0
            val sender = object : Sender {
                override suspend fun send(item: QueueItem): Result<Unit> {
                    sends++
                    assertEquals("pc-b", item.receiverId)
                    return Result.success(Unit)
                }
            }
            val router = SendRouter(dao, store, outbox, { sender }, { Result.success(Unit) },
                currentReceiverId = "pc-b")
            repeat(2) { router.route() }
            assertEquals(SendState.SENT, dao.findById(id)?.sendState)
            assertTrue(dao.findById(id)!!.isHeldFor("pc-b"))
            assertTrue(files.all { it.exists() })
            assertEquals(0, sends)
            store.reassignReceiver(id, "pc-b")
            router.route()
            assertEquals(1, sends)
            assertEquals(QueueItem.VIA_HTTP, dao.findById(id)?.sentVia)
            assertTrue(files.none { it.exists() })
            assertTrue(image.exists())
        }
    }

    @Test
    fun reassignToManualReceiverUnpinsWithoutChangingImageOrIdentity() = runTest {
        withQueue { dao, _, image ->
            val store = RoomQueueStore(dao) { "pc-a" }
            val id = store.enqueue(image, meta)
            val before = dao.findById(id)!!
            val hash = SenderPayloads.computeSha256Hex(image)
            store.reassignReceiver(id, " ")
            val after = dao.findById(id)!!
            assertEquals(before.copy(receiverId = null), after)
            assertEquals(hash, SenderPayloads.computeSha256Hex(File(after.imagePath)))
        }
    }

    @Test
    fun legacyJsonRemainsIdenticalForPinnedAndUnpinnedItems() = runTest {
        withQueue { dao, outbox, image ->
            val store = RoomQueueStore(dao)
            val item = dao.findById(store.enqueue(image, meta))!!
            assertNull(item.receiverId)
            val expected = "{\"local_id\":\"${item.localId}\",\"captured_at\":\"${item.capturedAt}\",\"device_name\":null,\"operator_value\":null,\"operator_note\":null}"
            assertEquals(expected, SenderPayloads.buildSidecarJson(item))
            FolderSender(outbox).send(item).getOrThrow()
            val json = File(outbox, "${SenderPayloads.buildBaseName(item)}.json")
            assertEquals(expected, json.readText())
            assertEquals(expected, SenderPayloads.buildSidecarJson(item.copy(receiverId = "pc-a")))
        }
    }

    @Test
    fun migrationAddsNullableReceiverWithoutDroppingOldRows() {
        val sql = mutableListOf<String>()
        val db = Proxy.newProxyInstance(SupportSQLiteDatabase::class.java.classLoader,
            arrayOf(SupportSQLiteDatabase::class.java)) { _, method, args ->
            check(method.name == "execSQL")
            sql.add(args!![0] as String)
            null
        } as SupportSQLiteDatabase
        CaptureDatabase.MIGRATION_2_3.migrate(db)
        assertEquals(listOf("ALTER TABLE queue_items ADD COLUMN receiverId TEXT"), sql)
        val converter = SendStateConverter()
        for (state in SendState.entries) {
            assertEquals(state, converter.toSendState(converter.fromSendState(state)))
        }
    }

    @Test
    fun onlyHeldItemsCanBeReassigned() = runTest {
        withQueue { dao, _, image ->
            val store = RoomQueueStore(dao)
            val id = store.enqueue(image, meta)
            try {
                store.reassignReceiver(id, "pc-b")
                fail("PENDING must not be reassigned")
            } catch (_: IllegalStateException) {
                assertNull(dao.findById(id)?.receiverId)
            }
        }
    }
}
