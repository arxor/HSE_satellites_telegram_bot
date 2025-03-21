import logging
import requests
import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    ConversationHandler,
    MessageHandler,
    Filters,
)
from skyfield.api import load, EarthSatellite, Topos

import os
from dotenv import load_dotenv

TLE_URL = "http://celestrak.org/NORAD/elements/satnogs.txt"
TLE_FILENAME = "tle.txt"

# Настройки спутника и сеансов (значения по умолчанию)
SAT_NAME = "CUBESX-HSE 3"  # имя спутника (ищется по вхождению)
GROUND_STATION_LAT = 55.7558  # широта станции (например, Москва)
GROUND_STATION_LON = 37.6173  # долгота станции
GROUND_STATION_ELEVATION = 144  # высота в метрах
ALTITUDE_THRESHOLD = (
    15  # минимальный порог наклонения для включения сеанса (в градусах)
)
NOTIFY_MINUTES = 15  # время уведомления до пролёта (в минутах)

# Переменные для TLE
tle_content = None
last_tle_update = None

# Загружаем timescale для расчётов
ts = load.timescale()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def update_tle():
    """Скачивает новый TLE-файл с заданного URL и сохраняет его локально."""
    global tle_content, last_tle_update
    try:
        response = requests.get(TLE_URL)
        if response.status_code == 200:
            tle_content = response.text
            with open(TLE_FILENAME, "w") as f:
                f.write(tle_content)
            last_tle_update = datetime.datetime.utcnow()
            return True, "Файл TLE обновлён."
        else:
            return False, f"Ошибка скачивания TLE: статус {response.status_code}"
    except Exception as e:
        return False, f"Ошибка: {e}"


def get_tle_for_satellite():
    """
    Ищет в TLE-файле блок для спутника.
    Ожидается, что блок состоит из 3 строк:
      - строка с именем (содержащая SAT_NAME),
      - две строки TLE.
    """
    global tle_content
    if tle_content is None:
        try:
            with open(TLE_FILENAME, "r") as f:
                tle_content = f.read()
        except Exception:
            return (
                None,
                None,
                None,
                "TLE-файл не найден. Обновите его командой /update_tle.",
            )
    lines = tle_content.splitlines()
    for i, line in enumerate(lines):
        if SAT_NAME in line:
            if i + 2 < len(lines):
                return lines[i], lines[i + 1], lines[i + 2], None
            else:
                return None, None, None, "Неполные данные TLE для спутника."
    return None, None, None, "Спутник не найден в TLE-файле."


def get_satellite():
    """Создаёт объект EarthSatellite для спутника."""
    name_line, tle_line1, tle_line2, error = get_tle_for_satellite()
    if error:
        return None, error
    try:
        sat = EarthSatellite(tle_line1, tle_line2, SAT_NAME, ts)
        return sat, None
    except Exception as e:
        return None, f"Ошибка создания спутника: {e}"


def calculate_passes(next_days=3):
    """
    Рассчитывает пролёты спутника над станцией за период от текущего момента до next_days вперёд.
    Используются события подъёма/захода (при 0°). Сеанс включается, если максимальное наклонение (в точке кульминации)
    больше ALTITUDE_THRESHOLD.
    """
    sat, error = get_satellite()
    if error:
        return None, error
    station = Topos(
        latitude_degrees=GROUND_STATION_LAT,
        longitude_degrees=GROUND_STATION_LON,
        elevation_m=GROUND_STATION_ELEVATION,
    )
    eph = load("de421.bsp")
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    t0 = ts.utc(now)
    t1 = ts.utc(now + datetime.timedelta(days=next_days))
    try:
        # Используем пересечение горизонта (0°) для определения событий
        t_events, events = sat.find_events(station, t0, t1, altitude_degrees=0)
    except Exception as e:
        return None, f"Ошибка расчёта пролётов: {e}"
    passes = []
    i = 0
    while i < len(events):
        # Ожидается последовательность: 0 - подъём, 1 - кульминация, 2 - заход
        if (
            events[i] == 0
            and i + 2 < len(events)
            and events[i + 1] == 1
            and events[i + 2] == 2
        ):
            rise_time = t_events[i].utc_datetime()
            culm_time = t_events[i + 1].utc_datetime()
            set_time = t_events[i + 2].utc_datetime()
            # Вычисляем максимальное наклонение в точке кульминации
            difference = sat - station
            alt, az, distance = difference.at(t_events[i + 1]).altaz()
            max_elevation = alt.degrees
            # Если максимальное наклонение меньше порога, пропускаем сеанс
            if max_elevation >= ALTITUDE_THRESHOLD:
                passes.append(
                    {
                        "rise": rise_time,
                        "culmination": culm_time,
                        "set": set_time,
                        "max_elevation": max_elevation,
                    }
                )
            i += 3
        else:
            i += 1
    return passes, None


def format_time(dt: datetime.datetime) -> tuple[str, str]:
    """Возвращает кортеж строк (UTC, МСК) для datetime."""
    utc_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    msk_tz = datetime.timezone(datetime.timedelta(hours=3))
    msk_str = dt.astimezone(msk_tz).strftime("%Y-%m-%d %H:%M:%S")
    return utc_str, msk_str


def pass_notification(context: CallbackContext):
    """Отправляет уведомление о начале пролёта за NOTIFY_MINUTES минут до события."""
    job = context.job
    chat_id = job.context["chat_id"]
    context.bot.send_message(
        chat_id=chat_id,
        text=f"Напоминаю: через {NOTIFY_MINUTES} минут(ы) начнется пролет спутника {SAT_NAME}!",
    )


def schedule_notification(context: CallbackContext, pass_time, chat_id):
    """
    Планирует уведомление за NOTIFY_MINUTES минут до подъёма сеанса.
    Если время уведомления ещё не прошло, ставится задача в JobQueue.
    """
    notify_time = pass_time - datetime.timedelta(minutes=NOTIFY_MINUTES)
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    delay = (notify_time - now).total_seconds()
    if delay > 0:
        context.job_queue.run_once(
            pass_notification, delay, context={"chat_id": chat_id}
        )
    else:
        logger.info("Время уведомления уже прошло.")


def start(update: Update, context: CallbackContext):
    """Команда /start – выводит информацию о TLE и основные действия."""
    msg = "Добро пожаловать!\n"
    if last_tle_update:
        msg += (
            f"TLE-файл обновлён: {last_tle_update.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        )
    else:
        msg += "TLE-файл не обновлён – обновите его с помощью /update_tle\n"
    keyboard = [
        [InlineKeyboardButton("Ближайший сеанс", callback_data="next_pass")],
        [InlineKeyboardButton("Сеансы на 3 дня", callback_data="three_day_passes")],
        [InlineKeyboardButton("Обновить TLE", callback_data="update_tle")],
        [InlineKeyboardButton("Настройки", callback_data="settings")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(msg, reply_markup=reply_markup)


def button_handler(update: Update, context: CallbackContext):
    """
    Глобальный обработчик callback‑запросов для главного меню.
    Обрабатываются только запросы с данными: next_pass, three_day_passes, update_tle, settings, back_to_main.
    """
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "next_pass":
        passes, error = calculate_passes(next_days=3)
        if error:
            query.edit_message_text(text="Ошибка: " + error)
            return
        if not passes:
            query.edit_message_text(text="Сеансов не найдено в ближайшие 3 дня.")
            return
        next_pass = passes[0]
        rise_utc, rise_msk = format_time(next_pass["rise"])
        culm_utc, culm_msk = format_time(next_pass["culmination"])
        set_utc, set_msk = format_time(next_pass["set"])
        msg = (
            f"Следующий сеанс:\n"
            f"Подъём (0°): {rise_utc} UTC / {rise_msk} МСК\n"
            f"Кульминация:\n  UTC: {culm_utc}\n  МСК: {culm_msk}\n"
            f"Завершение (0°): {set_utc} UTC / {set_msk} МСК\n"
            f"Максимальное наклонение: {next_pass['max_elevation']:.1f}°"
        )
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=msg, reply_markup=reply_markup)
        schedule_notification(context, next_pass["rise"], query.message.chat_id)
    elif data == "three_day_passes":
        passes, error = calculate_passes(next_days=3)
        if error:
            query.edit_message_text(text="Ошибка: " + error)
            return
        if not passes:
            query.edit_message_text(text="Сеансов не найдено в ближайшие 3 дня.")
            return
        msg = "Сеансы на 3 дня:\n"
        for p in passes:
            rise_utc, rise_msk = format_time(p["rise"])
            culm_utc, culm_msk = format_time(p["culmination"])
            set_utc, set_msk = format_time(p["set"])
            msg += (
                f"\nПодъём (0°): {rise_utc} UTC / {rise_msk} МСК\n"
                f"Кульминация: {culm_utc} UTC / {culm_msk} МСК\n"
                f"Завершение (0°): {set_utc} UTC / {set_msk} МСК\n"
                f"Максимальное наклонение: {p['max_elevation']:.1f}°\n"
            )
        keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=msg, reply_markup=reply_markup)
    elif data == "update_tle":
        success, message = update_tle()
        text = (
            ("TLE обновлён.\n" + message)
            if success
            else ("Ошибка обновления TLE: " + message)
        )
        query.edit_message_text(text=text)
    elif data == "settings":
        # Для настроек выводим подсказку – дальнейшее управление через команду /settings
        query.edit_message_text("Введите /settings для изменения настроек.")
    elif data == "back_to_main":
        msg = "Добро пожаловать!\n"
        if last_tle_update:
            msg += f"TLE-файл обновлён: {last_tle_update.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        else:
            msg += "TLE-файл не обновлён – обновите его с помощью /update_tle\n"
        keyboard = [
            [InlineKeyboardButton("Ближайший сеанс", callback_data="next_pass")],
            [InlineKeyboardButton("Сеансы на 3 дня", callback_data="three_day_passes")],
            [InlineKeyboardButton("Обновить TLE", callback_data="update_tle")],
            [InlineKeyboardButton("Настройки", callback_data="settings")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=msg, reply_markup=reply_markup)


def next_pass_command(update: Update, context: CallbackContext):
    """Команда /next – вывод ближайшего пролёта с уведомлением."""
    passes, error = calculate_passes(next_days=3)
    if error:
        update.message.reply_text("Ошибка: " + error)
        return
    if not passes:
        update.message.reply_text("Сеансов не найдено в ближайшие 3 дня.")
        return
    next_pass = passes[0]
    rise_utc, rise_msk = format_time(next_pass["rise"])
    culm_utc, culm_msk = format_time(next_pass["culmination"])
    set_utc, set_msk = format_time(next_pass["set"])
    msg = (
        f"Следующий сеанс:\n"
        f"Подъём (0°): {rise_utc} UTC / {rise_msk} МСК\n"
        f"Кульминация:\n  UTC: {culm_utc}\n  МСК: {culm_msk}\n"
        f"Завершение (0°): {set_utc} UTC / {set_msk} МСК\n"
        f"Максимальное наклонение: {next_pass['max_elevation']:.1f}°"
    )
    update.message.reply_text(msg)
    schedule_notification(context, next_pass["rise"], update.message.chat_id)


def three_day_command(update: Update, context: CallbackContext):
    """Команда /three – вывод всех пролётов на 3 дня."""
    passes, error = calculate_passes(next_days=3)
    if error:
        update.message.reply_text("Ошибка: " + error)
        return
    if not passes:
        update.message.reply_text("Сеансов не найдено в ближайшие 3 дня.")
        return
    msg = "Сеансы на 3 дня:\n"
    for p in passes:
        rise_utc, rise_msk = format_time(p["rise"])
        culm_utc, culm_msk = format_time(p["culmination"])
        set_utc, set_msk = format_time(p["set"])
        msg += (
            f"\nПодъём (0°): {rise_utc} UTC / {rise_msk} МСК\n"
            f"Кульминация: {culm_utc} UTC / {culm_msk} МСК\n"
            f"Завершение (0°): {set_utc} UTC / {set_msk} МСК\n"
            f"Максимальное наклонение: {p['max_elevation']:.1f}°\n"
        )
    keyboard = [[InlineKeyboardButton("Назад", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(msg, reply_markup=reply_markup)


def update_tle_command(update: Update, context: CallbackContext):
    """Команда /update_tle – ручное обновление TLE-файла."""
    success, message = update_tle()
    text = (
        ("TLE обновлён.\n" + message)
        if success
        else ("Ошибка обновления TLE: " + message)
    )
    update.message.reply_text(text)


(
    SETTING_CHOICE,
    SET_SAT_NAME,
    SET_STATION_COORDS,
    SET_STATION_ELEV,
    SET_ALT_THRESHOLD,
    SET_NOTIFY_MINUTES,
    SET_TLE_URL,
) = range(7)


def get_settings_text():
    """Возвращает строку с текущими настройками."""
    return (
        f"Текущие настройки:\n"
        f"Название спутника: {SAT_NAME}\n"
        f"Координаты станции: {GROUND_STATION_LAT}, {GROUND_STATION_LON}\n"
        f"Высота станции: {GROUND_STATION_ELEVATION} м\n"
        f"Порог наклонения пролёта: {ALTITUDE_THRESHOLD}°\n"
        f"Время уведомления: {NOTIFY_MINUTES} мин до пролёта\n"
        f"TLE URL: {TLE_URL}\n"
    )


def settings_keyboard():
    """Формирует inline‑клавиатуру для настроек."""
    keyboard = [
        [
            InlineKeyboardButton(
                "Изменить название спутника", callback_data="set_sat_name"
            )
        ],
        [
            InlineKeyboardButton(
                "Изменить координаты станции", callback_data="set_station_coords"
            )
        ],
        [
            InlineKeyboardButton(
                "Изменить высоту станции", callback_data="set_station_elev"
            )
        ],
        [
            InlineKeyboardButton(
                "Изменить порог наклонения пролёта", callback_data="set_alt_threshold"
            )
        ],
        [
            InlineKeyboardButton(
                "Изменить время уведомления", callback_data="set_notify_minutes"
            )
        ],
        [InlineKeyboardButton("Изменить TLE URL", callback_data="set_tle_url")],
        [InlineKeyboardButton("Готово", callback_data="done")],
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_start(update: Update, context: CallbackContext):
    """Команда /settings – вывод текущих настроек и меню для их изменения."""
    update.message.reply_text("Настройки:")
    update.message.reply_text(get_settings_text(), reply_markup=settings_keyboard())
    return SETTING_CHOICE


def settings_button(update: Update, context: CallbackContext):
    """Обработчик inline‑кнопок в режиме настроек."""
    query = update.callback_query
    query.answer()
    data = query.data
    if data == "set_sat_name":
        query.edit_message_text("Введите новое название спутника:")
        return SET_SAT_NAME
    elif data == "set_station_coords":
        query.edit_message_text(
            "Введите новые координаты станции в формате: lat,lon (например, 55.7558,37.6173):"
        )
        return SET_STATION_COORDS
    elif data == "set_station_elev":
        query.edit_message_text("Введите новую высоту станции (в метрах):")
        return SET_STATION_ELEV
    elif data == "set_alt_threshold":
        query.edit_message_text("Введите новый порог наклонения пролёта (в градусах):")
        return SET_ALT_THRESHOLD
    elif data == "set_notify_minutes":
        query.edit_message_text(
            "Введите новое время уведомления (в минутах до пролёта):"
        )
        return SET_NOTIFY_MINUTES
    elif data == "set_tle_url":
        query.edit_message_text("Введите новый URL для TLE файла:")
        return SET_TLE_URL
    elif data == "done":
        query.edit_message_text("Настройки сохранены.\n" + get_settings_text())
        return ConversationHandler.END


def set_sat_name(update: Update, context: CallbackContext):
    global SAT_NAME
    SAT_NAME = update.message.text.strip()
    update.message.reply_text("Название спутника обновлено.\n" + get_settings_text())
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def set_station_coords(update: Update, context: CallbackContext):
    global GROUND_STATION_LAT, GROUND_STATION_LON
    text = update.message.text.strip()
    try:
        lat_str, lon_str = text.split(",")
        GROUND_STATION_LAT = float(lat_str.strip())
        GROUND_STATION_LON = float(lon_str.strip())
        update.message.reply_text(
            "Координаты станции обновлены.\n" + get_settings_text()
        )
    except Exception:
        update.message.reply_text(
            "Неверный формат. Введите координаты в формате: lat,lon"
        )
        return SET_STATION_COORDS
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def set_station_elev(update: Update, context: CallbackContext):
    global GROUND_STATION_ELEVATION
    try:
        GROUND_STATION_ELEVATION = float(update.message.text.strip())
        update.message.reply_text("Высота станции обновлена.\n" + get_settings_text())
    except Exception:
        update.message.reply_text("Неверный формат. Введите число для высоты станции.")
        return SET_STATION_ELEV
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def set_alt_threshold(update: Update, context: CallbackContext):
    global ALTITUDE_THRESHOLD
    try:
        ALTITUDE_THRESHOLD = float(update.message.text.strip())
        update.message.reply_text(
            "Порог наклонения пролёта обновлён.\n" + get_settings_text()
        )
    except Exception:
        update.message.reply_text(
            "Неверный формат. Введите число для порога наклонения пролёта."
        )
        return SET_ALT_THRESHOLD
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def set_notify_minutes(update: Update, context: CallbackContext):
    global NOTIFY_MINUTES
    try:
        NOTIFY_MINUTES = int(update.message.text.strip())
        update.message.reply_text(
            "Время уведомления обновлено.\n" + get_settings_text()
        )
    except Exception:
        update.message.reply_text(
            "Неверный формат. Введите целое число для минут уведомления."
        )
        return SET_NOTIFY_MINUTES
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def set_tle_url(update: Update, context: CallbackContext):
    global TLE_URL
    url = update.message.text.strip()
    if url.startswith("http://") or url.startswith("https://"):
        TLE_URL = url
        update.message.reply_text("TLE URL обновлён.\n" + get_settings_text())
    else:
        update.message.reply_text(
            "Неверный URL. Введите URL, начинающийся с http:// или https://"
        )
        return SET_TLE_URL
    update.message.reply_text("Выберите действие:", reply_markup=settings_keyboard())
    return SETTING_CHOICE


def settings_cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Настройка отменена.")
    return ConversationHandler.END


def main():
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("Переменная окружения BOT_TOKEN не установлена!")

    updater = Updater(token, use_context=True)

    dp = updater.dispatcher

    # Глобальный обработчик callback‑запросов для главного меню
    dp.add_handler(
        CallbackQueryHandler(
            button_handler,
            pattern="^(next_pass|three_day_passes|update_tle|settings|back_to_main)$",
        )
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("next", next_pass_command))
    dp.add_handler(CommandHandler("three", three_day_command))
    dp.add_handler(CommandHandler("update_tle", update_tle_command))

    # Обработчик настроек через ConversationHandler, обрабатывающий только callback‑запросы для настроек
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", settings_start)],
        states={
            SETTING_CHOICE: [
                CallbackQueryHandler(
                    settings_button,
                    pattern="^(set_sat_name|set_station_coords|set_station_elev|set_alt_threshold|set_notify_minutes|set_tle_url|done)$",
                )
            ],
            SET_SAT_NAME: [
                MessageHandler(Filters.text & ~Filters.command, set_sat_name)
            ],
            SET_STATION_COORDS: [
                MessageHandler(Filters.text & ~Filters.command, set_station_coords)
            ],
            SET_STATION_ELEV: [
                MessageHandler(Filters.text & ~Filters.command, set_station_elev)
            ],
            SET_ALT_THRESHOLD: [
                MessageHandler(Filters.text & ~Filters.command, set_alt_threshold)
            ],
            SET_NOTIFY_MINUTES: [
                MessageHandler(Filters.text & ~Filters.command, set_notify_minutes)
            ],
            SET_TLE_URL: [MessageHandler(Filters.text & ~Filters.command, set_tle_url)],
        },
        fallbacks=[CommandHandler("cancel", settings_cancel)],
    )
    dp.add_handler(settings_conv)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    update_tle()
    main()
