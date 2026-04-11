#!/usr/bin/env node
/**
 * create-feral-demo — One command to experience FERAL
 *
 * Usage:
 *   npx create-feral-demo
 *   npx create-feral-demo --scenario morning
 *   npx create-feral-demo --scenario developer
 *   npx create-feral-demo --scenario mesh
 */

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const readline = require('readline');

const BANNER = `
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║            T H E O R A   D E M O                        ║
║                                                          ║
║    The Open AI Operating System                          ║
║    Voice · Hardware · Memory · Self-Learning             ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
`;

const SCENARIOS = {
  morning: {
    name: 'Morning Routine',
    desc: 'Wake word → health briefing → calendar → smart home → voice chat',
    audience: 'Consumer demo',
  },
  developer: {
    name: 'Developer Flow',
    desc: 'Chat → write plugin → self-learning → GenUI → memory',
    audience: 'Developer demo',
  },
  mesh: {
    name: 'The Mesh',
    desc: 'Multi-device → health monitoring → proactive alerts → computer use',
    audience: 'Hardware/AI community',
  },
};

function checkPython() {
  try {
    const version = execSync('python3 --version 2>&1', { encoding: 'utf-8' }).trim();
    const match = version.match(/(\d+)\.(\d+)/);
    if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 10) {
      return 'python3';
    }
  } catch {}
  try {
    const version = execSync('python --version 2>&1', { encoding: 'utf-8' }).trim();
    const match = version.match(/(\d+)\.(\d+)/);
    if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 10) {
      return 'python';
    }
  } catch {}
  return null;
}

async function main() {
  console.log(BANNER);

  const args = process.argv.slice(2);
  let scenario = '';
  const scenarioIdx = args.indexOf('--scenario');
  if (scenarioIdx !== -1 && args[scenarioIdx + 1]) {
    scenario = args[scenarioIdx + 1];
  }

  const python = checkPython();
  if (!python) {
    console.error('  ❌ Python 3.10+ is required but not found.');
    console.error('     Install from: https://python.org/downloads/');
    process.exit(1);
  }
  console.log(`  ✓ Found ${python}`);

  // Check if FERAL is installed
  let installed = false;
  try {
    execSync(`${python} -c "import api.server"`, { stdio: 'ignore', cwd: process.cwd() });
    installed = true;
  } catch {}

  if (!installed) {
    console.log('  📦 Installing FERAL...');
    try {
      execSync(`${python} -m pip install feral-ai 2>&1`, { stdio: 'inherit' });
    } catch {
      console.log('  ℹ  pip install not available. Trying from source...');
      try {
        execSync('git clone --depth 1 https://github.com/feral-ai/feral /tmp/feral-demo 2>&1', { stdio: 'inherit' });
        execSync(`cd /tmp/feral-demo/feral && ${python} -m pip install -e ".[llm]" 2>&1`, { stdio: 'inherit' });
      } catch (e) {
        console.error('  ❌ Failed to install FERAL:', e.message);
        process.exit(1);
      }
    }
  } else {
    console.log('  ✓ FERAL is installed');
  }

  if (!scenario) {
    console.log('\n  Available demo scenarios:\n');
    for (const [key, s] of Object.entries(SCENARIOS)) {
      console.log(`    ${key.padEnd(12)} ${s.name}`);
      console.log(`    ${''.padEnd(12)} ${s.desc}`);
      console.log(`    ${''.padEnd(12)} (${s.audience})\n`);
    }

    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    scenario = await new Promise(resolve => {
      rl.question('  Choose a scenario (morning/developer/mesh) or press Enter for interactive: ', answer => {
        rl.close();
        resolve(answer.trim().toLowerCase());
      });
    });
  }

  console.log('\n  🚀 Launching FERAL in demo mode...\n');

  const cmd = scenario
    ? `${python} -m cli.main demo --scenario ${scenario}`
    : `${python} -m cli.main start --demo`;

  const child = spawn(cmd, { shell: true, stdio: 'inherit' });
  child.on('exit', code => process.exit(code || 0));
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
