package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object QueueSendScheduler {
    const val UNIQUE_WORK_QUEUE_SEND = "queue-send"
    const val UNIQUE_WORK_QUEUE_SEND_PERIODIC = "queue-send-periodic"

    fun enqueueSend(context: Context) {
        val request = OneTimeWorkRequestBuilder<QueueSendWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            UNIQUE_WORK_QUEUE_SEND,
            ExistingWorkPolicy.APPEND_OR_REPLACE,
            request,
        )
    }

    fun schedulePeriodic(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<QueueSendWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            UNIQUE_WORK_QUEUE_SEND_PERIODIC,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }
}
