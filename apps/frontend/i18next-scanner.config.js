module.exports = {
  input: ['src/**/*.{js,jsx,ts,tsx}'],
  output: './',
  options: {
    debug: false,
    removeUnusedKeys: false,
    sort: true,
    lngs: ['en', 'es', 'fr', 'de', 'zh', 'ja'],
    ns: ['common', 'header', 'map', 'settings', 'hardware'],
    defaultLng: 'en',
    defaultNs: 'common',
    resource: {
      loadPath: 'public/locales/{{lng}}/{{ns}}.json',
      savePath: 'public/locales/{{lng}}/{{ns}}.json',
      jsonIndent: 2,
      lineEnding: '\n',
    },
    func: {
      list: ['t'],
      extensions: ['.js', '.jsx', '.ts', '.tsx'],
    },
    trans: {
      component: 'Trans',
      i18nKey: 'i18nKey',
      defaultsKey: 'defaults',
      extensions: ['.js', '.jsx', '.ts', '.tsx'],
    },
    interpolation: {
      prefix: '{{',
      suffix: '}}',
    },
  },
};
