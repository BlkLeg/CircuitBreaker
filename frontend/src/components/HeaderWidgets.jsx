import { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { CalendarDays, Clock, Sun } from 'lucide-react';

const HeaderWidgets = ({ settings }) => {
  const showHeaderWidgets = settings?.showHeaderWidgets ?? settings?.show_header_widgets ?? true;
  const showTimeWidget = settings?.showTimeWidget ?? settings?.show_time_widget ?? true;
  const showWeatherWidget = settings?.showWeatherWidget ?? settings?.show_weather_widget ?? true;
  const weatherLocation = settings?.weatherLocation ?? settings?.weather_location ?? 'Phoenix, AZ';
  const timezone = settings?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

  const [now, setNow] = useState(new Date());
  const weather = { temp: '72°F', condition: 'Sunny' };

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  const timeText = useMemo(
    () => new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }).format(now),
    [now, timezone]
  );

  const timezoneShort = useMemo(() => {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      timeZoneName: 'short',
      hour: '2-digit',
    }).formatToParts(now);
    return parts.find((part) => part.type === 'timeZoneName')?.value || timezone;
  }, [now, timezone]);

  const weekdayText = useMemo(
    () => new Intl.DateTimeFormat('en-US', { timeZone: timezone, weekday: 'long' }).format(now),
    [now, timezone]
  );

  const fullDateText = useMemo(
    () => new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    }).format(now),
    [now, timezone]
  );

  const monthShortText = useMemo(
    () => new Intl.DateTimeFormat('en-US', { timeZone: timezone, month: 'short' }).format(now).toUpperCase(),
    [now, timezone]
  );

  const dayNumberText = useMemo(
    () => new Intl.DateTimeFormat('en-US', { timeZone: timezone, day: 'numeric' }).format(now),
    [now, timezone]
  );

  if (!showHeaderWidgets || (!showTimeWidget && !showWeatherWidget)) return null;

  return (
    <div className="header-widgets" aria-label="Header status widgets">
      {showWeatherWidget && (
        <section className="header-widget header-widget--weather" aria-label="Weather widget">
          <Sun size={16} className="header-widget-icon header-widget-icon--sun" />
          <div className="header-widget-copy">
            <div className="header-widget-kicker">{weatherLocation.toUpperCase()}</div>
            <div className="header-widget-main">{weather.temp} | {weather.condition}</div>
          </div>
        </section>
      )}

      {showTimeWidget && (
        <>
          <section className="header-widget header-widget--time" aria-label="Time widget">
            <Clock size={15} className="header-widget-icon" />
            <div className="header-widget-copy">
              <div className="header-widget-main">{timeText}</div>
              <div className="header-widget-sub">{timezoneShort}</div>
            </div>
          </section>

          <section className="header-widget header-widget--date" aria-label="Date widget">
            <div className="header-widget-date-chip">
              <span className="header-widget-date-day">{dayNumberText}</span>
              <span className="header-widget-date-month">{monthShortText}</span>
            </div>
            <CalendarDays size={15} className="header-widget-icon" />
            <div className="header-widget-copy">
              <div className="header-widget-main">{weekdayText}</div>
              <div className="header-widget-sub">{fullDateText}</div>
            </div>
          </section>
        </>
      )}
    </div>
  );
};

HeaderWidgets.propTypes = {
  settings: PropTypes.shape({
    showHeaderWidgets: PropTypes.bool,
    showTimeWidget: PropTypes.bool,
    showWeatherWidget: PropTypes.bool,
    weatherLocation: PropTypes.string,
    timezone: PropTypes.string,
    show_header_widgets: PropTypes.bool,
    show_time_widget: PropTypes.bool,
    show_weather_widget: PropTypes.bool,
    weather_location: PropTypes.string,
  }),
};

HeaderWidgets.defaultProps = {
  settings: null,
};

export default HeaderWidgets;
