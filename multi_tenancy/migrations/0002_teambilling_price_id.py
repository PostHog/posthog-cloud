# Generated by Django 3.0.6 on 2020-08-15 19:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('multi_tenancy', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='teambilling',
            name='price_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
