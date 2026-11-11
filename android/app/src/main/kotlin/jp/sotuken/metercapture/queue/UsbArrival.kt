package jp.sotuken.metercapture.queue

import java.io.File
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

// QueueStore.delete と同じ画像・JSON・書き込み途中の2ファイルをすべて確認する。
internal fun isUsbArrival(item: QueueItem, outboxFilesExist: List<Boolean>): Boolean =
    item.sendState == SendState.SENT && item.sentVia == QueueItem.VIA_FOLDER &&
        outboxFilesExist.size == 4 && outboxFilesExist.none { it }

suspend fun QueueStore.refreshUsbArrivals(outboxDir: File) = withContext(Dispatchers.IO) {
    queueSendMutex.withLock { reconcileUsbArrivals(outboxDir) }
}

// Worker は送信全体で queueSendMutex を取得済み。
internal suspend fun QueueStore.reconcileUsbArrivals(outboxDir: File) {
    // 外部ストレージを読めないときは、ファイルの消失とは判断しない。
    if (!outboxDir.isDirectory || !outboxDir.canRead()) return
    for (item in observeQueue().first()) {
        if (item.sendState != SendState.SENT || item.sentVia != QueueItem.VIA_FOLDER) continue
        val base = SenderPayloads.buildBaseName(item)
        val ext = File(item.imagePath).extension.ifBlank { "jpg" }
        val files = listOf("$base.json", "$base.$ext", "$base.json.part", "$base.$ext.part")
        if (isUsbArrival(item, files.map { File(outboxDir, it).exists() })) {
            updateSentVia(item.localId, QueueItem.VIA_USB)
        }
    }
}
