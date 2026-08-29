package com.zigger06.tajiksttcollector.ui

import com.zigger06.tajiksttcollector.network.ApiException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Keep transport details, hostnames and raw backend messages out of the volunteer UI.
 * Logs may remain technical on the PC, but a phone user only needs an actionable message.
 */
fun userFacingError(error: Throwable, fallback: String): String = when {
    error is ApiException && error.statusCode == 429 ->
        "Дархостҳо муваққатан маҳдуд шуданд. Каме интизор шавед ва дубора кӯшиш кунед."
    error is UnknownHostException || error is ConnectException || error is SocketTimeoutException ->
        "Сервер Дастнорас аст"
    error is IllegalStateException && fallback.startsWith("Пайвастшав") ->
        "Сервер Дастнорас аст"
    else -> fallback
}
