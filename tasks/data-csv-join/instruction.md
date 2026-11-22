`/workspace/orders.csv` has columns `order_id,customer_id,amount` and
`/workspace/customers.csv` has columns `customer_id,name,country`.

Compute the total order `amount` per customer `country`. Ignore any order whose
`customer_id` does not exist in `customers.csv`.

Write `/workspace/report.csv` with the header `country,total_amount`, one row per country,
amounts rounded to 2 decimal places, sorted by `total_amount` descending.
