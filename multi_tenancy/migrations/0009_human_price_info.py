# Generated by Django 3.0.11 on 2021-02-09 07:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("multi_tenancy", "0008_metered_billing_support"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan", name="price_string", field=models.CharField(blank=True, max_length=128),
        ),
    ]
