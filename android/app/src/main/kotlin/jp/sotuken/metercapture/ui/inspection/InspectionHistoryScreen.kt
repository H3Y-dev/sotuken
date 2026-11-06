package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.inspection.RouteDevice
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.ui.Thumbnail

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
            Text("この点検の履歴", style = MaterialTheme.typography.headlineSmall)
            Text(state.header)
            Text("写真${state.photoCount}枚 ・ ${state.deviceLine}", style = MaterialTheme.typography.titleLarge)
        }
        state.noRouteNote?.let { item { Text(it) } }
        items(state.routeRows.orEmpty(), key = { "route/${it.device.id}" }) { row ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text("${if (row.done) "撮影済み" else "未撮影"}：${row.device.name} ${row.device.id}（${row.count}枚）")
                    TextButton(onClick = { onShootDevice(row.device) }) { Text("この機器を撮る") }
                }
            }
        }
        items(state.notices) { Text(it, color = MaterialTheme.colorScheme.tertiary) }
        if (state.rows.isEmpty()) item { Text("写真はまだありません") }
        items(state.rows, key = { it.item.localId }) { row ->
            Card(Modifier.fillMaxWidth().clickable { onPhotoClick(row.item) }) {
                Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Thumbnail(row.item.imagePath, Modifier.size(76.dp, 86.dp))
                    Column(Modifier.weight(1f)) {
                        Text(row.title, style = MaterialTheme.typography.titleMedium)
                        Text(row.idLine)
                        Text(row.timeLine)
                        Text(row.sourceLabel, style = MaterialTheme.typography.labelMedium)
                        Row {
                            TextButton(onClick = { onRetake(row.item) }, enabled = row.canEdit) { Text("撮り直す") }
                            TextButton(onClick = { deleteTarget = row }, enabled = row.canEdit) { Text("削除") }
                        }
                    }
                }
            }
        }
        item {
            Button(onClick = onBackToCapture, modifier = Modifier.fillMaxWidth()) { Text("撮影へ戻る") }
            OutlinedButton(onClick = onComplete, modifier = Modifier.fillMaxWidth()) { Text("点検完了へ") }
            TextButton(onClick = onHome) { Text("点検一覧") }
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
        confirmButton = { TextButton(onClick = onDelete) { Text("削除する") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}
