package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.inspection.RouteDevice
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.ui.Thumbnail
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.GaugeColors
import jp.sotuken.metercapture.ui.theme.gaugeNum

@Composable
fun InspectionHistoryScreen(
    state: HistoryUiState,
    onPhotoClick: (QueueItem) -> Unit,
    onRetake: (QueueItem) -> Unit,
    onShootDevice: (RouteDevice) -> Unit,
    onDelete: (QueueItem) -> Unit,
    onBackToCapture: () -> Unit,
    onComplete: () -> Unit,
    onHome: () -> Unit,
) {
    var deleteTarget by remember { mutableStateOf<HistoryRow?>(null) }
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("この点検の履歴", style = MaterialTheme.typography.headlineSmall)
                Text(state.header, style = MaterialTheme.typography.titleMedium)
                Text("写真${state.photoCount}枚 ・ ${state.deviceLine}", style = MaterialTheme.typography.titleLarge.gaugeNum(), color = GaugeColors.Ink)
            }
        }
        state.noRouteNote?.let { item { Text(it, style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel) } }
        if (!state.routeRows.isNullOrEmpty()) {
            item { Text("ルートの機器", style = MaterialTheme.typography.titleLarge) }
            items(state.routeRows, key = { "route/${it.device.id}" }) { row ->
                GaugeCard(kind = if (row.done) GaugeKind.OK else GaugeKind.MISSING, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(row.device.name, style = MaterialTheme.typography.titleMedium)
                            Text(row.device.id, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        }
                        StatusBadge(if (row.done) GaugeKind.OK else GaugeKind.MISSING, if (row.done) "撮影済み ${row.count}枚" else "未撮影")
                    }
                    TextButton(onClick = { onShootDevice(row.device) }) { Text("この機器を撮る") }
                }
            }
        }
        items(state.notices) { notice -> GaugeCard(kind = GaugeKind.WARN, modifier = Modifier.fillMaxWidth()) { Text(notice, style = MaterialTheme.typography.bodyLarge) } }
        item { Text("撮影した写真", style = MaterialTheme.typography.titleLarge) }
        if (state.rows.isEmpty()) item { Text("写真はまだありません", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel) }
        items(state.rows, key = { it.item.localId }) { row ->
            GaugeCard(kind = row.sendKind, modifier = Modifier.fillMaxWidth(), onClick = { onPhotoClick(row.item) }) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Thumbnail(row.item.imagePath, Modifier.size(76.dp, 86.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        StatusBadge(row.sendKind, row.sendLabel)
                        Text(row.title, style = MaterialTheme.typography.titleMedium)
                        Text(row.idLine, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        Text(row.timeLine, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        Text("出所：${row.sourceLabel}", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
                        row.reason?.let { Text("理由：$it", style = MaterialTheme.typography.bodyMedium) }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { onRetake(row.item) }, enabled = row.canEdit) { Text("撮り直す") }
                            GaugeDangerTextButton("削除", onClick = { deleteTarget = row }, enabled = row.canEdit)
                        }
                    }
                }
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                GaugePrimaryButton("撮影へ戻る", onClick = onBackToCapture, modifier = Modifier.fillMaxWidth())
                GaugeSecondaryButton("点検完了へ", onClick = onComplete, modifier = Modifier.fillMaxWidth())
                TextButton(onClick = onHome) { Text("点検一覧") }
            }
        }
    }
    deleteTarget?.let { row ->
        DeleteInspectionPhotoDialog(row, { deleteTarget = null }) {
            deleteTarget = null
            onDelete(row.item)
        }
    }
}

@Composable
private fun DeleteInspectionPhotoDialog(row: HistoryRow, onDismiss: () -> Unit, onDelete: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("この写真を削除しますか") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Thumbnail(row.item.imagePath, Modifier.size(120.dp))
                Text(row.title)
                Text(row.idLine)
                Text(row.timeLine)
                Text("この写真と紐づく機器の情報を、この点検の履歴から削除します。")
            }
        },
        confirmButton = { GaugeDangerTextButton("削除する", onClick = onDelete) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}
