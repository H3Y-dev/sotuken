package jp.sotuken.metercapture.settings

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ReceiverUrlCandidatesTest {
    @Test fun samePcMovesOldUrlToCandidates() { assertEquals(listOf("old", "older"), mergeCandidateUrls("old", listOf("older"), "new", true)) }
    @Test fun otherPcClearsCandidates() { assertEquals(emptyList<String>(), mergeCandidateUrls("old", listOf("older"), "new", false)) }
    @Test fun keepsAtMostThreeWithoutDuplicates() { assertEquals(listOf("old", "a", "b"), mergeCandidateUrls("old", listOf("new", "a", "old", "b", "c"), "new", true)) }
    @Test fun pickReachableReturnsFirstSuccess() = runTest {
        val called = mutableListOf<String>()
        val result = pickReachableUrl(listOf("a", "b", "c")) { called += it; if (it == "b") Result.success(Unit) else Result.failure(Exception("offline")) }
        assertEquals("b", result.url); assertNull(result.error); assertEquals(listOf("a", "b"), called)
    }
    @Test fun pickReachableReturnsLastErrorWhenNone() = runTest {
        val last = Exception("last")
        val result = pickReachableUrl(listOf("a", "b")) { Result.failure(if (it == "b") last else Exception()) }
        assertNull(result.url); assertSame(last, result.error)
    }
    @Test fun emptyCandidatesDoNotCallHealth() = runTest { assertEquals(Reachability(null, null), pickReachableUrl(emptyList()) { error("must not call") }) }
    @Test fun cancellationIsNotSwallowed() = runTest { assertTrue(runCatching { pickReachableUrl(listOf("a")) { throw CancellationException() } }.exceptionOrNull() is CancellationException) }
}
