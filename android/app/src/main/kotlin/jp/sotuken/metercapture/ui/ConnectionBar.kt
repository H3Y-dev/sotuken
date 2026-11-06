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
import androidx.compose.ui.unit.dp

private fun barBackground(state: ConnectionBarState): Color = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> Color(0xFFFFCDD2)
    ConnectionBarState.CHECKING -> Color(0xFFE0E0E0)
    ConnectionBarState.CONNECTED -> Color(0xFFC8E6C9)
    ConnectionBarState.UNREACHABLE -> Color(0xFFFFF59D)
}

private fun barForeground(state: ConnectionBarState): Color = when (state) {
    ConnectionBarState.NOT_CONFIGURED -> Color(0xFFB71C1C)
    ConnectionBarState.CHECKING -> Color(0xFF424242)
    ConnectionBarState.CONNECTED -> Color(0xFF1B5E20)
    ConnectionBarState.UNREACHABLE -> Color(0xFF5D4037)
}

@Composable
fun ConnectionBar(
    state: ConnectionBarState,
    text: String,
    onClick: () -> Unit,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = barForeground(state),
        maxLines = 2,
        modifier = Modifier
            .fillMaxWidth()
            .background(barBackground(state))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    )
}