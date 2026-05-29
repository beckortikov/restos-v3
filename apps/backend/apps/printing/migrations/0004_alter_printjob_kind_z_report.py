from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('printing', '0003_printer_paper_size_alter_printjob_kind_printstation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='printjob',
            name='kind',
            field=models.CharField(
                choices=[
                    ('guest_receipt', 'Гостевой чек'),
                    ('kitchen_order', 'Заказ на кухню'),
                    ('bar_order', 'Заказ в бар'),
                    ('pre_bill', 'Пре-чек'),
                    ('refund_receipt', 'Чек возврата'),
                    ('z_report', 'Z-отчёт по смене'),
                ],
                default='guest_receipt',
                max_length=24,
            ),
        ),
    ]
