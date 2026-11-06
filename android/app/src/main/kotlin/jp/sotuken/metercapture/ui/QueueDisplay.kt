package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import jp.sotuken.metercapture.queue.isHeldFor

/** 履歴画面に出す送信状態の文言。送信箱（folder）への保存は PC 未到着として区別する。 */
internal fun sendStatusLabel(item: QueueItem, currentReceiverId: String? = null): String =
    if (item.isHeldFor(currentReceiverId)) "別のPC宛て(保留)" else when (item.sendState) {
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

/** PC 未到着の件数の表示文言。0 件なら null（表示しない）。 */
internal fun undeliveredSummary(items: List<QueueItem>): String? {
    val count = undeliveredCount(items)
    return if (count > 0) "PC未到着: ${count}件（端末に保存済み）" else null
}

/** 行に出すエラー文言。失敗または送信箱滞留で、lastError が空でないときだけ返す。 */
internal fun errorTextFor(item: QueueItem): String? {
    if (item.sendState != SendState.FAILED && !isUndelivered(item)) return null
    return item.lastError?.takeIf { it.isNotBlank() }
}

/** 「再送」ボタンを出す項目か。 */
internal fun canRetry(item: QueueItem, currentReceiverId: String? = null): Boolean =
    item.sendState == SendState.FAILED && !item.isHeldFor(currentReceiverId)
