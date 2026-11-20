package jp.sotuken.metercapture.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 状態の形（● ▲ ■ ◌ ◎ ○）。設計書3.6節。 */
@Composable
fun StatusShape(kind: GaugeKind, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val r = size.minDimension / 2
        val center = this.center
        when (kind) {
            GaugeKind.OK -> drawCircle(color, r * 0.8f, center)
            GaugeKind.WARN -> {
                val path = Path().apply {
                    moveTo(size.width * 0.5f, size.height * 0.1f)
                    lineTo(size.width * 0.95f, size.height * 0.9f)
                    lineTo(size.width * 0.05f, size.height * 0.9f)
                    close()
                }
                drawPath(path, color)
            }
            GaugeKind.FAIL -> drawRect(color, topLeft = Offset(size.width * 0.15f, size.height * 0.15f), size = Size(size.width * 0.7f, size.height * 0.7f))
            GaugeKind.MISSING -> drawCircle(color, r * 0.8f, center, style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 2.dp.toPx()))))
            GaugeKind.WAIT -> {
                drawCircle(color, r * 0.84f, center, style = Stroke(1.5.dp.toPx()))
                drawCircle(color, r * 0.32f, center)
            }
            GaugeKind.NEUTRAL -> drawCircle(color, r * 0.8f, center, style = Stroke(1.5.dp.toPx()))
        }
    }
}

/** 状態の札。設計書3.6節の表のとおり。 */
@Composable
fun StatusBadge(kind: GaugeKind, label: String, modifier: Modifier = Modifier) {
    val (background, foreground) = when (kind) {
        GaugeKind.OK -> GaugeColors.OkTint to GaugeColors.Ok
        GaugeKind.WARN -> GaugeColors.Warn to GaugeColors.OnInk
        GaugeKind.FAIL -> GaugeColors.Fail to GaugeColors.OnInk
        GaugeKind.MISSING -> GaugeColors.Dial to GaugeColors.Ink
        GaugeKind.WAIT -> GaugeColors.Dial to GaugeColors.Steel
        GaugeKind.NEUTRAL -> GaugeColors.Dial to GaugeColors.Ink
    }
    val border = when (kind) {
        GaugeKind.OK -> BorderStroke(1.dp, GaugeColors.Ok)
        GaugeKind.WAIT -> BorderStroke(1.dp, GaugeColors.Rule)
        GaugeKind.NEUTRAL -> BorderStroke(1.dp, GaugeColors.Ink)
        else -> null
    }
    val outer = if (kind == GaugeKind.MISSING) modifier.dashedOutline(GaugeColors.Ink, 2.dp, 4.dp) else modifier
    Surface(
        color = background,
        contentColor = foreground,
        shape = MaterialTheme.shapes.small,
        border = border,
        modifier = outer.heightIn(min = 32.dp),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            StatusShape(kind, foreground, Modifier.size(18.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, color = foreground)
        }
    }
}

/** 札を折り返して並べる。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BadgeRow(badges: List<BadgeSpec>, modifier: Modifier = Modifier) {
    FlowRow(
        modifier,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        badges.forEach { StatusBadge(it.kind, it.label) }
    }
}
