package com.restos.waiter.data.events

import com.restos.waiter.data.auth.TokenStore
import com.restos.waiter.data.net.NetworkConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Держит одну SSE-подписку на /api/v1/events/. Автоматически переподключается
 * с back-off при разрыве. Эмиттит ServerEvent в EventBus.
 *
 * `start()` идемпотентен. `stop()` обрывает и cancel'ит retry-loop.
 */
@Singleton
class EventStreamClient @Inject constructor(
    private val tokenStore: TokenStore,
    private val config: NetworkConfig,
    private val bus: EventBus,
    private val json: Json,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loopJob: Job? = null
    private var currentSource: EventSource? = null

    @Synchronized
    fun start() {
        if (loopJob?.isActive == true) return
        loopJob = scope.launch { runReconnectLoop() }
    }

    @Synchronized
    fun stop() {
        loopJob?.cancel()
        loopJob = null
        currentSource?.cancel()
        currentSource = null
    }

    private suspend fun runReconnectLoop() {
        var backoffMs = 1000L
        while (scope.isActive) {
            val token = tokenStore.current()?.access
            if (token.isNullOrBlank()) {
                // Не авторизован — ждём и пробуем снова (но не палим лог).
                delay(2000)
                continue
            }

            val request = Request.Builder()
                .url("${config.baseUrl}api/v1/events/")
                .header("Accept", "text/event-stream")
                .header("Authorization", "Bearer $token")
                .build()

            val factory = EventSources.createFactory(buildSseClient())
            val terminated = kotlinx.coroutines.CompletableDeferred<Unit>()
            val source = factory.newEventSource(request, Listener(bus, json) { terminated.complete(Unit) })
            currentSource = source

            terminated.await()
            currentSource = null

            if (!scope.isActive) return
            delay(backoffMs)
            backoffMs = (backoffMs * 2).coerceAtMost(MAX_BACKOFF_MS)
        }
    }

    private fun buildSseClient(): OkHttpClient =
        // Отдельный клиент: long-poll'у не нужны write/connect ограничения
        // основного клиента, read-таймаут 0 = неограничен.
        OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .retryOnConnectionFailure(true)
            .build()

    private companion object {
        const val MAX_BACKOFF_MS = 30_000L
    }
}

private class Listener(
    private val bus: EventBus,
    private val json: Json,
    private val onTerminate: () -> Unit,
) : EventSourceListener() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onOpen(eventSource: EventSource, response: Response) {
        // Подключились — следующий backoff сбросится наружу через перезапуск
        // (loop сам понимает, что сначала reconnect = 1s).
    }

    override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
        val evt = parse(type, data) ?: return
        scope.launch { bus.emit(evt) }
    }

    override fun onClosed(eventSource: EventSource) { onTerminate() }
    override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
        onTerminate()
    }

    private fun parse(type: String?, data: String): ServerEvent? {
        val t = type ?: return null
        return when (t) {
            "resync" -> ServerEvent.Resync
            "order.created", "order.updated" -> {
                val payload = parseJson(data)
                val orderId = payload.longOrNull("id") ?: payload.longOrNull("order_id")
                val waiterId = payload.longOrNull("waiter_id")
                val status = payload.string("status")
                if (orderId == null) ServerEvent.Other(t)
                else if (t == "order.created") ServerEvent.OrderCreated(orderId, waiterId)
                else ServerEvent.OrderUpdated(orderId, waiterId, status)
            }
            "table.updated" -> {
                val payload = parseJson(data)
                val tableId = payload.longOrNull("id") ?: payload.longOrNull("table_id")
                if (tableId == null) ServerEvent.Other(t)
                else ServerEvent.TableUpdated(tableId)
            }
            else -> ServerEvent.Other(t)
        }
    }

    private fun parseJson(data: String): JsonObject =
        runCatching { json.parseToJsonElement(data) as JsonObject }
            .getOrDefault(JsonObject(emptyMap()))

    private fun JsonObject.longOrNull(key: String): Long? =
        runCatching { this[key]?.jsonPrimitive?.longOrNull }.getOrNull()

    private fun JsonObject.string(key: String): String? =
        runCatching { this[key]?.jsonPrimitive?.content }.getOrNull()
}
