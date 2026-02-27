# 🐳 Docker инструкция для VPN-бота

## Что такое Docker?

**Docker** — это система контейнеризации, которая позволяет упаковать приложение со всеми зависимостями в изолированный контейнер.

### Преимущества:
- ✅ Работает одинаково на любом сервере
- ✅ Не нужно устанавливать Python, зависимости вручную
- ✅ Легко обновлять и делать откат
- ✅ Изоляция от системы
- ✅ Простое резервное копирование

---

## 📋 Требования

- Ubuntu 20.04+ или Debian 10+
- Минимум 512 MB RAM
- Docker и Docker Compose

---

## 🚀 Установка Docker

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Установка Docker Compose
sudo apt install -y docker-compose-plugin

# Проверка
docker --version
docker compose version

# Добавить пользователя в группу docker (опционально)
sudo usermod -aG docker $USER
```

---

## 📦 Установка бота

### 1. Скопируйте файлы

```bash
cd /opt
# Распакуйте архив с ботом или склонируйте репозиторий
cd vpn_bot
```

### 2. Настройте .env

```bash
nano .env
```

Заполните:
- `BOT_TOKEN` — токен бота
- `ADMIN_IDS` — ваш Telegram ID
- `CHANNEL_ID` — ID канала
- Остальные настройки

### 3. Создайте SSL сертификаты

```bash
# Создайте директорию для SSL
sudo mkdir -p ssl

# Получите сертификат (замените domain.com на ваш домен)
sudo docker run --rm -it \
    -v /opt/vpn_bot/ssl:/etc/letsencrypt \
    certbot/certbot certonly --standalone \
    -d your-domain.com \
    --email your@email.com \
    --agree-tos
```

### 4. Настройте nginx.conf

Откройте `nginx.conf` и замените `_` на ваш домен:

```nginx
server_name your-domain.com;
```

### 5. Запустите бота

```bash
# Запуск в фоновом режиме
sudo docker compose up -d

# Просмотр логов
sudo docker compose logs -f bot

# Проверка статуса
sudo docker compose ps
```

---

## 🔧 Управление

### Просмотр логов

```bash
# Все логи
sudo docker compose logs -f

# Только бот
sudo docker compose logs -f bot

# Только nginx
sudo docker compose logs -f nginx
```

### Перезапуск

```bash
# Перезапуск всех сервисов
sudo docker compose restart

# Перезапуск только бота
sudo docker compose restart bot
```

### Остановка

```bash
# Остановить все сервисы
sudo docker compose down

# Остановить и удалить volumes (БД!)
sudo docker compose down -v  # ОПАСНО: удалит базу данных!
```

### Обновление

```bash
# 1. Остановите бота
sudo docker compose down

# 2. Обновите файлы (git pull или скопируйте новые)
git pull  # или вручную

# 3. Пересоберите образ
sudo docker compose build --no-cache

# 4. Запустите заново
sudo docker compose up -d
```

---

## 💾 Резервное копирование

### Бэкап базы данных

```bash
# Создать бэкап
sudo docker cp vpn_bot:/opt/vpn_bot/vpn_bot.db ./backup_$(date +%Y%m%d).db

# Восстановить
sudo docker cp ./backup_20260227.db vpn_bot:/opt/vpn_bot/vpn_bot.db
sudo docker compose restart bot
```

### Бэкап логов

```bash
tar -czf logs_backup_$(date +%Y%m%d).tar.gz logs/
```

### Полный бэкап

```bash
# Создать архив со всеми данными
tar -czf vpn_bot_backup_$(date +%Y%m%d).tar.gz \
    .env \
    vpn_bot.db \
    logs/ \
    ssl/
```

---

## 🐛 Решение проблем

### Бот не запускается

```bash
# Проверить логи
sudo docker compose logs bot

# Проверить конфигурацию
sudo docker compose config
```

### Ошибка "port already in use"

```bash
# Найти процесс на порту 8080
sudo lsof -i :8080

# Остановить или изменить порт в .env
```

### SSL сертификат не работает

```bash
# Проверить сертификаты
sudo ls -la ssl/

# Обновить сертификат
sudo docker compose run --rm certbot renew
```

### Бот не подключается к 3x-ui

```bash
# Проверить сеть
sudo docker compose exec bot ping 213.21.240.231

# Проверить .env
sudo docker compose exec bot env | grep XUI
```

### Нехватка места на диске

```bash
# Очистить старые образы
sudo docker system prune -a

# Проверить место
df -h
```

---

## 📊 Мониторинг

### Статистика использования ресурсов

```bash
# Использование CPU/RAM
sudo docker stats

# Только бот
sudo docker stats vpn_bot
```

### Проверка здоровья

```bash
# Health check
sudo docker inspect --format='{{.State.Health.Status}}' vpn_bot

# Webhook health endpoint
curl http://localhost:8080/health
```

---

## 🔐 Безопасность

### Firewall (UFW)

```bash
# Включить firewall
sudo ufw enable

# Разрешить SSH
sudo ufw allow 22/tcp

# Разрешить HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Закрыть порт 8080 (только для nginx)
sudo ufw deny 8080/tcp

# Проверить статус
sudo ufw status
```

### Обновление безопасности

```bash
# Регулярно обновляйте систему
sudo apt update && sudo apt upgrade -y

# Обновляйте Docker образы
sudo docker compose pull
sudo docker compose up -d
```

---

## 📈 Масштабирование

### Несколько инстансов бота

```yaml
# docker-compose.yml
services:
  bot:
    replicas: 3
    deploy:
      mode: replicated
      replicas: 3
```

### Load Balancing

```nginx
# nginx.conf
upstream vpn_bot {
    server bot1:8080;
    server bot2:8080;
    server bot3:8080;
}
```

---

## 🎯 Следующие шаги

1. **Настройте домен** — купите домен и направьте на сервер
2. **Получите SSL сертификат** — Let's Encrypt бесплатно
3. **Настройте мониторинг** — Prometheus + Grafana
4. **Автоматические бэкапы** — cron + скрипт
5. **CI/CD** — GitHub Actions для авто-деплоя

---

## 📞 Поддержка

При проблемах:
1. Проверьте логи: `docker compose logs -f`
2. Проверьте конфиг: `docker compose config`
3. Перезапустите: `docker compose restart`
4. Прочитайте документацию: SETUP.md, CHANGELOG.md
