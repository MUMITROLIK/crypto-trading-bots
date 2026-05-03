# Новые фичи OI Bot

## 📊 Order Book Analysis (orderbook.py)

**Что делает:**
- Запрашивает топ-20 уровней стакана с Binance/Bybit
- Находит крупные стенки (ордера в 3x больше среднего и >= $8K)
- Кэширует на 30 секунд (не спамим API)

**Использование в агрегаторе:**
- **Стенка продаж** выше цены (0-4%) → сопротивление → +1 балл SHORT
- **Стенка покупок** ниже цены (-4-0%) → поддержка → +1 балл LONG

**API:**
```python
walls = await orderbook.get_walls(exchange, symbol, current_price)
# Результат:
# {
#   "ask_walls": [{"price": float, "usd": float, "pct": float}, ...],
#   "bid_walls": [{"price": float, "usd": float, "pct": float}, ...]
# }
```

---

## 📈 Volume Profile (orderbook.py)

**Что делает:**
- Анализирует price_history (тысячи точек за 2 часа)
- Находит уровни где цена "тусовалась" дольше всего
- Аппроксимация настоящего volume profile (время ≈ объём)

**Использование:**
- Показывает 3 ключевых уровня поддержки/сопротивления
- Трейдер использует для выбора точек входа/выхода

**API:**
```python
zones = orderbook.get_volume_zones(price_hist, n=3)
# Результат: [price1, price2, price3]
```

---

## 👣 Footprint (data_store.py)

**Что делает:**
- Группирует торговые потоки по ценовым уровням (bucket ~0.2%)
- Считает дельту покупок/продаж на каждом уровне
- Показывает где доминируют покупатели/продавцы

**Использование в агрегаторе:**
- **Footprint > $1K** (покупатели) → +1 балл LONG
- **Footprint < -$1K** (продавцы) → +1 балл SHORT

**API:**
```python
# Полный footprint (все уровни в ±1.5% от цены)
fp = data_store.get_footprint(exchange, symbol, current_price, window_sec=300)
# Результат: {bucket_price: {"buy": $, "sell": $, "delta": $, "pct": %}}

# Суммарная дельта (быстрый вариант)
bias = data_store.get_footprint_bias(exchange, symbol, current_price)
# Результат: float (+ = покупатели, - = продавцы)
```

---

## 🔄 Интеграция

### cvd_tracker.py
Обновлён для передачи цены в `data_store.add_trade()`:
```python
data_store.add_trade("binance", symbol, qty, is_buy, price)
```

### data_store.py
Добавлены новые функции:
- `_price_bucket(price)` — округление до 3 значимых цифр
- `_record_footprint()` — запись сделки в footprint поток
- `get_footprint()` — получение дельты по уровням
- `get_footprint_bias()` — суммарная дельта

### aggregator.py
Добавлены в скоринг:
- Footprint bias (±1 балл)
- Order Book стенки (±1 балл)
- Volume Profile зоны (отображение в сообщении)

---

## 📱 Формат сообщения

Пример SHORT сигнала:
```
🎯 АГРЕГАТОР — 🔴 SHORT
Binance – BTCUSDT
Уверенность: 8/10  ████████░░

  ✅ Памп 1ч +12.3%
  ✅ OI +4.2% в боковике после пампа 1ч
  ✅ L/S: 68% лонгов (толпа в лонгах)
  ✅ Funding +0.0823% (лонги переплачивают)
  ✅ CVD -15000 (продавцы)
  ✅ Footprint: продавцы $12.5K на уровне
  ✅ Стенка продаж +2.3% ($45K)

👥 Лонгов: 68%
🔴 Funding: +0.0823%
💥 LONG лики: $125K за 5м
📈 CVD: -15000 ↓
🔴 Footprint: продавцы $12.5K
🧱 Стенка продаж: 67,850 (+2.3%, $45K)
📊 Volume зоны: 66,200 / 67,100 / 68,500
💵 OI: $2.3B
📊 Сигнал #3 за сутки

📍 Вход: 67,450
🛑 SL:  69,520 (-3.1%)
🎯 TP1: 65,980 (+2.2%)
🎯 TP2: 64,510 (+4.4%)
🏆 TP3: 61,570 (+8.7%)
⏰ 16:05 UTC
```

---

## ⚡ Производительность

- **Order Book:** кэш 30с, один запрос на символ
- **Footprint:** in-memory, deque maxlen=5000 (~1ч данных)
- **Volume Profile:** вычисляется на лету из price_history
- **Overhead:** минимальный, все данные уже собираются для CVD

---

## 🎯 Итоговый скоринг

**SHORT (макс 21 балл):**
- OI/Цена/Funding/CVD/Liq/L/S: до 19 баллов (как было)
- Footprint: +1 балл
- Order Book стенка: +1 балл

**LONG (макс 16 баллов):**
- OI/Цена/CVD/Liq/L/S: до 14 баллов (как было)
- Footprint: +1 балл
- Order Book стенка: +1 балл

Пороги остались прежними:
- `AGG_LONG_MIN_SCORE = 7`
- `AGG_SHORT_MIN_SCORE = 10`
