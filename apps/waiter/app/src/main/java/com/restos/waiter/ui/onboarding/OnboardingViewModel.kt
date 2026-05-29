package com.restos.waiter.ui.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.restos.waiter.data.config.ServerConfigStore
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import javax.inject.Inject

data class OnboardingUiState(
    val url: String = "",
    val testing: Boolean = false,
    val error: String? = null,
    val testOk: Boolean = false,
    val done: Boolean = false,
)

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val configStore: ServerConfigStore,
) : ViewModel() {

    private val _state = MutableStateFlow(OnboardingUiState())
    val state: StateFlow<OnboardingUiState> = _state.asStateFlow()

    private val probeClient = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()

    fun setUrl(s: String) {
        _state.update { it.copy(url = s, error = null, testOk = false) }
    }

    /** Из QR прилетает строка — может быть просто http://host:port/ либо
     *  URL вида http://host/?pair=... — нам важна только база. */
    fun onQrScanned(raw: String) {
        val cleaned = raw.trim()
        if (cleaned.isBlank()) return
        // Берём только origin: scheme://host[:port]/
        val origin = runCatching {
            val uri = java.net.URI(if (cleaned.contains("://")) cleaned else "http://$cleaned")
            val port = if (uri.port > 0) ":${uri.port}" else ""
            "${uri.scheme ?: "http"}://${uri.host}$port/"
        }.getOrNull() ?: cleaned

        _state.update { it.copy(url = origin, error = null, testOk = false) }
        testAndSave()
    }

    fun testAndSave() {
        val raw = _state.value.url
        if (!ServerConfigStore.isValid(raw)) {
            _state.update { it.copy(error = "Введите корректный адрес сервера") }
            return
        }
        val normalized = ServerConfigStore.normalize(raw)
        _state.update { it.copy(testing = true, error = null, testOk = false) }
        viewModelScope.launch {
            val result = probe(normalized)
            if (result.error != null) {
                _state.update { it.copy(testing = false, error = result.error) }
                return@launch
            }
            configStore.save(normalized)
            _state.update { it.copy(testing = false, testOk = true, done = true) }
        }
    }

    private data class ProbeResult(val error: String?)

    private suspend fun probe(baseUrl: String): ProbeResult = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("${baseUrl}api/v1/auth/me/")
            .get()
            .build()
        try {
            probeClient.newCall(request).execute().use { resp ->
                // Любой HTTP-статус значит «сервер достижим».
                if (resp.code in 200..599) ProbeResult(error = null)
                else ProbeResult(error = "Сервер вернул неожиданный код HTTP ${resp.code}")
            }
        } catch (e: java.net.SocketTimeoutException) {
            ProbeResult(error = "Таймаут (3с): сервер не отвечает по этому адресу. Сеть/IP/порт неверны или ресторан в другой LAN.")
        } catch (e: java.net.ConnectException) {
            ProbeResult(error = "Connection refused: на этом IP:порте никто не слушает. Проверь, что Django запущен на нужном порту.")
        } catch (e: java.net.UnknownHostException) {
            ProbeResult(error = "Не удалось разрешить адрес ${e.message ?: "сервера"}.")
        } catch (e: java.net.NoRouteToHostException) {
            ProbeResult(error = "No route to host: телефон не в одной LAN с сервером.")
        } catch (e: javax.net.ssl.SSLException) {
            ProbeResult(error = "SSL ошибка: ${e.message ?: "неизвестно"}. Используйте http://, а не https://.")
        } catch (e: java.io.IOException) {
            ProbeResult(error = "Сетевая ошибка: ${e.javaClass.simpleName} ${e.message ?: ""}".trim())
        } catch (e: Throwable) {
            ProbeResult(error = "${e.javaClass.simpleName}: ${e.message ?: "неизвестная ошибка"}")
        }
    }
}
