package jp.sotuken.metercapture.device

import jp.sotuken.metercapture.settings.DeviceIdSettings
import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HeldDeviceTest {
    private val held = HeldDevice("A-101", "ボイラー圧力計")

    @Test fun labelShowsIdWithQrSource() = assertEquals("機器ID: A-101(QR)", held.label())

    @Test fun sameNameKeepsDeviceId() {
        assertEquals(held, heldDeviceAfterNameEdit(held, "ボイラー圧力計"))
        assertEquals(held, heldDeviceAfterNameEdit(held, "  ボイラー圧力計 "))
    }

    @Test fun editingNameDetachesDeviceId() {
        assertNull(heldDeviceAfterNameEdit(held, "ボイラー圧力計2"))
        assertNull(heldDeviceAfterNameEdit(held, ""))
        assertNull(heldDeviceAfterNameEdit(null, "ボイラー圧力計"))
    }

    @Test fun captureGetsIdAndSourceOnlyWhileNameMatches() {
        assertEquals("A-101", deviceIdForCapture(held, "ボイラー圧力計"))
        assertEquals("qr", deviceIdSourceForCapture(held, "ボイラー圧力計"))
        assertNull(deviceIdForCapture(held, "手で書いた名前"))
        assertNull(deviceIdSourceForCapture(held, "手で書いた名前"))
        assertNull(deviceIdForCapture(null, "ボイラー圧力計"))
        assertNull(deviceIdSourceForCapture(null, "ボイラー圧力計"))
    }

    private val values = mutableMapOf<String, String?>()
    private val prefs = Proxy.newProxyInstance(
        SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java),
    ) { _, method, args ->
        when (method.name) {
            "getString" -> values[args!![0] as String] ?: args[1]
            "edit" -> {
                val pending = mutableMapOf<String, String?>()
                lateinit var editor: SharedPreferences.Editor
                editor = Proxy.newProxyInstance(
                    SharedPreferences.Editor::class.java.classLoader, arrayOf(SharedPreferences.Editor::class.java),
                ) { _, edit, items ->
                    when (edit.name) {
                        "putString" -> { pending[items!![0] as String] = items[1] as String?; editor }
                        "remove" -> { pending[items!![0] as String] = null; editor }
                        "apply" -> {
                            pending.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
                            null
                        }
                        else -> error("Unexpected editor method: ${edit.name}")
                    }
                } as SharedPreferences.Editor
                editor
            }
            else -> error("Unexpected preferences method: ${method.name}")
        }
    } as SharedPreferences

    @Test fun settingsKeepAndClearHeldDeviceAcrossInstances() {
        assertNull(DeviceIdSettings(prefs).get())
        DeviceIdSettings(prefs).save(held)
        assertEquals(held, DeviceIdSettings(prefs).get())
        DeviceIdSettings(prefs).clear()
        assertNull(DeviceIdSettings(prefs).get())
    }
}