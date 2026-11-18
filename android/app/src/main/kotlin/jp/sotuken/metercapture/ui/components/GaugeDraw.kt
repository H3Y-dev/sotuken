package jp.sotuken.metercapture.ui.components

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 内側に引く破線の枠（線6dp・間4dp）。未撮影のカードと札に使う。 */
fun Modifier.dashedOutline(color: Color, width: Dp, radius: Dp): Modifier = drawWithContent {
    drawContent()
    val w = width.toPx()
    drawRoundRect(
        color, topLeft = Offset(w / 2, w / 2), size = Size(size.width - w, size.height - w),
        cornerRadius = CornerRadius(radius.toPx()),
        style = Stroke(w, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))),
    )
}

/** カード左端の帯（幅10dp）。設計書3.6節の表のとおり。 */
fun DrawScope.drawGaugeEdge(kind: GaugeKind) {
    val e = 10.dp.toPx()
    val h = size.height
    when (kind) {
        GaugeKind.OK -> drawRect(GaugeColors.Ok, size = Size(4.dp.toPx(), h))
        GaugeKind.WAIT, GaugeKind.NEUTRAL -> drawRect(GaugeColors.Hairline, size = Size(4.dp.toPx(), h))
        GaugeKind.FAIL -> drawRect(GaugeColors.Fail, size = Size(e, h))
        GaugeKind.WARN -> clipRect(0f, 0f, e, h) {
            drawRect(GaugeColors.WarnTint, size = Size(e, h))
            val step = 14.dp.toPx()
            var x = -h
            while (x < e) {
                drawLine(GaugeColors.Warn, Offset(x, h), Offset(x + h, 0f), strokeWidth = 6.dp.toPx())
                x += step
            }
        }
        GaugeKind.MISSING -> Unit
    }
}
