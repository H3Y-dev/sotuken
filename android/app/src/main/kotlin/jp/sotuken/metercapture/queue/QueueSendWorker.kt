package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class QueueSendWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        // TODO(本人): Senderを使う送信・再送・保持ポリシーを実装する。Sprint 3
        TODO("送信WorkerはSprint 3で実装する")
    }
}

/*
// TODO(本人): WorkManagerへ送信Workerを登録する処理を実装する。Sprint 3
// ネットワーク接続を必須にする設定例:
// val constraints = Constraints.Builder()
//     .setRequiredNetworkType(NetworkType.CONNECTED)
//     .build()
// 指数バックオフを使う設定例:
// val request = OneTimeWorkRequestBuilder<QueueSendWorker>()
//     .setConstraints(constraints)
//     .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
//     .build()
*/
