package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.route.parseRouteJson
import jp.sotuken.metercapture.ui.countUndelivered
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.serialization.json.*

data class HomeCard(val inspectionId: String, val title: String, val stateLabel: String, val subtitle: String, val progress: String?, val action: String, val target: AppScreen)
data class HomeUiState(val inProgress: List<HomeCard>, val waiting: List<HomeCard>, val sent: List<HomeCard>, val legacyUndelivered: String?)

data class SavedCard(val imagePath: String, val deviceName: String?, val deviceId: String?, val capturedAt: String)
data class CaptureUiState(val header: String, val progress: String, val missingChips: List<RouteDevice>, val targetName: String, val targetId: String, val countLine: String, val justSaved: SavedCard?, val targetSourceLabel: String)
data class RouteCheckRow(val device: RouteDevice, val count: Int, val done: Boolean)
data class HistoryRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String, val sourceLabel: String, val canEdit: Boolean)
data class HistoryUiState(val header: String, val photoCount: Int, val deviceLine: String, val routeRows: List<RouteCheckRow>?, val rows: List<HistoryRow>, val notices: List<String>, val noRouteNote: String?)
data class CompleteUiState(val title: String, val photoCount: Int, val deviceCount: Int, val warnings: List<String>, val canComplete: Boolean, val completeLabel: String, val blockReason: String?)

fun formatInspectionCaptureTime(capturedAt: String, zone: ZoneId = ZoneId.systemDefault()): String =
    runCatching { DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(zone).format(Instant.parse(capturedAt)) }.getOrDefault(capturedAt)

fun buildCaptureUiState(inspection: Inspection, routeDevices: List<RouteDevice>?, photos: List<QueueItem>, target: CaptureTarget?, justSaved: SavedCard?): CaptureUiState {
    val summary = summarizeInspection(photos, routeDevices)
    val counts = "写真${summary.photoCount}枚 ・ ${summary.deviceCount}機器"
    val routeIds = routeDevices?.map { it.id }?.toSet().orEmpty()
    return CaptureUiState(
        "${inspection.name} ・ ${inspectionStateLabel(inspection.state)}",
        if (routeDevices == null) counts else "対象 ${summary.routeDeviceCount}機器中 ${summary.shotRouteDeviceCount}機器を撮影",
        summary.missing, target?.deviceName ?: "機器が選ばれていません",
        target?.let { it.deviceId ?: "機器IDなし" } ?: "QRを読むか、手入力してください",
        "この点検：$counts", justSaved,
        targetSourceLabel(target, routeIds),
    )
}

fun targetSourceLabel(target: CaptureTarget?, routeIds: Set<String>): String = when {
    target?.deviceId == null -> "機器IDなし"
    target.source == "qr" -> "QR"
    target.source == "manual" && target.deviceId in routeIds -> "一覧から"
    else -> "手入力"
}

fun deviceSourceLabel(item: QueueItem, routeIds: Set<String>): String = when {
    item.deviceId == null -> "機器IDなし"
    item.deviceIdSource == "qr" -> "QR"
    item.deviceIdSource == "manual" && item.deviceId in routeIds -> "一覧から"
    else -> "手入力"
}

fun buildHistoryUiState(inspection: Inspection, routeDevices: List<RouteDevice>?, photos: List<QueueItem>): HistoryUiState {
    val summary = summarizeInspection(photos, routeDevices)
    val routeIds = routeDevices?.map { it.id }?.toSet().orEmpty()
    return HistoryUiState(
        inspection.name, photos.size,
        if (routeDevices == null) "${summary.deviceCount}機器" else "${summary.shotRouteDeviceCount} / ${summary.routeDeviceCount}機器",
        routeDevices?.map { device ->
            val count = photos.count { it.deviceId == device.id }
            RouteCheckRow(device, count, count > 0)
        },
        photos.sortedByDescending { runCatching { Instant.parse(it.capturedAt) }.getOrDefault(Instant.EPOCH) }.map {
            HistoryRow(it, it.deviceName?.takeIf(String::isNotBlank) ?: "機器名なし", it.deviceId ?: "機器IDなし",
                "${formatInspectionCaptureTime(it.capturedAt)} 撮影", deviceSourceLabel(it, routeIds),
                inspection.state == InspectionState.IN_PROGRESS && it.sendState != SendState.SENDING)
        },
        summary.duplicates.map { "${it.deviceId ?: it.deviceName}は${it.count}枚あります。撮り直しの写真か確認してください。" },
        if (routeDevices == null) "対象一覧がないため、未撮影の機器は判定できません" else null,
    )
}

fun buildCompleteUiState(inspection: Inspection, summary: InspectionSummary): CompleteUiState {
    val warnings = buildList {
        summary.missing.forEach { add("未撮影：${it.name} ${it.id}") }
        summary.duplicates.forEach { add("重複：${listOfNotNull(it.deviceName, it.deviceId).joinToString(" ")} が${it.count}枚") }
        summary.extra.forEach { add("一覧外：$it") }
        if (summary.unidentifiedCount > 0) add("機器IDなし：${summary.unidentifiedCount}枚")
        if (summary.routeDeviceCount == null) add("対象一覧がないため、未撮影は確認できません")
    }
    val blockReason = when {
        inspection.state != InspectionState.IN_PROGRESS -> "完了した点検は変更できません"
        summary.photoCount == 0 -> "写真がありません。撮影してから完了してください"
        else -> null
    }
    return CompleteUiState(inspection.name, summary.photoCount, summary.deviceCount, warnings, blockReason == null,
        if (warnings.isEmpty()) "点検を完了する" else "確認して点検を完了する", blockReason)
}

fun inspectionStateLabel(state: InspectionState, undeliveredCount: Int = 0): String = when (state) {
    InspectionState.IN_PROGRESS -> "作業中"
    InspectionState.WAITING -> "送信待ち"
    InspectionState.SENDING -> "送信中"
    InspectionState.SENT -> "送信済み"
    InspectionState.SENT_INCOMPLETE -> "送信済み（未到着${undeliveredCount}枚）"
}

internal fun inspectionUndelivered(inspection: Inspection, photos: List<QueueItem>): Int {
    val failed = photos.filter { it.sendState == SendState.FAILED }.map { SenderPayloads.buildImageFileName(it) }
    val missing = inspection.pcMissingFileNames?.let { json -> runCatching { Json.parseToJsonElement(json).jsonArray.map { it.jsonPrimitive.content } }.getOrNull() }.orEmpty()
    return (failed + missing).toSet().size
}

fun buildHomeUiState(items: List<InspectionListItem>, legacyItems: List<QueueItem>, photosByInspection: Map<String, List<QueueItem>>): HomeUiState {
    val cards = items.sortedByDescending { it.inspection.startedAt }.map { item ->
        val inspection = item.inspection
        val photos = photosByInspection[inspection.inspectionId].orEmpty()
        val summary = summarizeInspection(photos, inspection.routeSnapshot?.let { parseRouteJson(it)?.devices })
        val count = item.counts?.photoCount ?: summary.photoCount
        val devices = item.counts?.deviceCount ?: summary.deviceCount
        val undelivered = inspectionUndelivered(inspection, photos)
        val subtitle = when (inspection.state) {
            InspectionState.IN_PROGRESS -> listOfNotNull(inspection.operatorName, inspection.place).joinToString(" ・ ").let { "${if (it.isEmpty()) "" else "$it "}写真${count}枚 ・ ${devices}機器" }
            InspectionState.WAITING -> "写真${count}枚 ・ 接続確認後に自動送信"
            InspectionState.SENDING -> "写真${count}枚 ・ ${item.counts?.deliveredCount ?: 0} / ${count}枚到着"
            InspectionState.SENT -> "写真${count}枚 ・ すべてPCへ到着"
            InspectionState.SENT_INCOMPLETE -> "写真${count}枚 ・ ${undelivered}枚が未到着"
        }
        HomeCard(inspection.inspectionId, inspection.name, inspectionStateLabel(inspection.state, undelivered), subtitle,
            if (inspection.state == InspectionState.IN_PROGRESS && summary.routeDeviceCount != null) "対象${summary.routeDeviceCount}機器のうち${summary.shotRouteDeviceCount}機器を撮影" else null,
            when (inspection.state) { InspectionState.IN_PROGRESS -> "点検を続ける"; InspectionState.WAITING, InspectionState.SENDING -> "状態を見る"; else -> "送信結果を見る" },
            if (inspection.state == InspectionState.IN_PROGRESS) AppScreen.Capture(inspection.inspectionId) else AppScreen.SendStatus(inspection.inspectionId))
    }
    val inProgressIds = items.filter { it.inspection.state == InspectionState.IN_PROGRESS }.map { it.inspection.inspectionId }.toSet()
    val waitingIds = items.filter { it.inspection.state in SENDABLE_INSPECTION_STATES }.map { it.inspection.inspectionId }.toSet()
    val sentIds = items.filter { it.inspection.state == InspectionState.SENT || it.inspection.state == InspectionState.SENT_INCOMPLETE }.map { it.inspection.inspectionId }.toSet()
    val legacy = countUndelivered(legacyItems.filter { it.inspectionId == null })
    return HomeUiState(cards.filter { it.inspectionId in inProgressIds }, cards.filter { it.inspectionId in waitingIds }, cards.filter { it.inspectionId in sentIds }, if (legacy > 0) "点検なしの写真: 未着${legacy}件" else null)
}
