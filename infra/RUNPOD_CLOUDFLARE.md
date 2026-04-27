# Запуск на RunPod через Cloudflare Tunnel

Образ запускает RustASR как раньше. Если задана переменная `CLOUDFLARED_TOKEN`, рядом с ним в том же контейнере запускается `cloudflared`, который прокидывает публичный hostname Cloudflare на локальный сервер `http://localhost:8080`.

## Что настроить в Cloudflare

1. Откройте Cloudflare Zero Trust.
2. Создайте или откройте tunnel.
3. Для tunnel настройте Public Hostname:
   - Hostname: `asr-proxy.efficlose.com`
   - Service: `http://localhost:8080`
4. Скопируйте новый token tunnel.

Токен нельзя хранить в Dockerfile, git или документации. Если токен уже был отправлен в чат или лог, его нужно перевыпустить.

## Что задать в RunPod

В переменных окружения pod/template:

```text
HOST=0.0.0.0:8080
CLOUDFLARED_TOKEN=<новый токен Cloudflare Tunnel>
```

Также поддерживается имя `TUNNEL_TOKEN`, если оно уже используется в шаблоне.

Остальные переменные зависят от выбранного образа:

```text
DEVICE=cuda
MODEL_TYPE=gigaam
MODEL_PATH=/app/models/gigaam-v3-e2e-ctc
LANGUAGE=ru
```

Для проверки без Cloudflare можно не задавать `CLOUDFLARED_TOKEN`/`TUNNEL_TOKEN`. Тогда контейнер запустит только `/app/rustasr`, как раньше.

## Ожидаемая схема

```text
https://asr-proxy.efficlose.com
  -> Cloudflare Tunnel
  -> cloudflared внутри контейнера RunPod
  -> http://localhost:8080
  -> RustASR WebSocket /transcribe
```
