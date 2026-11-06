package jp.sotuken.metercapture.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import jp.sotuken.metercapture.capture.CapturedImage
import jp.sotuken.metercapture.device.HeldDevice
import jp.sotuken.metercapture.device.deviceIdForCapture
import jp.sotuken.metercapture.device.deviceIdSourceForCapture
import jp.sotuken.metercapture.device.heldDeviceAfterNameEdit
import jp.sotuken.metercapture.queue.CaptureMeta
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.queue.QueueStore
import jp.sotuken.metercapture.settings.DeviceIdSettings
import jp.sotuken.metercapture.settings.PrivateIpv4Validator
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.launch
import androidx.compose.runtime.saveable.rememberSaveable

@Composable
fun MeterCaptureApp(queueStore: QueueStore) {
    val context = LocalContext.current
    val queueItems by queueStore.observeQueue().collectAsStateWithLifecycle(initialValue = emptyList())
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var capturedImage by remember { mutableStateOf<CapturedImage?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var showSettingsDialog by remember { mutableStateOf(false) }
    var showPairingScreen by remember { mutableStateOf(false) }
    val deviceIdSettings = remember { DeviceIdSettings(context) }
    var heldDevice by remember { mutableStateOf<HeldDevice?>(deviceIdSettings.get()) }
    var deviceQrScanning by remember { mutableStateOf(false) }
	var showHistoryScreen by remember { mutableStateOf(false) }
	val deviceNameCandidates = remember(queueItems) { buildDeviceNameCandidates(queueItems) }
    // 入力済みの機器名は撮影のたびに残す。まだ触っていなければ、直前に撮った機器名を初期値にする。
    var deviceNameEdited by rememberSaveable { mutableStateOf<String?>(heldDevice?.name) }
    val deviceNameInput = deviceNameEdited ?: deviceNameCandidates.firstOrNull().orEmpty()
    var operatorValueInput by rememberSaveable { mutableStateOf("") }

    val coroutineScope = rememberCoroutineScope()
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasCameraPermission = granted
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        hasCameraPermission =
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    MaterialTheme {
        Scaffold { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(text = "メーター撮影", style = MaterialTheme.typography.headlineMedium)

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(text = "キュー: ${queueItems.size}件")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { showHistoryScreen = true }) {
                            Text("履歴")
                        }
                        OutlinedButton(onClick = { showSettingsDialog = true }) {
                            Text("送信先の設定")
                        }
                    }
                }

                DeviceQrSection(
                    held = heldDevice,
                    onScanningChange = { deviceQrScanning = it },
                    onUse = { qr ->
                        val device = HeldDevice(qr.id, qr.name)
                        deviceIdSettings.save(device)
                        heldDevice = device
                        deviceNameEdited = qr.name
                    },
                    onClear = {
                        deviceIdSettings.clear()
                        heldDevice = null
                    },
                )

                if (hasCameraPermission && !showPairingScreen && !deviceQrScanning) {
                	CaptureMetaForm(
                        deviceName = deviceNameInput,
                        onDeviceNameChange = {
                            deviceNameEdited = it
                            val kept = heldDeviceAfterNameEdit(heldDevice, it)
                            if (kept == null && heldDevice != null) deviceIdSettings.clear()
                            heldDevice = kept
                        },
                        operatorValue = operatorValueInput,
                        onOperatorValueChange = { operatorValueInput = it },
                        deviceNameCandidates = deviceNameCandidates,
                    )
                    CameraCapturePanel(
                        onSaved = { image ->
                            coroutineScope.launch {
                                try {
                                    queueStore.enqueue(
                                        imageFile = image.file,
                                        meta = CaptureMeta(
                                            deviceName = normalizeDeviceName(deviceNameInput),
                                            operatorValue = parseOperatorValue(operatorValueInput),
                                            operatorNote = null,
                                            deviceId = deviceIdForCapture(heldDevice, deviceNameInput),
                                            deviceIdSource = deviceIdSourceForCapture(heldDevice, deviceNameInput),
                                        ),
                                    )
                                    try {
                                        QueueSendScheduler.enqueueSend(context)
                                    } catch (_: Exception) {
                                    }
                                    capturedImage = image
                                    operatorValueInput = ""
                                    errorMessage = null
                                } catch (error: Exception) {
                                    capturedImage = null
                                    errorMessage = "キューへの追加に失敗しました: ${error.message ?: error}"
                                }
                            }
                        },
                        onError = {
                            capturedImage = null
                            errorMessage = it
                        },
                    )
                } else {
                    Text("カメラの使用を許可してください")
                    Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                        Text("許可")
                    }
                }

                capturedImage?.let { Text("キューに追加しました: ${it.file.name}") }
                errorMessage?.let {
                    Text(text = it, color = MaterialTheme.colorScheme.error)
                }

                // TODO(SKくん): ガイド枠・キュー一覧・入力フォームを実装する。Sprint 3
            }
        }
        if (showHistoryScreen) {
            QueueListScreen(
                items = queueItems,
                onDelete = { localId -> queueStore.delete(localId) },
                currentReceiverId = ReceiverSettings(context).getReceiverId(),
                onClose = { showHistoryScreen = false },
                onRetry = { localId ->
                    coroutineScope.launch {
                        try {
                            queueStore.retry(localId)
                            QueueSendScheduler.enqueueSend(context)
                        } catch (_: Exception) {
                        }
                    }
                },
                onReassignReceiver = { localId ->
                    coroutineScope.launch {
                        try {
                            queueStore.reassignReceiver(localId, ReceiverSettings(context).getReceiverId())
                            QueueSendScheduler.enqueueSend(context)
                        } catch (error: Exception) {
                            errorMessage = "送り直しに失敗しました: ${error.message ?: error}"
                        }
                    }
                },
                onSendNow = {
                    try {
                        QueueSendScheduler.enqueueSend(context)
                    } catch (_: Exception) {
                    }
                },
            )
        }
        
        if (showPairingScreen) {
            PairingScreen(
                pendingCount = queueItems.count {
                    it.sendState != jp.sotuken.metercapture.queue.SendState.SENT ||
                        it.sentVia != jp.sotuken.metercapture.queue.QueueItem.VIA_HTTP
                },
                onClose = { showPairingScreen = false },
            )
        }
        if (showSettingsDialog) {
            val receiverSettings = remember { ReceiverSettings(context) }
            var urlInput by remember { mutableStateOf(receiverSettings.getUrl() ?: "") }
            var tokenInput by remember { mutableStateOf(receiverSettings.getToken() ?: "") }
            var validationError by remember { mutableStateOf<String?>(null) }

            AlertDialog(
                onDismissRequest = { showSettingsDialog = false },
                title = { Text("送信先の設定") },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            showSettingsDialog = false
                            showPairingScreen = true
                        }) { Text("QRで登録") }
                        OutlinedTextField(
                            value = urlInput,
                            onValueChange = {
                                urlInput = it
                                validationError = null
                            },
                            label = { Text("送信先URL (例: http://192.168.1.20:8765)") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = tokenInput,
                            onValueChange = {
                                tokenInput = it
                                validationError = null
                            },
                            label = { Text("合言葉 (Token)") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        validationError?.let {
                            Text(
                                text = it,
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            when (val result = PrivateIpv4Validator.validateUrl(urlInput)) {
                                is PrivateIpv4Validator.ValidationResult.Invalid -> {
                                    validationError = result.message
                                }
                                PrivateIpv4Validator.ValidationResult.Valid -> {
                                    if (tokenInput.isBlank()) {
                                        validationError = "合言葉を入力してください"
                                    } else {
                                        receiverSettings.save(urlInput, tokenInput)
                                        try {
                                            QueueSendScheduler.enqueueSend(context)
                                        } catch (_: Exception) {
                                        }
                                        showSettingsDialog = false
                                    }
                                }
                            }
                        },
                    ) {
                        Text("保存")
                    }
                },
                dismissButton = {
                    TextButton(onClick = { showSettingsDialog = false }) {
                        Text("キャンセル")
                    }
                },
            )
        }
    }
}
