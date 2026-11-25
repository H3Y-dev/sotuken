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
import jp.sotuken.metercapture.route.parseRouteJson
import jp.sotuken.metercapture.ui.*
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.*

data class HealthView(val reachable: Boolean?, val network: NetworkSnapshot)
data class SendRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String, val status: String, val heldForOtherPc: Boolean, val reason: String? = null, val kind: GaugeKind = GaugeKind.WAIT)
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
    val badgeKind: GaugeKind = GaugeKind.WAIT,
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
    val summary = summarizeInspection(photos, inspection.routeSnapshot?.let { parseRouteJson(it)?.devices })
    val badgeSpec = inspectionBadge(state, summary, undelivered)
    val headline = when (state) {
        InspectionState.SENDING -> "PCへ送っています"
        InspectionState.SENT -> "すべてPCに到着しました"
        InspectionState.SENT_INCOMPLETE -> "${undelivered}枚がPCに未着です"
        else -> "点検を完了しました"
    }
    val destination = if (state == InspectionState.SENT) {
        val time = inspection.manifestSentAt?.let { runCatching { DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(it)) }.getOrNull() }
        "　送信先：${pcName ?: "未設定"}${time?.let { " ・ $it" }.orEmpty()}"
    } else ""
    return SendStatusUiState(badgeSpec.label, headline,
        listOfNotNull(inspection.operatorName, inspection.place).joinToString(" ・ ") + " 写真${photos.size}枚 ・ ${summary.deviceCount}台",
        "到着 $arrived/${photos.size}枚",
        when {
            state == InspectionState.SENT || state == InspectionState.SENT_INCOMPLETE -> "写真の一覧：到着$destination"
            inspection.manifestError == "PCに届かないため、写真の一覧を送れませんでした" -> "写真の一覧：未送信（PCにつながりません）"
            inspection.manifestError != null -> "写真の一覧：送れませんでした（${inspection.manifestError}）"
            else -> "写真の一覧：未送信（写真がすべて到着したら送ります）"
        },
        if (!waiting) null else when {
            held -> "別のPC宛ての写真があります。『今のPCへ送り直す』で送れます"
            health.reachable == true -> "まもなく送信します"
            offline -> "PCにつながりません。接続の案内を見てください"
            else -> "${networkLabel(health.network)}には接続していますが、PCにつながりません。PCの受信アプリと接続を確認してください。"
        },
        photos.map { photo ->
            val pcMissing = SenderPayloads.buildImageFileName(photo) in missing && photo.sendState == SendState.SENT
            SendRow(photo, photo.deviceName ?: "機器名なし", photo.deviceId ?: "機器IDなし",
                "${formatInspectionCaptureTime(photo.capturedAt)} 撮影",
                if (pcMissing) "PCに未着" else sendStatusLabel(photo, currentReceiverId), photo.isHeldFor(currentReceiverId),
                if (pcMissing) "PCで写真が見つかりません" else undeliveredReason(photo),
                if (pcMissing) GaugeKind.WARN else sendStatusKind(photo, currentReceiverId))
        },
        waiting && !manifestOnly, state == InspectionState.SENT_INCOMPLETE, manifestOnly,
        waiting && offline && health.reachable != true,
        badgeSpec.kind,
    )
}

@Composable
fun InspectionSendStatusScreen(state: SendStatusUiState, onSendNow: () -> Unit, onRetryUndelivered: () -> Unit, onReassign: (String) -> Unit, onGuide: () -> Unit, onHome: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusBadge(state.badgeKind, state.badge)
                Text(state.headline, style = MaterialTheme.typography.headlineSmall)
                Text(state.summaryLine, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                Text(state.photoProgress, style = MaterialTheme.typography.titleLarge.gaugeNum(), color = GaugeColors.Ink)
                Text(state.manifestLine, style = MaterialTheme.typography.bodyMedium)
                state.guidance?.let { GaugeCard(kind = null, modifier = Modifier.fillMaxWidth()) { Text(it, style = MaterialTheme.typography.bodyLarge) } }
            }
        }
        items(state.rows, key = { it.item.localId }) { row ->
            GaugeCard(kind = row.kind, modifier = Modifier.fillMaxWidth()) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Thumbnail(row.item.imagePath, Modifier.size(76.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        StatusBadge(row.kind, row.status)
                        Text(row.title, style = MaterialTheme.typography.titleMedium)
                        Text(row.idLine, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        Text(row.timeLine, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        row.reason?.let { Text("理由：$it", style = MaterialTheme.typography.bodyMedium) }
                        if (row.heldForOtherPc) TextButton(onClick = { onReassign(row.item.localId) }) { Text("今のPCへ送り直す") }
                    }
                }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.showSendNow) GaugePrimaryButton("今すぐ送る", onClick = onSendNow, modifier = Modifier.fillMaxWidth())
                if (state.showRetryUndelivered) GaugePrimaryButton("未着の写真を再送", onClick = onRetryUndelivered, modifier = Modifier.fillMaxWidth())
                if (state.showManifestOnlyRetry) GaugePrimaryButton("写真の一覧だけ再送", onClick = onSendNow, modifier = Modifier.fillMaxWidth())
                if (state.showGuideLink) TextButton(onClick = onGuide) { Text("接続の案内を見る") }
                TextButton(onClick = onHome) { Text("点検の一覧へ") }
            }
        }
    }
}
