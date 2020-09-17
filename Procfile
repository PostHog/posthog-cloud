release: cd deploy && python manage.py migrate && python manage.py migrate_clickhouse
web: cd deploy && gunicorn posthog.wsgi --log-file -
worker: cd deploy && ./bin/docker-worker