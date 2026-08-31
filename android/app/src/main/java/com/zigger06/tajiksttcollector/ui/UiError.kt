package com.zigger06.tajiksttcollector.ui

import android.util.Log
import com.zigger06.tajiksttcollector.network.ApiException
import com.zigger06.tajiksttcollector.network.TlsDiagnosticProbe
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

private const val DIAG_TAG = "TajikSTT-DIAG"

/**
 * Diagnostic-only branch: always log the real exception and stack trace.
 * This branch must never be merged into release code.
 */
fun userFacingError(error: Throwable, fallback: String): String {
    Log.e(
        DIAG_TAG,
        "Caught ${error.javaClass.name}: ${error.message ?: "<no message>"}",
        error,
    )

    if (error is SSLHandshakeException || error is ConnectException) {
        TlsDiagnosticProbe.runAsync()
    }

    return when {
        error is ApiException && error.statusCode == 429 ->
            "Дархостҳо муваққатан маҳдуд шуданд. Каме интизор шавед ва дубора кӯшиш кунед."
        error is UnknownHostException || error is ConnectException || error is SocketTimeoutException ->
            "Сервер Дастнорас аст"
        error is IllegalStateException && fallback.startsWith("Пайвастшав") ->
            "Сервер Дастнорас аст"
        else -> fallback
    }
}
