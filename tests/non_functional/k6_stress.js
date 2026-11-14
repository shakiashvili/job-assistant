import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m', target: 40 },
    { duration: '15s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<600'],
    http_req_failed: ['rate<0.02'],
  },
};

export default function () {
  const healthRes = http.get(`${BASE_URL}/health`);
  check(healthRes, {
    'health status 200': (r) => r.status === 200,
  });

  const jobsRes = http.get(`${BASE_URL}/api/jobs?page=1&limit=12`);
  check(jobsRes, {
    'jobs status 200': (r) => r.status === 200,
    'jobs JSON returned': (r) => {
      try {
        const body = r.json();
        return body && Array.isArray(body.items);
      } catch (_e) {
        return false;
      }
    },
  });

  const profileRes = http.get(`${BASE_URL}/api/profile`);
  check(profileRes, {
    'profile status 200': (r) => r.status === 200,
  });

  sleep(0.5);
}
