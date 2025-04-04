# Telegram-бот для отслеживания спутников НИУ ВШЭ
![Telegram_9IVQ0AjtPV](https://github.com/user-attachments/assets/82f61e7f-fb9d-403e-a103-10e0326db19f)

Этот бот предназначен для удобного отслеживания пролётов спутника НИУ ВШЭ **CubeSX-HSE 3**. Он позволяет:

- Автоматически скачивать и обновлять TLE-данные спутника.
- Получать информацию о ближайших сеансах связи (пролётах спутника над выбранной наземной станцией).
- Настроить уведомления о предстоящих пролётах.

## Возможности

- Получение актуальной информации TLE из открытых источников (Celestrak).
- Расчёт времени пролётов спутника
- Получение уведомлений за заданное время до начала пролёта.
- Изменение названия спутника, координат и высоты станции, порога наклонения, URL файла TLE и времени уведомлений.

## Технические требования

- Python 3.8+
- [python-telegram-bot](https://python-telegram-bot.org/)
- [Skyfield](https://rhodesmill.org/skyfield/)
- Requests
- python-dotenv

Полный список зависимостей указан в файле [requirements.txt](requirements.txt).

## Установка и запуск

1. **Клонируйте репозиторий:**

```bash
git clone https://github.com/yourusername/hse-satellite-bot.git
cd hse-satellite-bot
```

2. **Создайте виртуальное окружение:**

```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Установите зависимости:**

```bash
pip install -r requirements.txt
```

4. **Создайте файл с переменными окружения** `.env` в корне проекта и добавьте токен вашего бота:

```env
BOT_TOKEN=ваш_токен_от_botfather
```

5. **Запустите бота:**

```bash
python main.py
```

## Развёртывание на сервере

Подробная инструкция по развёртыванию бота на сервере описана в [документации](deploy.md).

## Использование

После запуска бота в Telegram используйте команды:

- `/start` – основное меню бота.
- `/next` – показать ближайший сеанс связи.
- `/three` – показать все сеансы на ближайшие 3 дня.
- `/update_tle` – обновить TLE-файл вручную.
- `/settings` – изменить настройки (спутник, станция, порог наклонения и уведомления).

## Лицензия

Этот проект распространяется по лицензии MIT.
