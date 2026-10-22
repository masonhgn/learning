"""builds the sqlquest practice database: a small online store with staff"""

import random
import sqlite3
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE departments (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    budget  INTEGER NOT NULL
);

CREATE TABLE employees (
    id             INTEGER PRIMARY KEY,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    title          TEXT NOT NULL,
    department_id  INTEGER REFERENCES departments(id),
    manager_id     INTEGER REFERENCES employees(id),
    salary         INTEGER NOT NULL,
    hire_date      TEXT NOT NULL
);

CREATE TABLE customers (
    id           INTEGER PRIMARY KEY,
    first_name   TEXT NOT NULL,
    last_name    TEXT NOT NULL,
    email        TEXT,
    city         TEXT NOT NULL,
    country      TEXT NOT NULL,
    signup_date  TEXT NOT NULL
);

CREATE TABLE products (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL,
    price     REAL NOT NULL,
    stock     INTEGER NOT NULL
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    employee_id  INTEGER REFERENCES employees(id),
    order_date   TEXT NOT NULL,
    status       TEXT NOT NULL
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL
);
"""

FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Mia", "Lucas", "Zoe", "Ethan", "Ivy", "Mason",
    "Nora", "Leo", "Aria", "Owen", "Luna", "Caleb", "Maya", "Felix", "Iris", "Hugo",
    "Sofia", "Jonas", "Elena", "Diego", "Priya", "Kenji", "Amara", "Omar", "Freya", "Mateo",
    "Hana", "Ravi", "Clara", "Theo", "Lena", "Arjun", "Rosa", "Ezra", "Yara", "Milo",
]

LAST_NAMES = [
    "Smith", "Garcia", "Chen", "Patel", "Kim", "Muller", "Rossi", "Nguyen", "Lopez", "Brown",
    "Silva", "Novak", "Okafor", "Tanaka", "Schmidt", "Martin", "Haddad", "Ivanova", "Walsh", "Reyes",
    "Fischer", "Costa", "Larsen", "Moreau", "Singh", "Park", "Dubois", "Klein", "Hughes", "Torres",
]

DEPARTMENTS = [
    (1, "Sales", 500000),
    (2, "Engineering", 900000),
    (3, "Marketing", 300000),
    (4, "Support", 250000),
    (5, "Finance", 350000),
    (6, "Operations", 400000),
]

#dept id -> (staff count, staff titles, staff salary range, head salary)
STAFFING = {
    1: (9, ["Account Executive", "Sales Rep", "Sales Associate"], (48000, 98000), 128000),
    2: (5, ["Software Engineer", "Senior Engineer", "Data Engineer"], (95000, 155000), 172000),
    3: (3, ["Marketing Specialist", "Content Writer"], (52000, 88000), 115000),
    4: (3, ["Support Agent", "Support Lead"], (42000, 68000), 92000),
    5: (2, ["Accountant", "Financial Analyst"], (65000, 99000), 138000),
    6: (1, ["Logistics Coordinator"], (50000, 72000), 105000),
}

PRODUCTS = {
    "Electronics": (["Wireless Earbuds", "Mechanical Keyboard", "4K Monitor", "USB-C Hub",
                     "Smart Speaker", "HD Webcam", "Portable SSD"], (24, 520)),
    "Books": (["SQL for Humans", "The Data Garden", "Query Quest", "Indexing Mysteries",
               "Normal Forms", "Join Me"], (9, 58)),
    "Kitchen": (["Chef Knife", "Cast Iron Skillet", "French Press", "Bamboo Cutting Board",
                 "Spice Rack", "Electric Kettle", "Mixing Bowls"], (12, 140)),
    "Outdoors": (["Camping Tent", "Hiking Backpack", "Water Bottle", "Trekking Poles",
                  "Sleeping Bag", "Headlamp"], (14, 320)),
    "Toys": (["Puzzle Cube", "Building Blocks", "Remote Car", "Board Game Night",
              "Plush Dragon", "Kite"], (8, 90)),
    "Clothing": (["Rain Jacket", "Wool Socks", "Running Shoes", "Denim Jacket",
                  "Beanie", "Hoodie", "Cargo Pants"], (11, 180)),
}

#products nobody has ever bought
UNSOLD = {"Indexing Mysteries", "Kite", "Cargo Pants"}

CITIES = {
    "USA": ["New York", "Austin", "Chicago", "Seattle", "Denver"],
    "Canada": ["Toronto", "Vancouver", "Montreal"],
    "UK": ["London", "Manchester"],
    "Germany": ["Berlin", "Munich"],
    "Mexico": ["Mexico City", "Guadalajara"],
}
COUNTRY_WEIGHTS = [40, 18, 15, 14, 13]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me"]
STATUSES = ["delivered", "shipped", "pending", "cancelled"]
STATUS_WEIGHTS = [70, 12, 8, 10]


def _random_date(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _unique_names(rng, count, taken):
    names = []
    while len(names) < count:
        pair = (rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES))
        if pair not in taken:
            taken.add(pair)
            names.append(pair)
    return names


def build_database(path, seed=42):
    rng = random.Random(seed)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO departments VALUES (?, ?, ?)", DEPARTMENTS)

    taken = set()
    employees = []
    staff_count = sum(s[0] for s in STAFFING.values())
    names = iter(_unique_names(rng, 1 + len(STAFFING) + staff_count + 1, taken))

    def hire(title, dept, manager, salary, start=date(2015, 1, 1)):
        first, last = next(names)
        hired = _random_date(rng, start, date(2025, 6, 30)).isoformat()
        employees.append((len(employees) + 1, first, last, title, dept, manager, salary, hired))
        return len(employees)

    ceo = hire("CEO", 6, None, 250000, start=date(2014, 1, 1))
    heads = {}
    for dept_id, name, _ in DEPARTMENTS:
        heads[dept_id] = hire(f"Head of {name}", dept_id, ceo, STAFFING[dept_id][3])
    sales_staff = []
    for dept_id, (count, titles, (low, high), _) in STAFFING.items():
        for _ in range(count):
            salary = rng.randrange(low, high, 500)
            emp_id = hire(rng.choice(titles), dept_id, heads[dept_id], salary, start=date(2018, 1, 1))
            if dept_id == 1:
                sales_staff.append(emp_id)
    hire("Contract Engineer", 2, None, 88000, start=date(2024, 1, 1))
    conn.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?)", employees)

    products = []
    for category, (product_names, (low, high)) in PRODUCTS.items():
        for name in product_names:
            price = round(rng.uniform(low, high), 2)
            products.append((len(products) + 1, name, category, price, rng.randint(0, 180)))
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

    customers = []
    for first, last in _unique_names(rng, 80, set()):
        country = rng.choices(list(CITIES), COUNTRY_WEIGHTS)[0]
        email = None
        if rng.random() > 0.1:
            email = f"{first}.{last}{rng.randint(1, 99)}@{rng.choice(EMAIL_DOMAINS)}".lower()
        signup = _random_date(rng, date(2023, 1, 1), date(2025, 6, 30)).isoformat()
        customers.append((len(customers) + 1, first, last, email, rng.choice(CITIES[country]), country, signup))
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers)

    active = rng.sample(customers, 70)
    sellable = [p for p in products if p[1] not in UNSOLD]
    raw_orders = []
    for _ in range(420):
        customer = rng.choice(active)
        start = max(date.fromisoformat(customer[6]), date(2024, 1, 1))
        order_date = _random_date(rng, start, date(2025, 12, 31)).isoformat()
        employee = rng.choice(sales_staff) if rng.random() > 0.06 else None
        status = rng.choices(STATUSES, STATUS_WEIGHTS)[0]
        raw_orders.append((order_date, customer[0], employee, status))
    raw_orders.sort()

    orders, items = [], []
    for order_id, (order_date, customer_id, employee_id, status) in enumerate(raw_orders, start=1):
        orders.append((order_id, customer_id, employee_id, order_date, status))
        for product in rng.sample(sellable, rng.randint(1, 4)):
            items.append((len(items) + 1, order_id, product[0], rng.randint(1, 5), product[3]))
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)

    conn.commit()
    conn.close()
