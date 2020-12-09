# Generated by Django 3.0.11 on 2020-12-09 01:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("multi_tenancy", "0007_delete_teambilling"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationbilling",
            name="stripe_subscription_item_id",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="plan",
            name="is_metered_billing",
            field=models.BooleanField(default=False),
        ),
    ]