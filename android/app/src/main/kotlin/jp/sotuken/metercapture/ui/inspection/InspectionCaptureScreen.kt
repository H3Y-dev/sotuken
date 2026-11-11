package jp.sotuken.metercapture.ui.inspection

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import java.io.File
import java.time.Instant
import jp.sotuken.metercapture.inspection.Inspection
import jp.sotuken.metercapture.queue.CaptureMeta
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.route.parseRouteJson
import jp.sotuken.metercapture.ui.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun InspectionCaptureScreen(
    inspection: Inspection,
    photos: List<QueueItem>,
    health: ReceiverHealthState,
    initialTarget: CaptureTarget?,
    onSaved: suspend (File, CaptureMeta) -> Unit,
    onHistory: () -> Unit,
    onComplete: () -> Unit,
    onHome: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val route = remember(inspection.routeSnapshot) { inspection.routeSnapshot?.let { parseRouteJson(it)?.devices } }
    val firstTarget = initialTarget ?: initialTarget(route, photos)
    var targetId by rememberSaveable(inspection.inspectionId) { mutableStateOf(firstTarget?.deviceId) }
    var targetName by rememberSaveable(inspection.inspectionId) { mutableStateOf(firstTarget?.deviceName) }
    var targetSource by rememberSaveable(inspection.inspectionId) { mutableStateOf(firstTarget?.source) }
    val target = if (targetId == null && targetName == null) null else CaptureTarget(targetId, targetName, targetSource)
    fun select(next: CaptureTarget?) {
        targetId = next?.deviceId
        targetName = next?.deviceName
        targetSource = next?.source
    }
    LaunchedEffect(initialTarget) { if (initialTarget != null) select(initialTarget) }
    var saved by rememberSaveable(inspection.inspectionId, stateSaver = listSaver<SavedCard?, String?>(
        save = { card -> card?.let { listOf(it.imagePath, it.deviceName, it.deviceId, it.capturedAt) }.orEmpty() },
        restore = { fields -> if (fields.isEmpty()) null else SavedCard(checkNotNull(fields[0]), fields[1], fields[2], checkNotNull(fields[3])) },
    )) { mutableStateOf<SavedCard?>(null) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var manual by remember { mutableStateOf(false) }
    var scanning by remember { mutableStateOf(false) }
    var hasPermission by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { hasPermission = it }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        hasPermission = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        health.check()
    }
    val state = buildCaptureUiState(inspection, route, photos, target, saved)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(if (saved == null) "点検中の撮影" else "撮影できました", style = MaterialTheme.typography.headlineSmall)
        Text(state.header, style = MaterialTheme.typography.titleMedium)
        Text(state.progress)
        if (saved == null && !saving) {
            state.missingChips.forEach { device ->
                OutlinedButton(onClick = {
                    if (!shouldKeepQrTarget(target, device)) select(targetFromRoute(device))
                }) { Text("未撮影：${device.name} ${device.id}") }
            }
            if (hasPermission) DeviceQrSection(null, { scanning = it }, { select(targetFromQr(it)) }, {})
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text(state.targetName, style = MaterialTheme.typography.titleLarge)
                    Text(state.targetId)
                    Text("出所: ${state.targetSourceLabel}")
                    TextButton(onClick = { manual = true }) { Text("機器名・IDを手入力する") }
                }
            }
            if (!hasPermission) {
                Text("カメラの使用を許可してください")
                Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) { Text("許可") }
            } else if (!scanning) {
                Column(Modifier.fillMaxWidth().height(360.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    CameraCapturePanel(large = true, onError = { error = it }, onSaved = { captured ->
                        val capturedTarget = target
                        select(capturedTarget)
                        saving = true
                        error = null
                        scope.launch {
                            try {
                                onSaved(captured.file, (capturedTarget ?: CaptureTarget(null, null, null)).toMeta())
                                saved = SavedCard(captured.file.absolutePath, capturedTarget?.deviceName, capturedTarget?.deviceId, Instant.ofEpochMilli(captured.capturedAtEpochMillis).toString())
                            } catch (e: CancellationException) { throw e
                            } catch (e: Exception) { error = "保存に失敗しました: ${e.message}"
                            } finally { saving = false }
                        }
                    })
                }
            }
        }
        if (saving) Text("保存中...")
        state.justSaved?.let { card ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Thumbnail(card.imagePath, Modifier.fillMaxWidth().height(160.dp))
                    Text(card.deviceName ?: "機器名なし", style = MaterialTheme.typography.titleMedium)
                    Text(card.deviceId ?: "機器IDなし")
                    val savedAt = photos.firstOrNull { it.imagePath == card.imagePath }?.capturedAt ?: card.capturedAt
                    Text("${formatInspectionCaptureTime(savedAt)} 撮影")
                }
            }
            Button(onClick = {
                select(targetAfterCapture(route, photos, target))
                saved = null
            }, enabled = photos.any { it.imagePath == card.imagePath }, modifier = Modifier.fillMaxWidth()) { Text("次の機器を撮る") }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Text(state.countLine, style = MaterialTheme.typography.titleMedium)
        OutlinedButton(onClick = onHistory, enabled = !saving, modifier = Modifier.fillMaxWidth()) { Text(if (saved == null) "この点検の履歴を見る" else "履歴を確認する") }
        OutlinedButton(onClick = onComplete, enabled = !saving, modifier = Modifier.fillMaxWidth()) { Text("点検完了へ") }
        TextButton(onClick = onHome, enabled = !saving) { Text("点検一覧") }
    }
    if (manual) ManualDeviceDialog(target, { manual = false }) { select(it); manual = false }
}

@Composable
private fun ManualDeviceDialog(target: CaptureTarget?, onDismiss: () -> Unit, onUse: (CaptureTarget) -> Unit) {
    var name by rememberSaveable { mutableStateOf(target?.deviceName.orEmpty()) }
    var id by rememberSaveable { mutableStateOf(target?.deviceId.orEmpty()) }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("機器名・IDを手入力する") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(name, { name = it; error = null }, label = { Text("機器名") }, singleLine = true)
                OutlinedTextField(id, { id = it; error = null }, label = { Text("機器ID（任意）") }, singleLine = true)
                Text("撮影する機器のラベルと確認してください。")
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { TextButton(onClick = {
            manualTarget(name, id).fold(onSuccess = onUse, onFailure = { error = it.message })
        }) { Text("この機器を使う") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}
