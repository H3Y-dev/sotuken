package jp.sotuken.metercapture.queue

import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class RoomQueueStoreTest {
    @Test
    fun enqueueReturnsLocalIdThatCanBeFound() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            assertTrue(localId.isNotBlank())
            assertNotNull(dao.findById(localId))
        }
    }

    @Test
    fun enqueueCreatesPendingItemWithInitialValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            val item = dao.findById(localId)

            assertNotNull(item)
            assertEquals(SendState.PENDING, item?.sendState)
            assertEquals(0, item?.retryCount)
            assertEquals(null, item?.lastError)
            assertEquals(null, item?.sentAt)
        }
    }

    @Test
    fun enqueueStoresAbsoluteImagePath() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            assertEquals(imageFile.absolutePath, dao.findById(localId)?.imagePath)
        }
    }

    @Test
    fun enqueuePreservesCaptureMetaValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)
        val meta = CaptureMeta(
            deviceName = "Pressure meter A",
            operatorValue = 12.5,
            operatorNote = "verified",
        )

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, meta)
            val item = dao.findById(localId)

            assertEquals(meta.deviceName, item?.deviceName)
            assertEquals(meta.operatorValue, item?.operatorValue)
            assertEquals(meta.operatorNote, item?.operatorNote)
        }
    }

    @Test
    fun enqueuePreservesNullCaptureMetaValues() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            val item = dao.findById(localId)

            assertEquals(null, item?.deviceName)
            assertEquals(null, item?.operatorValue)
            assertEquals(null, item?.operatorNote)
        }
    }

    @Test
    fun enqueueGeneratesDifferentLocalIds() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val firstLocalId = store.enqueue(imageFile, emptyMeta())
            val secondLocalId = store.enqueue(imageFile, emptyMeta())

            assertTrue(firstLocalId != secondLocalId)
        }
    }

    @Test
    fun observeQueueContainsEveryEnqueuedItem() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val firstLocalId = store.enqueue(imageFile, emptyMeta())
            val secondLocalId = store.enqueue(imageFile, emptyMeta())
            val items = store.observeQueue().first()

            assertEquals(2, items.size)
            assertEquals(setOf(firstLocalId, secondLocalId), items.map { it.localId }.toSet())
        }
    }

    // --- markSending ---

    @Test
    fun markSendingTransitionsPendingToSending() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            store.markSending(localId)

            assertEquals(SendState.SENDING, dao.findById(localId)?.sendState)
        }
    }

    @Test
    fun markSendingFromNonPendingStateThrows() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)

            try {
                store.markSending(localId)
                fail("expected IllegalStateException")
            } catch (e: IllegalStateException) {
                // 期待どおり: SENDING状態からのmarkSendingは許可されない
            }
        }
    }

    // --- markSent ---

    @Test
    fun markSentTransitionsSendingToSentAndSetsSentAt() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)

            store.markSent(localId)

            val item = dao.findById(localId)
            assertEquals(SendState.SENT, item?.sendState)
            assertNotNull(item?.sentAt)
        }
    }

    @Test
    fun markSentFromPendingStateThrows() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            try {
                store.markSent(localId)
                fail("expected IllegalStateException")
            } catch (e: IllegalStateException) {
                // 期待どおり: PENDING状態から直接markSentは許可されない
            }
        }
    }

    // --- markFailed ---

    @Test
    fun markFailedTransitionsSendingToFailedAndSetsErrorAndRetryCount() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)

            store.markFailed(localId, "timeout")

            val item = dao.findById(localId)
            assertEquals(SendState.FAILED, item?.sendState)
            assertEquals("timeout", item?.lastError)
            assertEquals(1, item?.retryCount)
        }
    }

    @Test
    fun markFailedFromPendingStateThrows() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            try {
                store.markFailed(localId, "timeout")
                fail("expected IllegalStateException")
            } catch (e: IllegalStateException) {
                // 期待どおり: PENDING状態から直接markFailedは許可されない
            }
        }
    }

    // --- retry ---

    @Test
    fun retryTransitionsFailedToPendingAndClearsErrorButKeepsRetryCount() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())
            store.markSending(localId)
            store.markFailed(localId, "timeout")

            store.retry(localId)

            val item = dao.findById(localId)
            assertEquals(SendState.PENDING, item?.sendState)
            assertNull(item?.lastError)
            assertEquals(1, item?.retryCount)
        }
    }

    @Test
    fun retryFromPendingStateThrows() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val localId = store.enqueue(imageFile, emptyMeta())

            try {
                store.retry(localId)
                fail("expected IllegalStateException")
            } catch (e: IllegalStateException) {
                // 期待どおり: PENDING状態から直接retryは許可されない
            }
        }
    }

    // --- unknown localId ---

    @Test
    fun markSendingWithUnknownLocalIdThrowsIllegalArgumentException() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        try {
            store.markSending("unknown-local-id")
            fail("expected IllegalArgumentException")
        } catch (e: IllegalArgumentException) {
            // 期待どおり: 存在しないlocalIdはIllegalArgumentException
        }
    }

    @Test
    fun recoverInterruptedSendsResetsOnlySendingItemsToPending() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val sendingId = store.enqueue(imageFile, emptyMeta())
            store.markSending(sendingId)

            val pendingId = store.enqueue(imageFile, emptyMeta())

            store.recoverInterruptedSends()

            assertEquals(SendState.PENDING, dao.findById(sendingId)?.sendState)
            assertEquals(SendState.PENDING, dao.findById(pendingId)?.sendState)
        }
    }

    @Test
    fun recoverInterruptedSendsDoesNotAffectSentOrFailedItems() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)

        withTemporaryImage { imageFile ->
            val sentId = store.enqueue(imageFile, emptyMeta())
            store.markSending(sentId)
            store.markSent(sentId)

            val failedId = store.enqueue(imageFile, emptyMeta())
            store.markSending(failedId)
            store.markFailed(failedId, "network error")

            store.recoverInterruptedSends()

            assertEquals(SendState.SENT, dao.findById(sentId)?.sendState)
            assertEquals(SendState.FAILED, dao.findById(failedId)?.sendState)
        }
    }

    private suspend fun withTemporaryImage(block: suspend (File) -> Unit) {
        val imageFile = File.createTempFile("queue-store-test-", ".jpg")
        try {
            block(imageFile)
        } finally {
            imageFile.delete()
        }
    }

    private fun emptyMeta() = CaptureMeta(
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
    )
}
