package com.restos.waiter.data.events

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Транспорт SSE-событий между EventStreamClient и подписчиками (ViewModels).
 * extraBufferCapacity > 0 — чтобы emit'ы из IO-потока не блокировались.
 */
@Singleton
class EventBus @Inject constructor() {
    private val _events = MutableSharedFlow<ServerEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<ServerEvent> = _events.asSharedFlow()

    suspend fun emit(event: ServerEvent) = _events.emit(event)
}

sealed interface ServerEvent {
    /** «Полностью обновить состояние» — при reconnect/resync. */
    data object Resync : ServerEvent

    data class OrderCreated(val orderId: Long, val waiterId: Long?) : ServerEvent
    data class OrderUpdated(val orderId: Long, val waiterId: Long?, val status: String?) : ServerEvent
    data class TableUpdated(val tableId: Long) : ServerEvent

    /** Любое другое событие — для логирования / будущих фич. */
    data class Other(val type: String) : ServerEvent
}
