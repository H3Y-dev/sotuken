package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.io.File
import jp.sotuken.metercapture.inspection.InspectionSendCoordinator
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.settings.pickReachableUrl
import java.time.Instant
import jp.sotuken.metercapture.queue.sender.HttpSender
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

class QueueSendWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        // 即時作業と定期作業は別の一意名なので、キューの復旧・送信を直列にする。
        queueSendMutex.withLock {
            try {
                sendQueue()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Result.retry()
            }
        }
    }

    private suspend fun sendQueue(): Result {
        val database = CaptureDatabase.getInstance(applicationContext)
        val queueDao = database.queueItemDao()
        val inspectionDao = database.inspectionDao()
        val queueStore = RoomQueueStore(queueDao)
        val settings = ReceiverSettings(applicationContext).sendTarget()

        val outboxDir = File(
            requireNotNull(applicationContext.getExternalFilesDir(null)) { "External files directory unavailable" },
            "outbox",
        )

        val reach = pickReachableUrl(if (settings.isConfigured()) settings.candidateUrls else emptyList()) {
            HttpSender.health(it, settings.token!!)
        }
        val sender = reach.url?.let { HttpSender(it, settings.token!!) }
        val coordinator = InspectionSendCoordinator(
            inspectionDao,
            manifestPoster = sender?.let { http -> { id, json -> http.postManifest(id, json) } },
            sha256Of = { item -> runCatching { SenderPayloads.computeSha256Hex(File(item.imagePath)) }.getOrNull() },
            now = { Instant.now() },
        )
        coordinator.beforeRoute(reachable = sender != null)
        val httpSenderProvider = { sender }
        val healthChecker: suspend () -> kotlin.Result<Unit> = {
            if (sender != null) kotlin.Result.success(Unit)
            else kotlin.Result.failure(reach.error ?: IllegalStateException("送信先未設定"))
        }
        val router = SendRouter(
            queueDao = queueDao,
            queueStore = queueStore,
            outboxDir = outboxDir,
            httpSenderProvider = httpSenderProvider,
            healthChecker = healthChecker,
            currentReceiverId = settings.receiverId,
            isSendable = coordinator::isSendable,
        )

        router.route()
        coordinator.afterRoute(currentReceiverId = settings.receiverId)
        return Result.success()
    }

}
