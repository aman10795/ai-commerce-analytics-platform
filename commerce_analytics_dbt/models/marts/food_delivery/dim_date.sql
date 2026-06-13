with dates as (

    select *
    from range(
        date '2023-01-01',
        date '2030-12-31',
        interval 1 day
    ) as t(date_day)

)

select
    cast(date_day as date) as date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(day from date_day) as day_of_month,
    extract(week from date_day) as week_of_year,
    ceil(extract(day from date_day) / 7.0) as week_of_month,
    date_trunc('month', date_day) as month_start_date,
    date_trunc('year', date_day) as year_start_date

from dates