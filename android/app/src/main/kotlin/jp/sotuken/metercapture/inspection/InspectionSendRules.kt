package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.QueueItem

val SENDABLE_INSPECTION_STATES = setOf(InspectionState.WAITING, InspectionState.SENDING)

fun isPhotoSendable(item: QueueItem, inspectionState: InspectionState?): Boolean =
    item.inspectionId == null || inspectionState == null || inspectionState in SENDABLE_INSPECTION_STATES
