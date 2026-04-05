from django.db import migrations


def populate_exchange(apps, schema_editor):
    CandleSource = apps.get_model("candle_sources", "CandleSource")
    for cs in CandleSource.objects.select_related("exchange_client__exchange").all():
        cs.exchange = cs.exchange_client.exchange
        cs.save(update_fields=["exchange"])


def reverse_populate(apps, schema_editor):
    CandleSource = apps.get_model("candle_sources", "CandleSource")
    CandleSource.objects.all().update(exchange=None)


class Migration(migrations.Migration):

    dependencies = [
        ("candle_sources", "0007_add_exchange_fk"),
    ]

    operations = [
        migrations.RunPython(populate_exchange, reverse_populate),
    ]
