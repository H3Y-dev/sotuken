package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.*

@Composable
fun InspectionCompleteScreen(state: CompleteUiState, onBackToHistory: () -> Unit, onComplete: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("点検の完了確認", style = MaterialTheme.typography.headlineSmall)
        Text(state.title, style = MaterialTheme.typography.titleMedium)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            GaugeCard(kind = null, modifier = Modifier.weight(1f)) {
                Text("写真", style = MaterialTheme.typography.labelLarge, color = GaugeColors.Steel)
                Text("${state.photoCount}枚", style = MaterialTheme.typography.headlineSmall.gaugeNum(), color = GaugeColors.Ink)
            }
            GaugeCard(kind = null, modifier = Modifier.weight(1f)) {
                Text("機器", style = MaterialTheme.typography.labelLarge, color = GaugeColors.Steel)
                Text("${state.deviceCount}台", style = MaterialTheme.typography.headlineSmall.gaugeNum(), color = GaugeColors.Ink)
            }
        }
        if (state.warnings.isNotEmpty()) {
            GaugeCard(kind = if (state.warnings.any { it.startsWith("未撮影：") }) GaugeKind.MISSING else GaugeKind.WARN, modifier = Modifier.fillMaxWidth()) {
                Text("確認してください", style = MaterialTheme.typography.titleMedium)
                state.warnings.forEach { Text(it, style = MaterialTheme.typography.bodyLarge) }
            }
        }
        Text("完了すると送信待ちになります。PCに届く接続が確認できたら、自動で送信します。", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
        Text("完了後は撮影・削除ができません。取り消しはできません。", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
        state.blockReason?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        GaugePrimaryButton(state.completeLabel, onClick = onComplete, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp), enabled = state.canComplete)
        GaugeSecondaryButton("履歴に戻る", onClick = onBackToHistory, modifier = Modifier.fillMaxWidth())
    }
}
