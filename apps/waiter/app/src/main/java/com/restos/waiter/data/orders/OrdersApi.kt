package com.restos.waiter.data.orders

import com.restos.waiter.data.common.PagedEnvelope
import com.restos.waiter.data.net.Envelope
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface OrdersApi {
    /**
     * Список заказов. Без фильтра — возвращает все заказы ресторана за
     * последние 24 часа (см. apps/orders/views.py::OrderViewSet.get_queryset).
     * Параметр `created_at_from` (ISO-8601) сужает окно — нам надо «с начала
     * сегодняшнего дня в локальной таймзоне».
     */
    @GET("api/v1/orders/")
    suspend fun listOrders(
        @Query("created_at_from") createdAtFrom: String? = null,
        @Query("status") status: String? = null,
        @Query("page_size") pageSize: Int? = 200,
    ): PagedEnvelope<OrderDto>

    @GET("api/v1/orders/me/")
    suspend fun myActive(): PagedEnvelope<OrderDto>

    @GET("api/v1/orders/{id}/")
    suspend fun retrieve(@Path("id") id: Long): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/add_items/")
    suspend fun addItems(
        @Path("id") id: Long,
        @Body body: AddItemsRequest,
    ): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/cancel_item/")
    suspend fun cancelItem(
        @Path("id") id: Long,
        @Body body: CancelItemRequest,
    ): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/cancel/")
    suspend fun cancelOrder(
        @Path("id") id: Long,
        @Body body: CancelOrderRequest,
    ): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/transfer/")
    suspend fun transfer(
        @Path("id") id: Long,
        @Body body: TransferRequest,
    ): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/request_bill/")
    suspend fun requestBill(@Path("id") id: Long): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/print_pre_bill/")
    suspend fun printPreBill(@Path("id") id: Long): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/assign_waiter/")
    suspend fun assignWaiter(
        @Path("id") id: Long,
        @Body body: AssignWaiterRequest,
    ): Envelope<OrderDto>

    @POST("api/v1/orders/{id}/set_item_note/")
    suspend fun setItemNote(
        @Path("id") id: Long,
        @Body body: SetItemNoteRequest,
    ): Envelope<OrderDto>

    @GET("api/v1/orders/me/stats/today/")
    suspend fun myTodayStats(): Envelope<WaiterTodayStats>
}

@Serializable
data class AssignWaiterRequest(@SerialName("waiter_id") val waiterId: Long)

@Serializable
data class SetItemNoteRequest(
    @SerialName("item_id") val itemId: Long,
    val note: String,
)

@Serializable
data class WaiterTodayStats(
    @SerialName("orders_count") val ordersCount: Int = 0,
    val total: String = "0",
    @SerialName("service_charge") val serviceCharge: String = "0",
    val tip: String = "0",
)

@Serializable
data class AddItemsRequest(val items: List<NewOrderItem>)

@Serializable
data class NewOrderItem(
    @SerialName("menu_item_id") val menuItemId: Long,
    val qty: Int,
    val note: String = "",
    @SerialName("modifier_ids") val modifierIds: List<Long> = emptyList(),
)

@Serializable
data class CancelItemRequest(
    @SerialName("item_id") val itemId: Long,
    val reason: String,
)

@Serializable
data class CancelOrderRequest(val reason: String)

@Serializable
data class TransferRequest(@SerialName("table_id") val tableId: Long)

@Serializable
data class OrderDto(
    val id: Long,
    val status: String,
    @SerialName("status_display") val statusDisplay: String? = null,
    @SerialName("order_type") val orderType: String,
    val table: Long? = null,
    @SerialName("table_name") val tableName: String? = null,
    @SerialName("table_zone_name") val tableZoneName: String? = null,
    val waiter: Long? = null,
    @SerialName("waiter_name") val waiterName: String? = null,
    @SerialName("guests_count") val guestsCount: Int = 0,
    val subtotal: String = "0",
    val total: String = "0",
    @SerialName("service_charge_amount") val serviceChargeAmount: String = "0",
    @SerialName("discount_amount") val discountAmount: String = "0",
    @SerialName("tip_amount") val tipAmount: String = "0",
    val items: List<OrderItemDto> = emptyList(),
    @SerialName("cancelled_items") val cancelledItems: List<CancelledItemDto> = emptyList(),
    @SerialName("created_at") val createdAt: String,
    @SerialName("bill_requested_at") val billRequestedAt: String? = null,
    @SerialName("closed_at") val closedAt: String? = null,
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    @SerialName("updated_at") val updatedAt: String,
    val comment: String = "",
)

@Serializable
data class CancelledItemDto(
    val id: Long,
    @SerialName("menu_item") val menuItem: Long,
    @SerialName("name_at_order") val nameAtOrder: String,
    @SerialName("price_at_order") val priceAtOrder: String,
    val qty: Int,
    @SerialName("cancel_reason") val cancelReason: String = "",
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    @SerialName("cancelled_by_name") val cancelledByName: String? = null,
)

@Serializable
data class OrderItemDto(
    val id: Long,
    @SerialName("menu_item") val menuItem: Long,
    @SerialName("name_at_order") val nameAtOrder: String,
    @SerialName("price_at_order") val priceAtOrder: String,
    val qty: Int,
    val note: String = "",
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    @SerialName("sent_to_kitchen_at") val sentToKitchenAt: String? = null,
    @SerialName("served_at") val servedAt: String? = null,
    @SerialName("kitchen_status") val kitchenStatus: String? = null,
    val subtotal: String = "0",
)

/** Статусы заказа на стороне Django (apps/orders/models.py::OrderStatus). */
object OrderStatus {
    const val NEW = "new"
    const val BILL_REQUESTED = "bill_requested"
    const val DONE = "done"
    const val CANCELLED = "cancelled"

    /** Заказ ещё «живой» — должен показываться на карточке стола. */
    fun isActive(status: String): Boolean = status == NEW || status == BILL_REQUESTED
}
