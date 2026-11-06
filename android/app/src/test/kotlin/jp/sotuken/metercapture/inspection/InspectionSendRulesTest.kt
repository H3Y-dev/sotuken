package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.*
import org.junit.Assert.*
import org.junit.Test

internal fun photo(id: String = "photo", deviceId: String? = "A-1", name: String? = "圧力計", inspectionId: String? = "inspection", capturedAt: String = "2026-11-06T00:00:00Z") = QueueItem(id, "/tmp/$id.jpg", capturedAt, name, null, null, SendState.PENDING, 0, null, null, deviceId = deviceId, inspectionId = inspectionId)
internal fun inspection(id: String = "inspection", state: InspectionState = InspectionState.IN_PROGRESS) = Inspection(id, "朝の点検", "大久保", "第1工場", null, null, null, state, "2026-11-06T00:00:00Z")

class InspectionSendRulesTest {
    @Test fun photoWithoutInspectionIsSendable() = assertTrue(isPhotoSendable(photo(inspectionId = null), InspectionState.IN_PROGRESS))
    @Test fun inProgressPhotoIsNotSendable() = assertFalse(isPhotoSendable(photo(), InspectionState.IN_PROGRESS))
    @Test fun waitingAndSendingPhotosAreSendable() { listOf(InspectionState.WAITING, InspectionState.SENDING).forEach { assertTrue(isPhotoSendable(photo(), it)) } }
    @Test fun sentAndIncompletePhotosAreNotSendable() { listOf(InspectionState.SENT, InspectionState.SENT_INCOMPLETE).forEach { assertFalse(isPhotoSendable(photo(), it)) } }
    @Test fun photoOfMissingInspectionIsSendable() = assertTrue(isPhotoSendable(photo(), null))
}
