import { TestBed } from '@angular/core/testing';
import { HttpClient, HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { AuthInterceptor } from './auth.interceptor';

const TOKEN_KEY = 'vigil_token';

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpTesting: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpTesting = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpTesting.verify();
    localStorage.clear();
  });

  it('attaches the Authorization header when a token is stored', () => {
    localStorage.setItem(TOKEN_KEY, 'tok-123');
    http.get('/api/v1/endpoints/').subscribe();
    const req = httpTesting.expectOne('/api/v1/endpoints/');
    expect(req.request.headers.get('Authorization')).toBe('Token tok-123');
    req.flush({});
  });

  it('sends no Authorization header when no token is stored', () => {
    http.get('/api/v1/endpoints/').subscribe();
    const req = httpTesting.expectOne('/api/v1/endpoints/');
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush({});
  });

  it('clears the token and redirects to /login on a 401 response', () => {
    localStorage.setItem(TOKEN_KEY, 'stale-token');
    const spy = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    http.get('/api/v1/endpoints/').subscribe({ error: () => {} });
    const req = httpTesting.expectOne('/api/v1/endpoints/');
    req.flush({ detail: 'Token has expired.' }, { status: 401, statusText: 'Unauthorized' });

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(spy).toHaveBeenCalledWith(['/login']);
  });

  it('propagates the error to the caller after handling a 401', () => {
    localStorage.setItem(TOKEN_KEY, 'stale-token');
    vi.spyOn(router, 'navigate').mockResolvedValue(true);
    let caughtStatus: number | undefined;

    http.get('/api/v1/endpoints/').subscribe({
      error: (err) => (caughtStatus = err.status),
    });
    httpTesting
      .expectOne('/api/v1/endpoints/')
      .flush({}, { status: 401, statusText: 'Unauthorized' });

    expect(caughtStatus).toBe(401);
  });

  it('does not log the user out on a non-401 error', () => {
    localStorage.setItem(TOKEN_KEY, 'tok-123');
    const spy = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    http.get('/api/v1/endpoints/').subscribe({ error: () => {} });
    httpTesting
      .expectOne('/api/v1/endpoints/')
      .flush({}, { status: 500, statusText: 'Server Error' });

    expect(localStorage.getItem(TOKEN_KEY)).toBe('tok-123');
    expect(spy).not.toHaveBeenCalled();
  });
});
