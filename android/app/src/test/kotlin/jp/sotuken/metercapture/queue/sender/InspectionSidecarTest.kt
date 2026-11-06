package jp.sotuken.metercapture.queue.sender

import jp.sotuken.metercapture.inspection.photo
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class InspectionSidecarTest {
    @Test fun sidecarIncludesInspectionIdNameAndRoute() {
        val obj = Json.parseToJsonElement(SenderPayloads.buildSidecarJson(photo().copy(inspectionName = "朝の\"点検", routeId = "route-1"))).jsonObject
        assertEquals("inspection", obj["inspection_id"]?.jsonPrimitive?.content); assertEquals("朝の\"点検", obj["inspection_name"]?.jsonPrimitive?.content); assertEquals("route-1", obj["route_id"]?.jsonPrimitive?.content)
    }
    @Test fun sidecarOmitsRouteIdWhenNoRoute() {
        val obj = Json.parseToJsonElement(SenderPayloads.buildSidecarJson(photo().copy(inspectionName = "点検"))).jsonObject
        assertTrue("inspection_id" in obj); assertFalse("route_id" in obj)
    }
    @Test fun sidecarUnchangedWhenNoInspection() {
        val item = photo(deviceId = null, name = null, inspectionId = null).copy(inspectionName = "無視", routeId = "無視")
        assertEquals("{\"local_id\":\"photo\",\"captured_at\":\"2026-11-06T00:00:00Z\",\"device_name\":null,\"operator_value\":null,\"operator_note\":null}", SenderPayloads.buildSidecarJson(item))
    }
}
