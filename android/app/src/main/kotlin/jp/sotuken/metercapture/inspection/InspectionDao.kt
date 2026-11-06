package jp.sotuken.metercapture.inspection

import androidx.room.*
import kotlinx.coroutines.flow.Flow
import jp.sotuken.metercapture.queue.QueueItem

data class InspectionPhotoCount(
    val inspectionId: String,
    val photoCount: Int,
    val deviceCount: Int,
    val deliveredCount: Int,
)

@Dao
interface InspectionDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(inspection: Inspection)
    @Update suspend fun update(inspection: Inspection)
    @Delete suspend fun delete(inspection: Inspection)

    @Query("SELECT * FROM inspections WHERE inspectionId = :id")
    suspend fun findById(id: String): Inspection?

    @Query("SELECT * FROM inspections WHERE inspectionId = :id")
    fun observeById(id: String): Flow<Inspection?>

    /** 点検の一覧（ホーム）。新しい順。 */
    @Query("SELECT * FROM inspections ORDER BY startedAt DESC")
    fun observeAll(): Flow<List<Inspection>>

    @Query("SELECT * FROM inspections WHERE state = :state ORDER BY startedAt ASC")
    suspend fun findByState(state: InspectionState): List<Inspection>

    @Query("SELECT name FROM inspections")
    suspend fun allNames(): List<String>

    @Query("UPDATE inspections SET state = :to WHERE state = :from")
    suspend fun resetState(from: InspectionState, to: InspectionState)

    /** 点検ごとの写真。撮影の古い順。 */
    @Query("SELECT * FROM queue_items WHERE inspectionId = :id ORDER BY capturedAt ASC")
    fun observePhotos(id: String): Flow<List<QueueItem>>

    @Query("SELECT * FROM queue_items WHERE inspectionId = :id ORDER BY capturedAt ASC")
    suspend fun findPhotos(id: String): List<QueueItem>

    /** ホームのカード用の集計。機器数は機器IDまたは機器名で数え、どちらも無い写真は数えない。 */
    @Query(
        "SELECT inspectionId, COUNT(*) AS photoCount, " +
            "COUNT(DISTINCT COALESCE(deviceId, 'name:' || NULLIF(TRIM(deviceName), ''))) AS deviceCount, " +
            "SUM(CASE WHEN sendState = 'SENT' AND sentVia = 'http' THEN 1 ELSE 0 END) AS deliveredCount " +
            "FROM queue_items WHERE inspectionId IS NOT NULL GROUP BY inspectionId",
    )
    fun observePhotoCounts(): Flow<List<InspectionPhotoCount>>

}
