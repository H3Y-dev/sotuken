package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.photo
import jp.sotuken.metercapture.queue.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class LegacyQueueViewTest {
    @Test fun observeQueueHidesInspectionPhotos() = runTest {
        val dao = FakeQueueDao(); val legacy = photo(inspectionId = null); dao.insert(legacy); dao.insert(photo("inspection"))
        assertEquals(listOf(legacy), LegacyQueueView(RoomQueueStore(dao)).observeQueue().first())
    }
}
