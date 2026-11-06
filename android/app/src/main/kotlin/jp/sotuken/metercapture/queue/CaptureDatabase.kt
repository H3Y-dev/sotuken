package jp.sotuken.metercapture.queue

import android.content.Context
import jp.sotuken.metercapture.inspection.*
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [QueueItem::class, Inspection::class], version = 5, exportSchema = false)
@TypeConverters(SendStateConverter::class, InspectionStateConverter::class)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun queueItemDao(): QueueDao
    abstract fun inspectionDao(): InspectionDao

    companion object {
        val MIGRATION_1_2: Migration = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE queue_items ADD COLUMN sentVia TEXT")
            }
        }

        val MIGRATION_2_3: Migration = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE queue_items ADD COLUMN receiverId TEXT")
            }
        }

        val MIGRATION_3_4: Migration = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE queue_items ADD COLUMN deviceId TEXT")
                db.execSQL("ALTER TABLE queue_items ADD COLUMN deviceIdSource TEXT")
            }
        }

        val MIGRATION_4_5: Migration = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE queue_items ADD COLUMN inspectionId TEXT")
                db.execSQL("ALTER TABLE queue_items ADD COLUMN inspectionName TEXT")
                db.execSQL("ALTER TABLE queue_items ADD COLUMN routeId TEXT")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_queue_items_inspectionId` ON `queue_items` (`inspectionId`)")
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS `inspections` (" +
                        "`inspectionId` TEXT NOT NULL, `name` TEXT NOT NULL, `operatorName` TEXT, `place` TEXT, " +
                        "`routeId` TEXT, `routeName` TEXT, `routeSnapshot` TEXT, `state` TEXT NOT NULL, " +
                        "`startedAt` TEXT NOT NULL, `completedAt` TEXT, `completionSummary` TEXT, " +
                        "`manifestSentAt` TEXT, `manifestError` TEXT, `pcMissingFileNames` TEXT, " +
                        "PRIMARY KEY(`inspectionId`))",
                )
            }
        }

        val ALL_MIGRATIONS = arrayOf(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5)

        @Volatile private var instance: CaptureDatabase? = null

        /** プロセスで1つだけ開く。Workerと画面が同じインスタンスを使い、変更通知を画面へ届ける（F8）。 */
        fun getInstance(context: Context): CaptureDatabase =
            instance ?: synchronized(this) {
                instance ?: create(context.applicationContext).also { instance = it }
            }

        fun create(context: Context): CaptureDatabase =
            Room.databaseBuilder(context, CaptureDatabase::class.java, "meter-capture.db")
                .addMigrations(*ALL_MIGRATIONS)
                .build()
    }
}

class SendStateConverter {
    @TypeConverter
    fun fromSendState(value: SendState): String = value.name

    @TypeConverter
    fun toSendState(value: String): SendState = SendState.valueOf(value)
}
