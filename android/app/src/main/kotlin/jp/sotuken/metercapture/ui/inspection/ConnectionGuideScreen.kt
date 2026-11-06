package jp.sotuken.metercapture.ui.inspection

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun ConnectionGuideScreen(networkLabel: String, reachable: Boolean?, onHome: () -> Unit, onSettings: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("PCにつながりません", style = MaterialTheme.typography.headlineSmall)
        Text("Wi-Fiが使えないときは、USBテザリングで送れます。")
        Text("1. スマホとPCをUSBケーブルでつなぐ。")
        Text("2. スマホの「設定」でUSBテザリングをオンにする。")
        Text("3. PCの受信アプリを開く。接続表示が「PCに届きます」になるまで待つ。")
        Text("設定項目の場所はスマホによって異なります。")
        Text("今の接続: $networkLabel　${when (reachable) { true -> "PCに届きます"; false -> "PCに届きません"; null -> "未確認" }}")
        Button(onClick = onSettings, modifier = Modifier.fillMaxWidth()) { Text("送信先の設定") }
        TextButton(onClick = onHome) { Text("点検の一覧へ") }
    }
}
