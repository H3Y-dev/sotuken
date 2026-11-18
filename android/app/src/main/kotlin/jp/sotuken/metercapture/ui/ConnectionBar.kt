package jp.sotuken.metercapture.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

private fun barBackground(state: ConnectionBarState): Color = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> GaugeColors.Fail
    ConnectionBarState.CHECKING -> GaugeColors.PanelDeep
    ConnectionBarState.CONNECTED -> GaugeColors.OkTint
    ConnectionBarState.UNREACHABLE -> GaugeColors.Warn
}

private fun barForeground(state: ConnectionBarState): Color = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> GaugeColors.OnInk
    ConnectionBarState.CHECKING -> GaugeColors.Steel
    ConnectionBarState.CONNECTED -> GaugeColors.Ok
    ConnectionBarState.UNREACHABLE -> GaugeColors.OnInk
}

@Composable
fun ConnectionBar(
    state: ConnectionBarState,
    text: String,
    onClick: () -> Unit,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyLarge,
        fontWeight = FontWeight.Bold,
        color = barForeground(state),
        maxLines = 2,
        modifier = Modifier
            .fillMaxWidth()
            .background(barBackground(state))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    )
}
