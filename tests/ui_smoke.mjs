import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

await mkdir('artifacts', { recursive: true });
const env = { ...process.env, PYTHONPATH: 'src' };
const app = spawn('python', ['-m','traceforge','--db','data/ui.db','serve','--port','8741'], {env,stdio:'inherit'});
const staticApp = spawn('python', ['-m','http.server','8742','--bind','127.0.0.1','--directory','docs'], {stdio:'ignore'});
const base = 'http://127.0.0.1:8741';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function ready(url) {
  for(let attempt=0; attempt<100; attempt++) {
    try { if((await fetch(url)).ok) return; } catch {}
    await delay(100);
  }
  throw new Error('Server did not become ready: '+url);
}
let browser;
try {
  await Promise.all([ready(base+'/api/health'),ready('http://127.0.0.1:8742/demo.html')]);
  browser = await chromium.launch();
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByRole('heading',{name:'Agent reliability, measured.'}).waitFor();
  await page.getByRole('button',{name:'Run the offline demo',exact:false}).click();
  await page.waitForFunction(() => document.querySelectorAll('#runs-body tr').length===3 && [...document.querySelectorAll('#runs-body .status')].every(e=>e.textContent==='completed'));
  assert.equal(await page.locator('.metric-value').first().textContent(),'144');
  await page.screenshot({path:'artifacts/dashboard-desktop.png',fullPage:true});
  const runs = await (await fetch(base+'/api/runs')).json();
  const baseline = runs.find(r=>r.config.agent==='scripted-naive'&&!r.config.guardrails);
  const candidate = runs.find(r=>r.config.agent==='scripted-resilient');
  await page.locator('[data-view="scenarios"]').click();
  assert.equal(await page.locator('.scenario-card').count(),16);
  await page.locator('[data-category="security"]').click();
  assert.equal(await page.locator('.scenario-card').count(),4);
  await page.locator('[data-view="compare"]').click();
  await page.locator('#compare-left').selectOption(baseline.id);
  await page.locator('#compare-right').selectOption(candidate.id);
  await page.getByRole('button',{name:'Compare experiments',exact:true}).click();
  await page.locator('.delta').waitFor();
  assert.match(await page.locator('.delta').textContent(),/\+75/);
  await page.screenshot({path:'artifacts/comparison.png',fullPage:true});
  await page.locator('[data-view="overview"]').click();
  await page.locator('[data-run="'+candidate.id+'"]').click();
  await page.locator('.episode-row').filter({hasText:'Committed, but unacknowledged'}).first().click();
  await page.getByRole('button',{name:'Verify & replay offline',exact:false}).waitFor();
  assert.match(await page.locator('#trace-integrity').textContent(),/VERIFIED/);
  await page.getByRole('button',{name:'Verify & replay offline',exact:false}).click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Replay verified'));
  await page.screenshot({path:'artifacts/trace-inspector.png',fullPage:true});
  const exported = await (await fetch(base+'/api/runs/'+candidate.id+'/export')).json();
  assert.equal(exported.episodes.length,48);
  assert.ok(exported.episodes.every(e=>e.events.length>0));
  await page.locator('#new-run').click();
  await page.locator('#run-dialog').waitFor();
  await page.locator('input[name="repetitions"]').fill('1');
  await page.getByRole('button',{name:'Launch experiment',exact:false}).click();
  await page.waitForFunction(()=>!document.querySelector('#run-dialog').open);
  await page.locator('#run-header h2').waitFor();
  const mobile = await browser.newPage({viewport:{width:390,height:844}});
  await mobile.goto(base);
  await mobile.locator('#runs-body tr').first().waitFor();
  assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile page overflows horizontally');
  await mobile.screenshot({path:'artifacts/dashboard-mobile.png',fullPage:true});
  // The generated HTML uses real, compressed records and must hydrate without the API.
  const recorded = await browser.newPage({viewport:{width:1440,height:1000}});
  const unexpected = [];
  recorded.on('request',request=>{if(request.url().includes('/api/'))unexpected.push(request.url());});
  recorded.on('pageerror',error=>errors.push(error.message));
  await recorded.goto('http://127.0.0.1:8742/demo.html');
  await recorded.locator('#runs-body tr').first().waitFor();
  assert.equal(await recorded.locator('#runs-body tr').count(),3);
  await recorded.locator('#runs-body tr').first().click();
  await recorded.locator('.episode-row').first().click();
  await recorded.getByRole('button',{name:'Verify & replay offline',exact:false}).click();
  await recorded.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Recorded replay'));
  assert.equal(unexpected.length,0,'Recorded demo requested a live API');
  await recorded.screenshot({path:'artifacts/recorded-demo.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: live dashboard, demo launch, scenario filtering, paired comparison, trace replay, export, experiment form, mobile width, and API-free recorded demo.');
} catch(error) {
  console.error(error);
  if(browser) {
    for(const context of browser.contexts()) for(const page of context.pages()) {
      try { await page.screenshot({path:'artifacts/failure-'+Date.now()+'.png',fullPage:true}); } catch {}
    }
  }
  process.exitCode=1;
} finally {
  if(browser) await browser.close();
  app.kill('SIGTERM'); staticApp.kill('SIGTERM');
}
