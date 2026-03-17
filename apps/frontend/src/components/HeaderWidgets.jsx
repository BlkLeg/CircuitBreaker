import { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import {
  CalendarDays,
  Clock,
  Sun,
  Cloud,
  CloudRain,
  Snowflake,
  CloudLightning,
} from 'lucide-react';

const WMO_CODES = {
  0: 'Clear',
  1: 'Mostly Clear',
  2: 'Partly Cloudy',
  3: 'Overcast',
  45: 'Fog',
  48: 'Fog',
  51: 'Drizzle',
  53: 'Drizzle',
  55: 'Drizzle',
  56: 'Freezing Drizzle',
  57: 'Freezing Drizzle',
  61: 'Rain',
  63: 'Rain',
  65: 'Heavy Rain',
  66: 'Freezing Rain',
  67: 'Freezing Rain',
  71: 'Snow',
  73: 'Snow',
  75: 'Heavy Snow',
  77: 'Snow Grains',
  80: 'Rain Showers',
  81: 'Rain Showers',
  82: 'Heavy Rain Showers',
  85: 'Snow Showers',
  86: 'Snow Showers',
  95: 'Thunderstorm',
  96: 'Thunderstorm',
  99: 'Thunderstorm',
};

const WEATHER_REFRESH_INTERVAL_MS = 15 * 60 * 1000;

const buildLocationCandidates = (value) => {
  const primary = value.trim();
  const beforeComma = primary.split(',')[0]?.trim();
  const candidates = [primary];
  if (beforeComma && beforeComma !== primary) {
    candidates.push(beforeComma);
  }
  return [...new Set(candidates)];
};

const resolveCoordinates = async (location) => {
  const candidates = buildLocationCandidates(location);
  for (const candidate of candidates) {
    const geoRes = await fetch(
      `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(candidate)}&count=1&language=en&format=json`
    );
    if (!geoRes.ok) {
      continue;
    }
    const geoData = await geoRes.json();
    if (geoData.results?.length) {
      const { latitude, longitude } = geoData.results[0];
      return { latitude, longitude };
    }
  }
  return null;
};

const HeaderWidgets = ({ settings = {} }) => {
  const showHeaderWidgets = settings?.showHeaderWidgets ?? settings?.show_header_widgets ?? true;
  const showTimeWidget = settings?.showTimeWidget ?? settings?.show_time_widget ?? true;
  const showWeatherWidget = settings?.showWeatherWidget ?? settings?.show_weather_widget ?? true;
  const weatherLocation = settings?.weatherLocation ?? settings?.weather_location ?? 'Phoenix, AZ';
  const timezone = settings?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

  const [now, setNow] = useState(new Date());
  const [weatherData, setWeatherData] = useState({ temp: '--', condition: 'Loading...' });

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!showWeatherWidget || !weatherLocation) return;

    let isMounted = true;

    const fetchWeather = async () => {
      try {
        const coords = await resolveCoordinates(weatherLocation);
        if (!coords) {
          if (isMounted) setWeatherData({ temp: '--', condition: 'Not Found' });
          return;
        }
        const { latitude, longitude } = coords;

        const weatherRes = await fetch(
          `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current_weather=true&current=temperature_2m,weather_code&temperature_unit=fahrenheit`
        );
        if (!weatherRes.ok) {
          throw new Error(`Weather request failed with ${weatherRes.status}`);
        }
        const weatherJson = await weatherRes.json();
        const current = weatherJson.current_weather ?? weatherJson.current;
        const temperature = current?.temperature ?? current?.temperature_2m;
        const weatherCode = current?.weathercode ?? current?.weather_code;

        if (isMounted && temperature !== undefined) {
          setWeatherData({
            temp: `${Math.round(temperature)}°F`,
            condition: WMO_CODES[weatherCode] || 'Unknown',
            code: weatherCode,
          });
        }
      } catch (err) {
        console.error('Failed to fetch weather', err);
        if (isMounted) setWeatherData({ temp: '--', condition: 'Error' });
      }
    };

    fetchWeather();
    const weatherInterval = setInterval(fetchWeather, WEATHER_REFRESH_INTERVAL_MS);

    return () => {
      isMounted = false;
      clearInterval(weatherInterval);
    };
  }, [showWeatherWidget, weatherLocation]);

  const timeText = useMemo(
    () =>
      new Intl.DateTimeFormat('en-US', {
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
    () =>
      new Intl.DateTimeFormat('en-US', {
        timeZone: timezone,
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      }).format(now),
    [now, timezone]
  );

  const monthShortText = useMemo(
    () =>
      new Intl.DateTimeFormat('en-US', { timeZone: timezone, month: 'short' })
        .format(now)
        .toUpperCase(),
    [now, timezone]
  );

  const dayNumberText = useMemo(
    () => new Intl.DateTimeFormat('en-US', { timeZone: timezone, day: 'numeric' }).format(now),
    [now, timezone]
  );

  const WeatherIcon = useMemo(() => {
    if (weatherData.code === undefined) return Sun;
    const c = weatherData.code;
    if (c <= 1) return Sun;
    if (c <= 3 || c === 45 || c === 48) return Cloud;
    if ((c >= 51 && c <= 67) || (c >= 80 && c <= 82)) return CloudRain;
    if ((c >= 71 && c <= 77) || c === 85 || c === 86) return Snowflake;
    if (c >= 95) return CloudLightning;
    return Sun;
  }, [weatherData.code]);

  if (!showHeaderWidgets || (!showTimeWidget && !showWeatherWidget)) return null;

  return (
    <div className="header-widgets" aria-label="Header status widgets">
      {showWeatherWidget && (
        <section className="header-widget header-widget--weather" aria-label="Weather widget">
          <WeatherIcon size={16} className="header-widget-icon header-widget-icon--sun" />
          <div className="header-widget-copy">
            <div className="header-widget-kicker">{weatherLocation.toUpperCase()}</div>
            <div className="header-widget-main">
              {weatherData.temp} | {weatherData.condition}
            </div>
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

export default HeaderWidgets;
