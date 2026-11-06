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
import jp.sotuken.metercapture.route.*
import jp.sotuken.metercapture.settings.pickReachableUrl
import jp.sotuken.metercapture.queue.sender.HttpSender
import java.io.File
import java.time.Instant
import jp.sotuken.metercapture.settings.ReceiverSettings
import jp.sotuken.metercapture.ui.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun InspectionApp(queueStore: QueueStore, inspectionStore: InspectionStore, routeRepository: RouteRepository? = null) {
    val context = LocalContext.current
    val repository = routeRepository ?: remember(context) { RouteRepository(File(context.filesDir, "routes.json")) }
    val scope = rememberCoroutineScope()
    var savedRoutes by remember(repository) { mutableStateOf(emptyList<SavedRoute>()) }
    var routeLoading by remember { mutableStateOf(false) }
    var routeError by remember { mutableStateOf<String?>(null) }
    var remoteRoutes by remember { mutableStateOf<List<RouteSummary>?>(null) }
    var confirmRoute by remember { mutableStateOf<RouteDoc?>(null) }
    var routeSource by remember { mutableStateOf("wifi") }
    var scanRoute by remember { mutableStateOf(false) }
    var selectedRouteId by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(repository) {
        try { savedRoutes = withContext(Dispatchers.IO) { repository.load() } }
        catch (e: CancellationException) { throw e }
        catch (_: Exception) { routeError = "保存済みルートを読み込めません" }
    }
    fun routeOperation(block: suspend () -> Unit) {
        if (!routeLoading) {
            routeLoading = true
            routeError = null
            scope.launch {
                try { block() }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { routeError = e.message ?: "ルートの処理に失敗しました" }
                finally { routeLoading = false }
            }
        }
    }
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
    var pendingId by rememberSaveable { mutableStateOf<String?>(null) }
    var pendingName by rememberSaveable { mutableStateOf<String?>(null) }
    var pendingSource by rememberSaveable { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var operationError by remember { mutableStateOf<String?>(null) }
    var selectedPhoto by remember { mutableStateOf<QueueItem?>(null) }
    var deleteInspection by remember { mutableStateOf<Inspection?>(null) }
    fun capture(id: String, target: CaptureTarget? = null) {
        pendingId = target?.deviceId
        pendingName = target?.deviceName
        pendingSource = target?.source
        stack = listOf(AppScreen.Home.encode(), AppScreen.Capture(id).encode())
    }
    fun history(id: String) {
        stack = listOf(AppScreen.Home.encode(), AppScreen.Capture(id).encode(), AppScreen.History(id).encode())
    }

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
                                selectedRouteId = null
                                operator = latest.firstOrNull()?.inspection?.operatorName.orEmpty()
                                place = latest.firstOrNull()?.inspection?.place.orEmpty()
                                placeholder = defaultInspectionName(ZonedDateTime.now(), latest.map { it.inspection.name })
                                error = null
                                stack = listOf(AppScreen.Home.encode(), AppScreen.Create.encode())
                            }
                        },
                        onOpen = { open(it) }, onSettings = { showSettings = true }, onGuide = { showStatus = true }, onRoutes = { open(AppScreen.Routes) }, onLegacy = { open(AppScreen.LegacyCapture) },
                    )
                    AppScreen.Create -> InspectionCreateScreen(
                        CreateUiState(name, placeholder, operator, place, savedRoutes.map { RouteChoice(it.route.routeId, "${it.route.name}（${it.route.devices.size}機器）") }, selectedRouteId, error ?: routeError, starting),
                        onNameChange = { name = it; error = null }, onOperatorChange = { operator = it; error = null }, onPlaceChange = { place = it; error = null }, onRouteSelect = { selectedRouteId = it },
                        onStart = {
                            if (!starting) {
                                starting = true
                                scope.launch {
                                    try {
                                        val created = withContext(Dispatchers.IO) { inspectionStore.create(NewInspection(name, operator, place, savedRoutes.firstOrNull { it.route.routeId == selectedRouteId }?.route)) }
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
                        if (inspection != null) {
                            TextButton(onClick = { deleteInspection = inspection }, enabled = !busy) { Text("この点検を削除する") }
                            val pendingTarget = if (pendingId == null && pendingName == null) null else CaptureTarget(pendingId, pendingName, pendingSource)
                            InspectionCaptureScreen(
                                inspection, photos.filter { it.inspectionId == inspection.inspectionId }, health, pendingTarget,
                                onSaved = { file, meta -> withContext(Dispatchers.IO) { inspectionStore.addPhoto(inspection.inspectionId, file, meta) }; Unit },
                                onHistory = { history(inspection.inspectionId) }, onComplete = { open(AppScreen.Complete(inspection.inspectionId)) }, onHome = { home() },
                            )
                            LaunchedEffect(pendingTarget) {
                                if (pendingTarget != null) { pendingId = null; pendingName = null; pendingSource = null }
                            }
                        }
                    }
                    is AppScreen.History -> {
                        val inspection = inspections.firstOrNull { it.inspection.inspectionId == screen.inspectionId }?.inspection
                        if (inspection != null) InspectionHistoryScreen(
                            buildHistoryUiState(inspection, inspection.routeSnapshot?.let { parseRouteJson(it)?.devices }, photos.filter { it.inspectionId == inspection.inspectionId }),
                            onPhotoClick = { selectedPhoto = it },
                            onRetake = { capture(inspection.inspectionId, targetFromPhoto(it)) },
                            onShootDevice = { capture(inspection.inspectionId, targetFromRoute(it)) },
                            onDelete = { photo ->
                                if (!busy) {
                                    busy = true
                                    scope.launch {
                                        try {
                                            operationError = when (withContext(Dispatchers.IO) { inspectionStore.deletePhoto(inspection.inspectionId, photo.localId) }) {
                                                DeleteResult.DELETED -> null
                                                DeleteResult.SENDING -> "送信中のため削除できません"
                                                DeleteResult.NOT_FOUND -> "写真は既に削除されています"
                                            }
                                        } catch (e: CancellationException) { throw e
                                        } catch (e: Exception) { operationError = "削除に失敗しました: ${e.message}"
                                        } finally { busy = false }
                                    }
                                }
                            },
                            onBackToCapture = { capture(inspection.inspectionId) }, onComplete = { open(AppScreen.Complete(inspection.inspectionId)) }, onHome = { home() },
                        )
                    }
                    is AppScreen.Complete -> {
                        val inspection = inspections.firstOrNull { it.inspection.inspectionId == screen.inspectionId }?.inspection
                        if (inspection != null) {
                            val summary = summarizeInspection(photos.filter { it.inspectionId == inspection.inspectionId }, inspection.routeSnapshot?.let { parseRouteJson(it)?.devices })
                            val state = buildCompleteUiState(inspection, summary)
                            InspectionCompleteScreen(
                                if (busy) state.copy(canComplete = false, completeLabel = "処理中...") else state,
                                onBackToHistory = { if (!busy) history(inspection.inspectionId) },
                                onComplete = {
                                    if (!busy) {
                                        busy = true
                                        scope.launch {
                                            try {
                                                withContext(Dispatchers.IO) { inspectionStore.complete(inspection.inspectionId) }
                                                stack = listOf(AppScreen.Home.encode(), AppScreen.SendStatus(inspection.inspectionId).encode())
                                                QueueSendScheduler.enqueueSend(context)
                                            } catch (e: CancellationException) { throw e
                                            } catch (e: Exception) { operationError = "点検の完了に失敗しました: ${e.message}"
                                            } finally { busy = false }
                                        }
                                    }
                                },
                            )
                        }
                    }
                    is AppScreen.SendStatus -> {
                        val inspection = inspections.firstOrNull { it.inspection.inspectionId == screen.inspectionId }?.inspection
                        if (inspection != null) InspectionSendStatusPlaceholder(inspection, photos.filter { it.inspectionId == inspection.inspectionId }, { selectedPhoto = it }, { home() })
                    }
                    AppScreen.Routes -> RouteListScreen(
                        buildRouteListUiState(savedRoutes, remoteRoutes, routeLoading, routeError, confirmRoute),
                        onFetchList = { routeOperation {
                            if (!settings.isConfigured()) error("PCに接続できません")
                            val token = settings.getToken().orEmpty()
                            val candidates = listOfNotNull(settings.getUrl())
                            val reachable = pickReachableUrl(candidates) { HttpSender.health(it, token) }
                            // /health の失敗でも /routes を読み、401・404の案内を区別する。
                            remoteRoutes = RouteClient(reachable.url ?: candidates.first(), token).listRoutes().getOrThrow()
                        } },
                        onPick = { id -> routeOperation {
                            if (!settings.isConfigured()) error("PCに接続できません")
                            val token = settings.getToken().orEmpty()
                            val candidates = listOfNotNull(settings.getUrl())
                            val reachable = pickReachableUrl(candidates) { HttpSender.health(it, token) }
                            confirmRoute = RouteClient(reachable.url ?: candidates.first(), token).fetchRoute(id).getOrThrow()
                            routeSource = "wifi"
                        } },
                        onScanQr = { routeError = null; scanRoute = true },
                        onDelete = { id -> routeOperation {
                            savedRoutes = withContext(Dispatchers.IO) { repository.delete(id) }
                            if (selectedRouteId == id) selectedRouteId = null
                        } }, onBack = { back() },
                    )
                    else -> Text("この画面は次の更新で入ります", Modifier.padding(16.dp))
                }
            }
        }
        if (scanRoute && screen == AppScreen.Routes) AlertDialog(
            onDismissRequest = { scanRoute = false }, title = { Text("ルートのQRを読む") },
            text = { Column {
                QrScanPanel(onCodes = { codes ->
                    if (codes.isNotEmpty()) {
                        when (val result = parseRouteQr(codes.first())) {
                            is RouteQrResult.Ok -> { confirmRoute = result.route; routeSource = "qr"; scanRoute = false; routeError = null }
                            is RouteQrResult.Error -> routeError = result.message
                        }
                    }
                }, onError = { routeError = it })
                routeError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } }, confirmButton = { TextButton(onClick = { scanRoute = false }) { Text("閉じる") } },
        )
        confirmRoute?.takeIf { screen == AppScreen.Routes }?.let { route -> AlertDialog(
            onDismissRequest = { if (!routeLoading) confirmRoute = null },
            title = { Text(route.name) },
            text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${route.devices.size}機器")
                route.devices.take(5).forEach { Text("${it.name}（${it.id}）") }
                if (savedRoutes.any { it.route.routeId == route.routeId }) Text("保存済みのルートを新しい内容で置き換えます。作成済みの点検には影響しません。")
                routeError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } },
            confirmButton = { TextButton(enabled = !routeLoading, onClick = { routeOperation {
                savedRoutes = withContext(Dispatchers.IO) { repository.save(route, routeSource, Instant.now()) }
                confirmRoute = null
            } }) { Text("保存する") } },
            dismissButton = { TextButton(enabled = !routeLoading, onClick = { confirmRoute = null }) { Text("キャンセル") } },
        ) }
        if (showSettings) ReceiverSettingsDialog(settings, { showSettings = false }, health::onSettingsChanged, { showPairing = true })
        deleteInspection?.let { inspection -> AlertDialog(
            onDismissRequest = { if (!busy) deleteInspection = null },
            title = { Text("この点検を削除しますか") },
            text = { Text("この点検と、点検に含まれる写真を削除します。") },
            confirmButton = { TextButton(enabled = !busy, onClick = {
                busy = true
                scope.launch {
                    try {
                        if (withContext(Dispatchers.IO) { inspectionStore.delete(inspection.inspectionId) }) home()
                        else operationError = "送信中の写真があるため削除できません"
                    } catch (e: CancellationException) { throw e
                    } catch (e: Exception) { operationError = "点検の削除に失敗しました: ${e.message}"
                    } finally { busy = false; deleteInspection = null }
                }
            }) { Text("削除する") } },
            dismissButton = { TextButton(enabled = !busy, onClick = { deleteInspection = null }) { Text("キャンセル") } },
        ) }
        selectedPhoto?.let { FullImageDialog(it, { selectedPhoto = null }, settings.getReceiverId()) }
        operationError?.let { message -> AlertDialog(
            onDismissRequest = { operationError = null }, text = { Text(message) },
            confirmButton = { TextButton(onClick = { operationError = null }) { Text("閉じる") } },
        ) }
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
private fun InspectionSendStatusPlaceholder(inspection: Inspection, photos: List<QueueItem>, onPhotoClick: (QueueItem) -> Unit, onHome: () -> Unit) {
    androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("送信待ち", style = MaterialTheme.typography.headlineSmall)
            Text(inspection.name)
            Text("写真${photos.size}枚")
        }
        items(photos.size, key = { photos[it].localId }) { index ->
            val photo = photos[index]
            OutlinedCard(onClick = { onPhotoClick(photo) }, modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Thumbnail(photo.imagePath, Modifier.size(76.dp))
                    Column {
                        Text(photo.deviceName ?: "機器名なし")
                        Text(photo.deviceId ?: "機器IDなし")
                        Text("${formatInspectionCaptureTime(photo.capturedAt)} 撮影")
                    }
                }
            }
        }
        item { Button(onClick = onHome, modifier = Modifier.fillMaxWidth()) { Text("点検の一覧へ") } }
    }
}
