package jp.sotuken.metercapture.ui.inspection

import jp.sotuken.metercapture.inspection.InspectionState
import org.junit.Assert.*
import org.junit.Test

class AppScreenTest {
    @Test fun encodeDecodeRoundTripsAllScreens() { listOf(AppScreen.Home, AppScreen.Create, AppScreen.Capture("INS-a"), AppScreen.History("INS-a"), AppScreen.Complete("INS-a"), AppScreen.SendStatus("INS-a"), AppScreen.ConnectionGuide, AppScreen.Routes, AppScreen.LegacyCapture).forEach { assertEquals(it, decodeAppScreen(it.encode())) } }
    @Test fun unknownTextDecodesToHome() { listOf("unknown", "capture/", "capture/../../bad", "capture/不正").forEach { assertEquals(AppScreen.Home, decodeAppScreen(it)) } }
    @Test fun resolveSendsMissingInspectionHome() { listOf(AppScreen.Capture("id"), AppScreen.History("id"), AppScreen.Complete("id"), AppScreen.SendStatus("id")).forEach { assertEquals(AppScreen.Home, resolveScreen(it, null)) }; assertEquals(AppScreen.Create, resolveScreen(AppScreen.Create, null)) }
    @Test fun resolveRedirectsCaptureOfCompletedInspectionToSendStatus() { InspectionState.entries.filter { it != InspectionState.IN_PROGRESS }.forEach { state -> listOf(AppScreen.Capture("id"), AppScreen.History("id"), AppScreen.Complete("id")).forEach { assertEquals(AppScreen.SendStatus("id"), resolveScreen(it, state)) } }; assertEquals(AppScreen.Capture("id"), resolveScreen(AppScreen.Capture("id"), InspectionState.IN_PROGRESS)) }
}
