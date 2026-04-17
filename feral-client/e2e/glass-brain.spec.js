import { test, expect } from '@playwright/test';

test.describe('Glass Brain', () => {

  test.skip(!process.env.FERAL_E2E, 'Set FERAL_E2E=1 to run E2E tests against a running brain');

  test('loads and shows onboarding when no devices', async ({ page }) => {
    await page.goto('http://localhost:9090/glass');
    await expect(page.getByText('FERAL Glass Brain')).toBeVisible();
  });

  test('mode toggle switches event filter', async ({ page }) => {
    await page.goto('http://localhost:9090/glass');
    const commsBtn = page.getByRole('button', { name: 'Comms' });
    await commsBtn.click();
    await expect(commsBtn).toHaveCSS('color', 'rgb(6, 182, 212)');
  });

  test('all mode buttons are rendered', async ({ page }) => {
    await page.goto('http://localhost:9090/glass');
    await expect(page.getByRole('button', { name: 'All' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Comms' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Devices' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'LLM' })).toBeVisible();
  });

  test('legend is visible', async ({ page }) => {
    await page.goto('http://localhost:9090/glass');
    await expect(page.getByText('Brain core')).toBeVisible();
    await expect(page.getByText('Memory particles')).toBeVisible();
  });

  test('stats overlay shows session and device counts', async ({ page }) => {
    await page.goto('http://localhost:9090/glass');
    await expect(page.getByText('Sessions:')).toBeVisible();
    await expect(page.getByText('Devices:')).toBeVisible();
  });
});
