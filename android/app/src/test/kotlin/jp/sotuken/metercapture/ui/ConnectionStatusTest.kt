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
    ): QueueItem = QueueItem(
        localId = id,
        imagePath = "/tmp/$id.jpg",
        capturedAt = "2026-11-05T00:00:00Z",
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
            "▲ 送信先が未設定です（タップして設定）",
            connectionBarText(ConnectionBarState.NOT_CONFIGURED, 0, "なし", ""),
        )
        assertEquals(
            "… PCとの接続を確認中",
            connectionBarText(ConnectionBarState.CHECKING, 0, "なし", ""),
        )
        assertEquals(
            "● PCに接続中　未着 3件　最終送信 12:34",
            connectionBarText(ConnectionBarState.CONNECTED, 3, "12:34", ""),
        )
        assertEquals(
            "○ PCに届かない（送信箱に保存中）　未着 2件　接続できません",
            connectionBarText(ConnectionBarState.UNREACHABLE, 2, "なし", "接続できません"),
        )
    }
    
    @Test
    fun resultLabelShowsReasonOnlyWhenUnreachable() {
        assertEquals("未設定", connectionResultLabel(ConnectionBarState.NOT_CONFIGURED, ""))
        assertEquals("確認中", connectionResultLabel(ConnectionBarState.CHECKING, ""))
        assertEquals("接続中", connectionResultLabel(ConnectionBarState.CONNECTED, ""))
        assertEquals(
            "届かない（接続できません）",
            connectionResultLabel(ConnectionBarState.UNREACHABLE, "接続できません"),
        )
    }

    @Test
    fun folderReasonLabelOnlyForFolderSentWithError() {
        val withError = item(
            "1", SendState.SENT, QueueItem.VIA_FOLDER,
            lastError = "PC未接続: failed to connect to /192.168.1.20",
        )
        assertEquals("PCに届かず、送信箱に保存: 接続できません", folderReasonLabel(withError))

        val notConfigured = item("2", SendState.SENT, QueueItem.VIA_FOLDER, lastError = "送信先未設定")
        assertEquals("PCに届かず、送信箱に保存: 送信先が未設定です", folderReasonLabel(notConfigured))

        val noError = item("3", SendState.SENT, QueueItem.VIA_FOLDER)
        assertNull(folderReasonLabel(noError))

        val viaHttp = item("4", SendState.SENT, QueueItem.VIA_HTTP, lastError = "x")
        assertNull(folderReasonLabel(viaHttp))

        val failed = item("5", SendState.FAILED, lastError = "x")
        assertNull(folderReasonLabel(failed))
    }
    
}