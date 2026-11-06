package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import kotlinx.serialization.json.*

data class ManifestReply(val matched: Int, val missingPhotos: List<String>)

fun buildManifestJson(inspection: Inspection, photos: List<QueueItem>, summary: InspectionSummary, sha256Of: (QueueItem) -> String?): String = buildJsonObject {
    put("v", 1)
    put("inspection_id", inspection.inspectionId)
    put("inspection_name", inspection.name)
    put("route_id", inspection.routeId?.let(::JsonPrimitive) ?: JsonNull)
    put("operator", inspection.operatorName?.let(::JsonPrimitive) ?: JsonNull)
    put("place", inspection.place?.let(::JsonPrimitive) ?: JsonNull)
    put("started_at", inspection.startedAt)
    put("completed_at", inspection.completedAt?.let(::JsonPrimitive) ?: JsonNull)
    putJsonArray("photos") { photos.forEach { photo -> addJsonObject {
        put("file_name", SenderPayloads.buildImageFileName(photo))
        put("sha256", sha256Of(photo)?.let(::JsonPrimitive) ?: JsonNull)
        put("device_id", photo.deviceId?.let(::JsonPrimitive) ?: JsonNull)
        put("device_id_source", photo.deviceIdSource?.let(::JsonPrimitive) ?: JsonNull)
        put("captured_at", photo.capturedAt)
    } } }
    putJsonArray("missing") { if (inspection.routeId != null) summary.missing.forEach { add(JsonPrimitive(it.id)) } }
    putJsonArray("extra") { if (inspection.routeId != null) summary.extra.forEach { add(JsonPrimitive(it)) } }
}.toString()

fun parseManifestReply(text: String): ManifestReply? = runCatching {
    val obj = Json.parseToJsonElement(text).jsonObject
    val ok = obj.getValue("ok").jsonPrimitive
    require(!ok.isString && ok.booleanOrNull == true)
    val matched = obj.getValue("matched").jsonPrimitive
    require(!matched.isString && matched.int >= 0)
    ManifestReply(matched.int, obj.getValue("missing_photos").jsonArray.map {
        it.jsonPrimitive.also { value -> require(value.isString) }.content
    })
}.getOrNull()

internal fun parseMissingFileNames(json: String?): List<String> = json?.let {
    Json.parseToJsonElement(it).jsonArray.map { value -> value.jsonPrimitive.also { p -> require(p.isString) }.content }
}.orEmpty()
