const puppeteer = require('puppeteer-core');
const core = require('@actions/core');

async function run() {
  const url = core.getInput('url');
  
  try {
    const browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();
    
    // Load the page
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
    
    // Wait a bit for any sleep banner
    await page.waitForTimeout(2000);
    
    // Check for and click "wake up" button (common selectors)
    const wakeButton = await page.$('button:has-text("Wake up"), [data-testid="stAppViewContainer"] button, .stAlert button');
    if (wakeButton) {
      console.log('Sleep detected—waking up...');
      await wakeButton.click();
      await page.waitForTimeout(5000);  // Wait for wake
    } else {
      console.log('App is already awake.');
    }
    
    // Final load check
    await page.screenshot({ path: 'ping-screenshot.png', fullPage: true });  # Optional: Log for debug
    console.log('Ping successful—app is active.');
    
    await browser.close();
    core.setOutput('status', 'awake');
  } catch (error) {
    console.error(`Ping failed: ${error.message}`);
    core.setFailed(error.message);
  }
}

run();
