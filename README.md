# PostHog Cloud

This repository is used to run PostHog Cloud (app.posthog.com). It enables anyone to sign up to an account and create their own account along with an organization.

NOTE: This repository is copyrighted, unlike our [main repo](https://github.com/posthog/posthog). You're not allowed to use this code to host your own version of app.posthog.com.

## Structure

We pull in our main repo using the script into the `/deploy` folder. We then copy in the contents of `multi_tenancy` into `/deploy`. We also use `settings.py`, which has a few changes to the open source, mainly adding this new `multi_tenancy` app.

## Developing locally

> To develop locally with Docker follow the instructions at `https://posthog.com/docs/developing-locally`. Do not forget to load the relevant environment variables and run `bin/develop`. If you need to develop relative to a main repo branch other than `master`, pass branch name as command line argument, like so: `bin/develop some-branch`.

1. Set up a virtual environment (sample code below).
    ```bash
    python3 -m venv env
    ```
1. Run `bin/develop`.
1. Load the sample environment variables on `.env.template`.
1. cd into `deploy/` and run `bin/start` (this will pre-compile the front-end too).
1. Tests can be run using `DEBUG=1 bin/tests`.

You may now edit `/settings.py` or any files in `multi_tenancy`. They're automatically linked to the `/deploy` folder.
