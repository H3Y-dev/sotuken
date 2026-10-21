package jp.sotuken.metercapture.settings

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class ReceiverSettingsTest {

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
