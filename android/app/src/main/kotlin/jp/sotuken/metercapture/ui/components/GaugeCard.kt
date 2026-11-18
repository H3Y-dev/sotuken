package jp.sotuken.metercapture.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 計器盤のカード。左端の帯の種類を [kind] で指定する（null は帯なし）。 */
@Composable
fun GaugeCard(
    kind: GaugeKind?,                       // null = 左端の帯なし（ふつうのカード）
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    enabled: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = MaterialTheme.shapes.medium
    val missing = kind == GaugeKind.MISSING
    val border = if (missing) null else BorderStroke(1.dp, GaugeColors.Hairline)
    val outer = if (missing) modifier.dashedOutline(GaugeColors.Ink, 2.dp, 6.dp) else modifier
    val body: @Composable () -> Unit = {
        Column(
            Modifier.fillMaxWidth()
                .drawBehind { if (kind != null) drawGaugeEdge(kind) }
                .padding(start = if (kind != null && !missing) 26.dp else 16.dp, end = 16.dp, top = 16.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            content = content,
        )
    }
    if (onClick != null) {
        Surface(onClick = onClick, enabled = enabled, modifier = outer, shape = shape,
            color = GaugeColors.Dial, contentColor = GaugeColors.Text, border = border, content = body)
    } else {
        Surface(modifier = outer, shape = shape, color = GaugeColors.Dial, contentColor = GaugeColors.Text, border = border, content = body)
    }
}
