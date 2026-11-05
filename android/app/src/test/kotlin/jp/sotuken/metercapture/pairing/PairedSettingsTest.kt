package jp.sotuken.metercapture.pairing

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import jp.sotuken.metercapture.settings.ReceiverSettings
import org.junit.Assert.*
import org.junit.Test

class PairedSettingsTest {
    private val values = mutableMapOf<String, String?>()
    private var applies = 0
    private val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java)) { _, method, args ->
        when (method.name) {
            "getString" -> values[args!![0]] ?: args[1]
            "edit" -> {
                val pending = mutableMapOf<String, String?>()
                lateinit var editor: SharedPreferences.Editor
                editor = Proxy.newProxyInstance(SharedPreferences.Editor::class.java.classLoader, arrayOf(SharedPreferences.Editor::class.java)) { _, edit, items ->
                    when (edit.name) {
                        "putString" -> { pending[items!![0] as String] = items[1] as String?; editor }
                        "remove" -> { pending[items!![0] as String] = null; editor }
                        "apply" -> { values.putAll(pending); applies++; null }
                        else -> error("Unexpected editor method: ${edit.name}")
                    }
                } as SharedPreferences.Editor
                editor
            }
            else -> error("Unexpected preferences method: ${method.name}")
        }
    } as SharedPreferences
    private val settings = ReceiverSettings(prefs)
    private val receiver get() = PairedReceiver("http://10.0.0.1:8765", "shared", "a87d8c38-9186-4c32-a827-95057a1a1b36", "検査PC")

    @Test fun replacesAllFourFieldsInOneApply() {
        settings.save("192.168.0.2:8765", "old")
        settings.savePaired(receiver)
        assertEquals(2, applies)
        assertEquals(receiver.url, settings.getUrl())
        assertEquals(receiver.token, settings.getToken())
        assertEquals(receiver.receiverId, settings.getReceiverId())
        assertEquals(receiver.pcName, settings.getPcName())
    }

    @Test fun invalidPairingKeepsOldSettings() {
        settings.savePaired(receiver)
        val old = values.toMap()
        for (bad in listOf(
            PairedReceiver("http://8.8.8.8:80", "new", receiver.receiverId, "new"),
            PairedReceiver(receiver.url, "", receiver.receiverId, "new"),
            PairedReceiver(receiver.url, "new", "invalid", "new"),
            PairedReceiver(receiver.url, "new", receiver.receiverId, "\n"),
        )) {
            assertThrows(Exception::class.java) { settings.savePaired(bad) }
            assertEquals(old, values)
        }
        assertEquals(1, applies)
    }

    @Test fun manuallyChangedSettingsClearStaleIdentity() {
        settings.savePaired(receiver)
        settings.save("192.168.1.50:8765", "manual")
        assertNull(settings.getReceiverId())
        assertNull(settings.getPcName())
        assertEquals("manual", settings.getToken())
    }
}
