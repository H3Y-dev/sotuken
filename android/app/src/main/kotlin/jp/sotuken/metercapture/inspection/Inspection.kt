package jp.sotuken.metercapture.inspection

import androidx.room.*

@Entity(tableName = "inspections")
data class Inspection(
    @PrimaryKey val inspectionId: String,
    val name: String,
    val operatorName: String?,
    val place: String?,
    val routeId: String?,
    val routeName: String?,
    val routeSnapshot: String?,
    val state: InspectionState,
    val startedAt: String,
    val completedAt: String? = null,
    val completionSummary: String? = null,
    val manifestSentAt: String? = null,
    val manifestError: String? = null,
    val pcMissingFileNames: String? = null,
)

enum class InspectionState { IN_PROGRESS, WAITING, SENDING, SENT, SENT_INCOMPLETE }

class InspectionStateConverter {
    @TypeConverter fun from(value: InspectionState): String = value.name
    @TypeConverter fun to(value: String): InspectionState = InspectionState.valueOf(value)
}

data class RouteDevice(val id: String, val name: String)
