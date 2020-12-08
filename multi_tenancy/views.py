import datetime
import json
import logging
from distutils.util import strtobool
from typing import Dict, Optional

import pytz
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from posthog.api.organization import OrganizationSignupViewset
from posthog.api.user import user
from posthog.templatetags.posthog_filters import compact_number
from posthog.urls import render_template
from rest_framework import mixins, status
from rest_framework.viewsets import GenericViewSet, ModelViewSet
from sentry_sdk import capture_exception, capture_message

import stripe

from .models import OrganizationBilling, Plan
from .serializers import (
    BillingSubscribeSerializer,
    MultiTenancyOrgSignupSerializer,
    PlanSerializer,
)
from .stripe import cancel_payment_intent, customer_portal_url, parse_webhook
from .utils import get_cached_monthly_event_usage

logger = logging.getLogger(__name__)


class MultiTenancyOrgSignupViewset(OrganizationSignupViewset):
    serializer_class = MultiTenancyOrgSignupSerializer


class PlanViewset(ModelViewSet):
    serializer_class = PlanSerializer
    lookup_field = "key"

    def get_queryset(self):
        queryset = Plan.objects.filter(is_active=True)

        self_serve: Optional[str] = self.request.query_params.get("self_serve", None)
        if self_serve is not None:
            queryset = queryset.filter(self_serve=bool(strtobool(self_serve)))

        return queryset


class BillingSubscribeViewset(mixins.CreateModelMixin, GenericViewSet):
    serializer_class = BillingSubscribeSerializer


def user_with_billing(request: HttpRequest):
    """
    Overrides the posthog.api.user.user response to include
    appropriate billing information in the request
    """

    response = user(request)

    if response.status_code == 200:
        instance, _created = OrganizationBilling.objects.get_or_create(
            organization=request.user.organization,
        )

        output = json.loads(response.content)
        output["billing"] = {
            "plan": None,
        }

        # Obtain event usage of current organization
        event_usage: Optional[int] = None
        try:
            # Function calls clickhouse so make sure Clickhouse failure doesn't block api/user from loading
            event_usage = get_cached_monthly_event_usage(request.user.organization)
        except Exception as e:
            capture_exception(e)

        if event_usage is not None:
            output["billing"]["current_usage"] = {
                "value": event_usage,
                "formatted": compact_number(event_usage),
            }

        if instance.plan:
            plan_serializer = PlanSerializer()
            output["billing"]["plan"] = plan_serializer.to_representation(
                instance=instance.plan,
            )

            if instance.should_setup_billing and not instance.is_billing_active:

                if (
                    instance.stripe_checkout_session
                    and instance.checkout_session_created_at
                    and instance.checkout_session_created_at
                    + timezone.timedelta(minutes=1439)
                    > timezone.now()
                ):
                    # Checkout session has been created and is still active (i.e. created less than 24 hours ago)
                    checkout_session = instance.stripe_checkout_session
                else:

                    try:
                        (
                            checkout_session,
                            customer_id,
                        ) = instance.plan.create_checkout_session(
                            user=request.user,
                            team_billing=instance,
                            base_url=request.build_absolute_uri("/"),
                        )
                    except ImproperlyConfigured as e:
                        capture_exception(e)
                        checkout_session = None
                    else:
                        if checkout_session:
                            OrganizationBilling.objects.filter(pk=instance.pk).update(
                                stripe_checkout_session=checkout_session,
                                stripe_customer_id=customer_id,
                                checkout_session_created_at=timezone.now(),
                            )

                if checkout_session:
                    output["billing"] = {
                        **output["billing"],
                        "should_setup_billing": True,
                        "stripe_checkout_session": checkout_session,
                        "subscription_url": f"/billing/setup?session_id={checkout_session}",
                    }

        response = JsonResponse(output)

    return response


def stripe_checkout_view(request: HttpRequest):
    return render_template(
        "stripe-checkout.html",
        request,
        {"STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY},
    )


def stripe_billing_portal(request: HttpRequest):

    if not request.user.is_authenticated:
        return HttpResponse("Unauthorized", status=status.HTTP_401_UNAUTHORIZED)

    instance, created = OrganizationBilling.objects.get_or_create(
        organization=request.user.organization,
    )

    if instance.stripe_customer_id:
        url = customer_portal_url(instance.stripe_customer_id)
        if url:
            return redirect(url)

    return redirect("/")


def billing_welcome_view(request: HttpRequest):
    session_id = request.GET.get("session_id")
    extra_args: Dict = {}

    if session_id:
        try:
            team_billing = OrganizationBilling.objects.get(
                stripe_checkout_session=session_id,
            )
        except OrganizationBilling.DoesNotExist:
            pass
        else:
            serializer = PlanSerializer()
            extra_args["plan"] = serializer.to_representation(team_billing.plan)
            extra_args["billing_period_ends"] = team_billing.billing_period_ends

    return render_template("billing-welcome.html", request, extra_args)


def billing_failed_view(request: HttpRequest):
    return render_template("billing-failed.html", request)


def billing_hosted_view(request: HttpRequest):
    return render_template("billing-hosted.html", request)


@csrf_exempt
def stripe_webhook(request: HttpRequest) -> JsonResponse:
    response: JsonResponse = JsonResponse({"success": True}, status=status.HTTP_200_OK)
    error_response: JsonResponse = JsonResponse(
        {"success": False}, status=status.HTTP_400_BAD_REQUEST,
    )
    signature: str = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event: Dict = parse_webhook(request.read(), signature)
    except Exception as e:
        capture_exception(e)
        return error_response

    try:
        customer_id = event["data"]["object"]["customer"]

        try:
            instance = OrganizationBilling.objects.get(stripe_customer_id=customer_id)
        except OrganizationBilling.DoesNotExist:
            capture_message(
                f"Received invoice.payment_succeeded for {customer_id} but customer is not in the database.",
            )
            return response

        if event["type"] == "invoice.payment_succeeded":
            # We have to use the period from the invoice line items because on the first month
            # Stripe sets period_end = period_start because they manage these attributes on an accrual-basis
            line_items = event["data"]["object"]["lines"]["data"]
            if len(line_items) > 1:
                capture_message(
                    f"Stripe's invoice.payment_succeeded webhook contained more than 1 line item ({event}), "
                    "using the first one.",
                )

            # TODO: Validate plan in case it has changed outside the scope of posthog-production
            instance.billing_period_ends = datetime.datetime.utcfromtimestamp(
                line_items[0]["period"]["end"],
            ).replace(tzinfo=pytz.utc)
            instance.should_setup_billing = False

            instance.save()

        # Special handling for plans that only do card validation (e.g. startup);
        # default behavior is setting the plan for 1 year from registration.
        elif event["type"] == "payment_intent.amount_capturable_updated":
            instance.billing_period_ends = timezone.now() + datetime.timedelta(days=365)
            instance.should_setup_billing = False
            instance.save()

            # Attempt to cancel the validation charge
            try:
                cancel_payment_intent(event["data"]["object"]["id"])
            except stripe.error.StripeError as e:
                capture_exception(e)

    except KeyError:
        # Malformed request
        return error_response

    return response
