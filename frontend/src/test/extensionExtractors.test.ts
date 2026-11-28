import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';

// Import shared pure CommonJS extractor used by extension/content/content.js
// eslint-disable-next-line @typescript-eslint/no-require-imports
const extractors = require('../../../extension/shared/extractors.js') as {
  detectPortalFromUrl: (host: string, href: string) => string;
  extractJobContextFromDocument: (doc: Document, loc: { hostname: string; href: string }) => {
    url: string;
    portal: string;
    job_title: string;
    company_name: string;
    location: string;
    contact_email: string;
    job_description: string;
  };
};

function makeDoc(html: string): Document {
  const parser = new DOMParser();
  return parser.parseFromString(html, 'text/html');
}

describe('Extension shared portal DOM extractors', () => {
  it('extracts Georgian jobs.ge title, employer, and contact email without falling back to Jobs.GE / Jobs', () => {
    const doc = makeDoc(`
      <html>
        <head><title>Jobs.GE - ვაკანსიები</title></head>
        <body>
          <h1>Jobs.GE</h1>
          <div id="job_view">
            <table class="dtable">
              <tr><td class="dtitle">ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)</td></tr>
              <tr><td>მომწოდებელი: ბანკი ქართუ</td></tr>
              <tr><td>ადგილმდებარეობა: თბილისი</td></tr>
              <tr><td>გამოაგზავნეთ CV მისამართზე <a href="mailto:cv@cartubank.ge">cv@cartubank.ge</a></td></tr>
            </table>
          </div>
        </body>
      </html>
    `);
    const res = extractors.extractJobContextFromDocument(doc, {
      hostname: 'jobs.ge',
      href: 'https://jobs.ge/ge/?view=jobs&id=699001',
    });
    expect(res.portal).toBe('jobs.ge');
    expect(res.job_title).toBe('ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)');
    expect(res.company_name).toBe('ბანკი ქართუ');
    expect(res.contact_email).toBe('cv@cartubank.ge');
    expect(res.company_name.toLowerCase()).not.toBe('jobs');
  });

  it('extracts hr.ge, headhunter.ge, and linkedin.com job metadata accurately', () => {
    const hrDoc = makeDoc(`
      <html><body>
        <h1 class="vacancy-title">Junior Financial Analyst</h1>
        <a href="/company/tbc-bank">TBC Bank</a>
        <div class="vacancy-description">IFRS, Excel, SQL reporting in Tbilisi.</div>
      </body></html>
    `);
    const hrRes = extractors.extractJobContextFromDocument(hrDoc, {
      hostname: 'www.hr.ge',
      href: 'https://www.hr.ge/announcement/12345',
    });
    expect(hrRes.portal).toBe('hr.ge');
    expect(hrRes.job_title).toBe('Junior Financial Analyst');
    expect(hrRes.company_name).toBe('TBC Bank');

    const hhDoc = makeDoc(`
      <html><body>
        <h1 data-qa="vacancy-title">QA Automation Trainee</h1>
        <span data-qa="vacancy-company-name">EPAM Georgia</span>
        <div data-qa="vacancy-description">Playwright and Python testing.</div>
      </body></html>
    `);
    const hhRes = extractors.extractJobContextFromDocument(hhDoc, {
      hostname: 'tbilisi.headhunter.ge',
      href: 'https://tbilisi.headhunter.ge/vacancy/98765',
    });
    expect(hhRes.portal).toBe('headhunter.ge');
    expect(hhRes.job_title).toBe('QA Automation Trainee');
    expect(hhRes.company_name).toBe('EPAM Georgia');

    const liDoc = makeDoc(`
      <html><body>
        <div class="job-details-jobs-unified-top-card__job-title"><h1>QA Engineer</h1></div>
        <div class="job-details-jobs-unified-top-card__company-name"><a href="#">Bolt</a></div>
        <div id="job-details">Remote QA role with Playwright and REST APIs.</div>
      </body></html>
    `);
    const liRes = extractors.extractJobContextFromDocument(liDoc, {
      hostname: 'www.linkedin.com',
      href: 'https://www.linkedin.com/jobs/view/400112233/',
    });
    expect(liRes.portal).toBe('linkedin.com');
    expect(liRes.job_title).toBe('QA Engineer');
    expect(liRes.company_name).toBe('Bolt');
  });

  it('extracts Greenhouse HTML fixture from backend/tests/fixtures/forms', () => {
    const fixturePath = path.resolve(__dirname, '../../../backend/tests/fixtures/forms/greenhouse_sample.html');
    const html = fs.readFileSync(fixturePath, 'utf-8');
    const doc = makeDoc(html);
    const res = extractors.extractJobContextFromDocument(doc, {
      hostname: 'boards.greenhouse.io',
      href: 'https://boards.greenhouse.io/sampleco/jobs/42',
    });
    expect(res.portal).toBe('greenhouse');
    expect(res.job_title.length).toBeGreaterThan(2);
    expect(res.job_description.length).toBeGreaterThan(20);
  });
});
