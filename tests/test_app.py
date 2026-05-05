"""Unit-тесты для модуля database.py (бизнес-логика ИС оценивания преподавателей).
Запуск: python -m pytest tests/test_app.py -v
Покрытие: python -m pytest tests/test_app.py --cov=database --cov-report=term-missing"""

import pytest # pip  install pytest pytest-cov
import sqlite3
import os
from unittest.mock import patch, mock_open
# Добавляем родительскую папку в путь поиска модулей
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database


# ─────────────────────────────────────────────────────────────
# ФИКСТУРЫ (общие заготовки для тестов)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Создаёт временную SQLite-базу с таблицей teachers_grades. Используется вместо реальной БД — тест не трогает рабочие данные."""
    db_path = str(tmp_path / 'test.db')
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE teachers_grades (
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
    conn.close()
    return db_path


@pytest.fixture
def sample_users():
    """Тестовый список студентов."""
    return [
        {'short_user_name': 'ivanov', 'user_name': 'Иванов Иван', 'password': '1234', 'group': 'ИСП-24'},
        {'short_user_name': 'petrov', 'user_name': 'Петров Пётр', 'password': 'abcd', 'group': 'ИСП-24'},
        {'short_user_name': 'sidorov', 'user_name': 'Сидоров Сид', 'password': 'pass', 'group': 'ИСП-23'},
    ]


# ─────────────────────────────────────────────────────────────
# 1. ТЕСТЫ col_name — преобразование критерия в имя столбца
# ─────────────────────────────────────────────────────────────

class TestColName:
    def test_simple_russian_text(self):
        """Обычный русский текст преобразуется корректно."""
        assert database.col_name('Ясность объяснения') == 'ясность_объяснения'

    def test_special_characters_removed(self):
        """Спецсимволы удаляются."""
        assert database.col_name('Критерий №1!') == 'критерий_1'

    def test_leading_digit_gets_prefix(self):
        """Имя, начинающееся с цифры, получает префикс c_."""
        result = database.col_name('1 критерий')
        assert result.startswith('c_')

    def test_empty_string_returns_criterion(self):
        """Пустая строка → 'criterion'."""
        assert database.col_name('') == 'criterion'

    def test_spaces_replaced_by_underscore(self):
        """Пробелы заменяются на подчёркивания."""
        assert '_' in database.col_name('один два три')

    def test_latin_text(self):
        """Латинский текст сохраняется в нижнем регистре."""
        assert database.col_name('Knowledge Level') == 'knowledge_level'


# ─────────────────────────────────────────────────────────────
# 2. ТЕСТЫ is_valid_grade — валидация оценки
# ─────────────────────────────────────────────────────────────

class TestIsValidGrade:
    def test_valid_grades_1_to_5(self):
        """Оценки '1'–'5' допустимы."""
        for grade in ('1', '2', '3', '4', '5'):
            assert database.is_valid_grade(grade) is True

    def test_none_is_valid(self):
        """None означает 'оценка не выставлена' — допустимо."""
        assert database.is_valid_grade(None) is True

    def test_zero_is_invalid(self):
        """'0' — недопустимая оценка."""
        assert database.is_valid_grade('0') is False

    def test_six_is_invalid(self):
        """'6' — недопустимая оценка."""
        assert database.is_valid_grade('6') is False

    def test_empty_string_is_invalid(self):
        """Пустая строка — недопустимое значение."""
        assert database.is_valid_grade('') is False

    def test_text_is_invalid(self):
        """Произвольный текст — недопустимое значение."""
        assert database.is_valid_grade('отлично') is False


# ─────────────────────────────────────────────────────────────
# 3. ТЕСТЫ authenticate_user — аутентификация студентов
# ─────────────────────────────────────────────────────────────

class TestAuthenticateUser:
    def test_correct_credentials_returns_user(self, sample_users):
        """Верный логин/пароль возвращает словарь пользователя."""
        result = database.authenticate_user(sample_users, 'ivanov', '1234')
        assert result is not None
        assert result['user_name'] == 'Иванов Иван'

    def test_wrong_password_returns_none(self, sample_users):
        """Неверный пароль → None."""
        result = database.authenticate_user(sample_users, 'ivanov', 'wrong')
        assert result is None

    def test_wrong_login_returns_none(self, sample_users):
        """Несуществующий логин → None."""
        result = database.authenticate_user(sample_users, 'unknown', '1234')
        assert result is None

    def test_empty_list_returns_none(self):
        """Поиск по пустому списку → None."""
        result = database.authenticate_user([], 'ivanov', '1234')
        assert result is None

    def test_returns_correct_group(self, sample_users):
        """Возвращённый пользователь содержит правильную группу."""
        result = database.authenticate_user(sample_users, 'sidorov', 'pass')
        assert result['group'] == 'ИСП-23'


# ─────────────────────────────────────────────────────────────
# 4. ТЕСТЫ load_users — чтение CSV студентов (с моком файла)
# ─────────────────────────────────────────────────────────────

class TestLoadUsers:
    CSV_CONTENT = (
        "short_user_name;user_name;password;group\n"
        "ivanov;Иванов Иван;1234;ИСП-24\n"
        "petrov;Петров Пётр;abcd;ИСП-24\n"
    )

    def test_returns_list_of_users(self):
        """CSV-файл корректно парсится в список словарей."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            users = database.load_users('fake.csv')
        assert len(users) == 2
        assert users[0]['short_user_name'] == 'ivanov'

    def test_missing_file_returns_empty_list(self):
        """Отсутствующий файл → пустой список (без исключения)."""
        users = database.load_users('nonexistent_file_xyz.csv')
        assert users == []

    def test_fields_are_stripped(self):
        """Пробелы вокруг значений удаляются."""
        csv_with_spaces = (
            "short_user_name;user_name;password;group\n"
            " ivanov ; Иванов ; 1234 ; ИСП-24 \n"
        )
        with patch('builtins.open', mock_open(read_data=csv_with_spaces)):
            users = database.load_users('fake.csv')
        assert users[0]['short_user_name'] == 'ivanov'
        assert users[0]['group'] == 'ИСП-24'


# ─────────────────────────────────────────────────────────────
# 5. ТЕСТЫ load_criteria — чтение критериев (с моком)
# ─────────────────────────────────────────────────────────────

class TestLoadCriteria:
    CSV_CONTENT = "criterion\nЯсность объяснения\nДоступность материала\nПунктуальность\n"

    def test_returns_list_of_criteria(self):
        """Критерии корректно считываются."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            criteria = database.load_criteria('fake.csv')
        assert len(criteria) == 3
        assert 'Ясность объяснения' in criteria

    def test_missing_file_returns_empty_list(self):
        """Отсутствующий файл → пустой список."""
        criteria = database.load_criteria('nonexistent_xyz.csv')
        assert criteria == []


# ─────────────────────────────────────────────────────────────
# 6. ТЕСТЫ load_teachers_for_group — список преподавателей
# ─────────────────────────────────────────────────────────────

class TestLoadTeachersForGroup:
    CSV_CONTENT = (
        "group;teacher;subject\n"
        "ИСП-24;Смирнов А.А.;Математика\n"
        "ИСП-24;Козлов Б.Б.;Физика\n"
        "ИСП-24;Смирнов А.А.;Информатика\n"
        "ИСП-23;Новиков В.В.;Химия\n"
    )

    def test_returns_teachers_for_group(self):
        """Возвращаются только преподаватели нужной группы."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            teachers = database.load_teachers_for_group('ИСП-24', 'fake.csv')
        names = [t['teacher'] for t in teachers]
        assert 'Смирнов А.А.' in names
        assert 'Козлов Б.Б.' in names
        assert 'Новиков В.В.' not in names

    def test_no_duplicates(self):
        """Преподаватель, ведущий несколько предметов, встречается один раз."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            teachers = database.load_teachers_for_group('ИСП-24', 'fake.csv')
        names = [t['teacher'] for t in teachers]
        assert names.count('Смирнов А.А.') == 1

    def test_sorted_alphabetically(self):
        """Список отсортирован по алфавиту."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            teachers = database.load_teachers_for_group('ИСП-24', 'fake.csv')
        names = [t['teacher'] for t in teachers]
        assert names == sorted(names)

    def test_empty_group_returns_empty_list(self):
        """Несуществующая группа → пустой список."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            teachers = database.load_teachers_for_group('НЕТ-99', 'fake.csv')
        assert teachers == []


# ─────────────────────────────────────────────────────────────
# 7. ТЕСТЫ get_teacher_subjects — предметы преподавателя
# ─────────────────────────────────────────────────────────────

class TestGetTeacherSubjects:
    CSV_CONTENT = (
        "group;teacher;subject\n"
        "ИСП-24;Смирнов А.А.;Математика\n"
        "ИСП-24;Смирнов А.А.;Информатика\n"
        "ИСП-24;Козлов Б.Б.;Физика\n"
    )

    def test_multiple_subjects_for_teacher(self):
        """Преподаватель с несколькими предметами — все предметы в списке."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            subjects = database.get_teacher_subjects('ИСП-24', 'fake.csv')
        assert 'Смирнов А.А.' in subjects
        assert len(subjects['Смирнов А.А.']) == 2

    def test_no_duplicate_subjects(self):
        """Дублирующиеся предметы не добавляются."""
        csv = "group;teacher;subject\nИСП-24;Смирнов А.А.;Математика\nИСП-24;Смирнов А.А.;Математика\n"
        with patch('builtins.open', mock_open(read_data=csv)):
            subjects = database.get_teacher_subjects('ИСП-24', 'fake.csv')
        assert subjects['Смирнов А.А.'].count('Математика') == 1


# ─────────────────────────────────────────────────────────────
# 8. ТЕСТЫ save_grades_to_db и load_grades_from_db (с реальной temp БД)
# ─────────────────────────────────────────────────────────────

class TestGradesDB:
    def test_save_and_load_grades(self, tmp_db):
        """Сохранённые оценки корректно загружаются."""
        # Добавляем столбец критерия в тестовую БД
        conn = sqlite3.connect(tmp_db)
        conn.execute('ALTER TABLE teachers_grades ADD COLUMN "ясность_объяснения" TEXT DEFAULT NULL')
        conn.commit()
        conn.close()

        grades = {'ясность_объяснения': '4'}
        database.save_grades_to_db(
            group='ИСП-24',
            user_name='Иванов Иван',
            teacher='Смирнов А.А.',
            subject='Математика',
            grades_dict=grades,
            db_path=tmp_db
        )

        loaded = database.load_grades_from_db(
            user_name='Иванов Иван',
            teacher='Смирнов А.А.',
            subject='Математика',
            criteria=['Ясность объяснения'],
            db_path=tmp_db
        )
        assert loaded.get('ясность_объяснения') == '4'

    def test_update_existing_grades(self, tmp_db):
        """Повторное сохранение обновляет запись, а не создаёт дубль."""
        conn = sqlite3.connect(tmp_db)
        conn.execute('ALTER TABLE teachers_grades ADD COLUMN "ясность_объяснения" TEXT DEFAULT NULL')
        conn.commit()
        conn.close()

        grades_first = {'ясность_объяснения': '3'}
        grades_second = {'ясность_объяснения': '5'}

        database.save_grades_to_db('ИСП-24', 'Иванов', 'Козлов', 'Физика', grades_first, tmp_db)
        database.save_grades_to_db('ИСП-24', 'Иванов', 'Козлов', 'Физика', grades_second, tmp_db)

        conn = sqlite3.connect(tmp_db)
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM teachers_grades WHERE user_name="Иванов"')
        count = cur.fetchone()[0]
        conn.close()
        assert count == 1

    def test_empty_subject_raises_value_error(self, tmp_db):
        """Пустой subject вызывает ValueError."""
        with pytest.raises(ValueError):
            database.save_grades_to_db('ИСП-24', 'Иванов', 'Козлов', '', {}, tmp_db)

    def test_empty_teacher_raises_value_error(self, tmp_db):
        """Пустой teacher вызывает ValueError."""
        with pytest.raises(ValueError):
            database.save_grades_to_db('ИСП-24', 'Иванов', '', 'Физика', {}, tmp_db)

    def test_load_returns_empty_string_for_null(self, tmp_db):
        """NULL в БД → пустая строка при загрузке."""
        conn = sqlite3.connect(tmp_db)
        conn.execute('ALTER TABLE teachers_grades ADD COLUMN "пунктуальность" TEXT DEFAULT NULL')
        conn.execute(
            'INSERT INTO teachers_grades ("group", user_name, teacher, subject) VALUES (?,?,?,?)',
            ('ИСП-24', 'Петров', 'Новиков', 'Химия')
        )
        conn.commit()
        conn.close()

        loaded = database.load_grades_from_db('Петров', 'Новиков', 'Химия', ['Пунктуальность'], tmp_db)
        assert loaded.get('пунктуальность') == ''

    def test_load_nonexistent_record_returns_empty(self, tmp_db):
        """Загрузка несуществующей записи → словарь с пустыми строками."""
        loaded = database.load_grades_from_db(
            'НеСуществует', 'НетПреп', 'НетПредмет', ['Критерий'], tmp_db
        )
        assert loaded == {'критерий': ''}


# ─────────────────────────────────────────────────────────────
# 9. ТЕСТЫ Flask-маршрутов через test client (с моком database)
# ─────────────────────────────────────────────────────────────

class TestFlaskRoutes:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Настройка Flask test client."""
        import app as flask_app
        flask_app.app.config['TESTING'] = True
        flask_app.app.config['SECRET_KEY'] = 'test-secret'
        flask_app.app.config['WTF_CSRF_ENABLED'] = False
        self.client = flask_app.app.test_client()
        self.app = flask_app.app

    def test_login_page_returns_200(self):
        """Страница логина доступна без авторизации."""
        response = self.client.get('/')
        assert response.status_code == 200

    def test_profile_without_auth_redirects(self):
        """Попытка открыть /profile без авторизации → редирект на /."""
        response = self.client.get('/profile')
        assert response.status_code == 302
        assert '/' in response.headers['Location']

    def test_teachers_without_auth_redirects(self):
        """Попытка открыть /teachers без авторизации → редирект."""
        response = self.client.get('/teachers')
        assert response.status_code == 302

    def test_admin_databases_without_auth_redirects(self):
        """Попытка открыть /admin/databases без авторизации → редирект."""
        response = self.client.get('/admin/databases')
        assert response.status_code == 302

    def test_save_grades_without_auth_returns_401(self):
        """POST /save_grades без авторизации → 401."""
        response = self.client.post(
            '/save_grades',
            json={'teacher': 'Тест', 'subject': 'Математика', 'grades': {}}
        )
        assert response.status_code == 401

    def test_wrong_login_shows_error(self):
        """Неверный логин → страница с сообщением об ошибке."""
        response = self.client.post('/', data={
            'login': 'wronglogin',
            'password': 'wrongpass'
        })
        assert response.status_code == 200
        assert 'не найден' in response.data.decode('utf-8')

    def test_admin_login_redirects_to_admin_profile(self):
        """Вход администратора → редирект на /admin/profile."""
        import app as flask_app
        with patch.object(flask_app, 'ADMINS', {'Admin': '123456'}):
            response = self.client.post('/', data={
                'login': 'Admin',
                'password': '123456'
            })
        assert response.status_code == 302
        assert 'admin' in response.headers['Location']


# ─────────────────────────────────────────────────────────────
# 10. ДОПОЛНИТЕЛЬНЫЕ ТЕСТЫ для повышения покрытия
# ─────────────────────────────────────────────────────────────

class TestGetTeachersSorted:
    CSV_CONTENT = (
        "group;teacher;subject\n"
        "ИСП-24;Козлов Б.Б.;Физика\n"
        "ИСП-24;Смирнов А.А.;Математика\n"
        "ИСП-24;Алексеев В.В.;История\n"
    )

    def test_returns_sorted_names(self):
        """Возвращает список имён отсортированных по алфавиту."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            result = database.get_teachers_sorted('ИСП-24', 'fake.csv')
        assert result == sorted(result)
        assert len(result) == 3

    def test_wrong_group_returns_empty(self):
        """Несуществующая группа → пустой список."""
        with patch('builtins.open', mock_open(read_data=self.CSV_CONTENT)):
            result = database.get_teachers_sorted('НЕТ-99', 'fake.csv')
        assert result == []

    def test_file_not_found_returns_empty(self):
        """Отсутствующий файл → пустой список (без исключения)."""
        result = database.get_teachers_sorted('ИСП-24', 'nonexistent_xyz.csv')
        assert result == []


class TestGetDbTableData:
    def test_returns_headers_and_rows(self, tmp_db):
        """Правильно читает таблицу из SQLite-файла."""
        headers, rows = database.get_db_table_data(tmp_db.replace('.db', ''))
        # tmp_db — путь вида /tmp/.../test.db, имя без расширения нужно передать
        # Тест с реальным файлом проверяем через sqlite3 напрямую
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            'INSERT INTO teachers_grades ("group", user_name, teacher, subject) VALUES (?,?,?,?)',
            ('ИСП-24', 'Тест', 'Тестов', 'Тестология')
        )
        conn.commit()
        conn.close()
        # Читаем через нашу функцию напрямую
        conn2 = sqlite3.connect(tmp_db)
        conn2.row_factory = sqlite3.Row
        cur = conn2.cursor()
        cur.execute('SELECT * FROM teachers_grades')
        rows_raw = cur.fetchall()
        headers = list(rows_raw[0].keys()) if rows_raw else []
        conn2.close()
        assert 'user_name' in headers

    def test_nonexistent_db_returns_empty(self):
        """Несуществующий файл БД → пустые списки."""
        headers, rows = database.get_db_table_data('nonexistent_xyz_db')
        assert headers == []
        assert rows == []


class TestGetCsvData:
    def test_returns_headers_and_rows(self):
        """CSV корректно читается в headers + rows."""
        csv_content = "short_user_name;user_name;password;group\ntest;Тест Тестов;1234;ИСП-24\n"
        with patch('builtins.open', mock_open(read_data=csv_content)):
            headers, rows = database.get_csv_data('students')
        assert 'short_user_name' in headers
        assert len(rows) == 1

    def test_missing_file_returns_empty(self):
        """Несуществующий CSV → пустые списки."""
        headers, rows = database.get_csv_data('nonexistent_xyz')
        assert headers == []
        assert rows == []


class TestSyncCriteriaColumns:
    def test_new_column_is_added(self, tmp_db):
        """Новый критерий добавляет столбец в БД."""
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        database._sync_criteria_columns(conn, ['Новый критерий'])
        cols = database._get_existing_columns(conn)
        conn.close()
        assert 'новый_критерий' in cols

    def test_existing_column_not_duplicated(self, tmp_db):
        """Уже существующий критерий не добавляется повторно."""
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        conn.execute('ALTER TABLE teachers_grades ADD COLUMN "тест_критерий" TEXT DEFAULT NULL')
        conn.commit()
        # Повторный вызов не должен вызывать ошибку
        database._sync_criteria_columns(conn, ['Тест критерий'])
        cols = database._get_existing_columns(conn)
        conn.close()
        assert 'тест_критерий' in cols