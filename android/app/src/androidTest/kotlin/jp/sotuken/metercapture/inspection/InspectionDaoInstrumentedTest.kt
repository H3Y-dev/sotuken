package jp.sotuken.metercapture.inspection

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import jp.sotuken.metercapture.queue.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InspectionDaoInstrumentedTest {
    private suspend fun database(block: suspend (CaptureDatabase) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = Room.inMemoryDatabaseBuilder(context, CaptureDatabase::class.java).build()
        try { block(db) } finally { db.close() }
    }
    private fun photo(id: String, deviceId: String?, name: String?, time: String = "2026-11-06T00:00:00Z") = QueueItem(id, "/$id.jpg", time, name, null, null, SendState.PENDING, 0, null, null, deviceId = deviceId, inspectionId = "inspection")
    private fun inspection(id: String, state: InspectionState) = Inspection(id, "点検", null, null, null, null, null, state, "2026-11-06T00:00:00Z")
    @Test fun photoCountsMatchSummarizeInspection() = runTest { database { db ->
        val photos = listOf(photo("a", "A-1", "圧力計"), photo("b", "A-1", "別名"), photo("c", null, "温度計"), photo("d", null, " 温度計 "), photo("e", null, null), photo("f", null, "   "))
        photos.forEach { db.queueItemDao().insert(it) }
        val counts = db.inspectionDao().observePhotoCounts().first().single(); val summary = summarizeInspection(photos, null)
        assertEquals(summary.photoCount, counts.photoCount); assertEquals(summary.deviceCount, counts.deviceCount)
    } }
    @Test fun observePhotosOrdersByCapturedAt() = runTest { database { db ->
        val later = photo("later", "A-1", "圧力計", "2026-11-06T01:00:00Z"); val earlier = photo("earlier", "A-2", "温度計")
        db.queueItemDao().insert(later); db.queueItemDao().insert(earlier)
        assertEquals(listOf(earlier, later), db.inspectionDao().observePhotos("inspection").first())
    } }
    @Test fun findByStateAndResetState() = runTest { database { db ->
        val dao = db.inspectionDao(); dao.insert(inspection("working", InspectionState.IN_PROGRESS)); dao.insert(inspection("sending", InspectionState.SENDING))
        assertEquals(listOf("sending"), dao.findByState(InspectionState.SENDING).map { it.inspectionId }); dao.resetState(InspectionState.SENDING, InspectionState.WAITING)
        assertTrue(dao.findByState(InspectionState.SENDING).isEmpty()); assertEquals(InspectionState.WAITING, dao.findById("sending")?.state); assertEquals(InspectionState.IN_PROGRESS, dao.findById("working")?.state)
    } }
}
