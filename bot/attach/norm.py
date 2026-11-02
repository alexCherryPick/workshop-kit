# -*- coding: utf-8 -*-
# СГЕНЕРИРОВАНО bot/kit/gen_attach_norm.py из spec/03-spec-type-schemas/attachments.yaml — НЕ ПРАВИТЬ РУКАМИ.
# Перегенерация: python3 bot/kit/gen_attach_norm.py; проверка: bot/tests/test_attach_norm.py.
"""Реестры нормы вложений (D20 T1) для адаптера D20 T2 — только данные, без логики."""

SOURCE_PATH = 'spec/03-spec-type-schemas/attachments.yaml'
SOURCE_SHA256 = '2162e2f2cafb081c3fd604890309d63351c7b2a32c12616ac29ce70f6f256181'
SPEC = 'cherrypick-workshop-format'
CHAPTER = '04-attachments'
SCHEMA_VERSION = 2
PATH_GRAMMAR = 'attachments/<record-id>/<attachment-filename>'
PATH_PATTERN = '^attachments/[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/[^/]+$'
RESERVED_DIR = 'attachments'
FILENAME_PATTERN = '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(-[a-z0-9]+(-[a-z0-9]+)*)?\\.[a-z0-9]{1,8}$'
SLUG_PATTERN = '^[a-z0-9]+(-[a-z0-9]+)*$'
SLUG_MAX_LEN = 40
EXT_PATTERN = '^[a-z0-9]{1,8}$'
GIT_THRESHOLD_DEFAULT = 8000000
THRESHOLD_COMPARISON = 'greater_than'
ROUTING_STEPS = (
    (1, 'not obtained', 'unsaved', 'source-refused'),
    (2, 'байты начинаются pointer.magic_prefix или lfs.signature_prefix', 'storage_or_unsaved', None),
    (3, 'size <= threshold', 'git', None),
    (4, 'иначе', 'storage_or_unsaved', None),
)
ROUTING_OUTCOMES = ('git', 'storage', 'storage_or_unsaved', 'unsaved')
POINTER_MAGIC_PREFIX = 'workshop-attachment-pointer '
POINTER_MAGIC_LINE = 'workshop-attachment-pointer 1'
POINTER_FIRST_LINE_PATTERN = '^workshop-attachment-pointer [1-9][0-9]*$'
POINTER_VERSION_PATTERN = '^[1-9][0-9]*$'
POINTER_KNOWN_VERSIONS = ('1',)
POINTER_MAX_BYTES = 1024
POINTER_ENCODING = 'ASCII 0x20..0x7E и LF; без CR, без BOM, без табуляции, без пустых строк, без пробелов в конце строки; ровно один LF в конце'
POINTER_FIELD_ORDER = ('key', 'sha256', 'size', 'media-type', 'reason', 'source')
POINTER_FIELD_PATTERNS = (
    ('key', '^sha256/[0-9a-f]{64}$'),
    ('sha256', '^[0-9a-f]{64}$'),
    ('size', '^(0|[1-9][0-9]{0,15})$'),
    ('media-type', '^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$'),
    ('reason', '^(no-storage|source-refused|upload-failed|secret|erasure)$'),
    (
        'source',
        '^(https://[^/?#@: ]+(/[^?#@ ]*)?|urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$',
    ),
)
POINTER_FIELD_MAX_LEN = (
    ('source', 512),
)
POINTER_PRESENCE = (
    (
        'stored',
        (
            ('key', 'R'),
            ('sha256', 'R'),
            ('size', 'R'),
            ('media-type', 'R'),
            ('reason', 'X'),
            ('source', 'O'),
        ),
    ),
    (
        'pending',
        (
            ('key', 'R'),
            ('sha256', 'R'),
            ('size', 'R'),
            ('media-type', 'R'),
            ('reason', 'X'),
            ('source', 'R'),
        ),
    ),
    (
        'unsaved',
        (
            ('key', 'X'),
            ('sha256', 'O'),
            ('size', 'O'),
            ('media-type', 'O'),
            ('reason', 'R'),
            ('source', 'R'),
        ),
    ),
    (
        'withdrawn',
        (
            ('key', 'X'),
            ('sha256', 'X'),
            ('size', 'X'),
            ('media-type', 'X'),
            ('reason', 'R'),
            ('source', 'X'),
        ),
    ),
)
POINTER_PRESENCE_EXTRA = 'у unsaved при sha256 обязателен size (у кого были байты, тот знает размер)'
OBJECT_KEY_DERIVATION = 'sha256/<sha256>'
STATES = (
    (
        'git',
        'bytes',
        (),
    ),
    (
        'stored',
        'pointer',
        (),
    ),
    (
        'pending',
        'pointer',
        (),
    ),
    (
        'unsaved',
        'pointer',
        ('no-storage', 'source-refused', 'upload-failed'),
    ),
    (
        'withdrawn',
        'pointer',
        ('secret', 'erasure'),
    ),
)
TRANSITIONS = (
    ('pending', 'stored'),
    ('pending', 'unsaved'),
    ('unsaved', 'stored'),
    ('unsaved', 'git'),
    ('stored', 'withdrawn'),
    ('pending', 'withdrawn'),
    ('unsaved', 'withdrawn'),
    ('git', 'withdrawn'),
)
TRANSITION_RULES = (
    ('pending', 'stored', 'меняется только строка state; остальные строки побайтово те же'),
    (
        'pending',
        'unsaved',
        'reason upload-failed; key снят; sha256, size, media-type, source — побайтово те же',
    ),
    (
        'unsaved',
        'stored',
        'досохранение; sha256 и size, если были, ОБЯЗАНЫ совпасть; source сохраняется',
    ),
    (
        'unsaved',
        'git',
        'досохранение в git, если маршрут на момент досохранения даёт git; sha256 байт ОБЯЗАН совпасть с записанным, если он был',
    ),
    (
        'stored',
        'withdrawn',
        'reason secret | erasure; объект по key удалён из хранилища до коммита перехода',
    ),
    (
        'pending',
        'withdrawn',
        'reason secret | erasure; объект по key удалён, если он есть (загрузка могла завершиться до перехода в stored), — так же, как у stored',
    ),
    (
        'unsaved',
        'withdrawn',
        'reason secret | erasure (например, удаление ссылки на источник по требованию); key нет — удалять в хранилище нечего',
    ),
    (
        'git',
        'withdrawn',
        'видимая пометка изъятия; само изъятие байт из git — только переписыванием истории (immutability.only_legal_destructive_case)',
    ),
)
DIFF_PARENT_RULE = 'судится путь, существующий до и после коммита под тем же именем (D/R — E-ATT-PATH-MUTATED); корневой коммит — старого содержимого нет; содержимое законно, если для КАЖДОГО родителя, где путь есть, оно тождественно содержимому этого родителя или получается из него законным переходом transitions (одиночный коммит — частный случай с одним родителем); поля сравниваются только с родителями-указателями по условиям строки transitions; родитель-байты — только побайтовое тождество или git -> withdrawn; результат-байты против родителя unsaved — unsaved -> git с равным sha256'
TERMINAL_STATES = ('withdrawn',)
PENDING_REQUIRES_DURABLE_QUEUE = 'полные байты — в очереди писателя вне git, переживающей перезапуск; очистка — после коммита stored; память процесса и эфемерная CI-джоба (бот в GitHub Actions) очередью не являются — тогда unsaved upload-failed'
WRITE_FAILURE_RULE = 'исход записи storage-unavailable или storage-denied: писатель с устойчивой очередью пишет pending и повторяет; без неё — unsaved (upload-failed)'
UNSAVED_REASONS = (
    ('no-storage', 'не сохранено — хранилище не настроено'),
    ('source-refused', 'не сохранено — источник не отдал файл'),
    ('upload-failed', 'не сохранено — загрузка не удалась'),
)
READ_ORDER = ('разобрать файл по пути', 'состояние', 'привязка', 'доступность', 'наличие', 'размер', 'sha256')
READ_OUTCOMES = (
    'in-git',
    'ok',
    'pending-upload',
    'object-missing',
    'size-mismatch',
    'sha-mismatch',
    'not-stored',
    'withdrawn',
    'storage-not-configured',
    'storage-denied',
    'storage-unavailable',
    'pointer-invalid',
    'pointer-version-unknown',
    'lfs-unsupported',
)
WRITE_OUTCOMES = (
    'uploaded',
    'already-present',
    'repaired',
    'bytes-mismatch',
    'storage-not-configured',
    'storage-denied',
    'storage-unavailable',
)
VERIFICATION_REQUIRES_LOCAL_HASH = True
READ_OUTCOME_MEANINGS = (
    ('in-git', 'по пути байты (не указатель этой главы и не указатель LFS); хранилище не участвует'),
    ('ok', 'stored или pending; объект есть, size и sha256 совпали'),
    ('pending-upload', 'pending; объекта нет — ещё не загружено, не дефект'),
    ('object-missing', 'stored; объекта нет'),
    ('size-mismatch', 'объект есть, размер не равен size'),
    ('sha-mismatch', 'размер равен, sha256 не совпал'),
    ('not-stored', 'unsaved; объекта не ждут; отдаются reason и source'),
    ('withdrawn', 'withdrawn; объекта не ждут; отдаётся reason'),
    ('storage-not-configured', 'stored или pending, привязки нет'),
    ('storage-denied', 'привязка есть, ключи отвергнуты; повтор не поможет'),
    (
        'storage-unavailable',
        'сеть, таймаут, отказ хранилища 5xx, обрыв тела ответа при GET (не size-mismatch), отсутствующий бакет — 404 NoSuchBucket, деталь no-such-bucket (бакет — свойство привязки и инфраструктуры, а не ключа); повтор, в том числе после исправления привязки, может помочь',
    ),
    (
        'pointer-invalid',
        'сигнатура указателя; первая строка не проходит pointer.first_line_pattern, либо версия 1 и грамматика не выполнена; адаптер не действует',
    ),
    (
        'pointer-version-unknown',
        'первая строка проходит pointer.first_line_pattern, версия не из pointer.known_versions; адаптер не действует',
    ),
    (
        'lfs-unsupported',
        'по пути указатель Git LFS (lfs.signature_prefix); адаптер не действует; клиент показывает «формат LFS не поддерживается»',
    ),
)
WRITE_OUTCOME_MEANINGS = (
    ('uploaded', 'объекта не было; записан и проверен (size, sha256)'),
    ('already-present', 'объект с теми же size и sha256 уже есть; записи не было (идемпотентность)'),
    ('repaired', 'под ключом лежали иные байты; перезаписаны верными и проверены'),
    ('bytes-mismatch', 'поданные байты не дают sha256 указателя; ничего не записано'),
    ('storage-not-configured', 'привязки нет; ничего не записано'),
    ('storage-denied', 'ключи отвергнуты; ничего не записано'),
    (
        'storage-unavailable',
        'сеть или хранилище, в том числе отсутствующий бакет (404 NoSuchBucket, деталь no-such-bucket); ничего не подтверждено',
    ),
)
CONFIG_FACTS = (
    'git_threshold_bytes',
    'storage.endpoint',
    'storage.region',
    'storage.bucket',
    'storage.key_prefix',
    'storage.credentials',
)
STATUS_FACTS = ('storage_configured', 'storage_probe_outcome', 'pointers_by_state', 'last_verification_failures')
LINK_FORMS = (
    ('markdown_embed', '![<подпись>](attachments/<id>/<имя>)', 'record_directory'),
    ('markdown_link', '[<подпись>](attachments/<id>/<имя>)', 'record_directory'),
    ('backtick_mention', '`<repo-relative путь>`', 'repository_root'),
)
CAPTION_ESCAPE_CHARS = ('[', ']', '\\')
GLOB_ALL_ATTACHMENTS = '**/attachments/*/*'
LFS_SIGNATURE_PREFIX = 'version https://git-lfs.github.com/spec/v1'
