import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { AuthService } from './auth.service';

const TOKEN_KEY = 'vigil_token';

describe('AuthService', () => {
  let service: AuthService;
  let router: Router;
  let httpTesting: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    service = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTesting.verify();
    localStorage.clear();
  });

  describe('isAuthenticated()', () => {
    it('returns false when no token is stored', () => {
      expect(service.isAuthenticated()).toBe(false);
    });

    it('returns true when a token is present in localStorage', () => {
      localStorage.setItem(TOKEN_KEY, 'abc123');
      expect(service.isAuthenticated()).toBe(true);
    });
  });

  describe('login()', () => {
    it('stores the token in localStorage on success', () => {
      service.login('alice', 'secret').subscribe();
      const req = httpTesting.expectOne('/api/auth/token/');
      expect(req.request.method).toBe('POST');
      req.flush({ token: 'tok-abc' });
      expect(localStorage.getItem(TOKEN_KEY)).toBe('tok-abc');
    });

    it('makes isAuthenticated() return true after a successful login', () => {
      service.login('alice', 'secret').subscribe();
      httpTesting.expectOne('/api/auth/token/').flush({ token: 'tok-xyz' });
      expect(service.isAuthenticated()).toBe(true);
    });
  });

  describe('logout()', () => {
    beforeEach(() => {
      vi.spyOn(router, 'navigate').mockResolvedValue(true);
    });

    it('removes the token from localStorage', () => {
      localStorage.setItem(TOKEN_KEY, 'abc123');
      service.logout();
      expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    });

    it('makes isAuthenticated() return false', () => {
      localStorage.setItem(TOKEN_KEY, 'abc123');
      service.logout();
      expect(service.isAuthenticated()).toBe(false);
    });

    it('emits false on isAuthenticated$', () => {
      localStorage.setItem(TOKEN_KEY, 'abc123');
      const emitted: boolean[] = [];
      service.isAuthenticated$.subscribe(v => emitted.push(v));
      service.logout();
      expect(emitted[emitted.length - 1]).toBe(false);
    });

    it('navigates to /login', () => {
      service.logout();
      expect(router.navigate).toHaveBeenCalledWith(['/login']);
    });
  });
});
