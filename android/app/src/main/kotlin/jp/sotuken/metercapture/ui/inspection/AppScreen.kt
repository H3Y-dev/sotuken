package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.*

sealed interface AppScreen {
    data object Home : AppScreen
    data object Create : AppScreen
    data class Capture(val inspectionId: String) : AppScreen
    data class History(val inspectionId: String) : AppScreen
    data class Complete(val inspectionId: String) : AppScreen
    data class SendStatus(val inspectionId: String) : AppScreen
    data object ConnectionGuide : AppScreen
    data object Routes : AppScreen
    data object LegacyCapture : AppScreen
}

fun AppScreen.encode(): String = when (this) {
    AppScreen.Home -> "home"
    AppScreen.Create -> "create"
    is AppScreen.Capture -> "capture/$inspectionId"
    is AppScreen.History -> "history/$inspectionId"
    is AppScreen.Complete -> "complete/$inspectionId"
    is AppScreen.SendStatus -> "send-status/$inspectionId"
    AppScreen.ConnectionGuide -> "connection-guide"
    AppScreen.Routes -> "routes"
    AppScreen.LegacyCapture -> "legacy-capture"
}

fun decodeAppScreen(text: String): AppScreen {
    val parts = text.split('/')
    if (parts.size == 2 && INSPECTION_ID_PATTERN.matches(parts[1])) return when (parts[0]) {
        "capture" -> AppScreen.Capture(parts[1])
        "history" -> AppScreen.History(parts[1])
        "complete" -> AppScreen.Complete(parts[1])
        "send-status" -> AppScreen.SendStatus(parts[1])
        else -> AppScreen.Home
    }
    return when (text) {
        "create" -> AppScreen.Create
        "connection-guide" -> AppScreen.ConnectionGuide
        "routes" -> AppScreen.Routes
        "legacy-capture" -> AppScreen.LegacyCapture
        else -> AppScreen.Home
    }
}

internal fun AppScreen.inspectionIdOrNull(): String? = when (this) {
    is AppScreen.Capture -> inspectionId
    is AppScreen.History -> inspectionId
    is AppScreen.Complete -> inspectionId
    is AppScreen.SendStatus -> inspectionId
    else -> null
}

fun resolveScreen(requested: AppScreen, state: InspectionState?): AppScreen {
    val id = requested.inspectionIdOrNull() ?: return requested
    if (state == null) return AppScreen.Home
    if (state != InspectionState.IN_PROGRESS && (requested is AppScreen.Capture || requested is AppScreen.Complete || requested is AppScreen.History)) return AppScreen.SendStatus(id)
    return requested
}
