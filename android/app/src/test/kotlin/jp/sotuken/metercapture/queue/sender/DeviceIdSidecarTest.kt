package jp.sotuken.metercapture.queue.sender

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class DeviceIdSidecarTest {
    private fun item(deviceId: String?, source: String?) = QueueItem(
        localId = "id-1",
        imagePath = "/photo.jpg",
        capturedAt = "2026-11-06T00:00:00Z",
        deviceName = "ボイラー圧力計",
        operatorValue = null,
        operatorNote = null,
        sendState = SendState.PENDING,
        retryCount = 0,
        lastError = null,
        sentAt = null,
        deviceId = deviceId,
        deviceIdSource = source,
    )

    private fun parse(json: String) = Json.parseToJsonElement(json) as JsonObject

    @Test fun qrDeviceIdAddsBothKeysAndKeepsExistingKeys() {
        val json = SenderPayloads.buildSidecarJson(item("A-101", "qr"))
        val obj = parse(json)
        assertEquals("A-101", obj["device_id"]?.jsonPrimitive?.content)
        assertEquals("qr", obj["device_id_source"]?.jsonPrimitive?.content)
        assertEquals("ボイラー圧力計", obj["device_name"]?.jsonPrimitive?.content)
        assertEquals(
            listOf("local_id", "captured_at", "device_name", "operator_value", "operator_note", "device_id", "device_id_source"),
            obj.keys.toList(),
        )
    }

    @Test fun listSourceSurvivesSidecar() {
        assertEquals("list", parse(SenderPayloads.buildSidecarJson(item("A-101", "list")))["device_id_source"]?.jsonPrimitive?.content)
    }
    @Test fun manualInputHasNeitherKey() {
        val json = SenderPayloads.buildSidecarJson(item(null, null))
        assertFalse(json.contains("device_id"))
        assertEquals(
            listOf("local_id", "captured_at", "device_name", "operator_value", "operator_note"),
            parse(json).keys.toList(),
        )
    }

    @Test fun httpHeaderPayloadCarriesTheSameKeys() {
        val encoded = SenderPayloads.buildSidecarJsonBase64Url(item("A-101", "qr"))
        val decoded = String(Base64.getUrlDecoder().decode(encoded), Charsets.UTF_8)
        assertTrue(decoded.contains("\"device_id\":\"A-101\""))
        assertTrue(decoded.contains("\"device_id_source\":\"qr\""))
    }

    @Test fun folderSenderWritesDeviceIdIntoJson() = kotlinx.coroutines.test.runTest {
        val dir = java.nio.file.Files.createTempDirectory("device-id-sidecar").toFile()
        try {
            val image = java.io.File(dir, "photo.jpg").apply { writeBytes(byteArrayOf(1, 2, 3)) }
            val out = java.io.File(dir, "out")
            val source = item("A-101", "qr").copy(imagePath = image.path)
            FolderSender(out).send(source).getOrThrow()
            val json = java.io.File(out, "${SenderPayloads.buildBaseName(source)}.json").readText()
            assertTrue(json.contains("\"device_id\":\"A-101\",\"device_id_source\":\"qr\""))
        } finally {
            dir.deleteRecursively()
        }
    }
}
