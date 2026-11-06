package jp.sotuken.metercapture.route

import java.io.File
import java.io.IOException
import java.time.Instant
import kotlinx.serialization.json.*

data class SavedRoute(val route: RouteDoc, val savedAt: String, val source: String)

class RouteRepository(private val file: File) {
    @Synchronized fun load(): List<SavedRoute> {
        if (!file.exists()) return emptyList()
        val text = file.readText(Charsets.UTF_8)
        return try {
            val obj = Json.parseToJsonElement(text).jsonObject
            val version = obj.getValue("v").jsonPrimitive
            require(!version.isString && version.doubleOrNull == 1.0)
            obj.getValue("routes").jsonArray.map { element ->
                val row = element.jsonObject
                val route = requireNotNull(parseRouteJson(row.toString()))
                val savedAt = row.getValue("saved_at").jsonPrimitive.also { require(it.isString && it.content.isNotBlank()) }.content
                val source = row.getValue("source").jsonPrimitive.also { require(it.isString && it.content in setOf("wifi", "qr")) }.content
                SavedRoute(route, savedAt, source)
            }.also { routes -> require(routes.map { it.route.routeId }.distinct().size == routes.size) }
        } catch (_: Exception) {
            // 既存の退避ファイルも残し、壊れた元データを上書きしない。
            var broken = File(file.path + ".broken")
            var suffix = 1
            while (broken.exists()) { broken = File(file.path + ".broken.${suffix++}") }
            if (!file.renameTo(broken)) throw IOException("保存済みルートの退避に失敗しました")
            emptyList()
        }
    }

    @Synchronized fun save(route: RouteDoc, source: String, now: Instant): List<SavedRoute> {
        require(source in setOf("wifi", "qr"))
        val checked = requireNotNull(parseRouteJson(route.toJson()))
        return write(load().filterNot { it.route.routeId == checked.routeId } + SavedRoute(checked, now.toString(), source))
    }

    @Synchronized fun delete(routeId: String): List<SavedRoute> = write(load().filterNot { it.route.routeId == routeId })

    private fun write(routes: List<SavedRoute>): List<SavedRoute> {
        val text = buildJsonObject {
            put("v", 1)
            putJsonArray("routes") { routes.forEach { saved ->
                add(JsonObject(Json.parseToJsonElement(saved.route.toJson()).jsonObject + mapOf("saved_at" to JsonPrimitive(saved.savedAt), "source" to JsonPrimitive(saved.source))))
            } }
        }.toString()
        val tmp = File(file.path + ".tmp")
        tmp.writeText(text, Charsets.UTF_8)
        if (!tmp.renameTo(file)) throw IOException("ルートの保存に失敗しました")
        return routes
    }
}
