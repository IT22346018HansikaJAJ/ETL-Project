from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
import pandas as pd
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback
import sqlite3

app = Flask(__name__)
CORS(app)

app.secret_key = 'super_secret_key_123'

UPLOAD_FOLDER = 'uploads'
CLEANED_FOLDER = 'cleaned'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

for folder in [UPLOAD_FOLDER, CLEANED_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

USER_CREDENTIALS = {
    'admin': 'password123'
}

# --- DB INIT ---
def init_db():
    with sqlite3.connect("upload_history.db") as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                filename TEXT,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

# --- DB Logger ---
def log_upload_db(username, filename, status):
    with sqlite3.connect("upload_history.db") as conn:
        c = conn.cursor()
        c.execute("INSERT INTO uploads (username, filename, status) VALUES (?, ?, ?)",
                  (username, filename, status))
        conn.commit()

@app.route('/')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload_csv():
    if 'user' not in session:
        return redirect(url_for('login'))

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Invalid file format. Only .csv files are supported.'}), 400

    try:
        original_filename = secure_filename(file.filename)
        base, ext = os.path.splitext(original_filename)
        filename = original_filename
        save_path = os.path.join(UPLOAD_FOLDER, filename)

        counter = 1
        while os.path.exists(save_path):
            filename = f"{base}_{counter}{ext}"
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            counter += 1

        file.save(save_path)

        # Read CSV
        try:
            df = pd.read_csv(save_path)
            if len(df.columns) == 1 and '|' in df.columns[0]:
                df = pd.read_csv(save_path, delimiter='|')
        except Exception as e:
            log_upload_db(session['user'], filename, 'parse_error')
            return jsonify({'error': f'CSV parsing failed: {str(e)}'}), 400

        # Validate structure
        if df.empty:
            log_upload_db(session['user'], filename, 'empty')
            return jsonify({'error': 'Uploaded CSV is empty.'}), 400
        if len(df.columns) < 2:
            log_upload_db(session['user'], filename, 'invalid_structure')
            return jsonify({'error': 'CSV must contain at least two columns.'}), 400
        if all(not str(col).strip() for col in df.columns):
            log_upload_db(session['user'], filename, 'no_headers')
            return jsonify({'error': 'Column headers are missing or blank.'}), 400

        # Transform
        df.drop_duplicates(inplace=True)
        df.dropna(how='any', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

        for col in df.select_dtypes(include=['object']):
            df[col] = df[col].str.strip()
        for col in df.columns:
            if 'date' in col or 'time' in col:
                try:
                    df[col] = pd.to_datetime(df[col])
                except:
                    pass
        for col in df.select_dtypes(include=['float', 'int']):
            df[col].fillna(0, inplace=True)

        cleaned_filename = f"cleaned_{filename}"
        cleaned_path = os.path.join(CLEANED_FOLDER, cleaned_filename)
        df.to_csv(cleaned_path, index=False)

        log_upload_db(session['user'], filename, 'success')
        return jsonify({'data': df.to_dict(orient='records')})

    except Exception as e:
        print("ERROR:", traceback.format_exc())
        log_upload_db(session['user'], filename, 'server_error')
        return jsonify({'error': 'Something went wrong while processing the file.'}), 500

@app.route('/upload-history')
def upload_history():
    if 'user' not in session:
        return redirect(url_for('login'))
    with sqlite3.connect("upload_history.db") as conn:
        c = conn.cursor()
        c.execute("SELECT filename, status, timestamp FROM uploads WHERE username = ? ORDER BY timestamp DESC", (session['user'],))
        rows = c.fetchall()
    return render_template("upload_history.html", history=rows)

@app.route('/api/upload-history')
def upload_history_api():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    with sqlite3.connect("upload_history.db") as conn:
        c = conn.cursor()
        c.execute("SELECT filename, status, timestamp FROM uploads WHERE username = ? ORDER BY timestamp DESC", (session['user'],))
        rows = c.fetchall()
    return jsonify(rows)

@app.route('/clear-log', methods=['POST'])
def clear_log():
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        open("upload_log.txt", "w").close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/download/<filename>')
def download_cleaned_file(filename):
    if 'user' not in session:
        return redirect(url_for('login'))
    return send_from_directory(CLEANED_FOLDER, filename, as_attachment=True)

@app.route('/preview/<filename>')
def preview_file(filename):
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        file_path = os.path.join(CLEANED_FOLDER, filename)
        df = pd.read_csv(file_path)
        preview_data = df.head(10).to_dict(orient='records')
        return jsonify(preview_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        file_path = os.path.join(CLEANED_FOLDER, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    cleaned_files = os.listdir(CLEANED_FOLDER)
    log = ""
    if os.path.exists("upload_log.txt"):
        with open("upload_log.txt", "r") as f:
            log = f.read()
    return render_template("dashboard.html", cleaned_files=cleaned_files, log=log)

if __name__ == '__main__':
    app.run(debug=True)
