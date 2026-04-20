from flask import Flask, render_template, request, redirect, url_for, session, jsonify # pip install flask
import json, os
from database import (load_users, authenticate_user, load_teachers_for_group, get_teacher_subjects, get_teachers_sorted,
                      load_criteria, get_csv_data, col_name, init_db, ensure_criteria_columns, load_grades_from_db,
                      save_grades_to_db, get_db_table_data)

app = Flask(__name__)
app.secret_key = 'e83c627bdcb8ba3b5af1a2900ff6031c'

# КОНФИГУРАЦИЯ АДМИНИСТРАТОРОВ

ADMINS = {'Admin': '123456'}

ADMIN_CSV_FILES = ['students', 'teachers', 'criterion']
ADMIN_DB_FILES = ['teachers_grades']


def _get_admin_dbs() -> list:
    """Возвращает список доступных источников данных для административной панели."""
    csv_dbs = [{'name': n, 'type': 'csv'} for n in ADMIN_CSV_FILES if os.path.exists(f'{n}.csv')]
    db_dbs = [{'name': n, 'type': 'db'} for n in ADMIN_DB_FILES if os.path.exists(f'{n}.db')]
    return csv_dbs + db_dbs


# ИНИЦИАЛИЗАЦИЯ

users_db = load_users()
init_db()


# МАРШРУТЫ

@app.route('/', methods=['GET', 'POST'])
def login():
    error = False
    login_value = ''
    if request.method == 'POST':
        login_data = request.form['login'].strip()
        password_data = request.form['password'].strip()
        login_value = login_data

        if login_data in ADMINS and ADMINS[login_data] == password_data:
            session['fio'] = login_data
            session['logged_in'] = True
            session['is_admin'] = True
            return redirect(url_for('admin_profile'))

        user = authenticate_user(users_db, login_data, password_data)
        if user:
            session['fio'] = user['user_name']
            session['group'] = user['group']
            session['logged_in'] = True
            session['is_admin'] = False
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

    group_id = session.get('group', '')
    teachers_list = load_teachers_for_group(group_id)
    max_length = 120
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

    group_id = session.get('group', '')
    teacher_subjects = get_teacher_subjects(group_id)
    display_teacher = teacher_name.replace('_', ' ')
    subjects = teacher_subjects.get(display_teacher, [])

    current_subject = ''
    page_type = 'single' if len(subjects) == 1 else 'multi'
    if len(subjects) == 1:
        current_subject = subjects[0]
    elif request.args.get('subject') and len(subjects) > 1:
        current_subject = request.args.get('subject')

    all_teachers = get_teachers_sorted(group_id)
    criteria_list = ensure_criteria_columns()
    col_names_list = [col_name(c) for c in criteria_list]

    saved_grades = {}
    if current_subject:
        saved_grades = load_grades_from_db(session.get('fio'), display_teacher, current_subject, criteria_list)

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
    grades = data.get('grades', {})

    if not teacher or not subject:
        return jsonify({'ok': False, 'error': 'missing teacher or subject'}), 400

    criteria_list = load_criteria()
    valid_cols = {col_name(c) for c in criteria_list}
    clean_grades = {
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

    all_dbs = _get_admin_dbs()
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

    all_dbs = _get_admin_dbs()
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)