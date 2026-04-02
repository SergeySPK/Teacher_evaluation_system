from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import csv
import sqlite3
import threading
import json
import re

app = Flask(__name__)
app.secret_key = 'e83c627bdcb8ba3b5af1a2900ff6031c'

DB_PATH = 'teachers_grades.db'
DB_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────
#  CSV
# ─────────────────────────────────────────────────────────────

def load_users(filename='students.csv'):
    users = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                users.append({
                    'short_user_name': row['short_user_name'].strip(),
                    'user_name':       row['user_name'].strip(),
                    'password':        row['password'].strip(),
                    'group':           row['group'].strip(),
                })
    except FileNotFoundError:
        print(f"⚠️  Файл {filename} не найден.")
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}")
    return users


def load_teachers_for_group(group_id):
    teachers_data = []
    seen = set()
    try:
        with open('teachers.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['group'].strip() == group_id:
                    name = row['teacher'].strip()
                    if name not in seen:
                        seen.add(name)
                        teachers_data.append({'teacher': name, 'subject': row['subject'].strip()})
    except FileNotFoundError:
        print("⚠️  Файл teachers.csv не найден.")
    except Exception as e:
        print(f"❌ Ошибка чтения teachers.csv: {e}")
    teachers_data.sort(key=lambda x: x['teacher'])
    return teachers_data


def get_teacher_subjects(group_id):
    result = {}
    try:
        with open('teachers.csv', 'r', encoding='utf-8') as f:
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
        print(f"Ошибка чтения teachers.csv: {e}")
    return result


def get_teachers_sorted(group_id):
    teachers, seen = [], set()
    try:
        with open('teachers.csv', 'r', encoding='utf-8') as f:
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


def load_criteria():
    criteria = []
    try:
        with open('criterion.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                criteria.append(row['criterion'].strip())
    except FileNotFoundError:
        print("⚠️ criterion.csv не найден")
    except Exception as e:
        print(f"❌ Ошибка criterion.csv: {e}")
    return criteria


# ─────────────────────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────────────────────

def col_name(criterion):
    name = criterion.lower()
    name = re.sub(r'[^a-zа-яё0-9\s]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    if not name:
        name = 'criterion'
    if name[0].isdigit():
        name = 'c_' + name
    return name


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_existing_columns(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(teachers_grades)")
    return {row['name'] for row in cur.fetchall()}


def _sync_criteria_columns(conn, criteria):
    existing = _get_existing_columns(conn)
    cur = conn.cursor()
    for criterion in criteria:
        cname = col_name(criterion)
        if cname not in existing:
            cur.execute(f'ALTER TABLE teachers_grades ADD COLUMN "{cname}" TEXT DEFAULT NULL')
            print(f"  БД: добавлен столбец '{cname}'")
    conn.commit()


def init_db():
    criteria = load_criteria()
    with DB_LOCK:
        conn = get_db()
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
            print("  БД: добавлен столбец 'time'")
        _sync_criteria_columns(conn, criteria)
        conn.close()
    print(f"✅ БД инициализирована: {DB_PATH}")


def ensure_criteria_columns():
    criteria = load_criteria()
    with DB_LOCK:
        conn = get_db()
        _sync_criteria_columns(conn, criteria)
        conn.close()
    return criteria


def load_grades_from_db(user_name, teacher, subject, criteria):
    with DB_LOCK:
        conn = get_db()
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


def save_grades_to_db(group, user_name, teacher, subject, grades_dict):
    from datetime import datetime
    now = datetime.now().strftime('%d:%m:%y')
    with DB_LOCK:
        conn = get_db()
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
                f'UPDATE teachers_grades SET {set_parts} WHERE user_name=? AND teacher=? AND subject=?',
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


# ─────────────────────────────────────────────────────────────
#  ADMIN
# ─────────────────────────────────────────────────────────────

# Словарь администраторов: {login: password}
# Логин является и отображаемым именем
ADMINS = {
    'Admin': '123456',
}

ADMIN_CSV_FILES = ['students', 'teachers', 'criterion']
ADMIN_DB_FILES  = ['teachers_grades']


def get_csv_data(name):
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


def get_db_table_data(name):
    db_file = f'{name}.db'
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
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


def _get_admin_dbs():
    csv_dbs = [{'name': n, 'type': 'csv'} for n in ADMIN_CSV_FILES if os.path.exists(f'{n}.csv')]
    db_dbs  = [{'name': n, 'type': 'db'}  for n in ADMIN_DB_FILES  if os.path.exists(f'{n}.db')]
    return csv_dbs + db_dbs


# ─────────────────────────────────────────────────────────────
#  INIT
# ─────────────────────────────────────────────────────────────

users_db = load_users()
init_db()


# ─────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
def login():
    error = False
    login_value = ''
    if request.method == 'POST':
        login_data    = request.form['login'].strip()
        password_data = request.form['password'].strip()
        login_value   = login_data

        if login_data in ADMINS and ADMINS[login_data] == password_data:
            session['fio']       = login_data
            session['logged_in'] = True
            session['is_admin']  = True
            return redirect(url_for('admin_profile'))

        for user in users_db:
            if user['short_user_name'] == login_data and user['password'] == password_data:
                session['fio']       = user['user_name']
                session['group']     = user['group']
                session['logged_in'] = True
                session['is_admin']  = False
                return redirect(url_for('profile'))
        error = True

    return render_template('index.html', error=error, login_value=login_value)


@app.route('/profile')
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('is_admin'):
        return redirect(url_for('admin_profile'))
    return render_template('profile.html',
                           fio=session.get('fio'),
                           group=session.get('group'),
                           is_admin=False)


@app.route('/teachers')
def teachers():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('is_admin'):
        return redirect(url_for('admin_databases'))

    group_id      = session.get('group', '')
    teachers_list = load_teachers_for_group(group_id)
    max_length    = 120
    if teachers_list:
        max_length = max(len(t['teacher']) for t in teachers_list) * 12 + 40

    return render_template('teachers.html',
                           mode='list',
                           fio=session.get('fio'),
                           teachers=teachers_list,
                           teachers_btn_width=max_length,
                           display_teacher='',
                           all_teachers=[],
                           page_type='',
                           subjects=[],
                           current_subject='',
                           criteria=[],
                           col_names=[],
                           saved_grades={},
                           saved_grades_js='{}',
                           col_names_js='[]')


@app.route('/teachers/<teacher_name>')
def teachers_detail(teacher_name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    group_id         = session.get('group', '')
    teacher_subjects = get_teacher_subjects(group_id)
    display_teacher  = teacher_name.replace('_', ' ')
    subjects         = teacher_subjects.get(display_teacher, [])

    current_subject = ''
    page_type = 'single' if len(subjects) == 1 else 'multi'
    if len(subjects) == 1:
        current_subject = subjects[0]
    elif request.args.get('subject') and len(subjects) > 1:
        current_subject = request.args.get('subject')

    all_teachers   = get_teachers_sorted(group_id)
    criteria_list  = ensure_criteria_columns()
    col_names_list = [col_name(c) for c in criteria_list]

    saved_grades = {}
    if current_subject:
        saved_grades = load_grades_from_db(
            session.get('fio'), display_teacher, current_subject, criteria_list
        )

    max_length = 120
    if all_teachers:
        max_length = max(len(t) for t in all_teachers) * 12 + 80

    return render_template('teachers.html',
                           mode='detail',
                           fio=session.get('fio'),
                           teacher_name=teacher_name,
                           display_teacher=display_teacher,
                           subjects=subjects,
                           current_subject=current_subject,
                           page_type=page_type,
                           all_teachers=all_teachers,
                           teachers_btn_width=max_length,
                           criteria=criteria_list,
                           col_names=col_names_list,
                           saved_grades=saved_grades,
                           saved_grades_js=json.dumps(saved_grades),
                           col_names_js=json.dumps(col_names_list),
                           teachers=[])


@app.route('/save_grades', methods=['POST'])
def save_grades_route():
    if not session.get('logged_in'):
        return jsonify({'ok': False, 'error': 'not logged in'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'no data'}), 400

    teacher = data.get('teacher', '').strip()
    subject = data.get('subject', '').strip()
    grades  = data.get('grades', {})

    if not teacher or not subject:
        return jsonify({'ok': False, 'error': 'missing teacher or subject'}), 400

    criteria_list = load_criteria()
    valid_cols    = {col_name(c) for c in criteria_list}
    clean_grades  = {
        k: (v if v in ('1', '2', '3', '4', '5') else None)
        for k, v in grades.items()
        if k in valid_cols
    }

    save_grades_to_db(
        group=session.get('group'),
        user_name=session.get('fio'),
        teacher=teacher,
        subject=subject,
        grades_dict=clean_grades
    )
    return jsonify({'ok': True})


@app.route('/admin/profile')
def admin_profile():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('login'))
    return render_template('profile.html',
                           fio=session.get('fio'),
                           group=None,
                           is_admin=True)


@app.route('/admin/databases')
def admin_databases():
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('login'))

    all_dbs    = _get_admin_dbs()
    max_length = 180
    if all_dbs:
        max_length = max(len(d['name']) for d in all_dbs) * 12 + 40

    return render_template('dataview.html',
                           fio=session.get('fio'),
                           databases=all_dbs,
                           databases_btn_width=max_length,
                           selected_db=None,
                           current_type=None,
                           headers=[],
                           rows=[])


@app.route('/admin/databases/<db_type>/<db_name>')
def admin_db_view(db_type, db_name):
    if not session.get('logged_in') or not session.get('is_admin'):
        return redirect(url_for('login'))

    all_dbs    = _get_admin_dbs()
    max_length = 180
    if all_dbs:
        max_length = max(len(d['name']) for d in all_dbs) * 12 + 40

    headers, rows = [], []
    if db_type == 'csv' and db_name in ADMIN_CSV_FILES:
        headers, rows = get_csv_data(db_name)
    elif db_type == 'db' and db_name in ADMIN_DB_FILES:
        headers, rows = get_db_table_data(db_name)

    return render_template('dataview.html',
                           fio=session.get('fio'),
                           databases=all_dbs,
                           databases_btn_width=max_length,
                           selected_db=db_name,
                           current_type=db_type,
                           headers=headers,
                           rows=rows)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)