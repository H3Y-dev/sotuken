package jp.sotuken.metercapture.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import java.time.Instant
import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.DeleteResult
import jp.sotuken.metercapture.queue.SendState
import jp.sotuken.metercapture.queue.isHeldFor
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * キューの履歴画面。操作はコールバックを通じてQueueStoreへ渡す。
 * 送信済みの項目も一覧に残し、新しい順に並べる。
 */
@Composable
internal fun QueueListScreen(
    items: List<QueueItem>,
    onClose: () -> Unit,
    onRetry: (String) -> Unit = {},
    onSendNow: () -> Unit = {},
    onReassignReceiver: (String) -> Unit = {},
    currentReceiverId: String? = null,
    connectionUnreachable: Boolean = false,
    connectionReason: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
    onDelete: suspend (String) -> DeleteResult = { DeleteResult.NOT_FOUND },
) {
    var selected by remember { mutableStateOf<QueueItem?>(null) }
    var deleteTarget by remember { mutableStateOf<QueueItem?>(null) }
    // 撮影日時の文字列ではなく、時刻として解釈した値で新しい順に並べる。
    val sorted = remember(items) {
        items.sortedByDescending { parseInstantOrNull(it.capturedAt) ?: Instant.EPOCH }
    }

    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .systemBarsPadding()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "履歴（${sorted.size}件）",
                        style = MaterialTheme.typography.headlineSmall,
                    )
                    TextButton(onClick = onClose) {
                        Text("閉じる")
                    }
                }

                undeliveredSummary(items, currentReceiverId, isSendable)?.let { summary ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = summary,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.tertiary,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = onSendNow) {
                            Text("今すぐ送る")
                        }
                    }
                }

                if (sorted.isEmpty()) {
                    Text("履歴はまだありません")
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(sorted, key = { it.localId }) { item ->
                            QueueListRow(
                                item = item,
                                onClick = { selected = item },
                                currentReceiverId = currentReceiverId,
                                connectionUnreachable = connectionUnreachable,
                                connectionReason = connectionReason,
                                isSendable = isSendable,
                                onRetry = { onRetry(item.localId) },
                                onReassignReceiver = { onReassignReceiver(item.localId) },
                                onDelete = { deleteTarget = item },
                            )
                        }
                    }
                }
            }
        }
    }

    selected?.let { item ->
        FullImageDialog(item = item, onDismiss = { selected = null }, currentReceiverId = currentReceiverId, isSendable = isSendable)
    }
    DeleteConfirmDialog(deleteTarget, currentReceiverId, { deleteTarget = null }, onDelete)
}

@Composable
private fun QueueListRow(
    item: QueueItem,
    onClick: () -> Unit,
    onRetry: () -> Unit = {},
    onReassignReceiver: () -> Unit = {},
    currentReceiverId: String? = null,
    connectionUnreachable: Boolean = false,
    connectionReason: String? = null,
    isSendable: (QueueItem) -> Boolean = { true },
    onDelete: () -> Unit = {},
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Thumbnail(imagePath = item.imagePath, modifier = Modifier.size(72.dp))
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = formatCapturedAt(item.capturedAt),
                    style = MaterialTheme.typography.bodyLarge,
                )
                Text(
                    text = item.deviceName?.takeIf { it.isNotBlank() } ?: "機器名なし",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = sendStatusLabel(item, currentReceiverId, isSendable),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (!isSendable(item) && !item.isHeldFor(currentReceiverId)) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        stateColor(item.sendState)
                    },
                )
                errorTextFor(item, connectionUnreachable, connectionReason, isSendable, currentReceiverId)?.let { errorText ->
                    Text(
                        text = "理由：$errorText",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        maxLines = 2,
                    )
                }
                HeldReceiverAction(item, currentReceiverId, onReassignReceiver)
                TextButton(onClick = onDelete, enabled = canDelete(item)) {
                    Text("削除")
                }
                if (canRetry(item, currentReceiverId, isSendable)) {
                    TextButton(onClick = onRetry) {
                        Text("再送")
                    }
                }
            }
        }
    }
}

@Composable
private fun DeleteConfirmDialog(
    item: QueueItem?,
    currentReceiverId: String?,
    onDismiss: () -> Unit,
    onDelete: suspend (String) -> DeleteResult,
) {
    val scope = rememberCoroutineScope()
    var deleting by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    if (item != null) {
        AlertDialog(
            onDismissRequest = { if (!deleting) onDismiss() },
            title = { Text("写真の削除") },
            text = { Text(deleteConfirmationText(item, currentReceiverId)) },
            confirmButton = {
                TextButton(enabled = !deleting, onClick = {
                    deleting = true
                    scope.launch {
                        try {
                            error = when (onDelete(item.localId)) {
                                DeleteResult.DELETED -> null
                                DeleteResult.SENDING -> "送信中のため削除できません"
                                DeleteResult.NOT_FOUND -> "写真は既に削除されています"
                            }
                        } catch (cancelled: CancellationException) {
                            throw cancelled
                        } catch (failure: Exception) {
                            error = "削除に失敗しました: ${failure.message ?: failure}"
                        } finally {
                            deleting = false
                            onDismiss()
                        }
                    }
                }) { Text("削除する") }
            },
            dismissButton = {
                TextButton(enabled = !deleting, onClick = onDismiss) { Text("キャンセル") }
            },
        )
    }
    error?.let { message ->
        AlertDialog(
            onDismissRequest = { error = null },
            text = { Text(message) },
            confirmButton = { TextButton(onClick = { error = null }) { Text("閉じる") } },
        )
    }
}

private fun stateLabel(state: SendState): String = when (state) {
    SendState.PENDING -> "未送信"
    SendState.SENDING -> "送信中"
    SendState.SENT -> "送信済み"
    SendState.FAILED -> "送信失敗"
}

@Composable
private fun stateColor(state: SendState): Color = when (state) {
    SendState.PENDING -> MaterialTheme.colorScheme.onSurfaceVariant
    SendState.SENDING -> MaterialTheme.colorScheme.onSurfaceVariant
    SendState.SENT -> MaterialTheme.colorScheme.primary
    SendState.FAILED -> MaterialTheme.colorScheme.error
}

@Composable
private fun HeldReceiverAction(item: QueueItem, currentReceiverId: String?, onConfirm: () -> Unit) {
    var confirming by remember(item.localId) { mutableStateOf(false) }
    if (!item.isHeldFor(currentReceiverId)) return
    TextButton(onClick = { confirming = true }) {
        Text("今のPCへ送り直す")
    }
    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text("送信先を変更しますか？") },
            text = { Text("この写真の送信先を現在設定されているPCに変更して送り直します。") },
            confirmButton = {
                TextButton(onClick = { confirming = false; onConfirm() }) {
                    Text("送り直す")
                }
            },
            dismissButton = {
                TextButton(onClick = { confirming = false }) { Text("キャンセル") }
            },
        )
    }
}
