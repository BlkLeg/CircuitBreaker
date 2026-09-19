# Shared layouts

## Application shell

- Source: `apps/frontend/src/App.jsx`
- Description: fixed global header, optional lifecycle/status banners, scrollable page content, routed page transition, and auto-hiding dock.
- Render structure (exact render branch, logic omitted):

```jsx
return (
  <div className="app-shell">
    <CommandPalette isOpen={paletteOpen} onClose={handleClosePalette} />
    <Header onOpenPalette={handleOpenPalette} />
    <MasqueradeBanner />
    <ConnectionStatus discoveryConnected={discoveryConnected} />
    <div className="page-content">
      <UpdateBanner />
      <ErrorBoundary>
        <React.Suspense fallback={<LoadingScreen />}>
          <AnimatePresence mode="wait">
            <motion.div key={location.pathname} data-route-path={location.pathname}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}>
              <NavigationMountSignal />
              <Routes location={location}>{/* route elements */}</Routes>
            </motion.div>
          </AnimatePresence>
        </React.Suspense>
      </ErrorBoundary>
    </div>
    <MacOSDOCK pendingCount={pendingCount} wsStatus={wsStatus} />
  </div>
);
```

## Global header

- Source: `apps/frontend/src/components/Header.jsx`
- Description: fixed 60px header with real logo + brand text, weather/time/date widgets, route menu, recent changes, palette/theme buttons, avatar, and command-palette trigger.
- Key structure from the full component:

```jsx
<header className="global-header" role="banner" style={{ position: 'fixed', top: 0, left: 0,
  right: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '8px 16px', background: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)',
  height: 'var(--header-height)' }}>
  <Link to="/map" title="Home" aria-label={`${appName} — Home`} className="header-brand-link">
    <img src={branding?.login_logo_path ?? '/CB-AZ_Final.png'} alt={appName}
      className="header-logo" style={{ height: 40, width: 'auto', maxWidth: 120 }} />
    <div className="header-brand-text"><span className="header-brand-name">{appName}</span>
      {isAuthenticated && user && <span className="header-greeting">Welcome, {greetingName}</span>}</div>
  </Link>
  <div style={{ position: 'absolute', left: '50%', transform: 'translate(-50%, -50%)', top: '50%' }}>
    <HeaderWidgets settings={settings} />
  </div>
  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
    <button aria-label="Open route menu"><Menu size={16} /> Routes</button>
    <RecentChanges /><ThemePalette placement="header" />
    <button aria-label={isLightTheme ? 'Switch to dark mode' : 'Switch to light mode'}>
      {isLightTheme ? <Moon size={16} /> : <Sun size={16} />}
    </button>
    <UserAvatar onOpenAuth={openAuthModal} onOpenProfile={openProfileModal} />
    <button className="search-trigger" onClick={onOpenPalette} aria-label="Open command palette">
      <Search size={14} /><span>Type a command or search...</span><span>Ctrl K</span>
    </button>
  </div>
</header>
```

## Bottom dock

- Source: `apps/frontend/src/components/MacOSDOCK.jsx`
- Description: permission-aware route dock; desktop auto-hides near the viewport edge and mobile keeps three primary routes visible.

```jsx
return (
  <div className={['macos-dock-root', !dockVisible && !isMobile && 'is-hidden'].filter(Boolean).join(' ')} data-mobile={isMobile ? 'true' : 'false'}>
    <nav aria-label="MacOS dock" className="macos-dock-shelf" ref={dockRef}
      onMouseEnter={showDock} onMouseLeave={scheduleHideDock}>
      <div className="macos-dock-items">
        {visibleItems.map((item) => <DockIcon key={item.id} item={item}
          label={t(item.labelKey, { defaultValue: item.label })}
          isActive={isActivePath(location.pathname, item.path)}
          pendingCount={item.id === 'discovery' ? pendingCount : 0}
          wsStatus={item.id === 'discovery' ? wsStatus : null} isMobile={isMobile} />)}
      </div>
    </nav>
  </div>
);
```
