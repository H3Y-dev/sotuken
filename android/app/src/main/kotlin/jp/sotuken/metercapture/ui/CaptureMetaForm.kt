package jp.sotuken.metercapture.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.queue.QueueItem

private const val MAX_SUGGESTIONS = 8

// 真値の入力は、数字・小数点・先頭のマイナスだけを受け付ける（入力途中の "-" や "." も許す）。
private val OPERATOR_VALUE_INPUT = Regex("^-?\\d*\\.?\\d*$")

/**
 * 過去に入力した機器名の候補。キューに残っている項目の deviceName から、
 * 空白だけのものを除き、重複を取り除いて返す。キューは新しい順なので、候補も新しい順になる。
 */
internal fun buildDeviceNameCandidates(items: List<QueueItem>): List<String> =
    items
        .mapNotNull { item -> item.deviceName?.trim()?.takeIf { it.isNotEmpty() } }
        .distinct()

/** 機器名の入力値をキューへ渡す値にする。空欄（空白のみを含む）は null。 */
internal fun normalizeDeviceName(input: String): String? = input.trim().ifEmpty { null }

/** 真値の入力値をキューへ渡す値にする。空欄、または数値として読めない場合は null。 */
internal fun parseOperatorValue(input: String): Double? = input.trim().toDoubleOrNull()

/** 真値の入力欄に、この文字列を入れてよいか。 */
internal fun isOperatorValueInput(text: String): Boolean = OPERATOR_VALUE_INPUT.matches(text)

/**
 * 撮影画面に置く、機器名と真値の入力欄（どちらも任意）。
 * 機器名は、過去の入力を候補として表示し、選んで入力できる。
 */
@Composable
internal fun CaptureMetaForm(
    deviceName: String,
    onDeviceNameChange: (String) -> Unit,
    operatorValue: String,
    onOperatorValueChange: (String) -> Unit,
    deviceNameCandidates: List<String>,
) {
    val isOperatorValueInvalid = operatorValue.isNotEmpty() && parseOperatorValue(operatorValue) == null

    // 入力途中の文字を含む候補だけを出す。すでに入力済みの名前そのものは出さない。
    val suggestions = remember(deviceName, deviceNameCandidates) {
        val typed = deviceName.trim()
        deviceNameCandidates
            .filter { it != typed && (typed.isEmpty() || it.contains(typed, ignoreCase = true)) }
            .take(MAX_SUGGESTIONS)
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = deviceName,
                onValueChange = onDeviceNameChange,
                label = { Text("機器名（任意）") },
                singleLine = true,
                modifier = Modifier.weight(2f),
            )
            OutlinedTextField(
                value = operatorValue,
                onValueChange = { text ->
                    if (isOperatorValueInput(text)) onOperatorValueChange(text)
                },
                label = { Text("真値（任意）") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                isError = isOperatorValueInvalid,
                supportingText = if (isOperatorValueInvalid) {
                    { Text("数値ではないため、真値なしで保存されます") }
                } else {
                    null
                },
                modifier = Modifier.weight(1f),
            )
        }

        if (suggestions.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                suggestions.forEach { name ->
                    AssistChip(
                        onClick = { onDeviceNameChange(name) },
                        label = { Text(name) },
                    )
                }
            }
        }
    }
}
