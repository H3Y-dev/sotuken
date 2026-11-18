package jp.sotuken.metercapture.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.theme.GaugeColors

/** 見出しの下の目盛りの定規。計器の意匠はここだけ。 */
@Composable
fun TickRule(modifier: Modifier = Modifier) {
    Canvas(modifier.fillMaxWidth().height(10.dp)) {
        drawRect(GaugeColors.Ink, size = Size(size.width, 2.dp.toPx()))
        val step = 12.dp.toPx()
        var x = 0f
        var i = 0
        while (x <= size.width) {
            val major = i % 5 == 0                       // 60dp ごとに大目盛り
            drawRect(GaugeColors.Ink, topLeft = Offset(x, 0f),
                size = Size((if (major) 2 else 1).dp.toPx(), (if (major) 10 else 5).dp.toPx()))
            x += step
            i++
        }
    }
}
