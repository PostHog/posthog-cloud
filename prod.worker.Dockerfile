FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

# install basic dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

# fetch main posthog from Github
RUN curl -L https://github.com/posthog/posthog/tarball/master | tar --strip-components=1 -xz -C . --

# add local dependencies
COPY requirements.txt /code/cloud_requirements.txt
RUN cat cloud_requirements.txt >> requirements.txt

# install dependencies but ignore any we don't need for dev environment
RUN pip install -r requirements.txt

RUN mkdir /code/frontend/dist

# copy this repo's files
COPY ./multi_tenancy /code/multi_tenancy/
COPY ./messaging /code/messaging/

COPY multi_tenancy_settings.py /code/cloud_settings.py
RUN cat /code/cloud_settings.py >> /code/posthog/settings.py

EXPOSE 8000
EXPOSE 8234
CMD ["./bin/docker-worker"]