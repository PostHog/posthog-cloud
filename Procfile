release: cd deploy && python manage.py migrate && python manage.py migrate_clickhouse
web: bin/start-nginx bundle exec gunicorn posthog.wsgi --log-file -
worker: cd deploy && ./bin/docker-worker