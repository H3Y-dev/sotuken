package jp.sotuken.metercapture.inspection

import java.io.File
import java.time.Instant
import java.time.ZoneId
import jp.sotuken.metercapture.queue.*
import jp.sotuken.metercapture.route.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class NewInspection(val name: String, val operatorName: String, val place: String, val route: RouteDoc? = null)
data class InspectionListItem(val inspection: Inspection, val counts: InspectionPhotoCount?)

interface InspectionStore {
    fun observeInspections(): Flow<List<InspectionListItem>>
    fun observeInspection(id: String): Flow<Inspection?>
    fun observePhotos(id: String): Flow<List<QueueItem>>
    suspend fun create(input: NewInspection, now: Instant = Instant.now()): Inspection
    suspend fun addPhoto(inspectionId: String, imageFile: File, meta: CaptureMeta): String
    suspend fun complete(inspectionId: String, now: Instant = Instant.now()): InspectionSummary
    suspend fun deletePhoto(inspectionId: String, localId: String): DeleteResult
    suspend fun delete(inspectionId: String): Boolean
}

class RoomInspectionStore(
    private val inspectionDao: InspectionDao,
    private val queueStore: QueueStore,
    private val runInTransaction: suspend (suspend () -> Unit) -> Unit,
    private val zone: ZoneId = ZoneId.systemDefault(),
) : InspectionStore {
    // 撮影の追加と完了・削除を直列にし、完了後に写真が増えるのを防ぐ。
    private val mutationMutex = Mutex()
    override fun observeInspections(): Flow<List<InspectionListItem>> = combine(inspectionDao.observeAll(), inspectionDao.observePhotoCounts()) { inspections, counts ->
        val byId = counts.associateBy { it.inspectionId }
        inspections.map { InspectionListItem(it, byId[it.inspectionId]) }
    }
    override fun observeInspection(id: String) = inspectionDao.observeById(id)
    override fun observePhotos(id: String) = inspectionDao.observePhotos(id)

    override suspend fun create(input: NewInspection, now: Instant): Inspection = mutationMutex.withLock {
        val name = normalizeInspectionText(input.name) ?: defaultInspectionName(now.atZone(zone), inspectionDao.allNames())
        val route = input.route?.let { requireNotNull(parseRouteJson(it.toJson())) }
        val inspection = Inspection(newInspectionId(now), name, normalizeInspectionText(input.operatorName), normalizeInspectionText(input.place), route?.routeId, route?.name, route?.toJson(), InspectionState.IN_PROGRESS, now.toString())
        inspectionDao.insert(inspection)
        inspection
    }

    override suspend fun addPhoto(inspectionId: String, imageFile: File, meta: CaptureMeta): String = mutationMutex.withLock {
        val inspection = requireInProgress(inspectionId)
        queueStore.enqueue(imageFile, meta.copy(inspectionId = inspectionId, inspectionName = inspection.name, routeId = inspection.routeId))
    }

    override suspend fun complete(inspectionId: String, now: Instant): InspectionSummary = mutationMutex.withLock {
        queueSendMutex.withLock {
            var summary: InspectionSummary? = null
            runInTransaction {
                val inspection = requireInProgress(inspectionId)
                val photos = inspectionDao.findPhotos(inspectionId)
                check(photos.isNotEmpty()) { "写真がありません。撮影してから完了してください" }
                val computed = summarizeInspection(photos, inspection.routeSnapshot?.let { requireNotNull(parseRouteJson(it)).devices })
                inspectionDao.update(inspection.copy(state = nextInspectionState(inspection.state, InspectionEvent.Complete), completedAt = now.toString(), completionSummary = computed.toJson()))
                summary = computed
            }
            checkNotNull(summary)
        }
    }

    override suspend fun deletePhoto(inspectionId: String, localId: String): DeleteResult = mutationMutex.withLock {
        requireInProgress(inspectionId)
        if (inspectionDao.findPhotos(inspectionId).none { it.localId == localId }) {
            return@withLock DeleteResult.NOT_FOUND
        }
        queueStore.delete(localId)
    }

    override suspend fun delete(inspectionId: String): Boolean = mutationMutex.withLock {
        val inspection = requireInProgress(inspectionId)
        for (photo in inspectionDao.findPhotos(inspectionId)) {
            if (queueStore.delete(photo.localId) != DeleteResult.DELETED) return@withLock false
        }
        inspectionDao.delete(inspection)
        true
    }

    private suspend fun requireInProgress(id: String): Inspection = checkNotNull(inspectionDao.findById(id)).also {
        check(it.state == InspectionState.IN_PROGRESS) { "作業中の点検だけ変更できます" }
    }
}
