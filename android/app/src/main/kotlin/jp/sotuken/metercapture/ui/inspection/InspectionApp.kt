package jp.sotuken.metercapture.ui.inspection

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.time.ZonedDateTime
import jp.sotuken.metercapture.inspection.*
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.settings.ReceiverSettings
import jp.sotuken.metercapture.ui.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun InspectionApp(queueStore: QueueStore, inspectionStore: InspectionStore) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val health = rememberReceiverHealth()
    val settings = remember { ReceiverSettings(context) }
    val legacy = remember(queueStore) { LegacyQueueView(queueStore) }
    val inspections by remember(inspectionStore) { inspectionStore.observeInspections() }.collectAsStateWithLifecycle(emptyList())
    val photos by remember(queueStore) { queueStore.observeQueue() }.collectAsStateWithLifecycle(emptyList())
    var stack by rememberSaveable { mutableStateOf(listOf(AppScreen.Home.encode())) }
    val screen = decodeAppScreen(stack.last())
    fun home() { stack = listOf(AppScreen.Home.encode()) }
    fun back() { if (stack.size > 1) stack = stack.dropLast(1) else home() }
    fun open(next: AppScreen) { stack = stack + next.encode() }
    BackHandler(stack.size > 1) { back() }
    var showSettings by remember { mutableStateOf(false) }
    var showPairing by remember { mutableStateOf(false) }
    var showStatus by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var starting by remember { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    var operator by rememberSaveable { mutableStateOf("") }
    var place by rememberSaveable { mutableStateOf("") }
    var placeholder by rememberSaveable { mutableStateOf("") }

    LaunchedEffect(screen, inspections) {
        val id = screen.inspectionIdOrNull() ?: return@LaunchedEffect
        val found = inspectionStore.observeInspection(id).first()
        val resolved = resolveScreen(screen, found?.state)
        if (resolved != screen) {
            if (resolved == AppScreen.Home) home() else stack = stack.dropLast(1) + resolved.encode()
        }
    }

    MaterialTheme {
        if (screen == AppScreen.LegacyCapture) {
            Column {
                TextButton(onClick = { home() }) { Text("点検一覧") }
                MeterCaptureApp(legacy, health)
            }
        } else {
            InspectionScaffold(
                title = when (screen) { AppScreen.Home -> "点検の一覧"; AppScreen.Create -> "新しい点検"; else -> "点検" },
                health = health,
                barUndelivered = countUndelivered(photos),
                onBarClick = { showStatus = true; health.check(force = true) },
                onHome = if (screen == AppScreen.Home) null else ({ home() }),
            ) {
                when (screen) {
                    AppScreen.Home -> InspectionHomeScreen(
                        buildHomeUiState(inspections, photos.filter { it.inspectionId == null }, photos.filter { it.inspectionId != null }.groupBy { it.inspectionId!! }),
                        onCreate = {
                            scope.launch {
                                val latest = inspectionStore.observeInspections().first()
                                name = ""
                                operator = latest.firstOrNull()?.inspection?.operatorName.orEmpty()
                                place = latest.firstOrNull()?.inspection?.place.orEmpty()
                                placeholder = defaultInspectionName(ZonedDateTime.now(), latest.map { it.inspection.name })
                                error = null
                                stack = listOf(AppScreen.Home.encode(), AppScreen.Create.encode())
                            }
                        },
                        onOpen = { open(it) }, onSettings = { showSettings = true }, onGuide = { showStatus = true }, onRoutes = null, onLegacy = { open(AppScreen.LegacyCapture) },
                    )
                    AppScreen.Create -> InspectionCreateScreen(
                        CreateUiState(name, placeholder, operator, place, emptyList(), null, error, starting),
                        onNameChange = { name = it; error = null }, onOperatorChange = { operator = it; error = null }, onPlaceChange = { place = it; error = null }, onRouteSelect = {},
                        onStart = {
                            if (!starting) {
                                starting = true
                                scope.launch {
                                    try {
                                        val created = withContext(Dispatchers.IO) { inspectionStore.create(NewInspection(name, operator, place)) }
                                        stack = listOf(AppScreen.Home.encode(), AppScreen.Capture(created.inspectionId).encode())
                                        error = null
                                    } catch (e: CancellationException) { throw e
                                    } catch (_: IllegalArgumentException) { error = "64文字以内で入力してください"
                                    } catch (e: Exception) { error = "点検の作成に失敗しました: ${e.message}"
                                    } finally { starting = false }
                                }
                            }
                        }, onBack = { back() },
                    )
                    is AppScreen.Capture -> {
                        val inspection = inspections.firstOrNull { it.inspection.inspectionId == screen.inspectionId }?.inspection
                        if (inspection != null) InspectionPlaceholderScreen(inspection, error) {
                            scope.launch {
                                try {
                                    val deleted = withContext(Dispatchers.IO) { inspectionStore.delete(inspection.inspectionId) }
                                    if (deleted) { error = null; home() } else error = "送信中の写真があるため削除できません"
                                } catch (e: CancellationException) { throw e
                                } catch (e: Exception) { error = "点検の削除に失敗しました: ${e.message}" }
                            }
                        }
                    }
                    else -> Text("この画面は次の更新で入ります", Modifier.padding(16.dp))
                }
            }
        }
        if (showSettings) ReceiverSettingsDialog(settings, { showSettings = false }, health::onSettingsChanged, { showPairing = true })
        if (showPairing) PairingScreen(pendingCount = countUndelivered(photos), onClose = { showPairing = false; health.onSettingsChanged() })
        if (showStatus) AlertDialog(
            onDismissRequest = { showStatus = false }, title = { Text("接続の状態") },
            text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(connectionBarText(connectionBarState(health.configured, health.healthOk), countUndelivered(photos), "", health.reason))
                TextButton(onClick = { showStatus = false; showSettings = true }) { Text("送信先の設定") }
            } },
            confirmButton = { TextButton(onClick = { showStatus = false }) { Text("閉じる") } },
        )
    }
}

@Composable
private fun InspectionPlaceholderScreen(inspection: Inspection, error: String?, onDelete: () -> Unit) {
    var confirming by remember { mutableStateOf(false) }
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(inspection.name, style = MaterialTheme.typography.titleLarge)
        Text(inspectionStateLabel(inspection.state))
        Text("この点検で撮影する画面は次の更新で入ります")
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (inspection.state == InspectionState.IN_PROGRESS) OutlinedButton(onClick = { confirming = true }) { Text("この点検を削除する") }
    }
    if (confirming) AlertDialog(onDismissRequest = { confirming = false }, title = { Text("この点検を削除しますか") }, text = { Text("この点検と、点検に含まれる写真を削除します。") }, confirmButton = { TextButton(onClick = { confirming = false; onDelete() }) { Text("削除する") } }, dismissButton = { TextButton(onClick = { confirming = false }) { Text("キャンセル") } })
}
