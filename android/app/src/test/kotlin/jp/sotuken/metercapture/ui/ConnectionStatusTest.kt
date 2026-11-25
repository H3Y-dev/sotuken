package jp.sotuken.metercapture.ui

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.time.Instant
import java.time.ZoneId
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ConnectionStatusTest {
    private val tokyo = ZoneId.of("Asia/Tokyo")

    private fun item(
        id: String,
        state: SendState,
        via: String? = null,
        sentAt: String? = null,
        lastError: String? = null,
        capturedAt: String = "2026-11-05T00:00:00Z",
    ): QueueItem = QueueItem(
        localId = id,
        imagePath = "/tmp/$id.jpg",
        capturedAt = capturedAt,
        deviceName = null,
        operatorValue = null,
        operatorNote = null,
        sendState = state,
        retryCount = 0,
        lastError = lastError,
        sentAt = sentAt,
        sentVia = via,
    )

    @Test
    fun buildConnectionDetailFormatsAllFieldsAndNormalizesFailure() {
        val items = listOf(
            item("sent", SendState.SENT, via = QueueItem.VIA_HTTP, sentAt = "2026-11-05T03:00:00Z"),
            item("failed", SendState.FAILED, lastError = "PC未接続: Health check failed with HTTP 401: x", capturedAt = "2026-11-05T02:00:00Z"),
        )
        val detail = buildConnectionDetail(ConnectionBarState.CONNECTED, "", "http://192.168.1.20:8765", items, 2, tokyo)
        assertEquals("接続の結果：接続中", detail.resultLine)
        assertEquals("PCのURL：http://192.168.1.20:8765", detail.urlLine)
        assertEquals("最終送信：12:00", detail.lastSentLine)
        assertEquals("未着：2枚", detail.undeliveredLine)
        assertEquals("直近の失敗理由：合言葉が違います", detail.lastFailureLine)
        val empty = buildConnectionDetail(ConnectionBarState.NOT_CONFIGURED, "", null, emptyList(), 0, tokyo)
        assertEquals("接続の結果：未設定", empty.resultLine)
        assertEquals("PCのURL：未設定", empty.urlLine)
        assertEquals("最終送信：なし", empty.lastSentLine)
        assertEquals("未着：0枚", empty.undeliveredLine)
        assertEquals("直近の失敗理由：なし", empty.lastFailureLine)
    }

    @Test
    fun buildConnectionDetailPicksLatestFailureByInstantAndHandlesBrokenTime() {
        val old = item("old", SendState.FAILED, lastError = "PC未接続: 接続できません", capturedAt = "2026-11-05T01:00:00Z")
        val broken = item("broken", SendState.FAILED, lastError = "HTTP失敗: HTTP 400: bad", capturedAt = "zzz-broken")
        val latest = item("latest", SendState.FAILED, lastError = "PC未接続: Health check failed with HTTP 401: x", capturedAt = "2026-11-05T02:00:00Z")
        assertEquals("直近の失敗理由：合言葉が違います", buildConnectionDetail(ConnectionBarState.CONNECTED, "", null, listOf(old, broken, latest), 3, tokyo).lastFailureLine)
        val onlyBroken = item("only", SendState.FAILED, lastError = "PC未接続: 接続できません", capturedAt = "broken")
        assertEquals("直近の失敗理由：接続できません", buildConnectionDetail(ConnectionBarState.CONNECTED, "", null, listOf(onlyBroken), 1, tokyo).lastFailureLine)
    }

    @Test
    fun connectionErrorsAreClassifiedAsCannotConnect() {
        assertEquals("接続できません", classifyHealthFailure(ConnectException("refused")))
        assertEquals("接続できません", classifyHealthFailure(SocketTimeoutException("timeout")))
        assertEquals("接続できません", classifyHealthFailure(UnknownHostException("host")))
    }

    @Test
    fun http401IsWrongToken() {
        val error = IOException("Health check failed with HTTP 401: x")
        assertEquals("合言葉が違います", classifyHealthFailure(error))
    }

    @Test
    fun http400IsWrongFormat() {
        val error = IOException("Health check failed with HTTP 400: x")
        assertEquals("送信先の形式が違います", classifyHealthFailure(error))
    }

    @Test
    fun otherErrorsAreNoResponse() {
        assertEquals("応答がありません", classifyHealthFailure(IOException("Health check failed with HTTP 500: x")))
        assertEquals("応答がありません", classifyHealthFailure(IOException()))
        assertEquals("応答がありません", classifyHealthFailure(null))
    }

    @Test
    fun barStateFollowsConfigurationAndHealth() {
        assertEquals(ConnectionBarState.NOT_CONFIGURED, connectionBarState(false, true))
        assertEquals(ConnectionBarState.CHECKING, connectionBarState(true, null))
        assertEquals(ConnectionBarState.CONNECTED, connectionBarState(true, true))
        assertEquals(ConnectionBarState.UNREACHABLE, connectionBarState(true, false))
    }

    @Test
    fun undeliveredCountsPendingSendingFailedAndFolderSent() {
        val items = listOf(
            item("1", SendState.PENDING),
            item("2", SendState.SENDING),
            item("3", SendState.FAILED),
            item("4", SendState.SENT, via = QueueItem.VIA_FOLDER),
            item("5", SendState.SENT, via = QueueItem.VIA_HTTP),
        )
        assertEquals(4, countUndelivered(items))
    }

    @Test
    fun undeliveredIsZeroForEmptyList() {
        assertEquals(0, countUndelivered(emptyList()))
    }

    @Test
    fun latestHttpSentAtPicksNewestHttpItemOnly() {
        val items = listOf(
            item("1", SendState.SENT, QueueItem.VIA_HTTP, "2026-11-05T01:00:00Z"),
            item("2", SendState.SENT, QueueItem.VIA_HTTP, "2026-11-05T03:00:00Z"),
            item("3", SendState.SENT, QueueItem.VIA_FOLDER, "2026-11-05T09:00:00Z"),
        )
        assertEquals(Instant.parse("2026-11-05T03:00:00Z"), latestHttpSentAt(items))
    }

    @Test
    fun latestHttpSentAtIsNullWhenNoneOrUnreadable() {
        assertNull(latestHttpSentAt(emptyList()))
        val broken = listOf(item("1", SendState.SENT, QueueItem.VIA_HTTP, "broken"))
        assertNull(latestHttpSentAt(broken))
    }

    @Test
    fun formatHHmmHandlesDayBoundary() {
        assertEquals("23:59", formatHHmm(Instant.parse("2026-11-05T14:59:59Z"), tokyo))
        assertEquals("00:00", formatHHmm(Instant.parse("2026-11-05T15:00:00Z"), tokyo))
        assertEquals("なし", formatHHmm(null, tokyo))
    }

    @Test
    fun barTextMatchesDesignWording() {
        assertEquals(
            "■ 送信先が未設定です（タップして設定）",
            connectionBarText(ConnectionBarState.NOT_CONFIGURED, 0, "なし", ""),
        )
        assertEquals(
            "◎ PCとの接続を確認中",
            connectionBarText(ConnectionBarState.CHECKING, 0, "なし", ""),
        )
        assertEquals(
            "● PCに接続中　未着 3枚　最終送信 12:34",
            connectionBarText(ConnectionBarState.CONNECTED, 3, "12:34", ""),
        )
        assertEquals(
            "▲ PCにつながりません（端末に保存中）　未着 2枚　接続できません",
            connectionBarText(ConnectionBarState.UNREACHABLE, 2, "なし", "接続できません"),
        )
    }
    
    @Test
    fun resultLabelShowsReasonOnlyWhenUnreachable() {
        assertEquals("未設定", connectionResultLabel(ConnectionBarState.NOT_CONFIGURED, ""))
        assertEquals("確認中", connectionResultLabel(ConnectionBarState.CHECKING, ""))
        assertEquals("接続中", connectionResultLabel(ConnectionBarState.CONNECTED, ""))
        assertEquals(
            "つながりません（接続できません）",
            connectionResultLabel(ConnectionBarState.UNREACHABLE, "接続できません"),
        )
    }

    
        @Test
    fun http403IsWrongToken() {
        val error = IOException("Health check failed with HTTP 403: x")
        assertEquals("合言葉が違います", classifyHealthFailure(error))
    }

    @Test
    fun http404StaysNoResponse() {
        val error = IOException("Health check failed with HTTP 404: x")
        assertEquals("応答がありません", classifyHealthFailure(error))
    }

    @Test
    fun barTextDistinguishesHasOutboxFromPendingOnly() {
        assertEquals(
            "▲ PCにつながりません（端末に保存中）　未着 2枚　接続できません",
            connectionBarText(ConnectionBarState.UNREACHABLE, 2, "なし", "接続できません", hasOutbox = true),
        )
        assertEquals(
            "▲ PCにつながりません（送信待ち）　未着 2枚　接続できません",
            connectionBarText(ConnectionBarState.UNREACHABLE, 2, "なし", "接続できません", hasOutbox = false),
        )
    }

    @Test
    fun countUndeliveredExcludesNonSendablePhotos() {
        val items = listOf(
            item("1", SendState.PENDING),
            item("2", SendState.SENT, via = QueueItem.VIA_FOLDER),
            item("3", SendState.PENDING),
        )
        assertEquals(3, countUndelivered(items))
        assertEquals(2, countUndelivered(items, isSendable = { it.localId != "3" }))
    }
}
