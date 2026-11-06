package jp.sotuken.metercapture.device

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** QR機器ラベル仕様.md のテストケース表（PC側 parse_payload と共通）。 */
class DeviceQrTest {
    private fun accepted(text: String, id: String, name: String) {
        val qr = parseDeviceQr(text)
        assertEquals(id, qr?.id)
        assertEquals(name, qr?.name)
    }

    private fun rejected(text: String) = assertNull(text, parseDeviceQr(text))

    @Test fun row01_basicQr() =
        accepted("""{"v":1,"id":"A-101","name":"ボイラー圧力計"}""", "A-101", "ボイラー圧力計")

    @Test fun row02_trimsNameKeepsOptionalAndIgnoresUnknownKeys() {
        val qr = parseDeviceQr("""{"v":1,"id":"P.1_a-b","name":"  P-1  ","unit":"MPa","extra":1}""")
        assertEquals(DeviceQr("P.1_a-b", "P-1", "MPa", null, null), qr)
    }

    @Test fun row03_wrongVersion() = rejected("""{"v":2,"id":"A-101","name":"P-1"}""")

    @Test fun row04_legacyWithoutId() = rejected("""{"v":1,"name":"ボイラー圧力計A-101"}""")

    @Test fun row05_withoutName() = rejected("""{"v":1,"id":"A-101"}""")

    @Test fun row06_emptyId() = rejected("""{"v":1,"id":"","name":"P-1"}""")

    @Test fun row07_japaneseId() = rejected("""{"v":1,"id":"圧力計1","name":"P-1"}""")

    @Test fun row08_id33Chars() = rejected("""{"v":1,"id":"${"A".repeat(33)}","name":"P-1"}""")

    @Test fun row09_idWithSpace() = rejected("""{"v":1,"id":"A 101","name":"P-1"}""")

    @Test fun row10_emptyName() = rejected("""{"v":1,"id":"A-101","name":""}""")

    @Test fun row11_name65Chars() = rejected("""{"v":1,"id":"A-101","name":"${"A".repeat(65)}"}""")

    @Test fun row12_notJson() = rejected("P-1")

    @Test fun boundaries32CharIdAnd64CharNameAreAccepted() =
        accepted("""{"v":1,"id":"${"A".repeat(32)}","name":"${"あ".repeat(64)}"}""", "A".repeat(32), "あ".repeat(64))

    @Test fun optionalUnitMinMaxAreRead() {
        val qr = parseDeviceQr("""{"v":1,"id":"A-101","name":"P-1","unit":"MPa","min":0,"max":1.5}""")
        assertEquals(DeviceQr("A-101", "P-1", "MPa", 0.0, 1.5), qr)
    }

    @Test fun invalidOptionalValuesAreDroppedNotRejected() {
        val qr = parseDeviceQr("""{"v":1,"id":"A-101","name":"P-1","unit":5,"min":"0","max":true}""")
        assertEquals(DeviceQr("A-101", "P-1", null, null, null), qr)
    }

    @Test fun likePythonVersionMustBeNumberOneNotStringOrBoolean() {
        rejected("""{"v":"1","id":"A-101","name":"P-1"}""")
        rejected("""{"v":true,"id":"A-101","name":"P-1"}""")
        rejected("""{"id":"A-101","name":"P-1"}""")
        accepted("""{"v":1.0,"id":"A-101","name":"P-1"}""", "A-101", "P-1")
    }

    @Test fun likePythonNameWithControlCharacterIsRejectedEvenAtEdges() {
        rejected("{\"v\":1,\"id\":\"A-101\",\"name\":\"P\\n1\"}")
        rejected("{\"v\":1,\"id\":\"A-101\",\"name\":\"P-1\\n\"}")
        rejected("{\"v\":1,\"id\":\"A-101\",\"name\":\"P\\u200b1\"}")
    }

    @Test fun likePythonWhitespaceOnlyNameAndNonStringFieldsAreRejected() {
        rejected("""{"v":1,"id":"A-101","name":"   "}""")
        rejected("""{"v":1,"id":101,"name":"P-1"}""")
        rejected("""{"v":1,"id":"A-101","name":1}""")
        rejected("""["v",1]""")
        rejected("")
    }
}