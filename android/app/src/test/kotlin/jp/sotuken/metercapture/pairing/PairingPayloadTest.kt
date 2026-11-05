package jp.sotuken.metercapture.pairing

import org.junit.Assert.*
import org.junit.Test

class PairingPayloadTest {
    private val json = """{"v":1,"kind":"receiver-pair","url":"http://192.168.1.20:8765","token":"temporary-secret","receiver_id":"a87d8c38-9186-4c32-a827-95057a1a1b36","pc_name":"検査PC","expires_at":1793920200}"""
    private fun parse(body: String = json) = parsePairingQr("SOTUKEN-PAIR:$body")

    @Test fun acceptsValidQr() {
        val value = parse()
        assertEquals("検査PC", value.pcName)
        assertEquals(1793920200L, value.expiresAt)
        assertFalse(value.toString().contains("temporary-secret"))
    }

    @Test fun rejectsWrongPrefixAndEquipmentQr() {
        for (value in listOf(json, "sotuken-pair:$json", " SOTUKEN-PAIR:$json", """{"v":1,"id":"1","name":"meter"}""")) {
            assertThrows(PairingException::class.java) { parsePairingQr(value) }
        }
    }

    @Test fun rejectsInvalidJsonAndTypes() {
        for (value in listOf("{", "[]", "$json trailing", "{'v':1}", json.replace("\"v\":1", "\"v\":true"), json.replace("\"v\":1", "\"v\":1.0"), json.replace("\"v\":1", "\"v\":\"1\""), json.replace("\"v\":1", "\"v\":2"), json.replace("receiver-pair", "device"), json.replace("1793920200", "1.2"), json.replace("1793920200", "true"), json.replace("1793920200", "9223372036854775808"))) {
            assertThrows(value, PairingException::class.java) { parse(value) }
        }
    }

    @Test fun rejectsUnsafeUrls() {
        for (url in listOf("https://192.168.1.20:8765", "http://8.8.8.8:80", "http://127.0.0.1:80", "http://localhost:80", "http://192.168.1.20", "http://192.168.1.20:0", "http://192.168.1.20:65536", "http://u@192.168.1.20:80", "http://192.168.1.20:80/", "http://192.168.1.20:80/a", "http://192.168.1.20:80?x", "http://192.168.1.20:80#x", " http://192.168.1.20:80", "http://192.168.01.20:80")) {
            assertThrows(url, PairingException::class.java) { parse(json.replace("http://192.168.1.20:8765", url)) }
        }
    }

    @Test fun rejectsMissingAndInvalidFieldsWithoutLeakingSecrets() {
        for (value in listOf(json.replace("temporary-secret", ""), json.replace("\"token\":\"temporary-secret\",", ""), json.replace("検査PC", ""), json.replace("検査PC", "x".repeat(65)), json.replace("検査PC", "a\\n"), json.replace("a87d8c38-9186-4c32-a827-95057a1a1b36", "invalid"))) {
            val error = assertThrows(PairingException::class.java) { parse(value) }
            assertFalse(error.message.orEmpty().contains("temporary-secret"))
        }
    }

    @Test fun limitsUtf8Bytes() {
        assertThrows(PairingException::class.java) { parse(json.replace("検査PC", "あ".repeat(700))) }
    }
}
