package jp.sotuken.metercapture.ui

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import java.net.Inet4Address
import java.net.NetworkInterface

data class NetworkSnapshot(val wifi: Boolean, val wired: Boolean, val usbTether: Boolean)

fun networkLabel(snapshot: NetworkSnapshot): String = when {
    snapshot.wifi && snapshot.usbTether -> "Wi-Fi＋USBテザリング"
    snapshot.wifi -> "Wi-Fi"
    snapshot.usbTether -> "USBテザリング"
    snapshot.wired -> "有線LAN"
    else -> "未接続"
}

fun isUsbTetherInterfaceName(name: String): Boolean = Regex("^(rndis|usb|ncm)\\d+$").matches(name)

fun readNetworkSnapshot(context: Context, capabilities: Collection<NetworkCapabilities>? = null): NetworkSnapshot {
    val manager = context.getSystemService(ConnectivityManager::class.java)
    val caps = capabilities ?: listOfNotNull(manager.activeNetwork?.let(manager::getNetworkCapabilities))
    val usb = runCatching { NetworkInterface.getNetworkInterfaces()?.toList().orEmpty().any {
        it.isUp && !it.isLoopback && isUsbTetherInterfaceName(it.name) && it.inetAddresses.toList().any { address -> address is Inet4Address }
    } }.getOrDefault(false)
    return NetworkSnapshot(caps.any { it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) }, caps.any {
        it.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) || (Build.VERSION.SDK_INT >= 31 && it.hasTransport(NetworkCapabilities.TRANSPORT_USB))
    }, usb)
}

fun connectionBarTextWithNetwork(snapshot: NetworkSnapshot, state: ConnectionBarState, undelivered: Int, lastSent: String, reason: String): String =
    "${networkLabel(snapshot)}　${connectionBarText(state, undelivered, lastSent, reason)}"

fun shouldTriggerAutoSend(previous: Boolean?, now: Boolean, hasWork: Boolean): Boolean = now && previous != true && hasWork
