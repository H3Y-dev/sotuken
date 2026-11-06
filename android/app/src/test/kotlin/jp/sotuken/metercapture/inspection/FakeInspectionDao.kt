package jp.sotuken.metercapture.inspection

import jp.sotuken.metercapture.queue.*
import kotlinx.coroutines.flow.*

class FakeInspectionDao(private val queue: FakeQueueDao) : InspectionDao {
    private val items = MutableStateFlow<List<Inspection>>(emptyList())
    override suspend fun insert(inspection: Inspection) { check(items.value.none { it.inspectionId == inspection.inspectionId }); items.value += inspection }
    override suspend fun update(inspection: Inspection) { items.value = items.value.map { if (it.inspectionId == inspection.inspectionId) inspection else it } }
    override suspend fun delete(inspection: Inspection) { items.value = items.value.filterNot { it.inspectionId == inspection.inspectionId } }
    override suspend fun findById(id: String) = items.value.find { it.inspectionId == id }
    override fun observeById(id: String) = items.map { all -> all.find { it.inspectionId == id } }
    override fun observeAll() = items.map { it.sortedByDescending { inspection -> inspection.startedAt } }
    override suspend fun findByState(state: InspectionState) = items.value.filter { it.state == state }.sortedBy { it.startedAt }
    override suspend fun allNames() = items.value.map { it.name }
    override suspend fun resetState(from: InspectionState, to: InspectionState) { items.value = items.value.map { if (it.state == from) it.copy(state = to) else it } }
    override fun observePhotos(id: String) = queue.observeAll().map { all -> all.filter { it.inspectionId == id }.sortedBy { it.capturedAt } }
    override suspend fun findPhotos(id: String) = observePhotos(id).first()
    override fun observePhotoCounts() = queue.observeAll().map { all -> all.filter { it.inspectionId != null }.groupBy { it.inspectionId!! }.map { (id, photos) ->
        InspectionPhotoCount(id, photos.size, photos.mapNotNull { it.deviceId ?: it.deviceName?.trim()?.takeIf { name -> name.isNotEmpty() }?.let { name -> "name:$name" } }.distinct().size, photos.count { it.sendState == SendState.SENT && it.sentVia == QueueItem.VIA_HTTP })
    } }
}
