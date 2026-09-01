package jp.sotuken.metercapture.queue.sender

import jp.sotuken.metercapture.queue.QueueItem

interface Sender {
    suspend fun send(item: QueueItem): Result<Unit>
}

