package jp.sotuken.metercapture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import java.io.File
import jp.sotuken.metercapture.queue.CaptureDatabase
import jp.sotuken.metercapture.queue.QueueSendScheduler
import jp.sotuken.metercapture.queue.RoomQueueStore
import androidx.room.withTransaction
import jp.sotuken.metercapture.inspection.RoomInspectionStore
import jp.sotuken.metercapture.route.RouteRepository
import jp.sotuken.metercapture.ui.inspection.InspectionApp
import jp.sotuken.metercapture.settings.ReceiverSettings

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val database = CaptureDatabase.getInstance(applicationContext)
        val queueStore = RoomQueueStore(
            database.queueItemDao(),
            outboxDir = File(requireNotNull(getExternalFilesDir(null)), "outbox"),
        ) { ReceiverSettings(applicationContext).getReceiverId() }
        val inspectionStore = RoomInspectionStore(database.inspectionDao(), queueStore, { block -> database.withTransaction { block() } })
        val routeRepository = RouteRepository(File(filesDir, "routes.json"))

        // アプリ起動時の送信ワーク登録（即時実行 + 15分ごとの定期実行）
        QueueSendScheduler.schedulePeriodic(applicationContext)
        QueueSendScheduler.enqueueSend(applicationContext)

        setContent {
            InspectionApp(queueStore, inspectionStore, routeRepository)
        }
    }
}
