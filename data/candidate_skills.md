# KLIPY Sticker Search API — QA Case Study

**Portfolio project for a QA Engineer application**  
**Author:** Giorgi Shakiashvili  
**Status:** Test-design starter — execute the cases and add real evidence before presenting this as completed work.

> This is an independent learning/portfolio project based on KLIPY's publicly available developer documentation. It is not an official KLIPY project and is not affiliated with KLIPY. No production credentials or private data are included.

## Objective

Demonstrate a structured QA approach to a REST API that powers sticker discovery. The focus is on turning documented behavior into test scenarios, validating HTTP responses and JSON, checking query-parameter boundaries, and documenting ambiguities without assuming undocumented behavior.

## Documentation

- Official KLIPY API documentation: <https://docs.klipy.com/>
- Sticker API reference: <https://docs.klipy.com/stickers-api>

The current public reference describes sticker search and trending endpoints, including parameters such as `page`, `per_page`, `q`, `locale`, and `content_filter`. It documents `page` with a minimum of `1`, and `per_page` with a documented range of `8` to `50` for the sticker search endpoint. Re-check the live documentation before execution in case the API changes.

## Scope

### In scope

- Valid sticker-search request and response structure
- Required and optional query parameters
- Pagination and `per_page` boundary values
- Locale values and content-filter options documented by the API
- Empty/unknown search queries and malformed parameters
- Missing or invalid app key handling
- Response headers, JSON validity, errors and basic response-time observation
- Clear defect reports and test evidence

### Out of scope

- Load, stress or denial-of-service testing
- Production data or production credentials
- Security penetration testing
- Assertions about relevance, filtering or error behavior where the public specification does not define an exact expected result

## Tools

- Postman for request execution and response assertions
- Browser/API documentation for requirement review
- Git for version control
- Optional: a spreadsheet or Markdown table to record execution results

## Setup

1. Create or access an authorised KLIPY **test** API key through the official developer flow.
2. Import `postman/KLIPY_Sticker_Search_API.postman_collection.json` into Postman.
3. Create an environment with the variables below. Do not commit a real API key.

| Variable | Example / value | Notes |
|---|---|---|
| `base_url` | `https://api.klipy.com` | API host from the official docs |
| `app_key` | `YOUR_TEST_APP_KEY` | Set locally; never commit the real value |
| `query` | `cats` | Search term |
| `page` | `1` | Must be at least 1 according to the reference |
| `per_page` | `24` | Documented range: 8–50 for sticker search |
| `locale` | `us` | Use a supported two-letter country code from the docs |
| `content_filter` | `medium` | Documented options include `off`, `low`, `medium`, and `high` |
| `customer_id` | `qa-portfolio-user-01` | Stable synthetic identifier for testing, if needed |

4. Run the collection against the test environment and keep the request rate within the current test-key limit. The KLIPY quickstart currently states that test keys are limited to 100 API requests per hour; verify this in the live docs before execution.
5. Record actual results in the Execution Results section. Do not add a pass/fail result until the request has actually been run.

## Request under test

```http
GET {{base_url}}/api/v1/{{app_key}}/stickers/search
    ?q={{query}}
    &page={{page}}
    &per_page={{per_page}}
    &locale={{locale}}
    &content_filter={{content_filter}}
```

Postman will send the query parameters as a single URL. The line breaks above are for readability only.

## Test approach

1. **Requirement review:** confirm the current endpoint, parameter definitions, response schema and documented error behavior.
2. **Positive testing:** issue a valid search request and validate the success response against the published schema.
3. **Boundary testing:** check the minimum/maximum supported pagination values and just-outside values.
4. **Negative testing:** omit or corrupt parameters and app-key values. Compare the observed behavior with the documentation; do not assume a specific HTTP status if it is unspecified.
5. **Data validation:** validate required response fields and types against the live schema, and check that returned items are structurally usable by a consuming application.
6. **Evidence:** save sanitized request details, response snippets, timestamps and screenshots where useful. Never expose keys or user data.

## Test scenarios

| ID | Scenario | Test data | Expected result / oracle | Status |
|---|---|---|---|---|
| API-01 | Valid search | `q=cats`, `page=1`, `per_page=24` | Successful response and JSON structure matching the current API specification | Not run |
| API-02 | Minimum page | `page=1` | Request is accepted; response follows documented pagination schema | Not run |
| API-03 | Page below minimum | `page=0` | Validate documented error/validation behavior; if unspecified, record observation and raise a specification question | Not run |
| API-04 | Minimum page size | `per_page=8` | Request is accepted if the current documentation retains this lower bound | Not run |
| API-05 | Maximum page size | `per_page=50` | Request is accepted if the current documentation retains this upper bound | Not run |
| API-06 | Page size below minimum | `per_page=7` | Validate documented boundary handling; do not assume rejection versus clamping without a stated contract | Not run |
| API-07 | Page size above maximum | `per_page=51` | Validate documented boundary handling and capture the actual response | Not run |
| API-08 | Empty query | `q=` | Record whether the API rejects, returns empty results, or applies another documented behavior | Not run |
| API-09 | Unknown search term | Unlikely/unique term | Response remains schema-valid; result semantics should match documented behavior | Not run |
| API-10 | Locale variation | `locale=us`, then another supported code | Response is valid and locale behavior matches the documented contract | Not run |
| API-11 | Content-filter options | `off`, `low`, `medium`, `high` | Each documented value is handled according to the specification | Not run |
| API-12 | Unsupported content-filter value | `content_filter=invalid` | Validate the documented error/validation behavior; log ambiguity if unspecified | Not run |
| API-13 | Missing app key | Empty `app_key` | Request is not treated as a valid authorised request; record exact status and error body | Not run |
| API-14 | Invalid app key | Intentionally invalid test value | Authorisation/access error matches the documented contract | Not run |
| API-15 | Response content type | Valid search | Response content type and JSON body are consistent with the API specification | Not run |
| API-16 | Response-time observation | Repeat a small number of valid requests | Record elapsed time under the test conditions; do not declare a performance failure without an agreed SLA | Not run |

**Important:** API-03, API-06–API-08, API-12 and some error cases are partly specification-discovery tests. Where the documentation does not define a precise response, the correct QA action is to record the behavior and clarify the contract—not invent an expected status code.

## Example Postman assertions

The collection includes basic checks for a successful HTTP response, JSON content type and parseable JSON body. After verifying the current response schema in the official documentation, add assertions for required fields and data types. Avoid tests that pass merely because a status code is 200.

Example starter script for a valid-search request:

```javascript
pm.test("Valid search returns HTTP 200", function () {
  pm.response.to.have.status(200);
});

pm.test("Response declares JSON content", function () {
  pm.expect(pm.response.headers.get("Content-Type") || "")
    .to.include("application/json");
});

pm.test("Response body is valid JSON", function () {
  pm.expect(function () { pm.response.json(); }).to.not.throw();
});

pm.test("Response body is a JSON object", function () {
  pm.expect(pm.response.json()).to.be.an("object");
});
```

## Bug report template

When an issue is reproducible, create a report containing:

- **Title:** concise symptom + affected endpoint/parameter
- **Environment:** test API key type (never the key), date/time, request method and endpoint
- **Preconditions:** relevant variables and setup
- **Steps to reproduce:** numbered, minimal steps
- **Expected result:** quote or reference the relevant specification
- **Actual result:** observed status, sanitized response and headers
- **Impact/severity:** explain the user or integration risk
- **Evidence:** sanitized Postman request/response or screenshot
- **Regression checks:** related parameters/endpoints to retest

Do not report an undocumented behavior as a confirmed defect until the contract is clarified.

## Execution results

This starter version has **not been executed against the API**. Populate this section after running the requests:

| Date | Environment | Tests run | Passed | Failed | Blocked | Notes |
|---|---|---:|---:|---:|---:|---|
| To be completed after execution | Test key | — | — | — | — | No results claimed yet |

Attach sanitized evidence or add an `evidence/` folder after execution. Keep real API keys, secrets, and personal data out of Git.

## What this case study demonstrates

- Requirement-based test design rather than guessing expected behavior
- Positive, negative and boundary-value test coverage
- API request/response validation with Postman
- Attention to pagination, localization and filtering options
- Defect communication, evidence handling and honest reporting of limitations

## Suggested next steps

- [ ] Verify the endpoint and response contract in the current official docs.
- [ ] Run all valid requests with an authorised test key.
- [ ] Run negative and boundary tests at a safe request rate.
- [ ] Add actual execution results and sanitised evidence.
- [ ] Add a concise summary of confirmed findings and open specification questions.
- [ ] Only after completion, link this repository from the CV as a portfolio project.
