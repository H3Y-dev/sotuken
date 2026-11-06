package jp.sotuken.metercapture.ui

import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import jp.sotuken.metercapture.queue.sender.HttpSender
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.*

data class NetworkSnapshot(val wifi: Boolean, val wired: Boolean, val usbTether: Boolean)

class ReceiverHealthState internal constructor(
    private val settings: ReceiverSettings,
    private val scope: CoroutineScope,
) {
    var configured: Boolean by mutableStateOf(settings.isConfigured())
        private set
    var healthOk: Boolean? by mutableStateOf(null)
        private set
    var reason: String by mutableStateOf("")
        private set
    val network = NetworkSnapshot(false, false, false)
    private var inFlight = false
    private var generation = 0

    fun check(force: Boolean = false) {
        val url = settings.getUrl()
        val token = settings.getToken()
        if (!settings.isConfigured() || url.isNullOrBlank() || token.isNullOrBlank()) {
            generation++
            inFlight = false
            healthOk = null
            return
        }
        if (inFlight && !force) return
        inFlight = true
        val current = ++generation
        scope.launch {
            val result = withContext(Dispatchers.IO) { HttpSender.health(url, token) }
            if (current == generation) {
                healthOk = result.isSuccess
                reason = classifyHealthFailure(result.exceptionOrNull())
                inFlight = false
            }
        }
    }

    fun onSettingsChanged() {
        configured = settings.isConfigured()
        healthOk = null
        check(force = true)
    }
}

@Composable
fun rememberReceiverHealth(onBecameReachable: () -> Unit = {}): ReceiverHealthState {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val state = remember { ReceiverHealthState(ReceiverSettings(context), scope) }
    var resumed by remember { mutableStateOf(false) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { resumed = true; state.check() }
    LifecycleEventEffect(Lifecycle.Event.ON_PAUSE) { resumed = false }
    LaunchedEffect(resumed) {
        if (resumed) while (true) { delay(15_000); state.check() }
    }
    return state
}
