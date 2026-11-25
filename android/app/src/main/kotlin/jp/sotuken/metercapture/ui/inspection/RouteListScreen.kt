package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.route.*
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.GaugeColors
import jp.sotuken.metercapture.ui.theme.gaugeNum

data class SavedRouteRow(val routeId: String, val name: String, val detail: String)
data class RouteListUiState(val saved: List<SavedRouteRow>, val remote: List<RouteSummary>?, val loading: Boolean, val error: String?, val confirm: RouteDoc?)

fun buildRouteListUiState(saved: List<SavedRoute>, remote: List<RouteSummary>?, loading: Boolean, error: String?, confirm: RouteDoc?) = RouteListUiState(
    saved.map { SavedRouteRow(it.route.routeId, it.route.name, "${it.route.devices.size}台 ・ ${it.route.updatedAt} ・ ${if (it.source == "wifi") "Wi-Fi" else "QR"}") }, remote, loading, error, confirm,
)

@Composable
fun RouteListScreen(state: RouteListUiState, onFetchList: () -> Unit, onPick: (String) -> Unit, onScanQr: () -> Unit, onDelete: (String) -> Unit, onBack: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("保存済みのルート", style = MaterialTheme.typography.titleLarge)
        if (state.saved.isEmpty()) Text("保存済みのルートはありません", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
        state.saved.forEach { row ->
            GaugeCard(kind = null, modifier = Modifier.fillMaxWidth()) {
                    Text(row.name, style = MaterialTheme.typography.titleMedium)
                    Text(row.detail, style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
                    GaugeDangerTextButton("削除", onClick = { onDelete(row.routeId) }, enabled = !state.loading)
            }
        }
        GaugePrimaryButton("PCから取得", onClick = onFetchList, modifier = Modifier.fillMaxWidth(), enabled = !state.loading)
        GaugeSecondaryButton("ルートのQRを読む", onClick = onScanQr, modifier = Modifier.fillMaxWidth(), enabled = !state.loading)
        if (state.loading) Text("読み込み中...", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        state.remote?.forEach { row ->
            GaugeCard(kind = null, onClick = { onPick(row.routeId) }, enabled = !state.loading, modifier = Modifier.fillMaxWidth()) {
                Text(row.name, style = MaterialTheme.typography.titleMedium)
                Text("${row.count}台 ・ ${row.updatedAt}", style = MaterialTheme.typography.bodyMedium.gaugeNum(), color = GaugeColors.Steel)
            }
        }
        TextButton(onClick = onBack) { Text("戻る") }
    }
}
