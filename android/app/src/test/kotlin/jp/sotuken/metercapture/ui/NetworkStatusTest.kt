package jp.sotuken.metercapture.ui

import org.junit.Assert.*
import org.junit.Test

class NetworkStatusTest {
    @Test fun labels() {
        assertEquals("Wi-Fi", networkLabel(NetworkSnapshot(true, false, false)))
        assertEquals("USBテザリング", networkLabel(NetworkSnapshot(false, false, true)))
        assertEquals("Wi-Fi＋USBテザリング", networkLabel(NetworkSnapshot(true, false, true)))
        assertEquals("有線LAN", networkLabel(NetworkSnapshot(false, true, false)))
        assertEquals("未接続", networkLabel(NetworkSnapshot(false, false, false)))
    }
    @Test fun usbTetherInterfaceNames() {
        listOf("rndis0", "usb0", "ncm0", "usb12").forEach { assertTrue(isUsbTetherInterfaceName(it)) }
        listOf("wlan0", "rmnet0", "usb", "usb0x").forEach { assertFalse(isUsbTetherInterfaceName(it)) }
    }
    @Test fun barTextPrefixesNetwork() {
        val state = connectionBarState(true, true)
        assertEquals("Wi-Fi　${connectionBarText(state, 2, "", "")}", connectionBarTextWithNetwork(NetworkSnapshot(true, false, false), state, 2, "", ""))
    }
    @Test fun autoSendTriggersOnlyOnEdgeWithWork() {
        for (previous in listOf(null, false, true)) for (now in listOf(false, true)) for (work in listOf(false, true)) {
            assertEquals(now && previous != true && work, shouldTriggerAutoSend(previous, now, work))
        }
    }
}
