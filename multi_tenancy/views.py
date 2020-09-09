from typing import Dict
from posthog.urls import render_template
from django.http import JsonResponse, HttpResponse, HttpRequest
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect
from rest_framework import status
from rest_framework import exceptions
from posthog.models import User, Team, Organization
from posthog.api.user import user
from multi_tenancy.models import OrganizationBilling
from multi_tenancy.stripe import create_subscription, customer_portal_url, parse_webhook
from messaging.tasks import process_team_signup_messaging
import json
import logging
import datetime
import pytz
import posthoganalytics

logger = logging.getLogger(__name__)


def signup_view(request: HttpRequest):
    if request.method == "GET":
        if request.user.is_authenticated:
            return redirect("/")
        return render_template("signup.html", request)
    if request.method == "POST":
        email = request.POST["email"]
        password = request.POST["password"]
        company_name = request.POST.get("company_name")
        try:
            user = User.objects.create_user(
                email=email, password=password, first_name=request.POST.get("name")
            )
        except:
            return render_template(
                "signup.html",
                request=request,
                context={
                    "error": True,
                    "email": request.POST["email"],
                    "company_name": request.POST.get("company_name"),
                    "name": request.POST.get("name"),
                },
            )

        organization = Organization.objects.create(name=company_name)
        organization.members.add(user)
        team = Team.objects.create_with_data(organization=organization)
        user.current_organization = organization
        user.current_team = team
        user.save()

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        posthoganalytics.capture(
            user.distinct_id,
            "user signed up",
            properties={"is_first_user": False, "is_team_first_user": True},
        )
        posthoganalytics.identify(
            user.distinct_id,
            properties={
                "email": user.email,
                "company_name": company_name,
                "name": user.first_name,
            },
        )
        process_team_signup_messaging.delay(user_id=user.pk, team_id=team.pk)
        return redirect("/")


def user_with_billing(request: HttpRequest):
    """
    Overrides the posthog.api.user.user response to include
    appropriate billing information in the request
    """

    response = user(request)

    if response.status_code == 200:
        # TODO: Handle multiple organizations
        instance, created = OrganizationBilling.objects.get_or_create(
            organization=request.user.organization
        )

        if instance.should_setup_billing and not instance.is_billing_active:

            checkout_session, customer_id = create_subscription(
                request.user.email, instance.stripe_customer_id, instance.price_id,
            )

            if checkout_session:
                output = json.loads(response.content)

                OrganizationBilling.objects.filter(pk=instance.pk).update(
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

    instance, created = OrganizationBilling.objects.get_or_create(
        organization=request.user.organization
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
                    instance = OrganizationBilling.objects.get(stripe_customer_id=customer_id)
                except OrganizationBilling.DoesNotExist:
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
                    line_items[0]["period"]["end"]
                ).replace(tzinfo=pytz.utc)

                # Update the price_id too.
                instance.price_id = line_items[0]["price"]["id"]

                instance.save()

        except KeyError:
            # Malformed request
            return error_response

    else:
        return error_response

    return response
