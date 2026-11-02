# Журнал провенанса профилей

Сгенерирован `profiles/build_profile.py`, руками не правится. Не бюджетируется и агенту не выдаётся
(контракт — `spec/10-spec-assembly/00-profile-contract.md` §9.2). История, марки амендментов и адресаты
деферралов живут здесь, а не в профилях.

## Оговорки

- Перепись корпуса: числа переписи в профили не идут никогда; частичная воспроизводимость
  переписи — предмет этого журнала, не профиля.
- Токенизатор: бюджеты меряются кодировкой cl100k_base (tiktoken, версия — в манифесте пиннинга).
  cl100k недосчитывает кириллицу для токенизатора Claude на 20–40 %: числа сопоставимы между собой,
  но не «родные».

## Профиль `hours` — часы

### Блок `wp-aon-who` — `10-spec-assembly/03-agent-identity.md:49`

- покрывает: `10-spec-assembly/03-agent-identity.md#Кто человек`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 2026-10-03, решение alex по находкам paste-приёмки T6: агент, проверяя игнор `me.yaml`, грепал»; «[АМЕНДМЕНТ D10 2026-10-28, решение alex по decide d10-f-me-skip: вариант (г) — частичный откат»; «[АМЕНДМЕНТ D10 T25 2026-10-18,»

### Блок `wp-kernel-record-file` — `01-spec-kernel/spec-kernel.md:89`

- покрывает: `01-spec-kernel/spec-kernel.md#1. Физическая форма файла записи`; `01-spec-kernel/spec-kernel.md#2. Конверт: правила разбора`; `01-spec-kernel/spec-kernel.md#3. Идентичность: два слоя`; `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/spec-kernel.md#02.2.1 Полная форма: ISO-8601 UTC с Z`; `01-spec-kernel/spec-kernel.md#02.2.2 Дата-форма: YYYY-MM-DD`; `01-spec-kernel/spec-kernel.md#02.2.3 Время в свободной прозе`; `01-spec-kernel/envelope-fields.yaml#file_form`; `01-spec-kernel/envelope-fields.yaml#unknown_keys`; `01-spec-kernel/envelope-fields.yaml#fields[name=id]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=created]`; `01-spec-kernel/envelope-fields.yaml#fields[name=author]`; `01-spec-kernel/envelope-fields.yaml#fields[name=title]`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-namespace` — `01-spec-kernel/spec-kernel.md:411`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/envelope-fields.yaml#fields[name=namespace]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»

### Блок `wp-kernel-links` — `01-spec-kernel/spec-kernel.md:910`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`; `01-spec-kernel/spec-kernel.md#02.1.1 Тикетная ссылка `[[<label>]]``; `01-spec-kernel/spec-kernel.md#02.1.2 Упоминания: что ссылкой НЕ является`; `01-spec-kernel/spec-kernel.md#02.1.3 Кросс-репо и кросс-тип: голый текст`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «ок, берём А», Q2 суда T22 D10:»

### Блок `wp-kernel-timesheet-file` — `01-spec-kernel/spec-kernel.md:1336`

- покрывает: `01-spec-kernel/spec-kernel.md#03.3.4 Контейнер времени (`type: TIMESHEET`)`; `01-spec-kernel/spec-kernel.md#03.3.2 Общий контейнерный минимум`; `01-spec-kernel/spec-kernel.md#03.3.5 Конверт контейнера пишется один раз`; `01-spec-kernel/spec-kernel.md#03.5.4 Атрибуция`; `01-spec-kernel/line-forms.yaml#containers.common`; `01-spec-kernel/line-forms.yaml#containers.timesheet`; `01-spec-kernel/envelope-fields.yaml#aggregate_on_container`; `01-spec-kernel/envelope-fields.yaml#filename.per_type.TIMESHEET`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `04-spec-time-model/spec-time-model.md#1.1 Решение`; `04-spec-time-model/spec-time-model.md#1.2 Отношение к остальной раскладке`; `04-spec-time-model/spec-time-model.md#2.1 Грамматика`; `04-spec-time-model/spec-time-model.md#2.7 Что в имени проверяется, а что нет`; `04-spec-time-model/spec-time-model.md#3.1 Правило`; `04-spec-time-model/spec-time-model.md#4.2 Период конверта = календарный месяц имени, и это привязывает РАСКЛАДКА`; `04-spec-time-model/spec-time-model.md#4.3 Маршрутизация аппенда: что делает писатель`; `04-spec-time-model/spec-time-model.md#5.1 Авторитет — конверт`; `04-spec-time-model/spec-time-model.md#5.2 Форма id в имени`; `04-spec-time-model/spec-time-model.md#5. Атрибуция: person в конверте, автор коммита — транспорт`; `04-spec-time-model/spec-time-model.md#1.3 Носитель 1 — поле конверта`; `04-spec-time-model/spec-time-model.md#1.5 Носитель 3 — счётчик в имени файла`; `04-spec-time-model/time-model.yaml#layout`; `04-spec-time-model/time-model.yaml#filename`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `04-spec-time-model/spec-time-model.md#2.4 Коллизия с `filename.grammar` ядра — обе стороны дословно` (history); `04-spec-time-model/spec-time-model.md#2.6 Исход: заявка, а не самообъявленное исключение` (history); `04-spec-time-model/spec-time-model.md#3.3 Передача главе политики мульти-писателя` (boundary); `04-spec-time-model/spec-time-model.md#6. Границы: что здесь НЕ решено и где дом` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03, REQ-121: прежняя буква «нигде в спеке»

### Блок `wp-kernel-daily-line` — `01-spec-kernel/spec-kernel.md:1531`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.1 Грамматика`; `01-spec-kernel/spec-kernel.md#03.2.1 Строение строки`; `01-spec-kernel/spec-kernel.md#03.2.2 Разделители: канон и приёмка`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`; `01-spec-kernel/spec-kernel.md#03.2.4 Строки-продолжения — DECISION-03-02`; `01-spec-kernel/line-forms.yaml#line_form_model`; `01-spec-kernel/line-forms.yaml#continuation`; `01-spec-kernel/line-forms.yaml#forms.daily_time_v1`; `01-spec-kernel/line-forms.yaml#time_line_anchor`; `04-spec-time-model/spec-time-model.md#6. ПРОЕКТНЫЙ РАЗРЕЗ: решение НЕ заводить`; `04-spec-time-model/spec-time-model.md#3.3 Отсюда — почему якорь становится ОБЯЗАННОСТЬЮ машинного продюсера (П5)`; `04-spec-time-model/spec-time-model.md#3.4 Согласование с идемпотентностью бота`; `04-spec-time-model/spec-time-model.md#4. Нормализация ЧЧ:ММ → десятичные: чья обязанность и с какой точностью`; `04-spec-time-model/spec-time-model.md#4.1 Правило Н1 — единственное правило округления`; `04-spec-time-model/spec-time-model.md#4.2 Почему Н1 сформулировано на целых секундах, а не на дробных числах`; `04-spec-time-model/spec-time-model.md#4.3 Кто нормализует и когда`; `04-spec-time-model/spec-time-model.md#4.4 Рукописная строка: ЧЧ:ММ не примет валидатор`; `04-spec-time-model/spec-time-model.md#4.5 Края правила`; `04-spec-time-model/time-model.yaml#line_inheritance`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `01-spec-kernel/line-forms.yaml#boundaries` (boundary); `04-spec-time-model/spec-time-model.md#8. Заявки` (history); `04-spec-time-model/spec-time-model.md#9. Контракты другим главам и деливераблам` (boundary); `04-spec-time-model/spec-time-model.md#6. Границы: что здесь НЕ решено и где дом` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («4-а»), заявка D04-ANCHOR-04 —»

### Блок `wp-kernel-backfill` — `01-spec-kernel/spec-kernel.md:1552`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.2 Запись задним числом`; `01-spec-kernel/spec-kernel.md#03.2.5 Порядок строк и пустые строки`; `01-spec-kernel/spec-kernel.md#03.1.4 Идентичность, версия, sync-readiness`; `01-spec-kernel/spec-kernel.md#03.1.3 Неизменяемость и исправления`; `01-spec-kernel/spec-kernel.md#03.6.3 Что НИКОГДА не является ошибкой`; `04-spec-time-model/spec-time-model.md#4.4 `DATE_OUTSIDE_PERIOD` получает точный смысл`; `04-spec-time-model/spec-time-model.md#1.1 Норма`; `04-spec-time-model/spec-time-model.md#1.2 Предикат: что такое «носитель итога»`; `04-spec-time-model/spec-time-model.md#1.4 Носитель 2 — итоговая строка в теле`; `04-spec-time-model/spec-time-model.md#1.6 Что носителем НЕ является — границы правила, названные явно`; `04-spec-time-model/time-model.yaml#aggregation`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-midnight` — `01-spec-kernel/spec-kernel.md:1584`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.3 Полночь: что делает ГРАММАТИКА (именованный контракт MIDNIGHT-CUT → D04)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-line-validator` — `01-spec-kernel/spec-kernel.md:1640`

- покрывает: `01-spec-kernel/spec-kernel.md#03.6.1 Два режима, и это не смягчение, а разные вопросы`; `01-spec-kernel/spec-kernel.md#9. Валидатор`; `01-spec-kernel/line-forms.yaml#validator`
- история и границы тех же предков: `01-spec-kernel/line-forms.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comments-file` — `01-spec-kernel/spec-kernel.md:1719`

- покрывает: `01-spec-kernel/spec-kernel.md#04.1 Раскладка: комменты живут в файле-соседе (DECISION-1)`; `01-spec-kernel/spec-kernel.md#04.2.1 Конверта нет, заголовок — одна детерминированная строка`; `01-spec-kernel/spec-kernel.md#04.2.2 Связь с записью`; `01-spec-kernel/spec-kernel.md#04.2.3 Правило существования: ленивое создание`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.1.2 Склонность alex — названа и опрокинута эмпирикой` (history); `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comment-grammar` — `01-spec-kernel/spec-kernel.md:1869`

- покрывает: `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`; `01-spec-kernel/spec-kernel.md#04.3.2 Атрибуция — в содержимом, и только там`; `01-spec-kernel/spec-kernel.md#04.3.3 Собственный id коммента (DECISION-3)`; `01-spec-kernel/spec-kernel.md#04.3.4 Что проверяет валидатор (D05)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[Сужение области»

### Блок `wp-kernel-comment-append` — `01-spec-kernel/spec-kernel.md:1954`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4 Порядок: в файле не нормативен, канон восстанавливает читатель (DECISION-4)`; `01-spec-kernel/spec-kernel.md#04.6 Комменты и `version` (правило главы 01, обоснованное экспериментально)`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`; `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-comment-timesheet` — `01-spec-kernel/spec-kernel.md:1984`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4.2 Комменты к строкам времени (амендмент alex, ревью D01)`; `04-spec-time-model/spec-time-model.md#4.2 Инвариант Ч — часы живут ТОЛЬКО в табеле`; `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`
- история и границы тех же предков: `04-spec-time-model/spec-time-model.md#4.3 ЗАЯВКА D04-CORR-07 — разрешить отзыв дневной строки` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-kernel-corrections` — `01-spec-kernel/spec-kernel.md:2028`

- покрывает: `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#03.1.3 Неизменяемость и исправления`; `04-spec-time-model/spec-time-model.md#05 — Политика исправлений записанных часов`; `04-spec-time-model/spec-time-model.md#0.2 Отклонённый кандидат: правка строки на месте`; `04-spec-time-model/spec-time-model.md#1.1 Недобор: дозапись обычным аппендом, политика не нужна`; `04-spec-time-model/spec-time-model.md#1.2 Перебор: записанный факт обязан перестать считаться — это и есть предмет главы`; `04-spec-time-model/spec-time-model.md#1.3 Неверная дата = перебор плюс недобор, и иногда это ДВА файла`; `04-spec-time-model/spec-time-model.md#1.4 Исправление приходит ПОЗДНО, и месяц никогда не «закрыт»`; `04-spec-time-model/spec-time-model.md#4.1 Правило И-БАЗА — нормативно СЕГОДНЯ, без единого амендмента`; `04-spec-time-model/spec-time-model.md#4.4 Строки БЕЗ якоря: что делает исправляющий и сколько это стоит`; `04-spec-time-model/spec-time-model.md#6.2 Идемпотентность отзыва по цели`; `04-spec-time-model/time-model.yaml#corrections`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary); `04-spec-time-model/spec-time-model.md#02 — Политика мульти-писателя time-файла (REQ-072)` (history); `04-spec-time-model/spec-time-model.md#0.3 Что глава решает, чего НЕ трогает — с адресатом у каждого пункта` (boundary); `04-spec-time-model/spec-time-model.md#0.4 Долги предыдущих глав, которые эта глава ОБЯЗАНА погасить` (history); `04-spec-time-model/spec-time-model.md#4.3 ЗАЯВКА D04-CORR-07 — разрешить отзыв дневной строки` (history); `04-spec-time-model/spec-time-model.md#Ситуация` (history); `04-spec-time-model/spec-time-model.md#Выбор` (history); `04-spec-time-model/spec-time-model.md#Рекомендация` (history); `04-spec-time-model/spec-time-model.md#Часть А — предлагаемая редакция` (history); `04-spec-time-model/spec-time-model.md#Часть Б — что обязан делать индекс при принятии` (history); `04-spec-time-model/spec-time-model.md#Часть В — обязательные регрессии при принятии (кандидаты в фикстуры D06)` (history); `04-spec-time-model/spec-time-model.md#8. Границы — по конкретному предложению на соседа` (boundary); `04-spec-time-model/spec-time-model.md#9. Заявки` (history); `04-spec-time-model/spec-time-model.md#9.1 Вынесена: D04-CORR-07 — отзыв дневной строки (`retracts:t:<id>`)` (history); `04-spec-time-model/spec-time-model.md#9.2 Усилены существующие заявки — новых по ним не вносится` (history); `04-spec-time-model/spec-time-model.md#9.3 НЕ вынесены — с основанием` (history); `04-spec-time-model/spec-time-model.md#10. Выход для alex — материал приёмочного пакета` (history); `04-spec-time-model/spec-time-model.md#Вопрос 1 — как исправлять уже записанные часы` (history); `04-spec-time-model/spec-time-model.md#Вопрос 2 — разрешить «вычеркнуть» ошибочную запись, чтобы она перестала считаться` (history); `04-spec-time-model/spec-time-model.md#Вопрос 3 — мелкое: нужен ли след исправления в журнале событий` (history); `04-spec-time-model/spec-time-model.md#Вопрос 4 — мелкое: исправление через бота в первой версии не работает` (history); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-gitattributes` — `01-spec-kernel/spec-kernel.md:2078`

- покрывает: `01-spec-kernel/spec-kernel.md#04.7.1 Строка и кто её приносит`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-lang-secrets` — `01-spec-kernel/spec-kernel.md:2364`

- покрывает: `01-spec-kernel/spec-kernel.md#05.3.2 Что требует спека`; `01-spec-kernel/spec-kernel.md#05.1.1 Правило`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-time-git-discipline` — `04-spec-time-model/spec-time-model.md:1247`

- покрывает: `04-spec-time-model/spec-time-model.md#2.1 Дисциплина писателя: П1–П7, одинаково для бота, фронтов и рук`; `04-spec-time-model/spec-time-model.md#2.2 Правило Р1 — машинное разрешение конфликта хвостовых аппендов`; `04-spec-time-model/spec-time-model.md#2.5 Роль «ПРАВКА РУКАМИ» (редактор + обычный git, чужой ИИ)`; `04-spec-time-model/spec-time-model.md#3.2 Правило Т — тождество только по якорю`; `04-spec-time-model/spec-time-model.md#4.4 Порядок восстанавливается ЧТЕНИЕМ. Чинить файл ЗАПРЕЩЕНО`; `04-spec-time-model/spec-time-model.md#6.1 Исправление — ещё один аппенд, и вся дисциплина применяется без изменений`; `04-spec-time-model/time-model.yaml#multi_writer`
- история и границы тех же предков: `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: —

### Блок `wp-validator-forms` — `05-validator-core/01-invocation-interface.md:440`

- покрывает: `05-validator-core/01-invocation-interface.md#2.8 Какую форму зовёт писатель записи перед коммитом`; `05-validator-core/01-invocation-interface.md#3.1 Пять исходов, из них четыре обязательных и один отдельный`; `05-validator-core/validator-interface.yaml#return_codes`
- история и границы тех же предков: `05-validator-core/validator-interface.yaml#verdicts_as_inputs` (history); `05-validator-core/validator-interface.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-aon-machine-writer` — `10-spec-assembly/02-agent-operational-norm.md:19`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#1. Агент — машинный писатель`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-when` — `10-spec-assembly/02-agent-operational-norm.md:42`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#3. Когда писать и когда спрашивать`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate` — `10-spec-assembly/02-agent-operational-norm.md:63`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-pair` — `10-spec-assembly/02-agent-operational-norm.md:71`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit` — `10-spec-assembly/02-agent-operational-norm.md:88`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-comment-time` — `10-spec-assembly/02-agent-operational-norm.md:102`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#6. Время заголовка коммента`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-read-once` — `10-spec-assembly/02-agent-operational-norm.md:119`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#7. Чтение профиля`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ROUTE-GREP (decide D-B п. 4) — агент Sonnet искал»

### Блок `wp-aon-secrets` — `10-spec-assembly/02-agent-operational-norm.md:130`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#8. Секреты`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

## Профиль `tickets` — тикеты

### Блок `wp-aon-who` — `10-spec-assembly/03-agent-identity.md:49`

- покрывает: `10-spec-assembly/03-agent-identity.md#Кто человек`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 2026-10-03, решение alex по находкам paste-приёмки T6: агент, проверяя игнор `me.yaml`, грепал»; «[АМЕНДМЕНТ D10 2026-10-28, решение alex по decide d10-f-me-skip: вариант (г) — частичный откат»; «[АМЕНДМЕНТ D10 T25 2026-10-18,»

### Блок `wp-kernel-record-file` — `01-spec-kernel/spec-kernel.md:89`

- покрывает: `01-spec-kernel/spec-kernel.md#1. Физическая форма файла записи`; `01-spec-kernel/spec-kernel.md#2. Конверт: правила разбора`; `01-spec-kernel/spec-kernel.md#3. Идентичность: два слоя`; `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/spec-kernel.md#02.2.1 Полная форма: ISO-8601 UTC с Z`; `01-spec-kernel/spec-kernel.md#02.2.2 Дата-форма: YYYY-MM-DD`; `01-spec-kernel/spec-kernel.md#02.2.3 Время в свободной прозе`; `01-spec-kernel/envelope-fields.yaml#file_form`; `01-spec-kernel/envelope-fields.yaml#unknown_keys`; `01-spec-kernel/envelope-fields.yaml#fields[name=id]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=created]`; `01-spec-kernel/envelope-fields.yaml#fields[name=author]`; `01-spec-kernel/envelope-fields.yaml#fields[name=title]`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-namespace` — `01-spec-kernel/spec-kernel.md:411`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/envelope-fields.yaml#fields[name=namespace]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»

### Блок `wp-kernel-filename-ticket` — `01-spec-kernel/spec-kernel.md:415`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/spec-kernel.md#4. Ярлык: детерминизм и реестр`; `01-spec-kernel/envelope-fields.yaml#filename`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»; «[АМЕНДМЕНТ alex 2026-08-25 («го» по заявке PENDING-LABEL-ENTROPY из D03, вариант б+а): x-форма»

### Блок `wp-kernel-path-ticket` — `01-spec-kernel/spec-kernel.md:485`

- покрывает: `01-spec-kernel/spec-kernel.md#5.7 Путь записи в репозитории`; `01-spec-kernel/envelope-fields.yaml#record_layout`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03 (REQ-121, решение «месяц + декада»): до него раскладка тикетов и документов в спеке не»; «[АМЕНДМЕНТ D10 2026-10-03, пересуд»

### Блок `wp-kernel-version-ticket` — `01-spec-kernel/spec-kernel.md:550`

- покрывает: `01-spec-kernel/spec-kernel.md#6. version`; `01-spec-kernel/envelope-fields.yaml#fields[name=version]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-ticket-lifecycle` — `01-spec-kernel/spec-kernel.md:759`

- покрывает: `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `01-spec-kernel/envelope-fields.yaml#fields[name=status]`; `01-spec-kernel/envelope-fields.yaml#fields[name=status_note]`; `01-spec-kernel/envelope-fields.yaml#fields[name=evidence]`; `01-spec-kernel/envelope-fields.yaml#fields[name=assignee]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=decided_by]`; `01-spec-kernel/envelope-fields.yaml#fields[name=awaiting]`; `01-spec-kernel/envelope-fields.yaml#ticket_card`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-links` — `01-spec-kernel/spec-kernel.md:910`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`; `01-spec-kernel/spec-kernel.md#02.1.1 Тикетная ссылка `[[<label>]]``; `01-spec-kernel/spec-kernel.md#02.1.2 Упоминания: что ссылкой НЕ является`; `01-spec-kernel/spec-kernel.md#02.1.3 Кросс-репо и кросс-тип: голый текст`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «ок, берём А», Q2 суда T22 D10:»

### Блок `wp-kernel-refs-ticket` — `01-spec-kernel/spec-kernel.md:981`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1.4 Артефакты, код, сессии: бэктики`; `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comments-file` — `01-spec-kernel/spec-kernel.md:1719`

- покрывает: `01-spec-kernel/spec-kernel.md#04.1 Раскладка: комменты живут в файле-соседе (DECISION-1)`; `01-spec-kernel/spec-kernel.md#04.2.1 Конверта нет, заголовок — одна детерминированная строка`; `01-spec-kernel/spec-kernel.md#04.2.2 Связь с записью`; `01-spec-kernel/spec-kernel.md#04.2.3 Правило существования: ленивое создание`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.1.2 Склонность alex — названа и опрокинута эмпирикой` (history); `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comment-grammar` — `01-spec-kernel/spec-kernel.md:1869`

- покрывает: `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`; `01-spec-kernel/spec-kernel.md#04.3.2 Атрибуция — в содержимом, и только там`; `01-spec-kernel/spec-kernel.md#04.3.3 Собственный id коммента (DECISION-3)`; `01-spec-kernel/spec-kernel.md#04.3.4 Что проверяет валидатор (D05)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[Сужение области»

### Блок `wp-kernel-comment-append` — `01-spec-kernel/spec-kernel.md:1954`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4 Порядок: в файле не нормативен, канон восстанавливает читатель (DECISION-4)`; `01-spec-kernel/spec-kernel.md#04.6 Комменты и `version` (правило главы 01, обоснованное экспериментально)`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`; `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-gitattributes` — `01-spec-kernel/spec-kernel.md:2078`

- покрывает: `01-spec-kernel/spec-kernel.md#04.7.1 Строка и кто её приносит`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-lang-secrets` — `01-spec-kernel/spec-kernel.md:2364`

- покрывает: `01-spec-kernel/spec-kernel.md#05.3.2 Что требует спека`; `01-spec-kernel/spec-kernel.md#05.1.1 Правило`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-forms` — `03-spec-type-schemas/spec-type-schemas.md:1066`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Класс записи и поля жизненного цикла`; `03-spec-type-schemas/spec-type-schemas.md#1.1 Определение и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#2.1 Что это и в каком состоянии корпус`; `03-spec-type-schemas/spec-type-schemas.md#9.1 Определение и граница с соседями`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-sections` — `03-spec-type-schemas/spec-type-schemas.md:1117`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.3 Потолок секционной нормы: почему обязательная секция не может быть ERROR'ом`; `03-spec-type-schemas/section-ids.yaml#kernel_section_ids`; `03-spec-type-schemas/section-ids.yaml#introduced_by_ticket_forms`; `03-spec-type-schemas/section-ids.yaml#introduced_by_repo_type_extension`; `03-spec-type-schemas/section-ids.yaml#introduced_by_kernel_v2`; `03-spec-type-schemas/section-ids.yaml#section_anchor`; `03-spec-type-schemas/ticket-fields.yaml#rules`; `06-conformance-full/00-scope-coverage-and-dispositions.md#3.1 REQ-026 — исход (i): машинный носитель секции. АМЕНДМЕНТ-D06-01`; `03-spec-type-schemas/section-ids.yaml#normativity`; `01-spec-kernel/spec-kernel.md#05.1.3 Секции тела: семантические id, не литералы`; `01-spec-kernel/spec-kernel.md#8. DECISION-03 — судьба ключей Origin / Filed / Code`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/ticket-fields.yaml#not_validated` (boundary); `03-spec-type-schemas/ticket-fields.yaml#rules.kernel_grammars_not_redefined` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-relations` — `03-spec-type-schemas/spec-type-schemas.md:1168`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.5 Отношения — по id реестра; правило имени поля-носителя`; `03-spec-type-schemas/spec-type-schemas.md#1.9 Отношения TASK`; `03-spec-type-schemas/spec-type-schemas.md#2.4 Отношения ISSUE`; `03-spec-type-schemas/spec-type-schemas.md#2.2 Форма 02.1.2 — что ссылкой НЕ является`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Три кандидата и почему выбран третий`; `03-spec-type-schemas/spec-type-schemas.md#3.2 Внутренняя цель против внешней — два носителя, одно правило`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#4.3 «Двусторонняя ссылка» REQ-080 — требование к ЧТЕНИЮ, не к хранению (решение alex 2026-08-23)`; `03-spec-type-schemas/spec-type-schemas.md#5.1 Пояснения, которых таблица не вмещает`; `03-spec-type-schemas/spec-type-schemas.md#6. Правило закрытия контейнера работы (механизм для REQ-080)`; `03-spec-type-schemas/relations.yaml#rules`; `03-spec-type-schemas/relations.yaml#link_forms`; `03-spec-type-schemas/relations.yaml#relations`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#6.4 Перечисление в свидетельстве завершения — что формат может и чего не может` (boundary); `03-spec-type-schemas/spec-type-schemas.md#7. Заявки к alex — все закрыты` (history); `03-spec-type-schemas/spec-type-schemas.md#8. Границы проверки — сводно` (boundary); `03-spec-type-schemas/relations.yaml#out_of_registry` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-task` — `03-spec-type-schemas/spec-type-schemas.md:1251`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.2 Стадия — статусом ядра`; `03-spec-type-schemas/spec-type-schemas.md#1.3 Роли: автор, исполнитель, чей ход, кто решает`; `03-spec-type-schemas/spec-type-schemas.md#1.4 Вид и метки`; `03-spec-type-schemas/spec-type-schemas.md#1.7 Тело`; `03-spec-type-schemas/spec-type-schemas.md#1.8 `fixed_in` — где выдан результат`; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`; `03-spec-type-schemas/ticket-fields.yaml#shared_fields`
- история и границы тех же предков: `03-spec-type-schemas/ticket-fields.yaml#not_validated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-task-design` — `03-spec-type-schemas/spec-type-schemas.md:1336`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.5 Вид `design``; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-task-hotfix` — `03-spec-type-schemas/spec-type-schemas.md:1426`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.6 Режим hotfix — срочная точечная правка`; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-issue` — `03-spec-type-schemas/spec-type-schemas.md:1633`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.2 Поля ISSUE`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Статус: «снят» — не удаление`; `03-spec-type-schemas/spec-type-schemas.md#2.5 Скелет тела ISSUE`; `03-spec-type-schemas/ticket-fields.yaml#types.ISSUE`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ REQ-109 (вердикт alex Q9, судейство decide-common-fields, 2026-09-19; внесено D10 T2»

### Блок `wp-incident` — `03-spec-type-schemas/spec-type-schemas.md:1782`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#3.2 Поля шапки`; `03-spec-type-schemas/spec-type-schemas.md#3.3 Раскладка dual-clock и длительности — ПОФИЛЬДНО`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Латентная длительность — ПРОЗА, не поле (вердикт alex 2026-08-25)`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Скелет тела INCIDENT`; `03-spec-type-schemas/spec-type-schemas.md#3.6 «Что не восстановлено» — секция, которой нет ни у одной другой формы`; `03-spec-type-schemas/spec-type-schemas.md#3.7 Таблица предотвращения, отношение INCIDENT → TASK и «мина по дороге»`; `03-spec-type-schemas/spec-type-schemas.md#3.8 Отношения и разобранный образец`; `03-spec-type-schemas/ticket-fields.yaml#types.INCIDENT`; `01-spec-kernel/spec-kernel.md#02.2.4 Единственное узаконенное исключение: dual-clock шапки INCIDENT`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-epic` — `03-spec-type-schemas/spec-type-schemas.md:2036`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#4.2 Поля EPIC`; `03-spec-type-schemas/spec-type-schemas.md#4.4 Тело EPIC — обязательно, и это проверяется механически`; `03-spec-type-schemas/spec-type-schemas.md#4.5 Ничего счётного — механическая приёмка`; `03-spec-type-schemas/spec-type-schemas.md#4.6 EPIC как контейнер ранней стадии`; `03-spec-type-schemas/ticket-fields.yaml#types.EPIC`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-request-origin-pii` — `03-spec-type-schemas/spec-type-schemas.md:2372`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.2 Персональные данные — правило типа`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-att-path` — `03-spec-type-schemas/spec-type-schemas.md:4211`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Вложения комментов`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Грамматика`; `03-spec-type-schemas/spec-type-schemas.md#3.3 ASCII: правило и его измеренная причина`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Куда девается исходное имя`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Длина пути`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Две легальные формы, и они не конкурируют`; `03-spec-type-schemas/attachments.yaml#layout`; `03-spec-type-schemas/attachments.yaml#owners`; `03-spec-type-schemas/attachments.yaml#filename`; `03-spec-type-schemas/attachments.yaml#link_forms`; `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#4.3 Что глава про ссылку НЕ говорит` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-att-commit` — `03-spec-type-schemas/spec-type-schemas.md:4595`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#5.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#2.6 Вложение неизменяемо`; `03-spec-type-schemas/spec-type-schemas.md#6.3 Маршрут: куда писатель кладёт файл`; `03-spec-type-schemas/spec-type-schemas.md#6.1 Два хранилища и только два`; `03-spec-type-schemas/spec-type-schemas.md#6.4 Материалы внешних людей`; `03-spec-type-schemas/spec-type-schemas.md#6.5 Несохранённый файл: пометка и ответ`; `03-spec-type-schemas/attachments.yaml#one_commit_invariant`; `03-spec-type-schemas/attachments.yaml#immutability`; `03-spec-type-schemas/attachments.yaml#soft_limit`; `03-spec-type-schemas/attachments.yaml#stores`; `03-spec-type-schemas/attachments.yaml#routing`; `03-spec-type-schemas/attachments.yaml#routing.external_origin`; `03-spec-type-schemas/attachments.yaml#unsaved`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#6.7 Что порогом СОЗНАТЕЛЬНО не задано` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary); `03-spec-type-schemas/attachments.yaml#soft_limit.cumulative_limits` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D20 T1: прежняя буква запрещала только движение пути; правка байт по месту»; «[АМЕНДМЕНТ D20 T1 2026-10-05: прежняя редакция заводила настройку заказчика `external_media`»

### Блок `wp-att-store` — `03-spec-type-schemas/spec-type-schemas.md:4963`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.1 Носитель: файл по пути вложения`; `03-spec-type-schemas/spec-type-schemas.md#9.3 Грамматика указателя`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Ключ объекта`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Состояния и законные переходы`; `03-spec-type-schemas/spec-type-schemas.md#9.9 Git LFS не поддерживается`; `03-spec-type-schemas/attachments.yaml#pointer`; `03-spec-type-schemas/attachments.yaml#object_key`; `03-spec-type-schemas/attachments.yaml#states`; `03-spec-type-schemas/attachments.yaml#lfs`
- история и границы тех же предков: `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-repo-types` — `03-spec-type-schemas/spec-type-schemas.md:5473`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Формула форм: разрешение напряжения с REQ-002`; `03-spec-type-schemas/spec-type-schemas.md#1.2 Сужение ядрового набора`; `03-spec-type-schemas/spec-type-schemas.md#4. Паттерн `x_proposed_*` — штатный, и это его единственный дом`; `03-spec-type-schemas/spec-type-schemas.md#14. Схема ядра 2: что меняется для писателя и для конфига`; `03-spec-type-schemas/spec-type-schemas.md#15. Коллизии конфига с ядром v2`; `03-spec-type-schemas/types-config-schema.yaml#kernel_block.types_enabled`; `03-spec-type-schemas/types-config-schema.yaml#proposed_pattern`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.2 Четыре дыры GAP-REPO-EXT-* — где закрыта каждая и где граница` (boundary); `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#5. Форма HOTFIX схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#6. Форма DESIGN схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#7. Сверка констант референс-валидатора (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#8. FIND — миграция вместо типа (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#10. Контракты, границы, трассируемость` (boundary); `03-spec-type-schemas/spec-type-schemas.md#11. Стандартная поставка TASK / REQUEST (этап 1) — история` (history); `03-spec-type-schemas/spec-type-schemas.md#12. TASK — переехал в ядро` (history); `03-spec-type-schemas/spec-type-schemas.md#13. REQUEST — переехал в ядро` (history); `03-spec-type-schemas/types-config-schema.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-validator-forms` — `05-validator-core/01-invocation-interface.md:440`

- покрывает: `05-validator-core/01-invocation-interface.md#2.8 Какую форму зовёт писатель записи перед коммитом`; `05-validator-core/01-invocation-interface.md#3.1 Пять исходов, из них четыре обязательных и один отдельный`; `05-validator-core/validator-interface.yaml#return_codes`
- история и границы тех же предков: `05-validator-core/validator-interface.yaml#verdicts_as_inputs` (history); `05-validator-core/validator-interface.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-aon-when` — `10-spec-assembly/02-agent-operational-norm.md:42`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#3. Когда писать и когда спрашивать`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate` — `10-spec-assembly/02-agent-operational-norm.md:63`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-pair` — `10-spec-assembly/02-agent-operational-norm.md:71`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit` — `10-spec-assembly/02-agent-operational-norm.md:88`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-comment-time` — `10-spec-assembly/02-agent-operational-norm.md:102`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#6. Время заголовка коммента`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-read-once` — `10-spec-assembly/02-agent-operational-norm.md:119`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#7. Чтение профиля`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ROUTE-GREP (decide D-B п. 4) — агент Sonnet искал»

### Блок `wp-aon-secrets` — `10-spec-assembly/02-agent-operational-norm.md:130`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#8. Секреты`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Деферралы профиля `tickets`

- `find` (предмет `ticket`): вердикт alex Q4 «б» 2026-09-20: FIND — репозиторное расширение, подрядчику не нужно; формулировка 2026-09-28 (окно D10, решение alex по аудиту избыточности тикетов): «находка» по слову человека — ISSUE, FIND не тип; T25 2026-10-16 (аудит astra Б-02): имя FIND не резервируется (03 §15.4, решение alex 2026-10-09) — оговорка про объявленный тип заказчика

## Профиль `requests` — обращения

### Блок `wp-aon-who` — `10-spec-assembly/03-agent-identity.md:49`

- покрывает: `10-spec-assembly/03-agent-identity.md#Кто человек`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 2026-10-03, решение alex по находкам paste-приёмки T6: агент, проверяя игнор `me.yaml`, грепал»; «[АМЕНДМЕНТ D10 2026-10-28, решение alex по decide d10-f-me-skip: вариант (г) — частичный откат»; «[АМЕНДМЕНТ D10 T25 2026-10-18,»

### Блок `wp-kernel-record-file` — `01-spec-kernel/spec-kernel.md:89`

- покрывает: `01-spec-kernel/spec-kernel.md#1. Физическая форма файла записи`; `01-spec-kernel/spec-kernel.md#2. Конверт: правила разбора`; `01-spec-kernel/spec-kernel.md#3. Идентичность: два слоя`; `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/spec-kernel.md#02.2.1 Полная форма: ISO-8601 UTC с Z`; `01-spec-kernel/spec-kernel.md#02.2.2 Дата-форма: YYYY-MM-DD`; `01-spec-kernel/spec-kernel.md#02.2.3 Время в свободной прозе`; `01-spec-kernel/envelope-fields.yaml#file_form`; `01-spec-kernel/envelope-fields.yaml#unknown_keys`; `01-spec-kernel/envelope-fields.yaml#fields[name=id]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=created]`; `01-spec-kernel/envelope-fields.yaml#fields[name=author]`; `01-spec-kernel/envelope-fields.yaml#fields[name=title]`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-namespace` — `01-spec-kernel/spec-kernel.md:411`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/envelope-fields.yaml#fields[name=namespace]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»

### Блок `wp-kernel-filename-ticket` — `01-spec-kernel/spec-kernel.md:415`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/spec-kernel.md#4. Ярлык: детерминизм и реестр`; `01-spec-kernel/envelope-fields.yaml#filename`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»; «[АМЕНДМЕНТ alex 2026-08-25 («го» по заявке PENDING-LABEL-ENTROPY из D03, вариант б+а): x-форма»

### Блок `wp-kernel-path-ticket` — `01-spec-kernel/spec-kernel.md:485`

- покрывает: `01-spec-kernel/spec-kernel.md#5.7 Путь записи в репозитории`; `01-spec-kernel/envelope-fields.yaml#record_layout`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03 (REQ-121, решение «месяц + декада»): до него раскладка тикетов и документов в спеке не»; «[АМЕНДМЕНТ D10 2026-10-03, пересуд»

### Блок `wp-kernel-version-ticket` — `01-spec-kernel/spec-kernel.md:550`

- покрывает: `01-spec-kernel/spec-kernel.md#6. version`; `01-spec-kernel/envelope-fields.yaml#fields[name=version]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-ticket-lifecycle` — `01-spec-kernel/spec-kernel.md:759`

- покрывает: `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `01-spec-kernel/envelope-fields.yaml#fields[name=status]`; `01-spec-kernel/envelope-fields.yaml#fields[name=status_note]`; `01-spec-kernel/envelope-fields.yaml#fields[name=evidence]`; `01-spec-kernel/envelope-fields.yaml#fields[name=assignee]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=decided_by]`; `01-spec-kernel/envelope-fields.yaml#fields[name=awaiting]`; `01-spec-kernel/envelope-fields.yaml#ticket_card`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-links` — `01-spec-kernel/spec-kernel.md:910`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`; `01-spec-kernel/spec-kernel.md#02.1.1 Тикетная ссылка `[[<label>]]``; `01-spec-kernel/spec-kernel.md#02.1.2 Упоминания: что ссылкой НЕ является`; `01-spec-kernel/spec-kernel.md#02.1.3 Кросс-репо и кросс-тип: голый текст`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «ок, берём А», Q2 суда T22 D10:»

### Блок `wp-kernel-refs-ticket` — `01-spec-kernel/spec-kernel.md:981`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1.4 Артефакты, код, сессии: бэктики`; `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comments-file` — `01-spec-kernel/spec-kernel.md:1719`

- покрывает: `01-spec-kernel/spec-kernel.md#04.1 Раскладка: комменты живут в файле-соседе (DECISION-1)`; `01-spec-kernel/spec-kernel.md#04.2.1 Конверта нет, заголовок — одна детерминированная строка`; `01-spec-kernel/spec-kernel.md#04.2.2 Связь с записью`; `01-spec-kernel/spec-kernel.md#04.2.3 Правило существования: ленивое создание`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.1.2 Склонность alex — названа и опрокинута эмпирикой` (history); `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comment-grammar` — `01-spec-kernel/spec-kernel.md:1869`

- покрывает: `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`; `01-spec-kernel/spec-kernel.md#04.3.2 Атрибуция — в содержимом, и только там`; `01-spec-kernel/spec-kernel.md#04.3.3 Собственный id коммента (DECISION-3)`; `01-spec-kernel/spec-kernel.md#04.3.4 Что проверяет валидатор (D05)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[Сужение области»

### Блок `wp-kernel-comment-append` — `01-spec-kernel/spec-kernel.md:1954`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4 Порядок: в файле не нормативен, канон восстанавливает читатель (DECISION-4)`; `01-spec-kernel/spec-kernel.md#04.6 Комменты и `version` (правило главы 01, обоснованное экспериментально)`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`; `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-gitattributes` — `01-spec-kernel/spec-kernel.md:2078`

- покрывает: `01-spec-kernel/spec-kernel.md#04.7.1 Строка и кто её приносит`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-lang-secrets` — `01-spec-kernel/spec-kernel.md:2364`

- покрывает: `01-spec-kernel/spec-kernel.md#05.3.2 Что требует спека`; `01-spec-kernel/spec-kernel.md#05.1.1 Правило`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-forms` — `03-spec-type-schemas/spec-type-schemas.md:1066`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Класс записи и поля жизненного цикла`; `03-spec-type-schemas/spec-type-schemas.md#1.1 Определение и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#2.1 Что это и в каком состоянии корпус`; `03-spec-type-schemas/spec-type-schemas.md#9.1 Определение и граница с соседями`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-sections` — `03-spec-type-schemas/spec-type-schemas.md:1117`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.3 Потолок секционной нормы: почему обязательная секция не может быть ERROR'ом`; `03-spec-type-schemas/section-ids.yaml#kernel_section_ids`; `03-spec-type-schemas/section-ids.yaml#introduced_by_ticket_forms`; `03-spec-type-schemas/section-ids.yaml#introduced_by_repo_type_extension`; `03-spec-type-schemas/section-ids.yaml#introduced_by_kernel_v2`; `03-spec-type-schemas/section-ids.yaml#section_anchor`; `03-spec-type-schemas/ticket-fields.yaml#rules`; `06-conformance-full/00-scope-coverage-and-dispositions.md#3.1 REQ-026 — исход (i): машинный носитель секции. АМЕНДМЕНТ-D06-01`; `03-spec-type-schemas/section-ids.yaml#normativity`; `01-spec-kernel/spec-kernel.md#05.1.3 Секции тела: семантические id, не литералы`; `01-spec-kernel/spec-kernel.md#8. DECISION-03 — судьба ключей Origin / Filed / Code`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/ticket-fields.yaml#not_validated` (boundary); `03-spec-type-schemas/ticket-fields.yaml#rules.kernel_grammars_not_redefined` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-relations` — `03-spec-type-schemas/spec-type-schemas.md:1168`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.5 Отношения — по id реестра; правило имени поля-носителя`; `03-spec-type-schemas/spec-type-schemas.md#1.9 Отношения TASK`; `03-spec-type-schemas/spec-type-schemas.md#2.4 Отношения ISSUE`; `03-spec-type-schemas/spec-type-schemas.md#2.2 Форма 02.1.2 — что ссылкой НЕ является`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Три кандидата и почему выбран третий`; `03-spec-type-schemas/spec-type-schemas.md#3.2 Внутренняя цель против внешней — два носителя, одно правило`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#4.3 «Двусторонняя ссылка» REQ-080 — требование к ЧТЕНИЮ, не к хранению (решение alex 2026-08-23)`; `03-spec-type-schemas/spec-type-schemas.md#5.1 Пояснения, которых таблица не вмещает`; `03-spec-type-schemas/spec-type-schemas.md#6. Правило закрытия контейнера работы (механизм для REQ-080)`; `03-spec-type-schemas/relations.yaml#rules`; `03-spec-type-schemas/relations.yaml#link_forms`; `03-spec-type-schemas/relations.yaml#relations`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#6.4 Перечисление в свидетельстве завершения — что формат может и чего не может` (boundary); `03-spec-type-schemas/spec-type-schemas.md#7. Заявки к alex — все закрыты` (history); `03-spec-type-schemas/spec-type-schemas.md#8. Границы проверки — сводно` (boundary); `03-spec-type-schemas/relations.yaml#out_of_registry` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-request-pii` — `03-spec-type-schemas/spec-type-schemas.md:2368`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.2 Персональные данные — правило типа`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-request` — `03-spec-type-schemas/spec-type-schemas.md:2394`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.3 Канал, ссылка на заявителя, срок`; `03-spec-type-schemas/spec-type-schemas.md#9.1 Определение и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Стадии, чей ход, кто решает`; `03-spec-type-schemas/spec-type-schemas.md#9.5 Ответ заявителю и исход`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Обращение → работа`; `03-spec-type-schemas/spec-type-schemas.md#9.7 Тело`; `03-spec-type-schemas/ticket-fields.yaml#types.REQUEST`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-att-path` — `03-spec-type-schemas/spec-type-schemas.md:4211`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Вложения комментов`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Грамматика`; `03-spec-type-schemas/spec-type-schemas.md#3.3 ASCII: правило и его измеренная причина`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Куда девается исходное имя`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Длина пути`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Две легальные формы, и они не конкурируют`; `03-spec-type-schemas/attachments.yaml#layout`; `03-spec-type-schemas/attachments.yaml#owners`; `03-spec-type-schemas/attachments.yaml#filename`; `03-spec-type-schemas/attachments.yaml#link_forms`; `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#4.3 Что глава про ссылку НЕ говорит` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-att-commit` — `03-spec-type-schemas/spec-type-schemas.md:4595`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#5.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#2.6 Вложение неизменяемо`; `03-spec-type-schemas/spec-type-schemas.md#6.3 Маршрут: куда писатель кладёт файл`; `03-spec-type-schemas/spec-type-schemas.md#6.1 Два хранилища и только два`; `03-spec-type-schemas/spec-type-schemas.md#6.4 Материалы внешних людей`; `03-spec-type-schemas/spec-type-schemas.md#6.5 Несохранённый файл: пометка и ответ`; `03-spec-type-schemas/attachments.yaml#one_commit_invariant`; `03-spec-type-schemas/attachments.yaml#immutability`; `03-spec-type-schemas/attachments.yaml#soft_limit`; `03-spec-type-schemas/attachments.yaml#stores`; `03-spec-type-schemas/attachments.yaml#routing`; `03-spec-type-schemas/attachments.yaml#routing.external_origin`; `03-spec-type-schemas/attachments.yaml#unsaved`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#6.7 Что порогом СОЗНАТЕЛЬНО не задано` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary); `03-spec-type-schemas/attachments.yaml#soft_limit.cumulative_limits` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D20 T1: прежняя буква запрещала только движение пути; правка байт по месту»; «[АМЕНДМЕНТ D20 T1 2026-10-05: прежняя редакция заводила настройку заказчика `external_media`»

### Блок `wp-att-store` — `03-spec-type-schemas/spec-type-schemas.md:4963`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.1 Носитель: файл по пути вложения`; `03-spec-type-schemas/spec-type-schemas.md#9.3 Грамматика указателя`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Ключ объекта`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Состояния и законные переходы`; `03-spec-type-schemas/spec-type-schemas.md#9.9 Git LFS не поддерживается`; `03-spec-type-schemas/attachments.yaml#pointer`; `03-spec-type-schemas/attachments.yaml#object_key`; `03-spec-type-schemas/attachments.yaml#states`; `03-spec-type-schemas/attachments.yaml#lfs`
- история и границы тех же предков: `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-repo-types` — `03-spec-type-schemas/spec-type-schemas.md:5473`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Формула форм: разрешение напряжения с REQ-002`; `03-spec-type-schemas/spec-type-schemas.md#1.2 Сужение ядрового набора`; `03-spec-type-schemas/spec-type-schemas.md#4. Паттерн `x_proposed_*` — штатный, и это его единственный дом`; `03-spec-type-schemas/spec-type-schemas.md#14. Схема ядра 2: что меняется для писателя и для конфига`; `03-spec-type-schemas/spec-type-schemas.md#15. Коллизии конфига с ядром v2`; `03-spec-type-schemas/types-config-schema.yaml#kernel_block.types_enabled`; `03-spec-type-schemas/types-config-schema.yaml#proposed_pattern`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.2 Четыре дыры GAP-REPO-EXT-* — где закрыта каждая и где граница` (boundary); `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#5. Форма HOTFIX схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#6. Форма DESIGN схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#7. Сверка констант референс-валидатора (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#8. FIND — миграция вместо типа (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#10. Контракты, границы, трассируемость` (boundary); `03-spec-type-schemas/spec-type-schemas.md#11. Стандартная поставка TASK / REQUEST (этап 1) — история` (history); `03-spec-type-schemas/spec-type-schemas.md#12. TASK — переехал в ядро` (history); `03-spec-type-schemas/spec-type-schemas.md#13. REQUEST — переехал в ядро` (history); `03-spec-type-schemas/types-config-schema.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-validator-forms` — `05-validator-core/01-invocation-interface.md:440`

- покрывает: `05-validator-core/01-invocation-interface.md#2.8 Какую форму зовёт писатель записи перед коммитом`; `05-validator-core/01-invocation-interface.md#3.1 Пять исходов, из них четыре обязательных и один отдельный`; `05-validator-core/validator-interface.yaml#return_codes`
- история и границы тех же предков: `05-validator-core/validator-interface.yaml#verdicts_as_inputs` (history); `05-validator-core/validator-interface.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-aon-when` — `10-spec-assembly/02-agent-operational-norm.md:42`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#3. Когда писать и когда спрашивать`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate` — `10-spec-assembly/02-agent-operational-norm.md:63`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-pair` — `10-spec-assembly/02-agent-operational-norm.md:71`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit` — `10-spec-assembly/02-agent-operational-norm.md:88`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-comment-time` — `10-spec-assembly/02-agent-operational-norm.md:102`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#6. Время заголовка коммента`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-read-once` — `10-spec-assembly/02-agent-operational-norm.md:119`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#7. Чтение профиля`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ROUTE-GREP (decide D-B п. 4) — агент Sonnet искал»

### Блок `wp-aon-secrets` — `10-spec-assembly/02-agent-operational-norm.md:130`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#8. Секреты`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Деферралы профиля `requests`

- `find` (предмет `ticket`): вердикт alex Q4 «б» 2026-09-20: FIND — репозиторное расширение, подрядчику не нужно; формулировка 2026-09-28 (окно D10, решение alex по аудиту избыточности тикетов): «находка» по слову человека — ISSUE, FIND не тип; T25 2026-10-16 (аудит astra Б-02): имя FIND не резервируется (03 §15.4, решение alex 2026-10-09) — оговорка про объявленный тип заказчика

## Профиль `docs` — документы

### Блок `wp-aon-who` — `10-spec-assembly/03-agent-identity.md:49`

- покрывает: `10-spec-assembly/03-agent-identity.md#Кто человек`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 2026-10-03, решение alex по находкам paste-приёмки T6: агент, проверяя игнор `me.yaml`, грепал»; «[АМЕНДМЕНТ D10 2026-10-28, решение alex по decide d10-f-me-skip: вариант (г) — частичный откат»; «[АМЕНДМЕНТ D10 T25 2026-10-18,»

### Блок `wp-kernel-record-file` — `01-spec-kernel/spec-kernel.md:89`

- покрывает: `01-spec-kernel/spec-kernel.md#1. Физическая форма файла записи`; `01-spec-kernel/spec-kernel.md#2. Конверт: правила разбора`; `01-spec-kernel/spec-kernel.md#3. Идентичность: два слоя`; `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/spec-kernel.md#02.2.1 Полная форма: ISO-8601 UTC с Z`; `01-spec-kernel/spec-kernel.md#02.2.2 Дата-форма: YYYY-MM-DD`; `01-spec-kernel/spec-kernel.md#02.2.3 Время в свободной прозе`; `01-spec-kernel/envelope-fields.yaml#file_form`; `01-spec-kernel/envelope-fields.yaml#unknown_keys`; `01-spec-kernel/envelope-fields.yaml#fields[name=id]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=created]`; `01-spec-kernel/envelope-fields.yaml#fields[name=author]`; `01-spec-kernel/envelope-fields.yaml#fields[name=title]`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-namespace` — `01-spec-kernel/spec-kernel.md:411`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/envelope-fields.yaml#fields[name=namespace]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»

### Блок `wp-kernel-filename-doc` — `01-spec-kernel/spec-kernel.md:419`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/spec-kernel.md#4. Ярлык: детерминизм и реестр`; `01-spec-kernel/envelope-fields.yaml#filename`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»; «[АМЕНДМЕНТ alex 2026-08-25 («го» по заявке PENDING-LABEL-ENTROPY из D03, вариант б+а): x-форма»

### Блок `wp-kernel-path-doc` — `01-spec-kernel/spec-kernel.md:489`

- покрывает: `01-spec-kernel/spec-kernel.md#5.7 Путь записи в репозитории`; `01-spec-kernel/envelope-fields.yaml#record_layout`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03 (REQ-121, решение «месяц + декада»): до него раскладка тикетов и документов в спеке не»; «[АМЕНДМЕНТ D10 2026-10-03, пересуд»

### Блок `wp-kernel-version-doc` — `01-spec-kernel/spec-kernel.md:554`

- покрывает: `01-spec-kernel/spec-kernel.md#6. version`; `01-spec-kernel/envelope-fields.yaml#fields[name=version]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-doc-lifecycle` — `01-spec-kernel/spec-kernel.md:765`

- покрывает: `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `01-spec-kernel/envelope-fields.yaml#fields[name=status]`; `01-spec-kernel/envelope-fields.yaml#fields[name=status_note]`; `01-spec-kernel/envelope-fields.yaml#fields[name=evidence]`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-links` — `01-spec-kernel/spec-kernel.md:910`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`; `01-spec-kernel/spec-kernel.md#02.1.1 Тикетная ссылка `[[<label>]]``; `01-spec-kernel/spec-kernel.md#02.1.2 Упоминания: что ссылкой НЕ является`; `01-spec-kernel/spec-kernel.md#02.1.3 Кросс-репо и кросс-тип: голый текст`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «ок, берём А», Q2 суда T22 D10:»

### Блок `wp-kernel-refs-doc` — `01-spec-kernel/spec-kernel.md:985`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1.4 Артефакты, код, сессии: бэктики`; `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comments-file` — `01-spec-kernel/spec-kernel.md:1719`

- покрывает: `01-spec-kernel/spec-kernel.md#04.1 Раскладка: комменты живут в файле-соседе (DECISION-1)`; `01-spec-kernel/spec-kernel.md#04.2.1 Конверта нет, заголовок — одна детерминированная строка`; `01-spec-kernel/spec-kernel.md#04.2.2 Связь с записью`; `01-spec-kernel/spec-kernel.md#04.2.3 Правило существования: ленивое создание`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.1.2 Склонность alex — названа и опрокинута эмпирикой` (history); `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comment-grammar` — `01-spec-kernel/spec-kernel.md:1869`

- покрывает: `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`; `01-spec-kernel/spec-kernel.md#04.3.2 Атрибуция — в содержимом, и только там`; `01-spec-kernel/spec-kernel.md#04.3.3 Собственный id коммента (DECISION-3)`; `01-spec-kernel/spec-kernel.md#04.3.4 Что проверяет валидатор (D05)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[Сужение области»

### Блок `wp-kernel-comment-append` — `01-spec-kernel/spec-kernel.md:1954`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4 Порядок: в файле не нормативен, канон восстанавливает читатель (DECISION-4)`; `01-spec-kernel/spec-kernel.md#04.6 Комменты и `version` (правило главы 01, обоснованное экспериментально)`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`; `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-gitattributes` — `01-spec-kernel/spec-kernel.md:2078`

- покрывает: `01-spec-kernel/spec-kernel.md#04.7.1 Строка и кто её приносит`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-lang-secrets` — `01-spec-kernel/spec-kernel.md:2364`

- покрывает: `01-spec-kernel/spec-kernel.md#05.3.2 Что требует спека`; `01-spec-kernel/spec-kernel.md#05.1.1 Правило`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-doc` — `03-spec-type-schemas/spec-type-schemas.md:2681`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.1 Что это и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#1.3.2 `provenance` — единственная секционная норма главы`; `03-spec-type-schemas/spec-type-schemas.md#0.1 Классы записей и поля жизненного цикла`; `03-spec-type-schemas/spec-type-schemas.md#1.2.1 Ни одного нового обязательного поля`; `03-spec-type-schemas/spec-type-schemas.md#1.2.2 Полуюнит `status` без `status_note` — пробел ядра ЗАКРЫТ вердиктом`; `03-spec-type-schemas/spec-type-schemas.md#1.2.3 `kind` — единственное новое поле (REQ-075)`; `03-spec-type-schemas/spec-type-schemas.md#1.3.1 Скелета нет, и это решение, а не пропуск`; `03-spec-type-schemas/doc-fields.yaml#doc`; `03-spec-type-schemas/doc-fields.yaml#rules`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#1.2.4 След REQ-075: происхождение и отклонённые кандидаты` (history); `03-spec-type-schemas/doc-fields.yaml#d04_boundary` (boundary); `03-spec-type-schemas/doc-fields.yaml#not_validated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-doc-relations` — `03-spec-type-schemas/spec-type-schemas.md:2832`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.4 Отношения DOC`; `03-spec-type-schemas/spec-type-schemas.md#0.4 Отношения — по id реестра; имя поля-носителя`; `03-spec-type-schemas/spec-type-schemas.md#1.4.1 `epic_membership_doc` — членство живёт в ребёнке`; `03-spec-type-schemas/spec-type-schemas.md#1.4.2 `reclassified_as` требует `RETRACTED` — обязанность приходит от реестра, не от схемы`; `03-spec-type-schemas/spec-type-schemas.md#2.2 Форма 02.1.2 — что ссылкой НЕ является`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Три кандидата и почему выбран третий`; `03-spec-type-schemas/spec-type-schemas.md#3.2 Внутренняя цель против внешней — два носителя, одно правило`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#4.3 «Двусторонняя ссылка» REQ-080 — требование к ЧТЕНИЮ, не к хранению (решение alex 2026-08-23)`; `03-spec-type-schemas/spec-type-schemas.md#5.1 Пояснения, которых таблица не вмещает`; `03-spec-type-schemas/spec-type-schemas.md#6. Правило закрытия контейнера работы (механизм для REQ-080)`; `03-spec-type-schemas/relations.yaml#rules`; `03-spec-type-schemas/relations.yaml#link_forms`; `03-spec-type-schemas/relations.yaml#relations`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#6.4 Перечисление в свидетельстве завершения — что формат может и чего не может` (boundary); `03-spec-type-schemas/spec-type-schemas.md#7. Заявки к alex — все закрыты` (history); `03-spec-type-schemas/spec-type-schemas.md#8. Границы проверки — сводно` (boundary); `03-spec-type-schemas/relations.yaml#out_of_registry` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-att-path` — `03-spec-type-schemas/spec-type-schemas.md:4211`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Вложения комментов`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Грамматика`; `03-spec-type-schemas/spec-type-schemas.md#3.3 ASCII: правило и его измеренная причина`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Куда девается исходное имя`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Длина пути`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Две легальные формы, и они не конкурируют`; `03-spec-type-schemas/attachments.yaml#layout`; `03-spec-type-schemas/attachments.yaml#owners`; `03-spec-type-schemas/attachments.yaml#filename`; `03-spec-type-schemas/attachments.yaml#link_forms`; `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#4.3 Что глава про ссылку НЕ говорит` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-att-commit` — `03-spec-type-schemas/spec-type-schemas.md:4595`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#5.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#2.6 Вложение неизменяемо`; `03-spec-type-schemas/spec-type-schemas.md#6.3 Маршрут: куда писатель кладёт файл`; `03-spec-type-schemas/spec-type-schemas.md#6.1 Два хранилища и только два`; `03-spec-type-schemas/spec-type-schemas.md#6.4 Материалы внешних людей`; `03-spec-type-schemas/spec-type-schemas.md#6.5 Несохранённый файл: пометка и ответ`; `03-spec-type-schemas/attachments.yaml#one_commit_invariant`; `03-spec-type-schemas/attachments.yaml#immutability`; `03-spec-type-schemas/attachments.yaml#soft_limit`; `03-spec-type-schemas/attachments.yaml#stores`; `03-spec-type-schemas/attachments.yaml#routing`; `03-spec-type-schemas/attachments.yaml#routing.external_origin`; `03-spec-type-schemas/attachments.yaml#unsaved`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#6.7 Что порогом СОЗНАТЕЛЬНО не задано` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary); `03-spec-type-schemas/attachments.yaml#soft_limit.cumulative_limits` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D20 T1: прежняя буква запрещала только движение пути; правка байт по месту»; «[АМЕНДМЕНТ D20 T1 2026-10-05: прежняя редакция заводила настройку заказчика `external_media`»

### Блок `wp-att-store` — `03-spec-type-schemas/spec-type-schemas.md:4963`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.1 Носитель: файл по пути вложения`; `03-spec-type-schemas/spec-type-schemas.md#9.3 Грамматика указателя`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Ключ объекта`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Состояния и законные переходы`; `03-spec-type-schemas/spec-type-schemas.md#9.9 Git LFS не поддерживается`; `03-spec-type-schemas/attachments.yaml#pointer`; `03-spec-type-schemas/attachments.yaml#object_key`; `03-spec-type-schemas/attachments.yaml#states`; `03-spec-type-schemas/attachments.yaml#lfs`
- история и границы тех же предков: `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-doc-repo-types` — `03-spec-type-schemas/spec-type-schemas.md:5477`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Формула форм: разрешение напряжения с REQ-002`; `03-spec-type-schemas/spec-type-schemas.md#1.2 Сужение ядрового набора`; `03-spec-type-schemas/types-config-schema.yaml#kernel_block.types_enabled`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.2 Четыре дыры GAP-REPO-EXT-* — где закрыта каждая и где граница` (boundary); `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-validator-forms` — `05-validator-core/01-invocation-interface.md:440`

- покрывает: `05-validator-core/01-invocation-interface.md#2.8 Какую форму зовёт писатель записи перед коммитом`; `05-validator-core/01-invocation-interface.md#3.1 Пять исходов, из них четыре обязательных и один отдельный`; `05-validator-core/validator-interface.yaml#return_codes`
- история и границы тех же предков: `05-validator-core/validator-interface.yaml#verdicts_as_inputs` (history); `05-validator-core/validator-interface.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-aon-when` — `10-spec-assembly/02-agent-operational-norm.md:42`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#3. Когда писать и когда спрашивать`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate` — `10-spec-assembly/02-agent-operational-norm.md:63`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-pair` — `10-spec-assembly/02-agent-operational-norm.md:71`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit` — `10-spec-assembly/02-agent-operational-norm.md:88`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-comment-time` — `10-spec-assembly/02-agent-operational-norm.md:102`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#6. Время заголовка коммента`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-read-once` — `10-spec-assembly/02-agent-operational-norm.md:119`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#7. Чтение профиля`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ROUTE-GREP (decide D-B п. 4) — агент Sonnet искал»

### Блок `wp-aon-secrets` — `10-spec-assembly/02-agent-operational-norm.md:130`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#8. Секреты`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

## Профиль `full` — полный

### Блок `wp-aon-who` — `10-spec-assembly/03-agent-identity.md:49`

- покрывает: `10-spec-assembly/03-agent-identity.md#Кто человек`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 2026-10-03, решение alex по находкам paste-приёмки T6: агент, проверяя игнор `me.yaml`, грепал»; «[АМЕНДМЕНТ D10 2026-10-28, решение alex по decide d10-f-me-skip: вариант (г) — частичный откат»; «[АМЕНДМЕНТ D10 T25 2026-10-18,»

### Блок `wp-kernel-record-file` — `01-spec-kernel/spec-kernel.md:89`

- покрывает: `01-spec-kernel/spec-kernel.md#1. Физическая форма файла записи`; `01-spec-kernel/spec-kernel.md#2. Конверт: правила разбора`; `01-spec-kernel/spec-kernel.md#3. Идентичность: два слоя`; `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/spec-kernel.md#02.2.1 Полная форма: ISO-8601 UTC с Z`; `01-spec-kernel/spec-kernel.md#02.2.2 Дата-форма: YYYY-MM-DD`; `01-spec-kernel/spec-kernel.md#02.2.3 Время в свободной прозе`; `01-spec-kernel/envelope-fields.yaml#file_form`; `01-spec-kernel/envelope-fields.yaml#unknown_keys`; `01-spec-kernel/envelope-fields.yaml#fields[name=id]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=created]`; `01-spec-kernel/envelope-fields.yaml#fields[name=author]`; `01-spec-kernel/envelope-fields.yaml#fields[name=title]`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-namespace` — `01-spec-kernel/spec-kernel.md:411`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/envelope-fields.yaml#fields[name=namespace]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»

### Блок `wp-kernel-filename-ticket` — `01-spec-kernel/spec-kernel.md:415`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/spec-kernel.md#4. Ярлык: детерминизм и реестр`; `01-spec-kernel/envelope-fields.yaml#filename`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»; «[АМЕНДМЕНТ alex 2026-08-25 («го» по заявке PENDING-LABEL-ENTROPY из D03, вариант б+а): x-форма»

### Блок `wp-kernel-filename-doc` — `01-spec-kernel/spec-kernel.md:419`

- покрывает: `01-spec-kernel/spec-kernel.md#5. namespace и имя файла`; `01-spec-kernel/spec-kernel.md#4. Ярлык: детерминизм и реестр`; `01-spec-kernel/envelope-fields.yaml#filename`; `02-write-path-blueprint/write-path-blueprint.md#Входящие корпус-свидетельства (окно PadelApp `0bcbc631`, письмо 2026-08-22)`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `02-write-path-blueprint/write-path-blueprint.md#Границы` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («3а»), заявка D04-NAME-01 —»; «[АМЕНДМЕНТ alex 2026-08-25 («го» по заявке PENDING-LABEL-ENTROPY из D03, вариант б+а): x-форма»

### Блок `wp-kernel-path-ticket` — `01-spec-kernel/spec-kernel.md:485`

- покрывает: `01-spec-kernel/spec-kernel.md#5.7 Путь записи в репозитории`; `01-spec-kernel/envelope-fields.yaml#record_layout`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03 (REQ-121, решение «месяц + декада»): до него раскладка тикетов и документов в спеке не»; «[АМЕНДМЕНТ D10 2026-10-03, пересуд»

### Блок `wp-kernel-path-doc` — `01-spec-kernel/spec-kernel.md:489`

- покрывает: `01-spec-kernel/spec-kernel.md#5.7 Путь записи в репозитории`; `01-spec-kernel/envelope-fields.yaml#record_layout`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03 (REQ-121, решение «месяц + декада»): до него раскладка тикетов и документов в спеке не»; «[АМЕНДМЕНТ D10 2026-10-03, пересуд»

### Блок `wp-kernel-version-ticket` — `01-spec-kernel/spec-kernel.md:550`

- покрывает: `01-spec-kernel/spec-kernel.md#6. version`; `01-spec-kernel/envelope-fields.yaml#fields[name=version]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-version-doc` — `01-spec-kernel/spec-kernel.md:554`

- покрывает: `01-spec-kernel/spec-kernel.md#6. version`; `01-spec-kernel/envelope-fields.yaml#fields[name=version]`
- история и границы тех же предков: `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-ticket-lifecycle` — `01-spec-kernel/spec-kernel.md:759`

- покрывает: `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `01-spec-kernel/envelope-fields.yaml#fields[name=status]`; `01-spec-kernel/envelope-fields.yaml#fields[name=status_note]`; `01-spec-kernel/envelope-fields.yaml#fields[name=evidence]`; `01-spec-kernel/envelope-fields.yaml#fields[name=assignee]`; `01-spec-kernel/envelope-fields.yaml#fields[name=type]`; `01-spec-kernel/envelope-fields.yaml#fields[name=decided_by]`; `01-spec-kernel/envelope-fields.yaml#fields[name=awaiting]`; `01-spec-kernel/envelope-fields.yaml#ticket_card`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-doc-lifecycle` — `01-spec-kernel/spec-kernel.md:765`

- покрывает: `01-spec-kernel/spec-kernel.md#7. Поля конверта`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `01-spec-kernel/envelope-fields.yaml#fields[name=status]`; `01-spec-kernel/envelope-fields.yaml#fields[name=status_note]`; `01-spec-kernel/envelope-fields.yaml#fields[name=evidence]`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#7.12 История набора ядра` (history); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, вердикт по заявке §7.3 главы 03-reference-model D03:»; «[АМЕНДМЕНТ alex 2026-08-25 («решение с фолаутами и их разбор вручную — думаю так проще чем»; «[АМЕНДМЕНТ alex 2026-08-25 («да», заявка DOC-STATUS-HALF-UNIT из D03):»

### Блок `wp-kernel-links` — `01-spec-kernel/spec-kernel.md:910`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`; `01-spec-kernel/spec-kernel.md#02.1.1 Тикетная ссылка `[[<label>]]``; `01-spec-kernel/spec-kernel.md#02.1.2 Упоминания: что ссылкой НЕ является`; `01-spec-kernel/spec-kernel.md#02.1.3 Кросс-репо и кросс-тип: голый текст`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «ок, берём А», Q2 суда T22 D10:»

### Блок `wp-kernel-refs-ticket` — `01-spec-kernel/spec-kernel.md:981`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1.4 Артефакты, код, сессии: бэктики`; `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-refs-doc` — `01-spec-kernel/spec-kernel.md:985`

- покрывает: `01-spec-kernel/spec-kernel.md#02.1.4 Артефакты, код, сессии: бэктики`; `01-spec-kernel/spec-kernel.md#02.1 Четыре формы ссылок`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#02.3 Контракт для других глав` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-timesheet-file` — `01-spec-kernel/spec-kernel.md:1336`

- покрывает: `01-spec-kernel/spec-kernel.md#03.3.4 Контейнер времени (`type: TIMESHEET`)`; `01-spec-kernel/spec-kernel.md#03.3.2 Общий контейнерный минимум`; `01-spec-kernel/spec-kernel.md#03.3.5 Конверт контейнера пишется один раз`; `01-spec-kernel/spec-kernel.md#03.5.4 Атрибуция`; `01-spec-kernel/line-forms.yaml#containers.common`; `01-spec-kernel/line-forms.yaml#containers.timesheet`; `01-spec-kernel/envelope-fields.yaml#aggregate_on_container`; `01-spec-kernel/envelope-fields.yaml#filename.per_type.TIMESHEET`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `04-spec-time-model/spec-time-model.md#1.1 Решение`; `04-spec-time-model/spec-time-model.md#1.2 Отношение к остальной раскладке`; `04-spec-time-model/spec-time-model.md#2.1 Грамматика`; `04-spec-time-model/spec-time-model.md#2.7 Что в имени проверяется, а что нет`; `04-spec-time-model/spec-time-model.md#3.1 Правило`; `04-spec-time-model/spec-time-model.md#4.2 Период конверта = календарный месяц имени, и это привязывает РАСКЛАДКА`; `04-spec-time-model/spec-time-model.md#4.3 Маршрутизация аппенда: что делает писатель`; `04-spec-time-model/spec-time-model.md#5.1 Авторитет — конверт`; `04-spec-time-model/spec-time-model.md#5.2 Форма id в имени`; `04-spec-time-model/spec-time-model.md#5. Атрибуция: person в конверте, автор коммита — транспорт`; `04-spec-time-model/spec-time-model.md#1.3 Носитель 1 — поле конверта`; `04-spec-time-model/spec-time-model.md#1.5 Носитель 3 — счётчик в имени файла`; `04-spec-time-model/time-model.yaml#layout`; `04-spec-time-model/time-model.yaml#filename`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary); `04-spec-time-model/spec-time-model.md#2.4 Коллизия с `filename.grammar` ядра — обе стороны дословно` (history); `04-spec-time-model/spec-time-model.md#2.6 Исход: заявка, а не самообъявленное исключение` (history); `04-spec-time-model/spec-time-model.md#3.3 Передача главе политики мульти-писателя` (boundary); `04-spec-time-model/spec-time-model.md#6. Границы: что здесь НЕ решено и где дом` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-10-03, REQ-121: прежняя буква «нигде в спеке»

### Блок `wp-kernel-journal` — `01-spec-kernel/spec-kernel.md:1379`

- покрывает: `01-spec-kernel/spec-kernel.md#03.4.1 Грамматика`; `01-spec-kernel/spec-kernel.md#03.1.3 Неизменяемость и исправления`; `01-spec-kernel/spec-kernel.md#03.1.4 Идентичность, версия, sync-readiness`; `01-spec-kernel/spec-kernel.md#03.2.1 Строение строки`; `01-spec-kernel/spec-kernel.md#03.2.2 Разделители: канон и приёмка`; `01-spec-kernel/spec-kernel.md#03.2.4 Строки-продолжения — DECISION-03-02`; `01-spec-kernel/spec-kernel.md#03.2.5 Порядок строк и пустые строки`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`; `01-spec-kernel/spec-kernel.md#03.3.2 Общий контейнерный минимум`; `01-spec-kernel/spec-kernel.md#03.3.3 Контейнер журнала (`type: JOURNAL`)`; `01-spec-kernel/spec-kernel.md#03.3.5 Конверт контейнера пишется один раз`; `01-spec-kernel/spec-kernel.md#03.4.2 Ядро enum — DECISION-03-01`; `01-spec-kernel/spec-kernel.md#03.4.3 Строки доставки: COMMIT / PR / DEPLOY — DECISION-03-04`; `01-spec-kernel/spec-kernel.md#03.6.1 Два режима, и это не смягчение, а разные вопросы`; `01-spec-kernel/spec-kernel.md#03.6.3 Что НИКОГДА не является ошибкой`; `01-spec-kernel/line-forms.yaml#line_form_model`; `01-spec-kernel/line-forms.yaml#continuation`; `01-spec-kernel/line-forms.yaml#forms.journal_v1`; `01-spec-kernel/line-forms.yaml#journal_type_vocabulary`; `01-spec-kernel/line-forms.yaml#journal_core_types`; `01-spec-kernel/line-forms.yaml#delivery_payload`; `01-spec-kernel/line-forms.yaml#containers.common`; `01-spec-kernel/line-forms.yaml#containers.journal`; `01-spec-kernel/line-forms.yaml#validator`; `01-spec-kernel/envelope-fields.yaml#record_classes`; `04-spec-time-model/spec-time-model.md#5.1 Вердикт и три основания`; `04-spec-time-model/spec-time-model.md#5.2 Что журнальная строка МОЖЕТ и чего ОБЯЗАНА НЕ делать`
- история и границы тех же предков: `01-spec-kernel/line-forms.yaml#boundaries` (boundary); `01-spec-kernel/envelope-fields.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-25, интейк v3 (REQ-086): + `CORRECTION` — единственный»; «[АМЕНДМЕНТ ядра — выравнивание с решением alex»; «[АМЕНДМЕНТ ядра — решение alex 2026-10-07, «Б1 — А»,»

### Блок `wp-kernel-daily-line` — `01-spec-kernel/spec-kernel.md:1531`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.1 Грамматика`; `01-spec-kernel/spec-kernel.md#03.2.1 Строение строки`; `01-spec-kernel/spec-kernel.md#03.2.2 Разделители: канон и приёмка`; `01-spec-kernel/spec-kernel.md#03.2.6 Ссылки в свободном тексте (REQ-073)`; `01-spec-kernel/spec-kernel.md#03.2.4 Строки-продолжения — DECISION-03-02`; `01-spec-kernel/line-forms.yaml#line_form_model`; `01-spec-kernel/line-forms.yaml#continuation`; `01-spec-kernel/line-forms.yaml#forms.daily_time_v1`; `01-spec-kernel/line-forms.yaml#time_line_anchor`; `04-spec-time-model/spec-time-model.md#6. ПРОЕКТНЫЙ РАЗРЕЗ: решение НЕ заводить`; `04-spec-time-model/spec-time-model.md#3.3 Отсюда — почему якорь становится ОБЯЗАННОСТЬЮ машинного продюсера (П5)`; `04-spec-time-model/spec-time-model.md#3.4 Согласование с идемпотентностью бота`; `04-spec-time-model/spec-time-model.md#4. Нормализация ЧЧ:ММ → десятичные: чья обязанность и с какой точностью`; `04-spec-time-model/spec-time-model.md#4.1 Правило Н1 — единственное правило округления`; `04-spec-time-model/spec-time-model.md#4.2 Почему Н1 сформулировано на целых секундах, а не на дробных числах`; `04-spec-time-model/spec-time-model.md#4.3 Кто нормализует и когда`; `04-spec-time-model/spec-time-model.md#4.4 Рукописная строка: ЧЧ:ММ не примет валидатор`; `04-spec-time-model/spec-time-model.md#4.5 Края правила`; `04-spec-time-model/time-model.yaml#line_inheritance`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `01-spec-kernel/line-forms.yaml#boundaries` (boundary); `04-spec-time-model/spec-time-model.md#8. Заявки` (history); `04-spec-time-model/spec-time-model.md#9. Контракты другим главам и деливераблам` (boundary); `04-spec-time-model/spec-time-model.md#6. Границы: что здесь НЕ решено и где дом` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27, приёмка D04 («4-а»), заявка D04-ANCHOR-04 —»

### Блок `wp-kernel-backfill` — `01-spec-kernel/spec-kernel.md:1552`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.2 Запись задним числом`; `01-spec-kernel/spec-kernel.md#03.2.5 Порядок строк и пустые строки`; `01-spec-kernel/spec-kernel.md#03.1.4 Идентичность, версия, sync-readiness`; `01-spec-kernel/spec-kernel.md#03.1.3 Неизменяемость и исправления`; `01-spec-kernel/spec-kernel.md#03.6.3 Что НИКОГДА не является ошибкой`; `04-spec-time-model/spec-time-model.md#4.4 `DATE_OUTSIDE_PERIOD` получает точный смысл`; `04-spec-time-model/spec-time-model.md#1.1 Норма`; `04-spec-time-model/spec-time-model.md#1.2 Предикат: что такое «носитель итога»`; `04-spec-time-model/spec-time-model.md#1.4 Носитель 2 — итоговая строка в теле`; `04-spec-time-model/spec-time-model.md#1.6 Что носителем НЕ является — границы правила, названные явно`; `04-spec-time-model/time-model.yaml#aggregation`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-midnight` — `01-spec-kernel/spec-kernel.md:1584`

- покрывает: `01-spec-kernel/spec-kernel.md#03.5.3 Полночь: что делает ГРАММАТИКА (именованный контракт MIDNIGHT-CUT → D04)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#03.5.5 Граница D04 — записано явно` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-line-validator` — `01-spec-kernel/spec-kernel.md:1640`

- покрывает: `01-spec-kernel/spec-kernel.md#03.6.1 Два режима, и это не смягчение, а разные вопросы`; `01-spec-kernel/spec-kernel.md#9. Валидатор`; `01-spec-kernel/line-forms.yaml#validator`
- история и границы тех же предков: `01-spec-kernel/line-forms.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comments-file` — `01-spec-kernel/spec-kernel.md:1719`

- покрывает: `01-spec-kernel/spec-kernel.md#04.1 Раскладка: комменты живут в файле-соседе (DECISION-1)`; `01-spec-kernel/spec-kernel.md#04.2.1 Конверта нет, заголовок — одна детерминированная строка`; `01-spec-kernel/spec-kernel.md#04.2.2 Связь с записью`; `01-spec-kernel/spec-kernel.md#04.2.3 Правило существования: ленивое создание`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.1.2 Склонность alex — названа и опрокинута эмпирикой` (history); `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-comment-grammar` — `01-spec-kernel/spec-kernel.md:1869`

- покрывает: `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`; `01-spec-kernel/spec-kernel.md#04.3.2 Атрибуция — в содержимом, и только там`; `01-spec-kernel/spec-kernel.md#04.3.3 Собственный id коммента (DECISION-3)`; `01-spec-kernel/spec-kernel.md#04.3.4 Что проверяет валидатор (D05)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[Сужение области»

### Блок `wp-kernel-comment-append` — `01-spec-kernel/spec-kernel.md:1954`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4 Порядок: в файле не нормативен, канон восстанавливает читатель (DECISION-4)`; `01-spec-kernel/spec-kernel.md#04.6 Комменты и `version` (правило главы 01, обоснованное экспериментально)`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`; `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#04.4.1 Треды: плоское хранение, дерево на чтении (амендмент alex, ревью D01)`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-comment-timesheet` — `01-spec-kernel/spec-kernel.md:1984`

- покрывает: `01-spec-kernel/spec-kernel.md#04.4.2 Комменты к строкам времени (амендмент alex, ревью D01)`; `04-spec-time-model/spec-time-model.md#4.2 Инвариант Ч — часы живут ТОЛЬКО в табеле`; `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`
- история и границы тех же предков: `04-spec-time-model/spec-time-model.md#4.3 ЗАЯВКА D04-CORR-07 — разрешить отзыв дневной строки` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-kernel-corrections` — `01-spec-kernel/spec-kernel.md:2028`

- покрывает: `01-spec-kernel/spec-kernel.md#04.5 Правки и удаления существующих комментов (DECISION-5)`; `01-spec-kernel/spec-kernel.md#03.1.3 Неизменяемость и исправления`; `04-spec-time-model/spec-time-model.md#05 — Политика исправлений записанных часов`; `04-spec-time-model/spec-time-model.md#0.2 Отклонённый кандидат: правка строки на месте`; `04-spec-time-model/spec-time-model.md#1.1 Недобор: дозапись обычным аппендом, политика не нужна`; `04-spec-time-model/spec-time-model.md#1.2 Перебор: записанный факт обязан перестать считаться — это и есть предмет главы`; `04-spec-time-model/spec-time-model.md#1.3 Неверная дата = перебор плюс недобор, и иногда это ДВА файла`; `04-spec-time-model/spec-time-model.md#1.4 Исправление приходит ПОЗДНО, и месяц никогда не «закрыт»`; `04-spec-time-model/spec-time-model.md#4.1 Правило И-БАЗА — нормативно СЕГОДНЯ, без единого амендмента`; `04-spec-time-model/spec-time-model.md#4.4 Строки БЕЗ якоря: что делает исправляющий и сколько это стоит`; `04-spec-time-model/spec-time-model.md#6.2 Идемпотентность отзыва по цели`; `04-spec-time-model/time-model.yaml#corrections`
- история и границы тех же предков: `01-spec-kernel/spec-kernel.md#04.9 Вне v1 — объявлено явно` (boundary); `01-spec-kernel/spec-kernel.md#04.10 Контракт для других глав и деливераблов` (boundary); `04-spec-time-model/spec-time-model.md#02 — Политика мульти-писателя time-файла (REQ-072)` (history); `04-spec-time-model/spec-time-model.md#0.3 Что глава решает, чего НЕ трогает — с адресатом у каждого пункта` (boundary); `04-spec-time-model/spec-time-model.md#0.4 Долги предыдущих глав, которые эта глава ОБЯЗАНА погасить` (history); `04-spec-time-model/spec-time-model.md#4.3 ЗАЯВКА D04-CORR-07 — разрешить отзыв дневной строки` (history); `04-spec-time-model/spec-time-model.md#Ситуация` (history); `04-spec-time-model/spec-time-model.md#Выбор` (history); `04-spec-time-model/spec-time-model.md#Рекомендация` (history); `04-spec-time-model/spec-time-model.md#Часть А — предлагаемая редакция` (history); `04-spec-time-model/spec-time-model.md#Часть Б — что обязан делать индекс при принятии` (history); `04-spec-time-model/spec-time-model.md#Часть В — обязательные регрессии при принятии (кандидаты в фикстуры D06)` (history); `04-spec-time-model/spec-time-model.md#8. Границы — по конкретному предложению на соседа` (boundary); `04-spec-time-model/spec-time-model.md#9. Заявки` (history); `04-spec-time-model/spec-time-model.md#9.1 Вынесена: D04-CORR-07 — отзыв дневной строки (`retracts:t:<id>`)` (history); `04-spec-time-model/spec-time-model.md#9.2 Усилены существующие заявки — новых по ним не вносится` (history); `04-spec-time-model/spec-time-model.md#9.3 НЕ вынесены — с основанием` (history); `04-spec-time-model/spec-time-model.md#10. Выход для alex — материал приёмочного пакета` (history); `04-spec-time-model/spec-time-model.md#Вопрос 1 — как исправлять уже записанные часы` (history); `04-spec-time-model/spec-time-model.md#Вопрос 2 — разрешить «вычеркнуть» ошибочную запись, чтобы она перестала считаться` (history); `04-spec-time-model/spec-time-model.md#Вопрос 3 — мелкое: нужен ли след исправления в журнале событий` (history); `04-spec-time-model/spec-time-model.md#Вопрос 4 — мелкое: исправление через бота в первой версии не работает` (history); `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ alex 2026-08-27,»

### Блок `wp-kernel-gitattributes` — `01-spec-kernel/spec-kernel.md:2078`

- покрывает: `01-spec-kernel/spec-kernel.md#04.7.1 Строка и кто её приносит`; `01-spec-kernel/spec-kernel.md#04.7.3 Что union делает и чего не делает`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-kernel-lang-secrets` — `01-spec-kernel/spec-kernel.md:2364`

- покрывает: `01-spec-kernel/spec-kernel.md#05.3.2 Что требует спека`; `01-spec-kernel/spec-kernel.md#05.1.1 Правило`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-time-git-discipline` — `04-spec-time-model/spec-time-model.md:1247`

- покрывает: `04-spec-time-model/spec-time-model.md#2.1 Дисциплина писателя: П1–П7, одинаково для бота, фронтов и рук`; `04-spec-time-model/spec-time-model.md#2.2 Правило Р1 — машинное разрешение конфликта хвостовых аппендов`; `04-spec-time-model/spec-time-model.md#2.5 Роль «ПРАВКА РУКАМИ» (редактор + обычный git, чужой ИИ)`; `04-spec-time-model/spec-time-model.md#3.2 Правило Т — тождество только по якорю`; `04-spec-time-model/spec-time-model.md#4.4 Порядок восстанавливается ЧТЕНИЕМ. Чинить файл ЗАПРЕЩЕНО`; `04-spec-time-model/spec-time-model.md#6.1 Исправление — ещё один аппенд, и вся дисциплина применяется без изменений`; `04-spec-time-model/time-model.yaml#multi_writer`
- история и границы тех же предков: `04-spec-time-model/time-model.yaml#boundaries` (boundary); `04-spec-time-model/time-model.yaml#escalations` (history)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-forms` — `03-spec-type-schemas/spec-type-schemas.md:1066`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Класс записи и поля жизненного цикла`; `03-spec-type-schemas/spec-type-schemas.md#1.1 Определение и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#2.1 Что это и в каком состоянии корпус`; `03-spec-type-schemas/spec-type-schemas.md#9.1 Определение и граница с соседями`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-sections` — `03-spec-type-schemas/spec-type-schemas.md:1117`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.3 Потолок секционной нормы: почему обязательная секция не может быть ERROR'ом`; `03-spec-type-schemas/section-ids.yaml#kernel_section_ids`; `03-spec-type-schemas/section-ids.yaml#introduced_by_ticket_forms`; `03-spec-type-schemas/section-ids.yaml#introduced_by_repo_type_extension`; `03-spec-type-schemas/section-ids.yaml#introduced_by_kernel_v2`; `03-spec-type-schemas/section-ids.yaml#section_anchor`; `03-spec-type-schemas/ticket-fields.yaml#rules`; `06-conformance-full/00-scope-coverage-and-dispositions.md#3.1 REQ-026 — исход (i): машинный носитель секции. АМЕНДМЕНТ-D06-01`; `03-spec-type-schemas/section-ids.yaml#normativity`; `01-spec-kernel/spec-kernel.md#05.1.3 Секции тела: семантические id, не литералы`; `01-spec-kernel/spec-kernel.md#8. DECISION-03 — судьба ключей Origin / Filed / Code`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/ticket-fields.yaml#not_validated` (boundary); `03-spec-type-schemas/ticket-fields.yaml#rules.kernel_grammars_not_redefined` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-relations` — `03-spec-type-schemas/spec-type-schemas.md:1168`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.5 Отношения — по id реестра; правило имени поля-носителя`; `03-spec-type-schemas/spec-type-schemas.md#1.9 Отношения TASK`; `03-spec-type-schemas/spec-type-schemas.md#2.4 Отношения ISSUE`; `03-spec-type-schemas/spec-type-schemas.md#2.2 Форма 02.1.2 — что ссылкой НЕ является`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Три кандидата и почему выбран третий`; `03-spec-type-schemas/spec-type-schemas.md#3.2 Внутренняя цель против внешней — два носителя, одно правило`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#4.3 «Двусторонняя ссылка» REQ-080 — требование к ЧТЕНИЮ, не к хранению (решение alex 2026-08-23)`; `03-spec-type-schemas/spec-type-schemas.md#5.1 Пояснения, которых таблица не вмещает`; `03-spec-type-schemas/spec-type-schemas.md#6. Правило закрытия контейнера работы (механизм для REQ-080)`; `03-spec-type-schemas/relations.yaml#rules`; `03-spec-type-schemas/relations.yaml#link_forms`; `03-spec-type-schemas/relations.yaml#relations`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.8 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#6.4 Перечисление в свидетельстве завершения — что формат может и чего не может` (boundary); `03-spec-type-schemas/spec-type-schemas.md#7. Заявки к alex — все закрыты` (history); `03-spec-type-schemas/spec-type-schemas.md#8. Границы проверки — сводно` (boundary); `03-spec-type-schemas/relations.yaml#out_of_registry` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-task` — `03-spec-type-schemas/spec-type-schemas.md:1251`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.2 Стадия — статусом ядра`; `03-spec-type-schemas/spec-type-schemas.md#1.3 Роли: автор, исполнитель, чей ход, кто решает`; `03-spec-type-schemas/spec-type-schemas.md#1.4 Вид и метки`; `03-spec-type-schemas/spec-type-schemas.md#1.7 Тело`; `03-spec-type-schemas/spec-type-schemas.md#1.8 `fixed_in` — где выдан результат`; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`; `03-spec-type-schemas/ticket-fields.yaml#shared_fields`
- история и границы тех же предков: `03-spec-type-schemas/ticket-fields.yaml#not_validated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-task-design` — `03-spec-type-schemas/spec-type-schemas.md:1336`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.5 Вид `design``; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-task-hotfix` — `03-spec-type-schemas/spec-type-schemas.md:1426`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.6 Режим hotfix — срочная точечная правка`; `03-spec-type-schemas/ticket-fields.yaml#types.TASK`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-issue` — `03-spec-type-schemas/spec-type-schemas.md:1633`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.2 Поля ISSUE`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Статус: «снят» — не удаление`; `03-spec-type-schemas/spec-type-schemas.md#2.5 Скелет тела ISSUE`; `03-spec-type-schemas/ticket-fields.yaml#types.ISSUE`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ REQ-109 (вердикт alex Q9, судейство decide-common-fields, 2026-09-19; внесено D10 T2»

### Блок `wp-incident` — `03-spec-type-schemas/spec-type-schemas.md:1782`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#3.2 Поля шапки`; `03-spec-type-schemas/spec-type-schemas.md#3.3 Раскладка dual-clock и длительности — ПОФИЛЬДНО`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Латентная длительность — ПРОЗА, не поле (вердикт alex 2026-08-25)`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Скелет тела INCIDENT`; `03-spec-type-schemas/spec-type-schemas.md#3.6 «Что не восстановлено» — секция, которой нет ни у одной другой формы`; `03-spec-type-schemas/spec-type-schemas.md#3.7 Таблица предотвращения, отношение INCIDENT → TASK и «мина по дороге»`; `03-spec-type-schemas/spec-type-schemas.md#3.8 Отношения и разобранный образец`; `03-spec-type-schemas/ticket-fields.yaml#types.INCIDENT`; `01-spec-kernel/spec-kernel.md#02.2.4 Единственное узаконенное исключение: dual-clock шапки INCIDENT`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-epic` — `03-spec-type-schemas/spec-type-schemas.md:2036`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#4.2 Поля EPIC`; `03-spec-type-schemas/spec-type-schemas.md#4.4 Тело EPIC — обязательно, и это проверяется механически`; `03-spec-type-schemas/spec-type-schemas.md#4.5 Ничего счётного — механическая приёмка`; `03-spec-type-schemas/spec-type-schemas.md#4.6 EPIC как контейнер ранней стадии`; `03-spec-type-schemas/ticket-fields.yaml#types.EPIC`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-request-pii` — `03-spec-type-schemas/spec-type-schemas.md:2368`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.2 Персональные данные — правило типа`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-request-origin-pii` — `03-spec-type-schemas/spec-type-schemas.md:2372`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.2 Персональные данные — правило типа`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-request` — `03-spec-type-schemas/spec-type-schemas.md:2394`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.3 Канал, ссылка на заявителя, срок`; `03-spec-type-schemas/spec-type-schemas.md#9.1 Определение и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Стадии, чей ход, кто решает`; `03-spec-type-schemas/spec-type-schemas.md#9.5 Ответ заявителю и исход`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Обращение → работа`; `03-spec-type-schemas/spec-type-schemas.md#9.7 Тело`; `03-spec-type-schemas/ticket-fields.yaml#types.REQUEST`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-doc` — `03-spec-type-schemas/spec-type-schemas.md:2681`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.1 Что это и граница с соседями`; `03-spec-type-schemas/spec-type-schemas.md#1.3.2 `provenance` — единственная секционная норма главы`; `03-spec-type-schemas/spec-type-schemas.md#0.1 Классы записей и поля жизненного цикла`; `03-spec-type-schemas/spec-type-schemas.md#1.2.1 Ни одного нового обязательного поля`; `03-spec-type-schemas/spec-type-schemas.md#1.2.2 Полуюнит `status` без `status_note` — пробел ядра ЗАКРЫТ вердиктом`; `03-spec-type-schemas/spec-type-schemas.md#1.2.3 `kind` — единственное новое поле (REQ-075)`; `03-spec-type-schemas/spec-type-schemas.md#1.3.1 Скелета нет, и это решение, а не пропуск`; `03-spec-type-schemas/doc-fields.yaml#doc`; `03-spec-type-schemas/doc-fields.yaml#rules`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#1.2.4 След REQ-075: происхождение и отклонённые кандидаты` (history); `03-spec-type-schemas/doc-fields.yaml#d04_boundary` (boundary); `03-spec-type-schemas/doc-fields.yaml#not_validated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-doc-relations` — `03-spec-type-schemas/spec-type-schemas.md:2832`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#1.4 Отношения DOC`; `03-spec-type-schemas/spec-type-schemas.md#0.4 Отношения — по id реестра; имя поля-носителя`; `03-spec-type-schemas/spec-type-schemas.md#1.4.1 `epic_membership_doc` — членство живёт в ребёнке`; `03-spec-type-schemas/spec-type-schemas.md#1.4.2 `reclassified_as` требует `RETRACTED` — обязанность приходит от реестра, не от схемы`; `03-spec-type-schemas/spec-type-schemas.md#2.2 Форма 02.1.2 — что ссылкой НЕ является`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Три кандидата и почему выбран третий`; `03-spec-type-schemas/spec-type-schemas.md#3.2 Внутренняя цель против внешней — два носителя, одно правило`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#4.3 «Двусторонняя ссылка» REQ-080 — требование к ЧТЕНИЮ, не к хранению (решение alex 2026-08-23)`; `03-spec-type-schemas/spec-type-schemas.md#5.1 Пояснения, которых таблица не вмещает`; `03-spec-type-schemas/spec-type-schemas.md#6. Правило закрытия контейнера работы (механизм для REQ-080)`; `03-spec-type-schemas/relations.yaml#rules`; `03-spec-type-schemas/relations.yaml#link_forms`; `03-spec-type-schemas/relations.yaml#relations`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#6.4 Перечисление в свидетельстве завершения — что формат может и чего не может` (boundary); `03-spec-type-schemas/spec-type-schemas.md#7. Заявки к alex — все закрыты` (history); `03-spec-type-schemas/spec-type-schemas.md#8. Границы проверки — сводно` (boundary); `03-spec-type-schemas/relations.yaml#out_of_registry` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-att-path` — `03-spec-type-schemas/spec-type-schemas.md:4211`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.1 Грамматика пути`; `03-spec-type-schemas/spec-type-schemas.md#2.3 Вложения комментов`; `03-spec-type-schemas/spec-type-schemas.md#3.1 Грамматика`; `03-spec-type-schemas/spec-type-schemas.md#3.3 ASCII: правило и его измеренная причина`; `03-spec-type-schemas/spec-type-schemas.md#3.4 Куда девается исходное имя`; `03-spec-type-schemas/spec-type-schemas.md#3.5 Длина пути`; `03-spec-type-schemas/spec-type-schemas.md#4.1 Две легальные формы, и они не конкурируют`; `03-spec-type-schemas/attachments.yaml#layout`; `03-spec-type-schemas/attachments.yaml#owners`; `03-spec-type-schemas/attachments.yaml#filename`; `03-spec-type-schemas/attachments.yaml#link_forms`; `01-spec-kernel/spec-kernel.md#04.3.1 Грамматика`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#4.3 Что глава про ссылку НЕ говорит` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ATTACH-SEED (decide D-A) — профиль обязан быть»

### Блок `wp-att-lines` — `03-spec-type-schemas/spec-type-schemas.md:4306`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#2.4 Вложения контейнеров строчных форм (JOURNAL / TIMESHEET)`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-att-commit` — `03-spec-type-schemas/spec-type-schemas.md:4595`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#5.1 Правило`; `03-spec-type-schemas/spec-type-schemas.md#2.6 Вложение неизменяемо`; `03-spec-type-schemas/spec-type-schemas.md#6.3 Маршрут: куда писатель кладёт файл`; `03-spec-type-schemas/spec-type-schemas.md#6.1 Два хранилища и только два`; `03-spec-type-schemas/spec-type-schemas.md#6.4 Материалы внешних людей`; `03-spec-type-schemas/spec-type-schemas.md#6.5 Несохранённый файл: пометка и ответ`; `03-spec-type-schemas/attachments.yaml#one_commit_invariant`; `03-spec-type-schemas/attachments.yaml#immutability`; `03-spec-type-schemas/attachments.yaml#soft_limit`; `03-spec-type-schemas/attachments.yaml#stores`; `03-spec-type-schemas/attachments.yaml#routing`; `03-spec-type-schemas/attachments.yaml#routing.external_origin`; `03-spec-type-schemas/attachments.yaml#unsaved`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#6.7 Что порогом СОЗНАТЕЛЬНО не задано` (boundary); `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary); `03-spec-type-schemas/attachments.yaml#soft_limit.cumulative_limits` (boundary)
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D20 T1: прежняя буква запрещала только движение пути; правка байт по месту»; «[АМЕНДМЕНТ D20 T1 2026-10-05: прежняя редакция заводила настройку заказчика `external_media`»

### Блок `wp-att-store` — `03-spec-type-schemas/spec-type-schemas.md:4963`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#9.1 Носитель: файл по пути вложения`; `03-spec-type-schemas/spec-type-schemas.md#9.3 Грамматика указателя`; `03-spec-type-schemas/spec-type-schemas.md#9.4 Ключ объекта`; `03-spec-type-schemas/spec-type-schemas.md#9.6 Состояния и законные переходы`; `03-spec-type-schemas/spec-type-schemas.md#9.9 Git LFS не поддерживается`; `03-spec-type-schemas/attachments.yaml#pointer`; `03-spec-type-schemas/attachments.yaml#object_key`; `03-spec-type-schemas/attachments.yaml#states`; `03-spec-type-schemas/attachments.yaml#lfs`
- история и границы тех же предков: `03-spec-type-schemas/attachments.yaml#requirements_deferred` (boundary); `03-spec-type-schemas/attachments.yaml#contracts` (boundary); `03-spec-type-schemas/attachments.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-ticket-repo-types` — `03-spec-type-schemas/spec-type-schemas.md:5473`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Формула форм: разрешение напряжения с REQ-002`; `03-spec-type-schemas/spec-type-schemas.md#1.2 Сужение ядрового набора`; `03-spec-type-schemas/spec-type-schemas.md#4. Паттерн `x_proposed_*` — штатный, и это его единственный дом`; `03-spec-type-schemas/spec-type-schemas.md#14. Схема ядра 2: что меняется для писателя и для конфига`; `03-spec-type-schemas/spec-type-schemas.md#15. Коллизии конфига с ядром v2`; `03-spec-type-schemas/types-config-schema.yaml#kernel_block.types_enabled`; `03-spec-type-schemas/types-config-schema.yaml#proposed_pattern`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.2 Четыре дыры GAP-REPO-EXT-* — где закрыта каждая и где граница` (boundary); `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary); `03-spec-type-schemas/spec-type-schemas.md#5. Форма HOTFIX схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#6. Форма DESIGN схемы 1 (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#7. Сверка констант референс-валидатора (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#8. FIND — миграция вместо типа (история)` (history); `03-spec-type-schemas/spec-type-schemas.md#10. Контракты, границы, трассируемость` (boundary); `03-spec-type-schemas/spec-type-schemas.md#11. Стандартная поставка TASK / REQUEST (этап 1) — история` (history); `03-spec-type-schemas/spec-type-schemas.md#12. TASK — переехал в ядро` (history); `03-spec-type-schemas/spec-type-schemas.md#13. REQUEST — переехал в ядро` (history); `03-spec-type-schemas/types-config-schema.yaml#delegated` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-doc-repo-types` — `03-spec-type-schemas/spec-type-schemas.md:5477`

- покрывает: `03-spec-type-schemas/spec-type-schemas.md#0.1 Формула форм: разрешение напряжения с REQ-002`; `03-spec-type-schemas/spec-type-schemas.md#1.2 Сужение ядрового набора`; `03-spec-type-schemas/types-config-schema.yaml#kernel_block.types_enabled`
- история и границы тех же предков: `03-spec-type-schemas/spec-type-schemas.md#0.2 Четыре дыры GAP-REPO-EXT-* — где закрыта каждая и где граница` (boundary); `03-spec-type-schemas/spec-type-schemas.md#0.6 Что эта глава НЕ определяет` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-index-read` — `08-generated-index/01-index-and-ledger.md:342`

- покрывает: `08-generated-index/01-index-and-ledger.md#12. Что читает профиль агента`; `08-generated-index/01-index-and-ledger.md#1. Два артефакта: присвоенный факт и производная`; `08-generated-index/01-index-and-ledger.md#2. Пути, атрибуты git, слияние`; `08-generated-index/index-form.yaml#artifacts`; `08-generated-index/index-form.yaml#paths`; `08-generated-index/index-form.yaml#agent_read_rules`
- история и границы тех же предков: `08-generated-index/01-index-and-ledger.md#15. Трассируемость и границы` (boundary); `08-generated-index/index-form.yaml#performance_note` (boundary); `08-generated-index/index-form.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-validator-forms` — `05-validator-core/01-invocation-interface.md:440`

- покрывает: `05-validator-core/01-invocation-interface.md#2.8 Какую форму зовёт писатель записи перед коммитом`; `05-validator-core/01-invocation-interface.md#3.1 Пять исходов, из них четыре обязательных и один отдельный`; `05-validator-core/validator-interface.yaml#return_codes`
- история и границы тех же предков: `05-validator-core/validator-interface.yaml#verdicts_as_inputs` (history); `05-validator-core/validator-interface.yaml#boundaries` (boundary)
- марки амендментов покрытых разделов: —

### Блок `wp-aon-machine-writer` — `10-spec-assembly/02-agent-operational-norm.md:19`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#1. Агент — машинный писатель`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-when` — `10-spec-assembly/02-agent-operational-norm.md:42`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#3. Когда писать и когда спрашивать`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate` — `10-spec-assembly/02-agent-operational-norm.md:63`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-standalone` — `10-spec-assembly/02-agent-operational-norm.md:67`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-validate-pair` — `10-spec-assembly/02-agent-operational-norm.md:71`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#4. Проверка валидатором до коммита`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit` — `10-spec-assembly/02-agent-operational-norm.md:88`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-commit-standalone` — `10-spec-assembly/02-agent-operational-norm.md:92`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#5. Фиксация: коммит и push сразу`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-comment-time` — `10-spec-assembly/02-agent-operational-norm.md:102`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#6. Время заголовка коммента`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Блок `wp-aon-read-once` — `10-spec-assembly/02-agent-operational-norm.md:119`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#7. Чтение профиля`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: «[АМЕНДМЕНТ D10 T26 2026-10-26: решение alex по развилке F-ROUTE-GREP (decide D-B п. 4) — агент Sonnet искал»

### Блок `wp-aon-secrets` — `10-spec-assembly/02-agent-operational-norm.md:130`

- покрывает: `10-spec-assembly/02-agent-operational-norm.md#8. Секреты`
- история и границы тех же предков: —
- марки амендментов покрытых разделов: —

### Деферралы профиля `full`

- `find` (предмет `ticket`): вердикт alex Q4 «б» 2026-09-20: FIND — репозиторное расширение, подрядчику не нужно; формулировка 2026-09-28 (окно D10, решение alex по аудиту избыточности тикетов): «находка» по слову человека — ISSUE, FIND не тип; T25 2026-10-16 (аудит astra Б-02): имя FIND не резервируется (03 §15.4, решение alex 2026-10-09) — оговорка про объявленный тип заказчика
