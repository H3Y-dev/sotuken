package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.queue.QueueStore
import kotlinx.coroutines.flow.map

class LegacyQueueView(private val inner: QueueStore) : QueueStore by inner {
    override fun observeQueue() = inner.observeQueue().map { items -> items.filter { it.inspectionId == null } }
}
