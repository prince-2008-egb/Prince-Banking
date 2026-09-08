from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import json
import os
import threading

PostgreSQL is used on Render when DATABASE_URL is available.

JSON is kept as a local fallback for testing on a phone/PC.

try:
import psycopg
except ImportError:
psycopg = None

app = Flask(name)
app.secret_key = os.environ.get("SECRET_KEY", "prince-banking-demo-key")

BASE_DIR = os.path.dirname(os.path.abspath(file))
DATA_FILE = os.path.join(BASE_DIR, "bank_data.json")
LOCK = threading.Lock()

=========================

DATABASE HELPERS

=========================

def using_postgres():
return bool(os.environ.get("DATABASE_URL")) and psycopg is not None

def postgres_url():
url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres://"):
url = "postgresql://" + url[len("postgres://"):]
return url

def default_admin():
return {
"account_no": "ADMIN001",
"name": "Prince Banking Admin",
"email": "admin@princebanking.com",
"phone": "",
"account_type": "Admin",
"password_hash": generate_password_hash("admin123"),
"balance": 0.0,
"transactions": []
}

def create_database():
data = {"users": [default_admin()]}
with open(DATA_FILE, "w", encoding="utf-8") as file:
json.dump(data, file, indent=4)

def load_json_database():
if not os.path.exists(DATA_FILE):
create_database()

try:  
    with open(DATA_FILE, "r", encoding="utf-8") as file:  
        data = json.load(file)  

    if not isinstance(data, dict):  
        create_database()  
        with open(DATA_FILE, "r", encoding="utf-8") as file:  
            data = json.load(file)  

    data.setdefault("users", [])  
    return data  

except Exception:  
    create_database()  
    with open(DATA_FILE, "r", encoding="utf-8") as file:  
        return json.load(file)

def init_postgres():
"""Create the users table and migrate existing JSON data only if DB is empty."""
if not using_postgres():
return

with psycopg.connect(postgres_url()) as conn:  
    with conn.cursor() as cur:  
        cur.execute("""  
            CREATE TABLE IF NOT EXISTS users (  
                account_no TEXT PRIMARY KEY,  
                name TEXT NOT NULL,  
                email TEXT,  
                phone TEXT,  
                account_type TEXT NOT NULL,  
                password_hash TEXT NOT NULL,  
                balance DOUBLE PRECISION NOT NULL DEFAULT 0,  
                transactions JSONB NOT NULL DEFAULT '[]'::jsonb  
            )  
        """)  

        cur.execute("SELECT COUNT(*) FROM users")  
        count = cur.fetchone()[0]  

        if count == 0:  
            local_data = load_json_database()  

            for user in local_data.get("users", []):  
                cur.execute("""  
                    INSERT INTO users  
                    (account_no, name, email, phone, account_type,  
                     password_hash, balance, transactions)  
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)  
                    ON CONFLICT (account_no) DO NOTHING  
                """, (  
                    str(user.get("account_no", "")),  
                    user.get("name", ""),  
                    user.get("email", ""),  
                    user.get("phone", ""),  
                    user.get("account_type", "Savings"),  
                    user.get("password_hash", ""),  
                    float(user.get("balance", 0)),  
                    json.dumps(user.get("transactions", []))  
                ))  

    conn.commit()

def load_database():
if using_postgres():
init_postgres()

with psycopg.connect(postgres_url()) as conn:  
        with conn.cursor() as cur:  
            cur.execute("""  
                SELECT account_no, name, email, phone, account_type,  
                       password_hash, balance, transactions  
                FROM users  
                ORDER BY account_no  
            """)  
            rows = cur.fetchall()  

    users = []  
    for row in rows:  
        transactions = row[7] or []  
        if isinstance(transactions, str):  
            try:  
                transactions = json.loads(transactions)  
            except Exception:  
                transactions = []  

        users.append({  
            "account_no": row[0],  
            "name": row[1],  
            "email": row[2] or "",  
            "phone": row[3] or "",  
            "account_type": row[4],  
            "password_hash": row[5],  
            "balance": float(row[6] or 0),  
            "transactions": transactions  
        })  

    return {"users": users}  

return load_json_database()

def save_database(data):
"""Save the same dictionary format to PostgreSQL or local JSON."""
if using_postgres():
init_postgres()

with psycopg.connect(postgres_url()) as conn:  
        with conn.cursor() as cur:  
            for user in data.get("users", []):  
                cur.execute("""  
                    INSERT INTO users  
                    (account_no, name, email, phone, account_type,  
                     password_hash, balance, transactions)  
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)  
                    ON CONFLICT (account_no) DO UPDATE SET  
                        name = EXCLUDED.name,  
                        email = EXCLUDED.email,  
                        phone = EXCLUDED.phone,  
                        account_type = EXCLUDED.account_type,  
                        password_hash = EXCLUDED.password_hash,  
                        balance = EXCLUDED.balance,  
                        transactions = EXCLUDED.transactions  
                """, (  
                    str(user.get("account_no", "")),  
                    user.get("name", ""),  
                    user.get("email", ""),  
                    user.get("phone", ""),  
                    user.get("account_type", "Savings"),  
                    user.get("password_hash", ""),  
                    float(user.get("balance", 0)),  
                    json.dumps(user.get("transactions", []))  
                ))  

            # Remove database users that were deleted from the app.  
            accounts = [  
                str(u.get("account_no", ""))  
                for u in data.get("users", [])  
            ]  
            cur.execute(  
                "DELETE FROM users WHERE NOT (account_no = ANY(%s))",  
                (accounts,)  
            )  

        conn.commit()  
    return  

temporary_file = DATA_FILE + ".tmp"  
with open(temporary_file, "w", encoding="utf-8") as file:  
    json.dump(data, file, indent=4)  
os.replace(temporary_file, DATA_FILE)

def find_user(account_no):
database = load_database()

for user in database.get("users", []):  
    if str(user.get("account_no", "")) == str(account_no):  
        return user  

return None

=========================

LOGIN PROTECTION

=========================

def login_required(function):
@wraps(function)
def wrapper(*args, **kwargs):
if "account_no" not in session:
return redirect(url_for("login"))
return function(*args, **kwargs)
return wrapper

def admin_required(function):
@wraps(function)
def wrapper(*args, **kwargs):
if session.get("is_admin") is not True:
flash("Admin access required.", "error")
return redirect(url_for("dashboard"))
return function(*args, **kwargs)
return wrapper

=========================

HOME

=========================

@app.route("/")
def home():
if "account_no" in session:
if session.get("is_admin"):
return redirect(url_for("admin"))
return redirect(url_for("dashboard"))

return redirect(url_for("login"))

=========================

LOGIN

=========================

@app.route("/login", methods=["GET", "POST"])
def login():
if request.method == "POST":
account_no = request.form.get("account_no", "").strip().upper()
password = request.form.get("password", "")

user = find_user(account_no)  

    if user:  
        password_hash = user.get("password_hash", "")  

        try:  
            password_correct = bool(  
                password_hash and  
                check_password_hash(password_hash, password)  
            )  
        except Exception:  
            password_correct = False  

        if password_correct:  
            session["account_no"] = user.get("account_no")  
            session["is_admin"] = user.get("account_type") == "Admin"  

            if session["is_admin"]:  
                return redirect(url_for("admin"))  

            return redirect(url_for("dashboard"))  

    flash("Invalid account number or password.", "error")  

return render_template("login.html")

=========================

LOGOUT

=========================

@app.route("/logout")
def logout():
session.clear()
return redirect(url_for("login"))

=========================

REGISTER

=========================

@app.route("/register", methods=["GET", "POST"])
def register():
if request.method == "POST":
name = request.form.get("name", "").strip()
email = request.form.get("email", "").strip()
phone = request.form.get("phone", "").strip()
account_type = request.form.get("account_type", "Savings")
password = request.form.get("password", "")
confirm_password = request.form.get("confirm_password", "")

if not name:  
        flash("Please enter your name.", "error")  
        return render_template("register.html")  

    if len(password) < 6:  
        flash("Password must contain at least 6 characters.", "error")  
        return render_template("register.html")  

    if password != confirm_password:  
        flash("Passwords do not match.", "error")  
        return render_template("register.html")  

    if account_type not in ["Savings", "Current"]:  
        account_type = "Savings"  

    with LOCK:  
        database = load_database()  

        numbers = []  
        for user in database.get("users", []):  
            account = str(user.get("account_no", ""))  
            if account.isdigit():  
                numbers.append(int(account))  

        new_account = str(max(numbers) + 1 if numbers else 100001)  

        new_user = {  
            "account_no": new_account,  
            "name": name,  
            "email": email,  
            "phone": phone,  
            "account_type": account_type,  
            "password_hash": generate_password_hash(password),  
            "balance": 0.0,  
            "transactions": []  
        }  

        database.setdefault("users", []).append(new_user)  
        save_database(database)  

    return render_template(  
        "register.html",  
        created_account=new_account  
    )  

return render_template("register.html")

=========================

DASHBOARD

=========================

@app.route("/dashboard")
@login_required
def dashboard():
user = find_user(session["account_no"])

if not user:  
    session.clear()  
    return redirect(url_for("login"))  

account_type = user.get("account_type", "Savings")  
user["account_type"] = account_type  

balance = float(user.get("balance", 0))  
transactions = list(reversed(user.get("transactions", [])))  

return render_template(  
    "dashboard.html",  
    user=user,  
    balance=balance,  
    transactions=transactions[:10]  
)

=========================

DEPOSIT

=========================

@app.route("/deposit", methods=["POST"])
@login_required
def deposit():
try:
amount = float(request.form.get("amount", 0))
except (ValueError, TypeError):
amount = 0

if amount <= 0:  
    flash("Enter a valid amount.", "error")  
    return redirect(url_for("dashboard"))  

with LOCK:  
    database = load_database()  
    user = None  

    for item in database.get("users", []):  
        if str(item.get("account_no")) == str(session["account_no"]):  
            user = item  
            break  

    if not user:  
        flash("Account not found.", "error")  
        return redirect(url_for("logout"))  

    current_balance = float(user.get("balance", 0))  
    user["balance"] = round(current_balance + amount, 2)  

    transaction = {  
        "title": "Cash Deposit",  
        "amount": f"+₹{amount:,.2f}",  
        "type": "deposit",  
        "date": datetime.now().strftime("%d %b %Y, %I:%M %p")  
    }  

    user.setdefault("transactions", []).append(transaction)  
    save_database(database)  

flash(f"₹{amount:,.2f} deposited successfully.", "success")  
return redirect(url_for("dashboard"))

=========================

WITHDRAW

=========================

@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
try:
amount = float(request.form.get("amount", 0))
except (ValueError, TypeError):
amount = 0

if amount <= 0:  
    flash("Enter a valid amount.", "error")  
    return redirect(url_for("dashboard"))  

with LOCK:  
    database = load_database()  
    user = None  

    for item in database.get("users", []):  
        if str(item.get("account_no")) == str(session["account_no"]):  
            user = item  
            break  

    if not user:  
        flash("Account not found.", "error")  
        return redirect(url_for("logout"))  

    current_balance = float(user.get("balance", 0))  

    if amount > current_balance:  
        flash("Insufficient balance.", "error")  
        return redirect(url_for("dashboard"))  

    user["balance"] = round(current_balance - amount, 2)  

    transaction = {  
        "title": "Cash Withdrawal",  
        "amount": f"-₹{amount:,.2f}",  
        "type": "withdraw",  
        "date": datetime.now().strftime("%d %b %Y, %I:%M %p")  
    }  

    user.setdefault("transactions", []).append(transaction)  
    save_database(database)  

flash(f"₹{amount:,.2f} withdrawn successfully.", "success")  
return redirect(url_for("dashboard"))

=========================

ADMIN DASHBOARD

=========================

@app.route("/admin")
@login_required
@admin_required
def admin():
database = load_database()
users = []
total_balance = 0.0

for user in database.get("users", []):  
    if user.get("account_type") != "Admin":  
        users.append(user)  
        total_balance += float(user.get("balance", 0))  

return render_template(  
    "admin.html",  
    users=users,  
    total_balance=total_balance  
)

=========================

DELETE CUSTOMER

=========================

@app.route("/admin/delete/<account_no>", methods=["POST"])
@login_required
@admin_required
def delete_user(account_no):
with LOCK:
database = load_database()

database["users"] = [  
        user for user in database.get("users", [])  
        if not (  
            str(user.get("account_no", "")) == str(account_no)  
            and user.get("account_type") != "Admin"  
        )  
    ]  

    save_database(database)  

flash("Customer account removed.", "success")  
return redirect(url_for("admin"))

=========================

STARTUP

=========================

if name == "main":
print("")
print("================================")
print("       PRINCE BANKING")
print("================================")
print("")

if using_postgres():  
    init_postgres()  
    print("Database : PostgreSQL")  
else:  
    print("Database : bank_data.json (local fallback)")  

print("Admin Account : ADMIN001")  
print("Admin Password: admin123")  
print("")  
print("Open: http://127.0.0.1:5000")  
print("")  

app.run(  
    host="0.0.0.0",  
    port=5000,  
    debug=True

)
