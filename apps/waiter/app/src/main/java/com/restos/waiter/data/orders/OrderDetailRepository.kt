package com.restos.waiter.data.orders

import com.restos.waiter.data.auth.UserDto
import com.restos.waiter.data.cache.AppCache
import com.restos.waiter.data.kitchen.KitchenApi
import com.restos.waiter.data.menu.MenuApi
import com.restos.waiter.data.menu.MenuItemDto
import com.restos.waiter.data.tables.TableDto
import com.restos.waiter.data.tables.TablesApi
import com.restos.waiter.data.users.UsersApi
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class OrderDetailRepository @Inject constructor(
    private val ordersApi: OrdersApi,
    private val menuApi: MenuApi,
    private val tablesApi: TablesApi,
    private val cancelReasonsApi: CancelReasonsApi,
    private val kitchenApi: KitchenApi,
    private val usersApi: UsersApi,
    private val cache: AppCache,
) {
    val cachedMenu: List<MenuItemDto> get() = cache.menuItems.value
    val cachedTables: List<TableDto> get() = cache.tables.value
    val cachedWaiters: List<UserDto> get() = cache.users.value.filter { it.role == "waiter" }
    suspend fun loadInitial(orderId: Long): OrderDetailBundle = coroutineScope {
        val orderDef = async { ordersApi.retrieve(orderId).data!! }
        val menuDef = async { runCatching { menuApi.listItems().data }.getOrNull() }
        val tablesDef = async { runCatching { tablesApi.listTables().data }.getOrNull() }
        val waitersDef = async {
            runCatching { usersApi.listUsers().data }.getOrNull()
        }
        val groupsDef = async {
            // Все активные заказы — нужны чтобы посчитать «группы» на одном столе.
            runCatching { ordersApi.listOrders().data }.getOrDefault(emptyList())
        }
        val order = orderDef.await().also { cache.putOrder(it) }
        val allActive = groupsDef.await()
            .also { cache.putOrders(it) }
            .filter { OrderStatus.isActive(it.status) }
        val groups = if (order.table != null) {
            allActive.filter { it.table == order.table }.sortedBy { it.createdAt }
        } else listOf(order)

        val menu = menuDef.await()?.also { cache.setMenu(it) } ?: cache.menuItems.value
        val tables = tablesDef.await()?.also { cache.setTables(it) } ?: cache.tables.value
        val waitersAll = waitersDef.await()?.also { cache.setUsers(it) } ?: cache.users.value
        val waiters = waitersAll.filter { it.role == "waiter" }

        OrderDetailBundle(
            order = order,
            menu = menu,
            tables = tables,
            waiters = waiters,
            groups = groups,
        )
    }

    suspend fun refreshOrder(orderId: Long): OrderDto =
        ordersApi.retrieve(orderId).data!!.also { cache.putOrder(it) }

    fun cachedOrder(orderId: Long): OrderDto? = cache.getOrder(orderId)

    suspend fun addItem(orderId: Long, item: NewOrderItem): OrderDto =
        ordersApi.addItems(orderId, AddItemsRequest(listOf(item))).data!!

    suspend fun cancelItem(orderId: Long, itemId: Long, reason: String): OrderDto =
        ordersApi.cancelItem(orderId, CancelItemRequest(itemId, reason)).data!!

    suspend fun cancelOrder(orderId: Long, reason: String): OrderDto =
        ordersApi.cancelOrder(orderId, CancelOrderRequest(reason)).data!!

    suspend fun transfer(orderId: Long, newTableId: Long): OrderDto =
        ordersApi.transfer(orderId, TransferRequest(newTableId)).data!!

    suspend fun requestBill(orderId: Long): OrderDto =
        ordersApi.requestBill(orderId).data!!

    suspend fun printPreBill(orderId: Long): OrderDto =
        ordersApi.printPreBill(orderId).data!!

    suspend fun loadCancelReasons(kind: String): List<CancelReasonDto> =
        runCatching { cancelReasonsApi.list(kind).data }
            .getOrDefault(emptyList())
            .filter { it.isActive }
            .sortedBy { it.sortOrder }

    suspend fun markServed(itemId: Long) { kitchenApi.markServed(itemId) }
    suspend fun unmarkServed(itemId: Long) { kitchenApi.unmarkServed(itemId) }

    suspend fun assignWaiter(orderId: Long, waiterId: Long): OrderDto =
        ordersApi.assignWaiter(orderId, AssignWaiterRequest(waiterId = waiterId)).data!!

    suspend fun setItemNote(orderId: Long, itemId: Long, note: String): OrderDto =
        ordersApi.setItemNote(orderId, SetItemNoteRequest(itemId = itemId, note = note)).data!!
}

data class OrderDetailBundle(
    val order: OrderDto,
    val menu: List<MenuItemDto>,
    val tables: List<TableDto>,
    val waiters: List<UserDto> = emptyList(),
    val groups: List<OrderDto> = emptyList(),
)
