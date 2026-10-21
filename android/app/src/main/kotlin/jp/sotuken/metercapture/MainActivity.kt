package jp.sotuken.metercapture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import jp.sotuken.metercapture.queue.CaptureDatabase
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.queue.RoomQueueStore
import jp.sotuken.metercapture.ui.MeterCaptureApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val database = CaptureDatabase.create(applicationContext)
        val queueStore = RoomQueueStore(database.queueItemDao())

        // アプリ起動時の送信ワーク登録（即時実行 + 15分ごとの定期実行）
        QueueSendScheduler.schedulePeriodic(applicationContext)
        QueueSendScheduler.enqueueSend(applicationContext)

        setContent {
            MeterCaptureApp(queueStore)
        }
    }
}
