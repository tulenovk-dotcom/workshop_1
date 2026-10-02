# Развёртывание на Ubuntu 24.04

Короткая инструкция для боевого сервера erekshe.kz. Проверять её на живом
сервере пока было негде, поэтому читайте не как заклинание, а как план:
команды обычные, но первое развёртывание всегда вскрывает мелочи.

Что получится в итоге: приложение работает под systemd и слушает только
`127.0.0.1:8000`, наружу его отдаёт nginx с сертификатом Let's Encrypt,
база и загруженные фото лежат в `/srv/erekshe/data`.

## 1. Пользователь и папки

```bash
sudo adduser --system --group --home /srv/erekshe erekshe
sudo install -d -o erekshe -g erekshe /srv/erekshe/data
sudo install -d -o erekshe -g erekshe /srv/erekshe/data/uploads
```

## 2. Код и зависимости

```bash
sudo apt update
sudo apt install -y python3-venv git nginx

sudo -u erekshe git clone https://github.com/tulenovk-dotcom/workshop_1.git /srv/erekshe
sudo -u erekshe python3 -m venv /srv/erekshe/.venv
sudo -u erekshe /srv/erekshe/.venv/bin/pip install -r /srv/erekshe/requirements.txt
```

## 3. Переменные окружения

```bash
sudo install -d -m 750 -o root -g erekshe /etc/erekshe
sudo cp /srv/erekshe/deploy/erekshe.env.example /etc/erekshe/erekshe.env
sudo chown root:erekshe /etc/erekshe/erekshe.env
sudo chmod 640 /etc/erekshe/erekshe.env
sudo nano /etc/erekshe/erekshe.env
```

Обязательно подставить свои значения: `ADMIN_LOGIN`, `ADMIN_PASSWORD`,
`SECRET_KEY`, `IP_SALT`. Ключи сгенерировать так:

```bash
openssl rand -hex 32
```

**Чего в файле быть не должно:** `SEED_DEMO`, `NOINDEX`,
`SHOW_TEST_BANNER`. Первая нальёт в базу демонстрационные центры и
отзывы, вторая закроет сайт от поисковиков, третья нарисует полосу
«Тестовая версия сайта».

## 4. Служба systemd

```bash
sudo cp /srv/erekshe/deploy/erekshe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now erekshe
systemctl status erekshe
curl -I http://127.0.0.1:8000/
```

Логи: `journalctl -u erekshe -f`.

## 5. nginx и сертификат

```bash
sudo cp /srv/erekshe/deploy/nginx-erekshe.conf /etc/nginx/sites-available/erekshe.kz
sudo ln -s /etc/nginx/sites-available/erekshe.kz /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Домен `erekshe.kz` и `www.erekshe.kz` должны уже указывать A-записью на
адрес сервера, иначе certbot не подтвердит домен.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d erekshe.kz -d www.erekshe.kz
```

Certbot сам допишет блок с сертификатом и редирект с http на https.
После этого в `/etc/erekshe/erekshe.env` должно стоять `COOKIE_SECURE=1`
(в образце уже стоит) - перезапустить службу:

```bash
sudo systemctl restart erekshe
```

Обновление сертификата certbot ставит в таймер сам, проверить:
`systemctl list-timers | grep certbot`.

## 6. Проверка после запуска

```bash
curl -s https://erekshe.kz/robots.txt           # должна быть строка Sitemap:
curl -s https://erekshe.kz/sitemap.xml | head   # адреса страниц
curl -s -o /dev/null -w "%{http_code}\n" https://erekshe.kz/docs   # ждём 404
```

Глазами: на сайте нет полосы «Тестовая версия сайта», каталог пуст
(«Найдено: 0»), вход в `/admin` работает с вашим паролем, страница
`/privacy` называет оператора и сервер в Казахстане.

## 7. Обновление кода

```bash
cd /srv/erekshe
sudo -u erekshe git pull
sudo -u erekshe /srv/erekshe/.venv/bin/pip install -r requirements.txt
sudo systemctl restart erekshe
```

## 8. Резервные копии

База - один файл, поэтому копия делается просто. Копировать на ходу
нельзя: нужен `sqlite3 .backup`, он дождётся согласованного состояния.

```bash
sudo apt install -y sqlite3
sudo -u erekshe sqlite3 /srv/erekshe/data/catalog.db \
  ".backup '/srv/erekshe/data/backup-$(date +%F).db'"
```

Отдельно нужны `uploads` - фото в базе не лежат. Копии стоит увозить с
сервера: диск, на котором лежит и база, и копия, пропадает целиком.

## Чего в этой инструкции нет

- Автоматических резервных копий по расписанию: команду выше нужно
  поставить в cron или systemd-таймер и настроить вывоз копий наружу.
- Своих шрифтов: страницы грузят Google Fonts, и адрес посетителя
  становится известен Google. Для сайта с данными о детях это стоит
  убрать - положить шрифты в `app/static/` и поправить `base.html`.
- Мониторинга и оповещений: если служба упадёт, об этом никто не узнает,
  кроме `systemctl status`.
