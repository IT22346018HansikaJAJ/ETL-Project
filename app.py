# app.py
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
import pandas as pd
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback

app = Flask(__name__)
CORS(app)

# Secret key for sessions
app.secret_key = 'super_secret_key_123'  # 🔐 Change this in production

# Folder configs
UPLOAD_FOLDER = 'uploads'
CLEANED_FOLDER = 'cleaned'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ✅ Limit upload file size to 5MB
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB limit

# Ensure folders exist
for folder in [UPLOAD_FOLDER, CLEANED_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Dummy credentials
USER_CREDENTIALS = {
    'admin': 'password123'
}

# Upload log function
def log_upload(filename):
    with open("upload_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now().isoformat()} - Uploaded: {filename}\n")

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

        # Save original uploaded file
        file.save(save_path)

        # Log the upload
        log_upload(filename)

        # Extract with fallback delimiter + auto-detect
        try:
            df = pd.read_csv(save_path)
            if len(df.columns) == 1 and '|' in df.columns[0]:
                df = pd.read_csv(save_path, delimiter='|')
        except Exception:
            return jsonify({'error': 'Failed to parse CSV. Please check the file format.'}), 400

        # ✅ Check for empty CSV
        if df.empty:
            return jsonify({'error': 'Uploaded CSV is empty.'}), 400

        # Transform
        df.drop_duplicates(inplace=True)
        df.dropna(how='any', inplace=True)  # ✅ Remove rows with any missing values
        df.dropna(axis=1, how='all', inplace=True)  # Drop completely empty columns
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
            try:
                df[col].fillna(0, inplace=True)
            except:
                pass

        # Save cleaned version
        cleaned_filename = f"cleaned_{filename}"
        cleaned_path = os.path.join(CLEANED_FOLDER, cleaned_filename)
        df.to_csv(cleaned_path, index=False)

        # Load
        data = df.to_dict(orient='records')
        return jsonify({'data': data})

    except Exception as e:
        print("ERROR:", traceback.format_exc())
        return jsonify({'error': 'Something went wrong while processing the file. Please try again.'}), 500

@app.route('/clear-log', methods=['POST'])
def clear_log():
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        open("upload_log.txt", "w").close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/log')
def view_log():
    if 'user' not in session:
        return redirect(url_for('login'))

    if not os.path.exists("upload_log.txt"):
        return "<h2>No uploads yet</h2>"

    with open("upload_log.txt", "r") as f:
        lines = f.readlines()

    html = "<h2>Upload Log</h2><ul>"
    for line in lines:
        html += f"<li>{line.strip()}</li>"
    html += "</ul>"
    return html

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