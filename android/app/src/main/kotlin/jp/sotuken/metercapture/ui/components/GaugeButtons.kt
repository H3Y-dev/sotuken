package jp.sotuken.metercapture.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 主ボタン（紺）。 */
@Composable
fun GaugePrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.small) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

/** 副ボタン（紺の枠）。 */
@Composable
fun GaugeSecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.small,
        border = BorderStroke(1.dp, if (enabled) GaugeColors.Ink else GaugeColors.Hairline),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = GaugeColors.Dial, contentColor = GaugeColors.Ink),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}

/** 削除のような取り消せない操作の文字ボタン。文字色を赤錆にする。 */
@Composable
fun GaugeDangerTextButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    TextButton(onClick = onClick, modifier = modifier, enabled = enabled,
        colors = ButtonDefaults.textButtonColors(contentColor = GaugeColors.Fail)) { Text(text, style = MaterialTheme.typography.labelLarge) }
}
