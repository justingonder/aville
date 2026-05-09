# A'ville.net — Andersonville, Chicago

What's happening in Andersonville: events, happy hours, live music, drag shows, trivia, theater, and more from local bars, restaurants, and venues. Updated daily.

- Site: {{ site_url }}/
- Sitemap: {{ site_url }}/sitemap.xml
- Last updated: {{ last_updated or build_date.strftime('%A, %B %-d') }}
- Timezone: America/Chicago (all event times are local)

{% macro event_line(ev) -%}
- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ ev.business_name }}{% if when_text(ev) %} · {{ when_text(ev) }}{% endif %}
{%- endmacro %}

## Tonight — {{ build_date.strftime('%A, %B %-d') }}

{% if today_events %}### Dated events today
{% for ev in today_events %}{{ event_line(ev) }}
{% endfor %}
{% endif %}{% if today_recurring %}### Weekly regulars tonight
{% for ev in today_recurring %}{{ event_line(ev) }}
{% endfor %}
{% endif %}{% if not today_events and not today_recurring %}_Nothing listed tonight — check back tomorrow or browse the weekend._
{% endif %}
{% if this_week_events %}
## This week

{% for ev in this_week_events %}{{ event_line(ev) }}
{% endfor %}
{% endif %}
{% if this_weekend_events or weekend_recurring %}
## This weekend

{% if this_weekend_events %}### Dated events this weekend
{% for ev in this_weekend_events %}{{ event_line(ev) }}
{% endfor %}
{% endif %}{% if weekend_recurring %}### Weekly regulars this weekend
{% for ev in weekend_recurring %}{{ event_line(ev) }}
{% endfor %}
{% endif %}{% endif %}
{% if next_week_events %}
## Next week

{% for ev in next_week_events %}{{ event_line(ev) }}
{% endfor %}
{% endif %}
{% if next_weekend_events %}
## Next weekend

{% for ev in next_weekend_events %}{{ event_line(ev) }}
{% endfor %}
{% endif %}

## Coming up later

{% if later_events %}{% for ev in later_events %}{{ event_line(ev) }}
{% endfor %}{% else %}_No future dated events on the board right now._
{% endif %}

## Weekly regulars

{% for ev in recurring_events %}{{ event_line(ev) }}
{% endfor %}

## Venues

{% for slug, biz_name, note in venue_list %}- [**{{ biz_name }}**]({{ site_url }}/business/{{ slug }}/) — {{ note }}
{% endfor %}
