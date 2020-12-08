# Generated by Django 3.0.6 on 2020-12-07 23:22

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('multi_tenancy', '0007_delete_teambilling'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationbilling',
            name='stripe_subscription_item_id',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='plan',
            name='is_metered_billing',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='MonthlyBillingRecord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('billing_period', models.DateField()),
                ('event_usage', models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)])),
                ('usage_reported', models.BooleanField(default=False)),
                ('organization_billing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_records', to='multi_tenancy.OrganizationBilling')),
            ],
            options={
                'unique_together': {('organization_billing', 'billing_period')},
            },
        ),
    ]
