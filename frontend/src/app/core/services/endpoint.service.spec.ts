import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { EndpointService, Endpoint } from './endpoint.service';

const API_URL = '/api/v1/endpoints/';

const mockEndpoint: Endpoint = {
  id: 'uuid-1',
  name: 'My Site',
  url: 'https://example.com',
  interval_minutes: 5,
  is_active: true,
  last_alert_sent_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('EndpointService', () => {
  let service: EndpointService;
  let httpTesting: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(EndpointService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpTesting.verify());

  describe('list()', () => {
    it('sends a GET request to the endpoints API', () => {
      service.list().subscribe();
      const req = httpTesting.expectOne(API_URL);
      expect(req.request.method).toBe('GET');
      req.flush({ count: 0, next: null, previous: null, results: [] });
    });

    it('unwraps and returns the results array from the paginated response', () => {
      let result: Endpoint[] | undefined;
      service.list().subscribe(r => (result = r));
      httpTesting
        .expectOne(API_URL)
        .flush({ count: 1, next: null, previous: null, results: [mockEndpoint] });
      expect(result).toEqual([mockEndpoint]);
    });
  });

  describe('create()', () => {
    it('sends a POST request with the endpoint payload', () => {
      const payload = { name: 'My Site', url: 'https://example.com', interval_minutes: 5 };
      service.create(payload).subscribe();
      const req = httpTesting.expectOne(API_URL);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual(payload);
      req.flush(mockEndpoint);
    });
  });
});
