package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun InspectionCompleteScreen(state: CompleteUiState, onBackToHistory: () -> Unit, onComplete: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("点検の完了確認", style = MaterialTheme.typography.headlineSmall)
        Text(state.title, style = MaterialTheme.typography.titleMedium)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("写真${state.photoCount}枚", style = MaterialTheme.typography.headlineMedium)
            Text("${state.deviceCount}機器", style = MaterialTheme.typography.headlineMedium)
        }
        if (state.warnings.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("確認してください", style = MaterialTheme.typography.titleMedium)
                state.warnings.forEach { Text(it) }
            }
        }
        Text("完了すると送信待ちになります。PCに届く接続が確認できたら、自動で送信します。")
        Text("完了後は撮影・削除ができません。取り消しはできません。")
        state.blockReason?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = onComplete, enabled = state.canComplete, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp)) { Text(state.completeLabel) }
        OutlinedButton(onClick = onBackToHistory, modifier = Modifier.fillMaxWidth()) { Text("履歴に戻る") }
    }
}
