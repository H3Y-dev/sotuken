package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.ui.NetworkSnapshot
import jp.sotuken.metercapture.ui.components.GaugeKind
import org.junit.Assert.*
import org.junit.Test

class SendStatusUiStateTest {
    @Test fun incompleteBadgeAndMissingRowAreWarn() {
        val sent = photo.copy(deviceId = "A-1", sendState = SendState.SENT, sentVia = QueueItem.VIA_HTTP)
        val missing = build(inspection.copy(state = InspectionState.SENT_INCOMPLETE, pcMissingFileNames = "[\"${SenderPayloads.buildImageFileName(sent)}\"]"), listOf(sent))
        assertEquals(GaugeKind.WARN, missing.badgeKind)
        assertEquals("未着あり 1枚", missing.badge)
        assertEquals(GaugeKind.WARN, missing.rows.single().kind)
        assertEquals("PCに未着", missing.rows.single().status)
        assertEquals("PCで写真が見つかりません", missing.rows.single().reason)
        val complete = build(inspection.copy(state = InspectionState.SENT), listOf(sent))
        assertEquals(GaugeKind.OK, complete.badgeKind)
        assertEquals("送信済み", complete.badge)
        assertEquals(GaugeKind.OK, complete.rows.single().kind)
        assertNull(complete.rows.single().reason)
    }

    @Test fun pendingOmitsReasonWhileFailedAndOutboxShowReason() {
        val pending = build(photos = listOf(photo.copy(lastError = "PC未接続: 接続できません"))).rows.single()
        assertEquals(GaugeKind.WAIT, pending.kind)
        assertEquals("未送信", pending.status)
        assertNull(pending.reason)
        val outbox = build(photos = listOf(photo.copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_FOLDER, lastError = "PC未接続: 接続できません"))).rows.single()
        assertEquals(GaugeKind.WAIT, outbox.kind)
        assertEquals("PCに未着（端末に保存済み）", outbox.status)
        assertEquals("接続できません", outbox.reason)
        val failed = build(inspection.copy(state = InspectionState.SENT_INCOMPLETE), listOf(photo.copy(sendState = SendState.FAILED, lastError = "HTTP失敗: HTTP 409: conflict"))).rows.single()
        assertEquals(GaugeKind.FAIL, failed.kind)
        assertEquals("送信失敗", failed.status)
        assertEquals("PCが写真を受け付けませんでした", failed.reason)
    }
    @Test fun usbArrivalCountsInPhotoProgressAndManifestRetry() {
        val arrived = photo.copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_USB)
        val state = build(inspection.copy(manifestError = "offline"), listOf(arrived))
        assertEquals("到着 1/1枚", state.photoProgress)
        assertTrue(state.showManifestOnlyRetry)
        assertTrue(state.rows.single().status.contains("USB"))
    }

    private val inspection = Inspection("I-1", "点検", "担当", "工場", null, null, null, InspectionState.WAITING, "2026-11-06T00:00:00Z")
    private val photo = QueueItem("a", "/a.jpg", "2026-11-06T01:00:00Z", null, null, null, SendState.PENDING, 0, null, null)
    private val wifi = NetworkSnapshot(true, false, false)
    private fun build(i: Inspection = inspection, photos: List<QueueItem> = listOf(photo), health: HealthView = HealthView(true, wifi)) = buildSendStatusUiState(i, photos, health, "current", "点検PC")
    @Test fun waitingReachable() { val s = build(); assertEquals("まもなく送信します", s.guidance); assertTrue(s.showSendNow) }
    @Test fun waitingWifiButUnreachable() { assertTrue(build(health = HealthView(false, wifi)).guidance!!.startsWith("Wi-Fiには接続していますが")) }
    @Test fun waitingOffline() {
        val s = build(health = HealthView(false, NetworkSnapshot(false, false, false)))
        assertEquals("PCにつながりません。接続の案内を見てください", s.guidance); assertTrue(s.showGuideLink)
    }
    @Test fun sendingProgress() {
        val s = build(inspection.copy(state = InspectionState.SENDING), listOf(photo, photo.copy(localId = "b", sendState = SendState.SENT, sentVia = QueueItem.VIA_HTTP)))
        assertEquals("PCへ送っています", s.headline); assertEquals("到着 1/2枚", s.photoProgress); assertFalse(s.showSendNow)
    }
    @Test fun sentShowsManifestArrived() {
        val s = build(inspection.copy(state = InspectionState.SENT, manifestSentAt = "2026-11-06T02:00:00Z"), listOf(photo.copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_HTTP)))
        assertEquals("すべてPCに到着しました", s.headline); assertTrue(s.manifestLine.contains("写真の一覧：到着")); assertTrue(s.manifestLine.contains("点検PC"))
    }
    @Test fun incompleteShowsRetry() {
        val failed = photo.copy(sendState = SendState.FAILED)
        val s = build(inspection.copy(state = InspectionState.SENT_INCOMPLETE, pcMissingFileNames = "[\"${SenderPayloads.buildImageFileName(failed)}\"]"), listOf(failed))
        assertEquals("1枚がPCに未着です", s.headline); assertTrue(s.showRetryUndelivered)
    }
    @Test fun manifestOnlyRetryWhenPhotosDelivered() {
        val s = build(inspection.copy(manifestError = "失敗"), listOf(photo.copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_HTTP)))
        assertTrue(s.showManifestOnlyRetry); assertFalse(s.showSendNow)
        assertFalse(build(inspection.copy(manifestError = "失敗")).showManifestOnlyRetry)
    }
    @Test fun heldPhotoGuidance() {
        val s = build(photos = listOf(photo.copy(receiverId = "other")))
        assertTrue(s.guidance!!.contains("今のPCへ送り直す")); assertTrue(s.rows.single().heldForOtherPc)
    }
}
