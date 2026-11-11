package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.ui.*

data class HealthView(val reachable: Boolean?, val network: NetworkSnapshot)
data class SendRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String, val status: String, val heldForOtherPc: Boolean)
data class SendStatusUiState(
    val badge: String,
    val headline: String,
    val summaryLine: String,
    val photoProgress: String,
    val manifestLine: String,
    val guidance: String?,
    val rows: List<SendRow>,
    val showSendNow: Boolean,
    val showRetryUndelivered: Boolean,
    val showManifestOnlyRetry: Boolean,
    val showGuideLink: Boolean,
)

fun buildSendStatusUiState(inspection: Inspection, photos: List<QueueItem>, health: HealthView, currentReceiverId: String?, pcName: String?): SendStatusUiState {
    val missing = parseMissingFileNames(inspection.pcMissingFileNames).toSet()
    val arrived = photos.count { it.hasArrived() && SenderPayloads.buildImageFileName(it) !in missing }
    val undelivered = photos.filter { it.sendState == SendState.FAILED || SenderPayloads.buildImageFileName(it) in missing }.size
    val waiting = inspection.state == InspectionState.WAITING
    val held = photos.any { it.isHeldFor(currentReceiverId) }
    val offline = networkLabel(health.network) == "未接続"
    val manifestOnly = waiting && photos.all { it.hasArrived() } && inspection.manifestError != null
    val state = inspection.state
    val badge = when (state) {
        InspectionState.SENDING -> "送信中"
        InspectionState.SENT -> "送信済み"
        InspectionState.SENT_INCOMPLETE -> "送信済み（一部失敗あり）"
        else -> "送信待ち"
    }
    val headline = when (state) {
        InspectionState.SENDING -> "PCへ送っています"
        InspectionState.SENT -> "すべてPCに届きました"
        InspectionState.SENT_INCOMPLETE -> "${undelivered}枚が届いていません"
        else -> "点検を完了しました"
    }
    val summary = summarizeInspection(photos, null)
    val destination = if (state == InspectionState.SENT) {
        val time = inspection.manifestSentAt?.let { runCatching { DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(it)) }.getOrNull() }
        "　送信先：${pcName ?: "未設定"}${time?.let { " ・ $it" }.orEmpty()}"
    } else ""
    return SendStatusUiState(badge, headline,
        listOfNotNull(inspection.operatorName, inspection.place).joinToString(" ・ ") + " 写真${photos.size}枚 ・ ${summary.deviceCount}機器",
        if (state == InspectionState.SENT) "写真 $arrived / ${photos.size}枚 到着" else "$arrived / ${photos.size}枚",
        when {
            state == InspectionState.SENT || state == InspectionState.SENT_INCOMPLETE -> "写真の一覧：到着$destination"
            inspection.manifestError != null -> "写真の一覧：送れませんでした（${inspection.manifestError}）"
            else -> "写真の一覧：未送信 残りの写真が届いたら送ります。"
        },
        if (!waiting) null else when {
            held -> "別のPC宛ての写真があります。『今のPCへ送り直す』で送れます"
            health.reachable == true -> "まもなく送信します"
            offline -> "PCにつながりません。接続の案内を見てください"
            else -> "${networkLabel(health.network)}には接続していますが、PCに届きません。PCの受信アプリと接続を確認してください。"
        },
        photos.map { photo -> SendRow(photo, photo.deviceName ?: "機器名なし", photo.deviceId ?: "機器IDなし",
            "${formatInspectionCaptureTime(photo.capturedAt)} 撮影",
            if (SenderPayloads.buildImageFileName(photo) in missing && photo.sendState == SendState.SENT) "PC未到着" else sendStatusLabel(photo, currentReceiverId), photo.isHeldFor(currentReceiverId)) },
        waiting && !manifestOnly, state == InspectionState.SENT_INCOMPLETE, manifestOnly,
        waiting && offline && health.reachable != true,
    )
}

@Composable
fun InspectionSendStatusScreen(state: SendStatusUiState, onSendNow: () -> Unit, onRetryUndelivered: () -> Unit, onReassign: (String) -> Unit, onGuide: () -> Unit, onHome: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(state.badge, style = MaterialTheme.typography.labelLarge)
            Text(state.headline, style = MaterialTheme.typography.headlineSmall)
            Text(state.summaryLine)
            Text(state.photoProgress)
            Text(state.manifestLine)
            state.guidance?.let { Text(it) }
        }
        items(state.rows, key = { it.item.localId }) { row ->
            OutlinedCard(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Thumbnail(row.item.imagePath, Modifier.size(76.dp))
                    Column(Modifier.weight(1f)) {
                        Text(row.title); Text(row.idLine); Text(row.timeLine); Text(row.status)
                        if (row.heldForOtherPc) TextButton(onClick = { onReassign(row.item.localId) }) { Text("今のPCへ送り直す") }
                    }
                }
            }
        }
        item {
            if (state.showSendNow) Button(onClick = onSendNow, modifier = Modifier.fillMaxWidth()) { Text("今すぐ送る") }
            if (state.showRetryUndelivered) Button(onClick = onRetryUndelivered, modifier = Modifier.fillMaxWidth()) { Text("届いていない写真を再送") }
            if (state.showManifestOnlyRetry) Button(onClick = onSendNow, modifier = Modifier.fillMaxWidth()) { Text("写真の一覧だけ再送") }
            if (state.showGuideLink) TextButton(onClick = onGuide) { Text("接続の案内を見る") }
            TextButton(onClick = onHome) { Text("点検の一覧へ") }
        }
    }
}
