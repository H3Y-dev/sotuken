package jp.sotuken.metercapture.queue.sender

import jp.sotuken.metercapture.queue.QueueItem

class HttpSender : Sender {
    override suspend fun send(item: QueueItem): Result<Unit> {
        // TODO(本人): HTTPでPCへ送る。Sprint 3
        TODO("HTTP送信はSprint 3で実装する")
    }
}

