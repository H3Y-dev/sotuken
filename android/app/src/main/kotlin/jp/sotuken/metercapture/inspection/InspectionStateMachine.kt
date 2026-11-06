package jp.sotuken.metercapture.inspection

sealed interface InspectionEvent {
    data object Complete : InspectionEvent
    data object StartSending : InspectionEvent
    data object Recover : InspectionEvent
    data object RoundUnfinished : InspectionEvent
    data class ManifestAccepted(val undeliveredCount: Int) : InspectionEvent
    data object RetryUndelivered : InspectionEvent
}

fun nextInspectionState(current: InspectionState, event: InspectionEvent): InspectionState = when {
    current == InspectionState.IN_PROGRESS && event == InspectionEvent.Complete -> InspectionState.WAITING
    current == InspectionState.WAITING && event == InspectionEvent.StartSending -> InspectionState.SENDING
    current == InspectionState.SENDING && (event == InspectionEvent.Recover || event == InspectionEvent.RoundUnfinished) -> InspectionState.WAITING
    current == InspectionState.SENDING && event is InspectionEvent.ManifestAccepted -> {
        require(event.undeliveredCount >= 0)
        if (event.undeliveredCount == 0) InspectionState.SENT else InspectionState.SENT_INCOMPLETE
    }
    current == InspectionState.SENT_INCOMPLETE && event == InspectionEvent.RetryUndelivered -> InspectionState.WAITING
    else -> error("許されない点検の状態遷移: $current / $event")
}
