import csv, sqlite3, threading, re
from datetime import datetime


DB_PATH = 'teachers_grades.db'
DB_LOCK = threading.Lock()


# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: безопасное имя столбца

def col_name(criterion: str) -> str:
    """Преобразует текст критерия в безопасное имя столбца SQLite."""
    name = criterion.lower()
    name = re.sub(r'[^a-zа-яё0-9\s]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    if not name:
        name = 'criterion'
    if name[0].isdigit():
        name = 'c_' + name
    return name


# ВАЛИДАЦИЯ ОЦЕНКИ

def is_valid_grade(value) -> bool:
    """Возвращает True, если значение — допустимая оценка ('1'–'5') или None."""
    return value is None or value in ('1', '2', '3', '4', '5')


# CSV: студенты

def load_users(filename: str = 'students.csv') -> list:
    """Читает CSV-файл студентов. Возвращает список словарей: short_user_name, user_name, password, group."""
    users = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                users.append({
                    'short_user_name': row['short_user_name'].strip(),
                    'user_name': row['user_name'].strip(),
                    'password': row['password'].strip(),
                    'group': row['group'].strip(),
                })
    except FileNotFoundError:
        print(f"Файл {filename} не найден.")
    except Exception as e:
        print(f'Ошибка чтения {filename}: {e}')
    return users


def authenticate_user(users: list, login: str, password: str) -> dict | None:
    """Ищет пользователя по short_user_name и паролю. Возвращает словарь пользователя или None."""
    for user in users:
        if user['short_user_name'] == login and user['password'] == password:
            return user
    return None


# CSV: преподаватели

def load_teachers_for_group(group_id: str, filename: str = 'teachers.csv') -> list:
    """Возвращает список уникальных преподавателей группы, отсортированных по имени.
    Каждый элемент: {'teacher': str, 'subject': str}."""
    teachers_data = []
    seen = set()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['group'].strip() == group_id:
                    name = row['teacher'].strip()
                    if name not in seen:
                        seen.add(name)
                        teachers_data.append({
                            'teacher': name,
                            'subject': row['subject'].strip()
                        })
    except FileNotFoundError:
        print(f"Файл {filename} не найден.")
    except Exception as e:
        print(f'Ошибка чтения {filename}: {e}')
    teachers_data.sort(key=lambda x: x['teacher'])
    return teachers_data


def get_teacher_subjects(group_id: str, filename: str = 'teachers.csv') -> dict:
    """Возвращает словарь {teacher_name: [subject1, subject2, ...]} для указанной группы."""
    result = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['group'].strip() == group_id:
                    t = row['teacher'].strip()
                    s = row['subject'].strip()
                    if t not in result:
                        result[t] = []
                    if s not in result[t]:
                        result[t].append(s)
    except Exception as e:
        print(f'Ошибка чтения {filename}: {e}')
    return result


def get_teachers_sorted(group_id: str, filename: str = 'teachers.csv') -> list:
    """Возвращает отсортированный список имён преподавателей группы."""
    teachers, seen = [], set()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['group'].strip() == group_id:
                    t = row['teacher'].strip()
                    if t not in seen:
                        seen.add(t)
                        teachers.append(t)
    except Exception:
        pass
    teachers.sort()
    return teachers


# CSV: критерии оценивания

def load_criteria(filename: str = 'criterion.csv') -> list:
    """Читает и возвращает список критериев оценивания."""
    criteria = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                criteria.append(row['criterion'].strip())
    except FileNotFoundError:
        print(f"Файл {filename} не найден.")
    except Exception as e:
        print(f'Ошибка чтения {filename}: {e}')
    return criteria


# SQLITE: подключение и схема

def get_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Открывает и возвращает соединение с SQLite."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_existing_columns(conn: sqlite3.Connection) -> set:
    """Возвращает множество имён существующих столбцов таблицы teachers_grades."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(teachers_grades)")
    return {row['name'] for row in cur.fetchall()}


def _sync_criteria_columns(conn: sqlite3.Connection, criteria: list) -> None:
    """Добавляет новые столбцы критериев в БД (без удаления старых)."""
    existing = _get_existing_columns(conn)
    cur = conn.cursor()
    for criterion in criteria:
        cname = col_name(criterion)
        if cname not in existing:
            cur.execute(f'ALTER TABLE teachers_grades ADD COLUMN "{cname}" TEXT DEFAULT NULL')
            print(f"БД: добавлен столбец '{cname}'")
    conn.commit()


def init_db(db_path: str = DB_PATH) -> None:
    """Создаёт таблицу при первом запуске и синхронизирует столбцы критериев."""
    criteria = load_criteria()
    with DB_LOCK:
        conn = get_db(db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS teachers_grades (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                time      TEXT DEFAULT NULL,
                "group"   TEXT NOT NULL,
                user_name TEXT NOT NULL,
                teacher   TEXT NOT NULL,
                subject   TEXT NOT NULL,
                UNIQUE(user_name, teacher, subject)
            )
        ''')
        conn.commit()
        existing = _get_existing_columns(conn)
        if 'time' not in existing:
            conn.execute('ALTER TABLE teachers_grades ADD COLUMN time TEXT DEFAULT NULL')
            conn.commit()
        _sync_criteria_columns(conn, criteria)
        conn.close()
    print(f"БД инициализирована: {db_path}")


def ensure_criteria_columns() -> list:
    """Проверяет и добавляет новые критерии в БД. Возвращает актуальный список."""
    criteria = load_criteria()
    with DB_LOCK:
        conn = get_db()
        _sync_criteria_columns(conn, criteria)
        conn.close()
    return criteria


# SQLITE: оценки

def load_grades_from_db(user_name: str, teacher: str, subject: str, criteria: list, db_path: str = DB_PATH) -> dict:
    """Загружает оценки из БД для связки user_name + teacher + subject.Возвращает dict {col_name: value_or_empty_string}."""
    with DB_LOCK:
        conn = get_db(db_path)
        cur = conn.cursor()
        cur.execute(
            'SELECT * FROM teachers_grades WHERE user_name=? AND teacher=? AND subject=?',
            (user_name, teacher, subject)
        )
        row = cur.fetchone()
        existing_cols = _get_existing_columns(conn)
        conn.close()

    result = {}
    for criterion in criteria:
        cname = col_name(criterion)
        if row and cname in existing_cols:
            val = row[cname]
            result[cname] = val if val is not None else ''
        else:
            result[cname] = ''
    return result


def save_grades_to_db(group: str, user_name: str, teacher: str, subject: str, grades_dict: dict, db_path: str = DB_PATH) -> None:
    """Сохраняет или обновляет оценки в БД. Пустая строка в grades_dict → NULL в базе. Всегда обновляет поле time."""
    if not teacher or not subject:
        raise ValueError("teacher и subject не могут быть пустыми")

    now = datetime.now().strftime('%d:%m:%y')
    with DB_LOCK:
        conn = get_db(db_path)
        cur = conn.cursor()

        cur.execute(
            'SELECT id FROM teachers_grades WHERE user_name=? AND teacher=? AND subject=?',
            (user_name, teacher, subject)
        )
        existing = cur.fetchone()
        clean = {k: (v if v else None) for k, v in grades_dict.items()}

        if existing:
            update_data = {'time': now, **clean}
            set_parts = ', '.join([f'"{k}"=?' for k in update_data])
            vals = list(update_data.values()) + [user_name, teacher, subject]
            cur.execute(
                f'UPDATE teachers_grades SET {set_parts} '
                f'WHERE user_name=? AND teacher=? AND subject=?',
                vals
            )
        else:
            base_cols = ['"group"', 'user_name', 'teacher', 'subject', 'time']
            base_vals = [group, user_name, teacher, subject, now]
            crit_cols = [f'"{k}"' for k in clean]
            crit_vals = list(clean.values())
            all_cols = ', '.join(base_cols + crit_cols)
            placeholders = ', '.join(['?'] * (len(base_cols) + len(crit_cols)))
            cur.execute(
                f'INSERT INTO teachers_grades ({all_cols}) VALUES ({placeholders})',
                base_vals + crit_vals
            )
        conn.commit()
        conn.close()


# SQLITE: чтение таблицы (для админа)

def get_db_table_data(name: str) -> tuple:
    """Читает таблицу из SQLite-файла name.db. Возвращает (headers, rows)."""
    db_file = f'{name}.db'
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [r[0] for r in cur.fetchall()]
        if not tables:
            conn.close()
            return [], []
        table = name if name in tables else tables[0]
        cur.execute(f'SELECT * FROM "{table}"')
        rows_raw = cur.fetchall()
        if rows_raw:
            headers = list(rows_raw[0].keys())
        elif cur.description:
            headers = [d[0] for d in cur.description]
        else:
            cur.execute(f'PRAGMA table_info("{table}")')
            headers = [r[1] for r in cur.fetchall()]
        rows = [dict(r) for r in rows_raw]
        conn.close()
        return headers, rows
    except Exception as e:
        print(f'Ошибка чтения {db_file}: {e}')
        return [], []


# CSV: чтение файла (для админа)

def get_csv_data(name: str) -> tuple:
    """Читает CSV-файл name.csv. Возвращает (headers, rows)."""
    try:
        with open(f'{name}.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            headers = list(reader.fieldnames) if reader.fieldnames else []
            rows = [dict(row) for row in reader]
        return headers, rows
    except FileNotFoundError:
        return [], []
    except Exception as e:
        print(f'Ошибка чтения {name}.csv: {e}')
        return [], []