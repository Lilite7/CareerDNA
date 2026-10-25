import sqlite3

conn = sqlite3.connect("careerdna.db")

with open("schema.sql", "r") as f:
    schema = f.read()

conn.executescript(schema)

conn.commit()
conn.close()

print("Database created successfully!")