package jp.sotuken.metercapture.queue

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "queue_items")
data class QueueItem(
    @PrimaryKey val localId: String,
    val imagePath: String,
    val capturedAt: String,
    val deviceName: String?,
    val operatorValue: Double?,
    val operatorNote: String?,
    val sendState: SendState,
    val retryCount: Int,
    val lastError: String?,
    val sentAt: String?,
)

// 状態遷移: PENDING -> SENDING -> SENT、失敗時 SENDING -> FAILED、再送時 FAILED -> PENDING。
// TODO(本人): キューの状態遷移を実装する。Sprint 3
enum class SendState {
    PENDING,
    SENDING,
    SENT,
    FAILED,
}

data class CaptureMeta(
    val deviceName: String?,
    val operatorValue: Double?,
    val operatorNote: String?,
)

