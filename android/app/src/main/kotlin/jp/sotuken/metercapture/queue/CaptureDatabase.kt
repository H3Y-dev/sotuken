package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [QueueItem::class], version = 3, exportSchema = false)
@TypeConverters(SendStateConverter::class)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun queueItemDao(): QueueDao

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

        fun create(context: Context): CaptureDatabase =
            Room.databaseBuilder(context, CaptureDatabase::class.java, "meter-capture.db")
                .addMigrations(MIGRATION_1_2, MIGRATION_2_3)
                .build()
    }
}

class SendStateConverter {
    @TypeConverter
    fun fromSendState(value: SendState): String = value.name

    @TypeConverter
    fun toSendState(value: String): SendState = SendState.valueOf(value)
}
