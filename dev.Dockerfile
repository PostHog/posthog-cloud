FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
WORKDIR /code

COPY . /multi_tenancy

RUN apt-get update && apt-get install -y --no-install-recommends curl
RUN curl -L https://github.com/posthog/posthog/tarball/master | tar --strip-components=1 -xz -C . --
RUN ln -s /multi_tenancy/multi_tenancy /code/ \
    && cat /multi_tenancy/multi_tenancy_settings.py >> /code/posthog/settings.py \
    && cat /multi_tenancy/requirements.txt >> /code/requirements.txt \
    && pip3 install setuptools wheel \
    && python -m easy_install pip \
    && python -m pip install -r requirements.txt

RUN curl -sL https://deb.nodesource.com/setup_12.x  | bash - \
    && apt-get install nodejs -y --no-install-recommends \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

EXPOSE 8000
EXPOSE 8234
RUN yarn install
RUN yarn build

CMD ["/code/bin/docker-dev"]