# Rotta 116 — Production Operations Runbook

This runbook records the definitive production operating procedure. Do not store secrets, certificates, database dumps, or customer passwords in this repository.

## Environment

- Application path: `/opt/rotta116/current`
- Service user: `rotta116`
- Virtualenv: `/opt/rotta116/venv`
- Environment file: `/etc/rotta116/rotta116.env` with mode `0600` and owner `root:rotta116`
- Django settings: `config.settings.production`
- Static root: `/opt/rotta116/shared/staticfiles`
- Media root: `/opt/rotta116/shared/media`
- Private documents root: `/opt/rotta116/shared/private_documents`
- Backup root: `/var/backups/rotta116` with restricted permissions

## Deploy

```bash
sudo -u rotta116 git -C /opt/rotta116/current fetch origin
sudo -u rotta116 git -C /opt/rotta116/current checkout main
sudo -u rotta116 git -C /opt/rotta116/current pull --ff-only origin main
sudo -u rotta116 /opt/rotta116/venv/bin/pip install -e /opt/rotta116/current
sudo -u rotta116 DJANGO_SETTINGS_MODULE=config.settings.production /opt/rotta116/venv/bin/python /opt/rotta116/current/manage.py check --settings=config.settings.production
sudo -u rotta116 DJANGO_SETTINGS_MODULE=config.settings.production /opt/rotta116/venv/bin/python /opt/rotta116/current/manage.py migrate --settings=config.settings.production
sudo -u rotta116 DJANGO_SETTINGS_MODULE=config.settings.production /opt/rotta116/venv/bin/python /opt/rotta116/current/manage.py collectstatic --noinput --settings=config.settings.production
sudo systemctl restart rotta116
```

## Status, Restart, Logs

```bash
sudo systemctl status rotta116
sudo systemctl restart rotta116
sudo journalctl -u rotta116 -f
sudo journalctl -u rotta116 --since "1 hour ago"
```

## Migrations And Static

```bash
sudo -u rotta116 DJANGO_SETTINGS_MODULE=config.settings.production /opt/rotta116/venv/bin/python /opt/rotta116/current/manage.py migrate --settings=config.settings.production
sudo -u rotta116 DJANGO_SETTINGS_MODULE=config.settings.production /opt/rotta116/venv/bin/python /opt/rotta116/current/manage.py collectstatic --noinput --settings=config.settings.production
```

## Backup

Create `/usr/local/sbin/rotta116-pg-backup` on the server with a protected environment that provides `DATABASE_URL` or pg connection variables.

```bash
set -euo pipefail
install -d -m 0700 /var/backups/rotta116/postgres
pg_dump --format=custom --no-owner --no-privileges --file "/var/backups/rotta116/postgres/rotta116-$(date +%Y%m%d-%H%M%S).dump" "$DATABASE_URL"
find /var/backups/rotta116/postgres -type f -name "*.dump" -mtime +14 -delete
```

Recommended timer: daily, with 14-day local retention plus provider snapshots. Provider snapshots do not replace PostgreSQL logical backups.

## Restore

Restore only into a confirmed target database. Never overwrite production without an explicit maintenance decision.

```bash
createdb rotta116_restore
pg_restore --clean --if-exists --no-owner --dbname rotta116_restore /var/backups/rotta116/postgres/BACKUP_FILE.dump
```

## Rollback

```bash
sudo -u rotta116 git -C /opt/rotta116/current log --oneline -5
sudo -u rotta116 git -C /opt/rotta116/current checkout COMMIT_SHA
sudo systemctl restart rotta116
```

Only roll back code after checking whether migrations introduced non-reversible schema/data changes.
