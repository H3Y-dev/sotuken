package jp.sotuken.metercapture.queue

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface QueueDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(item: QueueItem)

    @Update
    suspend fun update(item: QueueItem)

    @Delete
    suspend fun delete(item: QueueItem)

    @Query("SELECT * FROM queue_items WHERE localId = :localId")
    suspend fun findById(localId: String): QueueItem?

    @Query("SELECT * FROM queue_items ORDER BY capturedAt DESC")
    fun observeAll(): Flow<List<QueueItem>>
}

