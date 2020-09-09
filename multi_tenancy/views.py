import datetime
import json
import logging
from typing import Dict

import pytz
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from rest_framework import status

from multi_tenancy.models import TeamBilling
from multi_tenancy.stripe import create_subscription, customer_portal_url, parse_webhook
from posthog.api.team import TeamSignupViewset
from posthog.api.user import user
from posthog.urls import render_template

from .serializers import MultiTenancyTeamSignupSerializer

logger = logging.getLogger(__name__)


class MultiTenancyTeamSignupViewset(TeamSignupViewset):
    serializer_class = MultiTenancyTeamSignupSerializer


def user_with_billing(request: HttpRequest):
    """
    Overrides the posthog.api.user.user response to include
    appropriate billing information in the request
    """

    response = user(request)

    if response.status_code == 200:
        # TO-DO (Future): Handle user having multiple teams
        instance, created = TeamBilling.objects.get_or_create(
            team=request.user.team_set.first(),
        )

        if instance.should_setup_billing and not instance.is_billing_active:

            checkout_session, customer_id = create_subscription(
                request.user.email, instance.stripe_customer_id, instance.price_id,
            )

            if checkout_session:
                output = json.loads(response.content)

                TeamBilling.objects.filter(pk=instance.pk).update(
                    stripe_checkout_session=checkout_session,
                    stripe_customer_id=customer_id,
                )
                output["billing"] = {
                    "should_setup_billing": instance.should_setup_billing,
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

    instance, created = TeamBilling.objects.get_or_create(
        team=request.user.team_set.first()
    )

    if instance.stripe_customer_id:
        url = customer_portal_url(instance.stripe_customer_id)
        if url:
            return redirect(url)

    return redirect("/")


def billing_welcome_view(request: HttpRequest):
    return render_template("billing-welcome.html", request)


def billing_failed_view(request: HttpRequest):
    return render_template("billing-failed.html", request)


def billing_hosted_view(request: HttpRequest):
    return render_template("billing-hosted.html", request)


def stripe_webhook(request: HttpRequest) -> JsonResponse:
    response: JsonResponse = JsonResponse({"success": True}, status=status.HTTP_200_OK)
    error_response: JsonResponse = JsonResponse(
        {"success": False}, status=status.HTTP_400_BAD_REQUEST
    )
    signature: str = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    event: Dict = parse_webhook(request.read(), signature)

    if event:
        # Event is correctly formed and signature is valid

        try:

            if event["type"] == "invoice.payment_succeeded":
                customer_id = event["data"]["object"]["customer"]

                try:
                    instance = TeamBilling.objects.get(stripe_customer_id=customer_id)
                except TeamBilling.DoesNotExist:
                    logger.warning(
                        f"Received invoice.payment_succeeded for {customer_id} but customer is not in the database."
                    )
                    return response

                # We have to use the period from the invoice line items because on the first month
                # Stripe sets period_end = period_start because they manage these attributes on an accrual-basis
                line_items = event["data"]["object"]["lines"]["data"]
                if len(line_items) > 1:
                    logger.warning(
                        f"Stripe's invoice.payment_succeeded webhook contained more than 1 line item ({event}), using the first one."
                    )

                instance.billing_period_ends = datetime.datetime.utcfromtimestamp(
                    line_items[0]["period"]["end"],
                ).replace(tzinfo=pytz.utc)

                instance.save()

        except KeyError:
            # Malformed request
            return error_response

    else:
        return error_response

    return response
