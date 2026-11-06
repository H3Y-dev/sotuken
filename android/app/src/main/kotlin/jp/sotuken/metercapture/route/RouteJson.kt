package jp.sotuken.metercapture.route

import jp.sotuken.metercapture.device.parseDeviceQr
import jp.sotuken.metercapture.inspection.*
import kotlinx.serialization.json.*

data class RouteDoc(val routeId: String, val name: String, val devices: List<RouteDevice>, val updatedAt: String)

fun parseRouteJson(text: String): RouteDoc? = runCatching {
    val obj = Json.parseToJsonElement(text).jsonObject
    val version = obj.getValue("v").jsonPrimitive
    require(!version.isString && version.doubleOrNull == 1.0)
    fun string(key: String) = obj.getValue(key).jsonPrimitive.also { require(it.isString) }.content
    val id = string("route_id").also { require(INSPECTION_ID_PATTERN.matches(it)) }
    val name = requireNotNull(normalizeInspectionText(string("name")))
    val updated = string("updated_at").also { require(it.isNotBlank()) }
    val devices = obj.getValue("devices").jsonArray.map { element ->
        // P3では既存の機器QRパーサーを通し、同じID・名前の検証規則を使う。
        val qr = requireNotNull(parseDeviceQr(JsonObject(element.jsonObject + ("v" to JsonPrimitive(1))).toString()))
        RouteDevice(qr.id, qr.name)
    }
    require(devices.size in 1..200 && devices.map { it.id }.distinct().size == devices.size)
    RouteDoc(id, name, devices, updated)
}.getOrNull()

fun RouteDoc.toJson(): String = buildJsonObject {
    put("v", 1); put("route_id", routeId); put("name", name)
    putJsonArray("devices") { devices.forEach { device -> addJsonObject { put("id", device.id); put("name", device.name) } } }
    put("updated_at", updatedAt)
}.toString()
