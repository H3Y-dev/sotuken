package jp.sotuken.metercapture.queue

import java.io.File
import java.io.IOException
import jp.sotuken.metercapture.queue.sender.FolderSender
import jp.sotuken.metercapture.queue.sender.Sender
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.queue.sender.PermanentSendException

/**
 * 送信Workerのルーティングロジック。
 * 外部依存（Senderや疎通確認関数）を注入可能にし、JVM単体テストを容易にします。
 */
class SendRouter(
    private val queueDao: QueueDao,
    private val queueStore: QueueStore,
    private val outboxDir: File,
    private val httpSenderProvider: () -> Sender?,
    private val healthChecker: suspend () -> Result<Unit>,
    private val folderSender: Sender = FolderSender(outboxDir),
    private val currentReceiverId: String? = null,
) {

    private fun reasonOf(e: Throwable?): String =
        e?.message?.takeIf { it.isNotBlank() } ?: e?.javaClass?.simpleName ?: "不明"

    suspend fun route() {
        // 1. 中断された送信中アイテムをPENDINGへ復元
        queueStore.recoverInterruptedSends()

        // 疎通確認
        val httpSender = httpSenderProvider()
        // HTTPを使えない理由。送信箱へ回した項目の lastError に残す。
        var fallbackReason: String? = null
        var isHttpReachable = if (httpSender == null) {
            fallbackReason = "送信先未設定"
            false
        } else {
            val health = healthChecker()
            if (health.isFailure) {
                fallbackReason = "PC未接続: ${reasonOf(health.exceptionOrNull())}"
            }
            health.isSuccess
        }

        // 今回HTTPに失敗して送信箱へ回した項目を、その場でもう一度送らない。
        val sentFolderItems = if (isHttpReachable) {
            queueDao.findByState(SendState.SENT).filter {
                it.sentVia == QueueItem.VIA_FOLDER && !it.isHeldFor(currentReceiverId)
            }
        } else {
            emptyList()
        }

        // 2. PENDING項目を古い順に取得
        val pendingItems = queueDao.findByState(SendState.PENDING)

        for (item in pendingItems) {
            if (item.isHeldFor(currentReceiverId)) continue
            queueStore.markSending(item.localId)
            var sentViaHttp = false
            var note = fallbackReason
            var permanentFailure = false

            // 3. 送信先が設定済みでGET /healthが通ればHTTP送信を試みる
            if (isHttpReachable) {
                val httpResult = requireNotNull(httpSender).send(item)
                if (httpResult.isSuccess) {
                    queueStore.markSent(item.localId, QueueItem.VIA_HTTP)
                    sentViaHttp = true
                } else {
                    val error = httpResult.exceptionOrNull()
                    note = "HTTP失敗: ${reasonOf(error)}"
                    permanentFailure = error is PermanentSendException
                    if (error is IOException) {
                        isHttpReachable = false
                        fallbackReason = note
                    }
                }
            }

            // 4. 受信口に届かない、またはHTTP送信に失敗した場合は送信箱（FolderSender）へ
            if (!sentViaHttp) {
                val folderResult = folderSender.send(item)
                if (folderResult.isSuccess) {
                    if (permanentFailure) {
                        queueStore.markFailed(item.localId, requireNotNull(note))
                    } else {
                        queueStore.markSent(item.localId, QueueItem.VIA_FOLDER, note)
                    }
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
                if (!isHttpReachable) break
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
                    } else {
                        val error = httpResult.exceptionOrNull()
                        val note = "追い送り失敗: ${reasonOf(error)}"
                        if (error is PermanentSendException) {
                            queueStore.markFailed(item.localId, note)
                        } else {
                            queueStore.updateLastError(item.localId, note)
                        }
                        if (error is IOException) isHttpReachable = false
                    }
                }
            }
        }
    }
}
