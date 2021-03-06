FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

# Grab posthog from local (You must have posthog cloned here)
COPY ./deploy .

# install javascript dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git build-essential \
    && curl -sL https://deb.nodesource.com/setup_14.x  | bash - \
    && apt-get install nodejs -y --no-install-recommends \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile \
    && yarn build \
    && cd plugins \
    && yarn --frozen-lockfile --ignore-optional \
    && cd .. \
    && yarn cache clean \
    && apt-get purge -y curl build-essential \
    && rm -rf node_modules \
    && rm -rf /var/lib/apt/lists/*

# Block for posthog cloud additions 
COPY requirements.txt /code/cloud_requirements.txt
RUN cat cloud_requirements.txt >> requirements.txt
COPY ./multi_tenancy /code/multi_tenancy/
COPY ./messaging /code/messaging/
COPY multi_tenancy_settings.py /code/cloud_settings.py
RUN cat /code/cloud_settings.py >> /code/posthog/settings.py

# Set up NewRelic
COPY ./bin/docker-server-newrelic /code/bin/.
COPY ./newrelic.ini /code/.
# NewRelic for worker (replace in line)
RUN sed -i.bak "s/celery -A posthog worker \${FLAGS\[\*]}/NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program celery -A posthog worker \${FLAGS\[\*]}/g" /code/bin/docker-worker-celery && rm /code/bin/docker-worker-celery.bak
RUN sed -i.bak "s/celery -A posthog beat -S redbeat.RedBeatScheduler/NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program celery -A posthog beat -S redbeat.RedBeatScheduler/g" /code/bin/docker-worker-beat && rm /code/bin/docker-worker-beat.bak

# install dependencies but ignore any we don't need for dev environment
RUN pip install $(grep -ivE "psycopg2" requirements.txt | cut -d'#' -f1) --no-cache-dir --compile\
    && pip install psycopg2-binary --no-cache-dir --compile\
    && pip uninstall ipython-genutils pip -y

RUN DATABASE_URL='postgres:///' REDIS_URL='redis:///' SECRET_KEY='no' python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["./gunicorn posthog.wsgi --log-file -"]