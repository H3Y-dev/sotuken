package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import jp.sotuken.metercapture.queue.isHeldFor
import jp.sotuken.metercapture.ui.components.GaugeKind

internal fun sendStatusKind(item: QueueItem, currentReceiverId: String? = null, isSendable: (QueueItem) -> Boolean = { true }): GaugeKind = when {
    item.isHeldFor(currentReceiverId) -> GaugeKind.WARN
    !isSendable(item) -> GaugeKind.WAIT
    else -> when (item.sendState) {
        SendState.PENDING, SendState.SENDING -> GaugeKind.WAIT
        SendState.SENT -> if (item.sentVia == QueueItem.VIA_FOLDER) GaugeKind.WAIT else GaugeKind.OK
        SendState.FAILED -> GaugeKind.FAIL
    }
}

/** 履歴画面に出す送信状態の文言。端末（folder）への保存は PC に未着として区別する。点検作業中の写真は意図的に保留。 */
internal fun sendStatusLabel(
    item: QueueItem,
    currentReceiverId: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
): String =
    if (item.isHeldFor(currentReceiverId)) {
        "別のPC宛て（保留）"
    } else if (!isSendable(item)) {
        "完了後に送信"
    } else when (item.sendState) {
        SendState.PENDING -> "未送信"
        SendState.SENDING -> "送信中"
        SendState.SENT -> when (item.sentVia) {
            QueueItem.VIA_FOLDER -> "PCに未着（端末に保存済み）"
            QueueItem.VIA_HTTP -> "PCに到着"
            QueueItem.VIA_USB -> "PCに到着（USB）"
            else -> "送信済み"
        }
        SendState.FAILED -> "送信失敗"
    }

/** 端末に保存しただけで、PC にはまだ届いていない項目か。 */
internal fun isUndelivered(item: QueueItem): Boolean =
    item.sendState == SendState.SENT && item.sentVia == QueueItem.VIA_FOLDER

internal fun undeliveredCount(items: List<QueueItem>): Int = items.count(::isUndelivered)

/** PC に未着・未送信の枚数の表示文言。0 枚なら null（表示しない）。 */
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
        "未送信 ${total}枚（端末に保存済み）"
    } else {
        "PCに未着 ${total}枚（端末に保存済み）"
    }
}

/** 保存されている lastError（生の文）を、画面に出す理由の言葉（設計書5.2節の9語）に置き換える。空なら null。 */
internal fun reasonFromLastError(lastError: String?): String? {
    val text = lastError?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    fun after(prefixes: List<String>): String? = prefixes.firstOrNull { text.startsWith(it) }?.let { text.removePrefix(it).trim() }
    // 詳細がすでに理由の言葉なら、そのまま使う（例「PC未接続: 接続できません」。QueueSendWorker.kt:67 が作る。
    // classifyFailureMessage は英語の手がかりしか見ないので、渡すと「応答がありません」に化ける）
    val known = setOf("接続できません", "合言葉が違います", "送信先の形式が違います", "応答がありません")
    fun classify(detail: String) = if (detail in known) detail else classifyFailureMessage(detail)
    if (text.startsWith("送信先未設定")) return "送信先が未設定です"
    after(listOf("PC未接続:", "PC未接続："))?.let { return classify(it) }
    after(listOf("HTTP失敗:", "追い送り失敗:"))?.let { detail ->
        return when {
            detail.contains("Image file does not exist") -> "写真のファイルが見つかりません"
            listOf("HTTP 400", "HTTP 409", "HTTP 413").any { detail.contains(it) } -> "PCが写真を受け付けませんでした"
            else -> classify(detail)
        }
    }
    return "端末への保存に失敗しました"
}

/** 行に出す未着の理由。FAILED と、端末に保存しただけ（SENT＋folder）の写真だけが対象。 */
internal fun undeliveredReason(item: QueueItem): String? =
    if (item.sendState == SendState.FAILED || isUndelivered(item)) reasonFromLastError(item.lastError) else null

/** 行に出す理由。失敗または端末への保存だけの写真で、lastError が空でないとき、または未送信でPCにつながらないときに返す。 */
internal fun errorTextFor(
    item: QueueItem,
    connectionUnreachable: Boolean = false,
    connectionReason: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
    currentReceiverId: String? = null,
): String? {
    if (item.isHeldFor(currentReceiverId)) return null
    if (!isSendable(item)) return null

    if (item.sendState == SendState.FAILED || isUndelivered(item)) return reasonFromLastError(item.lastError)

    if (item.sendState == SendState.PENDING && connectionUnreachable) {
        return reasonFromLastError(item.lastError)
            ?: connectionReason?.takeIf { it.isNotBlank() }
            ?: "接続できません"
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
        "端末内の写真を削除します。PCに到着した記録は消えません。"
    } else {
        "この写真を削除します。まだPCに未着のため、削除するとPCには送られません。"
    }
