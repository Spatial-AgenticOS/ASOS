// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'THEORA',
  tagline: 'The open-source AI operating system for your devices',
  favicon: 'img/favicon.ico',

  url: 'https://docs.theora.io',
  baseUrl: '/',

  organizationName: 'Spatial-AgenticOS',
  projectName: 'ASOS',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/Spatial-AgenticOS/ASOS/tree/main/docs/site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/theora-social.png',
      navbar: {
        title: 'THEORA',
        logo: {
          alt: 'THEORA Logo',
          src: 'img/logo.svg',
        },
        items: [
          { type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'Docs' },
          { to: '/sdk/python', label: 'Python SDK', position: 'left' },
          { to: '/sdk/node', label: 'Node SDK', position: 'left' },
          {
            href: 'https://github.com/Spatial-AgenticOS/ASOS',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Getting Started', to: '/getting-started' },
              { label: 'Architecture', to: '/architecture' },
              { label: 'Contributing', to: '/contributing' },
            ],
          },
          {
            title: 'SDKs',
            items: [
              { label: 'Python SDK', to: '/sdk/python' },
              { label: 'Node SDK', to: '/sdk/node' },
            ],
          },
          {
            title: 'Guides',
            items: [
              { label: 'Writing Skills', to: '/guides/skills' },
              { label: 'Device Adapters', to: '/guides/devices' },
              { label: 'GenUI Components', to: '/guides/genui' },
            ],
          },
          {
            title: 'Community',
            items: [
              { label: 'GitHub', href: 'https://github.com/Spatial-AgenticOS/ASOS' },
              { label: 'Issues', href: 'https://github.com/Spatial-AgenticOS/ASOS/issues' },
            ],
          },
        ],
        copyright: `Copyright © 2024–${new Date().getFullYear()} THEORA, Inc.`,
      },
      prism: {
        theme: require('prism-react-renderer').themes.github,
        darkTheme: require('prism-react-renderer').themes.dracula,
        additionalLanguages: ['bash', 'json', 'yaml', 'python', 'typescript'],
      },
    }),
};

module.exports = config;
