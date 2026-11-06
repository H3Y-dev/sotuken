package jp.sotuken.metercapture.inspection

import org.junit.Assert.*
import org.junit.Test

class InspectionStateMachineTest {
    @Test fun completeMovesInProgressToWaiting() = assertEquals(InspectionState.WAITING, nextInspectionState(InspectionState.IN_PROGRESS, InspectionEvent.Complete))
    @Test fun startSendingMovesWaitingToSending() = assertEquals(InspectionState.SENDING, nextInspectionState(InspectionState.WAITING, InspectionEvent.StartSending))
    @Test fun recoverMovesSendingToWaiting() = assertEquals(InspectionState.WAITING, nextInspectionState(InspectionState.SENDING, InspectionEvent.Recover))
    @Test fun roundUnfinishedMovesSendingToWaiting() = assertEquals(InspectionState.WAITING, nextInspectionState(InspectionState.SENDING, InspectionEvent.RoundUnfinished))
    @Test fun manifestAcceptedWithZeroUndeliveredIsSent() = assertEquals(InspectionState.SENT, nextInspectionState(InspectionState.SENDING, InspectionEvent.ManifestAccepted(0)))
    @Test fun manifestAcceptedWithUndeliveredIsSentIncomplete() = assertEquals(InspectionState.SENT_INCOMPLETE, nextInspectionState(InspectionState.SENDING, InspectionEvent.ManifestAccepted(2)))
    @Test fun retryUndeliveredMovesSentIncompleteToWaiting() = assertEquals(InspectionState.WAITING, nextInspectionState(InspectionState.SENT_INCOMPLETE, InspectionEvent.RetryUndelivered))
    @Test(expected = IllegalStateException::class) fun completeFromWaitingThrows() { nextInspectionState(InspectionState.WAITING, InspectionEvent.Complete) }
    @Test(expected = IllegalStateException::class) fun startSendingFromInProgressThrows() { nextInspectionState(InspectionState.IN_PROGRESS, InspectionEvent.StartSending) }
    private val events = listOf(InspectionEvent.Complete, InspectionEvent.StartSending, InspectionEvent.Recover, InspectionEvent.RoundUnfinished, InspectionEvent.ManifestAccepted(0), InspectionEvent.ManifestAccepted(1), InspectionEvent.RetryUndelivered)
    @Test fun noEventReturnsToInProgress() {
        InspectionState.entries.forEach { state -> events.forEach { event ->
            runCatching { nextInspectionState(state, event) }.onSuccess { assertNotEquals(InspectionState.IN_PROGRESS, it) }
        } }
    }
    @Test fun sentAcceptsNoEvent() { events.forEach { event -> assertTrue(runCatching { nextInspectionState(InspectionState.SENT, event) }.exceptionOrNull() is IllegalStateException) } }
}
