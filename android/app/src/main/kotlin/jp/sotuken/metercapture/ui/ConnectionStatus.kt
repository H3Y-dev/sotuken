package jp.sotuken.metercapture.ui

import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.hasArrived
import jp.sotuken.metercapture.queue.SendState

enum class ConnectionBarState {
    NOT_CONFIGURED,
    CHECKING,
    CONNECTED,
    UNREACHABLE,
}

/** healthOk: null = まだ結果なし、true = 成功、false = 失敗。 */
fun connectionBarState(configured: Boolean, healthOk: Boolean?): ConnectionBarState = when {
    !configured -> ConnectionBarState.NOT_CONFIGURED
    healthOk == null -> ConnectionBarState.CHECKING
    healthOk -> ConnectionBarState.CONNECTED
    else -> ConnectionBarState.UNREACHABLE
}

/** health失敗のThrowableから、帯に出す短い理由を作る。 */
fun classifyHealthFailure(error: Throwable?): String = when (error) {
    is ConnectException, is SocketTimeoutException, is UnknownHostException -> "接続できません"
    else -> classifyFailureMessage(error?.message)
}

private val CONNECT_HINTS = listOf(
    "failed to connect",
    "unable to resolve host",
    "timed out",
    "ConnectException",
    "SocketTimeoutException",
    "UnknownHostException",
)

/** メッセージ（文字列）から短い理由を作る。lastErrorの分類にも使う。 */
fun classifyFailureMessage(message: String?): String = when {
    message.isNullOrBlank() -> "応答がありません"
    message.contains("HTTP 401") || message.contains("HTTP 403") -> "合言葉が違います"
    message.contains("HTTP 400") -> "送信先の形式が違います"
    CONNECT_HINTS.any { message.contains(it, ignoreCase = true) } -> "接続できません"
    else -> "応答がありません"
}

/** 未着 = PENDING・SENDING・FAILED + (SENTかつ送信箱経由)。点検中の写真は対象外にできる。 */
fun countUndelivered(items: List<QueueItem>, isSendable: (QueueItem) -> Boolean = { true }): Int = items.count { item ->
    if (!isSendable(item)) return@count false
    when (item.sendState) {
        SendState.PENDING, SendState.SENDING, SendState.FAILED -> true
        SendState.SENT -> item.sentVia == QueueItem.VIA_FOLDER
    }
}

/** 到着済み項目のsentAtの最新。USBは送信箱への保存時刻。読めない値は無視する。 */
fun latestHttpSentAt(items: List<QueueItem>): Instant? = items
    .filter { it.hasArrived() }
    .mapNotNull { item -> runCatching { Instant.parse(item.sentAt) }.getOrNull() }
    .maxOrNull()

fun formatHHmm(instant: Instant?, zone: ZoneId = ZoneId.systemDefault()): String =
    if (instant == null) {
        "なし"
    } else {
        DateTimeFormatter.ofPattern("HH:mm").withZone(zone).format(instant)
    }

fun connectionBarText(
    state: ConnectionBarState,
    undelivered: Int,
    lastSent: String,
    reason: String,
    hasOutbox: Boolean = true,
): String = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> "▲ 送信先が未設定です（タップして設定）"
    ConnectionBarState.CHECKING -> "… PCとの接続を確認中"
    ConnectionBarState.CONNECTED -> "● PCに接続中　未着 ${undelivered}件　最終送信 $lastSent"
    ConnectionBarState.UNREACHABLE -> {
        val savingLabel = if (hasOutbox) "（送信箱に保存中）" else "（送信待ち）"
        "○ PCに届かない${savingLabel}　未着 ${undelivered}件　$reason"
    }
}


fun connectionResultLabel(state: ConnectionBarState, reason: String): String = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> "未設定"
    ConnectionBarState.CHECKING -> "確認中"
    ConnectionBarState.CONNECTED -> "接続中"
    ConnectionBarState.UNREACHABLE -> "届かない（$reason）"
}
