package jp.sotuken.metercapture.inspection

import org.junit.Assert.*
import org.junit.Test

class InspectionSummaryTest {
    private val route = listOf(RouteDevice("A-1", "圧力計"), RouteDevice("A-2", "温度計"), RouteDevice("A-3", "流量計"))
    @Test fun countsPhotosAndDistinctDevices() { val result = summarizeInspection(listOf(photo(), photo("second"), photo("third", "A-2")), route); assertEquals(3, result.photoCount); assertEquals(2, result.deviceCount) }
    @Test fun deviceNameOnlyPhotosCountByName() { val result = summarizeInspection(listOf(photo(deviceId = null), photo("two", null, " 圧力計 "), photo("three", null, "温度計")), null); assertEquals(2, result.deviceCount); assertEquals(3, result.unidentifiedCount) }
    @Test fun blankDeviceNamesAreNotDevicesAndTrimmedNamesShareOneGroup() {
        val photos = listOf(photo("one", null, "温度計"), photo("two", null, " 温度計 "), photo("blank", null, "   "))
        val result = summarizeInspection(photos, null)
        assertEquals(1, result.deviceCount)
        assertEquals(3, result.unidentifiedCount)
        assertEquals(1, result.duplicates.size)
        assertEquals(2, result.duplicates.single().count)
    }
    @Test fun photosWithoutIdAndNameAreUnidentifiedAndNotDevices() { val result = summarizeInspection(listOf(photo(deviceId = null, name = null)), null); assertEquals(0, result.deviceCount); assertEquals(1, result.unidentifiedCount); assertTrue(result.duplicates.isEmpty()) }
    @Test fun missingFollowsRouteOrder() = assertEquals(listOf(route[0], route[2]), summarizeInspection(listOf(photo(deviceId = "A-2")), route).missing)
    @Test fun nameMatchDoesNotSatisfyRouteDevice() = assertEquals(route, summarizeInspection(listOf(photo(deviceId = null)), route).missing)
    @Test fun duplicatesListDevicesWithTwoOrMorePhotos() { val result = summarizeInspection(listOf(photo(), photo("two"), photo("three", "A-2")), route); assertEquals(listOf(DuplicateDevice("A-1", "圧力計", 2)), result.duplicates) }
    @Test fun extraListsIdsOutsideRouteInCaptureOrder() {
        val result = summarizeInspection(listOf(photo("later", "Z-9", capturedAt = "2026-11-06T02:00:00Z"), photo("first", "X-9"), photo("same", "Z-9", capturedAt = "2026-11-06T03:00:00Z")), route)
        assertEquals(listOf("X-9", "Z-9"), result.extra)
    }
    @Test fun noRouteHasNullRouteCountsAndEmptyMissingExtra() { val result = summarizeInspection(listOf(photo()), null); assertNull(result.routeDeviceCount); assertNull(result.shotRouteDeviceCount); assertTrue(result.missing.isEmpty()); assertTrue(result.extra.isEmpty()) }
    @Test fun summaryJsonRoundTrips() {
        val result = summarizeInspection(listOf(photo(), photo("two"), photo("extra", "Z-9"), photo("unknown", null, null)), route)
        val parsed = requireNotNull(parseInspectionSummary(result.toJson()))
        assertEquals(result.missing, parsed.missing); assertEquals(result.extra, parsed.extra); assertEquals(result.duplicates, parsed.duplicates); assertEquals(result.unidentifiedCount, parsed.unidentifiedCount)
        assertEquals(result.toJson(), parsed.toJson())
        assertNull(parseInspectionSummary("{}"))
    }
}
