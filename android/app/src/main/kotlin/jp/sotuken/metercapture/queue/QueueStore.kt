package jp.sotuken.metercapture.queue

import java.io.File
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow

/**
 * ui/ と queue/ の境界。ここにある2関数だけを他領域へ公開する。
 */
interface QueueStore {
    suspend fun enqueue(imageFile: File, meta: CaptureMeta): String
    fun observeQueue(): Flow<List<QueueItem>>
    suspend fun markSending(localId: String)
    suspend fun markSent(localId: String)
    suspend fun markFailed(localId: String, error: String)
    suspend fun retry(localId: String)

    // アプリが送信中にクラッシュ・強制終了すると SENDING のまま残る項目がある。
    // 実際には送信されていない前提で、次回起動時に PENDING へ戻して再送させる。
    suspend fun recoverInterruptedSends()
}

class RoomQueueStore(
    private val queueDao: QueueDao,
) : QueueStore {
    override suspend fun enqueue(imageFile: File, meta: CaptureMeta): String {
        val localId = UUID.randomUUID().toString()
        queueDao.insert(
            QueueItem(
                localId = localId,
                imagePath = imageFile.absolutePath,
                capturedAt = Instant.now().toString(),
                deviceName = meta.deviceName,
                operatorValue = meta.operatorValue,
                operatorNote = meta.operatorNote,
                sendState = SendState.PENDING,
                retryCount = 0,
                lastError = null,
                sentAt = null,
            ),
        )
        return localId
    }

    override fun observeQueue(): Flow<List<QueueItem>> = queueDao.observeAll()

    override suspend fun markSending(localId: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.PENDING) {
            "cannot mark sending from state ${item.sendState}"
        }
        queueDao.update(item.copy(sendState = SendState.SENDING))
    }

    override suspend fun markSent(localId: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.SENDING) {
            "cannot mark sent from state ${item.sendState}"
        }
        queueDao.update(
            item.copy(sendState = SendState.SENT, sentAt = Instant.now().toString(), lastError = null),
        )
    }

    override suspend fun markFailed(localId: String, error: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.SENDING) {
            "cannot mark failed from state ${item.sendState}"
        }
        queueDao.update(
            item.copy(sendState = SendState.FAILED, lastError = error, retryCount = item.retryCount + 1),
        )
    }

    override suspend fun retry(localId: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.FAILED) {
            "cannot retry from state ${item.sendState}"
        }
        queueDao.update(item.copy(sendState = SendState.PENDING, lastError = null))
    }

    override suspend fun recoverInterruptedSends() {
        queueDao.resetState(from = SendState.SENDING, to = SendState.PENDING)
    }

    private suspend fun requireItem(localId: String): QueueItem =
        requireNotNull(queueDao.findById(localId)) { "QueueItem with localId $localId not found" }
}

