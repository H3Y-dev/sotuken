package jp.sotuken.metercapture.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import jp.sotuken.metercapture.queue.QueueStore

@Composable
fun MeterCaptureApp(queueStore: QueueStore) {
    val queueItems by queueStore.observeQueue().collectAsStateWithLifecycle(initialValue = emptyList())

    MaterialTheme {
        Scaffold { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(text = "メーター撮影", style = MaterialTheme.typography.headlineMedium)
                Text(text = "キュー: ${queueItems.size}件")

                // TODO(SKくん): CameraXでプレビューと撮影を実装する。Sprint 3
                // TODO(SKくん): ガイド枠・キュー一覧・入力フォームを実装する。Sprint 3
            }
        }
    }
}

