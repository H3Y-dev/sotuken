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
}

