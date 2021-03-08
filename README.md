# PostHog Cloud

This repository is used to run PostHog Cloud (app.posthog.com). It enables anyone to sign up to an account and create their own account along with an organization.

NOTE: This repository **is copyrighted** (unlike our [main repo](https://github.com/posthog/posthog)). You are not allowed to use this code to host your own version of app.posthog.com

## Current Infrastructure

![Infra Diagram](docs/images/infra.png?raw=true)

## Structure

The main repo is pulled using the script into the `/deploy` folder. The contents of `multi_tenancy` & `messaging` are then added into `/deploy` (if on development, folders are symlinked instead of copied so changes are updated automatically in both locations). We also use `multi_tenancy_settings.py` & `requirements.txt` to introduce a few changes to the base code.

## Developing locally

> Please note running locally now **requires Clickhouse. Tests will NOT PASS if Clickhouse is not available.**

Below you'll find the recommended steps to run locally. While running everything on Docker is possible (see [developing locally](https://posthog.com/docs/developing-locally) for the main repo), this would require more setup.

1. Set up a virtual environment (sample code below).
   ```bash
   python3 -m venv env
   ```
1. Run `bin/develop`. If you need to develop relative to a main repo branch other than `master`, pass branch name as command line argument, like so:
   ```
   bin/develop some-branch
   ```
1. Load the sample environment variables by running,
   ```bash
   source .env.template
   ```
1. Run Clickhouse (and dependencies) using Docker,
   ```bash
   docker-compose -f deploy/ee/docker-compose.ch.yml up clickhouse kafka zookeeper
   ```
1. You can run the server by running,
   ```bash
   cd deploy && bin/start
   ```
1. **Alternatively**, you can just run the local tests by doing
   ```bash
   python manage.py test multi_tenancy messaging --exclude-tag=skip_on_multitenancy
   ```

Origin repo test suite can be run doing

```bash
python manage.py test posthog --exclude-tag=skip_on_multitenancy
```

Any file on the `multi_tenancy/` or `messaging/` folder will automatically be updated on your working copy at `/deploy`. Please note however that any change to `requirements.txt` or `multi_tenancy_settings.py` **requires manually running `bin/develop` again**.

## Environment variables

Below is the documentation for the environment variables specifically scoped to this project. For the environment variables applicable to the main repo please visit the [docs](https://posthog.com/docs/configuring-posthog/environment-variables).

- `STRIPE_API_KEY`. Secret API key for Stripe. For security reasons only restricted keys should be used.
- `STRIPE_PUBLISHABLE_KEY`. Publishable API key for Stripe to generate checkout sessions.
- `STRIPE_WEBHOOK_SECRET`. Secret to verify webhooks indeed come from Stripe.
- `BILLING_TRIAL_DAYS`. Number of days (integer) to set up a trial for on each new metered or tiered-based subscription. Can be set to `0` for no trial.
- `BILLING_NO_PLAN_EVENT_ALLOCATION`. Number of events allocated to an organization with no active billing plan (i.e. number of events for free). `None` means unlimited free allocation, `0` means no allocation.


## Additional docs
Some features particular to this repo are documented below.
- [Billing](docs/Billing.md)

## Questions?

Join us on [Slack][slack].

[slack]: https://posthog.com/slack?utm_medium=readme&utm_campaign=posthog-production&utm_source=github.com
