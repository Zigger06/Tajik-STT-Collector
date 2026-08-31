package com.zigger06.tajiksttcollector.network

import android.util.Log
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.Handshake
import okhttp3.Protocol
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Proxy

private const val NETWORK_DIAG_TAG = "TajikSTT-NET"

/**
 * Diagnostic-only observer used on the DIAG branch.
 * It does not alter DNS, TLS, protocols, timeouts, requests, or credentials.
 */
internal class NetworkDiagEventListener : EventListener() {
    override fun callStart(call: Call) {
        val request = call.request()
        Log.e(
            NETWORK_DIAG_TAG,
            "callStart ${request.method} ${request.url.scheme}://${request.url.host}${request.url.encodedPath}",
        )
    }

    override fun dnsStart(call: Call, domainName: String) {
        Log.e(NETWORK_DIAG_TAG, "dnsStart host=$domainName")
    }

    override fun dnsEnd(call: Call, domainName: String, inetAddressList: List<InetAddress>) {
        Log.e(
            NETWORK_DIAG_TAG,
            "dnsEnd host=$domainName addresses=${inetAddressList.joinToString { address -> address.hostAddress ?: "?" }}",
        )
    }

    override fun connectStart(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy) {
        Log.e(
            NETWORK_DIAG_TAG,
            "connectStart address=${inetSocketAddress.address?.hostAddress}:${inetSocketAddress.port} proxy=$proxy",
        )
    }

    override fun secureConnectStart(call: Call) {
        Log.e(NETWORK_DIAG_TAG, "secureConnectStart")
    }

    override fun secureConnectEnd(call: Call, handshake: Handshake?) {
        Log.e(
            NETWORK_DIAG_TAG,
            "secureConnectEnd tls=${handshake?.tlsVersion} cipher=${handshake?.cipherSuite}",
        )
    }

    override fun connectEnd(
        call: Call,
        inetSocketAddress: InetSocketAddress,
        proxy: Proxy,
        protocol: Protocol?,
    ) {
        Log.e(
            NETWORK_DIAG_TAG,
            "connectEnd address=${inetSocketAddress.address?.hostAddress}:${inetSocketAddress.port} protocol=$protocol",
        )
    }

    override fun connectFailed(
        call: Call,
        inetSocketAddress: InetSocketAddress,
        proxy: Proxy,
        protocol: Protocol?,
        ioe: IOException,
    ) {
        Log.e(
            NETWORK_DIAG_TAG,
            "connectFailed address=${inetSocketAddress.address?.hostAddress}:${inetSocketAddress.port} protocol=$protocol error=${ioe.javaClass.name}: ${ioe.message}",
            ioe,
        )
    }

    override fun callFailed(call: Call, ioe: IOException) {
        Log.e(
            NETWORK_DIAG_TAG,
            "callFailed error=${ioe.javaClass.name}: ${ioe.message}",
            ioe,
        )
    }
}
