package jp.sotuken.metercapture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import jp.sotuken.metercapture.queue.CaptureDatabase
import jp.sotuken.metercapture.queue.RoomQueueStore
import jp.sotuken.metercapture.ui.MeterCaptureApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val database = CaptureDatabase.create(applicationContext)
        val queueStore = RoomQueueStore(database.queueItemDao())

        // TODO(SKくん): CAMERA権限などの実行時リクエストを実装する。Sprint 3
        setContent {
            MeterCaptureApp(queueStore)
        }
    }
}

