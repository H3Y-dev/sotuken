package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.route.parseRouteJson
import jp.sotuken.metercapture.ui.countUndelivered
import jp.sotuken.metercapture.ui.components.GaugeKind
import jp.sotuken.metercapture.ui.components.BadgeSpec
import jp.sotuken.metercapture.ui.components.edgeKindOf
import jp.sotuken.metercapture.ui.sendStatusKind
import jp.sotuken.metercapture.ui.sendStatusLabel
import jp.sotuken.metercapture.ui.undeliveredReason
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.serialization.json.*

data class HomeCard(val inspectionId: String, val title: String, val stateLabel: String, val subtitle: String, val progress: String?, val action: String, val target: AppScreen, val kind: GaugeKind = GaugeKind.WAIT, val badges: List<BadgeSpec> = emptyList(), val edgeKind: GaugeKind = GaugeKind.WAIT, val startedLabel: String = "")
data class HomeUiState(val inProgress: List<HomeCard>, val waiting: List<HomeCard>, val sent: List<HomeCard>, val legacyUndelivered: String?)

data class SavedCard(val imagePath: String, val deviceName: String?, val deviceId: String?, val capturedAt: String)
data class CaptureUiState(val header: String, val progress: String, val missingChips: List<RouteDevice>, val targetName: String, val targetId: String, val countLine: String, val justSaved: SavedCard?, val targetSourceLabel: String)
data class RouteCheckRow(val device: RouteDevice, val count: Int, val done: Boolean)
data class HistoryRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String, val sourceLabel: String, val canEdit: Boolean, val sendLabel: String = "", val sendKind: GaugeKind = GaugeKind.WAIT, val reason: String? = null)
data class HistoryUiState(val header: String, val photoCount: Int, val deviceLine: String, val routeRows: List<RouteCheckRow>?, val rows: List<HistoryRow>, val notices: List<String>, val noRouteNote: String?)
data class CompleteUiState(val title: String, val photoCount: Int, val deviceCount: Int, val warnings: List<String>, val canComplete: Boolean, val completeLabel: String, val blockReason: String?)

fun formatInspectionCaptureTime(capturedAt: String, zone: ZoneId = ZoneId.systemDefault()): String =
    runCatching { DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(zone).format(Instant.parse(capturedAt)) }.getOrDefault(capturedAt)

fun buildCaptureUiState(inspection: Inspection, routeDevices: List<RouteDevice>?, photos: List<QueueItem>, target: CaptureTarget?, justSaved: SavedCard?): CaptureUiState {
    val summary = summarizeInspection(photos, routeDevices)
    val counts = "写真${summary.photoCount}枚 ・ ${summary.deviceCount}台"
    val routeIds = routeDevices?.map { it.id }?.toSet().orEmpty()
    return CaptureUiState(
        "${inspection.name} ・ ${inspectionStateLabel(inspection.state)}",
        if (routeDevices == null) counts else "撮影 ${summary.shotRouteDeviceCount}/${summary.routeDeviceCount}台",
        summary.missing, target?.deviceName ?: "機器が選ばれていません",
        target?.let { it.deviceId ?: "機器IDなし" } ?: "QRを読むか、手入力してください",
        "この点検：$counts", justSaved,
        targetSourceLabel(target, routeIds),
    )
}

fun targetSourceLabel(target: CaptureTarget?, routeIds: Set<String>): String = when {
    target?.deviceId == null -> "機器IDなし"
    target.source == "qr" -> "QR"
    target.source == "list" -> "一覧から"
    target.source == "manual" && target.deviceId in routeIds -> "一覧から"
    else -> "手入力"
}

fun deviceSourceLabel(item: QueueItem, routeIds: Set<String>): String = when {
    item.deviceId == null -> "機器IDなし"
    item.deviceIdSource == "qr" -> "QR"
    item.deviceIdSource == "list" -> "一覧から"
    item.deviceIdSource == "manual" && item.deviceId in routeIds -> "一覧から"
    else -> "手入力"
}

internal fun isPhotoDisplaySendable(item: QueueItem, inspectionState: InspectionState?): Boolean =
    item.inspectionId == null || inspectionState != InspectionState.IN_PROGRESS

fun buildHistoryUiState(inspection: Inspection, routeDevices: List<RouteDevice>?, photos: List<QueueItem>, currentReceiverId: String? = null): HistoryUiState {
    val summary = summarizeInspection(photos, routeDevices)
    val sendable: (QueueItem) -> Boolean = { isPhotoDisplaySendable(it, inspection.state) }
    val routeIds = routeDevices?.map { it.id }?.toSet().orEmpty()
    return HistoryUiState(
        inspection.name, photos.size,
        if (routeDevices == null) "${summary.deviceCount}台" else "撮影 ${summary.shotRouteDeviceCount}/${summary.routeDeviceCount}台",
        routeDevices?.map { device ->
            val count = photos.count { it.deviceId == device.id }
            RouteCheckRow(device, count, count > 0)
        },
        photos.sortedByDescending { runCatching { Instant.parse(it.capturedAt) }.getOrDefault(Instant.EPOCH) }.map {
            HistoryRow(it, it.deviceName?.takeIf(String::isNotBlank) ?: "機器名なし", it.deviceId ?: "機器IDなし",
                "${formatInspectionCaptureTime(it.capturedAt)} 撮影", deviceSourceLabel(it, routeIds),
                inspection.state == InspectionState.IN_PROGRESS && it.sendState != SendState.SENDING,
                sendStatusLabel(it, currentReceiverId, sendable), sendStatusKind(it, currentReceiverId, sendable), undeliveredReason(it))
        },
        summary.duplicates.map { "${it.deviceId ?: it.deviceName}は${it.count}枚あります。撮り直しの写真か確認してください。" },
        if (routeDevices == null) "ルートがないため、未撮影の機器は判定できません" else null,
    )
}

fun buildCompleteUiState(inspection: Inspection, summary: InspectionSummary): CompleteUiState {
    val warnings = buildList {
        summary.missing.forEach { add("未撮影：${it.name} ${it.id}") }
        summary.duplicates.forEach { add("重複：${listOfNotNull(it.deviceName, it.deviceId).joinToString(" ")} が${it.count}枚") }
        summary.extra.forEach { add("ルート外：$it") }
        if (summary.unidentifiedCount > 0) add("機器IDなし：${summary.unidentifiedCount}枚")
        if (summary.routeDeviceCount == null) add("ルートがないため、未撮影は確認できません")
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
    InspectionState.SENT_INCOMPLETE -> "未着あり ${undeliveredCount}枚"
}

fun inspectionBadge(state: InspectionState, summary: InspectionSummary, undelivered: Int): BadgeSpec = when (state) {
    InspectionState.IN_PROGRESS -> BadgeSpec(GaugeKind.WAIT, "作業中")
    InspectionState.WAITING -> BadgeSpec(GaugeKind.WAIT, "送信待ち")
    InspectionState.SENDING -> BadgeSpec(GaugeKind.WAIT, "送信中")
    InspectionState.SENT_INCOMPLETE -> BadgeSpec(GaugeKind.WARN, "未着あり ${undelivered}枚")
    InspectionState.SENT -> if (summary.missing.isEmpty() && summary.duplicates.isEmpty() && summary.unidentifiedCount == 0) BadgeSpec(GaugeKind.OK, "送信済み") else BadgeSpec(GaugeKind.NEUTRAL, "送信済み（要確認あり）")
}

fun extraBadges(state: InspectionState, summary: InspectionSummary): List<BadgeSpec> =
    if (state == InspectionState.IN_PROGRESS) emptyList() else buildList {
        if (summary.missing.isNotEmpty()) add(BadgeSpec(GaugeKind.MISSING, "未撮影 ${summary.missing.size}台"))
        if (summary.duplicates.isNotEmpty()) add(BadgeSpec(GaugeKind.WARN, "重複 ${summary.duplicates.size}台"))
        if (summary.unidentifiedCount > 0) add(BadgeSpec(GaugeKind.WARN, "機器IDなし ${summary.unidentifiedCount}枚"))
        if (summary.extra.isNotEmpty()) add(BadgeSpec(GaugeKind.NEUTRAL, "ルート外 ${summary.extra.size}台"))
    }

fun formatStartedLabel(startedAt: String, zone: ZoneId = ZoneId.systemDefault()): String =
    runCatching { DateTimeFormatter.ofPattern("M/d(E) HH:mm", Locale.JAPAN).withZone(zone).format(Instant.parse(startedAt)) }.getOrDefault(startedAt)

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
        val badge = inspectionBadge(inspection.state, summary, undelivered)
        val extras = extraBadges(inspection.state, summary)
        val subtitle = when (inspection.state) {
            InspectionState.IN_PROGRESS -> listOfNotNull(inspection.operatorName, inspection.place).joinToString(" ・ ").let { "${if (it.isEmpty()) "" else "$it "}写真${count}枚 ・ ${devices}台" }
            InspectionState.WAITING -> "写真${count}枚 ・ 接続確認後に自動送信"
            InspectionState.SENDING -> "写真${count}枚 ・ 到着 ${item.counts?.deliveredCount ?: 0}/${count}枚"
            InspectionState.SENT -> "写真${count}枚 ・ すべてPCに到着"
            InspectionState.SENT_INCOMPLETE -> "写真${count}枚 ・ 未着 ${undelivered}枚"
        }
        HomeCard(inspection.inspectionId, inspection.name, badge.label, subtitle,
            if (inspection.state == InspectionState.IN_PROGRESS && summary.routeDeviceCount != null) "撮影 ${summary.shotRouteDeviceCount}/${summary.routeDeviceCount}台" else null,
            when (inspection.state) { InspectionState.IN_PROGRESS -> "点検を続ける"; InspectionState.WAITING, InspectionState.SENDING -> "状態を見る"; else -> "送信結果を見る" },
            if (inspection.state == InspectionState.IN_PROGRESS) AppScreen.Capture(inspection.inspectionId) else AppScreen.SendStatus(inspection.inspectionId),
            badge.kind, extras, edgeKindOf(listOf(badge.kind) + extras.map { it.kind }), formatStartedLabel(inspection.startedAt))
    }
    val inProgressIds = items.filter { it.inspection.state == InspectionState.IN_PROGRESS }.map { it.inspection.inspectionId }.toSet()
    val waitingIds = items.filter { it.inspection.state in SENDABLE_INSPECTION_STATES }.map { it.inspection.inspectionId }.toSet()
    val sentIds = items.filter { it.inspection.state == InspectionState.SENT || it.inspection.state == InspectionState.SENT_INCOMPLETE }.map { it.inspection.inspectionId }.toSet()
    val legacy = countUndelivered(legacyItems.filter { it.inspectionId == null })
    return HomeUiState(cards.filter { it.inspectionId in inProgressIds }, cards.filter { it.inspectionId in waitingIds }, cards.filter { it.inspectionId in sentIds }, if (legacy > 0) "点検なしの写真 未着 ${legacy}枚" else null)
}

/** 指定した日付（端末タイムゾーン）に撮影されたキュー項目数を返す。読めない日時は数えない。 */
fun countTodayPhotos(
    items: List<QueueItem>,
    today: LocalDate,
    zone: ZoneId = ZoneId.systemDefault(),
): Int = items.count { item ->
    runCatching { Instant.parse(item.capturedAt).atZone(zone).toLocalDate() == today }.getOrDefault(false)
}

/**
 * 保存完了直後の「今日 N枚目」を返す。
 * - 日付基準はキュー登録日時（allPhotos に反映済みならその capturedAt、未反映なら enqueue 完了直後の savedAt）。
 * - unconfirmedSaved に保存完了済みで Flow 未反映かもしれない (imagePath, savedAt) を渡すことで、
 *   直前の複数枚が Flow に未反映でも欠落・二重加算にならない。
 */
fun todayCaptureCountAfterSave(
    allPhotos: List<QueueItem>,
    savedImagePath: String,
    savedAt: Instant,
    unconfirmedSaved: Map<String, Instant> = emptyMap(),
    zone: ZoneId = ZoneId.systemDefault(),
): Int {
    val reflected = allPhotos.firstOrNull { it.imagePath == savedImagePath }
    val baseInstant = reflected?.capturedAt?.let { runCatching { Instant.parse(it) }.getOrNull() } ?: savedAt
    val today = baseInstant.atZone(zone).toLocalDate()
    val existing = countTodayPhotos(allPhotos, today, zone)
    val reflectedPaths = allPhotos.mapTo(HashSet()) { it.imagePath }
    val pendingToday = (unconfirmedSaved + (savedImagePath to savedAt)).count { (path, at) ->
        path !in reflectedPaths && at.atZone(zone).toLocalDate() == today
    }
    return existing + pendingToday
}
