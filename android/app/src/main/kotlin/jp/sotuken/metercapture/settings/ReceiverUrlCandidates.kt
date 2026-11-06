package jp.sotuken.metercapture.settings

import kotlinx.coroutines.CancellationException

data class Reachability(val url: String?, val error: Throwable?)

suspend fun pickReachableUrl(candidates: List<String>, health: suspend (String) -> Result<Unit>): Reachability {
    var error: Throwable? = null
    for (url in candidates) {
        val result = try { health(url) } catch (e: CancellationException) { throw e } catch (e: Exception) { Result.failure(e) }
        result.exceptionOrNull()?.let { if (it is CancellationException) throw it }
        if (result.isSuccess) return Reachability(url, null)
        error = result.exceptionOrNull()
    }
    return Reachability(null, error)
}
