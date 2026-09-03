package jp.sotuken.metercapture.queue

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

class FakeQueueDao : QueueDao {
    private val items = MutableStateFlow<List<QueueItem>>(emptyList())

    override suspend fun insert(item: QueueItem) {
        check(items.value.none { it.localId == item.localId }) {
            "QueueItem with localId ${item.localId} already exists"
        }
        items.value = items.value + item
    }

    override suspend fun update(item: QueueItem) {
        items.value = items.value.map { existing ->
            if (existing.localId == item.localId) item else existing
        }
    }

    override suspend fun delete(item: QueueItem) {
        items.value = items.value.filterNot { it.localId == item.localId }
    }

    override suspend fun findById(localId: String): QueueItem? =
        items.value.firstOrNull { it.localId == localId }

    override fun observeAll(): Flow<List<QueueItem>> =
        items.map { currentItems -> currentItems.sortedByDescending { it.capturedAt } }
}
