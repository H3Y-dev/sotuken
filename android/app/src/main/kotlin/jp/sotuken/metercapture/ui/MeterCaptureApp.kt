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
import androidx.compose.runtime.LaunchedEffect
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
import jp.sotuken.metercapture.queue.CaptureMeta
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.queue.QueueStore
import jp.sotuken.metercapture.queue.sender.HttpSender
import jp.sotuken.metercapture.settings.PrivateIpv4Validator
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
    var showHistoryScreen by remember { mutableStateOf(false) }
    val deviceNameCandidates = remember(queueItems) { buildDeviceNameCandidates(queueItems) }
    // 入力済みの機器名は撮影のたびに残す。まだ触っていなければ、直前に撮った機器名を初期値にする。
    var deviceNameEdited by rememberSaveable { mutableStateOf<String?>(null) }
    val deviceNameInput = deviceNameEdited ?: deviceNameCandidates.firstOrNull().orEmpty()
    var operatorValueInput by rememberSaveable { mutableStateOf("") }

    val coroutineScope = rememberCoroutineScope()

    // 接続状況バー用の状態（SK-09）
    val receiverSettings = remember { ReceiverSettings(context) }
    var settingsVersion by remember { mutableStateOf(0) }
    val configured = remember(settingsVersion) { receiverSettings.isConfigured() }
    var healthOk by remember { mutableStateOf<Boolean?>(null) }
    var healthReason by remember { mutableStateOf("") }
    var healthInFlight by remember { mutableStateOf(false) }
    var healthGeneration by remember { mutableStateOf(0) }
    var isResumed by remember { mutableStateOf(false) }
    var showStatusDialog by remember { mutableStateOf(false) }

    fun checkHealth(force: Boolean = false) {
        val url = receiverSettings.getUrl()
        val token = receiverSettings.getToken()
        if (!receiverSettings.isConfigured() || url.isNullOrBlank() || token.isNullOrBlank()) {
            healthOk = null
            return
        }
        if (healthInFlight && !force) return
        healthInFlight = true
        healthGeneration += 1
        val generation = healthGeneration
        coroutineScope.launch {
            val result = withContext(Dispatchers.IO) { HttpSender.health(url, token) }
            if (generation == healthGeneration) {
                healthOk = result.isSuccess
                healthReason = classifyHealthFailure(result.exceptionOrNull())
                healthInFlight = false
            }
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasCameraPermission = granted
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        hasCameraPermission =
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        isResumed = true
        checkHealth()
    }
    LifecycleEventEffect(Lifecycle.Event.ON_PAUSE) { isResumed = false }
    LaunchedEffect(isResumed) {
        if (isResumed) {
            while (true) {
                delay(15_000)
                checkHealth()
            }
        }
    }

    val barState = connectionBarState(configured, healthOk)
    val undelivered = countUndelivered(queueItems)
    val lastSentText = formatHHmm(latestHttpSentAt(queueItems))
    val barText = connectionBarText(barState, undelivered, lastSentText, healthReason)
    val lastFailure = queueItems
        .filter { !it.lastError.isNullOrBlank() }
        .maxByOrNull { it.capturedAt }
        ?.lastError

    MaterialTheme {
        Scaffold { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            ) {
                ConnectionBar(
                    state = barState,
                    text = barText,
                    onClick = {
                        if (barState == ConnectionBarState.NOT_CONFIGURED) {
                            showSettingsDialog = true
                        } else {
                            showStatusDialog = true
                        }
                    },
                )
                Column(
                    modifier = Modifier
                        .fillMaxSize()
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

                    if (hasCameraPermission && !showPairingScreen) {
                        CaptureMetaForm(
                            deviceName = deviceNameInput,
                            onDeviceNameChange = { deviceNameEdited = it },
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
                                            ),
                                        )
                                        try {
                                            QueueSendScheduler.enqueueSend(context)
                                        } catch (_: Exception) {
                                        }
                                        capturedImage = image
                                        operatorValueInput = ""
                                        errorMessage = null
                                        checkHealth()
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
        }
        if (showHistoryScreen) {
            QueueListScreen(
                items = queueItems,
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
                onClose = {
                    showPairingScreen = false
                    settingsVersion += 1
                    healthOk = null
                    checkHealth(force = true)
                },
            )
        }
        if (showSettingsDialog) {
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
                                        settingsVersion += 1
                                        healthOk = null
                                        checkHealth(force = true)
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
        if (showStatusDialog) {
            AlertDialog(
                onDismissRequest = { showStatusDialog = false },
                title = { Text("接続の詳細") },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("接続の結果: ${connectionResultLabel(barState, healthReason)}")
                        Text("PCのURL: ${receiverSettings.getUrl() ?: "未設定"}")
                        Text("最終送信: $lastSentText")
                        Text("未着: ${undelivered}件")
                        Text("直近の失敗の理由: ${lastFailure ?: "なし"}")
                    }
                },
                confirmButton = {
                    TextButton(onClick = { showStatusDialog = false }) {
                        Text("閉じる")
                    }
                },
            )
        }
    }
}