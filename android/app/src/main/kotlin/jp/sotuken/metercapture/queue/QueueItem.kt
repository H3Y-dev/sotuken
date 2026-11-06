package jp.sotuken.metercapture.queue

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "queue_items", indices = [Index(value = ["inspectionId"])])
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
    val sentVia: String? = null,
    val receiverId: String? = null,
    val deviceId: String? = null,
    val deviceIdSource: String? = null,
    val inspectionId: String? = null,
    val inspectionName: String? = null,
    val routeId: String? = null,
) {
    companion object {
        const val VIA_HTTP = "http"
        const val VIA_FOLDER = "folder"
        const val DEVICE_ID_SOURCE_QR = "qr"
    }
}

// 状態遷移: PENDING -> SENDING -> SENT、失敗時 SENDING -> FAILED、再送時 FAILED -> PENDING。
// 実装は QueueStore.markSending/markSent/markFailed/retry。不正な遷移は IllegalStateException。
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
    val deviceId: String? = null,
    val deviceIdSource: String? = null,
    val inspectionId: String? = null,
    val inspectionName: String? = null,
    val routeId: String? = null,
)

fun QueueItem.isHeldFor(currentReceiverId: String?): Boolean =
    receiverId != null && receiverId != currentReceiverId &&
        (sendState == SendState.PENDING || sendState == SendState.FAILED ||
            (sendState == SendState.SENT && sentVia == QueueItem.VIA_FOLDER))
