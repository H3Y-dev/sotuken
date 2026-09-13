package jp.sotuken.metercapture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.lifecycleScope
import jp.sotuken.metercapture.queue.CaptureDatabase
import jp.sotuken.metercapture.queue.RoomQueueStore
import jp.sotuken.metercapture.ui.MeterCaptureApp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val database = CaptureDatabase.create(applicationContext)
        val queueStore = RoomQueueStore(database.queueItemDao())

        // 前回起動時に送信中でクラッシュ・強制終了した項目を未送信へ戻し、再送対象に含める。
        lifecycleScope.launch {
            queueStore.recoverInterruptedSends()
        }

        setContent {
            MeterCaptureApp(queueStore)
        }
    }
}

