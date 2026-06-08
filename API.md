# API Documentation

## 1. Список беседок — bilet.mos.ru

### Endpoint
```
GET https://bilet.mos.ru/api/newsfeed/v4/frontend/json/ru/afisha
```

### Query Parameters

| Параметр | Значение | Описание |
|----------|----------|----------|
| `expand` | `spheres,spots,foundation` | Включить связанные объекты |
| `fields` | `id,title,date,date_from,date_to,ebs_id,ebs_type,ebs_agent_uid,ebs_has_available_seats,ebs_price_from` | Поля ответа |
| `filter` | JSON (см. ниже) | Фильтрация |
| `per-page` | `50` | Результатов на страницу (макс. 50) |
| `page` | `1,2,...` | Номер страницы |
| `sort` | `occurrences.date_from` | Сортировка |

### Фильтр (JSON-строка)

```json
{
  "&": {
    "=spheres.id": ["472299"]
  },
  "can_attend": 1,
  ">=occurrences.date_to": "2026-06-14 00:00:00",
  "<=occurrences.date_from": "2026-06-14 23:59:59",
  "<=ebs_price_from": 10000
}
```

- `472299` — sphere ID для «Бронирование беседок»
- Фильтры по дате опциональны

### Пагинация (заголовки ответа)

```
X-Pagination-Total-Count: 157
X-Pagination-Page-Count: 4
X-Pagination-Current-Page: 1
X-Pagination-Per-Page: 50
```

### Объект беседки (item)

```json
{
  "id": 310918257,
  "title": "Зона для пикника № 21",
  "date_from": "2026-06-08 14:00:00",
  "date_to": "2026-09-30 22:00:00",
  "date": "2026-06-08 14:00:00",
  "ebs_id": 43616,
  "ebs_type": "event",
  "ebs_agent_uid": "museum10",
  "ebs_has_available_seats": 1,
  "ebs_price_from": 0,
  "spheres": [
    { "id": 472299, "title": "Бронирование беседок" }
  ],
  "spots": [
    {
      "id": 9449210,
      "title": "Беседка № 21",
      "address": "Лесопарк «Кусково»",
      "lon": "37.472286",
      "lat": "55.832759",
      "ebs_id": 296870
    }
  ],
  "foundation": {
    "id": 12228211,
    "title": "Лесопарк «Кусково»",
    "ebs_id": 1190,
    "ebs_agent_uid": "museum10",
    "address": "...",
    "phone": "+7 (499) 493-00-00"
  }
}
```

**Ключевые поля:**
- `ebs_id` — ID события в системе EBS (нужен для запроса слотов)
- `ebs_agent_uid` — ID агента в EBS (нужен для запроса слотов)
- `foundation.title` — название парка/зоны (используется для фильтрации по зоне)
- `ebs_has_available_seats` — 1 если есть свободные места в принципе

---

## 2. Слоты бронирования — tickets.mos.ru

### Endpoint
```
GET https://tickets.mos.ru/api/widget/v2/event/{ebs_id}/performances
```

### Path Parameters
- `ebs_id` — из поля `ebs_id` беседки (например `43616`)

### Query Parameters

| Параметр | Пример | Описание |
|----------|--------|----------|
| `date_from` | `2026-06-23` | Начальная дата (YYYY-MM-DD) |
| `date_to` | `` | Конечная дата (пусто = авто) |
| `performances_limit_by_days` | `14` | Кол-во дней вперёд |
| `agent_id` | `museum10` | `ebs_agent_uid` беседки |

### Пример запроса
```
GET https://tickets.mos.ru/api/widget/v2/event/43616/performances
    ?date_from=2026-06-23
    &date_to=
    &performances_limit_by_days=14
    &agent_id=museum10
```

### Ответ — массив дней

```json
[
  {
    "date": "2026-06-23",
    "is_holiday": false,
    "performances": [
      {
        "id": 43617469,
        "event_id": 43616,
        "tariff_id": 101054,
        "name": "Бронирование беседки в лесопарке «Кусково» №21",
        "start_datetime": "2026-06-23T10:00:00",
        "end_datetime": "2026-06-23T14:00:00",
        "max_visitors": 1,
        "max_performance_price": 1000.0,
        "min_performance_price": 1000.0,
        "free_seats_count": 1,
        "is_display_end_time": false,
        "discount_exists": null
      }
    ]
  }
]
```

**Ключевые поля слота:**
- `start_datetime` / `end_datetime` — временной диапазон бронирования
- `free_seats_count` — количество свободных мест (0 = занято)
- `min_performance_price` / `max_performance_price` — цена в рублях (0 = бесплатно)
- `is_holiday` — признак выходного дня

---

## Схема использования

```
1. GET /api/newsfeed/v4/.../afisha
       ?filter={"=spheres.id":["472299"],"can_attend":1}
       → список беседок (157 штук, ~4 страницы по 50)
       → фильтруем по foundation.title нужных парков

2. Для каждой беседки:
   GET tickets.mos.ru/api/widget/v2/event/{ebs_id}/performances
       ?date_from=...&performances_limit_by_days=14&agent_id={ebs_agent_uid}
       → слоты по дням, смотрим free_seats_count > 0
```

---

## Настройки запросов

```python
# Обходим корпоративный прокси
HTTPS_PROXY = ""   # или proxies={"https": ""} в requests.Session
```
