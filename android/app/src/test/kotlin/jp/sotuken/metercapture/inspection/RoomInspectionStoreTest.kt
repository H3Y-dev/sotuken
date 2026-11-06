package jp.sotuken.metercapture.inspection

import java.io.File
import java.time.Instant
import java.time.ZoneId
import jp.sotuken.metercapture.queue.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class RoomInspectionStoreTest {
    @Test fun createCopiesRouteSnapshot() = runTest {
        val route = requireNotNull(jp.sotuken.metercapture.route.parseRouteJson(jp.sotuken.metercapture.route.PC_ROUTE_JSON))
        val inspection = store.create(NewInspection("点検", "", "", route), now)
        assertEquals(route.routeId, inspection.routeId)
        assertEquals(route.name, inspection.routeName)
        assertEquals(route, jp.sotuken.metercapture.route.parseRouteJson(requireNotNull(inspection.routeSnapshot)))
        val id = store.addPhoto(inspection.inspectionId, temp.newFile("route.jpg"), CaptureMeta("計器", null, null))
        assertEquals(route.routeId, queue.findById(id)?.routeId)
    }
    @Test fun laterRouteUpdateDoesNotChangeInspection() = runTest {
        val file = File(temp.root, "routes.json")
        val repository = jp.sotuken.metercapture.route.RouteRepository(file)
        val route = requireNotNull(jp.sotuken.metercapture.route.parseRouteJson(jp.sotuken.metercapture.route.PC_ROUTE_JSON))
        repository.save(route, "qr", now)
        val inspection = store.create(NewInspection("点検", "", "", repository.load().single().route), now)
        repository.save(route.copy(name = "更新"), "wifi", now.plusSeconds(1))
        repository.delete(route.routeId)
        assertEquals(inspection.routeSnapshot, dao.findById(inspection.inspectionId)?.routeSnapshot)
        assertEquals(route.name, dao.findById(inspection.inspectionId)?.routeName)
    }
    @get:Rule val temp = TemporaryFolder()
    private val queue = FakeQueueDao()
    private val dao = FakeInspectionDao(queue)
    private val queueStore = RoomQueueStore(queue)
    private val store = RoomInspectionStore(dao, queueStore, { it() }, ZoneId.of("Asia/Tokyo"))
    private val now = Instant.parse("2026-11-06T00:30:12Z")
    private suspend fun create() = store.create(NewInspection("", " 大久保 ", " 第1工場 "), now)
    @Test fun createStoresInProgressWithDefaultName() = runTest {
        val item = create(); assertEquals("11/06 朝の点検", item.name); assertEquals(InspectionState.IN_PROGRESS, item.state); assertEquals("大久保", item.operatorName); assertEquals("第1工場", item.place); assertEquals(item, dao.findById(item.inspectionId)); assertNull(item.routeSnapshot)
        assertEquals("11/06 朝の点検 2", create().name)
    }
    @Test fun createKeepsTypedName() = runTest { val item = store.create(NewInspection(" 自由な名前 ", "", ""), now); assertEquals("自由な名前", item.name); assertNull(item.operatorName); assertNull(item.place) }
    @Test fun addPhotoCopiesInspectionFieldsToQueueItem() = runTest {
        val item = create(); val id = store.addPhoto(item.inspectionId, temp.newFile("photo.jpg"), CaptureMeta("圧力計", null, null, inspectionId = "wrong", inspectionName = "wrong", routeId = "wrong"))
        val saved = requireNotNull(queue.findById(id)); assertEquals(item.inspectionId, saved.inspectionId); assertEquals(item.name, saved.inspectionName); assertNull(saved.routeId)
    }
    @Test fun addPhotoToCompletedInspectionThrows() = runTest {
        val item = create(); dao.update(item.copy(state = InspectionState.WAITING))
        assertTrue(runCatching { store.addPhoto(item.inspectionId, File("unused"), CaptureMeta(null, null, null)) }.exceptionOrNull() is IllegalStateException)
        assertTrue(queue.observeAll().first().isEmpty())
    }
    @Test fun completeSavesSummaryAndCompletedAt() = runTest {
        val item = create(); queue.insert(photo(inspectionId = item.inspectionId))
        val result = store.complete(item.inspectionId, now.plusSeconds(30)); val saved = requireNotNull(dao.findById(item.inspectionId))
        assertEquals(1, result.photoCount); assertEquals(InspectionState.WAITING, saved.state); assertEquals(now.plusSeconds(30).toString(), saved.completedAt); assertEquals(result.toJson(), saved.completionSummary)
    }
    @Test fun completeWithoutPhotosThrowsAndKeepsState() = runTest {
        val item = create(); assertTrue(runCatching { store.complete(item.inspectionId, now) }.exceptionOrNull() is IllegalStateException); assertEquals(item, dao.findById(item.inspectionId))
    }
    @Test fun deleteInProgressRemovesPhotosThenInspection() = runTest {
        val item = create(); val image = temp.newFile("delete.jpg"); val id = store.addPhoto(item.inspectionId, image, CaptureMeta(null, null, null))
        assertTrue(store.delete(item.inspectionId)); assertNull(queue.findById(id)); assertFalse(image.exists()); assertNull(dao.findById(item.inspectionId))
    }
    @Test fun deleteWaitingInspectionIsRejected() = runTest { val item = create(); dao.update(item.copy(state = InspectionState.WAITING)); assertTrue(runCatching { store.delete(item.inspectionId) }.exceptionOrNull() is IllegalStateException); assertNotNull(dao.findById(item.inspectionId)) }
    @Test fun observeInspectionsJoinsCounts() = runTest {
        val item = create(); queue.insert(photo(inspectionId = item.inspectionId)); queue.insert(photo("two", inspectionId = item.inspectionId).copy(sendState = SendState.SENT, sentVia = QueueItem.VIA_HTTP)); queue.insert(photo("legacy", inspectionId = null))
        assertEquals(listOf(InspectionListItem(item, InspectionPhotoCount(item.inspectionId, 2, 1, 1))), store.observeInspections().first())
    }
    @Test fun deleteStopsAndKeepsInspectionWhenPhotoIsSending() = runTest {
        val item = create(); queue.insert(photo(inspectionId = item.inspectionId).copy(sendState = SendState.SENDING)); assertFalse(store.delete(item.inspectionId)); assertNotNull(dao.findById(item.inspectionId)); assertNotNull(queue.findById("photo"))
    }
    @Test fun deletePhotoOnlyWhileInProgress() = runTest {
        val item = create()
        val id = store.addPhoto(item.inspectionId, temp.newFile("single.jpg"), CaptureMeta(null, null, null))
        assertEquals(DeleteResult.DELETED, store.deletePhoto(item.inspectionId, id))
        assertNull(queue.findById(id))
        assertNotNull(dao.findById(item.inspectionId))
        val remaining = store.addPhoto(item.inspectionId, temp.newFile("remaining.jpg"), CaptureMeta(null, null, null))
        dao.update(item.copy(state = InspectionState.WAITING))
        assertTrue(runCatching { store.deletePhoto(item.inspectionId, remaining) }.exceptionOrNull() is IllegalStateException)
        assertNotNull(queue.findById(remaining))
    }
    @Test fun deletePhotoOfOtherInspectionIsNotFound() = runTest {
        val item = create()
        val other = create()
        val id = store.addPhoto(other.inspectionId, temp.newFile("other.jpg"), CaptureMeta(null, null, null))
        assertEquals(DeleteResult.NOT_FOUND, store.deletePhoto(item.inspectionId, id))
        assertNotNull(queue.findById(id))
    }
    @Test fun deletePhotoWhileSendingIsRejected() = runTest {
        val item = create()
        queue.insert(photo(inspectionId = item.inspectionId).copy(sendState = SendState.SENDING))
        assertEquals(DeleteResult.SENDING, store.deletePhoto(item.inspectionId, "photo"))
        assertNotNull(queue.findById("photo"))
    }
}
