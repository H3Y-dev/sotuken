package jp.sotuken.metercapture.route

import java.io.IOException
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import jp.sotuken.metercapture.inspection.INSPECTION_ID_PATTERN
import jp.sotuken.metercapture.inspection.normalizeInspectionText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

data class RouteSummary(val routeId: String, val name: String, val count: Int, val updatedAt: String)

fun parseRouteList(text: String): List<RouteSummary>? = runCatching {
    val obj = Json.parseToJsonElement(text).jsonObject
    val version = obj.getValue("v").jsonPrimitive
    require(!version.isString && version.doubleOrNull == 1.0)
    obj.getValue("routes").jsonArray.map { element ->
        val row = element.jsonObject
        fun string(key: String) = row.getValue(key).jsonPrimitive.also { require(it.isString) }.content
        val id = string("route_id").also { require(INSPECTION_ID_PATTERN.matches(it)) }
        val name = requireNotNull(normalizeInspectionText(string("name")))
        val count = row.getValue("count").jsonPrimitive.also { require(!it.isString) }.int.also { require(it >= 0) }
        RouteSummary(id, name, count, string("updated_at").also { require(it.isNotBlank()) })
    }.also { rows -> require(rows.map { it.routeId }.distinct().size == rows.size) }
}.getOrNull()

class RouteClient(private val baseUrl: String, private val token: String,
    private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection }) {
    suspend fun listRoutes(): Result<List<RouteSummary>> = request("/routes") { parseRouteList(it) }

    suspend fun fetchRoute(routeId: String): Result<RouteDoc> {
        if (!INSPECTION_ID_PATTERN.matches(routeId)) return Result.failure(IllegalArgumentException("ルートの内容が正しくありません"))
        return request("/routes/$routeId") { parseRouteJson(it)?.takeIf { route -> route.routeId == routeId } }
    }

    private suspend fun <T : Any> request(path: String, parse: (String) -> T?): Result<T> = withContext(Dispatchers.IO) {
        try {
            val connection = openConnection(URL(baseUrl.trimEnd('/') + path))
            val result = try {
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 2000
                connection.readTimeout = 5000
                connection.requestMethod = "GET"
                connection.setRequestProperty("X-Sotuken-Token", token)
                when (connection.responseCode) {
                    401, 403 -> throw IllegalStateException("合言葉が違います")
                    404 -> throw IllegalStateException("PCがルートの受け渡しに未対応です。PCのアプリを更新してください")
                    200 -> Unit
                    else -> throw IOException("PCに接続できません")
                }
                val bytes = connection.inputStream.use { input ->
                    val output = ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        if (output.size() + count > 256 * 1024) throw IllegalStateException("ルートの内容が正しくありません")
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                parse(bytes.toString(Charsets.UTF_8)) ?: throw IllegalStateException("ルートの内容が正しくありません")
            } finally { connection.disconnect() }
            Result.success(result)
        } catch (e: CancellationException) { throw e
        } catch (e: IllegalStateException) { Result.failure(e)
        } catch (_: Exception) { Result.failure(IOException("PCに接続できません")) }
    }
}
