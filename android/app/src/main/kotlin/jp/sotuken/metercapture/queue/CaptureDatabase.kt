package jp.sotuken.metercapture.queue

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters

@Database(entities = [QueueItem::class], version = 1, exportSchema = false)
@TypeConverters(SendStateConverter::class)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun queueItemDao(): QueueDao

    companion object {
        fun create(context: Context): CaptureDatabase =
            Room.databaseBuilder(context, CaptureDatabase::class.java, "meter-capture.db").build()
    }
}

class SendStateConverter {
    @TypeConverter
    fun fromSendState(value: SendState): String = value.name

    @TypeConverter
    fun toSendState(value: String): SendState = SendState.valueOf(value)
}

