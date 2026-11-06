package jp.sotuken.metercapture.route

import java.io.File
import java.time.Instant
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class RouteRepositoryTest {
    @get:Rule val temp = TemporaryFolder()
    private val now = Instant.parse("2026-11-06T00:30:00Z")
    private val route = requireNotNull(parseRouteJson(PC_ROUTE_JSON))
    private fun repository() = RouteRepository(File(temp.root, "routes.json"))
    @Test fun saveThenLoad() { val saved = repository().save(route, "qr", now); assertEquals(saved, repository().load()); assertEquals("qr", saved.single().source); assertFalse(File(temp.root, "routes.json.tmp").exists()) }
    @Test fun saveReplacesSameRouteId() { repository().save(route, "qr", now); repository().save(route.copy(name = "更新"), "wifi", now.plusSeconds(1)); assertEquals("更新", repository().load().single().route.name) }
    @Test fun deleteRemoves() { repository().save(route, "qr", now); assertTrue(repository().delete(route.routeId).isEmpty()); assertTrue(repository().load().isEmpty()) }
    @Test fun brokenFileLoadsEmptyAndIsKept() { val file = File(temp.root, "routes.json"); file.writeText("broken"); assertTrue(repository().load().isEmpty()); assertEquals("broken", File(file.path + ".broken").readText()); assertFalse(file.exists()) }
    @Test fun brokenBackupIsNotOverwritten() { val file = File(temp.root, "routes.json"); File(file.path + ".broken").writeText("old"); file.writeText("new"); repository().load(); assertEquals("old", File(file.path + ".broken").readText()); assertEquals("new", File(file.path + ".broken.1").readText()) }
    @Test fun rejectsInvalidSourceWithoutChangingFile() { repository().save(route, "qr", now); assertTrue(runCatching { repository().save(route, "unknown", now) }.isFailure); assertEquals("qr", repository().load().single().source) }
}
