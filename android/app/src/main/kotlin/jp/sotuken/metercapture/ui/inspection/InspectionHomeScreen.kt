package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun InspectionHomeScreen(state: HomeUiState, onCreate: () -> Unit, onOpen: (AppScreen) -> Unit, onSettings: () -> Unit, onGuide: () -> Unit, onRoutes: (() -> Unit)?, onLegacy: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(onClick = onCreate, modifier = Modifier.fillMaxWidth()) { Text("新しい点検を作る") }
        for ((title, cards) in listOf("作業中" to state.inProgress, "送信待ち・送信中" to state.waiting, "送信済み" to state.sent)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            if (cards.isEmpty()) Text("${title}の点検はありません", style = MaterialTheme.typography.bodySmall)
            cards.forEach { card ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(card.stateLabel, style = MaterialTheme.typography.labelLarge)
                        Text(card.title, style = MaterialTheme.typography.titleMedium)
                        Text(card.subtitle)
                        card.progress?.let { Text(it) }
                        OutlinedButton(onClick = { onOpen(card.target) }) { Text(card.action) }
                    }
                }
            }
        }
        state.legacyUndelivered?.let { TextButton(onClick = onLegacy) { Text(it) } }
        OutlinedButton(onClick = onGuide, modifier = Modifier.fillMaxWidth()) { Text("接続を確認する") }
        TextButton(onClick = onSettings) { Text("送信先の設定") }
        if (onRoutes != null) TextButton(onClick = onRoutes) { Text("ルート") }
        TextButton(onClick = onLegacy) { Text("点検なしで撮る（従来の画面）") }
    }
}
