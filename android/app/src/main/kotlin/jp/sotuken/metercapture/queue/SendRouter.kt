package jp.sotuken.metercapture.queue

import java.io.File
import jp.sotuken.metercapture.queue.sender.FolderSender
import jp.sotuken.metercapture.queue.sender.Sender
import jp.sotuken.metercapture.queue.sender.SenderPayloads

/**
 * 送信Workerのルーティングロジック。
 * 外部依存（Senderや疎通確認関数）を注入可能にし、JVM単体テストを容易にします。
 */
class SendRouter(
    private val queueDao: QueueDao,
    private val queueStore: QueueStore,
    private val outboxDir: File,
    private val httpSenderProvider: () -> Sender?,
    private val healthChecker: suspend () -> Boolean,
    private val folderSender: Sender = FolderSender(outboxDir),
) {

    suspend fun route() {
        // 1. 中断された送信中アイテムをPENDINGへ復元
        queueStore.recoverInterruptedSends()

        // 疎通確認
        val httpSender = httpSenderProvider()
        val isHttpReachable = httpSender != null && healthChecker()

        // 今回HTTPに失敗して送信箱へ回した項目を、その場でもう一度送らない。
        val sentFolderItems = if (isHttpReachable) {
            queueDao.findByState(SendState.SENT).filter { it.sentVia == QueueItem.VIA_FOLDER }
        } else {
            emptyList()
        }

        // 2. PENDING項目を古い順に取得
        val pendingItems = queueDao.findByState(SendState.PENDING)

        for (item in pendingItems) {
            queueStore.markSending(item.localId)
            var sentViaHttp = false

            // 3. 送信先が設定済みでGET /healthが通ればHTTP送信を試みる
            if (isHttpReachable) {
                val httpResult = requireNotNull(httpSender).send(item)
                if (httpResult.isSuccess) {
                    queueStore.markSent(item.localId, QueueItem.VIA_HTTP)
                    sentViaHttp = true
                }
            }

            // 4. 受信口に届かない、またはHTTP送信に失敗した場合は送信箱（FolderSender）へ
            if (!sentViaHttp) {
                val folderResult = folderSender.send(item)
                if (folderResult.isSuccess) {
                    queueStore.markSent(item.localId, QueueItem.VIA_FOLDER)
                } else {
                    val error = folderResult.exceptionOrNull()?.message ?: "Folder sender failed"
                    queueStore.markFailed(item.localId, error)
                }
            }
        }

        // 5. 送信箱に残っている項目の追い送り（catch-up）
        // via = FOLDER かつ 送信箱のファイルが残っている項目を、受信口に届くならHTTPで再送
        if (isHttpReachable) {
            val nonNullHttpSender = requireNotNull(httpSender)
            for (item in sentFolderItems) {
                val baseName = SenderPayloads.buildBaseName(item)
                val ext = File(item.imagePath).extension.ifBlank { "jpg" }
                val jsonFile = File(outboxDir, "$baseName.json")
                val imageFile = File(outboxDir, "$baseName.$ext")

                if (jsonFile.exists() || imageFile.exists()) {
                    val httpResult = nonNullHttpSender.send(item)
                    if (httpResult.isSuccess) {
                        for (file in listOf(jsonFile, imageFile,
                            File(outboxDir, "$baseName.json.part"), File(outboxDir, "$baseName.$ext.part"))) {
                            check(!file.exists() || file.delete()) { "Failed to delete outbox file: $file" }
                        }
                        queueStore.updateSentVia(item.localId, QueueItem.VIA_HTTP)
                    }
                }
            }
        }
    }
}
