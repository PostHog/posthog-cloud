# PostHog Cloud

This repository is used to run PostHog Cloud (app.posthog.com). It enables anyone to sign up to an account and create their own account along with an organization.

NOTE: This repository **is copyrighted** (unlike our [main repo](https://github.com/posthog/posthog)). Any reproductions, partial or total, including but not limiting to launching a similar service is forbidden.

## Structure

The main repo is pulled using the script into the `/deploy` folder. Tthe contents of `multi_tenancy` & `messaging` are then symlinked (or copied if on production) into `/deploy`. We also use `multi_tenancy_settings.py` & `requirements.txt`, which introduce a few changes to the main version.

## Developing locally

> Please note running locally now **requires Clickhouse. Tests will NOT PASS if Clickhouse is not available.**

Below you'll find the recommended steps to run locally. While running directly on Docker is possible (see [developing locally](https://posthog.com/docs/developing-locally) for the main repo), this would require more setup.

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
