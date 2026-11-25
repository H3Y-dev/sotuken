package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import jp.sotuken.metercapture.ui.components.*
import jp.sotuken.metercapture.ui.theme.GaugeColors

@Composable
fun ConnectionGuideScreen(networkLabel: String, reachable: Boolean?, onHome: () -> Unit, onSettings: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("PCにつながりません", style = MaterialTheme.typography.headlineSmall)
        GaugeCard(kind = null, modifier = Modifier.fillMaxWidth()) {
            Text("Wi-Fiが使えないときは、USBテザリングで送れます。", style = MaterialTheme.typography.bodyLarge)
            Text("1. スマホとPCをUSBケーブルでつなぐ。", style = MaterialTheme.typography.bodyLarge)
            Text("2. スマホの「設定」でUSBテザリングをオンにする。", style = MaterialTheme.typography.bodyLarge)
            Text("3. PCの受信アプリを開く。画面上の帯が「PCに接続中」になるまで待つ。", style = MaterialTheme.typography.bodyLarge)
            Text("設定項目の場所はスマホによって異なります。", style = MaterialTheme.typography.bodyMedium, color = GaugeColors.Steel)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("今の接続：$networkLabel", style = MaterialTheme.typography.bodyLarge)
            val (kind, label) = when (reachable) { true -> GaugeKind.OK to "PCに接続中"; false -> GaugeKind.WARN to "PCにつながりません"; null -> GaugeKind.WAIT to "確認中" }
            StatusBadge(kind, label)
        }
        GaugePrimaryButton("送信先の設定", onClick = onSettings, modifier = Modifier.fillMaxWidth())
        TextButton(onClick = onHome) { Text("点検の一覧へ") }
    }
}
