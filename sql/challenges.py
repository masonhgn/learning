"""lessons and challenges for sqlquest

each challenge is checked by running its solution on a fresh copy of the
database and comparing the result to yours. for challenges that change data,
the check query is run after your statements and after the solution, and the
two outputs are compared instead.

fields:
  key       stable id used for saving progress
  level     index into LEVELS
  title     short name
  prompt    what to do
  solution  one correct answer
  ordered   true if row order matters
  check     (optional) query that inspects the database after a data change
  hints     revealed one at a time with .hint
"""

LEVELS = [
    {
        "title": "SELECT basics",
        "lesson": """\
Every query asks for some columns FROM some table.

  SELECT * FROM customers;                  -- every column
  SELECT first_name, city FROM customers;   -- just these columns
  SELECT DISTINCT country FROM customers;   -- unique values only

  -- a computed column, named with AS
  SELECT price * 2 AS double_price FROM products;

  -- || glues text together
  SELECT first_name || ' ' || last_name FROM employees;

End every query with a semicolon. Queries can span several lines.
Try .tables and .schema to look around first.""",
    },
    {
        "title": "Filtering with WHERE",
        "lesson": """\
WHERE keeps only the rows where a condition is true.

  WHERE price > 50              -- also <, <=, >=, = and <> (not equal)
  WHERE category = 'Books'      -- text goes in single quotes
  WHERE price > 50 AND stock < 10
  WHERE country = 'UK' OR country = 'USA'
  WHERE country IN ('UK', 'USA')            -- shorthand for the OR above
  WHERE category NOT IN ('Books', 'Toys')
  WHERE price BETWEEN 10 AND 20             -- inclusive on both ends
  WHERE email LIKE '%@gmail.com'            -- % any text, _ one char
  WHERE email IS NULL                       -- = NULL never matches

Dates here are stored as text like '2025-03-14', so they compare and sort correctly.""",
    },
    {
        "title": "Sorting and limiting",
        "lesson": """\
ORDER BY sorts the result. LIMIT caps how many rows come back.

  ORDER BY price               -- ascending (smallest first) by default
  ORDER BY price DESC          -- largest first
  ORDER BY country, city       -- by country, then city within each
  LIMIT 5                      -- only the first 5 rows
  LIMIT 5 OFFSET 10            -- skip 10 rows, then take 5 (paging)

Without ORDER BY, the database may return rows in any order it likes.
When a challenge says how to break ties, include that column in ORDER BY.""",
    },
    {
        "title": "Aggregates and GROUP BY",
        "lesson": """\
Aggregate functions squash many rows into one value.

  SELECT COUNT(*) FROM orders;          -- number of rows
  SELECT COUNT(email) FROM customers;   -- counts only non NULL values
  SUM(x)  AVG(x)  MIN(x)  MAX(x)  ROUND(x, 2)

GROUP BY makes one output row per group instead of one for the whole table:

  SELECT country, COUNT(*) AS n
  FROM customers
  GROUP BY country;

WHERE filters rows before grouping. HAVING filters groups after:

  SELECT country, COUNT(*) FROM customers
  GROUP BY country
  HAVING COUNT(*) > 10;

More grouping tricks:

  COUNT(DISTINCT customer_id)               -- unique values only
  GROUP BY country, city                    -- one group per combination
  GROUP BY SUBSTR(order_date, 1, 4)         -- group by an expression (the year)""",
    },
    {
        "title": "JOINs",
        "lesson": """\
A JOIN lines up rows from two tables using a matching column.

  SELECT o.id, c.first_name
  FROM orders o                          -- o is a short alias for orders
  JOIN customers c ON c.id = o.customer_id;

JOIN (aka INNER JOIN) keeps only rows that match on both sides.
LEFT JOIN keeps every row from the left table, filling NULLs when there is no match:

  SELECT c.first_name, o.id
  FROM customers c
  LEFT JOIN orders o ON o.customer_id = c.id;

Find rows with no match ("anti join"): LEFT JOIN then WHERE right_side.id IS NULL.
With a LEFT JOIN, a filter on the right table belongs in ON, not WHERE:

  LEFT JOIN orders o ON o.customer_id = c.id AND o.status = 'shipped'

In WHERE it would throw away the NULL rows and turn it back into an inner join.
JOIN and GROUP BY combine: join first, then group the joined rows.
A table can join to itself (self join), e.g. employees to their manager.
You can chain several JOINs in one query.""",
    },
    {
        "title": "Subqueries",
        "lesson": """\
A subquery is a query inside another query, wrapped in parentheses.

  -- as a single value
  SELECT name FROM products
  WHERE price > (SELECT AVG(price) FROM products);

  -- as a list
  SELECT * FROM customers WHERE id IN (SELECT customer_id FROM orders);

  -- correlated: refers to the outer row, runs once per outer row
  SELECT name FROM products p
  WHERE price > (SELECT AVG(price) FROM products x
                 WHERE x.category = p.category);

  -- EXISTS: true if the subquery returns at least one row
  WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)
  WHERE NOT EXISTS (...)""",
    },
    {
        "title": "CASE and functions",
        "lesson": """\
CASE is if/else for SQL:

  CASE WHEN price < 20 THEN 'cheap'
       WHEN price < 100 THEN 'normal'
       ELSE 'fancy' END AS label

Handy functions (SQLite flavor):

  COALESCE(email, 'none')        -- first non NULL value
  UPPER(x)  LOWER(x)  LENGTH(x)
  SUBSTR(text, start, length)    -- start counts from 1
  INSTR(text, '@')               -- position of '@', 0 if missing
  strftime('%Y-%m', order_date)  -- '2025-03' from '2025-03-14'
  julianday(a) - julianday(b)    -- days between two dates

Conditional counting, a classic trick:

  SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count""",
    },
    {
        "title": "CTEs and window functions",
        "lesson": """\
A CTE (WITH clause) names a subquery so you can read and reuse it:

  WITH spend AS (
      SELECT customer_id, COUNT(*) AS n FROM orders GROUP BY customer_id
  )
  SELECT * FROM spend WHERE n > 5;

Window functions compute across related rows WITHOUT collapsing them:

  ROW_NUMBER() OVER (PARTITION BY category ORDER BY price DESC)
  RANK()       OVER (PARTITION BY department_id ORDER BY salary DESC)
  SUM(x)       OVER (ORDER BY month)       -- running total
  LAG(x)       OVER (ORDER BY month)       -- value from the previous row

PARTITION BY is like GROUP BY for windows: numbering restarts in each group.
You cannot use a window result in WHERE directly; wrap it in a CTE or subquery.""",
    },
    {
        "title": "Changing data",
        "lesson": """\
Now you write to the database.

  INSERT INTO products (name, category, price, stock)
  VALUES ('Lamp', 'Kitchen', 30, 5);
  UPDATE products SET stock = stock + 10 WHERE category = 'Toys';
  DELETE FROM orders WHERE status = 'cancelled';

UPDATE or DELETE without WHERE hits EVERY row. The pro habit: write the
WHERE as a SELECT first, check the rows, then turn it into UPDATE/DELETE.

Every attempt runs on a fresh copy of the data, so nothing here is permanent.
You can enter several statements in one go; the checker inspects the tables
afterwards. Foreign keys are enforced: you cannot delete a row that others point at.""",
    },
    {
        "title": "Boss fights",
        "lesson": """\
Everything at once. Break each problem into steps: write a CTE for
step one, SELECT from it to check, then build the next step on top.
Real analysts work exactly like this.""",
    },
]

NOT_CANCELLED = "o.status <> 'cancelled'"

CHALLENGES = [
    #level 1 select basics
    {
        "key": "select_all",
        "level": 0,
        "title": "Hello, database",
        "prompt": "Show every column of every row in the products table.",
        "solution": "SELECT * FROM products;",
        "hints": ["* means all columns.", "SELECT * FROM table_name;"],
    },
    {
        "key": "select_columns",
        "level": 0,
        "title": "Pick your columns",
        "prompt": "Show the first_name, last_name and city of every customer (in that column order).",
        "solution": "SELECT first_name, last_name, city FROM customers;",
        "hints": ["List columns separated by commas after SELECT."],
    },
    {
        "key": "distinct_categories",
        "level": 0,
        "title": "No duplicates",
        "prompt": "List each product category exactly once.",
        "solution": "SELECT DISTINCT category FROM products;",
        "hints": ["SELECT category FROM products; repeats categories. One keyword fixes that.", "DISTINCT goes right after SELECT."],
    },
    {
        "key": "computed_column",
        "level": 0,
        "title": "Tax time",
        "prompt": "Show each product's name and its price with 8% tax added, in a column named price_with_tax.",
        "solution": "SELECT name, price * 1.08 AS price_with_tax FROM products;",
        "hints": ["Adding 8% is the same as multiplying by 1.08.", "Use AS to name a computed column."],
    },
    {
        "key": "full_name",
        "level": 0,
        "title": "Name tags",
        "prompt": "Show one column named full_name for every employee, like 'Ava Smith' (first name, a space, last name).",
        "solution": "SELECT first_name || ' ' || last_name AS full_name FROM employees;",
        "hints": ["In SQLite, || joins text together.", "first_name || ' ' || last_name"],
    },
    #level 2 where
    {
        "key": "where_equals",
        "level": 1,
        "title": "Gadgets only",
        "prompt": "Show the name and price of products in the 'Electronics' category.",
        "solution": "SELECT name, price FROM products WHERE category = 'Electronics';",
        "hints": ["WHERE category = '...'", "Text values need single quotes and are case sensitive."],
    },
    {
        "key": "where_and",
        "level": 1,
        "title": "Pricey and scarce",
        "prompt": "Show name, price and stock of products that cost more than 100 AND have fewer than 50 in stock.",
        "solution": "SELECT name, price, stock FROM products WHERE price > 100 AND stock < 50;",
        "hints": ["Combine two conditions with AND."],
    },
    {
        "key": "where_in",
        "level": 1,
        "title": "Neighbors",
        "prompt": "Show first_name, last_name and country of customers from Canada or Mexico.",
        "solution": "SELECT first_name, last_name, country FROM customers WHERE country IN ('Canada', 'Mexico');",
        "hints": ["Either OR, or the tidier IN ('a', 'b')."],
    },
    {
        "key": "where_not_in",
        "level": 1,
        "title": "Not for kids, not for reading",
        "prompt": "Show name, category and price of products that are NOT in 'Books' or 'Toys' and cost less than 40.",
        "solution": "SELECT name, category, price FROM products WHERE category NOT IN ('Books', 'Toys') AND price < 40;",
        "hints": ["NOT IN (...) is the opposite of IN.", "Then add AND price < 40."],
    },
    {
        "key": "where_between",
        "level": 1,
        "title": "The March rush",
        "prompt": "Show the id and order_date of every order placed in March 2025.",
        "solution": "SELECT id, order_date FROM orders WHERE order_date BETWEEN '2025-03-01' AND '2025-03-31';",
        "hints": ["Dates are text like '2025-03-14'.", "BETWEEN 'start' AND 'end' includes both ends."],
    },
    {
        "key": "where_like",
        "level": 1,
        "title": "Gmail users",
        "prompt": "Show the first_name and email of customers whose email ends in @gmail.com.",
        "solution": "SELECT first_name, email FROM customers WHERE email LIKE '%@gmail.com';",
        "hints": ["LIKE with % matches any run of characters.", "'%@gmail.com' means: anything, then @gmail.com at the end."],
    },
    {
        "key": "where_null",
        "level": 1,
        "title": "Off the grid",
        "prompt": "Show id, first_name and last_name of customers who have no email on file.",
        "solution": "SELECT id, first_name, last_name FROM customers WHERE email IS NULL;",
        "hints": ["Missing values are NULL.", "email = NULL never matches anything. Use IS NULL."],
    },
    {
        "key": "where_null_2",
        "level": 1,
        "title": "Nobody's the boss of me",
        "prompt": "Show first_name, last_name and title of employees who have no manager.",
        "solution": "SELECT first_name, last_name, title FROM employees WHERE manager_id IS NULL;",
        "hints": ["Look at the manager_id column."],
    },
    #level 3 order by and limit
    {
        "key": "order_limit",
        "level": 2,
        "title": "Top shelf",
        "prompt": "Show name and price of the 5 most expensive products, most expensive first.",
        "solution": "SELECT name, price FROM products ORDER BY price DESC LIMIT 5;",
        "ordered": True,
        "hints": ["ORDER BY price DESC puts the biggest first.", "LIMIT goes at the very end."],
    },
    {
        "key": "order_multi",
        "level": 2,
        "title": "Org chart sort",
        "prompt": "Show first_name, department_id and salary of all employees, sorted by department_id (lowest first), then salary (highest first), then employee id (lowest first) to break ties.",
        "solution": "SELECT first_name, department_id, salary FROM employees ORDER BY department_id, salary DESC, id;",
        "ordered": True,
        "hints": ["ORDER BY accepts several columns separated by commas.", "Each column gets its own ASC or DESC.", "You can sort by a column you did not SELECT."],
    },
    {
        "key": "offset",
        "level": 2,
        "title": "Page three",
        "prompt": "A shop page shows 5 products per page sorted alphabetically by name. Show just the name column for page 3.",
        "solution": "SELECT name FROM products ORDER BY name LIMIT 5 OFFSET 10;",
        "ordered": True,
        "hints": ["Page 3 means skip the first two pages (10 rows).", "LIMIT 5 OFFSET ..."],
    },
    {
        "key": "newest_customers",
        "level": 2,
        "title": "Fresh faces",
        "prompt": "Show first_name, last_name and signup_date of the 3 most recently signed up customers, newest first. Break ties by customer id, lowest first.",
        "solution": "SELECT first_name, last_name, signup_date FROM customers ORDER BY signup_date DESC, id LIMIT 3;",
        "ordered": True,
        "hints": ["Newest date first means DESC.", "Add id as a second sort column."],
    },
    #level 4 aggregates
    {
        "key": "count_rows",
        "level": 3,
        "title": "Headcount",
        "prompt": "How many customers are there? Return a single number.",
        "solution": "SELECT COUNT(*) FROM customers;",
        "hints": ["COUNT(*) counts rows."],
    },
    {
        "key": "avg_round",
        "level": 3,
        "title": "Average price",
        "prompt": "What is the average product price, rounded to 2 decimal places?",
        "solution": "SELECT ROUND(AVG(price), 2) FROM products;",
        "hints": ["AVG(column)", "Wrap it: ROUND(AVG(price), 2)"],
    },
    {
        "key": "count_column",
        "level": 3,
        "title": "Reachable customers",
        "prompt": "How many customers have an email address? Do it without a WHERE clause.",
        "solution": "SELECT COUNT(email) FROM customers;",
        "hints": ["COUNT(*) counts rows, but COUNT(column) counts something slightly different."],
    },
    {
        "key": "group_by",
        "level": 3,
        "title": "Customers per country",
        "prompt": "For each country, show country and the number of customers as customer_count.",
        "solution": "SELECT country, COUNT(*) AS customer_count FROM customers GROUP BY country;",
        "hints": ["GROUP BY country gives one row per country.", "Then COUNT(*) counts rows inside each group."],
    },
    {
        "key": "having",
        "level": 3,
        "title": "Crowded categories",
        "prompt": "Show category and product_count for categories that have more than 6 products.",
        "solution": "SELECT category, COUNT(*) AS product_count FROM products GROUP BY category HAVING COUNT(*) > 6;",
        "hints": ["You cannot filter on COUNT(*) with WHERE.", "HAVING goes after GROUP BY."],
    },
    {
        "key": "sum_expression",
        "level": 3,
        "title": "Gross revenue",
        "prompt": "What is the total revenue across all order_items (quantity times unit_price, summed), rounded to 2 decimals?",
        "solution": "SELECT ROUND(SUM(quantity * unit_price), 2) FROM order_items;",
        "hints": ["You can SUM an expression: SUM(a * b)."],
    },
    {
        "key": "group_order",
        "level": 3,
        "title": "Order pipeline",
        "prompt": "Show each order status and how many orders have it (as order_count), biggest count first. Break ties by status alphabetically.",
        "solution": "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY order_count DESC, status;",
        "ordered": True,
        "hints": ["GROUP BY status, then ORDER BY the count.", "You can ORDER BY an alias you defined in SELECT."],
    },
    {
        "key": "min_max",
        "level": 3,
        "title": "Pay bands",
        "prompt": "For each department_id, show department_id, min_salary and max_salary.",
        "solution": "SELECT department_id, MIN(salary) AS min_salary, MAX(salary) AS max_salary FROM employees GROUP BY department_id;",
        "hints": ["Two aggregates in one SELECT is fine."],
    },
    {
        "key": "group_two_columns",
        "level": 3,
        "title": "City by city",
        "prompt": "Show country, city and customer_count for every city that has customers, sorted by country then city.",
        "solution": "SELECT country, city, COUNT(*) AS customer_count FROM customers GROUP BY country, city ORDER BY country, city;",
        "ordered": True,
        "hints": ["You can GROUP BY more than one column: each distinct combination becomes a group.", "GROUP BY country, city"],
    },
    {
        "key": "where_then_group",
        "level": 3,
        "title": "Premium shelf",
        "prompt": "For each category, count the products priced over 50 as premium_count.",
        "solution": "SELECT category, COUNT(*) AS premium_count FROM products WHERE price > 50 GROUP BY category;",
        "hints": ["WHERE runs first and throws away the cheap rows, then GROUP BY groups what is left.", "WHERE comes before GROUP BY in the query."],
    },
    {
        "key": "group_avg",
        "level": 3,
        "title": "Category price check",
        "prompt": "Show category and avg_price (rounded to 2 decimals) for each category, most expensive category first.",
        "solution": "SELECT category, ROUND(AVG(price), 2) AS avg_price FROM products GROUP BY category ORDER BY avg_price DESC;",
        "ordered": True,
        "hints": ["ROUND(AVG(price), 2) inside a GROUP BY query works per group.", "ORDER BY avg_price DESC"],
    },
    {
        "key": "count_distinct",
        "level": 3,
        "title": "Loyal following",
        "prompt": "For each employee_id that handled orders, show employee_id and how many different customers they served (as customer_count). Skip orders with no employee. Most customers first, ties by employee_id.",
        "solution": "SELECT employee_id, COUNT(DISTINCT customer_id) AS customer_count FROM orders WHERE employee_id IS NOT NULL GROUP BY employee_id ORDER BY customer_count DESC, employee_id;",
        "ordered": True,
        "hints": ["A customer with 5 orders should only count once.", "COUNT(DISTINCT column) counts unique values.", "Filter out NULL employees with WHERE employee_id IS NOT NULL."],
    },
    {
        "key": "group_top_n",
        "level": 3,
        "title": "Big baskets",
        "prompt": "Using order_items, show order_id and order_total (quantity times unit_price summed, rounded to 2) for the 5 biggest orders. Biggest first, ties by order_id.",
        "solution": "SELECT order_id, ROUND(SUM(quantity * unit_price), 2) AS order_total FROM order_items GROUP BY order_id ORDER BY order_total DESC, order_id LIMIT 5;",
        "ordered": True,
        "hints": ["One group per order_id.", "SUM an expression, then ORDER BY it and LIMIT 5."],
    },
    {
        "key": "having_sum",
        "level": 3,
        "title": "Best sellers",
        "prompt": "Show product_id and units_sold (total quantity across order_items) for products that sold at least 100 units, most units first, ties by product_id.",
        "solution": "SELECT product_id, SUM(quantity) AS units_sold FROM order_items GROUP BY product_id HAVING SUM(quantity) >= 100 ORDER BY units_sold DESC, product_id;",
        "ordered": True,
        "hints": ["Total per product first: GROUP BY product_id.", "Filtering on the total needs HAVING, not WHERE."],
    },
    {
        "key": "having_avg",
        "level": 3,
        "title": "Well paid teams",
        "prompt": "Show department_id, headcount and avg_salary (rounded to 2) for departments whose average salary is above 100000.",
        "solution": "SELECT department_id, COUNT(*) AS headcount, ROUND(AVG(salary), 2) AS avg_salary FROM employees GROUP BY department_id HAVING AVG(salary) > 100000;",
        "hints": ["Two aggregates plus a HAVING on a third.", "HAVING AVG(salary) > 100000"],
    },
    {
        "key": "group_expression",
        "level": 3,
        "title": "Year over year",
        "prompt": "Show year (like '2025') and order_count for each year that has orders, oldest year first.",
        "solution": "SELECT SUBSTR(order_date, 1, 4) AS year, COUNT(*) AS order_count FROM orders GROUP BY year ORDER BY year;",
        "ordered": True,
        "hints": ["You can GROUP BY an expression, not just a column.", "SUBSTR(order_date, 1, 4) is the first 4 characters: the year."],
    },
    {
        "key": "group_stock_value",
        "level": 3,
        "title": "Warehouse worth",
        "prompt": "For each category, show category and stock_value: the total of price times stock, rounded to 2. Most valuable category first.",
        "solution": "SELECT category, ROUND(SUM(price * stock), 2) AS stock_value FROM products GROUP BY category ORDER BY stock_value DESC;",
        "ordered": True,
        "hints": ["Multiply inside the SUM, one row at a time: SUM(price * stock).", "ORDER BY stock_value DESC"],
    },
    {
        "key": "group_spread",
        "level": 3,
        "title": "Price spread",
        "prompt": "For each category, show category, cheapest, priciest and spread (priciest minus cheapest, rounded to 2). Widest spread first.",
        "solution": "SELECT category, MIN(price) AS cheapest, MAX(price) AS priciest, ROUND(MAX(price) - MIN(price), 2) AS spread FROM products GROUP BY category ORDER BY spread DESC;",
        "ordered": True,
        "hints": ["You can do arithmetic between aggregates: MAX(price) - MIN(price)."],
    },
    {
        "key": "having_two_conditions",
        "level": 3,
        "title": "Packed orders",
        "prompt": "Using order_items, show order_id, line_items (number of rows) and units (total quantity) for orders with exactly 4 line items AND at least 15 units. Sort by order_id.",
        "solution": "SELECT order_id, COUNT(*) AS line_items, SUM(quantity) AS units FROM order_items GROUP BY order_id HAVING COUNT(*) = 4 AND SUM(quantity) >= 15 ORDER BY order_id;",
        "ordered": True,
        "hints": ["COUNT(*) counts line items, SUM(quantity) counts units.", "HAVING can combine conditions with AND, just like WHERE."],
    },
    {
        "key": "group_year_status",
        "level": 3,
        "title": "Status by year",
        "prompt": "Show year (like '2025'), status and order_count for every year and status combination. Sort by year, then status.",
        "solution": "SELECT SUBSTR(order_date, 1, 4) AS year, status, COUNT(*) AS order_count FROM orders GROUP BY year, status ORDER BY year, status;",
        "ordered": True,
        "hints": ["Group by two things: an expression and a column.", "GROUP BY year, status"],
    },
    {
        "key": "where_having",
        "level": 3,
        "title": "Regulars",
        "prompt": "Show customer_id and order_count for customers with at least 10 orders that were not cancelled. Most orders first, ties by customer_id.",
        "solution": "SELECT customer_id, COUNT(*) AS order_count FROM orders WHERE status <> 'cancelled' GROUP BY customer_id HAVING COUNT(*) >= 10 ORDER BY order_count DESC, customer_id;",
        "ordered": True,
        "hints": ["Cancelled orders should be thrown away before counting. Which clause runs before grouping?", "WHERE for the rows, HAVING for the groups. You need both."],
    },
    #level 5 joins
    {
        "key": "inner_join",
        "level": 4,
        "title": "Who ordered what",
        "prompt": "Show every order's id, the customer's first_name and last_name, and the order_date.",
        "solution": "SELECT o.id, c.first_name, c.last_name, o.order_date FROM orders o JOIN customers c ON c.id = o.customer_id;",
        "hints": ["orders.customer_id points at customers.id.", "FROM orders o JOIN customers c ON c.id = o.customer_id"],
    },
    {
        "key": "join_departments",
        "level": 4,
        "title": "Where do they work",
        "prompt": "Show each employee's first_name, last_name and the name of their department.",
        "solution": "SELECT e.first_name, e.last_name, d.name FROM employees e JOIN departments d ON d.id = e.department_id;",
        "hints": ["Join employees.department_id to departments.id."],
    },
    {
        "key": "join_receipt",
        "level": 4,
        "title": "Receipt",
        "prompt": "For order 1, show each item's product name, quantity, unit_price and line_total (quantity times unit_price, rounded to 2). Sort by product name.",
        "solution": "SELECT p.name, oi.quantity, oi.unit_price, ROUND(oi.quantity * oi.unit_price, 2) AS line_total FROM order_items oi JOIN products p ON p.id = oi.product_id WHERE oi.order_id = 1 ORDER BY p.name;",
        "ordered": True,
        "hints": ["order_items.product_id points at products.id.", "WHERE comes after the JOIN: JOIN ... ON ... WHERE oi.order_id = 1"],
    },
    {
        "key": "join_where",
        "level": 4,
        "title": "Holiday rush",
        "prompt": "For orders placed in December 2025, show the order id, order_date and the first_name of the employee who handled it. Orders with no employee should not appear. Sort by order id.",
        "solution": "SELECT o.id, o.order_date, e.first_name FROM orders o JOIN employees e ON e.id = o.employee_id WHERE o.order_date LIKE '2025-12%' ORDER BY o.id;",
        "ordered": True,
        "hints": ["orders.employee_id points at employees.id.", "An inner JOIN already drops orders whose employee_id is NULL."],
    },
    {
        "key": "join_group",
        "level": 4,
        "title": "Department payroll",
        "prompt": "Show each department's name, headcount and total_salary. Biggest payroll first.",
        "solution": "SELECT d.name, COUNT(*) AS headcount, SUM(e.salary) AS total_salary FROM departments d JOIN employees e ON e.department_id = d.id GROUP BY d.id, d.name ORDER BY total_salary DESC;",
        "ordered": True,
        "hints": ["Join first, then GROUP BY the department.", "GROUP BY d.id, d.name is safest: two departments could share a name."],
    },
    {
        "key": "join_group_having",
        "level": 4,
        "title": "Sales leaderboard",
        "prompt": "Show first_name, last_name and orders_handled for employees who handled at least 40 orders. Most orders first, ties by last_name.",
        "solution": "SELECT e.first_name, e.last_name, COUNT(*) AS orders_handled FROM employees e JOIN orders o ON o.employee_id = e.id GROUP BY e.id, e.first_name, e.last_name HAVING COUNT(*) >= 40 ORDER BY orders_handled DESC, e.last_name;",
        "ordered": True,
        "hints": ["employees JOIN orders, one group per employee.", "Filter on the count with HAVING."],
    },
    {
        "key": "left_join_count",
        "level": 4,
        "title": "Including the window shoppers",
        "prompt": "For EVERY customer (even those with zero orders), show id, first_name and order_count.",
        "solution": "SELECT c.id, c.first_name, COUNT(o.id) AS order_count FROM customers c LEFT JOIN orders o ON o.customer_id = c.id GROUP BY c.id, c.first_name;",
        "hints": ["An inner JOIN drops customers with no orders. Which join keeps them?", "COUNT(*) would count 1 for a customer with no orders. COUNT(o.id) counts 0."],
    },
    {
        "key": "left_join_on_filter",
        "level": 4,
        "title": "Quiet year",
        "prompt": "For EVERY customer, show id, first_name and orders_2025: how many orders they placed in 2025. Customers with no 2025 orders must still appear, with 0. Sort by id.",
        "solution": "SELECT c.id, c.first_name, COUNT(o.id) AS orders_2025 FROM customers c LEFT JOIN orders o ON o.customer_id = c.id AND o.order_date LIKE '2025%' GROUP BY c.id, c.first_name ORDER BY c.id;",
        "ordered": True,
        "hints": ["Putting the date test in WHERE throws away the NULL rows the LEFT JOIN just added.", "Move the condition into the ON clause: ON o.customer_id = c.id AND o.order_date LIKE '2025%'"],
    },
    {
        "key": "anti_join",
        "level": 4,
        "title": "Dead stock",
        "prompt": "Show the name of every product that has never been ordered.",
        "solution": "SELECT p.name FROM products p LEFT JOIN order_items oi ON oi.product_id = p.id WHERE oi.id IS NULL;",
        "hints": ["LEFT JOIN products to order_items.", "Products with no match have NULL in every order_items column."],
    },
    {
        "key": "left_join_three",
        "level": 4,
        "title": "Sales floor",
        "prompt": "For every employee in the 'Sales' department, show first_name, last_name and orders_handled, including anyone who handled none. Fewest orders first, ties by last_name.",
        "solution": "SELECT e.first_name, e.last_name, COUNT(o.id) AS orders_handled FROM employees e JOIN departments d ON d.id = e.department_id LEFT JOIN orders o ON o.employee_id = e.id WHERE d.name = 'Sales' GROUP BY e.id, e.first_name, e.last_name ORDER BY orders_handled, e.last_name;",
        "ordered": True,
        "hints": ["Inner JOIN departments to find Sales people, then LEFT JOIN orders so nobody drops out.", "Filtering on d.name in WHERE is fine here: it is on the inner joined side.", "COUNT(o.id), not COUNT(*)."],
    },
    {
        "key": "self_join",
        "level": 4,
        "title": "Who's your boss",
        "prompt": "Show two columns: employee (the employee's first_name) and manager (their manager's first_name). Skip employees with no manager.",
        "solution": "SELECT e.first_name AS employee, m.first_name AS manager FROM employees e JOIN employees m ON m.id = e.manager_id;",
        "hints": ["Join the employees table to itself with two different aliases.", "e.manager_id = m.id"],
    },
    {
        "key": "self_join_group",
        "level": 4,
        "title": "Span of control",
        "prompt": "For every manager, show first_name, last_name and direct_reports (how many employees report to them). Most reports first, ties by last_name.",
        "solution": "SELECT m.first_name, m.last_name, COUNT(*) AS direct_reports FROM employees e JOIN employees m ON m.id = e.manager_id GROUP BY m.id, m.first_name, m.last_name ORDER BY direct_reports DESC, m.last_name;",
        "ordered": True,
        "hints": ["Same self join as before, but now group by the manager side.", "GROUP BY m.id, m.first_name, m.last_name"],
    },
    {
        "key": "multi_join",
        "level": 4,
        "title": "Revenue by category",
        "prompt": "Show category and revenue (sum of quantity times unit_price, rounded to 2) per product category, ignoring cancelled orders.",
        "solution": f"""SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE {NOT_CANCELLED}
GROUP BY p.category;""",
        "hints": ["You need three tables: order_items, products (for category), orders (for status).", "Chain two JOINs, filter with WHERE, then GROUP BY."],
    },
    {
        "key": "four_table_join",
        "level": 4,
        "title": "Bookworms abroad",
        "prompt": "Show country and books_sold (total quantity of 'Books' category products) per customer country, ignoring cancelled orders. Most books first.",
        "solution": f"""SELECT c.country, SUM(oi.quantity) AS books_sold
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE p.category = 'Books' AND {NOT_CANCELLED}
GROUP BY c.country
ORDER BY books_sold DESC;""",
        "ordered": True,
        "hints": ["Four tables: customers (country), orders (status), order_items (quantity), products (category).", "Walk the keys: customers -> orders -> order_items -> products."],
    },
    {
        "key": "top_customers",
        "level": 4,
        "title": "VIP list",
        "prompt": "Show first_name, last_name and total_spent (rounded to 2) of the top 5 customers by money spent on non cancelled orders, biggest first.",
        "solution": f"""SELECT c.first_name, c.last_name, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_items oi ON oi.order_id = o.id
WHERE {NOT_CANCELLED}
GROUP BY c.id
ORDER BY total_spent DESC
LIMIT 5;""",
        "ordered": True,
        "hints": ["customers -> orders -> order_items.", "GROUP BY the customer's id, not their name."],
    },
    #level 6 subqueries
    {
        "key": "scalar_subquery",
        "level": 5,
        "title": "Above average",
        "prompt": "Show name and price of products priced above the average product price.",
        "solution": "SELECT name, price FROM products WHERE price > (SELECT AVG(price) FROM products);",
        "hints": ["WHERE price > AVG(price) does not work. Compute the average in a subquery."],
    },
    {
        "key": "in_subquery",
        "level": 5,
        "title": "Changed their minds",
        "prompt": "Show first_name and last_name of customers who have at least one cancelled order. Each customer once.",
        "solution": "SELECT first_name, last_name FROM customers WHERE id IN (SELECT customer_id FROM orders WHERE status = 'cancelled');",
        "hints": ["Get the list of customer_ids with a cancelled order, then use IN.", "A JOIN works too, but watch for duplicates."],
    },
    {
        "key": "not_exists",
        "level": 5,
        "title": "Never bought a thing",
        "prompt": "Show first_name and last_name of customers who have never placed an order. Try NOT EXISTS this time.",
        "solution": "SELECT first_name, last_name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);",
        "hints": ["NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"],
    },
    {
        "key": "correlated",
        "level": 5,
        "title": "Above the team average",
        "prompt": "Show first_name, salary and department_id of employees who earn more than the average salary of their own department.",
        "solution": "SELECT e.first_name, e.salary, e.department_id FROM employees e WHERE e.salary > (SELECT AVG(x.salary) FROM employees x WHERE x.department_id = e.department_id);",
        "hints": ["The subquery needs to know which department the outer row is in.", "Alias the outer and inner employees tables differently."],
    },
    {
        "key": "exists",
        "level": 5,
        "title": "Six figure teams",
        "prompt": "Show the name of each department that has at least one employee earning more than 100000.",
        "solution": "SELECT d.name FROM departments d WHERE EXISTS (SELECT 1 FROM employees e WHERE e.department_id = d.id AND e.salary > 100000);",
        "hints": ["WHERE EXISTS (SELECT 1 FROM employees e WHERE ...)"],
    },
    #level 7 case and functions
    {
        "key": "case_when",
        "level": 6,
        "title": "Price tiers",
        "prompt": "Show name and tier for every product. tier is 'budget' under 25, 'mid' under 100, otherwise 'premium'.",
        "solution": "SELECT name, CASE WHEN price < 25 THEN 'budget' WHEN price < 100 THEN 'mid' ELSE 'premium' END AS tier FROM products;",
        "hints": ["CASE WHEN ... THEN ... WHEN ... THEN ... ELSE ... END", "Conditions are checked top to bottom; the first true one wins."],
    },
    {
        "key": "coalesce",
        "level": 6,
        "title": "Fill the gaps",
        "prompt": "Show id, first_name and contact for every customer. contact is their email, or the text 'no email' when it is missing.",
        "solution": "SELECT id, first_name, COALESCE(email, 'no email') AS contact FROM customers;",
        "hints": ["COALESCE returns the first non NULL argument."],
    },
    {
        "key": "strftime",
        "level": 6,
        "title": "Monthly volume",
        "prompt": "Show month (like '2025-03') and order_count for every month that has orders, in chronological order.",
        "solution": "SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS order_count FROM orders GROUP BY month ORDER BY month;",
        "ordered": True,
        "hints": ["strftime('%Y-%m', order_date) turns a date into 'YYYY-MM'.", "substr(order_date, 1, 7) also works."],
    },
    {
        "key": "conditional_agg",
        "level": 6,
        "title": "Email coverage",
        "prompt": "Per country, show country, with_email (customers who have an email) and without_email (customers who do not).",
        "solution": """SELECT country,
       SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS with_email,
       SUM(CASE WHEN email IS NULL THEN 1 ELSE 0 END) AS without_email
FROM customers
GROUP BY country;""",
        "hints": ["SUM(CASE WHEN condition THEN 1 ELSE 0 END) counts rows matching a condition.", "COUNT(email) is a shortcut for one of the two columns."],
    },
    {
        "key": "string_funcs",
        "level": 6,
        "title": "Email providers",
        "prompt": "Show domain (the part of the email after the @) and customers (how many customers use it). Ignore customers without an email.",
        "solution": "SELECT substr(email, instr(email, '@') + 1) AS domain, COUNT(*) AS customers FROM customers WHERE email IS NOT NULL GROUP BY domain;",
        "hints": ["instr(email, '@') finds the position of @.", "substr(text, start) with no length returns everything from start onward."],
    },
    #level 8 ctes and windows
    {
        "key": "cte",
        "level": 7,
        "title": "Big spenders",
        "prompt": "Consider only customers who have spent money on non cancelled orders. Show first_name, last_name and total_spent (rounded to 2) of those whose total is above the average total among them. Use a CTE.",
        "solution": f"""WITH spend AS (
    SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE {NOT_CANCELLED}
    GROUP BY o.customer_id
)
SELECT c.first_name, c.last_name, ROUND(s.total, 2) AS total_spent
FROM spend s
JOIN customers c ON c.id = s.customer_id
WHERE s.total > (SELECT AVG(total) FROM spend);""",
        "hints": ["Step 1: a CTE with customer_id and their total.", "Step 2: compare each total to (SELECT AVG(total) FROM your_cte)."],
    },
    {
        "key": "row_number",
        "level": 7,
        "title": "Flagship products",
        "prompt": "Show category, name and price of the single most expensive product in each category.",
        "solution": """SELECT category, name, price
FROM (
    SELECT category, name, price,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY price DESC, id) AS rn
    FROM products
)
WHERE rn = 1;""",
        "hints": ["ROW_NUMBER() OVER (PARTITION BY category ORDER BY price DESC)", "Wrap it in a subquery or CTE and keep rn = 1."],
    },
    {
        "key": "rank",
        "level": 7,
        "title": "Salary leaderboard",
        "prompt": "Show first_name, department_id, salary and salary_rank for every employee, where salary_rank is their RANK by salary within their department (1 = highest paid).",
        "solution": "SELECT first_name, department_id, salary, RANK() OVER (PARTITION BY department_id ORDER BY salary DESC) AS salary_rank FROM employees;",
        "hints": ["RANK() OVER (PARTITION BY ... ORDER BY ... DESC)"],
    },
    {
        "key": "running_total",
        "level": 7,
        "title": "Running total",
        "prompt": "For each month (like '2025-03'), show month, revenue (non cancelled orders) and running_total (revenue of that month plus all earlier months), in chronological order. Round both money columns to 2.",
        "solution": f"""WITH monthly AS (
    SELECT strftime('%Y-%m', o.order_date) AS month,
           SUM(oi.quantity * oi.unit_price) AS revenue
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE {NOT_CANCELLED}
    GROUP BY month
)
SELECT month, ROUND(revenue, 2) AS revenue,
       ROUND(SUM(revenue) OVER (ORDER BY month), 2) AS running_total
FROM monthly
ORDER BY month;""",
        "ordered": True,
        "hints": ["First build monthly revenue in a CTE.", "SUM(revenue) OVER (ORDER BY month) accumulates as it goes."],
    },
    {
        "key": "lag",
        "level": 7,
        "title": "Month over month",
        "prompt": "Show month, orders (number of orders that month, any status) and change (orders minus the previous month's orders; NULL for the first month), chronologically.",
        "solution": """WITH monthly AS (
    SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS orders
    FROM orders
    GROUP BY month
)
SELECT month, orders, orders - LAG(orders) OVER (ORDER BY month) AS change
FROM monthly
ORDER BY month;""",
        "ordered": True,
        "hints": ["LAG(orders) OVER (ORDER BY month) is last month's value."],
    },
    #level 9 dml
    {
        "key": "insert",
        "level": 8,
        "title": "New arrival",
        "prompt": "Add a product named 'Quantum Mug' in category 'Kitchen', price 19.99, stock 50. Let the database pick the id.",
        "solution": "INSERT INTO products (name, category, price, stock) VALUES ('Quantum Mug', 'Kitchen', 19.99, 50);",
        "check": "SELECT id, name, category, price, stock FROM products ORDER BY id;",
        "ordered": True,
        "hints": ["INSERT INTO table (col1, col2) VALUES (v1, v2);", "Leave id out of the column list and it gets filled automatically."],
    },
    {
        "key": "update",
        "level": 8,
        "title": "Book inflation",
        "prompt": "Raise the price of every product in 'Books' by 10%, rounded to 2 decimals. Nothing else should change.",
        "solution": "UPDATE products SET price = ROUND(price * 1.10, 2) WHERE category = 'Books';",
        "check": "SELECT id, name, category, price, stock FROM products ORDER BY id;",
        "ordered": True,
        "hints": ["UPDATE products SET price = ... WHERE ...;", "Forgetting WHERE would change every product."],
    },
    {
        "key": "update_where",
        "level": 8,
        "title": "Stale orders",
        "prompt": "Set status to 'cancelled' for every 'pending' order placed before 2025-06-01.",
        "solution": "UPDATE orders SET status = 'cancelled' WHERE status = 'pending' AND order_date < '2025-06-01';",
        "check": "SELECT id, status FROM orders ORDER BY id;",
        "ordered": True,
        "hints": ["Try it as a SELECT first to see which orders match.", "Two conditions in the WHERE."],
    },
    {
        "key": "delete",
        "level": 8,
        "title": "Spring cleaning",
        "prompt": "Delete every cancelled order, and its order_items too. Leave nothing pointing at a deleted order.",
        "solution": """DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE status = 'cancelled');
DELETE FROM orders WHERE status = 'cancelled';""",
        "check": """SELECT 'orders' AS tbl, COUNT(*), SUM(id) FROM orders
UNION ALL SELECT 'order_items', COUNT(*), SUM(id) FROM order_items
UNION ALL SELECT 'orphans', COUNT(*), 0 FROM order_items WHERE order_id NOT IN (SELECT id FROM orders);""",
        "ordered": True,
        "hints": ["Two DELETE statements. Order matters because of foreign keys.", "Delete the children (order_items) before the parents (orders).", "WHERE order_id IN (SELECT id FROM orders WHERE ...)"],
    },
    #level 10 boss fights
    {
        "key": "boss_sales",
        "level": 9,
        "title": "Sales leaderboard",
        "prompt": "Show first_name, last_name, orders_handled and revenue (rounded to 2) for the top 3 employees by revenue on non cancelled orders they handled, highest first. orders_handled counts their non cancelled orders.",
        "solution": f"""SELECT e.first_name, e.last_name, COUNT(DISTINCT o.id) AS orders_handled,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM employees e
JOIN orders o ON o.employee_id = e.id
JOIN order_items oi ON oi.order_id = o.id
WHERE {NOT_CANCELLED}
GROUP BY e.id
ORDER BY revenue DESC
LIMIT 3;""",
        "ordered": True,
        "hints": ["Joining to order_items multiplies order rows. COUNT(*) will overcount orders.", "COUNT(DISTINCT o.id)"],
    },
    {
        "key": "boss_retention",
        "level": 9,
        "title": "Loyal customers",
        "prompt": "Show first_name and last_name of customers who placed orders (any status) in BOTH 2024 and 2025.",
        "solution": """SELECT first_name, last_name FROM customers
WHERE id IN (SELECT customer_id FROM orders WHERE order_date LIKE '2024%')
  AND id IN (SELECT customer_id FROM orders WHERE order_date LIKE '2025%');""",
        "hints": ["Two separate conditions, each with its own subquery.", "INTERSECT is another option."],
    },
    {
        "key": "boss_onboarding",
        "level": 9,
        "title": "Time to first order",
        "prompt": "For each customer who has ordered, show first_name, last_name, signup_date, first_order (their earliest order_date) and days_to_first_order (whole days between signup_date and first_order).",
        "solution": """SELECT c.first_name, c.last_name, c.signup_date, MIN(o.order_date) AS first_order,
       CAST(julianday(MIN(o.order_date)) - julianday(c.signup_date) AS INTEGER) AS days_to_first_order
FROM customers c
JOIN orders o ON o.customer_id = c.id
GROUP BY c.id;""",
        "hints": ["MIN(order_date) per customer.", "julianday(a) - julianday(b) gives days; CAST(... AS INTEGER) drops decimals."],
    },
    {
        "key": "boss_bestsellers",
        "level": 9,
        "title": "Best sellers",
        "prompt": "For each category, show category, name and total_qty of the product with the most units sold on non cancelled orders. Break ties by lowest product id.",
        "solution": f"""WITH qty AS (
    SELECT p.id, p.category, p.name, SUM(oi.quantity) AS total_qty
    FROM products p
    JOIN order_items oi ON oi.product_id = p.id
    JOIN orders o ON o.id = oi.order_id
    WHERE {NOT_CANCELLED}
    GROUP BY p.id
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY total_qty DESC, id) AS rn
    FROM qty
)
SELECT category, name, total_qty FROM ranked WHERE rn = 1;""",
        "hints": ["CTE 1: units per product.", "CTE 2: ROW_NUMBER within each category.", "Keep rn = 1."],
    },
    {
        "key": "boss_share",
        "level": 9,
        "title": "Slice of the pie",
        "prompt": "Show category, revenue (non cancelled, rounded to 2) and pct_of_total (that category's share of all such revenue, as a percentage rounded to 1 decimal), largest share first.",
        "solution": f"""WITH cat AS (
    SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
    FROM order_items oi
    JOIN products p ON p.id = oi.product_id
    JOIN orders o ON o.id = oi.order_id
    WHERE {NOT_CANCELLED}
    GROUP BY p.category
)
SELECT category, ROUND(revenue, 2) AS revenue,
       ROUND(100.0 * revenue / (SELECT SUM(revenue) FROM cat), 1) AS pct_of_total
FROM cat
ORDER BY pct_of_total DESC;""",
        "ordered": True,
        "hints": ["Revenue per category in a CTE, then divide by the total.", "SUM(revenue) OVER () also gives the grand total on every row.", "Integer division trap: use 100.0, not 100."],
    },
    {
        "key": "boss_final",
        "level": 9,
        "title": "Customer of the month",
        "prompt": "For each month of 2025, show month (like '2025-03'), first_name, last_name and spent (rounded to 2) for the customer who spent the most on non cancelled orders that month. Break ties by lowest customer id. Chronological order.",
        "solution": f"""WITH monthly AS (
    SELECT strftime('%Y-%m', o.order_date) AS month, o.customer_id,
           SUM(oi.quantity * oi.unit_price) AS spent
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE {NOT_CANCELLED} AND o.order_date LIKE '2025%'
    GROUP BY month, o.customer_id
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY month ORDER BY spent DESC, customer_id) AS rn
    FROM monthly
)
SELECT r.month, c.first_name, c.last_name, ROUND(r.spent, 2) AS spent
FROM ranked r
JOIN customers c ON c.id = r.customer_id
WHERE r.rn = 1
ORDER BY r.month;""",
        "ordered": True,
        "hints": ["Spend per (month, customer) first.", "Then rank within each month and keep the winner.", "Join customers at the end for names."],
    },
]
