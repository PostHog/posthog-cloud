import json
import logging
from distutils.util import strtobool
from typing import Dict, Optional

import posthoganalytics
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from posthog.api.organization import OrganizationSignupViewset
from posthog.api.user import user
from posthog.urls import render_template
from rest_framework import mixins, status
from rest_framework.viewsets import GenericViewSet, ModelViewSet
from sentry_sdk import capture_exception, capture_message

import stripe
from multi_tenancy.tasks import (report_card_validated,
                                 update_subscription_billing_period)

from .models import OrganizationBilling, Plan
from .serializers import (BillingSubscribeSerializer,
                          MultiTenancyOrgSignupSerializer, PlanSerializer)
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

    if response.status_code == 200 and request.user.organization:
        instance, _ = OrganizationBilling.objects.get_or_create(organization=request.user.organization,)

        output = json.loads(response.content)

        output["billing"] = {
            "plan": None,
            "event_allocation": instance.event_allocation,
        }

        # Obtain event usage of current organization
        event_usage: Optional[int] = None
        try:
            # Function calls clickhouse so make sure Clickhouse failure doesn't block api/user from loading
            event_usage = get_cached_monthly_event_usage(request.user.organization)
        except Exception as e:
            capture_exception(e)

        output["billing"]["current_usage"] = event_usage

        if instance.plan:
            plan_serializer = PlanSerializer()
            output["billing"]["plan"] = plan_serializer.to_representation(instance=instance.plan,)

            if instance.should_setup_billing and not instance.is_billing_active:

                if (
                    instance.stripe_checkout_session
                    and instance.checkout_session_created_at
                    and instance.checkout_session_created_at + timezone.timedelta(minutes=1439) > timezone.now()
                ):
                    # Checkout session has been created and is still active (i.e. created less than 24 hours ago)
                    checkout_session = instance.stripe_checkout_session
                else:

                    try:
                        (checkout_session, customer_id,) = instance.create_checkout_session(
                            user=request.user, base_url=request.build_absolute_uri("/"),
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
        "stripe-checkout.html", request, {"STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY},
    )


def stripe_billing_portal(request: HttpRequest):
    url = ""

    if not request.user.is_authenticated:
        return HttpResponse("Unauthorized", status=status.HTTP_401_UNAUTHORIZED)

    instance, _ = OrganizationBilling.objects.get_or_create(organization=request.user.organization,)

    if instance.stripe_customer_id:
        url = customer_portal_url(instance.stripe_customer_id)

    # Report event manually because this page doesn't load any HTML (i.e. there's no autocapture available).
    posthoganalytics.capture(
        request.user.distinct_id, "visited billing customer portal", {"portal_available": bool(url)},
    )

    return redirect(url or "/")


def billing_welcome_view(request: HttpRequest):
    session_id = request.GET.get("session_id")
    extra_args: Dict = {}

    if session_id:
        try:
            organization_billing = OrganizationBilling.objects.get(stripe_checkout_session=session_id)
        except OrganizationBilling.DoesNotExist:
            pass
        else:
            serializer = PlanSerializer()
            extra_args["plan"] = serializer.to_representation(organization_billing.plan)
            extra_args["billing_period_ends"] = organization_billing.billing_period_ends

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
            subscription_id: str = event["data"]["object"]["subscription"]

            if instance.stripe_subscription_id:
                if instance.stripe_subscription_id != subscription_id:
                    capture_message(
                        "Stripe webhook does not match subscription on file "
                        f"({instance.stripe_subscription_id}): {json.dumps(event)}",
                        "error",
                    )
                    return error_response
            else:
                # First time receiving the subscription_id, record it
                instance.stripe_subscription_id = subscription_id

            instance.should_setup_billing = False
            instance.save()

            update_subscription_billing_period.delay(organization_id=instance.organization.id)

        # Special handling for plans that only do card validation (e.g. startup or metered-billing plans)
        elif event["type"] == "payment_intent.amount_capturable_updated":
            instance = instance.handle_post_card_validation()

            # Attempt to cancel the validation charge
            try:
                cancel_payment_intent(event["data"]["object"]["id"])
            except stripe.error.StripeError as e:
                capture_exception(e)

            report_card_validated(organization_id=instance.organization.id)

    except KeyError:
        # Malformed request
        return error_response

    return response


@csrf_exempt
def plan_template(request: HttpRequest, key: str) -> HttpResponse:
    plan: Optional[Plan] = None
    try:
        plan = Plan.objects.get(key=key, is_active=True)
    except Plan.DoesNotExist:
        pass

    if not plan:
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)

    try:
        template = get_template(f"plans/{key}.html")
    except TemplateDoesNotExist:
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)

    html = template.render(request=request)
    return HttpResponse(html)
