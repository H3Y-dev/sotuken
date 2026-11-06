package jp.sotuken.metercapture.inspection

import java.time.Instant
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.queue.sender.SenderPayloads
import jp.sotuken.metercapture.ui.classifyFailureMessage
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.*

sealed interface RoundOutcome {
    data object Unfinished : RoundOutcome
    data class ReadyForManifest(val failedFileNames: List<String>) : RoundOutcome
}

fun decideAfterRound(photos: List<QueueItem>, currentReceiverId: String?): RoundOutcome {
    if (photos.any { it.sendState == SendState.PENDING || it.sendState == SendState.SENDING ||
            (it.sendState == SendState.SENT && it.sentVia == QueueItem.VIA_FOLDER) || it.isHeldFor(currentReceiverId) }) return RoundOutcome.Unfinished
    return RoundOutcome.ReadyForManifest(photos.filter { it.sendState == SendState.FAILED }.map(SenderPayloads::buildImageFileName))
}

class InspectionSendCoordinator(
    private val inspectionDao: InspectionDao,
    private val manifestPoster: (suspend (String, String) -> Result<ManifestReply>)?,
    private val sha256Of: (QueueItem) -> String?,
    private val now: () -> Instant,
) {
    suspend fun beforeRoute(reachable: Boolean) {
        inspectionDao.resetState(InspectionState.SENDING, InspectionState.WAITING)
        if (reachable) inspectionDao.resetState(InspectionState.WAITING, InspectionState.SENDING)
    }

    suspend fun isSendable(item: QueueItem): Boolean = isPhotoSendable(item, item.inspectionId?.let { inspectionDao.findById(it)?.state })

    suspend fun afterRoute(currentReceiverId: String?) {
        for (inspection in inspectionDao.findByState(InspectionState.SENDING)) {
            val photos = inspectionDao.findPhotos(inspection.inspectionId)
            val round = decideAfterRound(photos, currentReceiverId)
            if (round == RoundOutcome.Unfinished) {
                inspectionDao.update(inspection.copy(state = InspectionState.WAITING))
                continue
            }
            if (manifestPoster == null) {
                inspectionDao.update(inspection.copy(state = InspectionState.WAITING, manifestError = "PCに届かないため、写真の一覧を送れませんでした"))
                continue
            }
            val result = try {
                val summary = inspection.completionSummary?.let { requireNotNull(parseInspectionSummary(it)) }
                    ?: summarizeInspection(photos, null)
                manifestPoster.invoke(inspection.inspectionId, buildManifestJson(inspection, photos, summary, sha256Of))
            } catch (e: CancellationException) { throw e } catch (e: Exception) { Result.failure(e) }
            result.exceptionOrNull()?.let { if (it is CancellationException) throw it }
            val reply = result.getOrNull()
            if (reply != null) {
                val undelivered = (round as RoundOutcome.ReadyForManifest).failedFileNames.toSet() + reply.missingPhotos
                inspectionDao.update(inspection.copy(
                    state = nextInspectionState(inspection.state, InspectionEvent.ManifestAccepted(undelivered.size)),
                    manifestSentAt = now().toString(), manifestError = null,
                    pcMissingFileNames = JsonArray(reply.missingPhotos.map(::JsonPrimitive)).toString(),
                ))
            } else {
                val message = result.exceptionOrNull()?.message
                inspectionDao.update(inspection.copy(state = InspectionState.WAITING,
                    manifestError = if (message?.contains("PCのアプリを更新") == true) message else classifyFailureMessage(message)))
            }
        }
    }
}
