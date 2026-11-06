package jp.sotuken.metercapture.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import jp.sotuken.metercapture.device.DeviceQr
import jp.sotuken.metercapture.device.HeldDevice
import jp.sotuken.metercapture.device.label
import jp.sotuken.metercapture.device.parseDeviceQr

internal const val NOT_DEVICE_QR_MESSAGE = "機器のQRではありません"

/** 読み取った複数のQR文字列から、最初に機器QRとして読めたものを返す。無ければ null。 */
internal fun pickDeviceQr(codes: List<String>): DeviceQr? = codes.firstNotNullOfOrNull { parseDeviceQr(it) }

/**
 * 撮影画面の「機器QRを読む」。読めたら確認表示を出し、「使う」で [onUse] を呼ぶ。
 * 保持中の機器IDは「機器ID: A-101(QR)」と見せ、「解除」で [onClear] を呼ぶ。
 */
@Composable
internal fun DeviceQrSection(
    held: HeldDevice?,
    onScanningChange: (Boolean) -> Unit,
    onUse: (DeviceQr) -> Unit,
    onClear: () -> Unit,
) {
    var scanning by remember { mutableStateOf(false) }
    var scanned by remember { mutableStateOf<DeviceQr?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    fun setScanning(value: Boolean) {
        scanning = value
        onScanningChange(value)
    }

    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = { error = null; setScanning(true) }) { Text("機器QRを読む") }
        if (held != null) {
            Text(held.label(), style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = onClear) { Text("解除") }
        }
    }

    if (scanning) {
        Dialog(
            onDismissRequest = { setScanning(false) },
            properties = DialogProperties(usePlatformDefaultWidth = false),
        ) {
            Surface(modifier = Modifier.fillMaxSize()) {
                Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("機器QRを読む", style = MaterialTheme.typography.headlineSmall)
                    Text("機器のラベルのQRを撮影してください。")
                    QrScanPanel(
                        onCodes = { codes ->
                            val qr = pickDeviceQr(codes)
                            if (qr != null) {
                                scanned = qr
                                error = null
                                setScanning(false)
                            } else {
                                error = if (codes.isEmpty()) {
                                    "QRを読み取れませんでした。撮影し直してください"
                                } else {
                                    NOT_DEVICE_QR_MESSAGE
                                }
                            }
                        },
                        onError = { error = it },
                    )
                    error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    TextButton(onClick = { setScanning(false) }) { Text("キャンセル") }
                }
            }
        }
    }
    if (!scanning) {
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }

    scanned?.let { qr ->
        AlertDialog(
            onDismissRequest = { scanned = null },
            title = { Text("この機器を使いますか？") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("機器名: ${qr.name}")
                    Text("機器ID: ${qr.id}")
                }
            },
            confirmButton = {
                Button(onClick = { onUse(qr); scanned = null }) { Text("使う") }
            },
            dismissButton = {
                TextButton(onClick = { scanned = null }) { Text("キャンセル") }
            },
        )
    }
}