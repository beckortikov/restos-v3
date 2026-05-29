# 90 — Развёртывание в LAN ресторана

Все три приложения ставятся на **одну main POS-машину**. Планшеты официантов получают PWA с этой же машины через nginx.

## Целевая платформа

| ОС | Поддерживаем | Как |
|---|---|---|
| Ubuntu / Debian LTS | первый класс | systemd, apt-пакеты |
| Windows 10/11 Pro | первый класс | NSSM-сервисы, PostgreSQL installer |
| macOS | dev only | brew, launchd (необязательно) |

В обоих случаях нужно: PostgreSQL 16, Python 3.12, Node 22 (один раз для билда waiter), nginx.

---

## Linux: установка с нуля

```bash
#!/usr/bin/env bash
# deploy/install-linux.sh
set -euo pipefail

# 1. PostgreSQL
sudo apt update
sudo apt install -y postgresql-16 nginx python3.12 python3.12-venv \
                    nodejs npm libusb-1.0-0 libcups2-dev
sudo systemctl enable --now postgresql

sudo -u postgres psql -c "CREATE USER restos WITH PASSWORD 'CHANGE_ME';"
sudo -u postgres psql -c "CREATE DATABASE restos OWNER restos;"

# 2. Backend
sudo mkdir -p /opt/restos
sudo chown $USER:$USER /opt/restos
git clone https://example.com/restos-backend.git /opt/restos/backend
cd /opt/restos/backend

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cat > .env <<EOF
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
DATABASE_URL=postgres://restos:CHANGE_ME@127.0.0.1:5432/restos
ALLOWED_HOSTS=*
PRINTER_VIRTUAL=false
MVP_RESTAURANT_ID=1
EOF

python manage.py migrate
python manage.py loaddata fixtures/initial_restaurant.json
python manage.py createsuperuser

# 3. systemd-юниты
sudo cp deploy/systemd/restos-backend.service       /etc/systemd/system/
sudo cp deploy/systemd/restos-print-worker.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now restos-backend restos-print-worker

# 4. nginx
sudo cp deploy/nginx/restos.conf  /etc/nginx/sites-available/restos
sudo ln -sf /etc/nginx/sites-available/restos /etc/nginx/sites-enabled/restos
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# 5. Waiter PWA static
git clone https://example.com/restos-waiter.git /opt/restos/waiter
cd /opt/restos/waiter
npm install -g pnpm
pnpm install
pnpm build
sudo mkdir -p /var/www/restos-waiter
sudo rsync -a --delete dist/ /var/www/restos-waiter/

# 6. Cashier (PySide)
git clone https://example.com/restos-cashier.git /opt/restos/cashier
cd /opt/restos/cashier
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# desktop entry
sudo cp deploy/restos-cashier.desktop /usr/share/applications/

# 7. Бэкап
sudo cp deploy/cron/restos-backup /etc/cron.daily/restos-backup
sudo chmod +x /etc/cron.daily/restos-backup

echo "Done. Backend at http://$(hostname -I | awk '{print $1}')/"
```

### `deploy/systemd/restos-backend.service`

```ini
[Unit]
Description=RestOS Django backend
After=network.target postgresql.service

[Service]
Type=simple
User=restos
WorkingDirectory=/opt/restos/backend
EnvironmentFile=/opt/restos/backend/.env
ExecStart=/opt/restos/backend/.venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --worker-class gthread --workers 3 --threads 16 \
    --timeout 0 --keepalive 75
Restart=on-failure
# `gthread` + `--timeout 0` обязательны для долгоживущих SSE-стримов /events/.
# 3 × 16 = 48 одновременных SSE-коннектов — с запасом для LAN ресторана.

[Install]
WantedBy=multi-user.target
```

### `deploy/systemd/restos-print-worker.service`

```ini
[Unit]
Description=RestOS print worker
After=restos-backend.service

[Service]
Type=simple
User=restos
WorkingDirectory=/opt/restos/backend
EnvironmentFile=/opt/restos/backend/.env
ExecStart=/opt/restos/backend/.venv/bin/python manage.py print_worker
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Воркер запускается отдельным процессом, чтобы перезагрузка gunicorn не теряла активные jobs.

### `deploy/nginx/restos.conf`

```nginx
upstream restos_backend {
    server 127.0.0.1:8000 fail_timeout=2s;
}

server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 5M;

    # Waiter PWA
    root /var/www/restos-waiter;
    index index.html;
    location / {
        try_files $uri /index.html;
        add_header Cache-Control "no-cache";
    }

    # Backend API + admin
    location /api/ {
        proxy_pass http://restos_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 30s;
    }

    # SSE — отдельный location, без буферизации, с долгим timeout
    location /api/v1/events/ {
        proxy_pass http://restos_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
        proxy_send_timeout 24h;
        chunked_transfer_encoding on;
        add_header X-Accel-Buffering no;
    }
    location /admin/ {
        # Only from localhost
        allow 127.0.0.1;
        deny all;
        proxy_pass http://restos_backend;
        proxy_set_header Host $host;
    }
    location /static/ {
        alias /opt/restos/backend/staticfiles/;
        expires 30d;
    }
    location /media/ {
        alias /opt/restos/backend/media/;
        expires 7d;
    }
}
```

### `deploy/cron/restos-backup`

```bash
#!/usr/bin/env bash
set -euo pipefail
DEST=/var/backups/restos
mkdir -p "$DEST"
DATE=$(date +%F)
PGPASSWORD=CHANGE_ME pg_dump -h 127.0.0.1 -U restos -Fc restos \
  | gzip > "$DEST/$DATE.dump.gz"
find "$DEST" -name "*.dump.gz" -mtime +30 -delete
```

Запускается ежедневно в 03:00 (cron.daily).

---

## Windows: установка с нуля

1. Установить **PostgreSQL 16** (официальный installer). Создать БД `restos` и пользователя `restos`.
2. Установить **Python 3.12** (галочка «Add to PATH»).
3. Установить **Node 22** + `pnpm` (`npm install -g pnpm`).
4. Установить **NSSM** (`choco install nssm`).
5. `git clone` всех трёх репо в `C:\restos\backend`, `C:\restos\waiter`, `C:\restos\cashier`.
6. Backend: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, `manage.py migrate`, `loaddata`, `createsuperuser`.
7. Зарегистрировать сервисы:
   ```powershell
   # waitress поддерживает long requests из коробки. SSE на нём работает,
   # но для нагрузки выше 10 одновременных стримов лучше gthread под gunicorn —
   # тогда нужен WSL или переход на Linux.
   nssm install restos-backend "C:\restos\backend\.venv\Scripts\waitress-serve.exe" `
     "--listen=127.0.0.1:8000 --threads=32 config.wsgi:application"
   nssm set restos-backend AppDirectory C:\restos\backend
   nssm set restos-backend AppEnvironmentExtra DJANGO_SETTINGS_MODULE=config.settings.prod
   nssm start restos-backend

   nssm install restos-print-worker "C:\restos\backend\.venv\Scripts\python.exe" `
     "manage.py print_worker"
   nssm set restos-print-worker AppDirectory C:\restos\backend
   nssm start restos-print-worker
   ```
8. nginx for Windows: distribut в `C:\nginx`, конфиг тот же. Поставить как сервис через NSSM.
9. PWA: `pnpm install && pnpm build`, скопировать `dist\*` в `C:\nginx\html\restos-waiter\`.
10. Cashier: запускать `C:\restos\cashier\.venv\Scripts\python.exe -m pos.main` через ярлык в Автозагрузке.
11. Бэкапы — Scheduled Task на `C:\restos\backup.ps1`, копия логики из cron-скрипта.

---

## Принтер

В Django admin (`/admin/printing/printer/add/`) создать запись:

| Поле | Пример |
|---|---|
| `name` | Касса |
| `kind` | `tcp` или `usb` |
| `address` | `192.168.1.50:9100` или `0x04b8:0x0202` |
| `is_default` | ✅ |

Тестовая печать: открыть `/admin/printing/printer/{id}/`, в правом верхнем углу действие **Print test page**. Создаётся `PrintJob` с типом `receipt` и фиксированным test-payload — чек с надписью «TEST PAGE».

USB на Linux требует прав:

```bash
# /etc/udev/rules.d/99-escpos.rules
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0666"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Проверочный чеклист после установки

```
[ ] http://<main-pos-ip>/             отдаёт waiter PWA login
[ ] http://<main-pos-ip>/api/v1/auth/me/  без auth → 401 (значит, проксируется)
[ ] http://<main-pos-ip>/admin/         с локалки открывается admin
[ ] systemctl status restos-backend  — active (running)
[ ] systemctl status restos-print-worker — active (running)
[ ] curl -N -H "Authorization: PIN <token>" http://localhost/api/v1/events/
    видит ":ok" → "event: resync" и каждые 15с ":heartbeat" — SSE работает
[ ] печать test page → принтер выдал чек с «TEST PAGE»
[ ] PIN-логин на cashier-app → попадаем на TablesScreen,
    в DevTools/логе видна одна постоянная сессия /events/
[ ] на планшете в той же Wi-Fi → логин официанта, видны столы
[ ] на втором устройстве запросить счёт → у первого изменение видно за < 1 с (через SSE)
[ ] выдернуть Ethernet/Wi-Fi → планшет показывает «Не в сети ресторана»
[ ] вернуть сеть → EventSource сам реконнектится, приходит resync, UI обновляется
[ ] /var/backups/restos/<сегодня>.dump.gz создаётся cron'ом
```

## Обновления

Простой путь: `git pull && pip install -r requirements.txt && manage.py migrate && systemctl restart restos-backend restos-print-worker`. Для PWA — `pnpm build && rsync dist/ /var/www/restos-waiter/`.

Долгосрочно — отдельный installer (DEB/MSI) и авто-обновление cashier через GitHub Releases. Phase 2.
