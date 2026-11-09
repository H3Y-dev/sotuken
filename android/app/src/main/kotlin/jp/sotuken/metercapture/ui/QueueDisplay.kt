package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import jp.sotuken.metercapture.queue.isHeldFor

/** 履歴画面に出す送信状態の文言。送信箱（folder）への保存は PC 未到着として区別する。点検作業中の写真は意図的に保留。 */
internal fun sendStatusLabel(
    item: QueueItem,
    currentReceiverId: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
): String =
    if (item.isHeldFor(currentReceiverId)) {
        "別のPC宛て(保留)"
    } else if (!isSendable(item)) {
        "点検中(完了すると送信します)"
    } else when (item.sendState) {
        SendState.PENDING -> "未送信"
        SendState.SENDING -> "送信中"
        SendState.SENT -> when (item.sentVia) {
            QueueItem.VIA_FOLDER -> "PC未到着・端末に保存済み"
            QueueItem.VIA_HTTP -> "PC受信済み"
            else -> "送信済み"
        }
        SendState.FAILED -> "失敗"
    }

/** 送信箱に保存しただけで、PC にはまだ届いていない項目か。 */
internal fun isUndelivered(item: QueueItem): Boolean =
    item.sendState == SendState.SENT && item.sentVia == QueueItem.VIA_FOLDER

internal fun undeliveredCount(items: List<QueueItem>): Int = items.count(::isUndelivered)

/** PC 未到着・未送信の件数の表示文言。0 件なら null（表示しない）。 */
internal fun undeliveredSummary(
    items: List<QueueItem>,
    currentReceiverId: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
): String? {
    val sendableItems = items.filter { isSendable(it) && !it.isHeldFor(currentReceiverId) }
    val pendingCount = sendableItems.count { it.sendState == SendState.PENDING }
    val folderCount = sendableItems.count(::isUndelivered)
    val total = pendingCount + folderCount
    if (total == 0) return null
    return if (pendingCount > 0) {
        "未送信: ${total}件（端末に保存済み）"
    } else {
        "PC未到着: ${total}件（端末に保存済み）"
    }
}

/** 行に出すエラー文言。失敗または送信箱滞留で、lastError が空でないとき、または未送信でPCに届かないときに返す。 */
internal fun errorTextFor(
    item: QueueItem,
    connectionUnreachable: Boolean = false,
    connectionReason: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
    currentReceiverId: String? = null,
): String? {
    if (item.isHeldFor(currentReceiverId)) return null
    if (!isSendable(item)) return null

    if (item.sendState == SendState.FAILED || isUndelivered(item)) {
        return item.lastError?.takeIf { it.isNotBlank() }
    }

    if (item.sendState == SendState.PENDING && connectionUnreachable) {
        val detail = item.lastError?.takeIf { it.isNotBlank() }
            ?: connectionReason?.takeIf { it.isNotBlank() }
        return if (!detail.isNullOrBlank()) {
            val clean = detail.removePrefix("PC未接続: ").removePrefix("PC未接続：").trim()
            if (clean.startsWith("PCに届いていません")) clean
            else "PCに届いていません。$clean"
        } else {
            "PCに届いていません"
        }
    }

    return null
}

/** 「再送」ボタンを出す項目か。 */
internal fun canRetry(
    item: QueueItem,
    currentReceiverId: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
): Boolean =
    item.sendState == SendState.FAILED && !item.isHeldFor(currentReceiverId) && isSendable(item)

internal fun canDelete(item: QueueItem): Boolean = item.sendState != SendState.SENDING

internal fun deleteConfirmationText(item: QueueItem, currentReceiverId: String? = null): String =
    if (item.sendState == SendState.SENT && !item.isHeldFor(currentReceiverId)) {
        "端末内の写真を削除します。PCに届いた記録は消えません。"
    } else {
        "この写真を削除します。まだPCに届いていないため、削除するとPCには送られません。"
    }
