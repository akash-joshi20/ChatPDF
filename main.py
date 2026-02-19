from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import os
import requests
from PyPDF2 import PdfReader
import mysql.connector
from mysql.connector import Error
import bcrypt
from dotenv import load_dotenv
import uuid
import re

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv(
    'SECRET_KEY', 'your-secret-key-change-in-production')  # Required for sessions

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------------
# Database Helper
# ------------------------


def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
        return conn
    except Error as e:
        print(f"Database connection error: {e}")
        return None

# ------------------------
# Auth Required
# ------------------------


def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_page'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth_page'))

        # Check if user is admin
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database error"}), 500

        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT role FROM users WHERE id = %s",
                           (session['user_id'],))
            user = cursor.fetchone()
            if not user or user['role'] != 'admin':
                return jsonify({"error": "Admin access required"}), 403
            return f(*args, **kwargs)
        finally:
            cursor.close()
            conn.close()
    return decorated_function

# ------------------------
# Routes
# ------------------------


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth_page'))

    # Redirect admins to admin dashboard
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    return render_template('index.html')


@app.route('/auth')
def auth_page():
    return render_template('auth.html')

# ------------------------
# Authentication
# ------------------------


@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password or not name:
        return jsonify({"error": "All fields are required"}), 400

    # Basic email validation
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database unavailable"}), 500

    cursor = conn.cursor()
    try:
        # Check if email exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"error": "Email already registered"}), 409

        # Hash password
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, is_active, created_at) VALUES (%s, %s, %s, %s, TRUE, NOW())",
            (name, email, hashed.decode('utf-8'), 'user')
        )
        conn.commit()
        user_id = cursor.lastrowid

        session['user_id'] = user_id
        session['email'] = email
        return jsonify({"message": "Account created"}), 201

    except Error as e:
        print(f"⛔ Signup Error: {e}")  # 👈 This prints to terminal!
        return jsonify({"error": f"Signup failed: {str(e)}"}), 500

    finally:
        cursor.close()
        conn.close()


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database unavailable"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, password_hash, role FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "Invalid credentials"}), 401

        try:
            # Strip whitespace from hash before checking
            stored_hash = user['password_hash'].strip() if isinstance(
                user['password_hash'], str) else user['password_hash']
            if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                return jsonify({"error": "Invalid credentials"}), 401
        except ValueError as e:
            print(f"Bcrypt error for user {email}: {e}")
            return jsonify({"error": "Invalid credentials"}), 401

        session['user_id'] = user['id']
        session['email'] = email
        session['role'] = user['role']
        return jsonify({"message": "Logged in", "role": user['role']}), 200

    except Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Login failed"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200

# ------------------------
# PDF Upload
# ------------------------


@app.route('/upload', methods=['POST'])
@login_required
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Only PDF files allowed"}), 400

    # Generate unique filename
    stored_filename = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
    file.save(filepath)

    # Extract text
    try:
        reader = PdfReader(filepath)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted
    except Exception as e:
        os.remove(filepath)  # Clean up
        return jsonify({"error": f"Failed to read PDF: {str(e)}"}), 500

    # Save to DB
    conn = get_db_connection()
    if not conn:
        os.remove(filepath)
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO pdfs (user_id, original_filename, stored_filename, extracted_text) VALUES (%s, %s, %s, %s)",
            (session['user_id'], file.filename, stored_filename, text)
        )
        conn.commit()
        pdf_id = cursor.lastrowid
        return jsonify({"message": "File uploaded", "pdf_id": pdf_id}), 200
    except Error as e:
        os.remove(filepath)
        return jsonify({"error": "Failed to save PDF"}), 500
    finally:
        cursor.close()
        conn.close()

# ------------------------
# Ask Question
# ------------------------


@app.route('/ask', methods=['POST'])
@login_required
def ask_question():
    data = request.get_json()
    question = data.get('question', '').strip()
    pdf_id = data.get('pdf_id')

    if not question or not pdf_id:
        return jsonify({"error": "Question and pdf_id required"}), 400

    # Fetch PDF text from DB (and verify ownership)
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT extracted_text FROM pdfs WHERE id = %s AND user_id = %s",
            (pdf_id, session['user_id'])
        )
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "PDF not found or access denied"}), 404

        pdf_text = result['extracted_text']
        if len(pdf_text) > 10000:
            pdf_text = pdf_text[:10000] + \
                "\n... [Content truncated for performance]"

        # Build prompt
        prompt = f"""
You are a helpful assistant that answers questions based on the provided document.
Answer concisely and accurately.

Document:
{pdf_text}

Question: {question}

Answer:
"""

        # Call Ollama
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_ctx": 4096}
            },
            timeout=120
        )

        if not response.ok:
            return jsonify({"error": f"LLM error: {response.status_code}"}), 500

        answer = response.json().get("response", "No response.").strip()

        # Save to chat history
        cursor.execute(
            "INSERT INTO chat_history (pdf_id, question, answer) VALUES (%s, %s, %s)",
            (pdf_id, question, answer)
        )
        conn.commit()

        return jsonify({"answer": answer})

    except requests.exceptions.Timeout:
        return jsonify({"error": "LLM request timed out"}), 500
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

# ------------------------
# Optional: Test Routes
# ------------------------


@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin.html')


# Admin API Routes
@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_admin_stats():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        # Total users
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='user'")
        total_users = cursor.fetchone()['total']

        # Active users
        cursor.execute(
            "SELECT COUNT(*) as total FROM users WHERE role='user' AND is_active=TRUE")
        active_users = cursor.fetchone()['total']

        # Total PDFs
        cursor.execute("SELECT COUNT(*) as total FROM pdfs")
        total_pdfs = cursor.fetchone()['total']

        # Total chats
        cursor.execute("SELECT COUNT(*) as total FROM chat_history")
        total_chats = cursor.fetchone()['total']

        # Storage usage
        cursor.execute(
            "SELECT SUM(OCTET_LENGTH(extracted_text)) as size FROM pdfs")
        storage = cursor.fetchone()['size'] or 0

        return jsonify({
            "total_users": total_users,
            "active_users": active_users,
            "total_pdfs": total_pdfs,
            "total_chats": total_chats,
            "storage_mb": round(storage / (1024 * 1024), 2)
        })
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_all_users():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, email, is_active, created_at, 
                   (SELECT COUNT(*) FROM pdfs WHERE user_id=users.id) as pdf_count,
                   (SELECT COUNT(*) FROM chat_history ch JOIN pdfs p ON ch.pdf_id=p.id WHERE p.user_id=users.id) as chat_count
            FROM users 
            WHERE role = 'user'
            ORDER BY created_at DESC
        """)
        users = cursor.fetchall()
        return jsonify(users)
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session['user_id']:
        return jsonify({"error": "Cannot delete yourself"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor()
    try:
        # Delete chat history
        cursor.execute(
            "DELETE FROM chat_history WHERE pdf_id IN (SELECT id FROM pdfs WHERE user_id = %s)", (user_id,))
        # Delete PDFs
        cursor.execute("DELETE FROM pdfs WHERE user_id = %s", (user_id,))
        # Delete user
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

        return jsonify({"message": "User deleted"}), 200
    except Error as e:
        conn.rollback()
        return jsonify({"error": "Failed to delete user"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@admin_required
def ban_user(user_id):
    if user_id == session['user_id']:
        return jsonify({"error": "Cannot ban yourself"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,))
        conn.commit()
        return jsonify({"message": "User banned"}), 200
    except Error as e:
        conn.rollback()
        return jsonify({"error": "Failed to ban user"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/users/<int:user_id>/unban', methods=['POST'])
@admin_required
def unban_user(user_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET is_active = TRUE WHERE id = %s", (user_id,))
        conn.commit()
        return jsonify({"message": "User unbanned"}), 200
    except Error as e:
        conn.rollback()
        return jsonify({"error": "Failed to unban user"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/pdfs', methods=['GET'])
@admin_required
def get_all_pdfs():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT p.id, p.original_filename, p.stored_filename, u.email,
                   LENGTH(p.extracted_text) as text_size,
                   (SELECT COUNT(*) FROM chat_history WHERE pdf_id = p.id) as chat_count
            FROM pdfs p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.id DESC
        """)
        pdfs = cursor.fetchall()
        return jsonify(pdfs)
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/pdfs/<int:pdf_id>/delete', methods=['POST'])
@admin_required
def delete_pdf(pdf_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        # Get stored filename
        cursor.execute(
            "SELECT stored_filename FROM pdfs WHERE id = %s", (pdf_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "PDF not found"}), 404

        # Delete file
        filepath = os.path.join(
            app.config['UPLOAD_FOLDER'], result['stored_filename'])
        if os.path.exists(filepath):
            os.remove(filepath)

        # Delete chat history
        cursor.execute("DELETE FROM chat_history WHERE pdf_id = %s", (pdf_id,))
        # Delete PDF
        cursor.execute("DELETE FROM pdfs WHERE id = %s", (pdf_id,))
        conn.commit()

        return jsonify({"message": "PDF deleted"}), 200
    except Error as e:
        conn.rollback()
        return jsonify({"error": "Failed to delete PDF"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/test-ollama')
def test_ollama():
    try:
        res = requests.get("http://localhost:11434", timeout=5)
        return "✅ Ollama is running!" if res.status_code == 200 else f"⚠️ Status: {res.status_code}"
    except Exception as e:
        return f"❌ Ollama error: {str(e)}"


@app.route('/test-db')
def test_db():
    conn = get_db_connection()
    if conn:
        conn.close()
        return "✅ DB connected!"
    return "❌ DB failed!", 500


# ------------------------
# Run
# ------------------------
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    app.run(debug=True, host='0.0.0.0', port=8080)
