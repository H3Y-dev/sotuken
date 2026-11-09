package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.*

@Composable
fun InspectionScaffold(title: String, health: ReceiverHealthState, barUndelivered: Int, onBarClick: () -> Unit, onHome: (() -> Unit)?, barHasOutbox: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val state = connectionBarState(health.configured, health.healthOk)
            ConnectionBar(state, connectionBarTextWithNetwork(health.network, state, barUndelivered, "", health.reason, hasOutbox = barHasOutbox), onBarClick)
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(title, style = MaterialTheme.typography.headlineSmall)
                if (onHome != null) TextButton(onClick = onHome) { Text("点検一覧") }
            }
            content()
        }
    }
}
