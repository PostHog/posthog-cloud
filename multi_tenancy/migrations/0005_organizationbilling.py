# Generated by Django 3.0.7 on 2020-09-23 14:57

from django.db import migrations, models
import django.db.models.deletion

def forwards_func(apps, schema_editor):
    TeamBilling = apps.get_model("multi_tenancy", "TeamBilling")
    OrganizationBilling = apps.get_model("multi_tenancy", "OrganizationBilling")
    for team_billing in TeamBilling.objects.all():
        OrganizationBilling.objects.create(
            organization=team_billing.team.organization,
            stripe_customer_id=team_billing.stripe_customer_id,
            stripe_checkout_session=team_billing.stripe_checkout_session,
            checkout_session_created_at=team_billing.checkout_session_created_at,
            should_setup_billing=team_billing.should_setup_billing,
            billing_period_ends=team_billing.billing_period_ends,
            plan=team_billing.plan,
        )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0085_org_models'),
        ('multi_tenancy', '0004_auto_20200920_2021'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationBilling',
            fields=[
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='billing', serialize=False, to='posthog.Organization')),
                ('stripe_customer_id', models.CharField(blank=True, max_length=128)),
                ('stripe_checkout_session', models.CharField(blank=True, max_length=128)),
                ('checkout_session_created_at', models.DateTimeField(blank=True, null=True)),
                ('should_setup_billing', models.BooleanField(default=False)),
                ('billing_period_ends', models.DateTimeField(blank=True, null=True)),
                ('plan', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='multi_tenancy.Plan')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.RunPython(forwards_func, reverse_func),
    ]
