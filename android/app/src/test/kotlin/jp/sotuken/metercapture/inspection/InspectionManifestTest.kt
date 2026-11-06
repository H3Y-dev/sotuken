package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class InspectionManifestTest {
    private val inspection = Inspection("I-1", "巡回", null, null, null, null, null, InspectionState.SENDING, "2026-11-06T01:00:00Z", "2026-11-06T02:00:00Z")
    private val photo = QueueItem("a", "/missing", "2026-11-06T01:10:00Z", null, null, null, SendState.FAILED, 0, null, null)

    @Test fun matchesPcValidatedInputFixture() {
        val expected = checkNotNull(javaClass.getResource("/inspection_manifest_pc.json")).readText().trim()
        val i = inspection.copy(routeId = "R-1", operatorName = "担当", place = "工場")
        val p = photo.copy(deviceId = "A", deviceIdSource = "manual")
        assertEquals(expected, buildManifestJson(i, listOf(p), summarizeInspection(listOf(p), listOf(RouteDevice("A", "機器")))) { "a".repeat(64) })
    }
    @Test fun noRouteHasEmptyMissingAndExtra() {
        val summary = summarizeInspection(listOf(photo.copy(deviceId = "extra")), listOf(RouteDevice("missing", "未撮影")))
        val obj = Json.parseToJsonElement(buildManifestJson(inspection, listOf(photo), summary) { null }).jsonObject
        assertEquals(JsonArray(emptyList()), obj["missing"]); assertEquals(JsonArray(emptyList()), obj["extra"])
    }
    @Test fun includesFailedPhotos() {
        val obj = Json.parseToJsonElement(buildManifestJson(inspection, listOf(photo), summarizeInspection(listOf(photo), null)) { null }).jsonObject
        assertEquals(1, obj.getValue("photos").jsonArray.size)
    }
    @Test fun sha256NullWhenFileMissing() {
        val obj = Json.parseToJsonElement(buildManifestJson(inspection, listOf(photo), summarizeInspection(listOf(photo), null)) { null }).jsonObject
        assertEquals(JsonNull, obj.getValue("photos").jsonArray.single().jsonObject["sha256"])
    }

    @Test fun buildsContractKeysInOrder() {
        val obj = Json.parseToJsonElement(buildManifestJson(inspection, listOf(photo), summarizeInspection(listOf(photo), null)) { "a".repeat(64) }).jsonObject
        assertEquals(listOf("v", "inspection_id", "inspection_name", "route_id", "operator", "place", "started_at", "completed_at", "photos", "missing", "extra"), obj.keys.toList())
        assertEquals("a".repeat(64), obj.getValue("photos").jsonArray.single().jsonObject.getValue("sha256").jsonPrimitive.content)
    }
    @Test fun nullsForMissingOptionalValues() {
        val obj = Json.parseToJsonElement(buildManifestJson(inspection, listOf(photo), summarizeInspection(listOf(photo), null)) { null }).jsonObject
        listOf("route_id", "operator", "place").forEach { assertEquals(JsonNull, obj[it]) }
        val p = obj.getValue("photos").jsonArray.single().jsonObject
        listOf("sha256", "device_id", "device_id_source").forEach { assertEquals(JsonNull, p[it]) }
        assertEquals(JsonArray(emptyList()), obj["missing"])
        assertEquals(JsonArray(emptyList()), obj["extra"])
    }
    @Test fun parseReplyReadsMatchedAndMissing() {
        assertEquals(ManifestReply(2, listOf("b.jpg")), parseManifestReply("""{"ok":true,"matched":2,"missing_photos":["b.jpg"]}"""))
    }
    @Test fun parseReplyRejectsOkFalseAndMalformedTypes() {
        listOf("""{"ok":false,"matched":0,"missing_photos":[]}""", """{"ok":"true","matched":0,"missing_photos":[]}""", """{"ok":true,"matched":-1,"missing_photos":[]}""", """{"ok":true,"matched":0,"missing_photos":[1]}""").forEach { assertNull(parseManifestReply(it)) }
    }
}
