package jp.sotuken.metercapture.ui

import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import jp.sotuken.metercapture.queue.sender.HttpSender
import jp.sotuken.metercapture.settings.ReceiverSettings
import kotlinx.coroutines.*
import android.net.*
import jp.sotuken.metercapture.settings.pickReachableUrl

class ReceiverHealthState internal constructor(
    private val settings: ReceiverSettings,
    private val scope: CoroutineScope,
    private val readNetwork: () -> NetworkSnapshot = { NetworkSnapshot(false, false, false) },
    private val onBecameReachable: () -> Unit = {},
) {
    var configured: Boolean by mutableStateOf(settings.isConfigured())
        private set
    var healthOk: Boolean? by mutableStateOf(null)
        private set
    var reason: String by mutableStateOf("")
        private set
    var network by mutableStateOf(NetworkSnapshot(false, false, false))
        private set
    private var inFlight = false
    private var generation = 0

    fun check(force: Boolean = false) {
        val target = settings.sendTarget()
        if (!target.isConfigured()) {
            generation++
            inFlight = false
            healthOk = null
            scope.launch { network = withContext(Dispatchers.IO) { readNetwork() } }
            return
        }
        if (inFlight && !force) return
        inFlight = true
        val current = ++generation
        scope.launch {
            val (snapshot, reach) = withContext(Dispatchers.IO) {
                readNetwork() to pickReachableUrl(target.candidateUrls) { HttpSender.health(it, target.token!!) }
            }
            if (current == generation) {
                val previous = healthOk
                network = snapshot
                healthOk = reach.url != null
                reason = classifyHealthFailure(reach.error)
                inFlight = false
                if (shouldTriggerAutoSend(previous, reach.url != null, true)) onBecameReachable()
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
    val latestOnReachable by rememberUpdatedState(onBecameReachable)
    val networks = remember { java.util.concurrent.ConcurrentHashMap<Network, NetworkCapabilities>() }
    val state = remember { ReceiverHealthState(ReceiverSettings(context), scope,
        readNetwork = { readNetworkSnapshot(context, networks.values.toList()) },
        onBecameReachable = { latestOnReachable() }) }
    DisposableEffect(context) {
        val manager = context.getSystemService(android.net.ConnectivityManager::class.java)
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                manager.getNetworkCapabilities(network)?.let { networks[network] = it }
                scope.launch { state.check(force = true) }
            }
            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                networks[network] = capabilities
                scope.launch { state.check(force = true) }
            }
            override fun onLost(network: Network) {
                networks.remove(network)
                scope.launch { state.check(force = true) }
            }
        }
        manager.registerNetworkCallback(NetworkRequest.Builder().build(), callback)
        onDispose { manager.unregisterNetworkCallback(callback); networks.clear() }
    }
    var resumed by remember { mutableStateOf(false) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { resumed = true; state.check() }
    LifecycleEventEffect(Lifecycle.Event.ON_PAUSE) { resumed = false }
    LaunchedEffect(resumed) {
        if (resumed) while (true) { delay(15_000); state.check() }
    }
    return state
}
