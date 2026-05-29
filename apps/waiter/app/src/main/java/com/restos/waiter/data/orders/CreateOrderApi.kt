package com.restos.waiter.data.orders

import com.restos.waiter.data.net.Envelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.POST

/** Расширение OrdersApi для создания заказа. Вынесено отдельным интерфейсом
 *  чтобы Retrofit можно было свапнуть, если контракт изменится. */
interface CreateOrderApi {
    @POST("api/v1/orders/")
    suspend fun create(@Body body: CreateOrderRequest): Envelope<OrderDto>
}

@Serializable
data class CreateOrderRequest(
    @SerialName("order_type") val orderType: String = "hall",
    @SerialName("table_id") val tableId: Long? = null,
    @SerialName("guests_count") val guestsCount: Int = 1,
    val items: List<NewOrderItem>,
    val comment: String = "",
)
