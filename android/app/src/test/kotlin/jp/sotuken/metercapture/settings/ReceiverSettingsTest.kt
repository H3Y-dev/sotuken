package jp.sotuken.metercapture.settings

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class ReceiverSettingsTest {
    @Test fun sendTargetListsPrimaryThenCandidates() {
        val values = mutableMapOf<String, Any>(ReceiverSettings.KEY_URL to "http://10.0.0.1:8765", ReceiverSettings.KEY_TOKEN to "token",
            ReceiverSettings.KEY_ALT_URLS to "[\"http://192.168.1.2:8765\",\"http://10.0.0.1:8765\",\"http://8.8.8.8:80\"]")
        val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java)) { _, method, _ ->
            check(method.name == "getAll"); values.toMap()
        } as SharedPreferences
        assertEquals(listOf("http://10.0.0.1:8765", "http://192.168.1.2:8765"), ReceiverSettings(prefs).sendTarget().candidateUrls)
    }
    @Test fun manualSaveClearsCandidates() {
        val values = mutableMapOf(ReceiverSettings.KEY_ALT_URLS to "[\"http://10.0.0.1:8765\"]")
        lateinit var editor: SharedPreferences.Editor
        editor = Proxy.newProxyInstance(SharedPreferences.Editor::class.java.classLoader, arrayOf(SharedPreferences.Editor::class.java)) { _, method, args ->
            when (method.name) {
                "putString" -> { values[args!![0] as String] = args[1] as String; editor }
                "remove" -> { values.remove(args!![0]); editor }
                "apply" -> null
                else -> error(method.name)
            }
        } as SharedPreferences.Editor
        val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java)) { _, method, _ ->
            check(method.name == "edit"); editor
        } as SharedPreferences
        ReceiverSettings(prefs).save("http://192.168.0.2:8765", "token")
        assertFalse(values.containsKey(ReceiverSettings.KEY_ALT_URLS))
    }

    @Test
    fun sendTargetKeepsUrlTokenAndIdFromOneSettingsSnapshot() {
        val values = mutableMapOf<String, Any>(ReceiverSettings.KEY_URL to "http://192.168.1.2:8765",
            ReceiverSettings.KEY_TOKEN to "old-token", ReceiverSettings.KEY_RECEIVER_ID to "old-pc")
        val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader,
            arrayOf(SharedPreferences::class.java)) { _, method, _ ->
            check(method.name == "getAll")
            values.toMap()
        } as SharedPreferences
        val target = ReceiverSettings(prefs).sendTarget()
        values[ReceiverSettings.KEY_URL] = "http://192.168.1.3:8765"
        values[ReceiverSettings.KEY_TOKEN] = "new-token"
        values[ReceiverSettings.KEY_RECEIVER_ID] = "new-pc"
        assertEquals("http://192.168.1.2:8765", target.url)
        assertEquals("old-token", target.token)
        assertEquals("old-pc", target.receiverId)
        assertTrue(target.isConfigured())
    }

    @Test
    fun saveRejectsNonPrivateHostsBeforeWritingPreferences() {
        val prefs = Proxy.newProxyInstance(
            SharedPreferences::class.java.classLoader,
            arrayOf(SharedPreferences::class.java),
        ) { _, _, _ -> throw AssertionError("Invalid settings must not access preferences") } as SharedPreferences
        val settings = ReceiverSettings(prefs)
        for (url in listOf("http://8.8.8.8", "http://127.0.0.1", "http://example.com")) {
            assertThrows(IllegalArgumentException::class.java) { settings.save(url, "secret") }
        }
    }

    @Test
    fun privateIpv4RejectsAmbiguousOctets() {
        for (host in listOf("010.0.0.1", "192.168.01.1", "+10.0.0.1", "10.0.0.-1")) {
            assertFalse(host, PrivateIpv4Validator.isPrivateIpv4Host(host))
        }
    }

    @Test
    fun privateIpv4HostValidation() {
        // 10.0.0.0/8
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("10.0.0.1"))
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("10.255.255.255"))

        // 172.16.0.0/12
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("172.16.0.1"))
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("172.31.255.255"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("172.15.255.255"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("172.32.0.1"))

        // 192.168.0.0/16
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("192.168.0.1"))
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("192.168.1.50"))
        assertTrue(PrivateIpv4Validator.isPrivateIpv4Host("192.168.255.255"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("192.169.1.1"))

        // Loopback & Public IPs must be rejected
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("127.0.0.1"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("8.8.8.8"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("1.1.1.1"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("example.com"))
        assertFalse(PrivateIpv4Validator.isPrivateIpv4Host("localhost"))
    }

    @Test
    fun validateUrlAcceptsValidPrivateIpv4Urls() {
        val result1 = PrivateIpv4Validator.validateUrl("http://192.168.1.20:8765")
        assertTrue(result1 is PrivateIpv4Validator.ValidationResult.Valid)

        val result2 = PrivateIpv4Validator.validateUrl("http://10.0.2.2:8765")
        assertTrue(result2 is PrivateIpv4Validator.ValidationResult.Valid)

        val result3 = PrivateIpv4Validator.validateUrl("172.20.10.5:8765")
        assertTrue(result3 is PrivateIpv4Validator.ValidationResult.Valid)
    }

    @Test
    fun validateUrlRejectsNonPrivateIpv4UrlsWithReason() {
        val loopbackResult = PrivateIpv4Validator.validateUrl("http://127.0.0.1:8765")
        assertTrue(loopbackResult is PrivateIpv4Validator.ValidationResult.Invalid)
        assertTrue(
            (loopbackResult as PrivateIpv4Validator.ValidationResult.Invalid).message.contains("プライベートIPv4"),
        )

        val publicResult = PrivateIpv4Validator.validateUrl("http://8.8.8.8:8765")
        assertTrue(publicResult is PrivateIpv4Validator.ValidationResult.Invalid)

        val domainResult = PrivateIpv4Validator.validateUrl("http://example.com:8765")
        assertTrue(domainResult is PrivateIpv4Validator.ValidationResult.Invalid)

        val emptyResult = PrivateIpv4Validator.validateUrl("   ")
        assertTrue(emptyResult is PrivateIpv4Validator.ValidationResult.Invalid)
    }
}
