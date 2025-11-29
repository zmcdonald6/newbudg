# MySQL Abstraction Layer for Musson Group IT's Budget Tracking Application
# Author: Zedaine McDonald
# Date; **

import pymysql
import streamlit as st
from datetime import datetime
import requests
import pandas as pd
import bcrypt
import base64

import pathlib
import tempfile

#Database config section
dbsecrets = st.secrets["MYSQL"]

#ssl authentication files.
ssl_options = {
    "ca": dbsecrets["sslserverca"],
    "cert": dbsecrets["sslclientcert"],
    "key": dbsecrets["sslclientkey"],
    "check_hostname": dbsecrets["sslcheck_hostname"]
}

def write_cert(b64_data, filename):
    """Function to decode base64 and write to a temportaty file"""
    decoded = base64.b64decode(b64_data)
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(decoded)
    f.flush()
    return f.name

# Initial database connection
def get_db():

    home_lib = pathlib.Path.home()
    target_path = home_lib/"private"
    dbsecrets = st.secrets["MYSQL"]
    
    

    #if target_path.is_dir():
    #    """Returns a MySQL connection using Streamlit secrets"""
        
        #ssl authentication.
    #    ssl_options = {
    #    "ca": dbsecrets["sslserverca"],
    #    "cert": dbsecrets["sslclientcert"],
    #   "key": dbsecrets["sslclientkey"],
    #   "check_hostname": dbsecrets["sslcheck_hostname"]
    #    }

    try:
        connection = pymysql.connect(
            host= dbsecrets["host"],
            user= dbsecrets["user"],
            password= dbsecrets["password"],
            database= dbsecrets["database"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            charset="utf8mb4",
        )
        return connection
    except pymysql.Error as e:
        st.error(f"Error connecting to MySQL database: {e}")
        return None
#else:
#    ca_path = write_cert(dbsecrets["sslserverca_b64"], "server-ca.pem")
#    cert_path = write_cert(dbsecrets["sslclientcert"], "client-cert.pem")
#    key_path = write_cert(dbsecrets["sslclientkey"], "client-key.pem")


#    ssl_options = {
#        "ca": ca_path,
#        "cert": cert_path,
#        "key": key_path,
#        "check_hostname": False
#    }
#    try:
#        connection = pymysql.connect(
#            host=st.secrets["MYSQL"]["host"],
#            user=st.secrets["MYSQL"]["user"],
#            password=st.secrets["MYSQL"]["password"],
#            database=st.secrets["MYSQL"]["database"],
#            cursorclass=pymysql.cursors.DictCursor,
#            autocommit=True,
#            charset="utf8mb4",
#            ssl = ssl_options
#        )
#        return connection
    except pymysql.Error as e:
        st.error(f"Error connecting to MySQL database: {e}")
        return None




# Users CRUD operations
def get_user_by_email(email: str):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT id, name, username, email, hashed_password, role, first_login
            FROM users
            WHERE LOWER(email) = LOWER(%s)
        """, (email,))
        return c.fetchone()


def get_all_users():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT id, name, username, email, role, first_login
            FROM users
            ORDER BY name ASC
        """)
        return c.fetchall()


def add_user(name: str, username: str, email: str, hashed_pw:str, role="user"):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO users (name, username, email, hashed_password, role, first_login)
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (name, username, email, hashed_pw, role))
    return True


def update_password(email, hashed_pw):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            UPDATE users
            SET hashed_password = %s, first_login = FALSE
            WHERE LOWER(email) = LOWER(%s)
        """, (hashed_pw, email))
    return True


def reset_user_password(email, hashed_pw):
    """
    Admin resets password -> first_login becomes TRUE.
    """
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            UPDATE users
            SET hashed_password = %s, first_login = TRUE
            WHERE LOWER(email) = LOWER(%s)
        """, (hashed_pw, email))
    return True


def delete_user(email):
    db = get_db()
    with db.cursor() as c:
        c.execute("DELETE FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
    return True




#Login information CRUD
def log_login_activity(email, activity_type, ip_address):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO loginlogs (email, activity_type, status, timestamp)
            VALUES (%s, %s, %s, NOW())
        """, (email, activity_type, ip_address))
    return True


def get_login_logs():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT email, activity_type, status, timestamp
            FROM loginlogs
            ORDER BY timestamp DESC
        """)
        return c.fetchall()
    



#File Upload CRUD
def add_uploaded_file(file_name, file_type, uploader_email, file_url):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO uploadedfiles
            (file_name, file_type, uploader_email, upload_date, file_url)
            VALUES (%s, %s, %s, NOW(), %s)
        """, (file_name, file_type, uploader_email, file_url))
    return True


def delete_uploaded_file(file_name):
    db = get_db()
    with db.cursor() as c:
        c.execute("DELETE FROM uploadedfiles WHERE file_name = %s", (file_name,))
    return True


def get_uploaded_files():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT file_name, file_type, uploader_email, upload_date, file_url
            FROM uploadedfiles
            ORDER BY upload_date DESC
        """)
        return c.fetchall()
    



#Budget State Operations
def load_budget_state_monthly(file_name: str):
    #db = get_db()
    #with db.cursor() as c:
    #    c.execute("""
    #        SELECT category, subcategory, month, amount, status_category
    #        FROM budget_state
    #        WHERE file_name = %s
    #    """, (file_name,))
    #    rows = c.fetchall()
    #return rows
    """
    Loads budget-state monthly classification from MySQL.
    Always returns a DataFrame with the required columns.
    Never returns a tuple or list.
    """

    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT category, subcategory, month, amount, status_category
            FROM budget_state
            WHERE file_name = %s
        """, (file_name,))
        rows = c.fetchall()

    # If nothing in DB → return empty DataFrame with required columns
    if not rows:
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month",
            "Amount", "Status Category"
        ])

    # Convert to DataFrame
    df = pd.DataFrame(rows)

    # Normalize column names to match dashboard expectations
    df = df.rename(columns={
        "category": "Category",
        "subcategory": "Sub-Category",
        "month": "Month",
        "amount": "Amount",
        "status_category": "Status Category",
    })

    # Ensure required columns exist
    required = ["Category", "Sub-Category", "Month", "Amount", "Status Category"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    return df[required]

def save_budget_state_monthly(file_name, df_melted, user_email):
    """
    Saves budget-state monthly classification using MySQL UPSERT.
    Only inserts new rows or updates existing ones.
    """
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = df_melted.to_dict(orient="records")

    with db.cursor() as c:
        for r in rows:
            c.execute("""
                INSERT INTO budget_state
                (file_name, category, subcategory, month, amount, status_category, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)

                ON DUPLICATE KEY UPDATE
                    amount = VALUES(amount),
                    status_category = VALUES(status_category),
                    updated_by = VALUES(updated_by),
                    updated_at = VALUES(updated_at)
            """, (
                file_name,
                r["Category"],
                r["Sub-Category"],
                r["Month"],
                r["Amount"],
                r["Status Category"],
                user_email,
                now
            ))

    return True





#Generic Helpers
def run_query(sql: str, params=None):
    """Run a SELECT and return all rows as list(dict)."""
    db = get_db()
    with db.cursor() as c:
        c.execute(sql, params or ())
        return c.fetchall()


def run_execute(sql: str, params=None):
    """Run INSERT/UPDATE/DELETE."""
    db = get_db()
    with db.cursor() as c:
        c.execute(sql, params or ())
    return True

#Non-SQL, IP get
def get_ip():
    try:
        response = requests.get("https://api.ipify.org?format=text")
        return response.text
    except:
        return "Unavailable"
    
def seed_admin_user():
    """
    Generates a default admin user with user defined credentials
    """
    x = run_query(sql = "select count(*) from users")
    try:

        #Check if any user exists
        if x[0].get("count(*)") < 1:

            #Inserting user details
            name = st.secrets['admin']['name']
            email = st.secrets['admin']['email']
            username = st.secrets['admin']['username']
            password = str(st.secrets['admin']['password'])
            role = st.secrets['admin']['role']

            #Hashing password
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            encoded = base64.b64encode(hashed).decode()

            #Inserting user
            add_user(name, username, email, encoded, role)
            print ("No users found, admin user seeded")
        else:
            pass

    except Exception as e:
        st.error(f"Error seeding user {e}")