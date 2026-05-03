# 🔄 Архитектура системы — Order Book + Footprint + Volume Profile

## 📊 Общая схема потока данных

```
┌─────────────────────────────────────────────────────────────────┐
│                    BINANCE / BYBIT API                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ├─── WebSocket (real-time)
                              │    ├─── Price (!miniTicker@arr)
                              │    ├─── Tickers (OI + Funding)
                              │    └─── Trades (aggTrade/publicTrade)
                              │
                              └─── REST (polling)
                                   ├─── OI (каждые 10с)
                                   ├─── Funding (каждые 60с)
                                   ├─── L/S Ratio (по запросу)
                                   └─── Order Book (по запросу, кэш 30с)
                              ┌──────────────┐
                              │              │
                              ▼              ▼
                    ┌──────────────┐  ┌──────────────┐
                    │  binance.py  │  │   bybit.py   │
                    └──────────────┘  └──────────────┘
                              │              │
                              └──────┬───────┘
                                     │
                                     ▼
                        ┌─────────────────────┐
                        │   data_store.py     │
                        │  (in-memory cache)  │
                        ├─────────────────────┤
                        │ • price_history     │
                        │ • oi_history        │
                        │ • funding_rates     │
                        │ • ls_ratio          │
                        │ • cvd_history       │
                        │ • liq_events        │
                        │ • _footprint_trades │◄─── НОВОЕ
                        └─────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
          ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
          │ screener.py  │  │cvd_tracker.py│  │ orderbook.py │◄─── НОВОЕ
          │  (OI сигнал) │  │ (динамич.    │  │ (стенки +    │
          │              │  │  подписки)   │  │  vol.profile)│
          └──────────────┘  └──────────────┘  └──────────────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                                     ▼
                          ┌──────────────────┐
                          │  aggregator.py   │
                          │  (скоринг LONG/  │
                          │   SHORT сигналов)│
                          └──────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
          ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
          │ notifier.py  │  │trade_tracker │  │ trade_bot.py │
          │  (Telegram)  │  │  (TP/SL)     │  │ (интеракт.)  │
          └──────────────┘  └──────────────┘  └──────────────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                                     ▼
                              ┌──────────────┐
                              │   TELEGRAM   │
                              │     USER     │
                              └──────────────┘
```

---

## 🔄 Детальный поток: Order Book

```
1. Агрегатор обнаружил потенциальный сигнал
   │
   ▼
2. Вызов: orderbook.get_walls(exchange, symbol, current_price)
   │
   ├─── Проверка кэша (30 секунд)
   │    └─── Если есть → возврат из кэша
   │
   └─── Если нет → HTTP запрос к API
        │
        ├─── Binance: GET /fapi/v1/depth?symbol=X&limit=20
        └─── Bybit:   GET /v5/market/orderbook?symbol=X&limit=20
             │
             ▼
        Парсинг ответа:
        {
          "bids": [(price, qty), ...],  // 20 уровней
          "asks": [(price, qty), ...]   // 20 уровней
        }
             │
             ▼
        Поиск крупных стенок:
        - Считаем средний размер ордера
        - Фильтр: >= 3x среднего И >= $8K
        - Фильтр: дистанция 0-4% (asks) или -4-0% (bids)
             │
             ▼
        Результат:
        {
          "ask_walls": [{"price": 67850, "usd": 45000, "pct": 2.3}],
          "bid_walls": [{"price": 66100, "usd": 38000, "pct": -2.0}]
        }
             │
             ▼
        Сохранение в кэш (30 секунд)
             │
             ▼
        Скоринг:
        - Если ask_wall близко → +1 балл SHORT
        - Если bid_wall близко → +1 балл LONG
             │
             ▼
        Отображение в сообщении:
        "🧱 Стенка продаж: 67,850 (+2.3%, $45K)"
```

---

## 👣 Детальный поток: Footprint

```
1. Screener обнаружил OI >= 3%
   │
   ▼
2. cvd_tracker.start_watch(exchange, symbol)
   │
   ├─── data_store.reset_cvd(exchange, symbol)
   └─── Открытие WebSocket на торговый поток
        │
        ├─── Binance: ws/{symbol}@aggTrade
        └─── Bybit:   publicTrade.{symbol}
             │
             ▼
        Каждая сделка:
        {
          "price": 67450.5,
          "qty": 0.15,
          "is_buy": true
        }
             │
             ▼
        data_store.add_trade(exchange, symbol, qty, is_buy, price)
             │
             ├─── CVD: delta = qty if is_buy else -qty
             │    cvd_running += delta
             │    cvd_history.append((ts, cvd_running))
             │
             └─── Footprint: _record_footprint(...)
                  │
                  ├─── Округление цены: bucket = _price_bucket(price)
                  │    Пример: 67450.5 → 67400 (3 значимые цифры)
                  │
                  ├─── Расчёт USD: usd = price * qty
                  │
                  └─── Запись: _footprint_trades.append(
                       (ts, bucket, buy_usd, sell_usd)
                  )
             │
             ▼
3. Агрегатор проверяет сигнал
   │
   ▼
4. get_footprint_bias(exchange, symbol, current_price)
   │
   ├─── Фильтр: только уровни в ±1.5% от цены
   ├─── Фильтр: только за последние 300 секунд
   │
   ▼
   Группировка по bucket:
   {
     67400: {"buy": 12500, "sell": 3200, "delta": +9300},
     67500: {"buy": 8100,  "sell": 15400, "delta": -7300},
     ...
   }
   │
   ▼
   Суммарная дельта: total_buy - total_sell = +12450
   │
   ▼
   Скоринг:
   - Если > $1K → +1 балл LONG
   - Если < -$1K → +1 балл SHORT
   │
   ▼
   Отображение:
   "🟢 Footprint: покупатели $12.5K"
```

---

## 📈 Детальный поток: Volume Profile

```
1. Агрегатор готовит сигнал
   │
   ▼
2. orderbook.get_volume_zones(price_hist, n=3)
   │
   ├─── Входные данные: price_history (deque с тысячами точек)
   │    Пример: [(ts1, 67200), (ts2, 67250), ..., (tsN, 67800)]
   │
   ▼
3. Разбивка на бакеты (40 штук):
   │
   ├─── Диапазон: min=66000, max=68000
   ├─── Размер бакета: (68000-66000)/40 = 50
   │
   └─── Бакеты: [66000-66050, 66050-66100, ..., 67950-68000]
        │
        ▼
4. Подсчёт времени на каждом уровне:
   │
   Для каждой точки в price_history:
   - Определяем бакет: idx = (price - min) / bucket_size
   - Увеличиваем счётчик: counts[idx] += 1
   │
   Результат:
   counts = [5, 12, 8, 45, 67, 23, ..., 3]
            │   │   │   │   │   │        │
            │   │   │   │   │   │        └─ мало времени
            │   │   │   │   └───┴────────── много времени (зона)
   │
   ▼
5. Топ-3 бакета с максимальным временем:
   │
   Сортировка: [67100 (67 точек), 66200 (45), 68500 (23)]
   │
   ▼
6. Отображение в сообщении:
   "📊 Volume зоны: 66,200 / 67,100 / 68,500"
```

---

## 🎯 Интеграция в скоринг агрегатора

```
aggregator._score(exchange, symbol)
│
├─── Базовые факторы (до 19 баллов SHORT / 14 LONG):
│    ├─── OI изменение
│    ├─── Цена 15м/20м/1ч
│    ├─── Funding rate
│    ├─── CVD
│    ├─── Ликвидации
│    └─── L/S ratio
│
├─── НОВОЕ: Footprint (+1 балл):
│    │
│    ├─── fp_bias = get_footprint_bias(exchange, symbol, current_price)
│    │
│    └─── Если fp_bias < -1000 → SHORT +1
│         Если fp_bias > 1000  → LONG +1
│
├─── НОВОЕ: Order Book (+1 балл):
│    │
│    ├─── walls = await orderbook.get_walls(exchange, symbol, current_price)
│    │
│    └─── Если ask_wall 0-4% выше  → SHORT +1
│         Если bid_wall -4-0% ниже → LONG +1
│
└─── НОВОЕ: Volume Profile (отображение):
     │
     └─── vol_zones = orderbook.get_volume_zones(price_hist, n=3)
          │
          └─── Добавляется в сигнал для отображения
```

---

## 💾 Структура данных в памяти

### data_store.py:

```python
# Footprint storage (НОВОЕ)
_footprint_trades = {
    "binance": {
        "BTCUSDT": deque([
            (ts1, 67400, 1250.0, 0.0),      # (timestamp, bucket, buy_usd, sell_usd)
            (ts2, 67400, 0.0, 850.0),
            (ts3, 67500, 3200.0, 0.0),
            ...
        ], maxlen=5000),
        "ETHUSDT": deque([...], maxlen=5000),
        ...
    },
    "bybit": {...}
}

# CVD storage (существующее)
cvd_history = {
    "binance": {
        "BTCUSDT": deque([
            (ts1, 1250.0),    # (timestamp, cumulative_delta)
            (ts2, 400.0),
            (ts3, 3600.0),
            ...
        ], maxlen=3000),
        ...
    },
    ...
}

# Price storage (существующее)
price_history = {
    "binance": {
        "BTCUSDT": deque([
            (ts1, 67200.5),   # (timestamp, price)
            (ts2, 67250.3),
            (ts3, 67180.7),
            ...
        ], maxlen=4000),
        ...
    },
    ...
}
```

### orderbook.py:

```python
# Order Book cache (НОВОЕ)
_cache = {
    "binance:BTCUSDT": (
        timestamp,  # время кэширования
        {
            "ask_walls": [{"price": 67850, "usd": 45000, "pct": 2.3}],
            "bid_walls": [{"price": 66100, "usd": 38000, "pct": -2.0}]
        }
    ),
    ...
}
```

---

## ⚡ Производительность

### Память:
```
Footprint (на 1 символ):
- 5000 записей × 32 байта = 160 KB
- 10 активных CVD подписок = 1.6 MB

Order Book cache (на 1 символ):
- ~2 KB (20 bids + 20 asks)
- 100 символов в кэше = 200 KB

Volume Profile:
- Вычисляется на лету, не хранится
- Использует существующий price_history

ИТОГО: ~2 MB дополнительно при 10 активных CVD
```

### CPU:
```
Order Book:
- 1 HTTP запрос раз в 30с (только при сигнале)
- Парсинг JSON: ~1ms
- Поиск стенок: ~2ms

Footprint:
- Запись сделки: O(1), ~0.01ms
- Расчёт bias: O(N), N≤5000, ~5ms

Volume Profile:
- Расчёт зон: O(N), N≤4000, ~10ms

ИТОГО: ~20ms overhead на сигнал (незаметно)
```

### API лимиты:
```
Binance:
- Order Book: 10 weight
- Лимит: 2400 weight/min
- Кэш 30с → макс 2 запроса/мин = 20 weight/min
- Запас: 2400 / 20 = 120x

Bybit:
- Order Book: 1 weight
- Лимит: 120 weight/min
- Кэш 30с → макс 2 запроса/мин = 2 weight/min
- Запас: 120 / 2 = 60x

Вывод: API лимиты не проблема
```

---

## 🔄 Жизненный цикл данных

```
Старт бота
    │
    ├─── Загрузка кэша (OI, Price, Trades)
    │
    ├─── Подключение WebSocket (Price, Tickers)
    │
    └─── Запуск polling (OI, Funding)
         │
         ▼
    Накопление данных (2-3 минуты)
         │
         ▼
    Screener обнаружил OI >= 3%
         │
         ├─── CVD tracker: start_watch()
         │    └─── WebSocket на торговый поток
         │         └─── Footprint накапливается
         │
         └─── Screener обнаружил OI >= 5%
              │
              ▼
         Агрегатор проверяет сигнал
              │
              ├─── Базовые факторы (OI, цена, funding, CVD, liq, L/S)
              ├─── Footprint bias (НОВОЕ)
              ├─── Order Book стенки (НОВОЕ)
              └─── Volume Profile зоны (НОВОЕ)
                   │
                   ▼
              Скоринг >= порога?
                   │
                   ├─── Да → Отправка сигнала в Telegram
                   │         └─── Trade tracker: add_trade()
                   │
                   └─── Нет → Пропуск
         │
         ▼
    Через CVD_TIMEOUT (30 мин) без сигнала
         │
         └─── CVD tracker: stop_watch()
              └─── Отписка от торгового потока
                   └─── Footprint очищается
```

---

**Конец архитектурной документации**

Все потоки данных задокументированы! 🎉
