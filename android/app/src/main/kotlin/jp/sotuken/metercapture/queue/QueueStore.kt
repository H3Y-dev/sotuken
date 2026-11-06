package jp.sotuken.metercapture.queue

import java.io.File
import java.time.Instant
import java.util.UUID
import java.util.logging.Logger
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

internal val queueSendMutex = Mutex()

enum class DeleteResult { DELETED, SENDING, NOT_FOUND }

/**
 * ui/ と queue/ の境界。ここにある2関数だけを他領域へ公開する。
 */
interface QueueStore {
    suspend fun enqueue(imageFile: File, meta: CaptureMeta): String
    suspend fun delete(localId: String): DeleteResult
    fun observeQueue(): Flow<List<QueueItem>>
    suspend fun markSending(localId: String)
    suspend fun markSent(localId: String, via: String, note: String? = null)
    suspend fun markFailed(localId: String, error: String)
    suspend fun reassignReceiver(localId: String, receiverId: String?)
    suspend fun retry(localId: String)
    suspend fun updateSentVia(localId: String, via: String)
    suspend fun updateLastError(localId: String, error: String?)

    // アプリが送信中にクラッシュ・強制終了すると SENDING のまま残る項目がある。
    // 実際には送信されていない前提で、次回起動時に PENDING へ戻して再送させる。
    suspend fun recoverInterruptedSends()
}

class RoomQueueStore(
    private val queueDao: QueueDao,
    private val outboxDir: File? = null,
    private val receiverIdProvider: () -> String? = { null },
) : QueueStore {
    override suspend fun delete(localId: String): DeleteResult = withContext(Dispatchers.IO) {
        if (queueDao.findById(localId)?.sendState == SendState.SENDING) {
            return@withContext DeleteResult.SENDING
        }
        // Workerの取得済み一覧とファイル送信にも衝突しないよう、送信全体と直列化する。
        queueSendMutex.withLock {
            val item = queueDao.findById(localId) ?: return@withLock DeleteResult.NOT_FOUND
            if (item.sendState == SendState.SENDING) return@withLock DeleteResult.SENDING
            queueDao.delete(item)
            val image = File(item.imagePath)
            val files = mutableListOf<File>()
            if (queueDao.observeAll().first().none { it.imagePath == item.imagePath }) files.add(image)
            outboxDir?.let { directory ->
                val base = SenderPayloads.buildBaseName(item)
                val extension = image.extension.ifBlank { "jpg" }
                files.addAll(listOf(
                    File(directory, "$base.json"), File(directory, "$base.$extension"),
                    File(directory, "$base.json.part"), File(directory, "$base.$extension.part"),
                ))
            }
            for (file in files) {
                try {
                    if (file.exists() && !file.delete()) {
                        Logger.getLogger("QueueStore").warning("Failed to delete file: $file")
                    }
                } catch (error: SecurityException) {
                    Logger.getLogger("QueueStore").warning("Failed to delete file: $file: $error")
                }
            }
            DeleteResult.DELETED
        }
    }

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
                sentVia = null,
                receiverId = receiverIdProvider()?.takeIf { it.isNotBlank() },
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

    override suspend fun markSent(localId: String, via: String, note: String?) {
        val item = requireItem(localId)
        check(item.sendState == SendState.SENDING) {
            "cannot mark sent from state ${item.sendState}"
        }
        queueDao.update(
            item.copy(
                sendState = SendState.SENT,
                sentAt = Instant.now().toString(),
                sentVia = via,
                lastError = note,
            ),
        )
    }

    override suspend fun markFailed(localId: String, error: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.SENDING ||
            (item.sendState == SendState.SENT && item.sentVia == QueueItem.VIA_FOLDER)) {
            "cannot mark failed from state ${item.sendState}"
        }
        queueDao.update(
            item.copy(sendState = SendState.FAILED, lastError = error, retryCount = item.retryCount + 1),
        )
    }

    override suspend fun reassignReceiver(localId: String, receiverId: String?) {
        val item = requireItem(localId)
        check(item.isHeldFor(receiverId?.takeIf { it.isNotBlank() }))
        val state = if (item.sentVia == QueueItem.VIA_FOLDER) SendState.SENT else SendState.PENDING
        queueDao.update(item.copy(receiverId = receiverId?.takeIf { it.isNotBlank() },
            sendState = state, lastError = null))
    }

    override suspend fun retry(localId: String) {
        val item = requireItem(localId)
        check(item.sendState == SendState.FAILED) {
            "cannot retry from state ${item.sendState}"
        }
        queueDao.update(item.copy(sendState = SendState.PENDING, lastError = null))
    }

    override suspend fun updateSentVia(localId: String, via: String) {
        val item = requireItem(localId)
        queueDao.update(item.copy(sentVia = via, lastError = null))
    }

    override suspend fun updateLastError(localId: String, error: String?) {
        val item = requireItem(localId)
        queueDao.update(item.copy(lastError = error))
    }

    override suspend fun recoverInterruptedSends() {
        queueDao.resetState(from = SendState.SENDING, to = SendState.PENDING)
    }

    private suspend fun requireItem(localId: String): QueueItem =
        requireNotNull(queueDao.findById(localId)) { "QueueItem with localId $localId not found" }
}
