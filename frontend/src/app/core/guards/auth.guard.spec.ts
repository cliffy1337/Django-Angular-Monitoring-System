import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, Router } from '@angular/router';
import { AuthGuard, GuestGuard } from './auth.guard';

const TOKEN_KEY = 'vigil_token';

describe('AuthGuard', () => {
  let guard: AuthGuard;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideRouter([])],
    });
    guard = TestBed.inject(AuthGuard);
    router = TestBed.inject(Router);
  });

  afterEach(() => localStorage.clear());

  it('allows navigation when a token is stored', () => {
    localStorage.setItem(TOKEN_KEY, 'tok');
    expect(guard.canActivate()).toBe(true);
  });

  it('blocks navigation and redirects to /login when no token', () => {
    const spy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(guard.canActivate()).toBe(false);
    expect(spy).toHaveBeenCalledWith(['/login']);
  });
});

describe('GuestGuard', () => {
  let guard: GuestGuard;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideRouter([])],
    });
    guard = TestBed.inject(GuestGuard);
    router = TestBed.inject(Router);
  });

  afterEach(() => localStorage.clear());

  it('allows navigation when no token is stored', () => {
    expect(guard.canActivate()).toBe(true);
  });

  it('blocks navigation and redirects to /dashboard when already authenticated', () => {
    localStorage.setItem(TOKEN_KEY, 'tok');
    const spy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(guard.canActivate()).toBe(false);
    expect(spy).toHaveBeenCalledWith(['/dashboard']);
  });
});
