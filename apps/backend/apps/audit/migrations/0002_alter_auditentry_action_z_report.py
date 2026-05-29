from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditentry',
            name='action',
            field=models.CharField(
                choices=[
                    ('login', 'Вход'),
                    ('logout', 'Выход'),
                    ('pin_change', 'Смена PIN'),
                    ('shift_open', 'Открытие смены'),
                    ('shift_close', 'Закрытие смены'),
                    ('z_report_printed', 'Печать Z-отчёта'),
                    ('cash_in', 'Внесение в кассу'),
                    ('cash_out', 'Изъятие из кассы'),
                    ('order_create', 'Создание заказа'),
                    ('order_add_items', 'Добавление позиций'),
                    ('order_cancel', 'Отмена заказа'),
                    ('order_close', 'Закрытие заказа (оплата)'),
                    ('order_transfer', 'Перенос на другой стол'),
                    ('item_cancel', 'Отмена позиции'),
                    ('bill_request', 'Запрос счёта'),
                    ('discount_apply', 'Применение скидки'),
                    ('discount_remove', 'Снятие скидки'),
                    ('refund', 'Возврат'),
                    ('user_create', 'Создание пользователя'),
                    ('user_update', 'Изменение пользователя'),
                    ('user_delete', 'Удаление пользователя'),
                    ('settings_update', 'Изменение настроек'),
                ],
                db_index=True,
                max_length=24,
            ),
        ),
    ]
