/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'getting-started',
    'architecture',
    {
      type: 'category',
      label: 'SDKs',
      items: ['sdk/python', 'sdk/node'],
    },
    {
      type: 'category',
      label: 'Guides',
      items: ['guides/skills', 'guides/devices', 'guides/genui'],
    },
    'contributing',
  ],
};

module.exports = sidebars;
