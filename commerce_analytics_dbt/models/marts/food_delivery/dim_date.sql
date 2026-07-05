with dates as (

    select *
    from range(
        timestamp '2023-01-01 00:00:00',
        timestamp '2030-12-31 23:59:59',
        interval 1 hour -- Changed from day to hour
    ) as t(date_day)

)

select
    cast(date_day as date) as date_day,
    extract(hour from date_day) as hour_of_day, -- Returns 0 to 23
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(day from date_day) as day_of_month,
    
    -- Day of week columns
    extract(dow from date_day) as day_of_week,       
    extract(isodow from date_day) as day_of_week_iso, 
    dayname(date_day) as day_of_week_name,            

    extract(week from date_day) as week_of_year,
    ceil(extract(day from date_day) / 7.0) as week_of_month,
    date_trunc('month', date_day) as month_start_date,
    date_trunc('year', date_day) as year_start_date

from dates
