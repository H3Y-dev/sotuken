package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.QueueItem
import kotlinx.serialization.json.*

data class DuplicateDevice(val deviceId: String?, val deviceName: String?, val count: Int)
data class InspectionSummary(
    val photoCount: Int,
    val deviceCount: Int,
    val routeDeviceCount: Int?,
    val shotRouteDeviceCount: Int?,
    val missing: List<RouteDevice>,
    val duplicates: List<DuplicateDevice>,
    val extra: List<String>,
    val unidentifiedCount: Int,
)

fun summarizeInspection(photos: List<QueueItem>, routeDevices: List<RouteDevice>?): InspectionSummary {
    val ordered = photos.sortedBy { it.capturedAt }
    val groups = ordered.filter { it.deviceId != null || !it.deviceName.isNullOrBlank() }
        .groupBy { it.deviceId ?: "name:${it.deviceName!!.trim()}" }
    val ids = ordered.mapNotNull { it.deviceId }.toSet()
    val routeIds = routeDevices?.map { it.id }?.toSet()
    val missing = routeDevices?.filter { it.id !in ids }.orEmpty()
    return InspectionSummary(
        photos.size, groups.size, routeDevices?.size, routeDevices?.let { it.size - missing.size }, missing,
        groups.values.filter { it.size >= 2 }.map { DuplicateDevice(it.first().deviceId, it.first().deviceName, it.size) },
        if (routeIds == null) emptyList() else ids.filter { it !in routeIds },
        photos.count { it.deviceId == null },
    )
}

fun InspectionSummary.toJson(): String = buildJsonObject {
    put("v", 1)
    putJsonArray("missing") { missing.forEach { device -> addJsonObject { put("id", device.id); put("name", device.name) } } }
    putJsonArray("extra") { extra.forEach { add(JsonPrimitive(it)) } }
    putJsonArray("duplicates") { duplicates.forEach { device -> addJsonObject {
        put("id", device.deviceId?.let(::JsonPrimitive) ?: JsonNull)
        put("name", device.deviceName?.let(::JsonPrimitive) ?: JsonNull)
        put("count", device.count)
    } } }
    put("unidentified", unidentifiedCount)
}.toString()

fun parseInspectionSummary(json: String): InspectionSummary? = runCatching {
    val obj = Json.parseToJsonElement(json).jsonObject
    val version = obj.getValue("v").jsonPrimitive
    require(!version.isString && version.doubleOrNull == 1.0)
    val missing = obj.getValue("missing").jsonArray.map { RouteDevice(it.jsonObject.getValue("id").jsonPrimitive.content, it.jsonObject.getValue("name").jsonPrimitive.content) }
    val extra = obj.getValue("extra").jsonArray.map { it.jsonPrimitive.content }
    val duplicates = obj.getValue("duplicates").jsonArray.map { value -> value.jsonObject.let {
        DuplicateDevice(it["id"]?.jsonPrimitive?.contentOrNull, it["name"]?.jsonPrimitive?.contentOrNull, it.getValue("count").jsonPrimitive.int.also { count -> require(count >= 2) })
    } }
    val unidentified = obj.getValue("unidentified").jsonPrimitive.int.also { require(it >= 0) }
    // 件数は保存しない契約。表示側は現在の写真から集計する。
    InspectionSummary(0, 0, null, null, missing, duplicates, extra, unidentified)
}.getOrNull()
