package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp

data class RouteChoice(val routeId: String, val label: String)
data class CreateUiState(val name: String, val namePlaceholder: String, val operatorName: String, val place: String, val routes: List<RouteChoice>, val selectedRouteId: String?, val error: String?, val starting: Boolean)

@Composable
fun InspectionCreateScreen(state: CreateUiState, onNameChange: (String) -> Unit, onOperatorChange: (String) -> Unit, onPlaceChange: (String) -> Unit, onRouteSelect: (String?) -> Unit, onStart: () -> Unit, onBack: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("点検名・担当者・場所は、空欄でも始められます。")
        OutlinedTextField(state.name, onNameChange, label = { Text("点検名（任意）") }, placeholder = { Text(state.namePlaceholder) }, singleLine = true, enabled = !state.starting, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(state.operatorName, onOperatorChange, label = { Text("担当者（任意）") }, singleLine = true, enabled = !state.starting, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(state.place, onPlaceChange, label = { Text("場所（任意）") }, singleLine = true, enabled = !state.starting, modifier = Modifier.fillMaxWidth())
        Text("点検ルート", style = MaterialTheme.typography.titleMedium)
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(state.selectedRouteId == null, enabled = !state.starting, role = Role.RadioButton, onClick = { onRouteSelect(null) }),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(state.selectedRouteId == null, onClick = null, enabled = !state.starting)
            Text("ルートなし", Modifier.padding(start = 12.dp))
        }
        state.routes.forEach { route ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(state.selectedRouteId == route.routeId, enabled = !state.starting, role = Role.RadioButton, onClick = { onRouteSelect(route.routeId) }),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(state.selectedRouteId == route.routeId, onClick = null, enabled = !state.starting)
                Text(route.label, Modifier.padding(start = 12.dp))
            }
        }
        Text("対象一覧がないため、未撮影の機器は判定できません", style = MaterialTheme.typography.bodySmall)
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = onStart, enabled = !state.starting, modifier = Modifier.fillMaxWidth()) { Text(if (state.starting) "作成中..." else "点検を始める") }
        TextButton(onClick = onBack, enabled = !state.starting) { Text("戻る") }
    }
}
