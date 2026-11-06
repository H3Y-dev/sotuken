package jp.sotuken.metercapture.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.settings.PrivateIpv4Validator
import jp.sotuken.metercapture.settings.ReceiverSettings

@Composable
internal fun ReceiverSettingsDialog(receiverSettings: ReceiverSettings, onDismiss: () -> Unit, onSaved: () -> Unit, onOpenPairing: () -> Unit) {
    val context = LocalContext.current
    var urlInput by remember { mutableStateOf(receiverSettings.getUrl() ?: "") }
    var tokenInput by remember { mutableStateOf(receiverSettings.getToken() ?: "") }
    var validationError by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = { onDismiss() },
        title = { Text("送信先の設定") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    onDismiss()
                    onOpenPairing()
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
                                onSaved()
                                try {
                                    QueueSendScheduler.enqueueSend(context)
                                } catch (_: Exception) {
                                }
                                onDismiss()
                            }
                        }
                    }
                },
            ) {
                Text("保存")
            }
        },
        dismissButton = {
            TextButton(onClick = { onDismiss() }) {
                Text("キャンセル")
            }
        },
    )

}
