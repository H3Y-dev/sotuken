package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.route.*

data class SavedRouteRow(val routeId: String, val name: String, val detail: String)
data class RouteListUiState(val saved: List<SavedRouteRow>, val remote: List<RouteSummary>?, val loading: Boolean, val error: String?, val confirm: RouteDoc?)

fun buildRouteListUiState(saved: List<SavedRoute>, remote: List<RouteSummary>?, loading: Boolean, error: String?, confirm: RouteDoc?) = RouteListUiState(
    saved.map { SavedRouteRow(it.route.routeId, it.route.name, "${it.route.devices.size}機器 ・ ${it.route.updatedAt} ・ ${if (it.source == "wifi") "Wi-Fi" else "QR"}") }, remote, loading, error, confirm,
)

@Composable
fun RouteListScreen(state: RouteListUiState, onFetchList: () -> Unit, onPick: (String) -> Unit, onScanQr: () -> Unit, onDelete: (String) -> Unit, onBack: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("保存済みのルート", style = MaterialTheme.typography.titleLarge)
        if (state.saved.isEmpty()) Text("保存済みのルートはありません")
        state.saved.forEach { row ->
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(row.name, style = MaterialTheme.typography.titleMedium)
                    Text(row.detail)
                    TextButton(onClick = { onDelete(row.routeId) }, enabled = !state.loading) { Text("削除") }
                }
            }
        }
        Button(onClick = onFetchList, enabled = !state.loading) { Text("PCから取得") }
        OutlinedButton(onClick = onScanQr, enabled = !state.loading) { Text("ルートのQRを読む") }
        if (state.loading) Text("読み込み中...")
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        state.remote?.forEach { row ->
            OutlinedCard(onClick = { onPick(row.routeId) }, enabled = !state.loading, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) { Text(row.name); Text("${row.count}機器 ・ ${row.updatedAt}") }
            }
        }
        TextButton(onClick = onBack) { Text("戻る") }
    }
}
