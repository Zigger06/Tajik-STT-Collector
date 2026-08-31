package com.zigger06.tajiksttcollector.ui

import android.util.Log
import com.zigger06.tajiksttcollector.BuildConfig
import com.zigger06.tajiksttcollector.network.ApiException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

private const val DIAG_TAG = "TajikSTT-DIAG"

/**
 * Keep transport details, hostnames and raw backend messages out of the volunteer UI.
 * Debug builds log the real exception and stack trace for developer diagnostics only.
 */
fun userFacingError(error: Throwable, fallback: String): String {
    if (BuildConfig.DEBUG) {
        Log.e(
            DIAG_TAG,
            "Caught ${error.javaClass.name}: ${error.message ?: "<no message>"}",
            error,
        )
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
