package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.route.parseRouteJson
import jp.sotuken.metercapture.ui.countUndelivered
import kotlinx.serialization.json.*

data class HomeCard(val inspectionId: String, val title: String, val stateLabel: String, val subtitle: String, val progress: String?, val action: String, val target: AppScreen)
data class HomeUiState(val inProgress: List<HomeCard>, val waiting: List<HomeCard>, val sent: List<HomeCard>, val legacyUndelivered: String?)

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
