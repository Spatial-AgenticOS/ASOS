/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'getting-started',
    'architecture',
    'deployment',
    {
      type: 'category',
      label: 'SDKs',
      items: ['sdk/python', 'sdk/node'],
    },
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/skills',
        'guides/devices',
        'guides/genui',
        'guides/security',
        'guides/voice',
        'guides/memory',
        'guides/channels',
        'guides/autonomy',
        'guides/hardware',
      ],
    },
    'contributing',
  ],
};

module.exports = sidebars;
