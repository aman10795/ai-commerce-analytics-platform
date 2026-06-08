{% snapshot wolt_addresses_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='address_id',
        strategy='check',
        check_cols=[
            'source_address_id_hash',
            'label_type',
            'is_verified',
            'city',
            'country',
            'postcode',
            'location_type',
            'address_version',
            'valid_from',
            'valid_to'
        ]
    )
}}

select
    address_id,
    source_address_id_hash,
    label_type,
    cast(is_verified as boolean) as is_verified,
    city,
    country,
    postcode,
    location_type,
    cast(address_version as integer) as address_version,
    cast(valid_from as date) as valid_from,
    cast(valid_to as date) as valid_to

from {{ ref('wolt_addresses') }}

{% endsnapshot %}