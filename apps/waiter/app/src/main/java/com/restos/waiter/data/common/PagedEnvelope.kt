package com.restos.waiter.data.common

import kotlinx.serialization.Serializable

/**
 * DRF DefaultRouter возвращает либо чистый массив, либо пагинированный объект:
 *   {"count":N, "next":..., "previous":..., "results":[...]}
 *
 * Django REST framework в restos-v3 настроен без глобальной пагинации, и все
 * list-эндпоинты возвращают `{"data": [...]}` (см. apps/common/renderers.py).
 *
 * Используем единый wrapper.
 */
@Serializable
data class PagedEnvelope<T>(
    val data: List<T> = emptyList(),
    val meta: Meta? = null,
)

@Serializable
data class Meta(
    val total: Int? = null,
    val page: Int? = null,
    @kotlinx.serialization.SerialName("page_size") val pageSize: Int? = null,
    val pages: Int? = null,
)
