package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.*
import jp.sotuken.metercapture.ui.components.TickRule
import jp.sotuken.metercapture.ui.theme.GaugeColors

@Composable
fun InspectionScaffold(title: String, health: ReceiverHealthState, barUndelivered: Int, onBarClick: () -> Unit, onHome: (() -> Unit)?, barHasOutbox: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            val state = connectionBarState(health.configured, health.healthOk)
            ConnectionBar(state, connectionBarTextWithNetwork(health.network, state, barUndelivered, "", health.reason, hasOutbox = barHasOutbox), onBarClick)
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, style = MaterialTheme.typography.headlineSmall, color = GaugeColors.Text)
                if (onHome != null) TextButton(onClick = onHome) { Text("点検一覧") }
            }
            TickRule(Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            content()
        }
    }
}
