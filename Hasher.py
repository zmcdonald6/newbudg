import bcrypt
import base64

def generate_base64_bcrypt(password: str) -> str:
    # Step 1: Hash with bcrypt
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    # Step 2: Encode in base64 for Google Sheets safety
    encoded = base64.b64encode(hashed).decode()

    return encoded

""" 
# Example usage:
password = "password"  # Replace with your desired password
base64_hash = generate_base64_bcrypt(password)

print("Paste this into your Google Sheet:")
print(base64_hash)
"""

print (generate_base64_bcrypt("password"))