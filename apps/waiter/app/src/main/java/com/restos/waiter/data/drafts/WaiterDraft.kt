package com.restos.waiter.data.drafts

import kotlinx.serialization.Serializable

/**
 * Локальный черновик заказа (offline-первая фича). Хранится в DataStore
 * как JSON. Никогда не уходит на бэк сам по себе — только при `createOrder`.
 *
 * Один черновик на стол на пользователя. Ключ в DataStore = "tableId:waiterId".
 */
@Serializable
data class WaiterDraft(
    val tableId: Long,
    val waiterId: Long,
    val guestsCount: Int = 1,
    val lines: List<DraftLine> = emptyList(),
    val updatedAt: Long = System.currentTimeMillis(),
)

@Serializable
data class DraftLine(
    val menuItemId: Long,
    val nameAtAdd: String,
    val price: String,
    val qty: Int = 1,
    val note: String = "",
)
