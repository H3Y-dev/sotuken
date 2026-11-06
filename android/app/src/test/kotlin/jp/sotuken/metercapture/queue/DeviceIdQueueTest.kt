package jp.sotuken.metercapture.queue

import androidx.sqlite.db.SupportSQLiteDatabase
import java.lang.reflect.Proxy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceIdQueueTest {
    @Test fun migration3to4AddsNullableColumnsWithoutTouchingOldRows() {
        val sql = mutableListOf<String>()
        val db = Proxy.newProxyInstance(
            SupportSQLiteDatabase::class.java.classLoader, arrayOf(SupportSQLiteDatabase::class.java),
        ) { _, method, args ->
            check(method.name == "execSQL")
            sql.add(args!![0] as String)
            null
        } as SupportSQLiteDatabase
        assertEquals(3, CaptureDatabase.MIGRATION_3_4.startVersion)
        assertEquals(4, CaptureDatabase.MIGRATION_3_4.endVersion)
        CaptureDatabase.MIGRATION_3_4.migrate(db)
        assertEquals(
            listOf(
                "ALTER TABLE queue_items ADD COLUMN deviceId TEXT",
                "ALTER TABLE queue_items ADD COLUMN deviceIdSource TEXT",
            ),
            sql,
        )
    }

    @Test fun oldRowsReadAsNullDeviceId() {
        val old = QueueItem("legacy", "/photo.jpg", "2026-11-06T00:00:00Z", null, null, null,
            SendState.PENDING, 0, null, null)
        assertNull(old.deviceId)
        assertNull(old.deviceIdSource)
    }

    @Test fun enqueueStoresDeviceIdAndSource() = runTest {
        val dao = FakeQueueDao()
        val store = RoomQueueStore(dao)
        val file = java.io.File.createTempFile("photo", ".jpg")
        try {
            val withQr = store.enqueue(file, CaptureMeta("P-1", null, null, deviceId = "A-101", deviceIdSource = "qr"))
            val manual = store.enqueue(file, CaptureMeta("P-1", null, null))
            assertEquals("A-101", dao.findById(withQr)?.deviceId)
            assertEquals("qr", dao.findById(withQr)?.deviceIdSource)
            assertNull(dao.findById(manual)?.deviceId)
            assertNull(dao.findById(manual)?.deviceIdSource)
        } finally {
            file.delete()
        }
    }
}