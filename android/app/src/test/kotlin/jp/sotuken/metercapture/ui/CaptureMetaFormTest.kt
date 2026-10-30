package jp.sotuken.metercapture.ui

import jp.sotuken.metercapture.queue.QueueItem
import jp.sotuken.metercapture.queue.SendState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureMetaFormTest {
	private fun item(localId: String, deviceName: String?): QueueItem = QueueItem(
		localId = localId,
		imagePath = "/tmp/$localId.jpg",
		capturedAt = "2026-10-30T00:00:00Z",
		deviceName = deviceName,
		operatorValue = null,
		operatorNote = null,
		sendState = SendState.PENDING,
		retryCount = 0,
		lastError = null,
		sentAt = null,
	)

	@Test
	fun candidatesKeepNewestFirstOrderAndRemoveDuplicates() {
		// キューは新しい順。候補も新しい順のまま、同じ名前は最初（最新）の1件だけ残す。
		val items = listOf(
			item("3", "B-202"),
			item("2", "A-101"),
			item("1", "B-202"),
		)

		assertEquals(listOf("B-202", "A-101"), buildDeviceNameCandidates(items))
	}

	@Test
	fun candidatesIgnoreNullAndBlankNamesAndTrimWhitespace() {
		val items = listOf(
			item("4", null),
			item("3", "   "),
			item("2", " A-101 "),
			item("1", "A-101"),
		)

		assertEquals(listOf("A-101"), buildDeviceNameCandidates(items))
	}

	@Test
	fun normalizeDeviceNameReturnsNullForBlankInput() {
		assertNull(normalizeDeviceName(""))
		assertNull(normalizeDeviceName("   "))
	}

	@Test
	fun normalizeDeviceNameTrimsInput() {
		assertEquals("A-101", normalizeDeviceName("  A-101 "))
	}

	@Test
	fun parseOperatorValueReturnsNullForBlankAndPartialInput() {
		assertNull(parseOperatorValue(""))
		assertNull(parseOperatorValue("   "))
		assertNull(parseOperatorValue("-"))
		assertNull(parseOperatorValue("."))
	}

	@Test
	fun parseOperatorValueParsesNumbers() {
		assertEquals(12.5, parseOperatorValue("12.5")!!, 0.0)
		assertEquals(-3.0, parseOperatorValue("-3")!!, 0.0)
		assertEquals(0.5, parseOperatorValue(".5")!!, 0.0)
		assertEquals(7.0, parseOperatorValue(" 7 ")!!, 0.0)
	}

	@Test
	fun operatorValueInputAcceptsNumericText() {
		assertTrue(isOperatorValueInput(""))
		assertTrue(isOperatorValueInput("12"))
		assertTrue(isOperatorValueInput("12.5"))
		assertTrue(isOperatorValueInput("-"))
		assertTrue(isOperatorValueInput("-3.5"))
		assertTrue(isOperatorValueInput(".5"))
	}

	@Test
	fun operatorValueInputRejectsNonNumericText() {
		assertFalse(isOperatorValueInput("1.2.3"))
		assertFalse(isOperatorValueInput("abc"))
		assertFalse(isOperatorValueInput("1e5"))
		assertFalse(isOperatorValueInput("--1"))
		assertFalse(isOperatorValueInput("1-2"))
		assertFalse(isOperatorValueInput("1 2"))
	}

	@Test
	fun emptyFormProducesNullMetaValues() {
		// 両方を未入力にしても、撮影からenqueueまで進めるよう、どちらも null になる。
		assertNull(normalizeDeviceName(""))
		assertNull(parseOperatorValue(""))
	}
}
