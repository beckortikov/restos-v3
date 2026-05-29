package com.restos.waiter.data.kitchen

import com.restos.waiter.data.net.Envelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.POST
import retrofit2.http.Path

interface KitchenApi {
    /** Отметить позицию как поданную гостю. waiter может на своих заказах. */
    @POST("api/v1/kitchen/items/{id}/mark_served/")
    suspend fun markServed(@Path("id") itemId: Long): Envelope<KitchenItemDto>

    /** Откатить «подано» обратно в READY. */
    @POST("api/v1/kitchen/items/{id}/unmark_served/")
    suspend fun unmarkServed(@Path("id") itemId: Long): Envelope<KitchenItemDto>
}

@Serializable
data class KitchenItemDto(
    val id: Long,
    @SerialName("kitchen_status") val kitchenStatus: String,
    @SerialName("served_at") val servedAt: String? = null,
)
