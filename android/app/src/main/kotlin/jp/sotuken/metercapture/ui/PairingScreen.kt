package jp.sotuken.metercapture.ui

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import jp.sotuken.metercapture.pairing.*
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch

@Composable
internal fun PairingScreen(pendingCount: Int, onClose: () -> Unit) {
    val context = LocalContext.current
    val settings = remember { ReceiverSettings(context) }
    val scope = rememberCoroutineScope()
    var invitation by remember { mutableStateOf<PairingInvitation?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var reading by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf(true) }
    var hasPermission by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { hasPermission = it }
    val scanner = remember {
        BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    }
    DisposableEffect(scanner) {
        onDispose { active = false; scanner.close() }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().padding(24.dp).then(
                    if (invitation != null) Modifier.verticalScroll(rememberScrollState()) else Modifier,
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("送信先QRを読む", style = MaterialTheme.typography.headlineSmall)
                Text("PCの「スマホを登録」で表示したQRを撮影してください。")
                val current = invitation
                if (current == null && !reading) {
                    if (hasPermission) {
                        CameraCapturePanel(
                            temporaryCapture = true,
                            onSaved = { captured ->
                                if (!active) {
                                    captured.file.delete()
                                } else {
                                    reading = true
                                    error = null
                                    try {
                                        val image = InputImage.fromFilePath(context, Uri.fromFile(captured.file))
                                        scanner.process(image)
                                            .addOnSuccessListener { codes ->
                                                if (active) {
                                                    try {
                                                        val code = codes.singleOrNull()?.rawValue
                                                            ?: throw PairingException("登録用QRを1つだけ写して撮影してください")
                                                        invitation = parsePairingQr(code)
                                                    } catch (failure: PairingException) { error = failure.message }
                                                }
                                            }
                                            .addOnFailureListener { if (active) error = "QRを読み取れませんでした。撮影し直してください" }
                                            .addOnCompleteListener { captured.file.delete(); if (active) reading = false }
                                    } catch (_: Exception) {
                                        captured.file.delete()
                                        reading = false
                                        error = "QRを読み取れませんでした。撮影し直してください"
                                    }
                                }
                            },
                            onError = { error = "カメラを利用できません。権限を確認し、もう一度お試しください" },
                        )
                    } else {
                        Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("カメラを許可") }
                    }
                } else if (reading) {
                    Text("QRを読み取り中…")
                }
                if (current != null) {
                    Text("PC: ${current.pcName}")
                    Text("URL: ${current.url}")
                    if (System.currentTimeMillis() / 1000 >= current.expiresAt) {
                        Text("端末時刻では期限切れです。PCでQRを更新してください。時刻がずれている場合は確認して登録できます。最終判定はPCが行います。")
                    }
                    val changesPc = settings.getReceiverId() != current.receiverId && pendingCount > 0
                    if (changesPc) Text("PC未到着の写真が${pendingCount}件あります。既存の写真も新しいPCへ送ります。")
                    Button(enabled = !busy, onClick = {
                        busy = true
                        error = null
                        scope.launch {
                            try {
                                PairingClient().register(current, settings)
                                ensureActive()
                                if (active) {
                                    if (shouldEnqueueSendOnPairing(pendingCount)) {
                                        QueueSendScheduler.enqueueSend(context)
                                    }
                                    onClose()
                                }
                            } catch (cancelled: CancellationException) {
                                throw cancelled
                            } catch (failure: PairingException) {
                                error = failure.message
                            } catch (_: Exception) {
                                error = "登録処理を完了できませんでした。設定を確認してください"
                            } finally { busy = false }
                        }
                    }) {
                        Text(if (busy) "登録中…" else if (changesPc) "確認して登録し、新しいPCへ送る" else "確認して登録")
                    }
                    TextButton(enabled = !busy, onClick = { invitation = null; error = null }) { Text("読み直す") }
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                TextButton(onClick = onClose) { Text("キャンセル") }
            }
        }
    }
}
