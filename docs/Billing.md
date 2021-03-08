# Billing Tech Details

This document contains the technical details for the cloud billing engine.


## General Functionality
- The billing engine supports two categories of billing plans.
  - Flat-pricing. These are plans that have a monthly flat fee (regardless of usage), and which may have a limited event allocation per month. After the allocation is exceeded, the users in the organization will see a warning in every page of the app prompting them for an update. **N.B. flat-priced plans are pre-paid every month.**
  - Usage-based pricing (also refered to as metered billing). These are plans that are priced based on the number of events ingested every month. These plans may or may not have a flat fee, may have multiple unit prices depending on tiers of usage, or may even offer volume discount (i.e. unit price is reduced for all events after certain usage threshold), all of this is configured directly on Stripe. **N.B. metered plans are post-paid every month.**
- Billing is organization-based and almost all the billing logic is handled on Stripe.
- We rely on webhooks to receive information from Stripe when stuff happens on their end (see `multi_tenancy/views.py#stripe_webhook`), so we can take action accordingly. One important thing to note is that Stripe also handles billing for VPC / enterprise customers, which is outside the scope of this repo, because Stripe doesn't distinguish between those customers, we will receive webhooks in this system that are not relevant; these just trigger an information message on Sentry. The events we listen to:
  - `invoice.payment_succeeded`. We use this event to update the `billing_period_ends` record (for metered plans, this means that the plan is covered until the next billing period, as these plans are post-paid).
  - `payment_intent.amount_capturable_updated`. We use this event to a) know when a card has been validated for a customer, b) cancel a pre-authorization charge, c) start metered subscriptions.
- The Environment Variables section of the README contains more details on how to set up some configuration details for the billing engine, however in terms of functionality, here is some additional points worth mentioning:
  - We support adding a free trial to all plans (through Stripe), which can be set up through an environment variable. Please note that we can only apply a free trial to all plans and all new customers. To apply trial periods to individual customers, please use the Stripe dashboard.
  - We have a default "no billing plan" state which is active until a customer signs up and starts in a particular plan. The only particularity of being in this state, is that we have a maximum monthly event allocation that can be used. This value is configurable via an env variable too.
- While today almost all paid plans have all the same premium features, we do have support for dynamically changing the premium features that each plan can provide. Premium features are configured on the `Plan` model and rely on the `plan_key`. The actual logic for the premium feature lives within each feature in the main repo.


## Workflow
- The billing plan is initially configured on the `OrganizationBilling` object where the plan is set (the handbook details all the ways in which a plan can be assigned for an organization).
- After the billing plan is set, we create a Stripe Checkout session where a user in the org can securely set up their billing details. We use this mechanism because it allows us to rely on Stripe's well tested page which is UX-optimized and handles common cases such as 3D secure (or 3DS 2.0), payment failures, fraud prevention, etc. Because sensitive card details are only ever handled on Stripe, our PCI compliance overhead is quite limited.
  - For flat fee plans, the checkout session automatically starts the recurring subscription.
  - Metered and startup plan subscriptions on the other hand, only use the Checkout session to capture the billing details on do a pre-authorization charge (also called zero-auth). This is an actual charge of $0.50 USD, with the key distinction that the charge is only authorized and not captured (non-captured charges are never posted to the user's account, i.e. they disappear; the actual behavior from a user's standpoint varies based on their financial institution, but basically this means the funds get a hold, but are never actually taken from the user's account). When we get confirmation that the authorization charge has gone through, we send a signal to Stripe to cancel the charge (should this signal fail, uncaptured charges are automatically cancelled after 7 days anyways).
- For usage-based plans, we start a post-paid subscription just after this pre-authorization charge. All usage-based subscriptions are anchored to calendar months, which means that the customer will get their first invoice around the 2nd of the next month.

## Models

The billing engine is comprised mainly of two models, `Plan` & `OrganizationBilling`. The first one contains general information on the plans (e.g. pricing, terms, etc.) and the second one contains information pertaining to a specific organization. Each attribute is documented in the `multi_tenancy/models.py` file.
