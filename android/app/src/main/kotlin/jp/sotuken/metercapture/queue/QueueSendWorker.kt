package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.io.File
import jp.sotuken.metercapture.queue.sender.HttpSender
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

class QueueSendWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        // 即時作業と定期作業は別の一意名なので、キューの復旧・送信を直列にする。
        sendMutex.withLock {
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
        val database = CaptureDatabase.create(applicationContext)
        try {
            val queueDao = database.queueItemDao()
            val queueStore = RoomQueueStore(queueDao)
            val settings = ReceiverSettings(applicationContext)

            val outboxDir = File(
                requireNotNull(applicationContext.getExternalFilesDir(null)) { "External files directory unavailable" },
                "outbox",
            )

            val httpSenderProvider = {
                if (settings.isConfigured()) {
                    val url = settings.getUrl()!!
                    val token = settings.getToken()!!
                    HttpSender(url, token)
                } else {
                    null
                }
            }

            val healthChecker: suspend () -> Boolean = {
                if (settings.isConfigured()) {
                    HttpSender.health(settings.getUrl()!!, settings.getToken()!!).isSuccess
                } else {
                    false
                }
            }

            val router = SendRouter(
                queueDao = queueDao,
                queueStore = queueStore,
                outboxDir = outboxDir,
                httpSenderProvider = httpSenderProvider,
                healthChecker = healthChecker,
            )

            router.route()
            return Result.success()
        } finally {
            database.close()
        }
    }

    companion object {
        private val sendMutex = Mutex()
    }
}
