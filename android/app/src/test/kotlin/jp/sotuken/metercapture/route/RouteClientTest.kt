package jp.sotuken.metercapture.route

import java.net.ServerSocket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class RouteClientTest {
    private val listJson = """{"v":1,"routes":[{"route_id":"R-20261106093000-a1b2","name":"巡回","count":1,"updated_at":"2026-11-06"}]}"""
    private fun serve(status: Int = 200, body: String, headers: String = "", action: (RouteClient) -> Unit): List<String> {
        ServerSocket(0).use { server ->
            server.soTimeout = 10000
            val executor = Executors.newSingleThreadExecutor()
            val received = executor.submit<List<String>> {
                server.accept().use { socket ->
                    socket.soTimeout = 10000
                    val reader = socket.getInputStream().bufferedReader()
                    val lines = mutableListOf<String>()
                    while (true) { val line = reader.readLine() ?: break; if (line.isEmpty()) break; lines += line }
                    val bytes = body.toByteArray(Charsets.UTF_8)
                    socket.getOutputStream().apply { write("HTTP/1.1 $status Response\r\nContent-Length: ${bytes.size}\r\n$headers\r\n".toByteArray()); write(bytes); flush() }
                    lines
                }
            }
            try { action(RouteClient("http://127.0.0.1:${server.localPort}", "secret")); return received.get(12, TimeUnit.SECONDS) }
            finally { executor.shutdownNow() }
        }
    }
    @Test fun listSendsTokenAndParses() {
        val headers = serve(body = listJson) { client -> runBlocking { val rows = client.listRoutes().getOrThrow(); assertEquals(1, rows.single().count); assertEquals("巡回", rows.single().name) } }
        assertTrue(headers.contains("GET /routes HTTP/1.1")); assertTrue(headers.any { it.equals("X-Sotuken-Token: secret", true) })
    }
    @Test fun fetchParsesRoute() { serve(body = PC_ROUTE_JSON) { client -> runBlocking { assertEquals(parseRouteJson(PC_ROUTE_JSON), client.fetchRoute("R-20261106093000-a1b2").getOrThrow()) } } }
    @Test fun unauthorizedMapsToTokenMessage() { listOf(401, 403).forEach { code -> serve(code, "{}") { client -> runBlocking { assertEquals("合言葉が違います", client.listRoutes().exceptionOrNull()?.message) } } } }
    @Test fun notFoundMapsToUnsupportedMessage() { serve(404, "{}") { client -> runBlocking { assertEquals("PCがルートの受け渡しに未対応です。PCのアプリを更新してください", client.listRoutes().exceptionOrNull()?.message) } } }
    @Test fun doesNotFollowRedirect() { serve(302, "", "Location: http://127.0.0.1:1/redirect\r\n") { client -> runBlocking { assertEquals("PCに接続できません", client.listRoutes().exceptionOrNull()?.message) } } }
    @Test fun rejectsOversizedBody() { serve(body = " ".repeat(256 * 1024 + 1)) { client -> runBlocking { assertTrue(client.listRoutes().isFailure) } } }
    @Test fun rejectsMalformedList() { listOf("{}", listJson.replace("\"v\":1", "\"v\":\"1\""), listJson.replace("\"count\":1", "\"count\":-1")).forEach { assertNull(parseRouteList(it)) } }
    @Test fun acceptsZeroCount() { assertEquals(0, parseRouteList(listJson.replace("\"count\":1", "\"count\":0"))?.single()?.count) }
    @Test fun rejectsInvalidDetail() { serve(body = PC_ROUTE_JSON.replace("[{\"id\":\"A\",\"name\":\"計器\"}]", "[]")) { client -> runBlocking { assertEquals("ルートの内容が正しくありません", client.fetchRoute("R-20261106093000-a1b2").exceptionOrNull()?.message) } } }
    @Test fun rejectsUnexpectedRouteId() { serve(body = PC_ROUTE_JSON) { client -> runBlocking { assertTrue(client.fetchRoute("other").isFailure) } } }
    @Test fun rejectsInvalidIdBeforeNetwork() = runBlocking { assertTrue(RouteClient("http://127.0.0.1:1", "secret").fetchRoute("../escape").isFailure) }
    @Test fun connectionFailureHasMessage() = runBlocking { assertEquals("PCに接続できません", RouteClient("http://127.0.0.1:1", "secret").listRoutes().exceptionOrNull()?.message) }
}
