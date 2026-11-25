package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.GaugeColors
import jp.sotuken.metercapture.ui.theme.gaugeNum

@Composable
fun InspectionHomeScreen(state: HomeUiState, onCreate: () -> Unit, onOpen: (AppScreen) -> Unit, onSettings: () -> Unit, onGuide: () -> Unit, onRoutes: (() -> Unit)?, onLegacy: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        GaugePrimaryButton("新しい点検を作る", onClick = onCreate, modifier = Modifier.fillMaxWidth())
        for ((title, cards) in listOf("作業中" to state.inProgress, "送信待ち・送信中" to state.waiting, "送信済み" to state.sent)) {
            Text("$title ${cards.size}件", style = MaterialTheme.typography.titleLarge.gaugeNum())
            if (cards.isEmpty()) Text("${title}の点検はありません", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
            cards.forEach { card ->
                GaugeCard(kind = card.edgeKind, modifier = Modifier.fillMaxWidth()) {
                        BadgeRow(listOf(BadgeSpec(card.kind, card.stateLabel)) + card.badges)
                        Text(card.startedLabel, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        Text(card.title, style = MaterialTheme.typography.titleMedium)
                        Text(card.subtitle, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                        card.progress?.let { Text(it, style = MaterialTheme.typography.titleLarge.gaugeNum(), color = GaugeColors.Ink) }
                        if (card.target is AppScreen.Capture) GaugePrimaryButton(card.action, { onOpen(card.target) }, Modifier.fillMaxWidth()) else GaugeSecondaryButton(card.action, { onOpen(card.target) }, Modifier.fillMaxWidth())
                }
            }
        }
        Text("接続と設定", style = MaterialTheme.typography.titleLarge)
        GaugeSecondaryButton("接続を確認する", onClick = onGuide, modifier = Modifier.fillMaxWidth())
        TextButton(onClick = onSettings) { Text("送信先の設定") }
        if (onRoutes != null) TextButton(onClick = onRoutes) { Text("ルート") }
        state.legacyUndelivered?.let { TextButton(onClick = onLegacy) { Text(it) } }
        TextButton(onClick = onLegacy) { Text("点検なしで撮る（従来の画面）") }
    }
}
