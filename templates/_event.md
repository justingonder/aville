# {{ e.title }}

{% if is_stale %}> This event is no longer listed on {{ e.business_name }}'s website. Kept for reference.
{% endif %}
**When:** {{ event_when }}
**Venue:** {% if e.business_website %}[{{ e.business_name }}]({{ e.business_website }}){% else %}{{ e.business_name }}{% endif %}
{% if e.business_address %}**Address:** {{ e.business_address }}
{% endif %}{% if e.price_info %}**Price:** {{ e.price_info }}
{% endif %}{% if e.performers %}**Performers:** {% for p in e.performers %}{{ p.name }}{% if p.role %} ({{ p.role }}){% endif %}{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}{% if e.tags %}**Tags:** {{ e.tags | join(', ') }}
{% endif %}
{% if e.description %}{{ e.description }}
{% endif %}
{% if e.external_link %}**Official page:** <{{ e.external_link }}>
{% endif %}
---

- Canonical URL: {{ site_url }}/event/{{ e.id }}/
- HTML version: {{ site_url }}/event/{{ e.id }}/
- Back to full event listing: {{ site_url }}/
